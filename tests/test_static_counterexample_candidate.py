from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import static_counterexample_candidate as candidates  # noqa: E402


class StaticCounterexampleCandidateTests(unittest.TestCase):
    def test_query_match_aliases_are_canonicalized(self) -> None:
        record = candidates.canonicalize_path_identity(
            {
                "query": "symbolic_oldV_path_3",
                "match": "symbolic_newV_path_7",
                "counterexample_source": "static_overlap_model",
            },
            task_uid="task",
            query_kind="return_value_counterexample",
            direction="old_to_new",
        )
        self.assertEqual(record["old_path_id"], "symbolic_oldV_path_3")
        self.assertEqual(record["new_path_id"], "symbolic_newV_path_7")
        self.assertEqual(record["direction"], "old_to_new")
        self.assertTrue(record["candidate_id"].startswith("cex-"))

    def test_reverse_direction_maps_source_to_new_path(self) -> None:
        record = candidates.canonicalize_path_identity(
            {
                "source": "symbolic_newV_path_8.txt",
                "target": "symbolic_oldV_path_2.txt",
            },
            task_uid="task",
            query_kind="output_counterexample",
            direction="new_to_old",
        )
        self.assertEqual(record["old_path_id"], "symbolic_oldV_path_2")
        self.assertEqual(record["new_path_id"], "symbolic_newV_path_8")

    def test_conflicting_aliases_are_rejected(self) -> None:
        with self.assertRaisesRegex(
            candidates.CandidateSchemaError,
            "conflicting",
        ):
            candidates.canonicalize_path_identity(
                {
                    "source": "symbolic_oldV_path_1",
                    "query": "symbolic_oldV_path_2",
                    "target": "symbolic_newV_path_1",
                },
                direction="old_to_new",
            )

    def test_multi_target_match_is_not_collapsed(self) -> None:
        with self.assertRaisesRegex(
            candidates.CandidateSchemaError,
            "exactly one path",
        ):
            candidates.canonicalize_path_identity(
                {
                    "source": "symbolic_oldV_path_1",
                    "match": [
                        "symbolic_newV_path_1",
                        "symbolic_newV_path_2",
                    ],
                },
                direction="old_to_new",
            )

    def test_checkpoint_is_atomic_and_terminal_journaled(self) -> None:
        candidate = candidates.canonicalize_path_identity(
            {
                "source": "symbolic_oldV_path_1",
                "target": "symbolic_newV_path_2",
                "counterexample": {
                    "inputs": [
                        {
                            "name": "arg_0",
                            "kind": "bitvec",
                            "bits": 32,
                            "value": 3,
                            "unsigned": 3,
                        }
                    ]
                },
            },
            task_uid="task",
            query_kind="return_value_counterexample",
            direction="old_to_new",
        )
        terminal = candidates.candidate_with_state(
            candidate,
            status="accepted",
            reason="stable_replay",
        )
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            paths = candidates.persist_candidate_checkpoint(
                terminal,
                directory,
            )
            checkpoint = json.loads(
                Path(paths["checkpoint_path"]).read_text(encoding="utf-8")
            )
            journal = Path(paths["journal_path"]).read_text(
                encoding="utf-8"
            )
        self.assertEqual(checkpoint["status"], "accepted")
        self.assertIn(candidate["candidate_id"], journal)


if __name__ == "__main__":
    unittest.main()
