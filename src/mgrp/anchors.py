"""Lightweight UI-to-code retrieval anchors for Android repositories."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .context import tokens


ANDROID = "{http://schemas.android.com/apk/res/android}"
APP = "{http://schemas.android.com/apk/res-auto}"
SOURCE_SUFFIXES = {".kt", ".java"}


@dataclass
class ActionAnchor:
    resource_id: str
    resource_type: str
    declaration: str
    visible_text: str | None = None
    string_id: str | None = None
    container: str | None = None
    open_action: str | None = None
    show_as_action: str | None = None
    handler_hits: list[dict] = field(default_factory=list)
    effect_seeds: list[str] = field(default_factory=list)
    interaction: str | None = None
    semantics: str | None = None
    commit_effect: str | None = None
    score: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def _resource_name(value: str | None, prefix: str) -> str | None:
    if not value or not value.startswith(prefix):
        return None
    return value.split("/", 1)[-1]


class ActionAnchorIndex:
    """Build a small resource -> declaration -> handler bridge once per app."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.anchors: list[ActionAnchor] = []
        self.files_scanned = 0
        self._build()

    def _strings(self) -> dict[str, str]:
        output: dict[str, str] = {}
        candidates = sorted(self.root.rglob("res/values/strings.xml"))
        for path in candidates:
            try:
                tree = ET.parse(path)
            except (ET.ParseError, OSError):
                continue
            for element in tree.getroot().findall("string"):
                name = element.attrib.get("name")
                value = "".join(element.itertext()).strip()
                if name and value:
                    output.setdefault(name, value)
        return output

    def _build(self) -> None:
        strings = self._strings()
        by_id: dict[str, ActionAnchor] = {}
        xml_paths = sorted(self.root.rglob("res/layout/*.xml")) + sorted(self.root.rglob("res/menu/*.xml"))
        for path in xml_paths:
            try:
                tree = ET.parse(path)
            except (ET.ParseError, OSError):
                continue
            relative = path.relative_to(self.root).as_posix()
            is_menu = "/menu/" in f"/{relative}"
            for element in tree.getroot().iter():
                resource_id = _resource_name(element.attrib.get(ANDROID + "id"), "@+id/") or _resource_name(element.attrib.get(ANDROID + "id"), "@id/")
                if not resource_id:
                    continue
                raw_text = element.attrib.get(ANDROID + "title") or element.attrib.get(ANDROID + "text") or element.attrib.get(ANDROID + "hint") or element.attrib.get(ANDROID + "contentDescription")
                string_id = _resource_name(raw_text, "@string/")
                visible = strings.get(string_id, raw_text) if string_id else raw_text
                show = element.attrib.get(APP + "showAsAction") or element.attrib.get(ANDROID + "showAsAction")
                anchor = ActionAnchor(
                    resource_id=resource_id,
                    resource_type="menu_item" if is_menu else "view",
                    declaration=relative,
                    visible_text=visible,
                    string_id=string_id,
                    container="overflow_menu" if is_menu and show == "never" else ("action_bar" if is_menu else path.stem),
                    open_action="open_more_options" if is_menu and show == "never" else None,
                    show_as_action=show,
                )
                # Prefer menu declarations and entries with visible text.
                previous = by_id.get(resource_id)
                if previous is None or (anchor.visible_text and not previous.visible_text) or (is_menu and previous.resource_type != "menu_item"):
                    by_id[resource_id] = anchor

        source_paths = [path for path in self.root.rglob("*") if path.is_file() and path.suffix.lower() in SOURCE_SUFFIXES]
        self.files_scanned = len(source_paths) + len(xml_paths)
        for path in source_paths:
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            relative = path.relative_to(self.root).as_posix()
            current_symbol = ""
            for number, line in enumerate(lines, 1):
                fun = re.search(r"\b(?:fun|void|boolean|Boolean|int|String)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)
                if fun:
                    current_symbol = fun.group(1)
                for resource_id in re.findall(r"R\.id\.([A-Za-z0-9_]+)", line):
                    anchor = by_id.get(resource_id)
                    if anchor is None:
                        continue
                    start = max(0, number - 2)
                    end = min(len(lines), number + 2)
                    context = " ".join(item.strip() for item in lines[start:end] if item.strip())[:900]
                    calls = re.findall(r"(?:->|\{|=)\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)
                    hit = {"path": relative, "line": number, "symbol": current_symbol, "text": context}
                    if hit not in anchor.handler_hits:
                        anchor.handler_hits.append(hit)
                    for call in calls:
                        if call not in {"if", "when", "let", "apply", "run"} and call not in anchor.effect_seeds:
                            anchor.effect_seeds.append(call)
            self._extract_dynamic_interactions(path, relative, lines, by_id)
        self.anchors = sorted(by_id.values(), key=lambda item: (item.resource_type != "menu_item", item.resource_id))

    def _extract_dynamic_interactions(
        self, path: Path, relative: str, lines: list[str], by_id: dict[str, ActionAnchor]
    ) -> None:
        """Extract high-value list-item and dialog semantics without a call graph."""
        text = "\n".join(lines)
        owner_match = re.search(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)", text)
        owner = owner_match.group(1) if owner_match else path.stem

        # An adapter constructor lambda is the ordinary item-click callback in
        # this Android style. Preserve the object type and immediate effect.
        pattern = re.compile(
            r"([A-Za-z_][A-Za-z0-9_]*Adapter)\s*\([^\n]*?\)\s*\{\s*"
            r"([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*it\s+as\s+([A-Za-z_][A-Za-z0-9_]*)\s*\)",
            re.MULTILINE,
        )
        for match in pattern.finditer(text):
            adapter, effect, item_type = match.groups()
            words = re.sub(r"(?<!^)(?=[A-Z])", " ", item_type).lower()
            line = text[:match.start()].count("\n") + 1
            key = f"dynamic_{item_type.lower()}_item_click"
            by_id[key] = ActionAnchor(
                resource_id=key,
                resource_type="dynamic_list_item",
                declaration=relative,
                visible_text=f"{words} list item",
                container=owner,
                interaction="ordinary_click",
                semantics="edit_existing_item",
                handler_hits=[{"path": relative, "line": line, "symbol": adapter, "text": match.group(0)}],
                effect_seeds=[effect],
            )

        # Contextual action mode / selection followed by delete is a distinct
        # destructive interaction and must not be confused with ordinary click.
        if "Adapter" in owner and "askConfirmDelete" in text and "actionItemPressed" in text:
            item_name = re.sub(r"Adapter$", "", owner)
            words = re.sub(r"(?<!^)(?=[A-Z])", " ", item_name).lower()
            key = f"dynamic_{item_name.lower()}_item_selection"
            by_id[key] = ActionAnchor(
                resource_id=key,
                resource_type="dynamic_list_item",
                declaration=relative,
                visible_text=f"{words} selected list item",
                container=owner,
                interaction="selection_or_long_press",
                semantics="delete_existing_item",
                effect_seeds=["askConfirmDelete"],
            )

        # Positive dialog buttons are commit boundaries. Distinguish update
        # from insert so a rename request cannot be satisfied by delete/create.
        if "BUTTON_POSITIVE" in text and "updateEventType" in text:
            line = next((n for n, value in enumerate(lines, 1) if "BUTTON_POSITIVE" in value), 1)
            key = "event_type_edit_dialog_commit"
            by_id[key] = ActionAnchor(
                resource_id=key,
                resource_type="dialog_commit",
                declaration=relative,
                visible_text="Edit event type OK",
                container=owner,
                interaction="positive_button",
                semantics="commit_edit_existing_item",
                commit_effect="updateEventType",
                handler_hits=[{"path": relative, "line": line, "symbol": owner, "text": lines[line - 1].strip()}],
                effect_seeds=["updateEventType"],
            )

    def search(self, query: str, *, max_results: int = 12) -> list[ActionAnchor]:
        query_terms = tokens(query)
        ranked: list[ActionAnchor] = []
        for anchor in self.anchors:
            blob = " ".join(filter(None, [
                anchor.resource_id, anchor.visible_text, anchor.string_id, anchor.declaration,
                anchor.container, anchor.open_action, " ".join(anchor.effect_seeds),
                anchor.interaction, anchor.semantics, anchor.commit_effect,
                " ".join(str(hit.get("symbol") or "") for hit in anchor.handler_hits),
            ]))
            anchor_terms = tokens(blob)
            overlap = len(query_terms & anchor_terms)
            if overlap == 0:
                continue
            phrase_bonus = 0.0
            lowered_query = query.lower()
            if anchor.visible_text and anchor.visible_text.lower() in lowered_query:
                phrase_bonus += 5.0
            if anchor.resource_id.lower().replace("_", " ") in lowered_query:
                phrase_bonus += 4.0
            anchor.score = overlap * 2.0 + phrase_bonus + (1.0 if anchor.handler_hits else 0.0)
            ranked.append(anchor)
        ordered = sorted(ranked, key=lambda item: (-item.score, item.resource_id))

        # If a task-relevant control lives on Settings, preserve the concrete
        # entry action from the main screen as one lightweight predecessor.
        # This avoids presenting an intermediate Activity as an assumed start.
        dynamic_destination = next(
            (item for item in ordered if item.resource_type == "dynamic_list_item" and item.container),
            None,
        )
        if dynamic_destination:
            destination_terms = tokens(re.sub(r"Activity$", "", dynamic_destination.container or ""))
            predecessor = next(
                (
                    item for item in self.anchors
                    if item.resource_id.startswith("settings_")
                    and len(destination_terms & tokens(item.resource_id)) >= 2
                ),
                None,
            )
            if predecessor:
                predecessor.score = max(dynamic_destination.score - 0.05, 0.1)
                if predecessor not in ordered:
                    ordered.append(predecessor)

        settings_entry = next((item for item in self.anchors if item.resource_id == "settings"), None)
        settings_child = next(
            (item for item in ordered if item.resource_id.startswith("settings_") or item.container == "SettingsActivity"),
            None,
        )
        if settings_entry and settings_child:
            settings_entry.score = max(settings_child.score - 0.1, 0.1)
            if settings_entry not in ordered:
                ordered.append(settings_entry)
        ordered.sort(key=lambda item: (-item.score, item.resource_id))
        return ordered[:max_results]

    @staticmethod
    def render(anchors: list[ActionAnchor]) -> str:
        if not anchors:
            return "No task-relevant UI-code anchors were found."
        rows = []
        for anchor in anchors:
            handlers = [f'{hit["path"]}:{hit["line"]} {hit.get("symbol") or ""}' for hit in anchor.handler_hits[:3]]
            rows.append(str({
                "resource_id": anchor.resource_id,
                "visible_text": anchor.visible_text,
                "declaration": anchor.declaration,
                "container": anchor.container,
                "open_action": anchor.open_action,
                "handlers": handlers,
                "effect_seeds": anchor.effect_seeds[:4],
                "interaction": anchor.interaction,
                "semantics": anchor.semantics,
                "commit_effect": anchor.commit_effect,
            }))
        return "\n".join(rows)
