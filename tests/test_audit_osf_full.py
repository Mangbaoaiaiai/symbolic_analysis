import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.audit_osf_full import (
    aggregate_target_verdict,
    classify,
    execution_failure_detail,
    extract_target_stdout,
    failure_category,
    failure_paths_dir,
    normalize_case,
    path_evidence,
    public_message,
    select_stage,
    target_audit,
    valid_verdict,
)


def stage(**overrides):
    value = {
        "attempt": "stage1",
        "evaluation_status": "ok",
        "verdict": "EQ",
        "both_complete": True,
        "report_confirms_both_complete": True,
        "artifact_status": "both_sides",
    }
    value.update(overrides)
    return value


class AuditOsfFullTests(unittest.TestCase):
    def test_target_stdout_is_partitioned_without_attribution(self):
        names = ["normalize", "intersect"]
        stdout = (
            "Target normalize: 0x1p+0 0x0p+0\n"
            "Target intersect: 0\n"
            "Result: 0\n"
        )
        blocks = extract_target_stdout(stdout, names)
        self.assertEqual(blocks["normalize"], "Target normalize: 0x1p+0 0x0p+0")
        self.assertEqual(blocks["intersect"], "Target intersect: 0")

    def test_target_audit_localizes_only_the_replayed_mismatch(self):
        item = {
            "case_id": "raytrace/raytrace_Eq",
            "support_status": "supported_targets",
            "entry_name": "normalize|intersect",
        }
        events = [
            {
                "target": "normalize",
                "source": "symbolic_oldV_path_1",
                "target_path": "symbolic_newV_path_1",
                "classification": "defined_neq",
                "reason": "observable_output_diff",
                "stdin_sha256": "abc",
                "left_stdout": "Target normalize: same",
                "right_stdout": "Target normalize: same",
                "observable_output_diff": False,
                "return_observation": "encoded_in_target_stdout",
                "global_state_observation": "process_level_aggregate",
            },
            {
                "target": "intersect",
                "source": "symbolic_oldV_path_1",
                "target_path": "symbolic_newV_path_1",
                "classification": "defined_neq",
                "reason": "observable_output_diff",
                "stdin_sha256": "abc",
                "left_stdout": "Target intersect: 0",
                "right_stdout": "Target intersect: 1",
                "observable_output_diff": True,
                "return_observation": "encoded_in_target_stdout",
                "global_state_observation": "process_level_aggregate",
            },
        ]

        rows = target_audit(item, events, "NEQ")

        self.assertEqual(
            {row["target"]: row["status"] for row in rows},
            {"normalize": "UNK", "intersect": "NEQ"},
        )
        self.assertEqual(aggregate_target_verdict(rows), "NEQ")

    def test_complete_case_eq_authorizes_each_joint_target(self):
        item = {
            "case_id": "tcas/tcas_Eq",
            "support_status": "supported_targets",
            "entry_name": "altseptest|Non_Crossing_Biased_Climb",
        }
        rows = target_audit(item, [], "EQ")
        self.assertEqual({row["status"] for row in rows}, {"EQ"})
        self.assertEqual(aggregate_target_verdict(rows), "EQ")

    def test_normalizes_checkout_and_container_case_paths(self):
        expected = "bess/bessj/eq"
        self.assertEqual(
            normalize_case(
                "E:/repo/work/run/paths/cases/bess/bessj/Eq/paths"
            ),
            expected,
        )
        self.assertEqual(
            normalize_case(
                "/workspace/repo/work/osf_prepared/benchmarks_typed/bess/bessj/Eq"
            ),
            expected,
        )

    def test_path_files_do_not_imply_complete_exploration(self):
        with TemporaryDirectory() as tmp:
            paths = Path(tmp)
            (paths / "symbolic_oldV_path_1.txt").write_text("a", encoding="utf-8")
            (paths / "symbolic_newV_path_1.txt").write_text("b", encoding="utf-8")
            evidence = path_evidence(paths, "")
            self.assertEqual(evidence["artifact_status"], "both_sides")
            self.assertFalse(evidence["both_complete"])
            self.assertIn("marker missing", evidence["incomplete_reasons"])

    def test_failure_messages_do_not_publish_generated_paths(self):
        message = public_message(
            "symbolic execution timed out for /workspace/repo/work/case/bin; "
            "see /workspace/repo/work/case/log"
        )
        self.assertEqual(message, "symbolic execution timed out")

    def test_failure_message_preserves_process_diagnostic(self):
        message = public_message(
            "symbolic_oldV: symbolic execution failed for C:/repo/case/bin; "
            "see C:/repo/case/log (symbolic executor terminated by SIGKILL)"
        )
        self.assertEqual(
            message,
            "symbolic_oldV: symbolic execution failed "
            "(symbolic executor terminated by SIGKILL)",
        )

    def test_both_complete_requires_markers_paths_and_no_failure(self):
        with TemporaryDirectory() as tmp:
            paths = Path(tmp)
            for prefix, suffix in (
                ("symbolic_oldV", "a"),
                ("symbolic_newV", "b"),
            ):
                (paths / f"{prefix}_path_1.txt").write_text(
                    suffix, encoding="utf-8"
                )
                (paths / f"{prefix}_exploration.json").write_text(
                    json.dumps({"complete": True}), encoding="utf-8"
                )
            self.assertTrue(path_evidence(paths, "")["both_complete"])
            (paths / "symbolic_newV_failure.json").write_text(
                json.dumps({"error": "timeout"}), encoding="utf-8"
            )
            self.assertFalse(path_evidence(paths, "")["both_complete"])

    def test_sigkill_log_is_reported_as_likely_oom(self):
        with TemporaryDirectory() as tmp:
            paths = Path(tmp)
            (paths / "symbolic_oldV_symbolic_execution.log").write_text(
                "Exploring paths...\nreturncode=-9\n", encoding="utf-8"
            )
            self.assertEqual(
                execution_failure_detail(paths, "symbolic_oldV"),
                "symbolic executor terminated by SIGKILL (typically OOM)",
            )

    def test_failure_record_recovers_paths_directory_from_log_path(self):
        with TemporaryDirectory() as tmp:
            paths = Path(tmp) / "case" / "paths"
            paths.mkdir(parents=True)
            log = paths / "symbolic_oldV_symbolic_execution.log"
            log.write_text("returncode=-9\n", encoding="utf-8")
            failure = {
                "error": f"symbolic execution failed for binary; see {log}"
            }
            self.assertEqual(failure_paths_dir(failure, Path(tmp)), paths)

    def test_failure_categories_distinguish_process_and_verifier_unknowns(self):
        common = {
            "support_status": "supported_function",
            "old_path_count": 0,
            "new_path_count": 0,
            "both_complete": False,
        }
        self.assertEqual(
            failure_category(
                {
                    **common,
                    "outcome": "failed",
                    "path_failure": "symbolic execution failed (SIGKILL/OOM)",
                }
            ),
            "sigkill_or_oom",
        )
        self.assertEqual(
            failure_category(
                {
                    **common,
                    "outcome": "unk",
                    "old_path_count": 160,
                    "new_path_count": 0,
                    "both_complete": False,
                    "path_failure": (
                        "symbolic_oldV: symbolic execution failed "
                        "(symbolic executor terminated by SIGKILL)"
                    ),
                }
            ),
            "sigkill_or_oom",
        )
        self.assertEqual(
            failure_category(
                {
                    **common,
                    "outcome": "failed",
                    "path_failure": "symbolic execution timed out",
                }
            ),
            "symbolic_timeout",
        )
        self.assertEqual(
            failure_category(
                {
                    **common,
                    "outcome": "unk",
                    "old_path_count": 2,
                    "new_path_count": 2,
                    "both_complete": True,
                }
            ),
            "verifier_or_semantic_unknown",
        )
        self.assertEqual(
            failure_category(
                {
                    **common,
                    "outcome": "failed",
                    "path_failure": "symbolic execution produced no complete paths",
                    "incomplete_reasons": "symbolic_oldV: timeout",
                }
            ),
            "symbolic_timeout",
        )

    def test_eq_requires_complete_paths_and_report(self):
        self.assertEqual(valid_verdict(stage()), "EQ")
        self.assertEqual(valid_verdict(stage(both_complete=False)), "")
        self.assertEqual(
            valid_verdict(stage(report_confirms_both_complete=False)), ""
        )
        self.assertEqual(valid_verdict(stage(verdict="NEQ", both_complete=False)), "NEQ")

    def test_later_complete_stage_overrides_incomplete_eq(self):
        selected, verdict = select_stage(
            [
                stage(both_complete=False, attempt="stage1"),
                stage(attempt="stage2"),
            ]
        )
        self.assertEqual(verdict, "EQ")
        self.assertEqual(selected["attempt"], "stage2")

    def test_conflicting_stage_verdicts_are_not_trusted(self):
        selected, verdict = select_stage(
            [
                stage(attempt="stage1"),
                stage(attempt="stage2", verdict="NEQ"),
            ]
        )
        self.assertEqual(verdict, "conflicting_stage_verdicts")
        self.assertEqual(selected["attempt"], "stage1")

    def test_unknown_selection_prefers_the_stage_with_best_path_evidence(self):
        selected, verdict = select_stage(
            [
                stage(
                    attempt="stage1",
                    verdict="UNK",
                    both_complete=False,
                    old_path_count=4,
                    new_path_count=4,
                ),
                stage(
                    attempt="stage2",
                    verdict="UNK",
                    both_complete=False,
                    old_path_count=0,
                    new_path_count=0,
                ),
            ]
        )
        self.assertEqual(verdict, "UNK")
        self.assertEqual(selected["attempt"], "stage1")

    def test_label_override_only_replaces_incorrect_verdicts(self):
        self.assertEqual(
            classify("EQ", "EQ", "undefined_behavior", supported=True, attempted=True),
            ("correct_eq", "true"),
        )
        self.assertEqual(
            classify("NEQ", "EQ", "undefined_behavior", supported=True, attempted=True),
            ("undefined_behavior", ""),
        )
        self.assertEqual(
            classify("", "EQ", "", supported=True, attempted=False),
            ("failed", ""),
        )


if __name__ == "__main__":
    unittest.main()
