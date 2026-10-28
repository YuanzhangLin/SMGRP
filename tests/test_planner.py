from __future__ import annotations

import json
from pathlib import Path

from mgrp.anchors import ActionAnchorIndex
from mgrp.context import project_ui_map
from mgrp.evidence import LocalEvidenceIndex
from mgrp.models import Gap
from mgrp.runner import MGRPPlanner
from mgrp.client import ChatResponse


class FakeClient:
    model = "fake-model"

    def __init__(self, responses: list[dict]):
        self.responses = list(responses)
        self.calls = 0

    def complete(self, *, system: str, user: str, model: str | None = None):
        self.calls += 1
        payload = self.responses.pop(0)
        return ChatResponse(json.dumps(payload), model or self.model, 10, 5)


def write_map(path: Path) -> None:
    path.write_text(json.dumps({
        "activities": {
            "MainActivity": {
                "summary": "Main calendar screen",
                "elements": [{"id": "calendar_fab", "text": "New Event"}],
            },
            "EventActivity": {"elements": [{"id": "event_title", "hint": "Title"}]},
        },
        "transitions": [{"from": "MainActivity", "to": "EventActivity"}],
    }), encoding="utf-8")


def test_ui_map_projection_is_bounded_and_task_conditioned(tmp_path):
    path = tmp_path / "map.json"
    write_map(path)
    excerpt = project_ui_map(path, "Create a new event", max_chars=1000)
    assert "New Event" in excerpt
    assert len(excerpt) <= 1000


def test_local_evidence_trace_finds_menu_and_handler(tmp_path):
    menu = tmp_path / "res" / "menu"
    menu.mkdir(parents=True)
    (menu / "main.xml").write_text('<item android:id="@+id/add_holidays" android:title="Add holidays"/>', encoding="utf-8")
    source = tmp_path / "src"
    source.mkdir()
    (source / "MainActivity.kt").write_text(
        "override fun onOptionsItemSelected(item: MenuItem) {\n"
        "  if (item.itemId == R.id.add_holidays) showHolidayCountries()\n}",
        encoding="utf-8",
    )
    index = LocalEvidenceIndex(tmp_path)
    results = index.search(Gap("R1", "missing_trigger", "Open Add holidays", ("add_holidays", "holiday"), ("menu_xml", "handler")))
    assert any(item.path.endswith("main.xml") for item in results)
    assert any(item.path.endswith("MainActivity.kt") for item in results)


def test_action_anchor_index_links_menu_to_handler(tmp_path):
    values = tmp_path / "app/src/main/res/values"
    menu = tmp_path / "app/src/main/res/menu"
    source = tmp_path / "app/src/main/kotlin/demo"
    values.mkdir(parents=True)
    menu.mkdir(parents=True)
    source.mkdir(parents=True)
    (values / "strings.xml").write_text(
        '<resources><string name="add_holidays">Add holidays</string></resources>',
        encoding="utf-8",
    )
    (menu / "menu_main.xml").write_text(
        '<menu xmlns:android="http://schemas.android.com/apk/res/android" '
        'xmlns:app="http://schemas.android.com/apk/res-auto">'
        '<item android:id="@+id/add_holidays" android:title="@string/add_holidays" '
        'app:showAsAction="never"/></menu>',
        encoding="utf-8",
    )
    (source / "MainActivity.kt").write_text(
        "fun onOptionsItemSelected(id: Int) {\n"
        "  when (id) { R.id.add_holidays -> addHolidays() }\n"
        "}\n",
        encoding="utf-8",
    )

    index = ActionAnchorIndex(tmp_path)
    result = index.search("Add holidays", max_results=1)[0]

    assert result.visible_text == "Add holidays"
    assert result.container == "overflow_menu"
    assert result.open_action == "open_more_options"
    assert result.handler_hits[0]["symbol"] == "onOptionsItemSelected"
    assert result.effect_seeds == ["addHolidays"]


