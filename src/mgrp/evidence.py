"""Budgeted local repository evidence tracing.

This is intentionally not a whole-repository graph.  It builds a lightweight
line/symbol index once and returns short action-relevant slices for explicit
UI-map gaps.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .context import tokens
from .models import EvidenceSnippet, Gap


SOURCE_SUFFIXES = {
    ".java", ".kt", ".kts", ".xml", ".gradle", ".properties", ".json"
}
SKIP_PARTS = {".git", "build", ".gradle", "node_modules", "generated"}
ACTION_MARKERS = {
    "onclick", "setonclicklistener", "onoptionsitemselected", "oncreateoptionsmenu",
    "intent", "startactivity", "fragment", "dialog", "setpositivebutton", "save",
    "insert", "update", "delete", "preference", "menu", "finish", "navigate",
}
MGRP_MARKERS = {
    "missing_commit": {"save", "confirm", "done", "positive", "insert", "update", "finish"},
    "missing_trigger": {"menu", "onclick", "listener", "options", "item", "navigate"},
    "missing_transition": {"intent", "startactivity", "fragment", "dialog", "show", "navigate"},
    "missing_effect": {"insert", "update", "delete", "save", "preference", "database"},
    "ambiguous_scope": {"preference", "config", "database", "global", "event", "update"},
    "missing_target": {"id", "title", "text", "hint", "layout", "menu"},
    "missing_verification": {"refresh", "update", "query", "load", "result"},
}


@dataclass(frozen=True)
class IndexedLine:
    path: str
    line: int
    text: str
    terms: frozenset[str]


class LocalEvidenceIndex:
    def __init__(
        self,
        root: Path,
        *,
        max_files: int = 12000,
        max_file_bytes: int = 2_000_000,
    ) -> None:
        self.root = root.resolve()
        self.max_files = max_files
        self.max_file_bytes = max_file_bytes
        self.lines: list[IndexedLine] = []
        self.file_lines: dict[str, list[str]] = {}
        self.files_indexed = 0
        self._build()

    def _build(self) -> None:
        for path in sorted(self.root.rglob("*")):
            if self.files_indexed >= self.max_files:
                break
            if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
                continue
            if any(part.lower() in SKIP_PARTS for part in path.parts):
                continue
            try:
                if path.stat().st_size > self.max_file_bytes:
                    continue
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            relative = path.relative_to(self.root).as_posix()
            self.files_indexed += 1
            source_lines = content.splitlines()
            self.file_lines[relative] = source_lines
            path_terms = tokens(relative)
            for number, text in enumerate(source_lines, 1):
                stripped = text.strip()
                if not stripped:
                    continue
                self.lines.append(IndexedLine(relative, number, stripped, frozenset(tokens(stripped) | path_terms)))

    def search(self, gap: Gap, *, max_results: int = 8, global_query: str = "") -> list[EvidenceSnippet]:
        query = tokens(" ".join((*gap.query_terms, gap.description, *gap.preferred_artifacts, global_query)))
        gap_markers = MGRP_MARKERS.get(gap.gap_type, set())
        scored: list[tuple[float, IndexedLine]] = []
        for row in self.lines:
            overlap = len(query & row.terms)
            if overlap == 0:
                continue
            marker_bonus = len(ACTION_MARKERS & row.terms) * 0.75
            gap_bonus = len(gap_markers & row.terms) * 2.0
            xml_bonus = 0.6 if row.path.endswith(".xml") and ({"menu", "title", "id"} & row.terms) else 0.0
            default_resource_bonus = 1.0 if "/res/values/" in f"/{row.path}" else 0.0
            localized_penalty = -1.5 if re.search(r"/res/values-[^/]+/", f"/{row.path}") else 0.0
            exact_bonus = 0.0
            lowered = row.text.lower()
            for term in query:
                if len(term) >= 5 and term in lowered:
                    exact_bonus += 0.15
            scored.append((overlap * 2.0 + marker_bonus + gap_bonus + xml_bonus + default_resource_bonus + localized_penalty + exact_bonus, row))

        # Follow resource identifiers discovered in the strongest lexical hits.
        # This produces the short Android chain menu/layout -> R.id usage ->
        # handler without constructing a whole-repository graph.
        seed_ids: set[str] = set()
        for _score, row in sorted(scored, key=lambda item: item[0], reverse=True)[:60]:
            for identifier in re.findall(r"(?:R\.id\.|@\+?id/)([A-Za-z0-9_]+)", row.text):
                if tokens(identifier) & query:
                    seed_ids.add(identifier)
        if seed_ids:
            scored_rows = {(row.path, row.line) for _score, row in scored}
            for row in self.lines:
                if (row.path, row.line) in scored_rows:
                    continue
                if any(re.search(rf"(?:R\.id\.|@\+?id/){re.escape(identifier)}\b", row.text) for identifier in seed_ids):
                    scored.append((0.0, row))
            boosted: list[tuple[float, IndexedLine]] = []
            for score, row in scored:
                identifier_hits = sum(
                    bool(re.search(rf"(?:R\.id\.|@\+?id/){re.escape(identifier)}\b", row.text))
                    for identifier in seed_ids
                )
                handler_hits = len(ACTION_MARKERS & row.terms)
                control_flow_bonus = 4.0 if identifier_hits and ("->" in row.text or "when" in row.text or "if" in row.text) else 0.0
                boosted.append((score + identifier_hits * (8.0 + handler_hits) + control_flow_bonus, row))
            scored = boosted

            # One additional bounded hop: resource-id handler -> directly called
            # function declaration. This is the minimal behavior chain needed
            # for actions such as addHolidays() or tryExportEvents().
            called_symbols: set[str] = set()
            for _score, row in sorted(scored, key=lambda item: item[0], reverse=True)[:30]:
                if not any(identifier in row.text for identifier in seed_ids):
                    continue
                called_symbols.update(re.findall(r"(?:->|\{|=)\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(", row.text))
            ignored = {"if", "when", "let", "apply", "run", "also", "with"}
            called_symbols.difference_update(ignored)
            if called_symbols:
                existing = {(row.path, row.line) for _score, row in scored}
                for row in self.lines:
                    if (row.path, row.line) in existing:
                        continue
                    if any(re.search(rf"\bfun\s+{re.escape(symbol)}\s*\(", row.text) for symbol in called_symbols):
                        scored.append((12.0 + len(ACTION_MARKERS & row.terms), row))

        output: list[EvidenceSnippet] = []
        per_file: dict[str, int] = {}
        seen_text: set[str] = set()
        for score, row in sorted(scored, key=lambda item: (-item[0], item[1].path, item[1].line)):
            if per_file.get(row.path, 0) >= 3:
                continue
            source_lines = self.file_lines.get(row.path, [])
            start = max(0, row.line - 3)
            end = min(len(source_lines), row.line + 4)
            context = " ".join(line.strip() for line in source_lines[start:end] if line.strip())
            normalized = re.sub(r"\s+", " ", context).lower()
            if normalized in seen_text:
                continue
            seen_text.add(normalized)
            per_file[row.path] = per_file.get(row.path, 0) + 1
            output.append(EvidenceSnippet(row.path, row.line, context[:700], score, gap.gap_type))
            if len(output) >= max_results:
                break
        return output

    def trace(self, gaps: list[Gap], *, max_total_results: int = 20, global_query: str = "") -> list[EvidenceSnippet]:
        output: list[EvidenceSnippet] = []
        seen: set[tuple[str, int]] = set()
        per_gap = max(4, max_total_results // max(1, len(gaps)))
        for gap in gaps:
            for result in self.search(gap, max_results=per_gap, global_query=global_query):
                key = (result.path, result.line)
                if key in seen:
                    continue
                seen.add(key)
                output.append(result)
                if len(output) >= max_total_results:
                    return output
        return output
