"""Task-conditioned projection of a static UI map."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")


def tokens(text: str) -> set[str]:
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    raw = {part.lower() for part in TOKEN_RE.findall(expanded) if len(part) >= 3}
    split = {
        piece.lower()
        for part in raw
        for piece in re.split(r"[_./:-]+", part)
        if len(piece) >= 3
    }
    return raw | split


def _records(value: Any, prefix: str = "root") -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if isinstance(value, dict):
        scalar = {key: item for key, item in value.items() if not isinstance(item, (dict, list))}
        if scalar:
            rows.append((prefix, json.dumps(scalar, ensure_ascii=False, default=str)))
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                rows.extend(_records(item, f"{prefix}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            rows.extend(_records(item, f"{prefix}[{index}]"))
    else:
        rows.append((prefix, str(value)))
    return rows


def project_ui_map(path: Path, instruction: str, *, max_chars: int = 18000) -> str:
    """Return a bounded UI-map excerpt without requiring a fixed upstream schema."""
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = _records(data)
    query = tokens(instruction)
    structural = {"activity", "fragment", "dialog", "menu", "transition", "effect", "summary"}

    ranked: list[tuple[float, str]] = []
    for location, value in rows:
        row_tokens = tokens(location + " " + value)
        overlap = len(query & row_tokens)
        structure_score = len(structural & row_tokens) * 0.35
        score = overlap * 3.0 + structure_score
        ranked.append((score, f"{location}: {value}"))

    # Keep a small structural prefix even when lexical overlap is weak, then add
    # the most task-relevant records. This prevents exact-string retrieval from
    # erasing the map skeleton.
    selected: list[str] = []
    seen: set[str] = set()
    for _score, row in ranked[:80] + sorted(ranked, key=lambda item: item[0], reverse=True):
        if row in seen:
            continue
        seen.add(row)
        if sum(len(item) + 1 for item in selected) + len(row) > max_chars:
            break
        selected.append(row)
    return "\n".join(selected)
