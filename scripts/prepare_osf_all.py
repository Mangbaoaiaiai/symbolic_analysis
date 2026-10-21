#!/usr/bin/env python3
"""Stage every C/Java pair in the OSF ARDiff benchmark with explicit support status."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_OSF_ROOT = Path("benchmark/osf_sources/benchmarks")
SCALAR_RETURN_TYPES = {"bool", "char", "double", "float", "int", "long", "short", "void"}
SCALAR_ARGUMENT_TYPES = {"bool", "char", "double", "float", "int", "long", "short"}


@dataclass(frozen=True)
class CFunction:
    return_type: str
    name: str
    raw_args: str
    body: str


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def find_variant(directory: Path, suffix: str, *, old: bool) -> Path | None:
    names = (
        ("oldV", "old") if old else ("newV", "new")
    )
    for stem in names:
        path = directory / f"{stem}{suffix}"
        if path.is_file():
            return path
    return None


def has_snippet(path: Path) -> bool:
    return bool(re.search(r"\bsnippet\s*\(", path.read_text(encoding="utf-8", errors="replace")))


def has_main(path: Path) -> bool:
    return bool(
        re.search(
            r"\bint\s+main\s*\(",
            path.read_text(encoding="utf-8", errors="replace"),
        )
    )


def _scalar_args(raw_args: str) -> list[tuple[str, str]]:
    args: list[tuple[str, str]] = []
    if not raw_args.strip() or raw_args.strip() == "void":
        return args
    for raw_arg in raw_args.split(","):
        declaration = raw_arg.strip()
        if "*" in declaration or "[" in declaration:
            raise ValueError(f"unsupported pointer/array argument: {declaration}")
        tokens = declaration.split()
        c_type = next(
            (token for token in tokens if token in SCALAR_ARGUMENT_TYPES),
            None,
        )
        if c_type is None or len(tokens) < 2:
            raise ValueError(f"unsupported argument declaration: {declaration}")
        args.append((c_type, tokens[-1]))
    return args


def _parse_c_functions(text: str) -> list[CFunction]:
    functions: list[CFunction] = []
    pattern = re.compile(
        r"(?m)^[ \t]*(?P<ret>(?:const\s+)?(?:unsigned\s+)?"
        r"(?:bool|char|double|float|int|long|short|void))\s+"
        r"(?P<name>[A-Za-z_]\w*)\s*\((?P<args>[^)]*)\)\s*\{"
    )
    for match in pattern.finditer(text):
        open_index = text.find("{", match.start())
        close_index = _matching_brace(text, open_index)
        functions.append(
            CFunction(
                return_type=" ".join(match.group("ret").split()),
                name=match.group("name"),
                raw_args=match.group("args"),
                body=text[open_index + 1 : close_index],
            )
        )
    return functions


def _rename_function_definition(text: str, name: str, replacement: str) -> str:
    pattern = re.compile(
        r"(?m)^([ \t]*(?:const\s+)?(?:unsigned\s+)?"
        r"(?:bool|char|double|float|int|long|short|void)\s+)"
        + re.escape(name)
        + r"(\s*\()"
    )
    renamed, count = pattern.subn(rf"\g<1>{replacement}\g<2>", text, count=1)
    if count != 1:
        raise ValueError(f"could not rename function definition: {name}")
    return renamed


def _writes_observable_global(text: str, body: str, entry_name: str) -> bool:
    """Conservatively detect a write to a file-scope variable in a void entry."""
    function_start = re.search(
        r"(?m)^[ \t]*(?:const\s+)?(?:unsigned\s+)?"
        r"(?:bool|char|double|float|int|long|short|void)\s+"
        + re.escape(entry_name)
        + r"\s*\([^)]*\)\s*\{",
        text,
    )
    prefix = text[: function_start.start()] if function_start else text
    globals_found: set[str] = set()
    for match in re.finditer(
        r"(?m)^[ \t]*(?:static\s+)?(?:const\s+)?"
        r"(?:unsigned\s+)?[A-Za-z_]\w*\s+"
        r"(?P<decls>[^;]+);",
        prefix,
    ):
        for declaration in match.group("decls").split(","):
            name_match = re.search(r"([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*(?:=.*)?$", declaration)
            if name_match:
                globals_found.add(name_match.group(1))
    for name in globals_found:
        if re.search(
            rf"\b{re.escape(name)}\s*(?:\[[^\]]*\])?\s*"
            r"(?:[+\-*/%&|^]?=|\+\+|--)",
            body,
        ):
            return True
    return False


def _has_supported_output_call(body: str) -> bool:
    """Return whether a void entry emits one of the modeled stdio calls."""
    return bool(
        re.search(
            r"\b(?:printf|fprintf|puts|fputs|putchar|putc|fputc)\s*\(",
            body,
        )
    )


def _has_observable_entry_effect(
    text: str,
    body: str,
    entry_name: str,
) -> bool:
    """Void entries require a modeled effect to carry a semantic summary."""
    return _has_supported_output_call(body) or _writes_observable_global(
        text,
        body,
        entry_name,
    )


def _normalized_body(body: str) -> str:
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
    body = re.sub(r"//[^\n]*", "", body)
    return re.sub(r"\s+", "", body)


def _java_method_names(path: Path | None) -> tuple[list[str], list[str]]:
    """Return public and all Java method names in declaration order."""
    if path is None or not path.is_file():
        return [], []
    text = path.read_text(encoding="utf-8", errors="replace")
    class_match = re.search(r"\bclass\s+([A-Za-z_]\w*)", text)
    class_name = class_match.group(1) if class_match else ""
    ignored = {"if", "for", "while", "switch", "catch", "return", "new"}
    public: list[str] = []
    all_methods: list[str] = []
    pattern = re.compile(
        r"(?m)^[ \t]*(?P<public>public\s+)?"
        r"(?:static\s+)?(?:final\s+)?"
        r"[A-Za-z_][\w<>\[\],.? ]*\s+"
        r"(?P<name>[A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{"
    )
    for match in pattern.finditer(text):
        name = match.group("name")
        if name in ignored or name == class_name:
            continue
        all_methods.append(name)
        if match.group("public"):
            public.append(name)
    return public, all_methods


def select_function_entry(
    old_text: str,
    new_text: str,
    *,
    program: str,
    entry_hint: str | None = None,
    old_java: Path | None,
    new_java: Path | None,
) -> str:
    """Select one auditable scalar entry that exists in both source variants.

    Selection is deterministic and corpus-independent.  It prefers a function
    matching the benchmark name, then a uniquely changed function, then a
    uniquely public Java method.  Ambiguous cases remain unsupported rather
    than guessing an unrelated helper.
    """
    old_functions = _parse_c_functions(old_text)
    new_functions = _parse_c_functions(new_text)
    new_by_name = {function.name: function for function in new_functions}
    old_names_in_order = [function.name for function in old_functions]
    common = [
        name
        for name in old_names_in_order
        if name in new_by_name and name != "main" and name != "snippet"
    ]
    if not common:
        raise ValueError("no common scalar C function")

    old_by_name = {function.name: function for function in old_functions}
    changed = [
        name
        for name in common
        if _normalized_body(old_by_name[name].body)
        != _normalized_body(new_by_name[name].body)
    ]
    old_public, old_methods = _java_method_names(old_java)
    new_public, new_methods = _java_method_names(new_java)
    public = [name for name in old_public if name in set(new_public) and name in common]
    java_common = [
        name for name in old_methods if name in set(new_methods) and name in common
    ]
    program_hint = Path(program.replace("\\", "/")).name
    hints = [program_hint]
    if entry_hint:
        hints.insert(0, entry_hint.split(".")[-1])

    ordered_rules: list[tuple[str, list[str]]] = [
        (
            "declared_program_name",
            [
                name
                for name in common
                if any(name.lower() == hint.lower() for hint in hints)
            ],
        ),
        ("public_changed", [name for name in changed if name in public]),
        ("public_method", public),
        ("changed", changed),
        ("java_method", java_common),
        ("only_function", common if len(common) == 1 else []),
    ]
    for _rule, candidates in ordered_rules:
        unique = list(dict.fromkeys(candidates))
        if len(unique) == 1:
            return unique[0]
    raise ValueError("ambiguous scalar entry: " + ", ".join(common))


def _append_harness(text: str, return_type: str, args: list[tuple[str, str]], target: str) -> str:
    if return_type == "void":
        raise ValueError(f"void {target} has no scalar return summary")

    includes = ""
    if "#include <stdio.h>" not in text:
        includes += "#include <stdio.h>\n"
    if "#include <math.h>" not in text:
        includes += "#include <math.h>\n"
    declarations = "\n".join(f"    {typ} {name};" for typ, name in args)
    scanf_fmt = " ".join(
        "%lf" if typ == "double" else "%f" if typ == "float" else "%ld" if typ == "long" else "%d"
        for typ, _name in args
    )
    scanf_args = ", ".join(f"&{name}" for _typ, name in args)
    call_args = ", ".join(name for _typ, name in args)
    scanf_line = (
        f'    scanf("{scanf_fmt}", {scanf_args});'
        if args
        else "    /* no symbolic input */"
    )
    result_fmt = "%a" if return_type in {"double", "float"} else "%ld" if return_type == "long" else "%d"
    harness = (
        "\n\nint main(void) {\n"
        "    /* Inputs are replaced by symbolic values by the angr scanf hook. */\n"
        f"{declarations}\n"
        f"{scanf_line}\n"
        f"    {return_type} result = {target}({call_args});\n"
        f'    printf("Result: {result_fmt}\\n", result);\n'
        "    return 0;\n"
        "}\n"
    )
    return includes + ("\n" if includes else "") + text + harness


def wrap_snippet_source(path: Path) -> str:
    """Append a precision-preserving harness to an existing C snippet.

    The OSF C files already contain any benchmark helper functions.  Reusing
    those files avoids losing helper definitions during Java-to-C translation.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(
        r"(?m)^\s*(?P<ret>(?:const\s+)?(?:unsigned\s+)?"
        r"(?:bool|char|int|long|double|float|short|void))\s+snippet\s*"
        r"\((?P<args>[^)]*)\)\s*\{",
        text,
    )
    if not match:
        raise ValueError("snippet signature not found")
    args = _scalar_args(match.group("args"))
    return_type = " ".join(match.group("ret").split())
    if return_type == "void":
        function = next(
            (item for item in _parse_c_functions(text) if item.name == "snippet"),
            None,
        )
        if function is None or not _has_observable_entry_effect(
            text,
            function.body,
            "snippet",
        ):
            raise ValueError(
                "void snippet has no observable global write or supported output"
            )
        renamed = _rename_function_definition(text, "snippet", "__benchmark_snippet")
        arg_decl = ", ".join(f"{typ} {name}" for typ, name in args) or "void"
        call_args = ", ".join(name for _typ, name in args)
        wrapper = (
            f"\n\nint snippet({arg_decl}) {{ "
            f"__benchmark_snippet({call_args}); "
            "return 0; "
            "}\n"
        )
        return _append_harness(renamed + wrapper, "int", args, "snippet")
    return _append_harness(text, return_type, args, "snippet")


