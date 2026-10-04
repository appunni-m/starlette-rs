#!/usr/bin/env python3
"""Check that the Rust core exposes its API only through named root exports.

This deliberately small source scanner uses only the Python standard library.
It tokenizes Rust while discarding comments and literals, so formatting and
commented examples cannot change the result. It is a policy check, not a Rust
parser; Cargo and rustc remain responsible for syntax and name resolution.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
CORE_SOURCE = ROOT / "starlette-rs" / "src"
CORE_ROOT = CORE_SOURCE / "lib.rs"
BINDING_SOURCE = ROOT / "starlette-rs-py" / "src"


class Token(NamedTuple):
    """A Rust token's source spelling and starting line."""

    kind: str
    value: str
    line: int


def skip_quoted(source: str, start: int, quote: str) -> int:
    """Return the position after a normal escaped string or character."""
    index = start + 1
    while index < len(source):
        if source[index] == "\\":
            index += 2
        elif source[index] == quote:
            return index + 1
        else:
            index += 1
    return len(source)


def skip_raw_string(source: str, start: int) -> int | None:
    """Skip Rust raw, byte-raw, or C-raw string literals when present."""
    prefix = next((value for value in ("br", "cr", "r") if source.startswith(value, start)), None)
    if prefix is None:
        return None
    index = start + len(prefix)
    while index < len(source) and source[index] == "#":
        index += 1
    if index >= len(source) or source[index] != '"':
        return None
    hashes = source[index - (index - start - len(prefix)) : index]
    terminator = '"' + hashes
    end = source.find(terminator, index + 1)
    return len(source) if end < 0 else end + len(terminator)


def skip_character(source: str, start: int) -> int | None:
    """Skip a character literal, leaving Rust lifetimes as tokens."""
    index = start + 1
    if index >= len(source) or source[index] in "\r\n":
        return None
    if source[index] == "\\":
        index += 1
        if index >= len(source):
            return None
        if source[index] == "u" and index + 1 < len(source) and source[index + 1] == "{":
            closing = source.find("}", index + 2)
            if closing < 0:
                return None
            index = closing + 1
        elif source[index] == "x":
            index += 3
        else:
            index += 1
    else:
        index += 1
    return index + 1 if index < len(source) and source[index] == "'" else None


def tokenize(source: str) -> list[Token]:
    """Produce identifiers and punctuation, omitting comments and literals."""
    result: list[Token] = []
    index = 0
    line = 1
    length = len(source)

    def advance(end: int) -> None:
        nonlocal index, line
        line += source[index:end].count("\n")
        index = end

    while index < length:
        char = source[index]
        if char.isspace():
            advance(index + 1)
            continue
        if source.startswith("//", index):
            end = source.find("\n", index + 2)
            advance(length if end < 0 else end)
            continue
        if source.startswith("/*", index):
            end = index + 2
            depth = 1
            while end < length and depth:
                if source.startswith("/*", end):
                    depth += 1
                    end += 2
                elif source.startswith("*/", end):
                    depth -= 1
                    end += 2
                else:
                    end += 1
            advance(end)
            continue

        raw_end = skip_raw_string(source, index)
        if raw_end is not None:
            advance(raw_end)
            continue
        if char == '"':
            advance(skip_quoted(source, index, '"'))
            continue
        if char in "bc" and index + 1 < length and source[index + 1] == '"':
            advance(skip_quoted(source, index + 1, '"'))
            continue
        if char == "'":
            character_end = skip_character(source, index)
            if character_end is not None:
                advance(character_end)
                continue
        if char == "b" and index + 1 < length and source[index + 1] == "'":
            character_end = skip_character(source, index + 1)
            if character_end is not None:
                advance(character_end)
                continue

        if source.startswith("r#", index) and index + 2 < length:
            ident_start = index + 2
            if source[ident_start].isalpha() or source[ident_start] == "_":
                end = ident_start + 1
                while end < length and (source[end].isalnum() or source[end] == "_"):
                    end += 1
                result.append(Token("ident", source[index:end], line))
                advance(end)
                continue
        if char.isalpha() or char == "_":
            end = index + 1
            while end < length and (source[end].isalnum() or source[end] == "_"):
                end += 1
            result.append(Token("ident", source[index:end], line))
            advance(end)
            continue
        if source.startswith("::", index):
            result.append(Token("punct", "::", line))
            advance(index + 2)
            continue

        result.append(Token("punct", char, line))
        advance(index + 1)

    return result


