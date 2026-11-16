"""Structural CSV parsing and the version content hash (FR-003, FR-004; FS §3, ARD §8.3.1).

Structural problems reject the upload. Content problems (wrong types, empty values, invalid
codes) are kept as raw text for validation to report.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from uuid import UUID

from sentinel.config.models import TableDef

HASH_ALGORITHM = "SENTINEL-CONTENT-V1"
MAX_REPORTED_ERRORS = 100


@dataclass(frozen=True)
class StructuralError:
    table: str
    line: int
    code: str

    def as_dict(self) -> dict[str, str | int]:
        return {"table": self.table, "line": self.line, "code": self.code}


@dataclass
class ParsedTable:
    name: str
    # Observed contract columns in contract order, then unexpected columns in header order.
    columns: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    errors: list[StructuralError] = field(default_factory=list)
    error_total: int = 0

    def _error(self, line: int, code: str) -> None:
        self.error_total += 1
        if len(self.errors) < MAX_REPORTED_ERRORS:
            self.errors.append(StructuralError(self.name, line, code))


def parse_table(name: str, table: TableDef, data: bytes, max_rows: int) -> ParsedTable:
    parsed = ParsedTable(name)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        parsed._error(data.count(b"\n", 0, exc.start) + 1, "ENCODING_ERROR")
        return parsed

    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        header = next(reader, None)
        if header is None or not any(h.strip() for h in header):
            parsed._error(1, "MISSING_HEADER")
            return parsed
        names = [h.strip() for h in header]
        folded = [n.casefold() for n in names]
        if "" in folded:
            parsed._error(1, "MISSING_HEADER")
        if len(set(folded)) != len(folded):
            parsed._error(1, "DUPLICATE_HEADER")
        if parsed.errors:
            return parsed

        contract = {c.casefold(): c for c in table.column_names}
        stored = [contract.get(f, n) for f, n in zip(folded, names, strict=True)]
        observed = [c for c in table.column_names if c in stored]
        parsed.columns = observed + [c for c in stored if c not in observed]
        order = [stored.index(c) for c in parsed.columns]

        width = len(header)
        for row in reader:
            if len(row) != width:
                parsed._error(reader.line_num, "RAGGED_ROW")
                continue
            if len(parsed.rows) >= max_rows:
                parsed._error(reader.line_num, "ROW_LIMIT_EXCEEDED")
                break
            parsed.rows.append([row[i] for i in order])
    except csv.Error:
        parsed._error(reader.line_num or 1, "UNTERMINATED_QUOTE")
    return parsed


def _line(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"


def content_hash(
    contract_version_id: UUID,
    tables: Mapping[str, tuple[Sequence[str], Iterable[Sequence[str | None]]]],
) -> str:
    """SENTINEL-CONTENT-V1. `tables` maps a table name to (columns, rows in file order)."""
    digest = hashlib.sha256()
    digest.update(f"{HASH_ALGORITHM}\n".encode())
    digest.update(f"contract:{contract_version_id}\n".encode())
    for name in sorted(tables):
        columns, rows = tables[name]
        digest.update(f"table:{name}\n".encode())
        digest.update(b"columns:" + _line(list(columns)))
        for row in rows:
            digest.update(_line(list(row)))
    return digest.hexdigest()
