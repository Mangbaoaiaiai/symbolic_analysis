#!/usr/bin/env python3
"""Build compact SMT-LIB inclusion queries from serialized path formulas."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


class SmtPathUnionError(ValueError):
    pass


@dataclass(frozen=True)
class PathUnionQuery:
    text: str
    declarations: tuple[str, ...]
    source_path_count: int
    target_path_count: int
    unsupported_commands: tuple[str, ...] = ()


def build_path_union_query(
    source_texts: Sequence[str],
    target_texts: Sequence[str],
    *,
    extra_domain_expressions: Iterable[str] = (),
    extra_declarations: Iterable[str] = (),
) -> PathUnionQuery:
    """Create ``source-union and not target-union`` as compact SMT-LIB text.

    Only the command subset emitted by the project's path serializer is
    accepted. Unknown commands make the builder fail conservatively instead of
    guessing their semantics.
    """
    declarations: dict[str, str] = {}
    unsupported: set[str] = set()

    def parse_paths(texts: Sequence[str]) -> list[str]:
        expressions: list[str] = []
        for text in texts:
            assertions: list[str] = []
            for command in top_level_commands(text):
                head = command_head(command)
                if head in {"set-info", "set-logic", "check-sat"}:
                    continue
                if head in {
                    "declare-fun",
                    "declare-const",
                    "declare-sort",
                }:
                    name, normalized = declaration_identity(command)
                    previous = declarations.get(name)
                    if previous is not None and previous != normalized:
                        raise SmtPathUnionError(
                            f"conflicting declaration for {name}"
                        )
                    declarations[name] = normalized
                    continue
                if head == "assert":
                    assertions.append(assertion_body(command))
                    continue
                unsupported.add(head)
            if unsupported:
                break
            expressions.append(conjoin(assertions))
        if unsupported:
            return []
        return expressions

    source_expressions = parse_paths(source_texts)
    if unsupported:
        names = tuple(sorted(unsupported))
        return PathUnionQuery(
            "",
            (),
            len(source_texts),
            len(target_texts),
            names,
        )
    target_expressions = parse_paths(target_texts)
    if unsupported:
        names = tuple(sorted(unsupported))
        return PathUnionQuery(
            "",
            (),
            len(source_texts),
            len(target_texts),
            names,
        )
    for declaration in extra_declarations:
        head = command_head(str(declaration))
        if head not in {"declare-fun", "declare-const", "declare-sort"}:
            raise SmtPathUnionError(
                f"unsupported extra declaration: {head}"
            )
        name, normalized = declaration_identity(str(declaration))
        previous = declarations.get(name)
        if previous is not None and previous != normalized:
            raise SmtPathUnionError(
                f"conflicting declaration for {name}"
            )
        declarations[name] = normalized
    source_union = disjoin(source_expressions)
    target_union = disjoin(target_expressions)
    declaration_lines = [
        declarations[name] for name in sorted(declarations)
    ]
    lines = [
        "(set-logic ALL)",
        "(set-info :status unknown)",
        *declaration_lines,
        f"(assert {source_union})",
        f"(assert (not {target_union}))",
    ]
    lines.extend(
        f"(assert {str(expression).strip()})"
        for expression in extra_domain_expressions
        if str(expression).strip()
    )
    lines.append("(check-sat)")
    return PathUnionQuery(
        "\n".join(lines) + "\n",
        tuple(declaration_lines),
        len(source_texts),
        len(target_texts),
    )


def top_level_commands(text: str) -> list[str]:
    commands: list[str] = []
    position = 0
    length = len(text)
    while position < length:
        position = _skip_space_and_comments(text, position)
        if position >= length:
            break
        if text[position] != "(":
            raise SmtPathUnionError(
                f"unexpected token at byte {position}"
            )
        start = position
        position = _scan_balanced_command(text, position)
        commands.append(text[start:position].strip())
    return commands


def command_head(command: str) -> str:
    value = command.lstrip()
    if not value.startswith("("):
        raise SmtPathUnionError("command does not start with '('")
    position = 1
    while position < len(value) and value[position].isspace():
        position += 1
    end = position
    while end < len(value) and not value[end].isspace() and value[end] != ")":
        end += 1
    return value[position:end]


def assertion_body(command: str) -> str:
    if command_head(command) != "assert":
        raise SmtPathUnionError("command is not an assertion")
    body = command.lstrip()[1:].lstrip()
    body = body[len("assert") :].strip()
    if not body.endswith(")"):
        raise SmtPathUnionError("unterminated assert command")
    return body[:-1].strip()


def declaration_identity(command: str) -> tuple[str, str]:
    head = command_head(command)
    body = command.lstrip()[1:].lstrip()
    body = body[len(head) :].lstrip()
    if head == "declare-sort":
        name, _ = _split_first_atom(body)
        return name, command.strip()
    name, _ = _split_first_atom(body)
    return name, command.strip()


def conjoin(expressions: Sequence[str]) -> str:
    values = [value.strip() for value in expressions if value.strip()]
    if not values:
        return "true"
    if len(values) == 1:
        return values[0]
    return "(and " + " ".join(values) + ")"


def disjoin(expressions: Sequence[str]) -> str:
    values = [value.strip() for value in expressions if value.strip()]
    if not values:
        return "false"
    if len(values) == 1:
        return values[0]
    return "(or " + " ".join(values) + ")"


def _skip_space_and_comments(text: str, position: int) -> int:
    length = len(text)
    while position < length:
        if text[position].isspace():
            position += 1
            continue
        if text[position] == ";":
            newline = text.find("\n", position)
            return length if newline < 0 else _skip_space_and_comments(
                text,
                newline + 1,
            )
        break
    return position


def _scan_balanced_command(text: str, position: int) -> int:
    depth = 0
    in_string = False
    in_quoted_symbol = False
    while position < len(text):
        character = text[position]
        if in_string:
            if character == '"':
                if position + 1 < len(text) and text[position + 1] == '"':
                    position += 2
                    continue
                in_string = False
            position += 1
            continue
        if in_quoted_symbol:
            if character == "|":
                in_quoted_symbol = False
            position += 1
            continue
        if character == '"':
            in_string = True
            position += 1
            continue
        if character == "|":
            in_quoted_symbol = True
            position += 1
            continue
        if character == ";":
            newline = text.find("\n", position)
            if newline < 0:
                raise SmtPathUnionError("comment inside unterminated command")
            position = newline + 1
            continue
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return position + 1
            if depth < 0:
                raise SmtPathUnionError("unbalanced closing parenthesis")
        position += 1
    raise SmtPathUnionError("unterminated SMT-LIB command")


def _split_first_atom(text: str) -> tuple[str, str]:
    value = text.lstrip()
    if not value:
        raise SmtPathUnionError("missing declaration name")
    if value[0] == "|":
        end = value.find("|", 1)
        if end < 0:
            raise SmtPathUnionError("unterminated quoted symbol")
        return value[: end + 1], value[end + 1 :]
    for index, character in enumerate(value):
        if character.isspace() or character == ")":
            return value[:index], value[index:]
    return value, ""

