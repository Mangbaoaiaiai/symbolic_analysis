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
from typing import Any

DEFAULT_OSF_ROOT = Path("benchmark/osf_sources/benchmarks")
DEFAULT_ENTRY_CONFIG = Path("configs/osf_entry_overrides.json")
SCALAR_RETURN_TYPES = {"bool", "char", "double", "float", "int", "long", "short", "void"}
SCALAR_ARGUMENT_TYPES = {"bool", "char", "double", "float", "int", "long", "short"}


@dataclass(frozen=True)
class CFunction:
    return_type: str
    name: str
    raw_args: str
    body: str


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge configuration dictionaries without mutating either input."""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_entry_config(path: Path | None) -> dict[str, Any]:
    """Load entry/type overrides; a missing default file means legacy behavior."""
    empty: dict[str, Any] = {
        "version": 1,
        "defaults": {"selection": "desc_then_heuristic"},
        "families": {},
        "programs": {},
        "cases": {},
    }
    if path is None or not path.is_file():
        return empty
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read entry configuration {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("entry configuration root must be a JSON object")
    payload = dict(payload)
    inherited = payload.pop("extends", None)
    if inherited is None:
        result = _deep_merge(empty, payload)
    else:
        if not isinstance(inherited, str) or not inherited.strip():
            raise ValueError("entry configuration extends must be a non-empty string")
        parent_path = path.parent / inherited
        result = _deep_merge(load_entry_config(parent_path), payload)
    for section in ("families", "programs", "cases"):
        value = result.get(section)
        if not isinstance(value, dict):
            raise ValueError(f"entry configuration section {section!r} must be an object")
        result[section] = {
            str(key).replace("\\", "/").lower(): item for key, item in value.items()
        }
        for key, item in result[section].items():
            if not isinstance(item, dict):
                raise ValueError(
                    f"entry configuration {section}[{key!r}] must be an object"
                )
    return result


def resolve_entry_config(
    config: dict[str, Any],
    *,
    case_id: str,
    family: str,
    program_id: str,
) -> dict[str, Any]:
    """Resolve family, program, then exact-case overrides in that order."""
    resolved: dict[str, Any] = {}
    sources: list[str] = []
    keys = (
        ("families", family.lower(), "family"),
        ("programs", program_id.replace("\\", "/").lower(), "program"),
        ("cases", case_id.lower(), "case"),
    )
    for section, key, label in keys:
        item = config.get(section, {}).get(key)
        if isinstance(item, dict):
            resolved = _deep_merge(resolved, item)
            sources.append(f"{label}:{key}")
    resolved["_config_source"] = "+".join(sources) if sources else "automatic"
    return resolved


def _config_entry_names(config: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return old/new entry names from a string or per-variant mapping."""
    entry = config.get("entry")
    if isinstance(entry, str) and entry.strip():
        name = entry.strip()
        return name, name
    if not isinstance(entry, dict):
        return None, None
    old = str(entry.get("old") or entry.get("old_name") or "").strip() or None
    new = str(entry.get("new") or entry.get("new_name") or "").strip() or None
    old = old or new
    new = new or old
    return old, new


def _configured_named_types(config: dict[str, Any]) -> set[str]:
    """Collect function argument/return types that need the named-type parser."""
    named: set[str] = set()
    pending = [config]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        targets = current.get("targets")
        if isinstance(targets, list):
            pending.extend(item for item in targets if isinstance(item, dict))
        return_value = current.get("return") or current.get("return_type")
        if isinstance(return_value, dict):
            return_value = return_value.get("type")
        if isinstance(return_value, str):
            normalized = return_value.replace("*", " ").replace("[]", " ").split()
            if normalized and normalized[-1] not in SCALAR_RETURN_TYPES:
                named.add(normalized[-1])
        for parameter in current.get("params") or []:
            if not isinstance(parameter, dict):
                continue
            value = parameter.get("type")
            if isinstance(value, str):
                normalized = value.replace("*", " ").replace("[]", " ").split()
                if normalized and normalized[-1] not in SCALAR_ARGUMENT_TYPES:
                    named.add(normalized[-1])
            for field in parameter.get("fields") or []:
                if isinstance(field, dict):
                    value = field.get("type")
                    if isinstance(value, str):
                        normalized = value.replace("*", " ").replace("[]", " ").split()
                        if normalized and normalized[-1] not in SCALAR_ARGUMENT_TYPES:
                            named.add(normalized[-1])
    return named


