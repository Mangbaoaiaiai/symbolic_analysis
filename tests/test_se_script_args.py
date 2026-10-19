from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "se_script_improved",
    ROOT / "scripts" / "se_script_improved.py",
)
assert SPEC is not None and SPEC.loader is not None
se_script = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(se_script)


class _SizedValue:
    def __init__(self, name: str, bits: int = 32):
        self.name = name
        self.bits = bits

    def size(self) -> int:
        return self.bits

    def raw_to_bv(self) -> "_SizedValue":
        return self


class _Offset:
    def __init__(self, value: int):
        self.value = value

    def __add__(self, increment: int) -> "_Offset":
        return _Offset(self.value + increment)


class _Memory:
    def __init__(self):
        self.stores = []

    def store(self, address, value, *, size, endness):
        self.stores.append((address.value, value.name, size, endness))


class _Regs:
    def __init__(self):
        self.sp = _Offset(0x1000)


class SymbolicArgumentTests(unittest.TestCase):
    def test_sysv_stack_arguments_are_installed_after_six_registers(self) -> None:
        runner = se_script.BenchmarkSymbolicExecution.__new__(
            se_script.BenchmarkSymbolicExecution
        )
        runner.binary_path = "symbolic_oldV"
        runner.project = SimpleNamespace(
            loader=SimpleNamespace(
                main_object=SimpleNamespace(os="linux"),
            )
        )
        values = [_SizedValue(f"arg{i}") for i in range(8)]
        state = SimpleNamespace(
            arch=SimpleNamespace(
                name="AMD64",
                registers={
                    "edi": (0, 4),
                    "esi": (0, 4),
                    "edx": (0, 4),
                    "ecx": (0, 4),
                    "r8d": (0, 4),
                    "r9d": (0, 4),
                },
                memory_endness="Iend_LE",
            ),
            regs=_Regs(),
            memory=_Memory(),
        )

        runner.install_call_arguments(
            state,
            [("int", value) for value in values],
        )

        self.assertEqual(
            state.memory.stores,
            [
                (0x1008, "arg6", 4, "Iend_LE"),
                (0x1010, "arg7", 4, "Iend_LE"),
            ],
        )
        self.assertIs(state.regs.edi, values[0])
        self.assertIs(state.regs.r9d, values[5])

    def test_sysv_ninth_double_is_installed_on_stack(self) -> None:
        runner = se_script.BenchmarkSymbolicExecution.__new__(
            se_script.BenchmarkSymbolicExecution
        )
        runner.binary_path = "symbolic_oldV"
        runner.project = SimpleNamespace(
            loader=SimpleNamespace(
                main_object=SimpleNamespace(os="linux"),
            )
        )
        values = [_SizedValue(f"arg{i}", bits=64) for i in range(9)]
        state = SimpleNamespace(
            arch=SimpleNamespace(
                name="AMD64",
                registers={
                    **{f"xmm{i}": (0, 16) for i in range(8)},
                },
                memory_endness="Iend_LE",
            ),
            regs=_Regs(),
            memory=_Memory(),
        )

        runner.install_call_arguments(
            state,
            [("double", value) for value in values],
        )

        self.assertEqual(
            state.memory.stores,
            [(0x1008, "arg8", 8, "Iend_LE")],
        )


if __name__ == "__main__":
    unittest.main()
