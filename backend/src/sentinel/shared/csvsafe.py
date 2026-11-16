"""Spreadsheet-safe CSV cells for exports that people open (NFR-004).

A cell that a spreadsheet would treat as a formula is prefixed with an apostrophe. The
verification ZIP does not use this: it is byte-exact by design.
"""

from __future__ import annotations

FORMULA_LEADERS = ("=", "+", "-", "@", "\t", "\r")


def neutralise(value: str) -> str:
    return "'" + value if value.startswith(FORMULA_LEADERS) else value
