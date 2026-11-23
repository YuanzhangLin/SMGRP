# ClosedSource tasks and ground-truth trajectories

This directory contains the 60 ClosedSource planning tasks and their action-only ground-truth trajectories.

- Applications: 12
- Tasks: 60
- APKs, screenshots, and UI hierarchies: not included

Task identifiers are the identifiers used in the experiment. They are not a contiguous `task1`–`task5` range for every application. `step_count` counts executable GUI actions. It excludes the initial observation and application launch.

`tasks/<app_id>/<task_id>.json` is the task definition. `trajectories/<app_id>/<task_id>.json` is the ordered ground-truth action list for that task. `TASKS.md` is a readable index. `manifest.json` lists every file.
