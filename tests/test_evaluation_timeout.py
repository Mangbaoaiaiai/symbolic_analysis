import unittest
from pathlib import Path

from run_evaluation import EvalConfig, extend_verifier_mode_args


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


if __name__ == "__main__":
    unittest.main()
