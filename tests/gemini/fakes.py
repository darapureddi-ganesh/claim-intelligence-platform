"""A stand-in for google.genai.Client so tests never call the network."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable


class FakeModels:
    def __init__(self, handler: Callable[[str, Any, Any], Any]) -> None:
        self._handler = handler
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, *, model: str, contents: Any, config: Any = None) -> Any:
        self.calls.append({"model": model, "contents": contents, "config": config})
        return self._handler(model, contents, config)


class FakeClient:
    def __init__(self, handler: Callable[[str, Any, Any], Any]) -> None:
        self.models = FakeModels(handler)


def structured(obj: Any) -> Any:
    return SimpleNamespace(parsed=obj, text=obj.model_dump_json(), candidates=[])


def text(value: str) -> Any:
    return SimpleNamespace(parsed=None, text=value, candidates=[])


def image(data: bytes, note: str = "") -> Any:
    blob = SimpleNamespace(data=data, mime_type="image/png")
    parts = [SimpleNamespace(inline_data=blob, text=None)]
    if note:
        parts.append(SimpleNamespace(inline_data=None, text=note))
    return SimpleNamespace(parsed=None, text=note,
                           candidates=[SimpleNamespace(content=SimpleNamespace(parts=parts))])