def wrap_function_source(path: Path, entry_name: str) -> str:
    """Append a precision-preserving harness around a named scalar function."""
    text = path.read_text(encoding="utf-8", errors="replace")
    function = next(
        (item for item in _parse_c_functions(text) if item.name == entry_name),
        None,
    )
    if function is None:
        raise ValueError(f"entry function not found: {entry_name}")
    args = _scalar_args(function.raw_args)
    if function.return_type == "void":
        if not _has_observable_entry_effect(text, function.body, entry_name):
            raise ValueError(
                f"void {entry_name} has no observable global write or supported output"
            )
        renamed = _rename_function_definition(
            text, entry_name, f"__benchmark_{entry_name}"
        )
        arg_decl = ", ".join(f"{typ} {name}" for typ, name in args) or "void"
        call_args = ", ".join(name for _typ, name in args)
        wrapper = (
            f"\n\nint snippet({arg_decl}) {{ "
            f"__benchmark_{entry_name}({call_args}); "
            "return 0; "
            "}\n"
        )
        return _append_harness(renamed + wrapper, "int", args, "snippet")
    arg_decl = ", ".join(f"{typ} {name}" for typ, name in args) or "void"
    call_args = ", ".join(name for _typ, name in args)
    wrapper = (
        f"\n\n{function.return_type} snippet({arg_decl}) {{ "
        f"return {entry_name}({call_args}); "
        "}\n"
    )
    return _append_harness(text + wrapper, function.return_type, args, "snippet")


