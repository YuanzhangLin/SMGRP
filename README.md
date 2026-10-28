# MGRP

MGRP is an Android GUI task planner. Given a task, a UI Map, and an application's source or decompiled resources, it produces an evidence-grounded action plan.

## Install

Requires Python 3.11 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## Configure

Copy `.env.example` to `.env` in this repository and set the API key, OpenAI-compatible base URL, and model. Environment variables take precedence. Generic `MGRP_LLM_API_KEY` / `MGRP_LLM_BASE_URL` settings override provider-specific routing. The client also supports `DASHSCOPE_*`, `DEEPSEEK_*`, `OPENAI_*`, and `HICODE_*` settings.

## Run

Supply your own UI Map JSON and application source/resource directory:

```powershell
mgrp example.task1 --app example --instruction "Create a new event" --ui-map path/to/ui_map.json --repo-root path/to/app_source --model qwen-max --output outputs/plan.json
```

`python -m mgrp` provides the same CLI. `--repo-root` is required whenever evidence completion is needed; provide it for the complete pipeline. The CLI `--model` defaults to `MGRP_LLM_MODEL` or `qwen-max`.

The default planner uses the complete MGRP pipeline: project task-relevant UI Map content, find UI/code anchors, assess missing knowledge, and retrieve local evidence only when needed. Direct planning makes one logical model call; evidence completion makes two sequential calls. Client retries may result in additional HTTP requests.

Output includes the final steps, selected route, analysis, retrieved evidence, unresolved gaps, elapsed time, and token usage. Token usage sums both model responses where applicable. Elapsed time is measured around the planner pipeline; it is not an API-only latency measurement.

## Quick API check

The bundled case is `closed_source.via_browser.task4`: disable WebRTC in Via Browser. It includes the
task's UI Map and Via Browser 7.3.3 APK. Install Java 11 or newer, then run:

```powershell
python -m mgrp.quick --model deepseek-chat
```

The command performs the complete path:

1. Download and verify the official JADX 1.5.6 release on first use.
2. Decompile the APK into `.mgrp/quick/decompiled/`.
3. Build MGRP's local evidence index over the JADX output.
4. Retrieve task-relevant evidence and call the configured model API.
5. Write the generated record to `quick_result.json`.

After installing the package, `mgrp-quick --model deepseek-chat` runs the same flow. Use
`--force-decompile` to rebuild the JADX output. The command always calls the real model API.

## Python API

```python
from pathlib import Path
from mgrp import MGRPPlanner
from mgrp.client import OpenAICompatibleClient

result = MGRPPlanner(OpenAICompatibleClient(model="qwen-max")).run(
    task_id="example.task1",
    app_id="example",
    instruction="Create a new event",
    ui_map_path=Path("path/to/ui_map.json"),
    repository_root=Path("path/to/app_source"),
)
record = result.to_generation_record()
```

## Tests

```powershell
python -m pytest -q
```

Tests use a fake model client and temporary artifacts; no credentials or paid API calls are required.

## Layout

- `src/mgrp/`: planner, prompts, UI Map projection, anchors, evidence retrieval, model client, and CLI.
- `tests/`: planner regression tests.
- `examples/via_browser_task4/`: bundled task, UI Map, and APK used by the quick API check.
