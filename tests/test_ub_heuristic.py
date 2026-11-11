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

    def check_replay(self, runs):
        with tempfile.TemporaryDirectory() as raw_dir:
            left, right = self._paths(Path(raw_dir))
            with mock.patch.object(verifier, 'run_binary', side_effect=runs):
                return verifier.replay_counterexample(left, right, {
                    'inputs': [{'name':'arg_0_0_32', 'kind':'bitvec', 'bits':32,
                                'value':1, 'unsigned':1}]})

    def test_both_unstable_does_not_confirm(self):
        result = self.check_replay([replay_run('1'), replay_run('2'),
                                    replay_run('3'), replay_run('4')])
        self.assertFalse(result['confirmed'])
        self.assertEqual(result['reason'], 'repeated_execution_unstable')

    def test_one_side_unstable_does_not_confirm(self):
        result = self.check_replay([replay_run('1'), replay_run('2'),
                                    replay_run('3'), replay_run('3')])
        self.assertFalse(result['confirmed'])
        self.assertEqual(result['reason'], 'repeated_execution_unstable')

    def test_incomplete_execution_does_not_confirm(self):
        result = self.check_replay([replay_run('', completed=False)] * 2 +
                                   [replay_run('1')] * 2)
        self.assertFalse(result['confirmed'])
        self.assertEqual(result['reason'], 'replay_failed')

    def test_clean_equal_does_not_confirm(self):
        result = self.check_replay([replay_run('1')] * 4)
        self.assertFalse(result['confirmed'])
        self.assertEqual(result['reason'], 'no_observable_output_diff')

    def test_stable_output_difference_confirms(self):
        result = self.check_replay([replay_run('1')] * 2 + [replay_run('2')] * 2)
        self.assertTrue(result['confirmed'])
        self.assertEqual(result['reason'], 'observable_output_diff')

    def test_signal_difference_does_not_confirm(self):
        result = self.check_replay([replay_run('', returncode=-11)] * 2 +
                                   [replay_run('1')] * 2)
        self.assertFalse(result['confirmed'])
        self.assertEqual(result['reason'], 'program_exit_nonzero')
