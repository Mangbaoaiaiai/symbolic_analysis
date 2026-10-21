import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from run_evaluation import (
    BinaryPair,
    EvalConfig,
    NaiveMatchingRunner,
    extend_verifier_mode_args,
)


class EvaluationTimeoutTests(unittest.TestCase):
    def test_smt_timeout_is_forwarded_to_verifier(self) -> None:
        config = EvalConfig(
            root=Path("."),
            benchmarks_dir=Path("benchmarks"),
            symbolic_dir=Path("."),
            veribin_dir=Path("../VeriBin"),
            output_dir=Path("out"),
            timeout=3600,
            smt_timeout_ms=60000,
            execute=True,
            python="python3",
        )
        command = ["verify"]
        extend_verifier_mode_args(command, config)
        self.assertEqual(command, ["verify", "--timeout-ms", "60000"])

    def test_tool_timeout_is_preserved_for_unknown_classification(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            config = EvalConfig(
                root=root,
                benchmarks_dir=root / "benchmarks",
                symbolic_dir=root,
                veribin_dir=root / "veribin",
                output_dir=root / "out",
                timeout=2,
                smt_timeout_ms=1000,
                execute=True,
                python="python3",
            )
            runner = NaiveMatchingRunner(config)
            pair = BinaryPair(
                pair_id="CLEVER/Add_Eq",
                subset="CLEVER",
                program="Add_Eq",
                left=root / "old",
                right=root / "new",
            )
            with mock.patch(
                "run_evaluation.subprocess.run",
                side_effect=subprocess.TimeoutExpired(["verify"], 2),
            ):
                completed, _elapsed, _stdout, stderr, _trace = (
                    runner._run_command(pair, ["verify"], "timeout_probe")
                )
            self.assertEqual(completed.returncode, 124)
            self.assertIn("tool timeout", stderr.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
