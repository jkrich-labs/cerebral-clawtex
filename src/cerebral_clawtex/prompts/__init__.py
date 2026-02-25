from __future__ import annotations

import importlib.resources


def load_prompt(filename: str) -> str:
    """Load a prompt template from the prompts package via importlib.resources."""
    return importlib.resources.files("cerebral_clawtex.prompts").joinpath(filename).read_text(encoding="utf-8")
