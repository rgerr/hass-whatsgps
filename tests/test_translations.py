"""Vertalingen: dezelfde sleutels in strings.json, en en nl; geen URL's (eis van hassfest)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

BASE = Path(__file__).resolve().parents[1] / "custom_components" / "whatsgps"
FILES = ["strings.json", "translations/en.json", "translations/nl.json"]
URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)


def _load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((BASE / name).read_text(encoding="utf-8"))
    return data


def _leaves(node: Any, path: str = "") -> dict[str, str]:
    if isinstance(node, dict):
        out: dict[str, str] = {}
        for key, value in node.items():
            out.update(_leaves(value, f"{path}.{key}" if path else key))
        return out
    return {path: str(node)}


def test_english_translation_equals_strings() -> None:
    assert _load("strings.json") == _load("translations/en.json")


def test_dutch_has_the_same_keys() -> None:
    assert set(_leaves(_load("translations/nl.json"))) == set(_leaves(_load("strings.json")))


@pytest.mark.parametrize("name", FILES)
def test_no_urls_in_texts(name: str) -> None:
    offending = {key: text for key, text in _leaves(_load(name)).items() if URL_RE.search(text)}
    assert offending == {}


@pytest.mark.parametrize("name", FILES)
def test_placeholders_match_english(name: str) -> None:
    english = _leaves(_load("strings.json"))
    for key, text in _leaves(_load(name)).items():
        assert set(re.findall(r"\{(\w+)\}", text)) == set(re.findall(r"\{(\w+)\}", english[key])), key
