"""Translation files stay complete and in sync with the code."""

from __future__ import annotations

import json
from pathlib import Path
import re

COMPONENT = Path(__file__).parent.parent / "custom_components" / "swissweather"


def _load(name: str) -> dict:
    return json.loads((COMPONENT / name).read_text(encoding="utf-8"))


def _leaf_paths(node: dict, prefix: str = "") -> set[str]:
    paths: set[str] = set()
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        paths |= _leaf_paths(value, path) if isinstance(value, dict) else {path}
    return paths


def test_every_language_has_the_same_keys_as_strings_json():
    expected = _leaf_paths(_load("strings.json"))
    for language in ("en", "de"):
        actual = _leaf_paths(_load(f"translations/{language}.json"))
        assert actual == expected, (
            language,
            sorted(expected - actual),
            sorted(actual - expected),
        )


def test_every_raised_translation_key_has_a_message():
    used = set()
    for module in COMPONENT.glob("*.py"):
        source = module.read_text(encoding="utf-8")
        for block in re.findall(r"raise \w+\((.*?)\)", source, re.S):
            used |= set(re.findall(r'translation_key="(\w+)"', block))

    assert used, "expected translated exceptions in the integration"
    assert used <= set(_load("strings.json")["exceptions"])
