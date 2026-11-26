"""Corpus loading and metadata utilities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Iterator


def find_parsed_elements(repo_root: Path) -> Path:
    candidates = [
        repo_root / "data" / "parsed_elements.json",
        Path("data") / "parsed_elements.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Could not locate data/parsed_elements.json")


def load_corpus(repo_root: Path) -> list[dict]:
    path = find_parsed_elements(repo_root)
    with path.open("r", encoding="utf-8") as handle:
        elements = json.load(handle)

    cleaned = []
    for element in elements:
        content = str(element.get("content", "")).strip()
        if not content:
            continue
        item = dict(element)
        item["content"] = content
        item["modality"] = str(item.get("modality", "text")).lower()
        item["page_or_slide"] = int(item.get("page_or_slide", 0) or 0)
        cleaned.append(item)
    return cleaned

