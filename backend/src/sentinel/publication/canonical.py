"""Canonical snapshot and manifest formats (ARD §8.3.2, §8.3.3). Versioned; never change
them silently. Golden-file tests freeze them."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from collections.abc import Iterable, Sequence
from datetime import date
from decimal import Decimal
from typing import Any

SNAPSHOT_FORMAT = "SENTINEL-SNAPSHOT-V1"
MANIFEST_FORMAT = "SENTINEL-MANIFEST-V1"
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
EXPORT_ORDER = ("invoices", "suppliers")
README = """Sentinel publication export
===========================

Contents: manifest.json, invoices.csv, suppliers.csv, README.txt.

To verify this package:

    python scripts/verify_publication.py <this file>.zip [--expected-manifest-sha256 <hex>]

The check recomputes the SHA-256 of each CSV and the snapshot hash and compares them with
manifest.json. Compare the manifest's own SHA-256 with the value shown in Sentinel.

Warning: these CSV files are byte-exact copies of the published data. A cell that begins
with =, +, - or @ may be treated as a formula by a spreadsheet. Do not open them in a
spreadsheet with automatic formula evaluation if you do not trust the source data.
"""


def _field(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def canonical_csv(columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> tuple[bytes, int]:
    """SENTINEL-SNAPSHOT-V1 CSV. `rows` must already be ordered by primary key, byte-wise."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(columns)
    count = 0
    for row in rows:
        writer.writerow([_field(v) for v in row])
        count += 1
    return buffer.getvalue().encode("utf-8"), count


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def snapshot_hash(table_hashes: dict[str, str]) -> str:
    lines = "".join(f"{name}:{table_hashes[name]}\n" for name in sorted(table_hashes))
    return sha256(lines.encode("utf-8"))


def manifest_bytes(manifest: dict[str, Any]) -> bytes:
    """Canonical JSON. Decimals are already strings, so number formatting cannot drift."""
    return json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def export_zip(manifest: bytes, tables: dict[str, bytes]) -> bytes:
    """Deterministic ZIP: fixed order, stored uncompressed, fixed timestamps (Doc 4 §7.3)."""
    buffer = io.BytesIO()
    entries = [("manifest.json", manifest)]
    entries += [(f"{name}.csv", tables[name]) for name in EXPORT_ORDER if name in tables]
    entries.append(("README.txt", README.encode("utf-8")))
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in entries:
            info = zipfile.ZipInfo(name, date_time=ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
    return buffer.getvalue()
