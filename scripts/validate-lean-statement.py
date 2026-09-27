#!/usr/bin/env python3
"""Validate one generated child theorem type without importing Pydantic."""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _recursive_lean.lean_contract import validate_lean_statement  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {Path(sys.argv[0]).name} LEAN_STATEMENT", file=sys.stderr)
        return 2
    try:
        validate_lean_statement(sys.argv[1])
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
