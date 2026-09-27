"""Lexical safety checks for generated one-line Lean theorem types."""

from __future__ import annotations

import re


_DECLARATION_PREFIX = re.compile(
    r"^(?:theorem|lemma|def|abbrev|opaque|axiom|example|instance|structure|class|"
    r"inductive|coinductive|namespace|section|end|import)\b"
)
_IDENTIFIER = re.compile(r"[A-Za-z0-9_']")


def validate_lean_statement(value: str) -> str:
    """Return a normalized type expression or reject command/proof injection syntax.

    A generated child contract is embedded inside parentheses by the comparator.  Named
    arguments may contain ``:=`` at positive delimiter depth, and an ordinary type expression
    may contain top-level ``let x := value; body`` binders.  A top-level assignment without a
    pending ``let`` is instead declaration/proof syntax and is rejected.
    """
    normalized = value.strip()
    if not normalized:
        raise ValueError("lean_statement must not be empty")
    if "\n" in normalized or "\r" in normalized:
        raise ValueError("lean_statement must be a single line")
    if _DECLARATION_PREFIX.match(normalized):
        raise ValueError("lean_statement must be a type expression, not a declaration")

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
            if normalized.startswith("let", index):
                before = normalized[index - 1] if index else ""
                after = normalized[index + 3] if index + 3 < len(normalized) else ""
                if (not before or not _IDENTIFIER.fullmatch(before)) and (
                    not after or not _IDENTIFIER.fullmatch(after)
                ):
                    top_level_let_pending = True
                    index += 3
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
