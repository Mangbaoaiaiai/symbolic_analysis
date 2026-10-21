#!/usr/bin/env python3
"""Write run metadata for a completed local experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from symbolic_analysis.profile import paper_profile  # noqa: E402

try:
    import angr  # noqa: E402
    import claripy  # noqa: E402
    import z3  # noqa: E402
except ImportError:
    angr = claripy = z3 = None


def command_output(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_state_sha256() -> str:
    digest = hashlib.sha256()
    excluded = {".git", "work", "results", "__pycache__"}
    for root, directories, files in os.walk(ROOT):
        directories[:] = sorted(
            directory
            for directory in directories
            if directory not in excluded
        )
        for name in sorted(files):
            if name.endswith((".pyc", ".pyo")):
                continue
            path = Path(root) / name
            relative = path.relative_to(ROOT).as_posix()
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            digest.update(b"\0")
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument(
        "--runtime-image",
        help="Read runtime versions from this Docker image.",
    )
    parser.add_argument("--command", action="append", default=[])
    args = parser.parse_args()

    try:
        diff = subprocess.run(
            ["git", "diff", "--binary"],
            cwd=ROOT,
            capture_output=True,
            check=False,
        ).stdout
    except FileNotFoundError:
        diff = b""
    runtime = {
        "python": platform.python_version(),
        "angr": getattr(angr, "__version__", None),
        "claripy": getattr(claripy, "__version__", None),
        "z3": z3.get_version_string() if z3 is not None else None,
    }
    if args.runtime_image and runtime["z3"] is None:
        runtime_text = command_output(
            [
                "docker",
                "run",
                "--rm",
                args.runtime_image,
                "python",
                "-c",
                (
                    "import json,angr,claripy,z3;"
                    "print(json.dumps({'python':__import__('sys').version.split()[0],"
                    "'angr':angr.__version__,'claripy':claripy.__version__,"
                    "'z3':z3.get_version_string()}))"
                ),
            ]
        )
        if runtime_text:
            runtime.update(json.loads(runtime_text.splitlines()[-1]))
    git_status = command_output(["git", "status", "--porcelain"])
    metadata = {
        "schema": "symbolicana.run_metadata.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "git_branch": command_output(["git", "branch", "--show-current"]),
        "git_commit": command_output(["git", "rev-parse", "HEAD"]),
        "git_dirty": bool(git_status),
        "git_diff_sha256": hashlib.sha256(diff).hexdigest() if diff else None,
        "source_state_sha256": source_state_sha256(),
        "image": args.image,
        "image_id": command_output(
            ["docker", "image", "inspect", "--format", "{{.Id}}", args.image]
        ),
        "commands": args.command,
        "runtime": runtime,
        "profile": paper_profile(),
        "input_sha256": {
            str(relative): file_sha256(ROOT / relative)
            for relative in (
                "configs/paper_62.csv",
                "requirements.txt",
                "Dockerfile",
                "benchmark/osf_benchmarks.zip",
            )
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
