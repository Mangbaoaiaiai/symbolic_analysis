from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import verify_ranked_path_equivalence as verifier


def replay_run(
    stdout: str,
    *,
    returncode: int = 0,
    completed: bool = True,
) -> dict[str, object]:
    return {
        "completed": completed,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": "",
    }


class UbHeuristicTests(unittest.TestCase):
    def _paths(self, directory: Path) -> tuple[Path, Path]:
        path_dir = directory / "case" / "paths"
        bin_dir = directory / "case" / "bin"
        path_dir.mkdir(parents=True)
        bin_dir.mkdir(parents=True)
        (bin_dir / "symbolic_oldV").write_bytes(b"old")
        (bin_dir / "symbolic_newV").write_bytes(b"new")
        left = path_dir / "symbolic_oldV_path_1.txt"
        right = path_dir / "symbolic_newV_path_1.txt"
        left.write_text("(assert true)\n", encoding="utf-8")
        right.write_text("(assert true)\n", encoding="utf-8")
        return left, right

    def test_unconstrained_path_recovers_complete_input_specs(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "symbolic_oldV_path_1.txt"
            path.write_text(
                "(check-sat)\n"
                "; Symbolic variable values: "
                "{'arg_0': None, 'FP_arg_1_1_32': None, "
                "'arg_2_2_64': None}\n"
                "; Semantic summary JSON: "
                '(declare-fun FP_arg_1_1_32 () (_ FloatingPoint 8 24))\n'
                '(declare-fun arg_2_2_64 () (_ BitVec 64))\n',
                encoding="utf-8",
            )

            specs = verifier.input_specs_from_path_artifacts(path)

        self.assertEqual(
            {name: (kind, bits) for name, kind, bits, _ in specs},
            {
                "arg_0": ("bitvec", 32),
                "FP_arg_1_1_32": ("float", 32),
                "arg_2_2_64": ("bitvec", 64),
            },
        )

    def test_unconstrained_path_uses_standard_seeds(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            left, right = self._paths(Path(raw_dir))
            left.write_text(
                "(check-sat)\n"
                "; Symbolic variable values: {'arg_0': None}\n",
                encoding="utf-8",
            )
            right.write_text(
                "(check-sat)\n"
                "; Symbolic variable values: {'arg_0': None}\n",
                encoding="utf-8",
            )
            recovered = (("arg_0", "bitvec", 32, 0),)
            with mock.patch.object(
                verifier,
                "replay_standard_inputs",
                return_value={
                    "counterexample": [
                        {
                            "name": "arg_0",
                            "kind": "bitvec",
                            "bits": 32,
                            "value": 1,
                            "unsigned": 1,
                        }
                    ],
                    "replay": {"confirmed": True},
                    "observations": [],
                },
            ) as scan:
                result = verifier.program_domain_counterexample(
                    [left],
                    [right],
                )

        self.assertIsNotNone(result)
        self.assertEqual(scan.call_args.args[2], recovered)

    def test_subnormal_hex_float_is_flagged(self) -> None:
        flags = verifier.replay_anomaly_flags(
            replay_run("Result: 0x0.07fffd27161c8p-1022\n")
        )
        self.assertIn("subnormal", flags)

    def test_both_ub_like_rejects_concrete_difference(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            left, right = self._paths(Path(raw_dir))
            runs = [
                replay_run("Result: 0x0.07fffd27161c8p-1022\n"),
                replay_run("Result: 0x0.07fff6047c0c8p-1022\n"),
                replay_run("Result: 0x0.0800011111111p-1022\n"),
                replay_run("Result: 0x0.0800022222222p-1022\n"),
                replay_run("Result: 0x0.0800033333333p-1022\n"),
                replay_run("Result: 0x0.0800044444444p-1022\n"),
            ]
            with mock.patch.object(verifier, "run_binary", side_effect=runs):
                replay = verifier.replay_counterexample(
                    left,
                    right,
                    {"inputs": [{
                        "name": "arg_0_0_32",
                        "kind": "bitvec",
                        "bits": 32,
                        "value": 10,
                        "unsigned": 10,
                    }]},
                )
        self.assertFalse(replay["confirmed"])
        self.assertEqual(replay["classification"], "both_ub_like")
        self.assertIn("unstable", replay["left_flags"])
        self.assertIn("unstable", replay["right_flags"])

    def test_asymmetric_ub_like_confirms_neq(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            left, right = self._paths(Path(raw_dir))
            runs = [
                replay_run("Result: 0x0.07fffd27161c8p-1022\n"),
                replay_run("Result: 1\n"),
                replay_run("Result: 0x0.07fffe27161c8p-1022\n"),
                replay_run("Result: 1\n"),
                replay_run("Result: 0x0.07ffff27161c8p-1022\n"),
                replay_run("Result: 1\n"),
            ]
            with mock.patch.object(verifier, "run_binary", side_effect=runs):
                replay = verifier.replay_counterexample(
                    left,
                    right,
                    {"inputs": [{
                        "name": "arg_0_0_32",
                        "kind": "bitvec",
                        "bits": 32,
                        "value": 2,
                        "unsigned": 2,
                    }]},
                )
        self.assertTrue(replay["confirmed"])
        self.assertEqual(replay["classification"], "asymmetric_ub_like")

    def test_unknown_execution_status_confirms_neq(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            left, right = self._paths(Path(raw_dir))
            runs = [
                replay_run("", completed=False),
                replay_run("Result: 1\n"),
                replay_run("", completed=False),
                replay_run("Result: 1\n"),
                replay_run("", completed=False),
                replay_run("Result: 1\n"),
            ]
            with mock.patch.object(verifier, "run_binary", side_effect=runs):
                replay = verifier.replay_counterexample(
                    left,
                    right,
                    {"inputs": [{
                        "name": "arg_0_0_32",
                        "kind": "bitvec",
                        "bits": 32,
                        "value": 1,
                        "unsigned": 1,
                    }]},
                )
        self.assertTrue(replay["confirmed"])
        self.assertEqual(replay["classification"], "ub_status_unknown")

    def test_clean_equal_replay_does_not_confirm(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            left, right = self._paths(Path(raw_dir))
            with mock.patch.object(
                verifier,
                "run_binary",
                side_effect=[replay_run("Result: 1\n"), replay_run("Result: 1\n")],
            ):
                replay = verifier.replay_counterexample(
                    left,
                    right,
                    {"inputs": [{
                        "name": "arg_0_0_32",
                        "kind": "bitvec",
                        "bits": 32,
                        "value": 1,
                        "unsigned": 1,
                    }]},
                )
        self.assertFalse(replay["confirmed"])
        self.assertEqual(replay["classification"], "defined_equal")

    def test_definedness_audit_counts_replays(self) -> None:
        audit = verifier.collect_definedness_audit(
            {
                "matches": [
                    {
                        "replay": {
                            "classification": "both_ub_like",
                            "reason": "both_ub_like",
                            "stdin": "1 2\n",
                        }
                    },
                    {
                        "replay": {
                            "classification": "ub_status_unknown",
                            "reason": "ub_status_unknown",
                            "stdin": "3 4\n",
                        }
                    },
                ]
            }
        )
        self.assertEqual(audit["checks"], 2)
        self.assertEqual(audit["rejected_witnesses"], 1)
        self.assertEqual(audit["unknown_as_neq"], 1)

    def test_definedness_audit_deduplicates_same_witness(self) -> None:
        replay = {
            "classification": "both_ub_like",
            "reason": "both_ub_like",
            "stdin": "10\n",
            "left_flags": ["subnormal", "unstable"],
            "right_flags": ["subnormal", "unstable"],
            "left": replay_run("0x0.07ffdb8802a78p-1022\n"),
            "right": replay_run("0x0.07ffee3643748p-1022\n"),
        }
        audit = verifier.collect_definedness_audit(
            {
                "matches": [
                    {"replay": replay},
                    {"details": {"replay": replay}},
                ],
                "confirmed_mismatches": [{"replay": replay}],
            }
        )
        self.assertEqual(audit["checks"], 1)
        self.assertEqual(audit["rejected_witnesses"], 1)

    def test_unstable_outputs_are_variants_of_one_witness(self) -> None:
        first = verifier.make_replay_observation(
            {
                "classification": "both_ub_like",
                "reason": "both_ub_like",
                "stdin": "10\n",
                "left_flags": ["subnormal", "unstable"],
                "right_flags": ["subnormal", "unstable"],
                "left": replay_run("0x0.07ffdb8802a78p-1022\n"),
                "right": replay_run("0x0.07ffee3643748p-1022\n"),
            },
            inputs=[{"name": "arg_0", "kind": "bitvec", "bits": 32, "value": 10}],
        )
        second = verifier.make_replay_observation(
            {
                "classification": "both_ub_like",
                "reason": "both_ub_like",
                "stdin": "10\n",
                "left_flags": ["subnormal", "unstable"],
                "right_flags": ["subnormal", "unstable"],
                "left": replay_run("0x0.0800011111111p-1022\n"),
                "right": replay_run("0x0.0800022222222p-1022\n"),
            },
            inputs=[{"name": "arg_0", "kind": "bitvec", "bits": 32, "value": 10}],
        )
        self.assertEqual(first["event_id"], second["event_id"])
        audit = verifier.collect_definedness_audit(
            {"matches": [{"definedness_observations": [first, second]}]}
        )
        self.assertEqual(audit["checks"], 1)
        self.assertEqual(audit["events"][0]["occurrences"], 2)
        self.assertEqual(len(audit["events"][0]["variants"]), 2)

    def test_standard_seed_scan_keeps_rejected_ub_witness(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            left, right = self._paths(Path(raw_dir))
            seed = [{
                "name": "arg_0_0_32",
                "kind": "bitvec",
                "bits": 32,
                "value": 10,
                "unsigned": 10,
            }]
            rejected = {
                "confirmed": False,
                "reason": "both_ub_like",
                "classification": "both_ub_like",
                "definedness_policy": verifier.DEFINEDNESS_POLICY,
                "stdin": "10\n",
                "observable_output_diff": True,
                "left_flags": ["subnormal", "unstable"],
                "right_flags": ["subnormal", "unstable"],
                "left": replay_run("0x0.07ffdb8802a78p-1022\n"),
                "right": replay_run("0x0.07ffee3643748p-1022\n"),
                "left_samples": [],
                "right_samples": [],
            }
            verifier._STANDARD_SEED_REPLAY_CACHE.clear()
            with (
                mock.patch.object(
                    verifier,
                    "standard_input_seeds",
                    return_value=[seed],
                ),
                mock.patch.object(
                    verifier,
                    "replay_counterexample",
                    return_value=rejected,
                ),
            ):
                scan = verifier.replay_standard_inputs(
                    left,
                    right,
                    (("arg_0", "bitvec", 32, 0),),
                )
        self.assertIsNotNone(scan)
        self.assertIsNone(scan["counterexample"])
        self.assertEqual(len(scan["observations"]), 1)
        audit = verifier.collect_definedness_audit(
            {"matches": [{"definedness_observations": scan["observations"]}]}
        )
        self.assertEqual(audit["rejected_witnesses"], 1)
        self.assertEqual(audit["events"][0]["inputs"], seed)

    def test_unconfirmed_standard_scan_is_not_a_domain_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            left, right = self._paths(Path(raw_dir))
            specs = (("arg_0", "bitvec", 32, 0),)
            with (
                mock.patch.object(
                    verifier,
                    "concrete_input_specs",
                    return_value=specs,
                ),
                mock.patch.object(
                    verifier,
                    "replay_standard_inputs",
                    return_value={
                        "counterexample": None,
                        "replay": None,
                        "observations": [{"classification": "both_ub_like"}],
                    },
                ),
            ):
                mismatch = verifier.program_domain_counterexample(
                    [left], [right]
                )
        self.assertIsNone(mismatch)

    def test_finalize_marks_eq_as_conditional_after_rejected_witness(self) -> None:
        result = verifier.finalize_definedness_audit(
            {
                "verdict": "EQ",
                "matches": [{
                    "definedness_observations": [{
                        "event_id": "replay:test",
                        "classification": "both_ub_like",
                        "reason": "both_ub_like",
                        "stdin": "10\n",
                    }]
                }],
            }
        )
        self.assertTrue(result["conditional_eq"])
        self.assertEqual(result["definedness_audit"]["rejected_witnesses"], 1)


if __name__ == "__main__":
    unittest.main()
