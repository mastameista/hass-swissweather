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


def test_every_icon_belongs_to_a_translated_entity():
    """icons.json is keyed by translation_key; a typo would silently drop the icon."""
    icons = _load("icons.json")["entity"]
    entities = _load("strings.json")["entity"]
    for platform, keys in icons.items():
        assert set(keys) <= set(entities[platform]), (platform, set(keys) - set(entities[platform]))


def test_every_config_flow_selector_is_translated():
    """The fixed dropdown entries (no station, search again) need a translation."""
    source = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
    selectors = _load("strings.json")["selector"]
    used = set(re.findall(r'translation_key="(\w+)"', source))
    assert used == set(selectors), (used, set(selectors))

    fixed_values = set(re.findall(r'^[A-Z_]+_OPTION = "(\w+)"', source, re.M))
    translated = {value for sel in selectors.values() for value in sel["options"]}
    assert fixed_values == translated, (fixed_values, translated)


def test_translation_keys_follow_the_hassfest_pattern():
    """hassfest rejects keys outside [a-z0-9-_] or starting/ending with - or _."""
    valid = re.compile(r"^[a-z0-9]([a-z0-9_-]*[a-z0-9])?$")

    def keys(node: dict):
        for key, value in node.items():
            yield key
            if isinstance(value, dict):
                yield from keys(value)

    strings = _load("strings.json")
    checked = {k for section in ("selector", "exceptions", "entity", "issues") for k in keys(strings.get(section, {}))}
    bad = sorted(k for k in checked if not valid.match(k))
    assert not bad, bad
