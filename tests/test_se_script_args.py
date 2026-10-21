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
    def test_global_initializer_mode_is_explicit_and_defaults_off(self) -> None:
        legacy = se_script.BenchmarkSymbolicExecution("binary")
        concrete = se_script.BenchmarkSymbolicExecution(
            "binary",
            concrete_global_initializers=True,
        )
        self.assertFalse(legacy.concrete_global_initializers)
        self.assertTrue(concrete.concrete_global_initializers)
        self.assertTrue(legacy.retain_path_details)

    def test_streaming_path_output_releases_each_state(self) -> None:
        runner = se_script.BenchmarkSymbolicExecution.__new__(
            se_script.BenchmarkSymbolicExecution
        )
        runner.paths_info = []
        runner.retain_path_details = False
        runner.extract_path_signature = lambda state: {
            "variables": {},
            "constraints": {"count": 0},
        }
        runner.generate_smt_constraints = lambda state: "(check-sat)"
        runner.extract_semantic_summary = lambda state: {"state": state}
        runner.save_path_to_file = lambda info: f"path_{info['index']}.txt"
        states = [object(), object()]

        runner.analyze_states(states)

        self.assertEqual(
            runner.paths_info,
            [
                {"index": 1, "path_file": "path_1.txt"},
                {"index": 2, "path_file": "path_2.txt"},
            ],
        )
        self.assertEqual(states, [None, None])

    def test_printf_fp_argument_is_serialized_as_ieee_bits(self) -> None:
        runner = se_script.BenchmarkSymbolicExecution.__new__(
            se_script.BenchmarkSymbolicExecution
        )
        value = se_script.claripy.BVS("double_value", 64).raw_to_fp()

        segment = runner.serialize_output_argument(
            SimpleNamespace(),
            value,
            event_index=0,
            argument_index=0,
            specifier="%a",
        )

        self.assertEqual(segment["kind"], "formatted_value")
        self.assertTrue(segment["available"])
        self.assertNotIn("(assert\n false)", segment["smt"])
        self.assertIn("__output_0_0", segment["smt"])
        self.assertIn("double_value", segment["smt"])

    def test_printf_integer_argument_is_serialized(self) -> None:
        runner = se_script.BenchmarkSymbolicExecution.__new__(
            se_script.BenchmarkSymbolicExecution
        )
        value = se_script.claripy.BVS("integer_value", 32)

        segment = runner.serialize_output_argument(
            SimpleNamespace(),
            value,
            event_index=1,
            argument_index=0,
            specifier="%d",
        )

        self.assertEqual(segment["kind"], "formatted_value")
        self.assertTrue(segment["available"])
        self.assertNotIn("smt_error", segment)
        self.assertIn("__output_1_0", segment["smt"])
        self.assertIn("integer_value", segment["smt"])

    def test_long_return_uses_64_bit_register(self) -> None:
        runner = se_script.BenchmarkSymbolicExecution.__new__(
            se_script.BenchmarkSymbolicExecution
        )
        runner.snippet_signature = {"return": "long", "args": []}
        state = SimpleNamespace(
            arch=SimpleNamespace(registers={"eax": (0, 4), "rax": (0, 8)}),
            regs=SimpleNamespace(eax="low32", rax="full64"),
        )

        self.assertEqual(runner.get_return_expr(state), "full64")

    def test_64_bit_sysv_integer_uses_full_register(self) -> None:
        runner = se_script.BenchmarkSymbolicExecution.__new__(
            se_script.BenchmarkSymbolicExecution
        )
        runner.binary_path = "symbolic_oldV"
        runner.project = SimpleNamespace(
            loader=SimpleNamespace(
                main_object=SimpleNamespace(os="linux"),
            )
        )
        state = SimpleNamespace(
            arch=SimpleNamespace(
                name="AMD64",
                registers={"rsi": (0, 8)},
                memory_endness="Iend_LE",
            ),
            regs=_Regs(),
            memory=_Memory(),
        )

        runner.install_call_arguments(
            state,
            [
                ("int", _SizedValue("arg0")),
                ("long", _SizedValue("arg1", bits=64)),
            ],
        )

        self.assertFalse(hasattr(state.regs, "esi"))
        self.assertEqual(state.regs.rsi.name, "arg1")

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
