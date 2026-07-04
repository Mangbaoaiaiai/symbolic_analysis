#!/usr/bin/env python3
"""
Evaluation harness for path-pairing optimization algorithms.

The script is intentionally adapter-oriented: benchmark discovery, metric
aggregation, and report generation are implemented here; tool-specific command
lines are isolated in runner classes so the real VeriBin / symbolic_analysis
entry points can be wired in without touching the evaluation logic.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Optional


class Group(str, Enum):
    NAIVE = "naive"
    VERIBIN_ALIGN = "veribin_align"
    FMCAD_ALIGN = "fmcad_align"


@dataclass(frozen=True)
class BinaryPair:
    pair_id: str
    subset: str
    program: str
    left: Path
    right: Path
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PairingStats:
    total_candidate_pairs: int = 0
    aligned_pairs: int = 0
    correct_pairs: int = 0
    smt_calls: int = 0

    @property
    def acc_percent(self) -> Optional[float]:
        if self.aligned_pairs == 0:
            return None
        return 100.0 * self.correct_pairs / self.aligned_pairs

    def pruning_rate_percent(self, naive_smt_calls: Optional[int]) -> Optional[float]:
        if naive_smt_calls is None or naive_smt_calls <= 0:
            return None
        return 100.0 * (1.0 - (self.smt_calls / naive_smt_calls))


@dataclass
class TimingStats:
    t_se: float = 0.0
    t_align: float = 0.0
    t_smt: float = 0.0

    @property
    def t_total(self) -> float:
        return self.t_se + self.t_align + self.t_smt


@dataclass
class TraceStats:
    t_align: float = 0.0
    t_smt: float = 0.0
    smt_calls: int = 0
    events: int = 0


@dataclass
class RankingStats:
    valid_queries: int = 0
    hit_at_1: int = 0
    hit_at_3: int = 0
    reciprocal_rank_sum: float = 0.0
    missing: int = 0
    ranks: list[int] = field(default_factory=list)

    @property
    def hit1_percent(self) -> Optional[float]:
        if self.valid_queries == 0:
            return None
        return 100.0 * self.hit_at_1 / self.valid_queries

    @property
    def hit3_percent(self) -> Optional[float]:
        if self.valid_queries == 0:
            return None
        return 100.0 * self.hit_at_3 / self.valid_queries

    @property
    def mrr(self) -> Optional[float]:
        if self.valid_queries == 0:
            return None
        return self.reciprocal_rank_sum / self.valid_queries


@dataclass
class GroupResult:
    pair_id: str
    subset: str
    program: str
    group: Group
    status: str
    pairing: PairingStats = field(default_factory=PairingStats)
    ranking: RankingStats = field(default_factory=RankingStats)
    timing: TimingStats = field(default_factory=TimingStats)
    pruning_rate_percent: Optional[float] = None
    command: list[str] = field(default_factory=list)
    stdout_path: Optional[Path] = None
    stderr_path: Optional[Path] = None
    trace_paths: list[Path] = field(default_factory=list)
    error: Optional[str] = None
    ground_truth: Optional[bool] = None
    prediction: Optional[bool] = None
    confusion: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)

    def flat(self) -> dict[str, Any]:
        return {
            "pair_id": self.pair_id,
            "subset": self.subset,
            "program": self.program,
            "group": self.group.value,
            "status": self.status,
            "acc_percent": self.pairing.acc_percent,
            "hit_at_1": self.ranking.hit1_percent,
            "hit_at_3": self.ranking.hit3_percent,
            "mrr": self.ranking.mrr,
            "ranking_queries": self.ranking.valid_queries,
            "ranking_missing": self.ranking.missing,
            "t_se": self.timing.t_se,
            "t_align": self.timing.t_align,
            "t_smt": self.timing.t_smt,
            "t_total": self.timing.t_total,
            "pruning_rate_percent": self.pruning_rate_percent,
            "total_candidate_pairs": self.pairing.total_candidate_pairs,
            "aligned_pairs": self.pairing.aligned_pairs,
            "correct_pairs": self.pairing.correct_pairs,
            "smt_calls": self.pairing.smt_calls,
            "command": " ".join(self.command),
            "stdout_path": str(self.stdout_path) if self.stdout_path else None,
            "stderr_path": str(self.stderr_path) if self.stderr_path else None,
            "trace_paths": ";".join(str(p) for p in self.trace_paths),
            "ground_truth": self.ground_truth,
            "prediction": self.prediction,
            "confusion": self.confusion,
            "error": self.error,
        }


@dataclass(frozen=True)
class EvalConfig:
    root: Path
    benchmarks_dir: Path
    symbolic_dir: Path
    veribin_dir: Path
    output_dir: Path
    timeout: int
    execute: bool
    python: str
    ground_truth_path: Optional[Path] = None
    use_ground_truth_path_matches: bool = False


class ToolRunner:
    group: Group

    def __init__(self, config: EvalConfig):
        self.config = config

    def run(self, pair: BinaryPair) -> GroupResult:
        raise NotImplementedError

    def _empty_result(self, pair: BinaryPair, status: str) -> GroupResult:
        return GroupResult(
            pair_id=pair.pair_id,
            subset=pair.subset,
            program=pair.program,
            group=self.group,
            status=status,
        )

    def _run_command(
        self,
        pair: BinaryPair,
        command: list[str],
        log_stem: str,
        env: Optional[dict[str, str]] = None,
    ) -> tuple[subprocess.CompletedProcess[str], float, Path, Path, Path]:
        log_dir = self.config.output_dir / "logs" / pair.subset / pair.program
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = log_dir / f"{log_stem}.stdout.txt"
        stderr_path = log_dir / f"{log_stem}.stderr.txt"
        trace_path = log_dir / f"{log_stem}.trace.jsonl"
        command_env = dict(env or os.environ.copy())
        command_env.setdefault("SYMBOLICANA_TRACE_PATH", str(trace_path))
        command_env.setdefault(
            "SYMBOLICANA_TRACE_RUN_ID",
            f"{pair.pair_id}:{self.group.value}:{log_stem}",
        )

        start = time.perf_counter()
        completed = subprocess.run(
            command,
            cwd=self.config.root,
            env=command_env,
            text=True,
            capture_output=True,
            timeout=self.config.timeout,
            check=False,
        )
        elapsed = time.perf_counter() - start

        stdout_path.write_text(completed.stdout, encoding="utf-8", errors="replace")
        stderr_path.write_text(completed.stderr, encoding="utf-8", errors="replace")
        return completed, elapsed, stdout_path, stderr_path, trace_path


class NaiveMatchingRunner(ToolRunner):
    """Brute-force all-vs-all SMT comparison baseline."""

    group = Group.NAIVE

    def run(self, pair: BinaryPair) -> GroupResult:
        result = self._empty_result(pair, "dry_run")
        paths_dir = pair.metadata.get("paths_dir")
        report_path = self.config.output_dir / "raw" / pair.pair_id / "naive_report.json"
        command = [
            self.config.python,
            str(self.config.symbolic_dir / "scripts/verify_ranked_path_equivalence.py"),
            "--paths-dir",
            str(paths_dir or pair.left.parent),
            "--naive",
            "--out",
            str(report_path),
        ]
        extend_truth_args(command, pair, self.config.use_ground_truth_path_matches)
        result.command = command
        if pair.metadata.get("naive_ranking_path"):
            result.extra["naive_ranking_path"] = str(pair.metadata["naive_ranking_path"])
        result.extra["report_path"] = str(report_path)

        if not self.config.execute:
            return result

        if not paths_dir:
            result.status = "skipped"
            result.error = "missing paths_dir metadata for ranked SMT verification"
            return result

        try:
            completed, elapsed, stdout_path, stderr_path, trace_path = self._run_command(
                pair, command, "naive", env=symbolic_env(self.config)
            )
            result.stdout_path = stdout_path
            result.stderr_path = stderr_path
            result.trace_paths.append(trace_path)
            result.status = "ok" if completed.returncode == 0 else "failed"
            apply_verification_report(result, report_path, fallback_elapsed=elapsed)
            apply_trace_stats(result, [trace_path])
        except Exception as exc:  # noqa: BLE001 - evaluation harness records failures.
            result.status = "error"
            result.error = str(exc)
        return result


class VeriBinAlignRunner(ToolRunner):
    """BinDiff basic-block graph alignment / VeriBin preferential matching."""

    group = Group.VERIBIN_ALIGN

    def run(self, pair: BinaryPair) -> GroupResult:
        result = self._empty_result(pair, "dry_run")
        config_path = pair.metadata.get("veribin_config")
        ranking_path = pair.metadata.get("veribin_ranking_path")
        paths_dir = pair.metadata.get("paths_dir")
        old_addr = pair.metadata.get("func_addr_old", "0x0")
        new_addr = pair.metadata.get("func_addr_new", "0x0")

        # TODO: Replace placeholder function addresses/config handling with the
        # benchmark manifest's real VeriBin metadata.
        command = [
            self.config.python,
            str(self.config.veribin_dir / "src/veribin.py"),
            "--original_path",
            str(pair.left),
            "--patched_path",
            str(pair.right),
            "--config_file",
            str(config_path or ""),
            "--func_addr_original",
            str(old_addr),
            "--func_addr_patched",
            str(new_addr),
            "--use_ida",
            "True",
        ]
        result.command = command
        if pair.metadata.get("veribin_ranking_path"):
            result.extra["veribin_ranking_path"] = str(pair.metadata["veribin_ranking_path"])
        if pair.metadata.get("veribin_report"):
            result.extra["report_path"] = str(pair.metadata["veribin_report"])
        elif ranking_path:
            result.extra["report_path"] = str(self.config.output_dir / "raw" / pair.pair_id / "veribin_report.json")

        if not self.config.execute:
            if not pair.metadata.get("veribin_ranking_path") and not config_path:
                result.status = "skipped"
                result.error = "missing veribin_ranking_path or veribin_config/BinDiff metadata"
            return result

        if ranking_path and paths_dir:
            report_path = self.config.output_dir / "raw" / pair.pair_id / "veribin_report.json"
            command = [
                self.config.python,
                str(self.config.symbolic_dir / "scripts/verify_ranked_path_equivalence.py"),
                "--paths-dir",
                str(paths_dir),
                "--ranking",
                str(ranking_path),
                "--out",
                str(report_path),
            ]
            extend_truth_args(command, pair, self.config.use_ground_truth_path_matches)
            result.command = command
            result.extra["report_path"] = str(report_path)
            try:
                completed, elapsed, stdout_path, stderr_path, trace_path = self._run_command(
                    pair, command, "veribin_align", env=symbolic_env(self.config)
                )
                result.stdout_path = stdout_path
                result.stderr_path = stderr_path
                result.trace_paths.append(trace_path)
                result.status = "ok" if completed.returncode == 0 else "failed"
                apply_verification_report(result, report_path, fallback_elapsed=elapsed)
                apply_trace_stats(result, [trace_path])
            except Exception as exc:  # noqa: BLE001
                result.status = "error"
                result.error = str(exc)
            return result

        if not config_path:
            result.status = "skipped"
            result.error = "missing veribin_config in benchmark metadata"
            return result

        try:
            completed, elapsed, stdout_path, stderr_path, trace_path = self._run_command(
                pair, command, "veribin_align", env=self._env()
            )
            result.stdout_path = stdout_path
            result.stderr_path = stderr_path
            result.trace_paths.append(trace_path)
            result.status = "ok" if completed.returncode == 0 else "failed"
            result.timing = parse_veribin_timing(completed.stdout, fallback_total=elapsed)
            result.pairing = parse_veribin_output(completed.stdout)
            apply_trace_stats(result, [trace_path])
        except Exception as exc:  # noqa: BLE001
            result.status = "error"
            result.error = str(exc)
        return result

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        src = str(self.config.veribin_dir / "src")
        env["PYTHONPATH"] = f"{src}{os.pathsep}{env.get('PYTHONPATH', '')}"
        return env


class FmcadAlignRunner(ToolRunner):
    """11-dimensional path-constraint features + cosine-similarity ranking."""

    group = Group.FMCAD_ALIGN

    def run(self, pair: BinaryPair) -> GroupResult:
        result = self._empty_result(pair, "dry_run")
        pair_out = self.config.output_dir / "raw" / pair.pair_id / "fmcad"
        vectors_path = pair_out / "path_vectors.json"
        ranking_path = pair_out / "ranking.json"
        precomputed_ranking = pair.metadata.get("fmcad_ranking_path", pair.metadata.get("ranking_path"))
        report_path = pair_out / "verification_report.json"

        # TODO: The current symbolic_analysis scripts operate on path-constraint
        # files. If pair.left / pair.right are raw binaries, insert the symbolic
        # execution step before feature generation.
        command = [
            self.config.python,
            str(self.config.symbolic_dir / "scripts/path_similarity_batch.py"),
            "--vectors",
            str(vectors_path),
            "--all-pairs",
            "--out",
            str(ranking_path),
        ]
        result.command = command
        result.extra["fmcad_ranking_path"] = str(
            pair.metadata.get("fmcad_ranking_path", pair.metadata.get("ranking_path", ranking_path))
        )
        if pair.metadata.get("fmcad_report"):
            result.extra["report_path"] = str(pair.metadata["fmcad_report"])
        else:
            result.extra["report_path"] = str(report_path)

        if not self.config.execute:
            return result

        try:
            pair_out.mkdir(parents=True, exist_ok=True)
            effective_ranking = Path(precomputed_ranking) if precomputed_ranking else ranking_path
            trace_paths: list[Path] = []
            if not effective_ranking.is_file():
                vector_trace_path = self._generate_vectors(pair, vectors_path)
                completed, _, stdout_path, stderr_path, ranking_trace_path = self._run_command(
                    pair, command, "fmcad_align", env=self._env()
                )
                result.stdout_path = stdout_path
                result.stderr_path = stderr_path
                trace_paths.extend([vector_trace_path, ranking_trace_path])
                if completed.returncode != 0:
                    result.status = "failed"
                    result.trace_paths.extend(trace_paths)
                    return result
            verify_command = [
                self.config.python,
                str(self.config.symbolic_dir / "scripts/verify_ranked_path_equivalence.py"),
                "--paths-dir",
                str(pair.metadata.get("paths_dir") or pair.left.parent),
                "--ranking",
                str(effective_ranking),
                "--out",
                str(report_path),
            ]
            extend_truth_args(verify_command, pair, self.config.use_ground_truth_path_matches)
            result.command = verify_command
            completed, elapsed, stdout_path, stderr_path, verify_trace_path = self._run_command(
                pair, verify_command, "fmcad_verify", env=self._env()
            )
            result.stdout_path = stdout_path
            result.stderr_path = stderr_path
            trace_paths.append(verify_trace_path)
            result.trace_paths.extend(trace_paths)
            result.status = "ok" if completed.returncode == 0 else "failed"
            apply_verification_report(result, report_path, fallback_elapsed=elapsed)
            apply_trace_stats(result, result.trace_paths)
        except Exception as exc:  # noqa: BLE001
            result.status = "error"
            result.error = str(exc)
        return result

    def _generate_vectors(self, pair: BinaryPair, vectors_path: Path) -> Path:
        paths_dir = pair.metadata.get("paths_dir")
        if not paths_dir:
            raise RuntimeError("missing paths_dir metadata for FMCAD feature extraction")
        command = [
            self.config.python,
            str(self.config.symbolic_dir / "scripts/generate_path_feature_vectors.py"),
            "--paths-dir",
            str(paths_dir),
            "--include-min-max",
            "--normalize",
            "--out",
            str(vectors_path),
        ]
        completed, _, _, _, trace_path = self._run_command(pair, command, "fmcad_vectors", env=self._env())
        if completed.returncode != 0:
            raise RuntimeError("feature vector generation failed")
        return trace_path

    def _env(self) -> dict[str, str]:
        return symbolic_env(self.config)


def symbolic_env(config: EvalConfig) -> dict[str, str]:
    env = os.environ.copy()
    src = str(config.symbolic_dir / "src")
    env["PYTHONPATH"] = f"{src}{os.pathsep}{env.get('PYTHONPATH', '')}"
    return env


def extend_truth_args(command: list[str], pair: BinaryPair, use_path_truth: bool = False) -> None:
    truth_pairs = first_present(
        pair.metadata,
        "ground_truth_pairs",
        "correct_path_pairs",
        "path_pairs",
        "vep_pairs",
    )
    if use_path_truth and truth_pairs:
        command.extend(["--truth-pairs-json", json.dumps(truth_pairs, ensure_ascii=False)])
    truth = parse_bool(
        pair.metadata.get(
            "ground_truth",
            pair.metadata.get("equivalent", pair.metadata.get("is_equivalent")),
        )
    )
    if truth is None:
        truth = infer_truth_from_pair_id(pair.pair_id)
    if truth is not None:
        command.extend(["--program-ground-truth", "true" if truth else "false"])


def discover_benchmark_pairs(benchmarks_dir: Path) -> list[BinaryPair]:
    manifest = benchmarks_dir / "manifest.json"
    if manifest.is_file():
        return load_manifest(manifest)
    nested_manifests = sorted(benchmarks_dir.glob("*/manifest.json"))
    if nested_manifests:
        pairs: list[BinaryPair] = []
        for nested_manifest in nested_manifests:
            pairs.extend(load_manifest(nested_manifest))
        return pairs
    return discover_by_layout(benchmarks_dir)


def load_manifest(manifest: Path) -> list[BinaryPair]:
    data = json.loads(manifest.read_text(encoding="utf-8"))
    pairs = data.get("pairs", data if isinstance(data, list) else [])
    out: list[BinaryPair] = []
    for item in pairs:
        subset = item["subset"]
        program = item["program"]
        left = Path(item["left"])
        right = Path(item["right"])
        if not left.is_absolute():
            left = manifest.parent / left
        if not right.is_absolute():
            right = manifest.parent / right
        metadata = dict(item.get("metadata", {}))
        for key in (
            "ground_truth",
            "equivalent",
            "is_equivalent",
            "original_path_count",
            "old_path_count",
            "left_path_count",
            "patched_path_count",
            "new_path_count",
            "right_path_count",
            "paths_left",
            "paths_right",
            "paths_dir",
            "veribin_config",
            "veribin_report",
            "fmcad_report",
            "ranking_path",
            "naive_ranking_path",
            "veribin_ranking_path",
            "fmcad_ranking_path",
            "ranking_paths",
            "ground_truth_pairs",
            "correct_path_pairs",
            "path_pairs",
            "func_addr_old",
            "func_addr_new",
        ):
            if key in item and key not in metadata:
                metadata[key] = item[key]
        for key in (
            "paths_dir",
            "veribin_config",
            "veribin_report",
            "fmcad_report",
            "ranking_path",
            "naive_ranking_path",
            "veribin_ranking_path",
            "fmcad_ranking_path",
        ):
            if key in metadata and metadata[key]:
                p = Path(metadata[key])
                metadata[key] = p if p.is_absolute() else manifest.parent / p
        out.append(
            BinaryPair(
                pair_id=item.get("pair_id", f"{subset}/{program}"),
                subset=subset,
                program=program,
                left=left,
                right=right,
                metadata=metadata,
            )
        )
    return out


def discover_by_layout(benchmarks_dir: Path) -> list[BinaryPair]:
    """Fallback discovery for simple layouts.

    Supported patterns under each leaf directory:
    - left/right, old/new, original/patched
    - exactly two executable-looking files
    """
    candidates: list[BinaryPair] = []
    if not benchmarks_dir.is_dir():
        return candidates

    for leaf in sorted(p for p in benchmarks_dir.rglob("*") if p.is_dir()):
        files = [p for p in sorted(leaf.iterdir()) if p.is_file()]
        lookup = {p.name.lower(): p for p in files}
        pair = first_complete_pair(
            (lookup.get("left"), lookup.get("right")),
            (lookup.get("old"), lookup.get("new")),
            (lookup.get("original"), lookup.get("patched")),
        )
        if pair is None:
            executable_like = [p for p in files if is_binary_candidate(p)]
            if len(executable_like) != 2:
                continue
            pair = (executable_like[0], executable_like[1])

        rel = leaf.relative_to(benchmarks_dir)
        subset = rel.parts[0] if rel.parts else "unknown"
        program = "/".join(rel.parts[1:]) if len(rel.parts) > 1 else leaf.name
        candidates.append(
            BinaryPair(
                pair_id=str(rel),
                subset=subset,
                program=program,
                left=pair[0],
                right=pair[1],
                metadata={},
            )
        )
    return candidates


def first_complete_pair(*pairs: tuple[Optional[Path], Optional[Path]]) -> Optional[tuple[Path, Path]]:
    for left, right in pairs:
        if left is not None and right is not None:
            return left, right
    return None


def is_binary_candidate(path: Path) -> bool:
    if path.suffix in {".c", ".cc", ".cpp", ".h", ".java", ".json", ".txt", ".md"}:
        return False
    return os.access(path, os.X_OK) or path.suffix == ""


def parse_symbolic_analysis_output(output: str) -> PairingStats:
    stats = PairingStats()
    stats.smt_calls = parse_first_int(
        output,
        [
            r"SMT constraint checking:.*\((\d+) calls\)",
            r"constraint_call_count['\"]?:\s*(\d+)",
        ],
    )
    stats.aligned_pairs = parse_first_int(
        output,
        [r"Fully equivalent path pairs:\s*(\d+)", r"equivalent_pairs['\"]?:\s*(\d+)"],
    )
    stats.correct_pairs = stats.aligned_pairs
    return stats


def parse_veribin_output(output: str) -> PairingStats:
    stats = PairingStats()
    stats.smt_calls = parse_first_int(output, [r"SMT.*?calls?:\s*(\d+)", r"z3.*?calls?:\s*(\d+)"])
    stats.aligned_pairs = parse_first_int(output, [r"matching path pairs.*?:\s*(\d+)", r"paths_mapping.*?:\s*(\d+)"])
    stats.correct_pairs = parse_first_int(output, [r"correct.*?pairs.*?:\s*(\d+)"]) or stats.aligned_pairs
    return stats


def parse_fmcad_ranking(ranking_path: Path) -> PairingStats:
    stats = PairingStats()
    if not ranking_path.is_file():
        return stats
    data = json.loads(ranking_path.read_text(encoding="utf-8"))
    pairs = data.get("pairs", data.get("ranking", []))
    stats.total_candidate_pairs = len(pairs)
    stats.aligned_pairs = len(pairs)
    return stats


def apply_verification_report(result: GroupResult, report_path: Path, fallback_elapsed: float = 0.0) -> None:
    if not report_path.is_file():
        result.timing.t_smt = fallback_elapsed
        return
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        result.timing.t_smt = fallback_elapsed
        return

    result.prediction = parse_bool(data.get("prediction"))
    result.pairing.total_candidate_pairs = int(data.get("candidate_pairs", 0) or 0)
    result.pairing.aligned_pairs = int(data.get("aligned_pairs", 0) or 0)
    result.pairing.smt_calls = int(data.get("smt_calls", 0) or 0)
    result.timing.t_align = float(data.get("t_align", 0.0) or 0.0)
    result.timing.t_smt = float(data.get("t_smt", fallback_elapsed) or 0.0)
    result.extra["verification_report"] = str(report_path)
    result.extra["unknown_smt_results"] = int(data.get("unknowns", 0) or 0)
    result.extra["semantic_definition"] = data.get("semantic_definition")
    result.extra["semantic_modes"] = data.get("semantic_modes")


def parse_veribin_timing(output: str, fallback_total: float) -> TimingStats:
    init_time = parse_first_float(output, [r"Time elapse for VeriBin init.*?:\s*([0-9.]+)"])
    translator_time = parse_first_float(output, [r"Time elapse for SpiderCheck Translator:\s*([0-9.]+)"])
    smt_time = parse_first_float(output, [r"SMT.*?time.*?:\s*([0-9.]+)", r"Z3.*?time.*?:\s*([0-9.]+)"])
    t_align = init_time + translator_time
    if smt_time == 0.0:
        smt_time = max(0.0, fallback_total - t_align)
    return TimingStats(t_align=t_align, t_smt=smt_time)


def parse_trace_file(path: Path) -> TraceStats:
    stats = TraceStats()
    if not path or not path.is_file():
        return stats
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        stats.events += 1
        name = event.get("event")
        if name == "align_end":
            stats.t_align += float(event.get("elapsed", 0.0) or 0.0)
        elif name == "smt_end":
            stats.t_smt += float(event.get("elapsed", 0.0) or 0.0)
            stats.smt_calls += 1
        elif name == "summary":
            counters = event.get("counters", {}) or {}
            totals = event.get("totals", {}) or {}
            stats.smt_calls = max(stats.smt_calls, int(counters.get("SMT_calls", 0) or 0))
            stats.t_align = max(stats.t_align, float(totals.get("align_seconds", 0.0) or 0.0))
            stats.t_smt = max(stats.t_smt, float(totals.get("smt_seconds", 0.0) or 0.0))
    return stats


def merge_trace_stats(paths: Iterable[Path]) -> TraceStats:
    merged = TraceStats()
    for path in paths:
        stats = parse_trace_file(path)
        merged.t_align += stats.t_align
        merged.t_smt += stats.t_smt
        merged.smt_calls += stats.smt_calls
        merged.events += stats.events
    return merged


def apply_trace_stats(result: GroupResult, trace_paths: Iterable[Path]) -> None:
    stats = merge_trace_stats(trace_paths)
    if stats.events == 0:
        return
    if stats.t_align > 0:
        result.timing.t_align = stats.t_align
    if stats.t_smt > 0:
        result.timing.t_smt = stats.t_smt
    if stats.smt_calls > 0:
        result.pairing.smt_calls = stats.smt_calls
    result.extra["trace_events"] = stats.events


def parse_first_int(output: str, patterns: Iterable[str]) -> int:
    for pattern in patterns:
        match = re.search(pattern, output, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return int(match.group(1))
    return 0


def parse_first_float(output: str, patterns: Iterable[str]) -> float:
    for pattern in patterns:
        match = re.search(pattern, output, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return float(match.group(1))
    return 0.0


def load_ground_truth(path: Optional[Path]) -> dict[str, bool]:
    if not path or not path.is_file():
        return {}
    if path.suffix.lower() == ".csv":
        return load_ground_truth_csv(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "pairs" in data:
        rows = data["pairs"]
    elif isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        return {str(k): parse_bool(v) for k, v in data.items() if parse_bool(v) is not None}
    else:
        rows = []
    out: dict[str, bool] = {}
    for row in rows:
        pair_id = str(row.get("pair_id") or f"{row.get('subset', '')}/{row.get('program', '')}".strip("/"))
        truth = parse_bool(
            row.get("ground_truth", row.get("equivalent", row.get("is_equivalent")))
        )
        if pair_id and truth is not None:
            out[pair_id] = truth
    return out


def load_ground_truth_csv(path: Path) -> dict[str, bool]:
    out: dict[str, bool] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pair_id = row.get("pair_id") or f"{row.get('subset', '')}/{row.get('program', '')}".strip("/")
            truth = parse_bool(
                row.get("ground_truth", row.get("equivalent", row.get("is_equivalent")))
            )
            if pair_id and truth is not None:
                out[pair_id] = truth
    return out


def load_ranking_ground_truth(path: Optional[Path]) -> dict[str, dict[str, set[str]]]:
    if not path or not path.is_file():
        return {}
    if path.suffix.lower() == ".csv":
        return load_ranking_ground_truth_csv(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("pairs", data if isinstance(data, list) else [])
    out: dict[str, dict[str, set[str]]] = {}
    if isinstance(data, dict) and "ranking_ground_truth" in data:
        for pair_id, raw_pairs in data["ranking_ground_truth"].items():
            out[str(pair_id)] = normalize_truth_pairs(raw_pairs)
    for row in rows:
        if not isinstance(row, dict):
            continue
        pair_id = str(row.get("pair_id") or f"{row.get('subset', '')}/{row.get('program', '')}".strip("/"))
        raw_pairs = first_present(
            row,
            "ground_truth_pairs",
            "correct_path_pairs",
            "path_pairs",
            "vep_pairs",
        )
        truth_pairs = normalize_truth_pairs(raw_pairs)
        if pair_id and truth_pairs:
            out[pair_id] = truth_pairs
    return out


def load_ranking_ground_truth_csv(path: Path) -> dict[str, dict[str, set[str]]]:
    out: dict[str, dict[str, set[str]]] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pair_id = row.get("pair_id") or f"{row.get('subset', '')}/{row.get('program', '')}".strip("/")
            query = row.get("query") or row.get("source") or row.get("path_a") or row.get("left_path")
            target = row.get("target") or row.get("match") or row.get("path_b") or row.get("right_path")
            if pair_id and query and target:
                out.setdefault(pair_id, {}).setdefault(norm_path_id(query), set()).add(norm_path_id(target))
    return out


def first_present(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row:
            return row[key]
    return None


def normalize_truth_pairs(raw_pairs: Any) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    if not raw_pairs:
        return out
    if isinstance(raw_pairs, dict):
        for query, targets in raw_pairs.items():
            target_values = targets if isinstance(targets, list) else [targets]
            for target in target_values:
                out.setdefault(norm_path_id(query), set()).add(norm_path_id(target))
        return out
    if isinstance(raw_pairs, list):
        for item in raw_pairs:
            if isinstance(item, dict):
                query = item.get("query") or item.get("source") or item.get("path_a") or item.get("left_path")
                target = item.get("target") or item.get("match") or item.get("path_b") or item.get("right_path")
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                query, target = item[0], item[1]
            else:
                continue
            if query and target:
                out.setdefault(norm_path_id(query), set()).add(norm_path_id(target))
    return out


def norm_path_id(value: Any) -> str:
    text = str(value)
    # Keep path IDs stable across absolute paths, relative paths, and extensions.
    return Path(text).stem if "/" in text or "\\" in text else text.rsplit(".", 1)[0]


def parse_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "equivalent", "eq", "same", "safe"}:
        return True
    if text in {"0", "false", "no", "n", "not_equivalent", "neq", "different", "unsafe"}:
        return False
    return None


def apply_ground_truth(results: list[GroupResult], pairs: list[BinaryPair], external: dict[str, bool]) -> None:
    truth_by_pair: dict[str, bool] = {}
    for pair in pairs:
        truth = parse_bool(
            pair.metadata.get(
                "ground_truth",
                pair.metadata.get("equivalent", pair.metadata.get("is_equivalent")),
            )
        )
        if truth is None:
            truth = infer_truth_from_pair_id(pair.pair_id)
        if truth is not None:
            truth_by_pair[pair.pair_id] = truth
    truth_by_pair.update(external)

    for result in results:
        result.ground_truth = truth_by_pair.get(result.pair_id)
        result.prediction = infer_prediction(result)
        result.confusion = classify_confusion(result.prediction, result.ground_truth)
        if result.confusion in {"TP", "TN"}:
            result.pairing.correct_pairs = max(result.pairing.correct_pairs, 1)
            result.pairing.aligned_pairs = max(result.pairing.aligned_pairs, 1)
        elif result.confusion in {"FP", "FN"}:
            result.pairing.aligned_pairs = max(result.pairing.aligned_pairs, 1)


def infer_truth_from_pair_id(pair_id: str) -> Optional[bool]:
    parts = [p.lower() for p in Path(pair_id).parts]
    if "neq" in parts:
        return False
    if "eq" in parts:
        return True
    return None


def apply_ranking_metrics(
    results: list[GroupResult],
    pairs: list[BinaryPair],
    external_ranking_truth: dict[str, dict[str, set[str]]],
) -> None:
    truth_by_pair: dict[str, dict[str, set[str]]] = {}
    for pair in pairs:
        raw_pairs = first_present(
            pair.metadata,
            "ground_truth_pairs",
            "correct_path_pairs",
            "path_pairs",
            "vep_pairs",
        )
        parsed = normalize_truth_pairs(raw_pairs)
        if parsed:
            truth_by_pair[pair.pair_id] = parsed
    truth_by_pair.update(external_ranking_truth)

    for result in results:
        truth_pairs = truth_by_pair.get(result.pair_id)
        if not truth_pairs:
            continue
        candidates = load_ranking_candidates(result)
        if not candidates:
            continue
        result.ranking = compute_ranking_stats(candidates, truth_pairs)


def apply_precomputed_ranking_timing(results: list[GroupResult]) -> None:
    for result in results:
        timing = load_ranking_timing(result)
        if timing is None:
            continue
        result.timing.t_align = timing
        if result.group == Group.VERIBIN_ALIGN:
            rank_only = load_ranking_timing_component(result, "t_align_rank")
            if rank_only is not None:
                result.timing.t_align = rank_only


def apply_symbolic_execution_timing(results: list[GroupResult], pairs: list[BinaryPair]) -> None:
    se_by_pair = {pair.pair_id: symbolic_execution_seconds(pair) for pair in pairs}
    for result in results:
        result.timing.t_se = se_by_pair.get(result.pair_id, 0.0)
        if result.timing.t_se > 0:
            result.extra["symbolic_execution_seconds"] = result.timing.t_se


def symbolic_execution_seconds(pair: BinaryPair) -> float:
    paths_dir = pair.metadata.get("paths_dir")
    if not paths_dir:
        return 0.0
    paths_dir = Path(paths_dir)
    return (
        read_elapsed_from_log(paths_dir / "symbolic_oldV_symbolic_execution.log")
        + read_elapsed_from_log(paths_dir / "symbolic_newV_symbolic_execution.log")
    )


def read_elapsed_from_log(path: Path) -> float:
    if not path.is_file():
        return 0.0
    match = re.search(r"(?m)^elapsed=([0-9.]+)\s*$", path.read_text(encoding="utf-8", errors="replace"))
    return float(match.group(1)) if match else 0.0


def load_ranking_timing(result: GroupResult) -> Optional[float]:
    total = 0.0
    found = False
    for path in ranking_paths_for_result(result):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        timing = data.get("timing", {}) if isinstance(data, dict) else {}
        value = timing.get("t_align", data.get("t_align") if isinstance(data, dict) else None)
        if value is None:
            continue
        try:
            total += float(value)
            found = True
        except (TypeError, ValueError):
            continue
    return total if found else None


def load_ranking_timing_component(result: GroupResult, component: str) -> Optional[float]:
    total = 0.0
    found = False
    for path in ranking_paths_for_result(result):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        timing = data.get("timing", {}) if isinstance(data, dict) else {}
        value = timing.get(component)
        if value is None:
            continue
        try:
            total += float(value)
            found = True
        except (TypeError, ValueError):
            continue
    return total if found else None


def load_ranking_candidates(result: GroupResult) -> dict[str, list[str]]:
    candidates: dict[str, list[str]] = {}
    for path in ranking_paths_for_result(result):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        merge_candidate_map(candidates, parse_ranking_json(data))
    return candidates


def ranking_paths_for_result(result: GroupResult) -> list[Path]:
    paths = []
    for key in ("ranking_path", "naive_ranking_path", "veribin_ranking_path", "fmcad_ranking_path"):
        raw = result.extra.get(key)
        if raw:
            paths.append(Path(raw))
    for raw_path in result.extra.get("ranking_paths", []) or []:
        paths.append(Path(raw_path))
    return paths


def parse_ranking_json(data: Any) -> dict[str, list[str]]:
    if not isinstance(data, dict):
        return {}
    if "target" in data and "ranking" in data:
        query = norm_path_id(data["target"])
        return {query: [candidate_id(item) for item in data.get("ranking", []) if candidate_id(item)]}
    if "queries" in data:
        out: dict[str, list[str]] = {}
        for query_record in data.get("queries", []):
            query = query_record.get("query") or query_record.get("target") or query_record.get("source")
            ranking = query_record.get("ranking", query_record.get("candidates", []))
            if query:
                out[norm_path_id(query)] = [candidate_id(item) for item in ranking if candidate_id(item)]
        return out
    if "pairs" in data:
        out: dict[str, list[str]] = {}
        for item in data.get("pairs", []):
            a = candidate_id(item, keys=("path_a", "query", "source", "left_path"))
            b = candidate_id(item, keys=("path_b", "target", "match", "right_path", "candidate"))
            if a and b:
                out.setdefault(a, []).append(b)
                out.setdefault(b, []).append(a)
        return out
    return {}


def candidate_id(item: Any, keys: tuple[str, ...] = ("path_id", "candidate", "target", "match", "path_b")) -> Optional[str]:
    if isinstance(item, str):
        return norm_path_id(item)
    if isinstance(item, dict):
        for key in keys:
            if item.get(key) is not None:
                return norm_path_id(item[key])
    return None


def merge_candidate_map(dst: dict[str, list[str]], src: dict[str, list[str]]) -> None:
    for query, candidates in src.items():
        seen = set(dst.get(query, []))
        dst.setdefault(query, [])
        for candidate in candidates:
            if candidate not in seen:
                dst[query].append(candidate)
                seen.add(candidate)


def compute_ranking_stats(
    candidates_by_query: dict[str, list[str]],
    truth_by_query: dict[str, set[str]],
) -> RankingStats:
    stats = RankingStats()
    for query, correct_targets in truth_by_query.items():
        stats.valid_queries += 1
        candidates = candidates_by_query.get(norm_path_id(query), [])
        rank = first_correct_rank(candidates, correct_targets)
        if rank is None:
            stats.missing += 1
            continue
        stats.ranks.append(rank)
        if rank == 1:
            stats.hit_at_1 += 1
        if rank <= 3:
            stats.hit_at_3 += 1
        stats.reciprocal_rank_sum += 1.0 / rank
    return stats


def first_correct_rank(candidates: list[str], correct_targets: set[str]) -> Optional[int]:
    normalized_targets = {norm_path_id(t) for t in correct_targets}
    for idx, candidate in enumerate(candidates, 1):
        if norm_path_id(candidate) in normalized_targets:
            return idx
    return None


def infer_prediction(result: GroupResult) -> Optional[bool]:
    if result.prediction is not None:
        return result.prediction
    text_parts = []
    for path in (result.stdout_path, result.stderr_path):
        if path and path.is_file():
            text_parts.append(path.read_text(encoding="utf-8", errors="replace"))
    for path in result_report_paths(result):
        if path.is_file():
            text_parts.append(path.read_text(encoding="utf-8", errors="replace"))
    text = "\n".join(text_parts)
    parsed = infer_prediction_from_text(text)
    if parsed is not None:
        return parsed
    if result.status == "ok" and result.group == Group.NAIVE:
        return result.pairing.aligned_pairs > 0
    return None


def result_report_paths(result: GroupResult) -> list[Path]:
    paths = []
    raw = result.extra.get("report_path")
    if raw:
        paths.append(Path(raw))
    for raw_path in result.extra.get("report_paths", []) or []:
        paths.append(Path(raw_path))
    return paths


def infer_prediction_from_text(text: str) -> Optional[bool]:
    lowered = text.lower()
    negative_patterns = [
        "not equivalent",
        "not_equivalent",
        "program equivalence: ❌",
        "overall program equivalence: ❌",
        "overall program equivalence: false",
        "condition 1 is false",
        "final result: false",
    ]
    positive_patterns = [
        "semantically fully equivalent",
        "program equivalence: ✅",
        "overall program equivalence: ✅",
        "overall program equivalence: true",
        "the two path constraints are logically equivalent",
        "final result: true",
        "==> condition 1 is true",
    ]
    if any(p in lowered for p in negative_patterns):
        return False
    if any(p in lowered for p in positive_patterns):
        return True
    return None


def classify_confusion(prediction: Optional[bool], truth: Optional[bool]) -> Optional[str]:
    if prediction is None or truth is None:
        return None
    if prediction and truth:
        return "TP"
    if not prediction and not truth:
        return "TN"
    if prediction and not truth:
        return "FP"
    return "FN"


def candidate_pair_count_for_result(result: GroupResult, pairs_by_id: dict[str, BinaryPair]) -> Optional[int]:
    pair = pairs_by_id.get(result.pair_id)
    if pair is None:
        return result.pairing.total_candidate_pairs or None
    meta = pair.metadata
    left_count = first_positive_int(
        meta.get("original_path_count"),
        meta.get("old_path_count"),
        meta.get("left_path_count"),
        meta.get("paths_left"),
    )
    right_count = first_positive_int(
        meta.get("patched_path_count"),
        meta.get("new_path_count"),
        meta.get("right_path_count"),
        meta.get("paths_right"),
    )
    if left_count and right_count:
        return left_count * right_count
    if result.pairing.total_candidate_pairs > 0:
        return result.pairing.total_candidate_pairs
    parsed = parse_path_counts_from_result_logs(result)
    if parsed:
        return parsed[0] * parsed[1]
    return None


def parse_path_counts_from_result_logs(result: GroupResult) -> Optional[tuple[int, int]]:
    text_parts = []
    for path in (result.stdout_path, result.stderr_path):
        if path and path.is_file():
            text_parts.append(path.read_text(encoding="utf-8", errors="replace"))
    text = "\n".join(text_parts)
    patterns = [
        r"Number of paths in program 1:\s*(\d+).*?Number of paths in program 2:\s*(\d+)",
        r"Original,\s*all paths:\s*(\d+).*?New,\s*all paths:\s*(\d+)",
        r"old paths:\s*(\d+).*?new paths:\s*(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return int(match.group(1)), int(match.group(2))
    return None


def first_positive_int(*values: Any) -> Optional[int]:
    for value in values:
        if value is None:
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return None


def attach_pruning_rates(results: list[GroupResult], pairs: list[BinaryPair]) -> None:
    pairs_by_id = {p.pair_id: p for p in pairs}
    for result in results:
        if result.status == "dry_run" and result.pairing.smt_calls == 0:
            result.pruning_rate_percent = None
            continue
        denominator = candidate_pair_count_for_result(result, pairs_by_id)
        if denominator and denominator > 0:
            result.pruning_rate_percent = 100.0 * (1.0 - (result.pairing.smt_calls / denominator))
            result.pairing.total_candidate_pairs = denominator
        else:
            result.pruning_rate_percent = None


def summarize(results: list[GroupResult]) -> dict[str, Any]:
    groups: dict[str, list[GroupResult]] = {}
    for result in results:
        groups.setdefault(result.group.value, []).append(result)

    summary: dict[str, Any] = {}
    for group, rows in groups.items():
        ok_rows = [r for r in rows if r.status == "ok"]
        metric_rows = [r for r in rows if r.status in {"ok", "dry_run"}]
        summary[group] = {
            "cases": len(rows),
            "ok": len(ok_rows),
            "failed_or_skipped": len(rows) - len(ok_rows),
            "avg_acc_percent": confusion_acc_percent(metric_rows),
            "avg_hit_at_1": weighted_ranking_percent(metric_rows),
            "avg_hit_at_3": weighted_ranking_percent(metric_rows, "hit_at_3"),
            "avg_mrr": weighted_mrr(metric_rows),
            "avg_t_se": mean_timing(metric_rows, "t_se"),
            "avg_t_align": mean_timing(metric_rows, "t_align"),
            "avg_t_smt": mean_timing(ok_rows, "t_smt"),
            "avg_t_total": mean_timing(metric_rows, "t_total"),
            "avg_pruning_rate_percent": mean([r.pruning_rate_percent for r in metric_rows]),
        }
    return summary


def summarize_by_subset(results: list[GroupResult]) -> dict[str, dict[str, dict[str, Any]]]:
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for subset in report_subsets(results):
        subset_rows = [r for r in results if normalize_subset(r.subset) == subset]
        out[subset] = {}
        for group in Group:
            rows = [r for r in subset_rows if r.group == group and r.status in {"ok", "dry_run"}]
            out[subset][group.value] = aggregate_rows(rows)
    return out


def report_subsets(results: list[GroupResult]) -> list[str]:
    normalized = sorted({normalize_subset(r.subset) for r in results})
    explicit_abcd = [s for s in ["A", "B", "C", "D"] if s in normalized]
    if explicit_abcd:
        return ["A", "B", "C", "D"]
    return normalized or ["A", "B", "C", "D"]


def aggregate_rows(rows: list[GroupResult]) -> dict[str, Any]:
    total = len(rows)
    tp = sum(1 for r in rows if r.confusion == "TP")
    tn = sum(1 for r in rows if r.confusion == "TN")
    fp = sum(1 for r in rows if r.confusion == "FP")
    fn = sum(1 for r in rows if r.confusion == "FN")
    judged = tp + tn + fp + fn
    acc = 100.0 * (tp + tn) / judged if judged else mean([r.pairing.acc_percent for r in rows])
    return {
        "cases": total,
        "judged": judged,
        "TP": tp,
        "TN": tn,
        "FP": fp,
        "FN": fn,
        "avg_acc_percent": acc,
        "avg_hit_at_1": weighted_ranking_percent(rows, "hit_at_1"),
        "avg_hit_at_3": weighted_ranking_percent(rows, "hit_at_3"),
        "avg_mrr": weighted_mrr(rows),
        "avg_t_se": mean_timing(rows, "t_se"),
        "avg_t_align": mean_timing(rows, "t_align"),
        "avg_t_smt": mean_timing([r for r in rows if r.status == "ok"], "t_smt"),
        "avg_t_total": mean_timing(rows, "t_total"),
        "avg_pruning_rate_percent": mean([r.pruning_rate_percent for r in rows]),
    }


def confusion_acc_percent(rows: list[GroupResult]) -> Optional[float]:
    judged = [r for r in rows if r.confusion in {"TP", "TN", "FP", "FN"}]
    if not judged:
        return mean([r.pairing.acc_percent for r in rows])
    correct = sum(1 for r in judged if r.confusion in {"TP", "TN"})
    return 100.0 * correct / len(judged)


def weighted_ranking_percent(rows: list[GroupResult], field_name: str = "hit_at_1") -> Optional[float]:
    total = sum(r.ranking.valid_queries for r in rows)
    if total == 0:
        return None
    hits = sum(getattr(r.ranking, field_name) for r in rows)
    return 100.0 * hits / total


def weighted_mrr(rows: list[GroupResult]) -> Optional[float]:
    total = sum(r.ranking.valid_queries for r in rows)
    if total == 0:
        return None
    return sum(r.ranking.reciprocal_rank_sum for r in rows) / total


def normalize_subset(subset: str) -> str:
    text = str(subset).strip()
    if re.fullmatch(r"[A-D]", text, flags=re.IGNORECASE):
        return text.upper()
    match = re.fullmatch(r"(?:subset[_\-\s]*)?([A-D])", text, flags=re.IGNORECASE)
    return match.group(1).upper() if match else text


def display_group_name(group: Group) -> str:
    return {
        Group.NAIVE: "Naive",
        Group.VERIBIN_ALIGN: "VERIBIN",
        Group.FMCAD_ALIGN: "Ours",
    }[group]


def mean(values: Iterable[float | None]) -> float | None:
    clean = [v for v in values if v is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def mean_timing(rows: Iterable[GroupResult], field_name: str) -> float | None:
    values = []
    for row in rows:
        value = getattr(row.timing, field_name)
        if value > 0:
            values.append(value)
    return mean(values)


def write_reports(
    results: list[GroupResult],
    pairs: list[BinaryPair],
    output_dir: Path,
    external_ground_truth: dict[str, bool],
    external_ranking_truth: dict[str, dict[str, set[str]]],
    render_tables: bool = True,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    apply_ground_truth(results, pairs, external_ground_truth)
    apply_ranking_metrics(results, pairs, external_ranking_truth)
    apply_precomputed_ranking_timing(results)
    apply_symbolic_execution_timing(results, pairs)
    attach_pruning_rates(results, pairs)
    summary = summarize(results)
    subset_summary = summarize_by_subset(results)

    rows = [r.flat() for r in results]
    (output_dir / "results.json").write_text(
        json.dumps(
            {
                "results": [asdict_for_json(r) for r in results],
                "summary": summary,
                "subset_summary": subset_summary,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    if rows:
        with (output_dir / "results.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    if render_tables:
        write_markdown_summary(summary, output_dir / "summary.md")
        subset_markdown = render_subset_markdown(subset_summary)
        (output_dir / "subset_summary.md").write_text(subset_markdown, encoding="utf-8")
        final_markdown = render_final_equivalence_markdown(results, pairs)
        (output_dir / "final_summary.md").write_text(final_markdown, encoding="utf-8")
        print(subset_markdown)
    else:
        note = (
            "# Dry-run Evaluation Plan\n\n"
            "No tools were executed, so ACC/Hit@1/Hit@3/MRR/timing metrics were not computed.\n\n"
            "Run with `--execute` to collect real measurements.\n"
        )
        (output_dir / "summary.md").write_text(note, encoding="utf-8")
        (output_dir / "subset_summary.md").write_text(note, encoding="utf-8")


def asdict_for_json(result: GroupResult) -> dict[str, Any]:
    data = asdict(result)
    data["group"] = result.group.value
    for key in ("stdout_path", "stderr_path"):
        if data[key] is not None:
            data[key] = str(data[key])
    data["trace_paths"] = [str(p) for p in result.trace_paths]
    return data


def write_markdown_summary(summary: dict[str, Any], path: Path) -> None:
    lines = [
        "# Path Pairing Evaluation Summary",
        "",
        "| Group | Cases | OK | ACC % | Hit@1 % | Hit@3 % | MRR | T_se s | T_align s | T_smt s | T_total s | Pruning % |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for group, row in summary.items():
        lines.append(
            "| {group} | {cases} | {ok} | {acc} | {h1} | {h3} | {mrr} | {tse} | {ta} | {ts} | {tt} | {pr} |".format(
                group=group,
                cases=row["cases"],
                ok=row["ok"],
                acc=fmt(row["avg_acc_percent"]),
                h1=fmt(row.get("avg_hit_at_1")),
                h3=fmt(row.get("avg_hit_at_3")),
                mrr=fmt(row.get("avg_mrr")),
                tse=fmt(row.get("avg_t_se")),
                ta=fmt(row["avg_t_align"]),
                ts=fmt(row["avg_t_smt"]),
                tt=fmt(row["avg_t_total"]),
                pr=fmt(row["avg_pruning_rate_percent"]),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def render_subset_markdown(subset_summary: dict[str, dict[str, dict[str, Any]]]) -> str:
    metrics = [
        ("ACC %", "avg_acc_percent"),
        ("Hit@1 %", "avg_hit_at_1"),
        ("Hit@3 %", "avg_hit_at_3"),
        ("MRR", "avg_mrr"),
        ("T_se s", "avg_t_se"),
        ("T_align s", "avg_t_align"),
        ("T_smt s", "avg_t_smt"),
        ("T_total s", "avg_t_total"),
        ("Pruning %", "avg_pruning_rate_percent"),
    ]
    preferred = ["A", "B", "C", "D"]
    available = list(subset_summary.keys())
    subsets = preferred if any(s in available for s in preferred) else available
    header = ["Method"]
    for subset in subsets:
        for label, _ in metrics:
            header.append(f"Subset {subset} {label}")
    align = ["---"] + ["---:"] * (len(header) - 1)

    lines = [
        "# Evaluation Summary by Subset",
        "",
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(align) + " |",
    ]
    for group in Group:
        row = [display_group_name(group)]
        for subset in subsets:
            values = subset_summary.get(subset, {}).get(group.value, {})
            for _, key in metrics:
                value = values.get(key)
                row.append(fmt(value) if key.startswith("avg_t_") else fmt(value))
        lines.append("| " + " | ".join(row) + " |")

    lines.extend([
        "",
        "Confusion counts use the ground-truth label per binary pair: TP/TN are correct decisions; FP/FN are wrong decisions.",
        "Ranking metrics use path-level ground truth: Hit@1 is the percentage of queries whose correct match is ranked first; Hit@3 counts ranks 1-3; MRR averages reciprocal rank.",
        "T_se is symbolic-execution time for old/new binaries; T_total = T_se + T_align + T_smt.",
        "Pruning % = (1 - SMT_calls / (original_path_count * patched_path_count)) * 100.",
    ])
    return "\n".join(lines) + "\n"


def render_final_equivalence_markdown(results: list[GroupResult], pairs: list[BinaryPair]) -> str:
    pair_map = {pair.pair_id: pair for pair in pairs}
    benches = sorted({pair.subset for pair in pairs})
    methods = [Group.FMCAD_ALIGN, Group.VERIBIN_ALIGN, Group.NAIVE]
    rows: list[list[str]] = []

    for bench in benches:
        bench_pairs = [p for p in pairs if p.subset == bench]
        m_count = len(bench_pairs)
        row = [bench, str(m_count)]
        for truth in (True, False):
            for method in methods:
                subset_rows = [
                    r for r in results
                    if r.pair_id in pair_map
                    and pair_map[r.pair_id].subset == bench
                    and r.group == method
                    and r.ground_truth == truth
                ]
                row.extend(final_cell(subset_rows, truth))
        rows.append(row)

    total_row = ["Total", str(len(pairs))]
    for truth in (True, False):
        for method in methods:
            subset_rows = [
                r for r in results
                if r.group == method
                and r.ground_truth == truth
            ]
            total_row.extend(final_cell(subset_rows, truth))
    rows.append(total_row)

    header = [
        "Bench",
        "# M",
        "Equivalent: Ours Res",
        "Equivalent: Ours Time (s)",
        "Equivalent: VERIBIN Res",
        "Equivalent: VERIBIN Time (s)",
        "Equivalent: Naive Res",
        "Equivalent: Naive Time (s)",
        "Not Equivalent: Ours Res",
        "Not Equivalent: Ours Time (s)",
        "Not Equivalent: VERIBIN Res",
        "Not Equivalent: VERIBIN Time (s)",
        "Not Equivalent: Naive Res",
        "Not Equivalent: Naive Time (s)",
    ]
    lines = [
        "# Final Equivalence Results",
        "",
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] + ["---:"] * (len(header) - 1)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    lines.append("Res = TP/TN/FP/FN classification against ground truth; Time (s) = T_total = T_se + T_align + T_smt.")
    return "\n".join(lines) + "\n"


def final_cell(rows: list[GroupResult], truth: bool) -> list[str]:
    if not rows:
        return ["NA", "NA"]
    ok = sum(1 for r in rows if r.confusion in {"TP", "TN"})
    total = sum(1 for r in rows if r.prediction is not None)
    res = f"{ok}/{total}" if total else "NA"
    tvals = [r.timing.t_total for r in rows if r.timing.t_total > 0]
    time_s = f"{(sum(tvals) / len(tvals)):.4f}" if tvals else "NA"
    return [res, time_s]


def fmt(value: float | None) -> str:
    return "NA" if value is None else f"{value:.4f}"


def fmt_seconds_ms(value: float | None) -> str:
    return "NA" if value is None else f"{value * 1000.0:.4f}"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare Naive, VeriBin Align, and FMCAD feature-vector path matching."
    )
    parser.add_argument("--benchmarks", type=Path, default=Path("benchmarks"))
    parser.add_argument("--symbolic-dir", type=Path, default=Path("."))
    parser.add_argument("--veribin-dir", type=Path, default=Path("../VeriBin"))
    parser.add_argument("--output-dir", type=Path, default=Path("evaluation_results"))
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--python", default=os.environ.get("PYTHON", "python3"))
    parser.add_argument(
        "--ground-truth",
        type=Path,
        default=None,
        help="Optional JSON/CSV file with per-pair ground-truth equivalence labels.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually invoke tool adapters. Default only writes dry-run plans.",
    )
    parser.add_argument(
        "--use-ground-truth-path-matches",
        action="store_true",
        help=(
            "Use path-pair ground truth to judge candidate matches after timing SMT calls. "
            "By default, ranked verification uses the three-layer semantic definition."
        ),
    )
    return parser


def candidate_benchmark_dirs(root: Path) -> list[Path]:
    candidates = [
        root / "benchmarks",
        root / "experiments" / "ardiff_comparison" / "benchmarks",
        root.parent / "VeriBin" / "examples",
    ]
    return [p for p in candidates if p.is_dir()]


def print_no_benchmarks_message(config: EvalConfig) -> None:
    print(f"No benchmark pairs discovered under {config.benchmarks_dir}")
    print("")
    print("Nothing was evaluated, so no ACC/Hit/MRR/timing numbers can be computed.")
    print("Provide a benchmark directory with binary pairs or a manifest.json, for example:")
    print("")
    print("  python3 run_evaluation.py --benchmarks ./benchmarks")
    print("  python3 run_evaluation.py --benchmarks <path-to-benchmarks> --ground-truth <truth.json>")
    candidates = candidate_benchmark_dirs(config.root)
    if candidates:
        print("")
        print("Candidate directories found in this workspace:")
        for path in candidates:
            print(f"  - {path}")


def main() -> int:
    args = build_arg_parser().parse_args()
    root = Path(__file__).resolve().parent
    config = EvalConfig(
        root=root,
        benchmarks_dir=(root / args.benchmarks).resolve(),
        symbolic_dir=(root / args.symbolic_dir).resolve(),
        veribin_dir=(root / args.veribin_dir).resolve(),
        output_dir=(root / args.output_dir).resolve(),
        timeout=args.timeout,
        execute=args.execute,
        python=args.python,
        ground_truth_path=(root / args.ground_truth).resolve() if args.ground_truth else None,
        use_ground_truth_path_matches=args.use_ground_truth_path_matches,
    )

    pairs = discover_benchmark_pairs(config.benchmarks_dir)
    if not pairs:
        config.output_dir.mkdir(parents=True, exist_ok=True)
        (config.output_dir / "results.json").write_text(
            json.dumps({"results": [], "summary": {}, "subset_summary": {}}, indent=2),
            encoding="utf-8",
        )
        print_no_benchmarks_message(config)
        return 1

    if not config.execute:
        print("Dry-run mode: tool commands will NOT be executed.")
        print("Use --execute to collect real T_align/T_smt/SMT_calls and verification outputs.")
        print("")

    runners: list[ToolRunner] = [
        NaiveMatchingRunner(config),
        VeriBinAlignRunner(config),
        FmcadAlignRunner(config),
    ]

    results: list[GroupResult] = []
    for pair in pairs:
        print(f"[+] {pair.pair_id}: {pair.left.name} vs {pair.right.name}")
        for runner in runners:
            print(f"    - {runner.group.value}")
            results.append(runner.run(pair))

    ground_truth = load_ground_truth(config.ground_truth_path)
    ranking_ground_truth = load_ranking_ground_truth(config.ground_truth_path)
    write_reports(
        results,
        pairs,
        config.output_dir,
        ground_truth,
        ranking_ground_truth,
        render_tables=True,
    )
    print(f"Wrote evaluation reports to {config.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
