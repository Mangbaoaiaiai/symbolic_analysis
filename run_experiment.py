#!/usr/bin/env python3
"""Build the pinned image and run a benchmark suite."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_IMAGE = "symbolicana-paper:latest"


def run(command: list[str]) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def docker_image_exists(image: str) -> bool:
    completed = subprocess.run(
        ["docker", "image", "inspect", image],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        choices=("tests", "paper", "osf", "all"),
        default="paper",
        help="Experiment suite to execute.",
    )
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Regenerate path artifacts instead of resuming from existing files.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--max-cases",
        type=int,
        help="Smoke-test limit per generated profile; omit for the full suite.",
    )
    args = parser.parse_args()

    if args.rebuild or not docker_image_exists(args.image):
        build = ["docker", "build", "-t", args.image, str(ROOT)]
        if args.dry_run:
            print("+ " + " ".join(build))
        else:
            run(build)

    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "-v",
        f"{ROOT}:/workspace/symbolicana",
        "-w",
        "/workspace/symbolicana",
        args.image,
        "python",
        "scripts/run_suite.py",
        "--suite",
        args.suite,
    ]
    if args.max_cases is not None:
        command.extend(["--max-cases", str(args.max_cases)])
    if args.fresh:
        command.append("--fresh")
    if args.dry_run:
        print("+ " + " ".join(command))
    else:
        run(command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
