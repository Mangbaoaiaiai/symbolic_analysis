import csv
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.summarize_method_comparison import (
    MethodInput,
    exclude_case_prefixes,
    load_method_rows,
    match_type_counts,
    parse_method_input,
    prefer_successful_attempts,
    summarize,
)


class SummarizeMethodComparisonTests(unittest.TestCase):
    def test_merges_shards_and_computes_metrics(self) -> None:
        with TemporaryDirectory() as raw_tmp:
            root_a = Path(raw_tmp) / "a"
            root_b = Path(raw_tmp) / "b"
            root_a.mkdir()
            root_b.mkdir()
            fields = [
                "pair_id",
                "subset",
                "group",
                "status",
                "ground_truth",
                "prediction",
                "confusion",
                "hit_at_1",
                "hit_at_3",
                "mrr",
                "ranking_queries",
            ]
            rows_a = [
                ["Fam/A_Eq", "Fam", "hybrid", "ok", "True", "True", "TP", "100", "100", "1.0", "1"],
                ["Fam/A_Neq", "Fam", "other", "ok", "False", "", "", "50", "100", "0.75", "2"],
            ]
            rows_b = [
                ["Fam/B_Eq", "Fam", "hybrid", "failed", "True", "", "", "", "", "", ""],
            ]
            for root, rows in ((root_a, rows_a), (root_b, rows_b)):
                with (root / "results.csv").open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(fields)
                    writer.writerows(rows)
            report_path = root_a / "raw" / "case" / "fmcad" / "verification_report.json"
            report_path.parent.mkdir(parents=True)
            report_path.write_text(
                json.dumps(
                    {
                        "matches": [{"match_type": "one_to_one_exact"}],
                        "reverse_matches": [{"match_type": "one_to_many_exact_cover"}],
                    }
                ),
                encoding="utf-8",
            )

            rows = load_method_rows(
                MethodInput(name="hybrid", root=root_a, group="hybrid")
            )
            rows += load_method_rows(
                MethodInput(name="hybrid", root=root_b, group="hybrid")
            )
            summary = summarize(
                MethodInput(name="hybrid", root=Path("."), group="hybrid"),
                rows,
                expected_cases=4,
                matches=match_type_counts(root_a),
            )
            self.assertEqual(summary["cases_run"], 2)
            self.assertEqual(summary["correct_determinate"], 1)
            self.assertEqual(summary["unk"], 0)
            self.assertEqual(summary["failed"], 1)
            self.assertEqual(summary["missing_cases"], 2)
            self.assertEqual(summary["ranking_queries"], 1)
            self.assertAlmostEqual(summary["hit_at_1_percent"], 100.0)
            self.assertAlmostEqual(summary["hit_at_3_percent"], 100.0)
            self.assertAlmostEqual(summary["mrr"], 1.0)
            self.assertEqual(summary["one_to_many_records"], 1)

    def test_group_selector_is_parsed(self) -> None:
        item = parse_method_input("Hybrid:fmcad_align=results/run")
        self.assertEqual(item.name, "Hybrid")
        self.assertEqual(item.group, "fmcad_align")
        self.assertEqual(item.root, Path("results/run"))

    def test_exclude_case_prefix(self) -> None:
        rows = [
            {"pair_id": "gam/gcf_Eq"},
            {"pair_id": "gam/ei_Eq"},
        ]
        remaining = exclude_case_prefixes(rows, ["gam/gcf_"])
        self.assertEqual(remaining, [{"pair_id": "gam/ei_Eq"}])

    def test_retry_prefers_successful_attempt(self) -> None:
        rows = [
            {"pair_id": "fam/case", "status": "failed"},
            {"pair_id": "fam/case", "status": "ok"},
        ]
        self.assertEqual(
            prefer_successful_attempts(rows),
            [{"pair_id": "fam/case", "status": "ok"}],
        )


if __name__ == "__main__":
    unittest.main()
