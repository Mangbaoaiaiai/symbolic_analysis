from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from loop_frontier_audit import classify_smt_frontiers  # noqa: E402
import claripy  # noqa: E402
import se_script_improved as se  # noqa: E402


class LoopFrontierAuditTests(unittest.TestCase):
    def test_only_unsat_frontiers_are_removed(self) -> None:
        result = classify_smt_frontiers(
            [
                """
                (declare-fun x () (_ BitVec 8))
                (assert (= x #x00))
                (assert (= x #x01))
                """,
                """
                (declare-fun x () (_ BitVec 8))
                (assert (= x #x01))
                """,
            ],
            timeout_ms=1_000,
        )
        self.assertEqual(result.infeasible_count, 1)
        self.assertEqual(result.feasible_count, 1)
        self.assertTrue(result.blocks_completeness)
        self.assertEqual(
            [record.status for record in result.records],
            ["unsat", "sat"],
        )

    def test_parse_failure_blocks_completeness(self) -> None:
        result = classify_smt_frontiers(
            ["(assert"],
            timeout_ms=1_000,
        )
        self.assertEqual(result.unknown_count, 1)
        self.assertTrue(result.blocks_completeness)

    def test_all_infeasible_frontiers_are_nonblocking(self) -> None:
        result = classify_smt_frontiers(
            [
                """
                (declare-fun x () (_ BitVec 8))
                (assert (= x #x00))
                (assert (= x #x01))
                """,
            ],
            timeout_ms=1_000,
        )
        self.assertEqual(result.infeasible_count, 1)
        self.assertFalse(result.blocks_completeness)

    def test_stop_on_blocking_marks_remaining_states_not_checked(self) -> None:
        result = classify_smt_frontiers(
            [
                "(declare-fun x () (_ BitVec 8))\n(assert (= x #x01))",
                "(declare-fun y () (_ BitVec 8))\n(assert (= y #x01))",
            ],
            timeout_ms=1_000,
            stop_on_blocking=True,
        )
        self.assertEqual(result.feasible_count, 1)
        self.assertEqual(result.not_checked_count, 1)
        self.assertTrue(result.blocks_completeness)

    def test_se_integration_keeps_feasible_frontier_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            executor = object.__new__(se.BenchmarkSymbolicExecution)
            executor.output_prefix = str(directory / "symbolic_oldV")
            value = claripy.BVS("value", 8)
            infeasible = SimpleNamespace(
                solver=SimpleNamespace(
                    constraints=[value == 0, value == 1]
                )
            )
            feasible = SimpleNamespace(
                solver=SimpleNamespace(constraints=[value == 1])
            )
            blocking, audit = executor.audit_loop_bound_states(
                [infeasible, feasible]
            )
            persisted = (
                directory / "symbolic_oldV_loop_bound_audit.json"
            ).is_file()
        self.assertEqual(blocking, [feasible])
        self.assertEqual(audit["infeasible_count"], 1)
        self.assertEqual(audit["feasible_count"], 1)
        self.assertTrue(audit["blocks_completeness"])
        self.assertTrue(persisted)


if __name__ == "__main__":
    unittest.main()
