"""Known failures retained while publishing the exact measured method.

These assert the desired ABI behavior, not the buggy output. Remove the
expectedFailure decorators when a separately validated fix is incorporated.
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from se_script_improved import BenchmarkSymbolicExecution


class CurrentAbiLimitations(unittest.TestCase):
    @unittest.expectedFailure
    def test_long_return_uses_full_64_bit_register(self):
        runner = BenchmarkSymbolicExecution.__new__(BenchmarkSymbolicExecution)
        runner.snippet_signature = {'return': 'long', 'args': []}
        state = SimpleNamespace(
            arch=SimpleNamespace(registers={'eax': (0, 4), 'rax': (0, 8)}),
            regs=SimpleNamespace(eax='low32', rax='full64'))
        self.assertEqual(runner.get_return_expr(state), 'full64')

    @unittest.expectedFailure
    def test_long_argument_uses_full_sysv_register(self):
        runner = BenchmarkSymbolicExecution.__new__(BenchmarkSymbolicExecution)
        runner.binary_path = 'symbolic_oldV'
        runner.project = SimpleNamespace(loader=SimpleNamespace(
            main_object=SimpleNamespace(os='linux')))
        state = SimpleNamespace(arch=SimpleNamespace(
            name='AMD64', registers={'edi': (0, 4), 'rdi': (0, 8)}))
        self.assertEqual(runner.argument_register_name(state, 'long', 0), 'rdi')
