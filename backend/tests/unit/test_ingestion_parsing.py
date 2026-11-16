"""Structural CSV parsing (FR-003) and the content hash (FR-004.2, ARD §8.3.1)."""

from __future__ import annotations

import hashlib
from uuid import UUID

from hypothesis import given
from hypothesis import strategies as st

from sentinel.config.models import ColumnDef, TableDef
from sentinel.ingestion.parsing import content_hash, parse_table

TABLE = TableDef(
    primary_key=["id"],
    columns=[
        ColumnDef(name="id", type="string", required=True),
        ColumnDef(name="amount", type="decimal(18,2)", required=True),
        ColumnDef(name="note", type="string", required=False),
    ],
)
CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000001")


def _codes(data: bytes, max_rows: int = 100) -> list[tuple[int, str]]:
    return [(e.line, e.code) for e in parse_table("t", TABLE, data, max_rows).errors]


def test_fr_003_header_matching_is_case_insensitive_and_keeps_extra_columns() -> None:
    parsed = parse_table("t", TABLE, b"\xef\xbb\xbf Note ,Extra Col,ID,AMOUNT\nn,x,1, 12.5 \n", 10)
    assert parsed.errors == []
    # Contract columns in contract order, then unexpected columns under their trimmed name.
    assert parsed.columns == ["id", "amount", "note", "Extra Col"]
    assert parsed.rows == [["1", " 12.5 ", "n", "x"]]  # values are never trimmed


def test_fr_003_4_content_defects_are_kept_as_raw_text() -> None:
    parsed = parse_table("t", TABLE, b'id,amount\n1,"12,50O.00"\n2,\n3,"multi\nline"\n', 10)
    assert parsed.errors == []
    assert parsed.rows == [["1", "12,50O.00"], ["2", ""], ["3", "multi\nline"]]


def test_fr_003_3_structural_failures_report_line_numbers() -> None:
    assert _codes(b"id,amount\n1,2\n3\n4,5,6\n7,8\n") == [(3, "RAGGED_ROW"), (4, "RAGGED_ROW")]
    assert _codes(b"") == [(1, "MISSING_HEADER")]
    assert _codes(b"id,,amount\n") == [(1, "MISSING_HEADER")]
    assert _codes(b"id, ID ,amount\n1,2,3\n") == [(1, "DUPLICATE_HEADER")]
    assert _codes(b'id,amount\n1,"open\n2,3\n') == [(3, "UNTERMINATED_QUOTE")]
    assert _codes(b"id,amount\n1,2\n\xff,3\n") == [(3, "ENCODING_ERROR")]
    assert _codes(b"id,amount\n1,2\n3,4\n5,6\n", max_rows=2) == [(4, "ROW_LIMIT_EXCEEDED")]


def test_fr_003_only_the_first_100_errors_are_listed_but_all_are_counted() -> None:
    parsed = parse_table("t", TABLE, b"id,amount\n" + b"x\n" * 250, 1000)
    assert len(parsed.errors) == 100 and parsed.error_total == 250


def test_content_hash_golden_value() -> None:
    """Freezes SENTINEL-CONTENT-V1. Changing this value is a format change (CLAUDE.md §6)."""
    tables = {
        "suppliers": (["supplier_id"], [["S1"]]),
        "invoices": (["invoice_id", "note"], [["I1", 'a,"b"\n'], ["I2", "é"]]),
    }
    expected = hashlib.sha256(
        b"SENTINEL-CONTENT-V1\n"
        b"contract:00000000-0000-4000-8000-000000000001\n"
        b"table:invoices\n"
        b'columns:["invoice_id","note"]\n'
        b'["I1","a,\\"b\\"\\n"]\n'
        b'["I2","\xc3\xa9"]\n'
        b"table:suppliers\n"
        b'columns:["supplier_id"]\n'
        b'["S1"]\n'
    ).hexdigest()
    assert content_hash(CONTRACT_ID, tables) == expected


cells = st.text(max_size=8)
rows = st.lists(st.lists(cells, min_size=2, max_size=2), min_size=1, max_size=6)


@given(rows=rows, data=st.data())
def test_fr_004_2_any_content_change_changes_the_hash(
    rows: list[list[str]], data: st.DataObject
) -> None:
    def digest(content: list[list[str]], contract: UUID = CONTRACT_ID) -> str:
        return content_hash(contract, {"t": (["a", "b"], content)})

    base = digest(rows)
    i = data.draw(st.integers(0, len(rows) - 1))
    j = data.draw(st.integers(0, 1))
    changed = [list(r) for r in rows]
    changed[i][j] += "x"
    assert digest(changed) != base  # one cell
    assert digest([*rows, ["", ""]]) != base  # a row added
    assert digest(rows[:-1]) != base  # a row removed
    assert digest(rows, UUID("00000000-0000-4000-8000-000000000002")) != base  # contract
    if len(rows) > 1 and rows[0] != rows[-1]:
        assert digest(rows[::-1]) != base  # row order
