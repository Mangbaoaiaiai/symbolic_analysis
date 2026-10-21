import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.prepare_osf_all import (
    select_function_entry,
    wrap_function_source,
    wrap_snippet_source,
)


class PrepareOsfAllTests(unittest.TestCase):
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
