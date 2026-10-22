import unittest
import csv
import json
import tempfile
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

from run_evaluation import (
    compute_ranking_stats,
    path_truth_status,
    select_benchmark_pairs,
)
from scripts.summarize_paper_subset import canonical_case_id
from scripts.summarize_paper_eval import (
    classify,
    failure_case_id,
    summarize_variant,
)
from scripts.run_suite import domain_arguments, retry_reasons
from symbolic_analysis.profile import FULL_INPUT_SPACE, profile_for_input_domains


class PaperSubsetTests(unittest.TestCase):
    def test_pair_selector_is_case_insensitive(self) -> None:
        pairs = [
            SimpleNamespace(pair_id="CLEVER/LoopMult10_Neq"),
            SimpleNamespace(pair_id="CLEVER/LoopMult10_Eq"),
        ]
        selected = select_benchmark_pairs(pairs, ["CLEVER/LoopMult10_NEq"])
        self.assertEqual(
            [pair.pair_id for pair in selected],
            ["CLEVER/LoopMult10_Neq"],
        )

    def test_fixed_62_manifest_identity(self) -> None:
        path = Path(__file__).resolve().parents[1] / "configs" / "paper_62.csv"
        with path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 62)
        self.assertEqual(
            Counter(row["ground_truth"] for row in rows),
            Counter({"EQ": 33, "NEQ": 29}),
        )
        self.assertEqual(
            len({row["case_id"].lower() for row in rows}),
            62,
        )
        self.assertEqual(len({row["family"].lower() for row in rows}), 9)
        self.assertTrue(
            {
                "bess/bessi0_Eq",
                "bess/bessj0_Eq",
                "gam/ei_Eq",
                "CLEVER/LoopMult2_NEq",
                "ran/gammln_NEq",
            }
            <= {row["case_id"] for row in rows}
        )

    def test_source_manifest_matches_fixed_62_cases(self) -> None:
        paper_path = (
            Path(__file__).resolve().parents[1]
            / "configs"
            / "paper_62.csv"
        )
        source_path = (
            Path(__file__).resolve().parents[1]
            / "configs"
            / "paper_source_manifest.csv"
        )
        with paper_path.open(encoding="utf-8", newline="") as stream:
            paper = list(csv.DictReader(stream))
        with source_path.open(encoding="utf-8", newline="") as stream:
            source = list(csv.DictReader(stream))
        self.assertEqual(len(source), 62)
        self.assertEqual(
            {canonical_case_id(row["case_id"]) for row in source},
            {canonical_case_id(row["case_id"]) for row in paper},
        )
        self.assertTrue(
            all(
                row["osf_old_sha256"]
                and row["osf_new_sha256"]
                and not row["source_case"].startswith(("C:", "E:"))
                for row in source
            )
        )

    def test_moddiff_and_osf_clever_names_share_a_key(self) -> None:
        self.assertEqual(
            canonical_case_id("ModDiff/Add_Eq"),
            canonical_case_id("CLEVER/Add_Eq"),
        )

    def test_negative_labels_are_case_insensitive(self) -> None:
        self.assertEqual(
            canonical_case_id("Ran/gammln_NEq"),
            canonical_case_id("ran/gammln_Neq"),
        )

    def test_pow_and_power_names_share_a_key(self) -> None:
        self.assertEqual(
            canonical_case_id("power/test_Eq"),
            canonical_case_id("pow/test_Eq"),
        )

    def test_classify_detects_false_verdicts(self) -> None:
        self.assertEqual(classify("EQ", True), "correct_eq")
        self.assertEqual(classify("EQ", False), "wrong_eq")
        self.assertEqual(classify("NEQ", True), "wrong_neq")
        self.assertEqual(classify("UNK", False), "unk")

    def test_path_failure_maps_to_candidate_id(self) -> None:
        self.assertEqual(failure_case_id("ell/rc/Eq"), "ell/rc_eq")

    def test_correct_rate_uses_fixed_candidate_denominator(self) -> None:
        rows = [
            {
                "path_status": "complete",
                "outcome": "correct_eq",
            },
            {
                "path_status": "complete",
                "outcome": "unk",
            },
            {
                "path_status": "path_failed",
                "outcome": "path_failed",
            },
        ]
        summary = summarize_variant("fixed", rows)
        self.assertEqual(summary["correct_rate_denominator"], 3)
        self.assertEqual(summary["path_complete"], 2)
        self.assertAlmostEqual(summary["correct_rate_percent"], 100.0 / 3.0)

    def test_ranking_queries_require_fully_known_overlap_status(self) -> None:
        statuses = path_truth_status(
            {
                "queries": [
                    {
                        "query": "old_0",
                        "related_targets": ["new_0"],
                        "unknown_targets": ["new_1"],
                    },
                    {
                        "query": "old_1",
                        "related_targets": ["new_0"],
                        "unknown_targets": [],
                    },
                    {
                        "query": "old_2",
                        "related_targets": [],
                        "unknown_targets": [],
                    },
                ]
            }
        )
        self.assertEqual(statuses["old_0"], "unknown")
        stats = compute_ranking_stats(
            {"old_0": ["new_0"], "old_1": ["new_0"], "old_2": ["new_0"]},
            {
                "old_0": {"new_0"},
                "old_1": {"new_0"},
                "old_2": set(),
            },
            statuses,
        )
        self.assertEqual(stats.all_queries, 3)
        self.assertEqual(stats.valid_queries, 1)
        self.assertEqual(stats.unknown_queries, 1)
        self.assertEqual(stats.no_related_queries, 1)

    def test_input_domain_metadata_distinguishes_paper_and_full_space(self) -> None:
        paper = profile_for_input_domains(-100, 100, -100.0, 100.0)
        full = profile_for_input_domains(None, None, None, None)
        self.assertEqual(
            paper["symbolic_execution"]["integer_domain"], [-100, 100]
        )
        self.assertEqual(
            paper["symbolic_execution"]["floating_point_domain"],
            [-100.0, 100.0],
        )
        self.assertEqual(
            full["symbolic_execution"]["integer_domain"], FULL_INPUT_SPACE
        )
        self.assertEqual(
            full["symbolic_execution"]["floating_point_domain"],
            FULL_INPUT_SPACE,
        )

    def test_full_input_space_omits_all_bound_cli_arguments(self) -> None:
        self.assertEqual(domain_arguments(None, None, None, None), [])
        self.assertEqual(
            domain_arguments("-100", "100", "-100.0", "100.0"),
            [
                "--int-min",
                "-100",
                "--int-max",
                "100",
                "--float-min",
                "-100.0",
                "--float-max",
                "100.0",
            ],
        )

    def test_retry_selection_includes_incomplete_exploration(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            case_dir = root / "cases" / "ell" / "zbrent" / "Eq"
            paths_dir = case_dir / "paths"
            paths_dir.mkdir(parents=True)
            for prefix in ("symbolic_oldV", "symbolic_newV"):
                (paths_dir / f"{prefix}_path_1.txt").write_text(
                    "(assert true)\n", encoding="utf-8"
                )
            (paths_dir / "symbolic_oldV_exploration.json").write_text(
                json.dumps({"complete": True}), encoding="utf-8"
            )
            (paths_dir / "symbolic_newV_exploration.json").write_text(
                json.dumps(
                    {
                        "complete": False,
                        "incomplete_reasons": ["loop_bound"],
                    }
                ),
                encoding="utf-8",
            )
            (paths_dir / "symbolic_newV_failure.json").write_text(
                json.dumps({"status": "incomplete"}), encoding="utf-8"
            )
            (root / "manifest.json").write_text(
                json.dumps(
                    {
                        "pairs": [
                            {
                                "source_case": (
                                    "../../osf_prepared/benchmarks_typed/"
                                    "ell/zbrent/Eq"
                                ),
                                "paths_dir": "cases/ell/zbrent/Eq/paths",
                            }
                        ],
                        "failures": [],
                    }
                ),
                encoding="utf-8",
            )
            (root / "generation_summary.json").write_text(
                json.dumps(
                    {
                        "failures": [
                            {"case": "bess/dawson/Eq", "error": "no paths"}
                        ]
                    }
                ),
                encoding="utf-8",
            )

            reasons = retry_reasons(root)

        self.assertEqual(
            reasons["ell/zbrent/eq"],
            [
                "incomplete_symbolic_newV_exploration",
                "symbolic_newV_failure_marker",
            ],
        )
        self.assertEqual(reasons["bess/dawson/eq"], ["generation_failed"])

    def test_retry_selection_treats_missing_manifest_as_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            paths_dir = root / "cases" / "airy" / "sphbes" / "Eq" / "paths"
            paths_dir.mkdir(parents=True)
            for prefix in ("symbolic_oldV", "symbolic_newV"):
                (paths_dir / f"{prefix}_path_1.txt").write_text(
                    "(assert true)\n", encoding="utf-8"
                )
            (paths_dir / "symbolic_oldV_exploration.json").write_text(
                json.dumps({"complete": True}), encoding="utf-8"
            )
            (root / "manifest.json").write_text(
                json.dumps(
                    {
                        "pairs": [
                            {
                                "source_case": "airy/sphbes/Eq",
                                "paths_dir": "cases/airy/sphbes/Eq/paths",
                            }
                        ],
                        "failures": [],
                    }
                ),
                encoding="utf-8",
            )

            reasons = retry_reasons(root)

        self.assertEqual(
            reasons["airy/sphbes/eq"],
            ["missing_symbolic_newV_exploration"],
        )


if __name__ == "__main__":
    unittest.main()
