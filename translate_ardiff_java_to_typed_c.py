#!/usr/bin/env python3
"""Translate ARDiff Java snippets to C while preserving scalar types."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_SRC = ROOT / "experiments" / "ardiff_comparison" / "benchmarks"
DEFAULT_DST = ROOT / "experiments" / "ardiff_comparison" / "benchmarks_typed"


TYPE_MAP = {
    "int": "int",
    "long": "long",
    "double": "double",
    "float": "float",
    "boolean": "int",
}

MATH_MAP = {
    "Math.abs": "fabs",
    "Math.sqrt": "sqrt",
    "Math.sin": "sin",
    "Math.cos": "cos",
    "Math.tan": "tan",
    "Math.exp": "exp",
    "Math.log": "log",
    "Math.pow": "pow",
    "Math.PI": "M_PI",
    "Math.E": "M_E",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Translate ARDiff Java benchmark snippets to typed C.")
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC)
    parser.add_argument("--dst", type=Path, default=DEFAULT_DST)
    parser.add_argument("--clean", action="store_true", help="Remove generated C files in destination first.")
    args = parser.parse_args()

    src = args.src.resolve()
    dst = args.dst.resolve()
    if not src.is_dir():
        raise SystemExit(f"Source benchmark directory not found: {src}")
    dst.mkdir(parents=True, exist_ok=True)

    if args.clean:
        for path in dst.rglob("symbolic_*V.c"):
            path.unlink()

    translated = 0
    failed: list[tuple[str, str]] = []
    for old_java in sorted(src.rglob("oldV.java")):
        case_dir = old_java.parent
        if "instrumented" in case_dir.parts:
            continue
        new_java = case_dir / "newV.java"
        if not new_java.is_file():
            continue
        rel = case_dir.relative_to(src)
        out_case = dst / rel
        out_case.mkdir(parents=True, exist_ok=True)
        for java_path, out_name in ((old_java, "symbolic_oldV.c"), (new_java, "symbolic_newV.c")):
            try:
                c_text = translate_file(java_path)
                (out_case / out_name).write_text(c_text, encoding="utf-8")
                translated += 1
            except Exception as exc:  # noqa: BLE001
                failed.append((str(java_path.relative_to(src)), str(exc)))

    print(f"Translated {translated} Java files to {dst}")
    if failed:
        print(f"Failures: {len(failed)}")
        for path, error in failed[:20]:
            print(f"  {path}: {error}")
    return 1 if failed else 0


def translate_file(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    signature = find_snippet_signature(text)
    body = extract_method_body(text, signature["body_start"])
    body = translate_java_body(body)
    return render_c(signature, body)


def find_snippet_signature(text: str) -> dict[str, object]:
    pattern = re.compile(
        r"public\s+static\s+(?P<ret>\w+)\s+snippet\s*\((?P<args>[^)]*)\)\s*\{",
        re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        raise ValueError("snippet signature not found")
    ret_type = map_type(match.group("ret"))
    args = []
    raw_args = match.group("args").strip()
    if raw_args:
        for raw in raw_args.split(","):
            parts = raw.strip().split()
            if len(parts) < 2:
                raise ValueError(f"unsupported argument syntax: {raw}")
            args.append((map_type(parts[0]), parts[-1]))
    return {
        "return_type": ret_type,
        "args": args,
        "body_start": match.end(),
    }


def extract_method_body(text: str, start: int) -> str:
    depth = 1
    i = start
    while i < len(text):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i]
        i += 1
    raise ValueError("snippet body is not balanced")


def translate_java_body(body: str) -> str:
    out = body
    for java_name, c_name in MATH_MAP.items():
        out = out.replace(java_name, c_name)
    out = re.sub(r"\bboolean\b", "int", out)
    out = re.sub(r"\btrue\b", "1", out)
    out = re.sub(r"\bfalse\b", "0", out)
    return out.strip()


def render_c(signature: dict[str, object], body: str) -> str:
    return_type = str(signature["return_type"])
    args = list(signature["args"])
    arg_decl = ", ".join(f"{typ} {name}" for typ, name in args) or "void"
    scanf_fmt = " ".join(scanf_format(typ) for typ, _name in args)
    scanf_args = ", ".join(f"&{name}" for _typ, name in args)
    declarations = "\n".join(f"    {typ} {name};" for typ, name in args)
    call_args = ", ".join(name for _typ, name in args)
    result_fmt = printf_format(return_type)

    if args:
        scanf_block = f'    scanf("{scanf_fmt}", {scanf_args});'
    else:
        scanf_block = "    /* no symbolic input */"

    return (
        "#include <stdio.h>\n"
        "#include <stdlib.h>\n"
        "#include <math.h>\n\n"
        "#ifndef M_PI\n#define M_PI 3.14159265358979323846\n#endif\n"
        "#ifndef M_E\n#define M_E 2.71828182845904523536\n#endif\n\n"
        f"{return_type} snippet({arg_decl}) {{\n"
        f"{indent_body(body)}\n"
        "}\n\n"
        "int main() {\n"
        "    /* symbolic inputs are provided through scanf hooks when main is analyzed */\n"
        f"{declarations}\n"
        f"{scanf_block}\n"
        f"    {return_type} result = snippet({call_args});\n"
        f'    printf("Result: {result_fmt}\\n", result);\n'
        "    return 0;\n"
        "}\n"
    )


def indent_body(body: str) -> str:
    lines = body.splitlines()
    return "\n".join("    " + line.rstrip() for line in lines if line.strip())


def map_type(java_type: str) -> str:
    try:
        return TYPE_MAP[java_type]
    except KeyError as exc:
        raise ValueError(f"unsupported Java type: {java_type}") from exc


def scanf_format(c_type: str) -> str:
    if c_type == "double":
        return "%lf"
    if c_type == "float":
        return "%f"
    if c_type == "long":
        return "%ld"
    return "%d"


def printf_format(c_type: str) -> str:
    if c_type in {"double", "float"}:
        return "%f"
    if c_type == "long":
        return "%ld"
    return "%d"


if __name__ == "__main__":
    raise SystemExit(main())
