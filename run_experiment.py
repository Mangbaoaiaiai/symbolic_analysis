#!/usr/bin/env python3
"""Build the pinned image and run a benchmark suite."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BASE_IMAGE = "symbolicana-paper:latest"
BINDIFF_IMAGE = os.environ.get(
    "SYMBOLICANA_BINDIFF_IMAGE", "symbolicana-bindiff:latest"
)
DEFAULT_IMAGE = os.environ.get("SYMBOLICANA_IMAGE", BASE_IMAGE)


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
    parser.add_argument("--image")
    parser.add_argument(
        "--bindiff",
        action="store_true",
        help=(
            "Build/use the BinDiff 8 + Ghidra 9.2.3 image from "
            "Dockerfile.bindiff."
        ),
    )
    parser.add_argument(
        "--run-name",
        help=(
            "Run label. Defaults to the suite name; --suite all writes separate "
            "paper and OSF result directories."
        ),
    )
    parser.add_argument(
        "--paper-manifest",
        default="configs/paper_62.csv",
        help="Paper-suite case manifest, relative to the repository root.",
    )
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

    base_build = ["docker", "build", "-t", BASE_IMAGE, str(ROOT)]
    bindiff_build = [
        "docker",
        "build",
        "-f",
        str(ROOT / "Dockerfile.bindiff"),
        "-t",
        BINDIFF_IMAGE,
        str(ROOT),
    ]

    def build(command: list[str]) -> None:
        if args.dry_run:
            print("+ " + " ".join(command))
        else:
            run(command)

    use_default_bindiff = args.bindiff and args.image is None
    if args.rebuild or (use_default_bindiff and not docker_image_exists(BASE_IMAGE)):
        build(base_build)
    if use_default_bindiff and (args.rebuild or not docker_image_exists(BINDIFF_IMAGE)):
        build(bindiff_build)

    effective_image = args.image or (
        BINDIFF_IMAGE if use_default_bindiff else DEFAULT_IMAGE
    )
    if not args.dry_run and not docker_image_exists(effective_image):
        if effective_image != BASE_IMAGE:
            print(
                f"Image {effective_image!r} is unavailable; "
                f"falling back to {BASE_IMAGE!r} with explicit feature-only "
                "graph fallback.",
                flush=True,
            )
        effective_image = BASE_IMAGE
        if not docker_image_exists(effective_image):
            build(base_build)

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
        "-e",
        f"SYMBOLICANA_IMAGE={effective_image}",
        effective_image,
        "python",
        "scripts/run_suite.py",
        "--suite",
        args.suite,
    ]
    if args.max_cases is not None:
        command.extend(["--max-cases", str(args.max_cases)])
    if args.fresh:
        command.append("--fresh")
    if args.run_name:
        command.extend(["--run-name", args.run_name])
    if args.suite in {"paper", "all"}:
        command.extend(["--paper-manifest", args.paper_manifest])
    if args.dry_run:
        print("+ " + " ".join(command))
    else:
        run(command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