def identifier(token: Token) -> str:
    """Return an identifier's normalized name, including raw identifiers."""
    return token.value[2:] if token.value.startswith("r#") else token.value


def matching_delimiter(tokens: list[Token], start: int) -> int | None:
    """Find a matching Rust group delimiter, if one is present."""
    pairs = {"{": "}", "(": ")", "[": "]"}
    opening = tokens[start].value
    closing = pairs.get(opening)
    if closing is None:
        return None
    stack = [closing]
    for index in range(start + 1, len(tokens)):
        value = tokens[index].value
        if value in pairs:
            stack.append(pairs[value])
        elif value in pairs.values():
            if not stack or value != stack[-1]:
                return None
            stack.pop()
            if not stack:
                return index
    return None


def statement_end(tokens: list[Token], start: int) -> int | None:
    """Find a semicolon outside nested use-tree groups."""
    stack: list[str] = []
    pairs = {"{": "}", "(": ")", "[": "]"}
    closing = set(pairs.values())
    for index in range(start, len(tokens)):
        value = tokens[index].value
        if value in pairs:
            stack.append(pairs[value])
        elif value in closing:
            if not stack or stack.pop() != value:
                return None
        elif value == ";" and not stack:
            return index
    return None


def public_visibility_start(tokens: list[Token], item_index: int) -> int | None:
    """Return the `pub` token before an item, including restricted visibility."""
    previous = item_index - 1
    if previous >= 0 and tokens[previous].value == "pub":
        return previous
    if previous < 0 or tokens[previous].value != ")":
        return None
    depth = 1
    index = previous - 1
    while index >= 0:
        if tokens[index].value == ")":
            depth += 1
        elif tokens[index].value == "(":
            depth -= 1
            if depth == 0:
                return index - 1 if index > 0 and tokens[index - 1].value == "pub" else None
        index -= 1
    return None


def module_declarations(tokens: list[Token]) -> list[tuple[int, Token]]:
    """Return module declarations and their names, ignoring comments/literals."""
    return [
        (index, tokens[index + 1])
        for index, token in enumerate(tokens[:-1])
        if token.value == "mod" and tokens[index + 1].kind == "ident"
    ]


def root_module_names(tokens: list[Token]) -> set[str]:
    """Collect module names declared at the crate root."""
    names: set[str] = set()
    brace_depth = 0
    for index, token in enumerate(tokens):
        if token.value == "}" and brace_depth:
            brace_depth -= 1
        if (
            token.value == "mod"
            and brace_depth == 0
            and index + 1 < len(tokens)
            and tokens[index + 1].kind == "ident"
        ):
            names.add(identifier(tokens[index + 1]))
        if token.value == "{":
            brace_depth += 1
    return names


def top_level_public_use_statements(tokens: list[Token]) -> list[tuple[int, int]]:
    """Return token ranges for public crate-root `use` items."""
    statements: list[tuple[int, int]] = []
    brace_depth = 0
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if (
            brace_depth == 0
            and token.value == "pub"
            and index + 1 < len(tokens)
            and tokens[index + 1].value == "use"
        ):
            end = statement_end(tokens, index + 2)
            if end is None:
                index += 1
                continue
            statements.append((index, end))
            index = end + 1
            continue
        if token.value == "}" and brace_depth:
            brace_depth -= 1
        elif token.value == "{":
            brace_depth += 1
        index += 1
    return statements


def comma_separated_trees(tokens: list[Token], start: int, end: int) -> list[list[Token]]:
    """Split a use-tree group at commas outside nested delimiters."""
    trees: list[list[Token]] = []
    group_start = start
    stack: list[str] = []
    pairs = {"{": "}", "(": ")", "[": "]"}
    closing = set(pairs.values())
    for index in range(start, end):
        value = tokens[index].value
        if value in pairs:
            stack.append(pairs[value])
        elif value in closing and stack:
            stack.pop()
        elif value == "," and not stack:
            if group_start < index:
                trees.append(tokens[group_start:index])
            group_start = index + 1
    if group_start < end:
        trees.append(tokens[group_start:end])
    return trees


