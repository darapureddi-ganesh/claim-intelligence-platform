"""Gemini Live bridge: tool calls run the real pipeline, audio/transcripts are relayed."""

import asyncio
import base64
from contextlib import asynccontextmanager
from types import SimpleNamespace

from src.gemini.config import GoogleAISettings
from src.gemini.live import build_live_config, run_live_bridge


def _matcher(spoken):
    import re
    return "HC-STD-2024" if re.sub(r"[^A-Z0-9]", "", spoken.upper()) == "HCSTD2024" else None


class FakeWS:
    def __init__(self, incoming):
        self.incoming = list(incoming)
        self.sent = []

    async def send_json(self, m):
        self.sent.append(m)

    async def receive_json(self):
        while not self.incoming:
            await asyncio.sleep(0.01)
            if any(m["type"] == "claim" for m in self.sent):
                return {"type": "stop"}
        return self.incoming.pop(0)


class FakeSession:
    def __init__(self):
        self.audio_in, self.tool_responses = [], []
        self._turns = [
            [SimpleNamespace(tool_call=None, server_content=SimpleNamespace(
                interrupted=False, input_transcription=SimpleNamespace(text="मेरी कार"),
                output_transcription=SimpleNamespace(text="पॉलिसी नंबर बताइए"),
                model_turn=SimpleNamespace(parts=[SimpleNamespace(
                    inline_data=SimpleNamespace(data=b"\x01\x00"))])))],
            [SimpleNamespace(server_content=None, tool_call=SimpleNamespace(function_calls=[
                SimpleNamespace(id="c1", name="check_policy", args={"policy_id": "hc-std 2024"}),
                SimpleNamespace(id="c2", name="submit_fnol", args={"policy_id": "HC-STD-2024"}),
            ]))],
        ]

    async def send_realtime_input(self, **kw):
        self.audio_in.append(kw)

    async def send_tool_response(self, function_responses):
        self.tool_responses.extend(function_responses)

    async def receive(self):
        if self._turns:
            for m in self._turns.pop(0):
                yield m
        else:
            await asyncio.sleep(0.05)


class FakeLiveClient:
    def __init__(self, session):
        @asynccontextmanager
        async def connect(model, config):
            self.model, self.config = model, config
            yield session
        self.aio = SimpleNamespace(live=SimpleNamespace(connect=connect))


def test_live_bridge_relays_and_files_claim():
    session = FakeSession()
    client = FakeLiveClient(session)
    ws = FakeWS([{"type": "audio", "data": base64.b64encode(b"\x00\x00").decode()}])
    submitted = []

    async def submit(args):
        submitted.append(args)
        return {"ok": True, "claim_id": "abc", "assigned_queue": "standard",
                "coverage_status": "COVERED", "clauses": ["7.2"]}

    settings = GoogleAISettings(gemini_api_key="k")
    asyncio.run(asyncio.wait_for(
        run_live_bridge(ws, client, submit, _matcher, settings), 5))

    types_sent = [m["type"] for m in ws.sent]
    assert types_sent[0] == "ready"
    assert {"transcript", "audio", "claim"} <= set(types_sent)
    assert submitted == [{"policy_id": "HC-STD-2024"}]
    names = {r.name: r.response for r in session.tool_responses}
    assert names["check_policy"] == {"policy_id": "HC-STD-2024", "on_file": True}
    assert names["submit_fnol"]["claim_id"] == "abc"
    assert session.audio_in[0]["audio"].mime_type == "audio/pcm;rate=16000"
    assert client.model == settings.gemini_live_model


def test_live_config_declares_tools_and_audio():
    cfg = build_live_config(GoogleAISettings(gemini_api_key="k"))
    names = [f.name for f in cfg.tools[0].function_declarations]
    assert names == ["check_policy", "submit_fnol"]
    assert "Today's date" in cfg.system_instruction
