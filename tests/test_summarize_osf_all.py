import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.summarize_osf_all import (
    apply_label_override,
    classify,
    load_label_overrides,
    load_results,
    localize_artifact_path,
    path_evidence,
    path_evidence_priority,
)


class SummarizeOsfAllTests(unittest.TestCase):
    def test_classify_determinate_and_unknown(self) -> None:
        item = {}
        self.assertEqual(
            classify(item, {"status": "ok", "ground_truth": "True", "prediction": "True"}),
            ("correct_eq", "yes"),
        )
        self.assertEqual(
            classify(item, {"status": "ok", "ground_truth": "False", "prediction": "True"}),
            ("wrong_eq", "no"),
        )
        self.assertEqual(
            classify(item, {"status": "ok", "ground_truth": "False", "prediction": ""}),
            ("unk", ""),
        )

    def test_path_evidence_requires_both_sides(self) -> None:
        with TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            paths = root / "cases" / "family" / "program" / "Eq" / "paths"
            paths.mkdir(parents=True)
            (paths / "symbolic_oldV_path_1.txt").write_text("old", encoding="utf-8")
            evidence = path_evidence(root, "family/program/Eq")
            self.assertEqual(evidence["path_status"], "partial")
            (paths / "symbolic_newV_path_1.txt").write_text("new", encoding="utf-8")
            (paths / "symbolic_oldV_exploration.json").write_text(
                json.dumps({"complete": True}), encoding="utf-8"
            )
            evidence = path_evidence(root, "family/program/Eq")
            self.assertEqual(evidence["path_status"], "complete")
            self.assertEqual(evidence["old_exploration_complete"], "True")

    def test_container_artifact_path_is_localized_to_checkout(self) -> None:
        with TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            localized = localize_artifact_path(
                "/workspace/symbolic_analysis/benchmarks/example/cases/fam/prog/Eq/paths",
                path_root=root / "benchmarks" / "merged",
                repo_root=root,
            )
            self.assertEqual(
                localized,
                root / "benchmarks/example/cases/fam/prog/Eq/paths",
            )

    def test_later_complete_path_root_can_override_earlier(self) -> None:
        earlier = {
            "path_status": "complete",
            "old_path_count": 20,
            "new_path_count": 20,
        }
        later = {
            "path_status": "complete",
            "old_path_count": 3,
            "new_path_count": 1,
        }
        self.assertGreater(
            path_evidence_priority(earlier, 0, prefer_later_root=False),
            path_evidence_priority(later, 1, prefer_later_root=False),
        )
        self.assertGreater(
            path_evidence_priority(later, 1, prefer_later_root=True),
            path_evidence_priority(earlier, 0, prefer_later_root=True),
        )

    def test_raw_verification_reports_fill_missing_results(self) -> None:
        with TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            report = root / "raw" / "fam" / "case_Neq" / "fmcad" / "verification_report.json"
            report.parent.mkdir(parents=True)
            report.write_text(
                json.dumps({"verdict": "NEQ", "prediction": False}),
                encoding="utf-8",
            )
            rows = load_results([root], result_group="fmcad_align")
            self.assertEqual(rows["fam/case_Neq"]["status"], "ok")
            self.assertEqual(rows["fam/case_Neq"]["ground_truth"], "False")
            self.assertEqual(rows["fam/case_Neq"]["prediction"], "False")

    def test_label_audit_overrides_are_loaded_explicitly(self) -> None:
        with TemporaryDirectory() as raw_tmp:
            path = Path(raw_tmp) / "audit.csv"
            path.write_text(
                "case_id,outcome_override\n"
                "fam/identical_Neq,label_inconsistent\n"
                "fam/unchanged_Neq,\n",
                encoding="utf-8",
            )
            self.assertEqual(
                load_label_overrides(path),
                {"fam/identical_neq": "label_inconsistent"},
            )

    def test_label_override_changes_only_incorrect_verdicts(self) -> None:
        self.assertEqual(
            apply_label_override("wrong_eq", "no", "label_inconsistent"),
            ("label_inconsistent", ""),
        )
        self.assertEqual(
            apply_label_override("wrong_neq", "no", "label_inconsistent"),
            ("label_inconsistent", ""),
        )
        self.assertEqual(
            apply_label_override("wrong_neq", "no", "undefined_behavior"),
            ("undefined_behavior", ""),
        )
        self.assertEqual(
            apply_label_override("correct_eq", "yes", "label_inconsistent"),
            ("correct_eq", "yes"),
        )


if __name__ == "__main__":
    unittest.main()
