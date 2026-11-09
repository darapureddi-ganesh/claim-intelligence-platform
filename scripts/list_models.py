"""List the Google AI models your key / project can call, grouped by family.

    GEMINI_API_KEY=... python scripts/list_models.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.gemini.client import get_client  # noqa: E402
from src.gemini.config import get_google_ai_settings  # noqa: E402

FAMILIES = {
    "Gemini (text/multimodal)": lambda n: n.startswith("gemini") and not any(
        k in n for k in ("live", "image", "banana", "tts", "omni", "embedding", "robotics")),
    "Gemini Live": lambda n: "live" in n,
    "Nano Banana / image": lambda n: "image" in n or "banana" in n,
    "Gemini Omni": lambda n: "omni" in n,
    "Gemma": lambda n: n.startswith("gemma"),
    "Lyria": lambda n: n.startswith("lyria"),
}


def main() -> None:
    settings = get_google_ai_settings()
    names = sorted(m.name.split("/")[-1] for m in get_client().models.list())
    for family, match in FAMILIES.items():
        hits = [n for n in names if match(n)]
        print(f"\n{family}:")
        for n in hits:
            print(f"  {n}")
    print("\nConfigured:", settings.public_summary()["models"])


if __name__ == "__main__":
    main()
