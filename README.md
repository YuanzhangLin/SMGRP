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

## Applications

The evaluation uses 25 Android applications: 13 from the official DroidTask APK set and 12 fixed closed-source APKs. A version in parentheses is the APK version name. Closed-source APKs are not redistributed in this repository. The bundled example contains only Via Browser 7.3.3.

| Category | DroidTask (version) | Package | Closed-source (version) | Package |
|---|---|---|---|---|
| Launcher | AppLauncher (5.11.2) | `com.simplemobiletools.applauncher` | Nova Launcher (8.8.8) | `com.teslacoilsw.launcher` |
| Calendar | Calendar (3.4.2) | `com.simplemobiletools.calendar` | Business Calendar (1.6.1.5) | `netgenius.bizcal` |
| Camera | Camera (5.6.3) | `com.simplemobiletools.camera` | ProCam X (1.26) | `com.intermedia.hd.camera.pro` |
| Alarm and clock | Clock (5.10.0) | `com.simplemobiletools.clock` | Alarm Clock Xtreme (24.16.4) | `com.alarmclock.xtreme.free` |
| Contacts and dialing | Contacts (6.22.3), Dialer (5.17.8) | `com.simplemobiletools.contacts.pro`, `com.simplemobiletools.dialer` | True Phone Dialer & Contacts (2.0.24-gp) | `com.hb.dialer.free` |
| File management | FileManager (6.15.3) | `com.simplemobiletools.filemanager.pro` | CX File Explorer (2.7.8) | `com.cxinventor.file.explorer` |
| Browser | Firefox (115.0.1) | `org.mozilla.firefox` | Via Browser (7.3.3) | `mark.via.gp` |
| Gallery | Gallery (6.26.7) | `com.simplemobiletools.gallery.pro` | Vertical Gallery (1.8.1) | `com.mobsnake.verticalgallery` |
| Messaging | Messenger (5.18.2) | `com.simplemobiletools.smsmessenger` | Textra SMS (4.83) | `com.textra` |
| Music playback | MusicPlayer (5.16.5) | `com.simplemobiletools.musicplayer` | Poweramp (2.0.10) | `com.maxmpz.audioplayer` |
| Notes | Notes (6.15.5) | `com.simplemobiletools.notes.pro` | ColorNote (4.8.6) | `com.socialnmobile.dictapps.notepad.color.note` |
| Voice recording | VoiceRecorder (5.11.3) | `com.simplemobiletools.voicerecorder` | Recorder (2.1.4) | `com.pawegio.recandsave` |

Execution used x86_64 Android emulators. Android 13 (API 33) was the default. Applications with compatibility constraints used Android 6.0 (API 23), Android 7.1.1 (API 25), or Android 14 (API 34). All emulators used the English locale and the UTC time zone. Planning methods for one application shared that application's emulator. The per-application emulator assignment is kept with the experiment records.

The 60 ClosedSource task instructions and action-only ground-truth trajectories are in `dataset/closed_source/`. That directory does not contain APKs. DroidTask's 158 tasks are not included. The Via Browser 7.3.3 APK bundled for the quick API check remains in `examples/via_browser_task4/`.

## Layout

- `src/mgrp/`: planner, prompts, UI Map projection, anchors, evidence retrieval, model client, and CLI.
- `tests/`: planner regression tests.
- `examples/via_browser_task4/`: bundled task, UI Map, and APK used by the quick API check.
