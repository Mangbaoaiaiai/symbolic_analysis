from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from path_relation_policy import (  # noqa: E402
    classify_path_relation,
    classify_source_feasibility,
)


class PathRelationPolicyTests(unittest.TestCase):
    def test_unsat_source_skips_remaining_candidates(self) -> None:
        decision = classify_source_feasibility("unsat")
        self.assertEqual(decision.status, "vacuous_source")
        self.assertTrue(decision.skip_remaining_candidates)
        self.assertTrue(decision.coverage_obligation_vacuous)
        self.assertFalse(decision.count_unknown)

    def test_sat_source_continues_candidate_matching(self) -> None:
        decision = classify_source_feasibility("sat")
        self.assertEqual(decision.status, "source_feasible")
        self.assertFalse(decision.skip_remaining_candidates)

    def test_unknown_source_is_not_removed(self) -> None:
        decision = classify_source_feasibility("unknown")
        self.assertEqual(decision.status, "source_feasibility_unknown")
        self.assertFalse(decision.skip_remaining_candidates)
        self.assertTrue(decision.count_unknown)

    def test_missing_source_probe_fails_closed(self) -> None:
        decision = classify_source_feasibility(None)
        self.assertEqual(
            decision.status,
            "source_feasibility_invalid",
        )
        self.assertFalse(decision.coverage_obligation_vacuous)
        self.assertTrue(decision.count_unknown)

    def test_unsat_intersection_is_vacuous_but_not_program_eq(self) -> None:
        decision = classify_path_relation(overlap_status="unsat")
        self.assertEqual(decision.status, "vacuous_intersection")
        self.assertTrue(decision.coverage_obligation_vacuous)
        self.assertFalse(decision.may_support_program_eq)
        self.assertFalse(decision.may_confirm_program_neq)

    def test_unsat_source_is_vacuous_at_sat_overlap(self) -> None:
        decision = classify_path_relation(
            overlap_status="sat",
            source_feasible=False,
        )
        self.assertEqual(decision.status, "vacuous_source")
        self.assertTrue(decision.coverage_obligation_vacuous)

    def test_unreplayed_difference_is_not_confirmed_neq(self) -> None:
        decision = classify_path_relation(
            overlap_status="sat",
            source_feasible=True,
            semantic_status=False,
            replay_confirmed=False,
        )
        self.assertEqual(decision.status, "unresolved_semantics")
        self.assertFalse(decision.may_confirm_program_neq)

    def test_replayed_difference_confirms_neq(self) -> None:
        decision = classify_path_relation(
            overlap_status="sat",
            source_feasible=True,
            semantic_status=False,
            replay_confirmed=True,
        )
        self.assertEqual(decision.status, "confirmed_neq")
        self.assertTrue(decision.may_confirm_program_neq)

    def test_unknown_feasibility_stays_unknown(self) -> None:
        decision = classify_path_relation(
            overlap_status="sat",
            source_feasible=None,
        )
        self.assertEqual(decision.status, "unknown")
        self.assertFalse(decision.coverage_obligation_vacuous)


if __name__ == "__main__":
    unittest.main()
