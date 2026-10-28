"""Run the MGRP planner for one explicitly supplied task and app artifact set."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mgrp.client import OpenAICompatibleClient, _setting

from .runner import MGRPPlanner


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("--app", required=True)
    parser.add_argument("--instruction", required=True)
    parser.add_argument("--ui-map", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--model", default=_setting("MGRP_LLM_MODEL", "qwen-max"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = MGRPPlanner(OpenAICompatibleClient(model=args.model), model=args.model).run(
        task_id=args.task_id,
        app_id=args.app,
        instruction=args.instruction,
        ui_map_path=args.ui_map,
        repository_root=args.repo_root,
    )
    payload = result.to_generation_record()
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
