"""Run a bundled case through a real model API."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

from .client import OpenAICompatibleClient, _setting
from .runner import MGRPPlanner


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASE = ROOT / "examples" / "via_browser_task4" / "case.json"
JADX_VERSION = "1.5.6"
JADX_URL = f"https://github.com/skylot/jadx/releases/download/v{JADX_VERSION}/jadx-{JADX_VERSION}.zip"
JADX_SHA256 = "545ea2be9c242511bc145755cf4bda2485ade42966e096f8b4d3da2a230e8974"


def _ensure_jadx(cache_root: Path) -> Path:
    tool_root = cache_root / "tools" / "jadx"
    executable = tool_root / "bin" / "jadx.bat"
    if executable.is_file():
        return executable

    cache_root.mkdir(parents=True, exist_ok=True)
    archive = cache_root / "tools" / f"jadx-{JADX_VERSION}.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading JADX {JADX_VERSION} from its official release...", file=sys.stderr)
    urllib.request.urlretrieve(JADX_URL, archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != JADX_SHA256:
        archive.unlink(missing_ok=True)
        raise SystemExit(f"JADX checksum mismatch: {digest}")

    if tool_root.exists():
        shutil.rmtree(tool_root)
    tool_root.mkdir(parents=True)
    with zipfile.ZipFile(archive) as bundle:
        root = tool_root.resolve()
        for member in bundle.infolist():
            target = (tool_root / member.filename).resolve()
            if root not in target.parents and target != root:
                raise SystemExit(f"Unsafe path in JADX archive: {member.filename}")
        bundle.extractall(tool_root)
    archive.unlink()
    if not executable.is_file():
        raise SystemExit(f"JADX executable missing after extraction: {executable}")
    return executable


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a bundled MGRP case using a real API.")
    parser.add_argument("--case", type=Path, default=DEFAULT_CASE)
    parser.add_argument("--model", default=_setting("MGRP_LLM_MODEL", "qwen-max"))
    parser.add_argument("--output", type=Path, default=Path("quick_result.json"))
    parser.add_argument("--work-dir", type=Path, default=Path(".mgrp") / "quick")
    parser.add_argument("--force-decompile", action="store_true")
    args = parser.parse_args()

    case_path = args.case.resolve()
    case = json.loads(case_path.read_text(encoding="utf-8"))
    case_root = case_path.parent
    apk_path = case_root / case["apk"]
    decompiled = args.work_dir.resolve() / "decompiled"
    if args.force_decompile and decompiled.exists():
        shutil.rmtree(decompiled)
    if not (decompiled / "sources").is_dir() or not (decompiled / "resources").is_dir():
        if shutil.which("java") is None:
            raise SystemExit("Java 11 or newer is required to download and run JADX.")
        jadx = _ensure_jadx(args.work_dir.resolve().parent)
        decompiled.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            [str(jadx), "-j", "4", "-d", str(decompiled), str(apk_path)],
            check=False,
        )
        java_files = list((decompiled / "sources").rglob("*.java"))
        if not java_files or not (decompiled / "resources").is_dir():
            raise SystemExit(f"JADX produced no usable output (exit code {completed.returncode})")
        if completed.returncode != 0:
            print(
                f"Warning: JADX exited with {completed.returncode}, continuing with "
                f"{len(java_files)} generated Java files.",
                file=sys.stderr,
            )
    result = MGRPPlanner(OpenAICompatibleClient(model=args.model), model=args.model).run(
        task_id=case["task_id"],
        app_id=case["app_id"],
        instruction=case["instruction"],
        ui_map_path=case_root / case["ui_map"],
        repository_root=decompiled,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result.to_generation_record(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "task_id": result.task_id,
        "model": result.model,
        "apk": str(apk_path),
        "decompiled": str(decompiled),
        "route": result.route,
        "steps": result.steps,
        "evidence_count": len(result.evidence),
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "duration_seconds": result.duration_seconds,
        "output": str(args.output),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
