"""Gemini Live: a claimant phones in a claim, in their own language.

Browser  ⇄  WebSocket /api/live/fnol (Cloud Run)  ⇄  Gemini Live API

The API key / service account never reaches the browser. When the agent has
collected enough, it calls the `submit_fnol` tool; we run the real triage
pipeline and hand the result back so the agent can read out the claim
number and next step. The agent is instructed never to promise approval.

Wire protocol (JSON text frames):
  client → server  {"type":"audio","data":<b64 PCM16 mono 16 kHz>}
                   {"type":"text","text":"..."}           typed fallback
                   {"type":"stop"}
  server → client  {"type":"ready"} | {"type":"audio","data":<b64 PCM16 24 kHz>}
                   {"type":"transcript","role":"user"|"model","text":"..."}
                   {"type":"claim","result":{...}} | {"type":"interrupted"}
                   {"type":"error","message":"..."}
"""

from __future__ import annotations

import asyncio
import base64
from datetime import date
from typing import Any, Awaitable, Callable

import structlog

from src.gemini.config import GoogleAISettings, get_google_ai_settings
from src.gemini.prompts import load_prompt

logger = structlog.get_logger(__name__)

SubmitFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
PolicyMatchFn = Callable[[str], "str | None"]  # spoken id -> canonical id

SUBMIT_FNOL_SCHEMA = {
    "type": "object",
    "properties": {
        "policy_id": {"type": "string", "description": "Policy number as spoken, letters+digits"},
        "insured_name": {"type": "string"},
        "claim_type": {
            "type": "string",
            "enum": ["motor", "health", "property", "life", "marine", "other"],
        },
        "amount_claimed_inr": {"type": "number", "description": "Estimated amount in rupees"},
        "incident_date": {"type": "string", "description": "YYYY-MM-DD"},
        "incident_location": {"type": "string"},
        "language": {"type": "string", "description": "ISO 639-1 code the caller spoke"},
        "narrative_original": {"type": "string", "description": "What happened, caller's words"},
        "narrative_english": {"type": "string", "description": "Faithful English translation"},
    },
    "required": ["policy_id", "claim_type", "amount_claimed_inr", "incident_date",
                 "narrative_english", "language"],
}


def build_live_config(settings: GoogleAISettings) -> Any:
    from google.genai import types

    return types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        system_instruction=(
            f"{load_prompt('live_fnol_agent')}\n\nToday's date: {date.today().isoformat()}"
        ),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=settings.gemini_live_voice
                )
            )
        ),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        tools=[
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name="check_policy",
                        description="Check whether a policy number is on file before filing.",
                        parameters_json_schema={
                            "type": "object",
                            "properties": {"policy_id": {"type": "string"}},
                            "required": ["policy_id"],
                        },
                    ),
                    types.FunctionDeclaration(
                        name="submit_fnol",
                        description=(
                            "File the first notice of loss once the caller has confirmed the "
                            "details. Returns the claim number and next step."
                        ),
                        parameters_json_schema=SUBMIT_FNOL_SCHEMA,
                    ),
                ]
            )
        ],
    )


async def run_live_bridge(
    websocket: Any,
    client: Any,
    submit: SubmitFn,
    match_policy: PolicyMatchFn,
    settings: GoogleAISettings | None = None,
) -> None:
    """Bridge one browser WebSocket to one Gemini Live session until either side closes."""
    from google.genai import types

    settings = settings or get_google_ai_settings()
    config = build_live_config(settings)

    async with client.aio.live.connect(model=settings.gemini_live_model, config=config) as session:
        await websocket.send_json({"type": "ready", "model": settings.gemini_live_model})

        async def browser_to_gemini() -> None:
            while True:
                msg = await websocket.receive_json()
                kind = msg.get("type")
                if kind == "audio":
                    await session.send_realtime_input(
                        audio=types.Blob(
                            data=base64.b64decode(msg["data"]), mime_type="audio/pcm;rate=16000"
                        )
                    )
                elif kind == "text" and msg.get("text"):
                    await session.send_realtime_input(text=msg["text"])
                elif kind == "stop":
                    await session.send_realtime_input(audio_stream_end=True)
                    return

        async def gemini_to_browser() -> None:
            while True:
                async for message in session.receive():
                    if message.tool_call:
                        responses = []
                        for fc in message.tool_call.function_calls or []:
                            result = await _handle_tool(fc.name, fc.args or {}, submit,
                                                        match_policy)
                            if fc.name == "submit_fnol":
                                await websocket.send_json({"type": "claim", "result": result})
                            responses.append(
                                types.FunctionResponse(id=fc.id, name=fc.name, response=result)
                            )
                        await session.send_tool_response(function_responses=responses)
                        continue

                    sc = message.server_content
                    if sc is None:
                        continue
                    if sc.interrupted:
                        await websocket.send_json({"type": "interrupted"})
                    if sc.input_transcription and sc.input_transcription.text:
                        await websocket.send_json({"type": "transcript", "role": "user",
                                                   "text": sc.input_transcription.text})
                    if sc.output_transcription and sc.output_transcription.text:
                        await websocket.send_json({"type": "transcript", "role": "model",
                                                   "text": sc.output_transcription.text})
                    if sc.model_turn:
                        for part in sc.model_turn.parts or []:
                            inline = part.inline_data
                            if inline is not None and inline.data:
                                await websocket.send_json({
                                    "type": "audio",
                                    "data": base64.b64encode(inline.data).decode(),
                                })

        tasks = [asyncio.create_task(browser_to_gemini()), asyncio.create_task(gemini_to_browser())]
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            for t in done:
                exc = t.exception()
                if exc and not _is_disconnect(exc):
                    raise exc
        finally:
            for t in tasks:
                t.cancel()


async def _handle_tool(
    name: str, args: dict[str, Any], submit: SubmitFn, match_policy: PolicyMatchFn
) -> dict[str, Any]:
    try:
        if name == "check_policy":
            spoken = str(args.get("policy_id", ""))
            match = match_policy(spoken)
            return {"policy_id": match or spoken.strip().upper(), "on_file": match is not None}
        if name == "submit_fnol":
            return await submit(args)
        return {"ok": False, "error": f"unknown tool {name}"}
    except Exception as exc:  # the caller hears a polite error, not a crash
        logger.exception("live_tool_failed", tool=name)
        return {"ok": False, "error": str(exc)}


def _is_disconnect(exc: BaseException) -> bool:
    return type(exc).__name__ in {"WebSocketDisconnect", "ConnectionClosedOK", "CancelledError"}