def test_action_anchor_index_extracts_dynamic_item_edit_semantics(tmp_path):
    source = tmp_path / "app/src/main/kotlin/demo"
    source.mkdir(parents=True)
    (source / "ManageTypesActivity.kt").write_text(
        "class ManageTypesActivity {\n"
        "  fun load() {\n"
        "    val adapter = ManageTypesAdapter(this, types, list) {\n"
        "      showTypeDialog(it as EventType)\n"
        "    }\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    (source / "UpdateEventTypeDialog.kt").write_text(
        "class UpdateEventTypeDialog {\n"
        "  fun commit() {\n"
        "    getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {\n"
        "      dbHelper.updateEventType(eventType)\n"
        "    }\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )

    index = ActionAnchorIndex(tmp_path)
    results = index.search("change existing event type", max_results=10)

    edit = next(item for item in results if item.semantics == "edit_existing_item")
    commit = next(item for item in results if item.semantics == "commit_edit_existing_item")
    assert edit.interaction == "ordinary_click"
    assert edit.effect_seeds == ["showTypeDialog"]
    assert commit.interaction == "positive_button"
    assert commit.commit_effect == "updateEventType"


def test_fast_path_uses_one_model_call(tmp_path):
    path = tmp_path / "map.json"
    write_map(path)
    client = FakeClient([{
        "requirements": [{"id": "R1", "goal": "Open new event", "critical": True}],
        "initial_plan": ["Tap New Event."], "gaps": [], "confidence": 0.9,
    }])
    result = MGRPPlanner(client).run(
        task_id="droidtask.calendar.task1", app_id="calendar",
        instruction="Create an event", ui_map_path=path,
    )
    assert client.calls == 1
    assert result.route == "fast_map_only"
    assert result.steps == ["Tap New Event."]


def test_abstract_navigation_does_not_inject_a_gap(tmp_path):
    path = tmp_path / "map.json"
    write_map(path)
    client = FakeClient([{
        "requirements": [{"id": "R1", "goal": "Open settings", "critical": True}],
        "initial_plan": ["Navigate to SettingsActivity."], "gaps": [], "confidence": 0.9,
    }])
    result = MGRPPlanner(client).run(
        task_id="example.task1", app_id="example",
        instruction="Open settings", ui_map_path=path,
    )
    assert client.calls == 1
    assert result.route == "fast_map_only"
    assert result.analysis["gaps"] == []


def test_slow_path_traces_evidence_and_uses_two_calls(tmp_path):
    path = tmp_path / "map.json"
    write_map(path)
    (tmp_path / "MainActivity.kt").write_text(
        "if (item.itemId == R.id.add_holidays) showHolidayCountries()", encoding="utf-8"
    )
    client = FakeClient([
        {
            "requirements": [{"id": "R1", "goal": "Open holidays", "critical": True}],
            "initial_plan": [],
            "gaps": [{"requirement_id": "R1", "gap_type": "missing_trigger", "description": "Open Add holidays", "query_terms": ["add_holidays", "holiday"], "preferred_artifacts": ["handler"]}],
            "confidence": 0.4,
        },
        {
            "steps": ["Open More options.", "Tap Add holidays."],
            "requirement_coverage": [{"requirement_id": "R1", "step_numbers": [1, 2], "supported": True}],
            "unresolved_gaps": [], "confidence": 0.9,
        },
    ])
    result = MGRPPlanner(client).run(
        task_id="droidtask.calendar.task4", app_id="calendar",
        instruction="Add holidays", ui_map_path=path, repository_root=tmp_path,
    )
    assert client.calls == 2
    assert result.route == "slow_local_evidence"
    assert result.evidence
    assert result.steps[-1] == "Tap Add holidays."
    assert result.prompt_tokens == 20


def test_no_anchor_ablation_omits_anchor_context(tmp_path):
    path = tmp_path / "map.json"
    write_map(path)
    client = FakeClient([{
        "requirements": [{"id": "R1", "goal": "Open new event", "critical": True}],
        "initial_plan": ["Tap New Event."], "gaps": [], "confidence": 0.9,
    }])
    result = MGRPPlanner(client, method_name="mgrp_no_anchors").run(
        task_id="droidtask.calendar.task1", app_id="calendar",
        instruction="Create an event", ui_map_path=path, repository_root=tmp_path,
        anchor_index=ActionAnchorIndex(tmp_path),
    )
    assert result.planner_config["use_anchors"] is False
    assert result.route == "fast_map_only"


def test_task_wide_ablation_retrieves_with_detected_gap(tmp_path):
    path = tmp_path / "map.json"
    write_map(path)
    (tmp_path / "MainActivity.kt").write_text(
        "fun createEvent() = openEventEditor()", encoding="utf-8"
    )
    client = FakeClient([
        {
            "requirements": [{"id": "R1", "goal": "Create event", "critical": True}],
            "initial_plan": ["Tap New Event."],
            "gaps": [{"requirement_id": "R1", "gap_type": "missing_effect",
                      "description": "Confirm editor", "query_terms": ["editor"],
                      "preferred_artifacts": ["handler"]}], "confidence": 0.5,
        },
        {"steps": ["Tap New Event."], "requirement_coverage": [],
         "unresolved_gaps": [], "confidence": 0.8},
    ])
    result = MGRPPlanner(client, method_name="mgrp_task_wide").run(
        task_id="droidtask.calendar.task1", app_id="calendar",
        instruction="Create an event", ui_map_path=path, repository_root=tmp_path,
    )
    assert result.planner_config["retrieval_query"] == "task"
    assert client.calls == 2


def test_always_retrieve_ablation_uses_second_call_without_gap(tmp_path):
    path = tmp_path / "map.json"
    write_map(path)
    (tmp_path / "MainActivity.kt").write_text(
        "fun createEvent() = openEventEditor()", encoding="utf-8"
    )
    client = FakeClient([
        {
            "requirements": [{"id": "R1", "goal": "Create event", "critical": True}],
            "initial_plan": ["Tap New Event."], "gaps": [], "confidence": 0.9,
        },
        {"steps": ["Tap New Event."], "requirement_coverage": [],
         "unresolved_gaps": [], "confidence": 0.9},
    ])
    result = MGRPPlanner(client, method_name="mgrp_always_retrieve").run(
        task_id="droidtask.calendar.task1", app_id="calendar",
        instruction="Create an event", ui_map_path=path, repository_root=tmp_path,
    )
    assert result.route == "always_local_evidence"
    assert client.calls == 2
