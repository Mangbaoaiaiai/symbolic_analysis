import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.merge_osf_support_results import custom_row, normalize_case_key


class MergeOsfSupportResultsTests(unittest.TestCase):
    def test_result_ids_are_case_insensitive_but_keep_polarity(self):
        self.assertEqual(
            normalize_case_key("raytrace/intersect_NEq"),
            normalize_case_key("raytrace/intersect_Neq"),
        )
        self.assertNotEqual(
            normalize_case_key("raytrace/intersect_Eq"),
            normalize_case_key("raytrace/intersect_Neq"),
        )

    def test_custom_row_uses_report_counts_not_a_stale_path_directory(self):
        with TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            report_path = (
                root
                / "raytrace"
                / "intersect_Neq"
                / "fmcad"
                / "verification_report.json"
            )
            report_path.parent.mkdir(parents=True)
            report_path.write_text(
                json.dumps(
                    {
                        "verdict": "NEQ",
                        "old_path_count": 3,
                        "new_path_count": 3,
                        "exploration": {
                            "symbolic_oldV": {"complete": True},
                            "symbolic_newV": {"complete": True},
                        },
                        "definedness_audit": {
                            "checks": 1,
                            "classification_counts": {"defined_neq": 1},
                        },
                    }
                ),
                encoding="utf-8",
            )
            base = {
                "case_id": "raytrace/intersect_NEq",
                "support_status": "unsupported",
                "outcome": "not_attempted",
                "both_complete": "False",
            }
            manifest = {
                "case_id": "raytrace/intersect_NEq",
                "family": "raytrace",
                "program": "intersect",
                "label": "NEQ",
                "support_status": "supported_function",
            }
            result = {
                "pair_id": "raytrace/intersect_Neq",
                "status": "ok",
                "error": "",
            }

            row = custom_row(base, manifest, result, root, {})

            self.assertEqual(row["old_path_count"], "3")
            self.assertEqual(row["new_path_count"], "3")
            self.assertEqual(row["artifact_status"], "both_sides")
            self.assertTrue(row["both_complete"])
            self.assertEqual(row["outcome"], "correct_neq")
            self.assertEqual(
                row["provisional_merge_source"],
                "small_osf_complex_type_regression",
            )


if __name__ == "__main__":
    unittest.main()
