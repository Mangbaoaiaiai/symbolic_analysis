#!/usr/bin/env python3
"""Validate the curated result tables shipped with this repository."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
BENCHMARK = ROOT / "benchmark" / "osf_benchmarks.zip"
EXPECTED_BENCHMARK_SHA256 = (
    "e3cdbb21ab079ed69d3a40286cebf4d21d0ec51ee64ca898d93a57d885ba4005"
)
PATH_PATTERNS = (
    re.compile(r"[A-Za-z]:\\"),
    re.compile(r"/workspace/"),
    re.compile(r"/home/"),
    re.compile(r"/tmp/"),
)
FORBIDDEN_FIELDS = {
    "path_dir",
    "typed_old",
    "typed_new",
    "report_path",
    "evaluation_result_file",
    "artifact_path",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assert_path_free(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for pattern in PATH_PATTERNS:
        assert not pattern.search(text), f"local path found in {path}: {pattern.pattern}"


def main() -> int:
    assert sha256(BENCHMARK) == EXPECTED_BENCHMARK_SHA256

    paper_root = RESULTS / "paper"
    paper_summary = load_json(paper_root / "summary.json")
    assert paper_summary["total"] == 62
    assert paper_summary["correct"] == 58
    assert paper_summary["wrong"] == 0
    assert paper_summary["unk"] == 4
    assert paper_summary["eq_correct"] == 29
    assert paper_summary["eq_total"] == 33
    assert paper_summary["neq_correct"] == 29
    assert paper_summary["neq_total"] == 29

    paper_rows = read_rows(paper_root / "cases.csv")
    assert len(paper_rows) == 62
    assert len({row["case_id"] for row in paper_rows}) == 62
    assert Counter(row["ground_truth"] for row in paper_rows) == {
        "EQ": 33,
        "NEQ": 29,
    }
    paper_status = Counter(
        (row.get("final_status") or row.get("outcome") or "").upper()
        for row in paper_rows
    )
    assert paper_status == {"CORRECT": 58, "UNK": 4}

    manifest_rows = read_rows(ROOT / "configs" / "osf_manifest.csv")
    assert len(manifest_rows) == 272
    assert len({row["case_id"] for row in manifest_rows}) == 272
    assert Counter(row["support_status"] for row in manifest_rows) == {
        "supported_snippet": 129,
        "supported_function": 99,
        "supported_main": 28,
        "supported_targets": 15,
        "unsupported": 1,
    }

    osf_root = RESULTS / "osf"
    osf_summary = load_json(osf_root / "summary.json")
    assert osf_summary["total"] == 272
    assert osf_summary["supported"] == 271
    assert osf_summary["unsupported"] == 1
    assert osf_summary["entered_symbolic_execution"] == 198
    assert osf_summary["both_sides_complete"] == 170
    assert osf_summary["correct"] == 147
    assert osf_summary["determinate"] == 147
    assert osf_summary["provisional"] is True
    assert osf_summary["full_osf_rerun_complete"] is False
    assert osf_summary["provisional_replaced_cases"] == 27
    assert len(osf_summary["provisional_case_ids"]) == 27

    osf_rows = read_rows(osf_root / "cases.csv")
    assert len(osf_rows) == 272
    assert len({row["case_id"] for row in osf_rows}) == 272
    expected_outcomes = {
        "correct_eq": 72,
        "correct_neq": 75,
        "wrong_eq": 0,
        "wrong_neq": 0,
        "label_inconsistent": 5,
        "undefined_behavior": 3,
        "unk": 43,
        "failed": 73,
        "not_attempted": 1,
    }
    assert Counter(row["outcome"] for row in osf_rows) == Counter(expected_outcomes)
    assert sum(
        row["outcome"] in {"correct_eq", "correct_neq"} for row in osf_rows
    ) == 147
    provisional_rows = [
        row
        for row in osf_rows
        if row["case_id"] in set(osf_summary["provisional_case_ids"])
    ]
    assert len(provisional_rows) == 27
    assert all(row.get("provisional_merge_source") for row in provisional_rows)

    failure_rows = read_rows(osf_root / "failure_cases.csv")
    assert Counter(row["failure_category"] for row in failure_rows) == {
        "sigkill_or_oom": 46,
        "symbolic_timeout": 28,
        "incomplete_symbolic_exploration": 26,
        "no_complete_paths": 1,
        "verifier_or_semantic_unknown": 15,
        "unsupported_harness": 1,
    }

    upstream = read_rows(osf_root / "upstream_142_cases.csv")
    assert len(upstream) == 142
    assert sum(
        row["outcome"] in {"correct_eq", "correct_neq"} for row in upstream
    ) == 81
    assert Counter(row["outcome"] for row in upstream) == Counter({
        "correct_eq": 38,
        "correct_neq": 43,
        "wrong_eq": 0,
        "wrong_neq": 0,
        "label_inconsistent": 2,
        "undefined_behavior": 1,
        "unk": 15,
        "failed": 43,
    })

    audit_rows = read_rows(ROOT / "configs" / "osf_label_audit.csv")
    assert Counter(row["outcome_override"] for row in audit_rows) == {
        "label_inconsistent": 5,
        "undefined_behavior": 5,
    }

    for path in (paper_root / "cases.csv", osf_root / "cases.csv"):
        rows = read_rows(path)
        assert rows
        assert not (FORBIDDEN_FIELDS & rows[0].keys())

    for result_root in (paper_root, osf_root):
        for path in sorted(result_root.rglob("*")):
            if path.suffix in {".csv", ".json", ".md"}:
                assert_path_free(path)

    print(
        "validated paper=62 (58 correct, 0 wrong, 4 UNK); "
        "provisional OSF=272 (271 supported, 198 entered SE, 170 complete, "
        "147 correct, 0 wrong, 5 label inconsistencies, 3 UB exclusions)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