def _matching_brace(text: str, open_index: int) -> int:
    depth = 0
    for index in range(open_index, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    raise ValueError("unbalanced function body")


def wrap_main_source(path: Path) -> str:
    """Analyze the Java-equivalent public ``main`` method as the entry."""
    text = path.read_text(encoding="utf-8", errors="replace")
    main_match = re.search(
        r"(?m)^\s*int\s+main\s*\((?P<args>[^)]*)\)\s*\{",
        text,
    )
    if not main_match:
        raise ValueError("main signature not found")
    main_open = text.find("{", main_match.start())
    main_close = _matching_brace(text, main_open)
    main_body = text[main_open + 1 : main_close]
    raw_main_args = main_match.group("args").strip()
    args: list[tuple[str, str]] = []
    if raw_main_args and raw_main_args != "void":
        for declaration in raw_main_args.split(","):
            declaration = declaration.strip()
            name_match = re.search(r"([A-Za-z_]\w*)\s*$", declaration.strip())
            if name_match is None and "*" in declaration:
                pointer_name = re.search(r"\*\s*([A-Za-z_]\w*)", declaration)
                name_match = pointer_name
            if not name_match:
                raise ValueError(f"unsupported main argument: {declaration}")
            argument_name = name_match.group(1)
            if "*" in declaration or "[" in declaration:
                if re.search(rf"\b{re.escape(argument_name)}\b", main_body):
                    raise ValueError(
                        f"main process argument {argument_name} is used; cannot model it"
                    )
                continue
            args.extend(_scalar_args(declaration))
    arg_decl = ", ".join(f"{typ} {name}" for typ, name in args) or "void"
    call_args = ", ".join(name for _typ, name in args)
    renamed = (
        text[: main_match.start()]
        + f"int benchmark_original_main({arg_decl}) {{"
        + text[main_open + 1 :]
    )
    alias = (
        f"\n\nint snippet({arg_decl}) {{ "
        f"return benchmark_original_main({call_args}); "
        "}\n"
    )
    return _append_harness(renamed + alias, "int", args, "snippet")


def discover_cases(root: Path) -> list[tuple[Path, Path, Path, Path | None, Path | None]]:
    cases = []
    for directory in sorted(path for path in root.rglob("*") if path.is_dir()):
        old_c = find_variant(directory, ".c", old=True)
        new_c = find_variant(directory, ".c", old=False)
        if old_c is None or new_c is None:
            continue
        old_java = find_variant(directory, ".java", old=True)
        new_java = find_variant(directory, ".java", old=False)
        cases.append((directory, old_c, new_c, old_java, new_java))
    return cases


def read_entry_hint(directory: Path) -> str:
    description = directory / "Desc.json"
    if not description.is_file():
        return ""
    try:
        payload = json.loads(description.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(payload.get("program name") or payload.get("program_name") or "")


def read_upstream_benchmark_cases(script: Path | None) -> dict[str, dict[str, object]]:
    """Index the upstream runner's benchmark membership and per-case loop bounds."""
    if script is None or not script.is_file():
        return {}
    text = script.read_text(encoding="utf-8", errors="replace")
    cases: dict[str, dict[str, object]] = {}
    path_pattern = re.compile(
        r"--path1\s+\.\./benchmarks/(?P<rel>[^/\s]+/[^/\s]+/[^/\s]+)/oldV\.java"
    )
    for line in text.splitlines():
        path_match = path_pattern.search(line)
        if not path_match:
            continue
        rel = path_match.group("rel")
        parts = rel.split("/")
        lookup = rel
        if parts[0] == "ModDiff" and len(parts) == 3:
            lookup = f"CLEVER/{parts[2]}/{parts[1]}"
        elif parts[0] == "power" and len(parts) == 3:
            lookup = f"pow/{parts[1]}/{parts[2]}"
        bound_match = re.search(r"--b\s+(\d+)", line)
        record = cases.setdefault(
            lookup.lower(),
            {"pair": rel, "loop_bounds": [], "tool_invocations": 0},
        )
        record["tool_invocations"] = int(record["tool_invocations"]) + 1
        if bound_match:
            bound = int(bound_match.group(1))
            bounds = record["loop_bounds"]
            assert isinstance(bounds, list)
            if bound not in bounds:
                bounds.append(bound)
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--osf-root", type=Path, default=DEFAULT_OSF_ROOT)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("experiments/osf_all"),
    )
    parser.add_argument(
        "--ardiff-script",
        type=Path,
        default=Path("benchmark/ardiff/RunningBenchmarksOnLinux.sh"),
    )
    args = parser.parse_args()

    osf_root = args.osf_root.resolve()
    output_root = args.output_root.resolve()
    typed_root = output_root / "benchmarks_typed"
    typed_root.mkdir(parents=True, exist_ok=True)
    upstream_cases = read_upstream_benchmark_cases(args.ardiff_script)

    rows = []
    for index, (directory, old_c, new_c, old_java, new_java) in enumerate(
        discover_cases(osf_root), 1
    ):
        rel = directory.relative_to(osf_root)
        parts = rel.parts
        family = parts[0]
        label = parts[-1]
        program = "/".join(parts[1:-1])
        pair_id = f"{family}/{program}_{'Eq' if label.lower() == 'eq' else 'NEq'}"
        typed_dir = typed_root / rel
        status = "unsupported"
        reason = ""
        typed_old = ""
        typed_new = ""
        entry_name = ""
        entry_signature = ""
        selection_rule = ""
        entry_hint = read_entry_hint(directory)
        upstream = upstream_cases.get(rel.as_posix().lower())

        if has_snippet(old_c) and has_snippet(new_c):
            if not old_java or not new_java:
                reason = "missing_java_variant"
            else:
                try:
                    old_text = wrap_snippet_source(old_c)
                    new_text = wrap_snippet_source(new_c)
                    typed_dir.mkdir(parents=True, exist_ok=True)
                    old_target = typed_dir / "symbolic_oldV.c"
                    new_target = typed_dir / "symbolic_newV.c"
                    old_target.write_text(old_text, encoding="utf-8")
                    new_target.write_text(new_text, encoding="utf-8")
                    typed_old = old_target.as_posix()
                    typed_new = new_target.as_posix()
                    status = "supported_snippet"
                    entry_name = "snippet"
                    selection_rule = "existing_snippet"
                except Exception as exc:  # noqa: BLE001
                    reason = f"translation_failed:{exc}"
        elif has_main(old_c) and has_main(new_c):
            typed_dir.mkdir(parents=True, exist_ok=True)
            old_target = typed_dir / "symbolic_oldV.c"
            new_target = typed_dir / "symbolic_newV.c"
            try:
                old_target.write_text(wrap_main_source(old_c), encoding="utf-8")
                new_target.write_text(wrap_main_source(new_c), encoding="utf-8")
                typed_old = old_target.as_posix()
                typed_new = new_target.as_posix()
                status = "supported_main"
                entry_name = "main"
                selection_rule = "declared_java_main"
            except Exception as exc:  # noqa: BLE001
                status = "unsupported"
                reason = f"main_target_wrap_failed:{exc}"
        elif all(path is not None for path in (old_java, new_java)):
            try:
                old_text = old_c.read_text(encoding="utf-8", errors="replace")
                new_text = new_c.read_text(encoding="utf-8", errors="replace")
                entry_name = select_function_entry(
                    old_text,
                    new_text,
                    program=program,
                    entry_hint=entry_hint,
                    old_java=old_java,
                    new_java=new_java,
                )
                old_entry = next(
                    item for item in _parse_c_functions(old_text) if item.name == entry_name
                )
                new_entry = next(
                    item for item in _parse_c_functions(new_text) if item.name == entry_name
                )
                old_types = [typ for typ, _name in _scalar_args(old_entry.raw_args)]
                new_types = [typ for typ, _name in _scalar_args(new_entry.raw_args)]
                if old_entry.return_type != new_entry.return_type or old_types != new_types:
                    raise ValueError(
                        "entry type signature differs between variants: "
                        f"{old_entry.return_type}({','.join(old_types)}) vs "
                        f"{new_entry.return_type}({','.join(new_types)})"
                    )
                old_text = wrap_function_source(old_c, entry_name)
                new_text = wrap_function_source(new_c, entry_name)
                typed_dir.mkdir(parents=True, exist_ok=True)
                old_target = typed_dir / "symbolic_oldV.c"
                new_target = typed_dir / "symbolic_newV.c"
                old_target.write_text(old_text, encoding="utf-8")
                new_target.write_text(new_text, encoding="utf-8")
                typed_old = old_target.as_posix()
                typed_new = new_target.as_posix()
                status = "supported_function"
                selection_rule = "scalar_function_wrapper"
                entry_signature = f"{old_entry.return_type}({old_entry.raw_args.strip()})"
            except Exception as exc:  # noqa: BLE001
                status = "unsupported"
                reason = f"function_wrap_failed:{exc}"
        else:
            reason = "no_common_snippet_or_main_entry"

        if status == "unsupported":
            for stale_name in ("symbolic_oldV.c", "symbolic_newV.c"):
                stale = typed_dir / stale_name
                if stale.is_file():
                    stale.unlink()

        rows.append(
            {
                "case_id": pair_id,
                "family": family,
                "program": program,
                "label": "EQ" if label.lower() == "eq" else "NEQ",
                "support_status": status,
                "reason": reason,
                "source_case": rel.as_posix(),
                "old_c": old_c.relative_to(osf_root).as_posix(),
                "new_c": new_c.relative_to(osf_root).as_posix(),
                "old_c_sha256": sha256(old_c),
                "new_c_sha256": sha256(new_c),
                "old_java": old_java.relative_to(osf_root).as_posix() if old_java else "",
                "new_java": new_java.relative_to(osf_root).as_posix() if new_java else "",
                "typed_old": (
                    Path(typed_old).relative_to(output_root).as_posix() if typed_old else ""
                ),
                "typed_new": (
                    Path(typed_new).relative_to(output_root).as_posix() if typed_new else ""
                ),
                "entry_name": entry_name,
                "entry_signature": entry_signature,
                "selection_rule": selection_rule,
                "upstream_ardiff_pair": str(upstream["pair"]) if upstream else "",
                "upstream_loop_bounds": (
                    ",".join(str(value) for value in upstream["loop_bounds"])
                    if upstream
                    else ""
                ),
                "upstream_tool_invocations": (
                    int(upstream["tool_invocations"]) if upstream else 0
                ),
            }
        )
        if index % 25 == 0:
            print(f"staged {index} cases", flush=True)

    output_root.mkdir(parents=True, exist_ok=True)
    manifest = output_root / "manifest_all.csv"
    with manifest.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    supported = sum(row["support_status"].startswith("supported") for row in rows)
    upstream_count = sum(bool(row["upstream_ardiff_pair"]) for row in rows)
    print(f"staged {supported}/{len(rows)} OSF cases; manifest={manifest}")
    print(f"matched {upstream_count} cases in the upstream ARDiff runner")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

