import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.prepare_osf_all import (
    apply_source_repairs,
    configured_targets,
    load_entry_config,
    resolve_entry_config,
    select_function_entry,
    wrap_function_source,
    wrap_snippet_source,
    wrap_targets_source,
)


class PrepareOsfAllTests(unittest.TestCase):
    def test_source_repairs_are_literal_and_strict(self) -> None:
        config = {
            "source_repairs": [
                {"old": "obj.AMBIENT", "new": "0"},
                {"old": "obj.DIRECTIONAL", "new": "1"},
            ]
        }
        self.assertEqual(
            apply_source_repairs(
                "type != obj.AMBIENT && type == obj.DIRECTIONAL",
                config,
            ),
            "type != 0 && type == 1",
        )
        with self.assertRaisesRegex(ValueError, "did not match"):
            apply_source_repairs("obj.AMBIENT", {"source_repairs": [{"old": "missing", "new": "0"}]})

    def test_raytrace_repair_initializes_java_default_object_state(self) -> None:
        root = Path(__file__).resolve().parents[1]
        config = load_entry_config(root / "configs" / "osf_entry_overrides.json")
        raytrace = resolve_entry_config(
            config,
            case_id="raytrace/raytrace_Eq",
            family="raytrace",
            program_id="raytrace/raytrace",
        )
        source = """
        Light LightConstructor(int type, Vector3D v) {
            Light obj;
            obj.lightType = type;
            if (type != obj.AMBIENT && type == obj.DIRECTIONAL) {
                obj.lvec = v;
            }
            return obj;
        }
        """
        repaired = apply_source_repairs(source, raytrace)
        self.assertIn("Light obj = {0};", repaired)
        self.assertIn("type != 0 && type == 1", repaired)
        self.assertNotIn("obj.AMBIENT", repaired)
        self.assertNotIn("obj.DIRECTIONAL", repaired)

    def test_entry_config_precedence(self) -> None:
        with TemporaryDirectory() as raw_tmp:
            path = Path(raw_tmp) / "entries.json"
            path.write_text(
                json.dumps(
                    {
                        "families": {
                            "f": {"entry": "family_entry", "params": [{"name": "x"}]}
                        },
                        "programs": {
                            "f/p": {"entry": "program_entry", "mode": "program"}
                        },
                        "cases": {
                            "f/p_Eq": {"mode": "case", "params": [{"name": "y"}]}
                        },
                    }
                ),
                encoding="utf-8",
            )
            config = load_entry_config(path)
            resolved = resolve_entry_config(
                config,
                case_id="f/p_Eq",
                family="f",
                program_id="f/p",
            )
            self.assertEqual(resolved["entry"], "program_entry")
            self.assertEqual(resolved["mode"], "case")
            self.assertEqual(resolved["params"], [{"name": "y"}])
            self.assertEqual(
                resolved["_config_source"],
                "family:f+program:f/p+case:f/p_eq",
            )

    def test_entry_config_extends_relative_file(self) -> None:
        with TemporaryDirectory() as raw_tmp:
            directory = Path(raw_tmp)
            (directory / "base.json").write_text(
                json.dumps({"programs": {"f/p": {"entry": "base"}}}),
                encoding="utf-8",
            )
            (directory / "child.json").write_text(
                json.dumps(
                    {
                        "extends": "base.json",
                        "programs": {"f/p": {"params": []}},
                    }
                ),
                encoding="utf-8",
            )
            resolved = resolve_entry_config(
                load_entry_config(directory / "child.json"),
                case_id="f/p_Eq",
                family="f",
                program_id="f/p",
            )
            self.assertEqual(resolved["entry"], "base")
            self.assertEqual(resolved["params"], [])

    def test_configured_record_argument_and_return(self) -> None:
        with TemporaryDirectory() as raw_tmp:
            source = Path(raw_tmp) / "oldV.c"
            source.write_text(
                "typedef struct V { float x, y; } V;\n"
                "V scale(V v) { v.x *= 2.0f; v.y *= 2.0f; return v; }\n",
                encoding="utf-8",
            )
            wrapped = wrap_function_source(
                source,
                "scale",
                config={
                    "entry": "scale",
                    "params": [
                        {
                            "name": "v",
                            "type": "V",
                            "mode": "record",
                            "fields": [
                                {"path": "x", "type": "float"},
                                {"path": "y", "type": "float"},
                            ],
                        }
                    ],
                    "return": {
                        "type": "V",
                        "fields": [
                            {"path": "x", "type": "float"},
                            {"path": "y", "type": "float"},
                        ],
                    },
                },
            )
            self.assertIn("V __param_0 = {0};", wrapped)
            self.assertIn("__param_0.x = arg_0;", wrapped)
            self.assertIn("V __result = scale(__param_0);", wrapped)
            self.assertIn('printf("Result: %a %a\\n", __result.x, __result.y);', wrapped)

    def test_configured_record_argument_scalar_return(self) -> None:
        with TemporaryDirectory() as raw_tmp:
            source = Path(raw_tmp) / "oldV.c"
            source.write_text(
                "typedef struct P { int x; long y; int z; } P;\n"
                "int hashP(P p) { return p.x + (int)p.y + p.z; }\n",
                encoding="utf-8",
            )
            wrapped = wrap_function_source(
                source,
                "hashP",
                config={
                    "entry": "hashP",
                    "params": [
                        {
                            "name": "p",
                            "type": "P",
                            "mode": "record",
                            "fields": [
                                {
                                    "path": "x",
                                    "type": "int",
                                    "bounds": {"min": -4, "max": 4},
                                },
                                {"path": "y", "type": "long"},
                                {"path": "z", "type": "int"},
                            ],
                        }
                    ],
                    "return": {"type": "int"},
                },
            )
            self.assertIn(
                "int snippet(int arg_0, long arg_1, int arg_2)",
                wrapped,
            )
            self.assertIn("P __param_0 = {0};", wrapped)
            self.assertIn("if (arg_0 < -4 || arg_0 > 4) { return 0; }", wrapped)
            self.assertIn("return hashP(__param_0);", wrapped)

    def test_configured_nested_record_fields(self) -> None:
        with TemporaryDirectory() as raw_tmp:
            source = Path(raw_tmp) / "oldV.c"
            source.write_text(
                "typedef struct V { float x; float y; float z; } V;\n"
                "typedef struct S { V center; float radius; } S;\n"
                "S moveSphere(S s, V center) {\n"
                "  s.center = center;\n"
                "  s.radius += 1.0f;\n"
                "  return s;\n"
                "}\n",
                encoding="utf-8",
            )
            wrapped = wrap_function_source(
                source,
                "moveSphere",
                config={
                    "entry": "moveSphere",
                    "params": [
                        {
                            "name": "s",
                            "type": "S",
                            "mode": "record",
                            "fields": [
                                {"path": "center.x", "type": "float"},
                                {"path": "center.y", "type": "float"},
                                {"path": "center.z", "type": "float"},
                                {"path": "radius", "type": "float"},
                            ],
                        },
                        {
                            "name": "center",
                            "type": "V",
                            "mode": "record",
                            "fields": [
                                {"path": "x", "type": "float"},
                                {"path": "y", "type": "float"},
                                {"path": "z", "type": "float"},
                            ],
                        },
                    ],
                    "return": {
                        "type": "S",
                        "fields": [
                            {"path": "center.x", "type": "float"},
                            {"path": "center.y", "type": "float"},
                            {"path": "center.z", "type": "float"},
                            {"path": "radius", "type": "float"},
                        ],
                    },
                },
            )
            self.assertIn("__param_0.center.x = arg_0;", wrapped)
            self.assertIn("__param_1.z = arg_6;", wrapped)
            self.assertIn(
                'printf("Result: %a %a %a %a\\n", '
                "__result.center.x, __result.center.y, __result.center.z, "
                "__result.radius);",
                wrapped,
            )

    def test_configured_targets_aggregate_scalar_and_global_outputs(self) -> None:
        with TemporaryDirectory() as raw_tmp:
            source = Path(raw_tmp) / "oldV.c"
            source.write_text(
                "#include <stdio.h>\n"
                "double state;\n"
                "int add(int x, int y) { return x + y; }\n"
                "void mutate(double x) { state = x * 2.0; }\n",
                encoding="utf-8",
            )
            config = {
                "targets": [
                    {
                        "name": "add",
                        "entry": "add",
                        "return": {"type": "int"},
                    },
                    {
                        "name": "mutate",
                        "entry": "mutate",
                        "observe": [{"path": "state", "type": "double"}],
                    },
                ]
            }
            wrapped = wrap_targets_source(source, config, variant="old")
            self.assertIn("int snippet(int arg_0, int arg_1, double arg_2)", wrapped)
            self.assertIn("int __target_0_result = add(arg_0, arg_1);", wrapped)
            self.assertIn(
                'printf("Target add: %d\\n", __target_0_result);',
                wrapped,
            )
            self.assertIn("mutate(arg_2);", wrapped)
            self.assertIn('printf("Target mutate: %a\\n", state);', wrapped)
            self.assertIn('scanf("%d %d %lf"', wrapped)

    def test_configured_targets_allow_explicit_empty_observation(self) -> None:
        with TemporaryDirectory() as raw_tmp:
            source = Path(raw_tmp) / "oldV.c"
            source.write_text(
                "void calculate(int n, double x) { double local = n + x; }\n",
                encoding="utf-8",
            )
            wrapped = wrap_targets_source(
                source,
                {
                    "targets": [
                        {
                            "name": "calculate",
                            "entry": "calculate",
                            "observe": [],
                        }
                    ]
                },
                variant="old",
            )
            self.assertIn("calculate(arg_0, arg_1);", wrapped)
            self.assertIn('printf("Target calculate: void\\n");', wrapped)

    def test_configured_targets_reject_duplicate_names(self) -> None:
        with self.assertRaisesRegex(ValueError, "target names must be unique"):
            configured_targets(
                {
                    "targets": [
                        {"name": "same", "entry": "first"},
                        {"name": "same", "entry": "second"},
                    ]
                }
            )

    def test_configured_bounded_array_and_domain_guard(self) -> None:
        with TemporaryDirectory() as raw_tmp:
            source = Path(raw_tmp) / "oldV.c"
            source.write_text(
                "double average(int n, int a[]) {\n"
                "  int sum = 0;\n"
                "  for (int i = 0; i < n; i++) sum += a[i];\n"
                "  return n ? (double)sum / n : 0.0;\n"
                "}\n",
                encoding="utf-8",
            )
            wrapped = wrap_function_source(
                source,
                "average",
                config={
                    "entry": "average",
                    "params": [
                        {
                            "name": "n",
                            "type": "int",
                            "mode": "scalar",
                            "bounds": {"min": 0, "max": 2},
                        },
                        {
                            "name": "a",
                            "type": "int[]",
                            "mode": "array",
                            "length": 2,
                            "element_bounds": {"min": -3, "max": 3},
                        },
                    ],
                    "return": {"type": "double"},
                },
            )
            self.assertIn("if (arg_0 < 0 || arg_0 > 2) { return 0; }", wrapped)
            self.assertIn("if (arg_1 < -3 || arg_1 > 3) { return 0; }", wrapped)
            self.assertIn("if (arg_2 < -3 || arg_2 > 3) { return 0; }", wrapped)
            self.assertIn("int __param_1[2] = {0};", wrapped)
            self.assertIn("__param_1[1] = arg_2;", wrapped)
            self.assertIn("return average(arg_0, __param_1);", wrapped)

    def test_const_scalar_return_keeps_legacy_path(self) -> None:
        with TemporaryDirectory() as raw_tmp:
            source = Path(raw_tmp) / "oldV.c"
            source.write_text(
                "const double theta(double x, double y) { return x + y; }\n",
                encoding="utf-8",
            )
            wrapped = wrap_function_source(source, "theta")
            self.assertIn(
                "const double snippet(double x, double y)",
                wrapped,
            )
            self.assertIn("return theta(x, y);", wrapped)

    def test_selects_unique_changed_function(self) -> None:
        old = """
int helper(int x) { return x + 1; }
int client(int x) {
  if (x > 0) return helper(x);
  return 0;
}
"""
        new = """
int helper(int x) { return x + 1; }
int client(int x) {
  if (x >= 0) return helper(x);
  return 0;
}
"""
        self.assertEqual(
            select_function_entry(
                old,
                new,
                program="client",
                entry_hint=None,
                old_java=None,
                new_java=None,
            ),
            "client",
        )

    def test_selects_single_scalar_function(self) -> None:
        with TemporaryDirectory() as raw_tmp:
            source = Path(raw_tmp) / "oldV.c"
            source.write_text("int f(int x) { return x * 2; }\n", encoding="utf-8")
            text = source.read_text(encoding="utf-8")
            self.assertEqual(
                select_function_entry(
                    text,
                    text,
                    program="ackermann",
                    entry_hint=None,
                    old_java=None,
                    new_java=None,
                ),
                "f",
            )
            wrapped = wrap_function_source(source, "f")
            self.assertIn("int snippet(int x) { return f(x); }", wrapped)
            self.assertIn("int main(void)", wrapped)

    def test_rejects_ambiguous_scalar_functions(self) -> None:
        source = """
int first(int x) { return x + 1; }
int second(int x) { return x - 1; }
"""
        with self.assertRaisesRegex(ValueError, "ambiguous scalar entry"):
            select_function_entry(
                source,
                source,
                program="unknown",
                entry_hint=None,
                old_java=None,
                new_java=None,
            )

    def test_public_entry_beats_private_changed_helper(self) -> None:
        old = """
int lib(int n) {
  if (n <= 1) return 0;
  return lib(n - 1) + lib(n - 2);
}
int fib(int x) {
  if (x < 5) return lib(x);
  return 0;
}
"""
        new = """
int lib(int n) {
  int a = 0;
  while (n-- > 0) a += n;
  return a;
}
int fib(int x) {
  if (x < 5) return lib(x);
  return 0;
}
"""
        java = """\
class oldV {
  private int lib(int n) { return 0; }
  public int fib(int x) { return lib(x); }
}
"""
        with TemporaryDirectory() as raw_tmp:
            java_path = Path(raw_tmp) / "oldV.java"
            java_path.write_text(java, encoding="utf-8")
            self.assertEqual(
                select_function_entry(
                    old,
                    new,
                    program="fib2",
                    entry_hint=None,
                    old_java=java_path,
                    new_java=java_path,
                ),
                "fib",
            )

    def test_declared_program_name_selects_public_entry(self) -> None:
        old = """
int lib(int x, int y) { return x / y; }
int client(int c, int d) {
  return lib(c, d);
}
"""
        new = """
int lib(int x, int y) {
  if (y == 0) return 0;
  return x / y;
}
int client(int c, int d) {
  return lib(c, d);
}
"""
        self.assertEqual(
            select_function_entry(
                old,
                new,
                program="divide",
                entry_hint="divide.client",
                old_java=None,
                new_java=None,
            ),
            "client",
        )

    def test_rejects_pointer_argument(self) -> None:
        with TemporaryDirectory() as raw_tmp:
            source = Path(raw_tmp) / "oldV.c"
            source.write_text("int f(int *x) { return *x; }\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "pointer/array"):
                wrap_function_source(source, "f")

    def test_void_snippet_writes_global_state(self) -> None:
        with TemporaryDirectory() as raw_tmp:
            source = Path(raw_tmp) / "oldV.c"
            source.write_text(
                "double output;\n"
                "void snippet(double x) {\n"
                "  output = x * 2.0;\n"
                "}\n",
                encoding="utf-8",
            )
            wrapped = wrap_snippet_source(source)
            self.assertIn("void __benchmark_snippet(double x)", wrapped)
            self.assertIn("int snippet(double x)", wrapped)
            self.assertIn("__benchmark_snippet(x); return 0;", wrapped)

    def test_void_function_without_global_output_is_rejected(self) -> None:
        with TemporaryDirectory() as raw_tmp:
            source = Path(raw_tmp) / "oldV.c"
            source.write_text(
                "void wood(double x) { if (x > 0.0) { } }\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "no observable global"):
                wrap_function_source(source, "wood")

    def test_void_function_with_supported_printf_is_accepted(self) -> None:
        with TemporaryDirectory() as raw_tmp:
            source = Path(raw_tmp) / "oldV.c"
            source.write_text(
                "#include <stdio.h>\n"
                "void wood(double x) {\n"
                "  if (x > 0.0) { printf(\"positive\\n\"); }\n"
                "}\n",
                encoding="utf-8",
            )
            wrapped = wrap_function_source(source, "wood")
            self.assertIn("void __benchmark_wood(double x)", wrapped)
            self.assertIn("int snippet(double x)", wrapped)
            self.assertIn("__benchmark_wood(x); return 0;", wrapped)


if __name__ == "__main__":
    unittest.main()
