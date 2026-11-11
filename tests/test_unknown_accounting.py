"""Regression tests for final obligations versus historical solver UNKNOWNs."""
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import verify_ranked_path_equivalence as v


class UnknownAccountingTests(unittest.TestCase):
    def tearDown(self):
        v.configure_smt_audit(None)

    def record(self, source="old", target="new", equivalent=True, **changes):
        record = {"query": source, "match": target, "matched": True,
                  "source_subset_targets": True,
                  "semantic_checks": [{"target": target, "equivalent": equivalent, "details": {}}]}
        record.update(changes)
        return record

    def queue(self, *, reverse_missing=False, semantic=None, confirmed=False, malformed=False):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for side in ("old", "new"):
                (root / f"symbolic_{side}V_path_1.txt").write_text(
                    "(declare-fun x () (_ BitVec 32))\n(assert (= x (_ bv1 32)))\n")
                (root / f"symbolic_{side}V_exploration.json").write_text(json.dumps({
                    "complete": True, "proof_eligible": True, "incomplete_reasons": [],
                    "terminating_path_count": 1, "active_count": 0, "timeout_count": 0,
                    "loop_bound_event_count": 0, "errored_count": 0, "max_paths": 128}))

            def directional(sources, targets, *args, **kwargs):
                record = self.record(sources[0].stem, targets[0].stem)
                if semantic is not None:
                    record["semantic_checks"] = [{"target": targets[0].stem, **semantic}]
                if malformed:
                    record.pop("semantic_checks")
                records = [] if reverse_missing and kwargs["direction"] == "new_to_old" else [record]
                return {"records": records, "source_count": 1, "processed_source_count": len(records),
                        "success": True, "matching_complete": True, "semantic_checks_complete": True,
                        "smt_calls": 0, "t_smt": 0, "unknowns": 4, "semantic_modes": {},
                        "matched_source_count": 1, "confirmed_mismatches": [{"replay": {"confirmed": True}}] if confirmed else []}
            with mock.patch.object(v, "verify_complete_directional_cover", side_effect=directional):
                return v.verify_ranked_queue(root, None, 1000, True, None, None,
                                             complete_matching=True, static_only=True)

    def test_earlier_unknown_does_not_veto_later_union_proof(self):
        source = Path("symbolic_oldV_path_1.txt")
        targets = [Path(f"symbolic_newV_path_{i}.txt") for i in (1, 2)]
        relation = (True, 0.0, 1, {"input_overlap": "sat"})
        with mock.patch.object(v, "verify_semantic_path_relation", return_value=relation), \
             mock.patch.object(v, "check_path_union_equal", side_effect=[
                 (None, 0.0, {"source_subset_targets": None, "targets_subset_source": True}),
                 (True, 0.0, {"source_subset_targets": True, "targets_subset_source": True}),
             ]):
            result = v.verify_directional_cover([source], targets, {}, 1000)
        self.assertEqual(result["unknowns"], 1)
        self.assertTrue(result["success"])

    def test_queue_ignores_historical_counter_only_when_obligations_proven(self):
        result = self.queue()
        self.assertEqual(result["verdict"], "EQ")
        self.assertEqual(result["unknowns"], 8)
        self.assertEqual(result["unresolved_required_obligation_count"], 0)

    def test_optional_unknown_candidate_is_not_required(self):
        source, first, second = Path("old.txt"), Path("new1.txt"), Path("new2.txt")
        with mock.patch.object(v, "verify_semantic_path_relation", side_effect=[
            (None, 0, 1, {"input_overlap": "unknown"}),
            (True, 0, 1, {"input_overlap": "sat"}),
        ]), mock.patch.object(v, "check_path_union_equal", return_value=(
            True, 0, {"source_subset_targets": True, "targets_subset_source": True})):
            result = v.verify_directional_cover([source], [first, second], {}, 1000)
        self.assertTrue(result["success"])

    def test_unknown_feasibility_can_be_replaced_by_valid_cover(self):
        proof = v.summarize_required_obligations(["old"], [self.record(source_feasibility="unknown")], "forward")
        self.assertTrue(proof["success"])

    def test_vacuity_requires_unsat(self):
        record = {"query": "old", "coverage_obligation_vacuous": True, "source_feasibility": "unsat"}
        self.assertTrue(v.summarize_required_obligations(["old"], [record], "forward")["success"])
        record["source_feasibility"] = "unknown"
        proof = v.summarize_required_obligations(["old"], [record], "forward")
        self.assertFalse(proof["success"])
        self.assertEqual(v.classify_directional_failure(proof, []), "proof_accounting_inconsistent")

    def test_required_coverage_unknown_blocks(self):
        record = self.record(matched=False, source_subset_targets=None)
        proof = v.summarize_required_obligations(["old"], [record], "forward")
        self.assertEqual(v.classify_directional_failure(proof, []), "matching_incomplete")
        self.assertEqual(proof["unresolved_required_obligations"][0]["reason"], "coverage_query_unknown")

    def test_semantic_unknown_blocks(self):
        result = self.queue(semantic={"equivalent": None, "details": {}})
        self.assertEqual(result["verdict"], "UNK")
        self.assertEqual(result["failure_stage"], "semantic_checks_incomplete")

    def test_reverse_missing_blocks_even_with_success_flags(self):
        result = self.queue(reverse_missing=True)
        self.assertEqual(result["verdict"], "UNK")
        self.assertEqual(result["failure_stage"], "matching_incomplete")

    def test_early_exit_is_not_complete_proof(self):
        proof = v.summarize_required_obligations(["old", "other"], [self.record()], "forward")
        self.assertFalse(proof["success"])
        self.assertEqual(proof["unresolved_required_obligation_count"], 2)
        self.assertFalse(v.summarize_required_obligations(["old"], [], "forward")["success"])

    def test_unreplayed_abstract_difference_has_specific_classification(self):
        result = self.queue(semantic={"equivalent": False, "details": {
            "return_value_equivalent": False, "counterexample": {"inputs": [1]},
            "return_replay": {"confirmed": False, "reason": "no_observable_output_diff"}}})
        self.assertEqual(result["verdict"], "UNK")
        self.assertEqual(result["failure_stage"], "abstract_mismatch_without_confirmed_replay")
        self.assertTrue(result["abstract_difference_candidates"])

    def test_overlap_replay_seed_is_not_abstract_difference(self):
        record = self.record(equivalent=None)
        record["semantic_checks"][0]["details"] = {
            "input_overlap": "sat", "static_model_counterexample": {"inputs": [1]},
            "static_model_replay": {"reason": "no_observable_output_diff"}}
        self.assertEqual(v.abstract_difference_candidates([record]), [])

    def test_confirmed_neq_survives_historical_unknowns(self):
        result = self.queue(confirmed=True)
        self.assertEqual(result["verdict"], "NEQ")
        self.assertGreater(result["unknowns"], 0)

    def test_missing_semantic_evidence_cannot_be_replaced_by_aggregate_flags(self):
        result = self.queue(malformed=True)
        self.assertEqual(result["verdict"], "UNK")
        self.assertEqual(result["failure_stage"], "semantic_checks_incomplete")

    def test_non_required_inverse_union_unknown_in_both_modes(self):
        for fn in (v.verify_directional_cover, v.verify_complete_directional_cover):
            with self.subTest(fn=fn.__name__), \
                 mock.patch.object(v, "verify_path_overlap", return_value=(v.sat, 0)), \
                 mock.patch.object(v, "verify_semantic_path_relation", return_value=(True, 0, 1, {"input_overlap": "sat"})), \
                 mock.patch.object(v, "check_path_union_equal", return_value=(
                     None, 0, {"source_subset_targets": True, "targets_subset_source": None})):
                result = fn([Path("old.txt")], [Path("new.txt")], {}, 1000)
                self.assertTrue(result["success"])
                self.assertTrue(result["semantic_checks_complete"])
                self.assertGreater(result["unknowns"], 0)

    def test_history_counts_query_events_not_legacy_counter_and_preserves_unknown(self):
        with tempfile.TemporaryDirectory() as raw:
            v.configure_smt_audit(Path(raw))
            def query():
                return v.persist_smt_query(v.Solver(), stage="test", timeout_ms=1,
                                           elapsed=0, status="unknown")
            for _ in range(2):
                v.proof_query_call("coverage", "forward", "old", ["new"], query)
            proof = v.summarize_required_obligations(["old"], [self.record()], "forward")
            history = v.historical_unknown_summary(proof["required_obligations"])
            self.assertEqual(history["historical_unknown_query_count"], 2)
            self.assertEqual(len(history["discharged_historical_unknown_events"]), 2)
            self.assertEqual(len({e["event_id"] for e in history["historical_unknown_events"]}), 2)
            self.assertTrue(all(e["status"] == "unknown" for e in history["historical_unknown_events"]))
            self.assertTrue(all(json.loads(Path(e["query_path"]).with_suffix(".json").read_text())["status"] == "unknown"
                                for e in history["historical_unknown_events"]))

    def test_duplicate_source_and_false_matched_fail_closed(self):
        for records in ([self.record(), self.record()], [self.record(source_subset_targets=False)]):
            proof = v.summarize_required_obligations(["old"], records, "forward")
            self.assertFalse(proof["success"])
            self.assertEqual(v.classify_directional_failure(proof, []), "proof_accounting_inconsistent")


if __name__ == "__main__":
    unittest.main()
