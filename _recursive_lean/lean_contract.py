"""Lexical safety checks for generated one-line Lean theorem types."""

from __future__ import annotations

import re


_DECLARATION_PREFIX = re.compile(
    r"^(?:theorem|lemma|def|abbrev|opaque|axiom|example|instance|structure|class|"
    r"inductive|coinductive|namespace|section|end|import)\b"
)
_IDENTIFIER = re.compile(r"[A-Za-z0-9_']")
_RAW_MATRIX_IS_UNIT = re.compile(r"\bIsUnit\s*\(\s*fun\b.*?:\s*Matrix\b")


def validate_lean_statement(value: str) -> str:
    """Return a normalized type expression or reject command/proof injection syntax.

    A generated child contract is embedded inside parentheses by the comparator.  Named
    arguments may contain ``:=`` at positive delimiter depth, and an ordinary type expression
    may contain top-level ``let x := value; body`` or ``letI : T := value; body`` binders.  A
    top-level assignment without a pending term-level binder is instead declaration/proof
    syntax and is rejected.
    """
    normalized = value.strip()
    if not normalized:
        raise ValueError("lean_statement must not be empty")
    if "\n" in normalized or "\r" in normalized:
        raise ValueError("lean_statement must be a single line")
    if _DECLARATION_PREFIX.match(normalized):
        raise ValueError("lean_statement must be a type expression, not a declaration")
    if _RAW_MATRIX_IS_UNIT.search(normalized):
        raise ValueError(
            "lean_statement must wrap a constructed matrix in Matrix.of before IsUnit "
            "to select matrix multiplication instead of pointwise function multiplication"
        )

    stack: list[str] = []
    pairs = {")": "(", "]": "[", "}": "{"}
    quoted = False
    escaped = False
    top_level_let_pending = False
    index = 0
    while index < len(normalized):
        character = normalized[index]
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
            index += 1
            continue
        if character == '"':
            quoted = True
            index += 1
            continue
        if normalized.startswith("--", index) or normalized.startswith("/-", index):
            raise ValueError("lean_statement must not contain comments")
        if normalized.startswith("-/", index):
            raise ValueError("lean_statement has an unmatched comment terminator")
        if character in "([{":
            stack.append(character)
            index += 1
            continue
        if character in pairs:
            if not stack or stack.pop() != pairs[character]:
                raise ValueError("lean_statement has unbalanced delimiters")
            index += 1
            continue
        if not stack:
            keyword = next(
                (
                    candidate
                    for candidate in ("letI", "let")
                    if normalized.startswith(candidate, index)
                ),
                "",
            )
            if keyword:
                before = normalized[index - 1] if index else ""
                end = index + len(keyword)
                after = normalized[end] if end < len(normalized) else ""
                if (not before or not _IDENTIFIER.fullmatch(before)) and (
                    not after or not _IDENTIFIER.fullmatch(after)
                ):
                    top_level_let_pending = True
                    index = end
                    continue
            if normalized.startswith(":=", index):
                if not top_level_let_pending:
                    raise ValueError(
                        "lean_statement must be a type expression, not a declaration"
                    )
                top_level_let_pending = False
                index += 2
                continue
        index += 1

    if quoted or stack:
        raise ValueError("lean_statement has an unterminated string or delimiter")
    return normalized