def configured_targets(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the target specifications for a joint all-methods case."""
    raw_targets = config.get("targets")
    if raw_targets is None:
        return [config]
    if not isinstance(raw_targets, list) or not raw_targets:
        raise ValueError("configured targets must be a non-empty list")
    base = {
        key: value
        for key, value in config.items()
        if key not in {"targets", "name"} and not key.startswith("_")
    }
    targets: list[dict[str, Any]] = []
    for index, raw_target in enumerate(raw_targets):
        if not isinstance(raw_target, dict):
            raise ValueError(f"configured target {index} must be an object")
        target = _deep_merge(base, raw_target)
        name = str(target.get("name") or f"target_{index}")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ValueError(f"invalid target name: {name!r}")
        target["name"] = name
        targets.append(target)
    names = [str(target["name"]) for target in targets]
    if len(names) != len(set(names)):
        raise ValueError("configured target names must be unique")
    return targets


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


def _split_parameter_declarations(raw_args: str) -> list[str]:
    """Split a C parameter list while respecting nested brackets."""
    raw_args = raw_args.strip()
    if not raw_args or raw_args == "void":
        return []
    declarations: list[str] = []
    current: list[str] = []
    depth = 0
    for character in raw_args:
        if character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
        if character == "," and depth == 0:
            declarations.append("".join(current).strip())
            current = []
        else:
            current.append(character)
    if current:
        declarations.append("".join(current).strip())
    return declarations


def _declaration_name(declaration: str) -> str:
    match = re.search(
        r"([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*$",
        declaration.strip(),
    )
    if match is None:
        raise ValueError(f"cannot determine parameter name: {declaration}")
    return match.group(1)


def _declaration_base_type(declaration: str) -> str:
    name = _declaration_name(declaration)
    prefix = declaration[: declaration.rfind(name)]
    tokens = [
        token
        for token in prefix.replace("*", " ").replace("[", " ").replace("]", " ").split()
        if token not in {"const", "volatile", "register", "static", "unsigned", "signed"}
    ]
    if not tokens:
        raise ValueError(f"cannot determine parameter type: {declaration}")
    return tokens[-1]


def _declaration_shape(declaration: str) -> tuple[str, str]:
    pointer_kind = "pointer/array" if "*" in declaration or "[" in declaration else "value"
    return (_declaration_base_type(declaration), pointer_kind)


def _configured_type_name(value: str) -> str:
    tokens = value.replace("*", " ").replace("[", " ").replace("]", " ").split()
    if not tokens:
        raise ValueError("configured type cannot be empty")
    return tokens[-1]


def _printf_format(type_name: str) -> str:
    if type_name in {"float", "double"}:
        return "%a"
    if type_name == "long":
        return "%ld"
    return "%d"


def _configured_call(
    function: CFunction,
    config: dict[str, Any],
    *,
    argument_offset: int = 0,
    declaration_prefix: str = "__param_",
    force_flatten: bool = False,
) -> tuple[list[tuple[str, str]], list[str], list[str], list[str]]:
    """Build flattened scalar inputs and the call to the configured entry."""
    declarations = _split_parameter_declarations(function.raw_args)
    parameters = config.get("params")
    if parameters is None and not force_flatten:
        args = _scalar_args(function.raw_args)
        return args, [], [name for _typ, name in args], []
    if parameters is None:
        parameters = [{"name": _declaration_name(item)} for item in declarations]
    if not isinstance(parameters, list):
        raise ValueError("configured params must be a list")
    if len(parameters) != len(declarations):
        raise ValueError(
            f"configured {len(parameters)} params for {len(declarations)} function arguments"
        )

    flattened: list[tuple[str, str]] = []
    declarations_out: list[str] = []
    guards: list[str] = []
    call_args: list[str] = []

    def add_scalar(type_name: str, prefix: str, bounds: Any = None) -> str:
        if type_name not in SCALAR_ARGUMENT_TYPES:
            raise ValueError(f"unsupported scalar field type: {type_name}")
        argument = f"arg_{argument_offset + len(flattened)}"
        flattened.append((type_name, argument))
        if isinstance(bounds, dict):
            minimum = bounds.get("min")
            maximum = bounds.get("max")
            conditions: list[str] = []
            if minimum is not None:
                conditions.append(f"{argument} < {minimum}")
            if maximum is not None:
                conditions.append(f"{argument} > {maximum}")
            if conditions:
                guards.append(
                    f"    if ({' || '.join(conditions)}) {{ return 0; }}"
                )
        return argument

    for index, (declaration, parameter) in enumerate(zip(declarations, parameters)):
        if not isinstance(parameter, dict):
            raise ValueError(f"configured param {index} must be an object")
        actual_name = _declaration_name(declaration)
        configured_name = str(parameter.get("name") or actual_name)
        if configured_name != actual_name:
            raise ValueError(
                f"configured parameter {configured_name!r} does not match {actual_name!r}"
            )
        mode = str(parameter.get("mode") or "scalar")
        configured_type = str(parameter.get("type") or _declaration_base_type(declaration))

        if mode == "scalar":
            scalar_type, _name = _scalar_args(declaration)[0]
            if _configured_type_name(configured_type) != scalar_type:
                raise ValueError(
                    f"configured scalar type {configured_type} does not match {scalar_type}"
                )
            call_args.append(add_scalar(scalar_type, actual_name, parameter.get("bounds")))
            continue

        if mode in {"record", "struct"}:
            if "*" in declaration or "[" in declaration:
                raise ValueError(
                    f"record parameter {actual_name} must be passed by value"
                )
            if _configured_type_name(configured_type) != _declaration_base_type(declaration):
                raise ValueError(
                    f"configured record type {configured_type} does not match {declaration}"
                )
            local = f"{declaration_prefix}{index}"
            declarations_out.append(f"    {configured_type} {local} = {{0}};")
            fields = parameter.get("fields")
            if not isinstance(fields, list) or not fields:
                raise ValueError(f"record parameter {actual_name} needs scalar fields")
            for field in fields:
                if not isinstance(field, dict):
                    raise ValueError(f"record field in {actual_name} must be an object")
                path = str(field.get("path") or "")
                if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", path):
                    raise ValueError(f"unsupported record field path: {path!r}")
                field_type = str(field.get("type") or "")
                argument = add_scalar(
                    field_type,
                    f"{actual_name}.{path}",
                    field.get("bounds"),
                )
                declarations_out.append(f"    {local}.{path} = {argument};")
            call_args.append(local)
            continue

        if mode in {"array", "pointer_array"}:
            configured_base = _configured_type_name(configured_type)
            if configured_base not in SCALAR_ARGUMENT_TYPES:
                raise ValueError(f"unsupported array element type: {configured_type}")
            if "*" not in declaration and "[" not in declaration:
                raise ValueError(f"array parameter {actual_name} is not an array/pointer")
            length_value = parameter.get("length", parameter.get("max_length"))
            if not isinstance(length_value, int) or length_value <= 0:
                raise ValueError(f"array parameter {actual_name} needs positive length")
            local = f"{declaration_prefix}{index}"
            declarations_out.append(
                f"    {configured_base} {local}[{length_value}] = {{0}};"
            )
            element_bounds = parameter.get(
                "element_bounds",
                parameter.get("bounds"),
            )
            for element in range(length_value):
                argument = add_scalar(
                    configured_base,
                    f"{actual_name}[{element}]",
                    element_bounds,
                )
                declarations_out.append(f"    {local}[{element}] = {argument};")
            call_args.append(local)
            continue

        raise ValueError(f"unsupported configured parameter mode: {mode}")
    return flattened, declarations_out, call_args, guards


def _parse_c_functions(
    text: str,
    extra_return_types: set[str] | None = None,
) -> list[CFunction]:
    """Parse function definitions, optionally admitting configured named types."""
    functions: list[CFunction] = []
    return_types = SCALAR_RETURN_TYPES | (extra_return_types or set())
    type_pattern = "|".join(
        re.escape(item) for item in sorted(return_types, key=len, reverse=True)
    )
    pattern = re.compile(
        r"(?m)^[ \t]*(?P<ret>(?:const\s+)?(?:unsigned\s+)?"
        + type_pattern
        + r")\s+"
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
    extra_return_types: set[str] | None = None,
) -> str:
    """Select one auditable scalar entry that exists in both source variants.

    Selection is deterministic and corpus-independent.  It prefers a function
    matching the benchmark name, then a uniquely changed function, then a
    uniquely public Java method.  Ambiguous cases remain unsupported rather
    than guessing an unrelated helper.
    """
    old_functions = _parse_c_functions(old_text, extra_return_types)
    new_functions = _parse_c_functions(new_text, extra_return_types)
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


def _target_entry_name(target: dict[str, Any], variant: str) -> str:
    """Resolve a target's entry name for one source variant."""
    entry = target.get("entry")
    if isinstance(entry, str) and entry.strip():
        return entry.strip()
    if isinstance(entry, dict):
        name = str(
            entry.get(variant)
            or entry.get(f"{variant}_name")
            or entry.get("new" if variant == "new" else "old")
            or ""
        ).strip()
        if name:
            return name
    raise ValueError(f"target {target.get('name')!r} has no {variant} entry")


def _c_string_literal(value: str) -> str:
    """Encode a short ASCII target label as a C string literal."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _validated_scalar_fields(
    value: Any,
    *,
    description: str,
    allow_empty: bool = False,
) -> list[tuple[str, str]]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ValueError(f"{description} needs scalar fields")
    fields: list[tuple[str, str]] = []
    for field in value:
        if not isinstance(field, dict):
            raise ValueError(f"{description} fields must be objects")
        path_value = str(field.get("path") or "")
        if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", path_value):
            raise ValueError(f"unsupported {description} field path: {path_value!r}")
        field_type = str(field.get("type") or "")
        if field_type not in SCALAR_ARGUMENT_TYPES:
            raise ValueError(f"unsupported {description} field type: {field_type}")
        fields.append((path_value, field_type))
    return fields


def apply_source_repairs(text: str, config: dict[str, Any]) -> str:
    """Apply explicit C-translation repairs before building a target harness."""
    repairs = config.get("source_repairs", [])
    if repairs in (None, []):
        return text
    if not isinstance(repairs, list):
        raise ValueError("source_repairs must be a list")
    repaired = text
    for index, repair in enumerate(repairs):
        if not isinstance(repair, dict):
            raise ValueError(f"source_repairs[{index}] must be an object")
        old = repair.get("old")
        new = repair.get("new")
        if not isinstance(old, str) or not old:
            raise ValueError(f"source_repairs[{index}].old must be a non-empty string")
        if not isinstance(new, str):
            raise ValueError(f"source_repairs[{index}].new must be a string")
        occurrences = repaired.count(old)
        if occurrences == 0:
            raise ValueError(
                f"source_repairs[{index}] did not match: {old!r}"
            )
        repaired = repaired.replace(old, new)
    return repaired


def wrap_targets_source(
    path: Path,
    config: dict[str, Any],
    *,
    variant: str,
    source_text: str | None = None,
) -> str:
    """Append one harness that executes every configured all-methods target."""
    if variant not in {"old", "new"}:
        raise ValueError("target variant must be 'old' or 'new'")
    text = (
        source_text
        if source_text is not None
        else path.read_text(encoding="utf-8", errors="replace")
    )
    targets = configured_targets(config)
    extra_types = _configured_named_types(config)
    functions = {function.name: function for function in _parse_c_functions(text, extra_types)}
    all_args: list[tuple[str, str]] = []
    declarations: list[str] = []
    guards: list[str] = []
    body: list[str] = []

    for index, target in enumerate(targets):
        name = str(target["name"])
        entry_name = _target_entry_name(target, variant)
        function = functions.get(entry_name)
        if function is None:
            raise ValueError(f"target {name!r} entry function not found: {entry_name}")

        return_spec = target.get("return")
        if isinstance(return_spec, str):
            return_spec = {"type": return_spec}
        if return_spec is None:
            return_type = target.get("return_type")
            return_spec = {"type": return_type} if isinstance(return_type, str) else {}
        if not isinstance(return_spec, dict):
            raise ValueError(f"target {name!r} return must be an object or type string")
        configured_return = str(return_spec.get("type") or function.return_type)
        if _configured_type_name(configured_return) != _configured_type_name(function.return_type):
            raise ValueError(
                f"target {name!r} configured return {configured_return} "
                f"does not match {function.return_type}"
            )

        target_args, target_declarations, call_args, target_guards = _configured_call(
            function,
            target,
            argument_offset=len(all_args),
            declaration_prefix=f"__target_{index}_param_",
            force_flatten=True,
        )
        all_args.extend(target_args)
        declarations.extend(target_declarations)
        guards.extend(target_guards)
        call = f"{entry_name}({', '.join(call_args)})"
        label = f"Target {name}:"
        observed = target.get("observe")
        if observed is not None:
            observations = _validated_scalar_fields(
                observed,
                description=f"target {name!r} observation",
                allow_empty=True,
            )
        else:
            observations = []

        function_base = _configured_type_name(function.return_type)
        result_name = f"__target_{index}_result"
        if function_base == "void":
            if observed is None and not _has_observable_entry_effect(
                text,
                function.body,
                entry_name,
            ):
                raise ValueError(
                    f"void target {name!r} has no observable output or configured observation"
                )
            body.append(f"    {call};")
            if observations:
                formats = " ".join(_printf_format(typ) for _path, typ in observations)
                values = ", ".join(path for path, _typ in observations)
                body.append(f'    printf("{label} {formats}\\n", {values});')
            else:
                body.append(f'    printf("{label} void\\n");')
            continue

        body.append(f"    {function.return_type} {result_name} = {call};")
        if function_base in SCALAR_RETURN_TYPES:
            witness = (result_name, function_base)
        else:
            fields = return_spec.get("fields")
            fields = _validated_scalar_fields(
                fields,
                description=f"target {name!r} return",
            )
            formats = " ".join(_printf_format(typ) for _path, typ in fields)
            values = ", ".join(f"{result_name}.{path}" for path, _typ in fields)
            body.append(f'    printf("{label} {formats}\\n", {values});')
            continue
        body.append(
            f'    printf("{label} {_printf_format(witness[1])}\\n", {witness[0]});'
        )

    arg_decl = ", ".join(f"{typ} {name}" for typ, name in all_args) or "void"
    wrapper_lines = ["", f"int snippet({arg_decl}) {{"]
    wrapper_lines.extend(declarations)
    wrapper_lines.extend(guards)
    wrapper_lines.extend(body)
    wrapper_lines.extend(["    return 0;", "}"])
    wrapper = "\n".join(wrapper_lines) + "\n"
    return _append_harness(text + wrapper, "int", all_args, "snippet")


def configured_target_signatures(
    path: Path,
    config: dict[str, Any],
    *,
    variant: str,
) -> list[tuple[str, str, list[tuple[str, str]]]]:
    """Return target names and C signatures for pair compatibility checks."""
    text = path.read_text(encoding="utf-8", errors="replace")
    extra_types = _configured_named_types(config)
    functions = {function.name: function for function in _parse_c_functions(text, extra_types)}
    signatures: list[tuple[str, str, list[tuple[str, str]]]] = []
    for target in configured_targets(config):
        name = str(target["name"])
        entry_name = _target_entry_name(target, variant)
        function = functions.get(entry_name)
        if function is None:
            raise ValueError(f"target {name!r} entry function not found: {entry_name}")
        shapes = [
            _declaration_shape(item)
            for item in _split_parameter_declarations(function.raw_args)
        ]
        signatures.append((name, function.return_type, shapes))
    return signatures


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


def wrap_function_source(
    path: Path,
    entry_name: str,
    *,
    config: dict[str, Any] | None = None,
) -> str:
    """Append a precision-preserving harness around a configured function."""
    config = config or {}
    text = path.read_text(encoding="utf-8", errors="replace")
    extra_types = _configured_named_types(config)
    function = next(
        (
            item
            for item in _parse_c_functions(text, extra_types)
            if item.name == entry_name
        ),
        None,
    )
    if function is None:
        raise ValueError(f"entry function not found: {entry_name}")

    return_spec = config.get("return")
    if isinstance(return_spec, str):
        return_spec = {"type": return_spec}
    if return_spec is None:
        return_spec = config.get("return_type")
        return_spec = {"type": return_spec} if isinstance(return_spec, str) else {}
    if not isinstance(return_spec, dict):
        raise ValueError("configured return must be an object or type string")
    return_type = str(return_spec.get("type") or function.return_type)
    function_return_base = _configured_type_name(function.return_type)
    if _configured_type_name(return_type) != function_return_base:
        raise ValueError(
            f"configured return type {return_type} does not match {function.return_type}"
        )

    configured_layout = bool(
        config.get("params")
        or return_spec.get("fields")
        or function_return_base not in SCALAR_RETURN_TYPES
    )

    if not configured_layout:
        args = _scalar_args(function.raw_args)
        if function_return_base == "void":
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

    args, declarations, call_args, guards = _configured_call(function, config)
    arg_decl = ", ".join(f"{typ} {name}" for typ, name in args) or "void"
    lines = [""]

    if function_return_base == "void":
        if not _has_observable_entry_effect(text, function.body, entry_name):
            raise ValueError(
                f"void {entry_name} has no observable global write or supported output"
            )
        renamed = _rename_function_definition(
            text, entry_name, f"__benchmark_{entry_name}"
        )
        lines.append(f"int snippet({arg_decl}) {{")
        lines.extend(declarations)
        lines.extend(guards)
        lines.append(f"    __benchmark_{entry_name}({', '.join(call_args)});")
        lines.append("    return 0;")
        lines.append("}")
        wrapper = "\n".join(lines) + "\n"
        return _append_harness(renamed + wrapper, "int", args, "snippet")

    if function_return_base in SCALAR_RETURN_TYPES:
        lines.append(f"{function.return_type} snippet({arg_decl}) {{")
        lines.extend(declarations)
        lines.extend(guards)
        lines.append(f"    return {entry_name}({', '.join(call_args)});")
        lines.append("}")
        wrapper = "\n".join(lines) + "\n"
        return _append_harness(text + wrapper, function.return_type, args, "snippet")

    fields = return_spec.get("fields")
    if not isinstance(fields, list) or not fields:
        raise ValueError(f"custom return type {function.return_type} needs scalar fields")
    field_paths: list[tuple[str, str]] = []
    for field in fields:
        if not isinstance(field, dict):
            raise ValueError("custom return fields must be objects")
        path_value = str(field.get("path") or "")
        if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", path_value):
            raise ValueError(f"unsupported return field path: {path_value!r}")
        field_type = str(field.get("type") or "")
        if field_type not in SCALAR_ARGUMENT_TYPES:
            raise ValueError(f"unsupported return field type: {field_type}")
        field_paths.append((path_value, field_type))

    formats = " ".join(_printf_format(type_name) for _path, type_name in field_paths)
    values = ", ".join(f"__result.{path}" for path, _type_name in field_paths)
    lines.append(f"int snippet({arg_decl}) {{")
    lines.extend(declarations)
    lines.extend(guards)
    lines.append(f"    {function.return_type} __result = {entry_name}({', '.join(call_args)});")
    lines.append(f'    printf("Result: {formats}\\n", {values});')
    lines.append("    return 0;")
    lines.append("}")
    wrapper = "\n".join(lines) + "\n"
    return _append_harness(text + wrapper, "int", args, "snippet")


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
    parser.add_argument(
        "--entry-config",
        type=Path,
        default=DEFAULT_ENTRY_CONFIG,
        help="Family/program/case entry and complex-type overrides.",
    )
    args = parser.parse_args()

    osf_root = args.osf_root.resolve()
    output_root = args.output_root.resolve()
    typed_root = output_root / "benchmarks_typed"
    typed_root.mkdir(parents=True, exist_ok=True)
    upstream_cases = read_upstream_benchmark_cases(args.ardiff_script)
    entry_configs = load_entry_config(args.entry_config)

    rows = []
    for index, (directory, old_c, new_c, old_java, new_java) in enumerate(
        discover_cases(osf_root), 1
    ):
        rel = directory.relative_to(osf_root)
        parts = rel.parts
        family = parts[0]
        label = parts[-1]
        program = "/".join(parts[1:-1])
        program_id = f"{family}/{program}"
        pair_id = f"{family}/{program}_{'Eq' if label.lower() == 'eq' else 'NEq'}"
        case_config = resolve_entry_config(
            entry_configs,
            case_id=pair_id,
            family=family,
            program_id=program_id,
        )
        entry_config_source = str(case_config.get("_config_source") or "automatic")
        typed_dir = typed_root / rel
        status = "unsupported"
        reason = ""
        typed_old = ""
        typed_new = ""
        entry_name = ""
        entry_old_name = ""
        entry_new_name = ""
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
                    old_target.write_text(old_text, encoding="utf-8", newline="\n")
                    new_target.write_text(new_text, encoding="utf-8", newline="\n")
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
                old_target.write_text(
                    wrap_main_source(old_c),
                    encoding="utf-8",
                    newline="\n",
                )
                new_target.write_text(
                    wrap_main_source(new_c),
                    encoding="utf-8",
                    newline="\n",
                )
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
                extra_return_types = _configured_named_types(case_config)
                if case_config.get("targets") is not None:
                    old_repaired_text = apply_source_repairs(
                        old_text,
                        case_config,
                    )
                    new_repaired_text = apply_source_repairs(
                        new_text,
                        case_config,
                    )
                    old_signatures = configured_target_signatures(
                        old_c,
                        case_config,
                        variant="old",
                    )
                    new_signatures = configured_target_signatures(
                        new_c,
                        case_config,
                        variant="new",
                    )
                    if old_signatures != new_signatures:
                        raise ValueError(
                            "configured target signatures differ between variants: "
                            f"{old_signatures} vs {new_signatures}"
                        )
                    old_text = wrap_targets_source(
                        old_c,
                        case_config,
                        variant="old",
                        source_text=old_repaired_text,
                    )
                    new_text = wrap_targets_source(
                        new_c,
                        case_config,
                        variant="new",
                        source_text=new_repaired_text,
                    )
                    entry_old_name = ",".join(
                        str(target.get("entry")) for target in configured_targets(case_config)
                    )
                    entry_new_name = entry_old_name
                    entry_name = "|".join(
                        str(target["name"]) for target in configured_targets(case_config)
                    )
                    entry_signature = "; ".join(
                        f"{name}:{return_type}{shapes}"
                        for name, return_type, shapes in old_signatures
                    )
                    status = "supported_targets"
                else:
                    configured_old, configured_new = _config_entry_names(case_config)
                    if configured_old and configured_new:
                        entry_old_name = configured_old
                        entry_new_name = configured_new
                        entry_name = (
                            configured_old
                            if configured_old == configured_new
                            else f"{configured_old}->{configured_new}"
                        )
                    else:
                        entry_name = select_function_entry(
                            old_text,
                            new_text,
                            program=program,
                            entry_hint=entry_hint,
                            old_java=old_java,
                            new_java=new_java,
                            extra_return_types=extra_return_types,
                        )
                        entry_old_name = entry_name
                        entry_new_name = entry_name
                    old_entry = next(
                        (
                            item
                            for item in _parse_c_functions(old_text, extra_return_types)
                            if item.name == entry_old_name
                        ),
                        None,
                    )
                    new_entry = next(
                        (
                            item
                            for item in _parse_c_functions(new_text, extra_return_types)
                            if item.name == entry_new_name
                        ),
                        None,
                    )
                    if old_entry is None:
                        raise ValueError(f"configured old entry not found: {entry_old_name}")
                    if new_entry is None:
                        raise ValueError(f"configured new entry not found: {entry_new_name}")
                    old_shapes = [
                        _declaration_shape(item)
                        for item in _split_parameter_declarations(old_entry.raw_args)
                    ]
                    new_shapes = [
                        _declaration_shape(item)
                        for item in _split_parameter_declarations(new_entry.raw_args)
                    ]
                    if old_entry.return_type != new_entry.return_type or old_shapes != new_shapes:
                        raise ValueError(
                            "entry type signature differs between variants: "
                            f"{old_entry.return_type}{old_shapes} vs "
                            f"{new_entry.return_type}{new_shapes}"
                        )
                    old_text = wrap_function_source(
                        old_c,
                        entry_old_name,
                        config=case_config,
                    )
                    new_text = wrap_function_source(
                        new_c,
                        entry_new_name,
                        config=case_config,
                    )
                    status = "supported_function"
                    entry_signature = f"{old_entry.return_type}({old_entry.raw_args.strip()})"
                typed_dir.mkdir(parents=True, exist_ok=True)
                old_target = typed_dir / "symbolic_oldV.c"
                new_target = typed_dir / "symbolic_newV.c"
                old_target.write_text(old_text, encoding="utf-8", newline="\n")
                new_target.write_text(new_text, encoding="utf-8", newline="\n")
                typed_old = old_target.as_posix()
                typed_new = new_target.as_posix()
                selection_rule = (
                    "configured_all_methods"
                    if status == "supported_targets"
                    else (
                        entry_config_source
                        if entry_config_source != "automatic"
                        else "scalar_function_wrapper"
                    )
                )
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
                "entry_old_name": entry_old_name,
                "entry_new_name": entry_new_name,
                "entry_config_source": entry_config_source,
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