def binding_private_module_uses(
    path: Path, tokens: list[Token], private_modules: set[str]
) -> list[str]:
    """Find private core module paths and wildcard imports in a binding crate."""
    violations: list[str] = []
    for index in range(len(tokens) - 2):
        if (
            tokens[index].value == "starlette_rs"
            and tokens[index + 1].value == "::"
            and tokens[index + 2].kind == "ident"
            and identifier(tokens[index + 2]) in private_modules
        ):
            module = identifier(tokens[index + 2])
            violations.append(
                f"{path.relative_to(ROOT)}:{tokens[index + 2].line}: binding reaches "
                f"private Starlette module `{module}`; import a named crate-root export"
            )

    index = 0
    while index < len(tokens):
        if tokens[index].value != "use":
            index += 1
            continue
        end = statement_end(tokens, index + 1)
        if end is None:
            index += 1
            continue
        statement = tokens[index + 1 : end]
        root_positions = [
            position for position, token in enumerate(statement) if token.value == "starlette_rs"
        ]
        if root_positions and any(token.value == "*" for token in statement):
            violations.append(
                f"{path.relative_to(ROOT)}:{tokens[index].line}: binding wildcard-imports "
                "the Starlette crate; import named crate-root exports"
            )
        for root_position in root_positions:
            if root_position + 1 < len(statement) and statement[root_position + 1].value == "as":
                violations.append(
                    f"{path.relative_to(ROOT)}:{statement[root_position].line}: binding aliases "
                    "the Starlette crate root; use explicit `starlette_rs::Name` imports"
                )
            if (
                root_position + 2 < len(statement)
                and statement[root_position + 1].value == "::"
                and statement[root_position + 2].value == "{"
            ):
                group_end = matching_delimiter(statement, root_position + 2)
                if group_end is None:
                    continue
                for tree in comma_separated_trees(statement, root_position + 3, group_end):
                    first = tree[0] if tree else None
                    if first is None:
                        continue
                    candidate = first
                    if candidate.value == "self" and len(tree) > 2 and tree[1].value == "::":
                        candidate = tree[2]
                    if first.value == "self" and len(tree) > 1 and tree[1].value == "as":
                        violations.append(
                            f"{path.relative_to(ROOT)}:{first.line}: binding aliases "
                            "the Starlette crate root; use explicit `starlette_rs::Name` imports"
                        )
                    if candidate.kind == "ident" and identifier(candidate) in private_modules:
                        module = identifier(candidate)
                        violations.append(
                            f"{path.relative_to(ROOT)}:{candidate.line}: binding imports "
                            f"private Starlette module `{module}`; import a named crate-root export"
                        )
        index = end + 1
    return violations


def check() -> list[str]:
    """Check core declarations, public exports, and binding import paths."""
    violations: list[str] = []
    if not CORE_ROOT.is_file():
        return ["starlette-rs/src/lib.rs: crate root is missing"]
    if not BINDING_SOURCE.is_dir():
        return ["starlette-rs-py/src: Python binding source directory is missing"]

    core_files = sorted(CORE_SOURCE.rglob("*.rs"))
    binding_files = sorted(BINDING_SOURCE.rglob("*.rs"))
    root_tokens = tokenize(CORE_ROOT.read_text(encoding="utf-8"))
    private_modules = root_module_names(root_tokens)

    for path in core_files:
        tokens = tokenize(path.read_text(encoding="utf-8"))
        for module_index, module_token in module_declarations(tokens):
            if public_visibility_start(tokens, module_index) is not None:
                violations.append(
                    f"{path.relative_to(ROOT)}:{module_token.line}: implementation module "
                    f"`{identifier(module_token)}` is public; keep modules private and re-export "
                    "selected names from starlette-rs/src/lib.rs"
                )

    for pub_index, end in top_level_public_use_statements(root_tokens):
        if any(token.value == "*" for token in root_tokens[pub_index + 2 : end]):
            violations.append(
                f"starlette-rs/src/lib.rs:{root_tokens[pub_index].line}: public crate-root "
                "re-export uses a wildcard; enumerate exported names explicitly"
            )

    for path in binding_files:
        tokens = tokenize(path.read_text(encoding="utf-8"))
        violations.extend(binding_private_module_uses(path, tokens, private_modules))

    return sorted(set(violations))


def main() -> int:
    violations = check()
    if violations:
        print("Rust public API boundary violations:")
        for violation in violations:
            print(f"  {violation}")
        return 1

    print(
        "Rust public API boundary check passed: implementation modules stay private, "
        "crate-root exports are named, and Python bindings use crate-root exports"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
