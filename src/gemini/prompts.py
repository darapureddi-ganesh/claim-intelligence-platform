"""Loads system prompts from /prompts.

The prompts live as plain Markdown so they can be pasted straight into Google AI
Studio, iterated there, and copied back without touching Python.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    path = PROMPT_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8").strip()
