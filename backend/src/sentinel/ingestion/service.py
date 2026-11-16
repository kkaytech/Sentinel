"""Ingestion commands and version queries (FR-003, FR-004; FS §3).

An ingestion either creates one complete version or nothing but an attempt record. The
version, its rows and its raw files are written in one transaction, which is what lets the
seal-on-commit guard accept them and reject anything added later.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import PurePath
from typing import Any, cast
from uuid import UUID

from psycopg import Connection as PsycopgConnection
from sqlalchemy import Connection, Engine, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from sentinel import audit
from sentinel.config import service as config_service
from sentinel.config.service import ActiveConfig
from sentinel.identity.tables import users
from sentinel.ingestion.parsing import HASH_ALGORITHM, ParsedTable, content_hash, parse_table
from sentinel.ingestion.tables import (
    dataset_periods,
    dataset_versions,
    ingestion_attempts,
    raw_files,
    version_rows,
)
from sentinel.shared.authz import Permission, Principal, require
from sentinel.shared.db import unit_of_work
from sentinel.shared.errors import SentinelError, not_found
from sentinel.shared.settings import Settings

PERIOD_PATTERN = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")


@dataclass(frozen=True)
class Upload:
    filename: str
    data: bytes

    @property
    def safe_name(self) -> str:
        return PurePath(self.filename.replace("\\", "/")).name[:200] or "upload.csv"


@dataclass(frozen=True)
class IngestResult:
    created: bool  # False for DUPLICATE_CONTENT
    attempt: dict[str, Any]
    version: dict[str, Any]


def validate_period(period: str, today: date) -> None:
    """FR-003.7: a real YYYY-MM, at most one month after the current UTC month."""
    if not PERIOD_PATTERN.match(period):
        raise SentinelError(422, "INVALID_PERIOD", "The period must be a valid YYYY-MM.")
    year, month = int(period[:4]), int(period[5:])
    if year * 12 + month > today.year * 12 + today.month + 1:
        raise SentinelError(
            422, "INVALID_PERIOD", "The period is more than one month after the current date."
        )


def _file_facts(
    uploads: dict[str, Upload], rows: dict[str, int] | None = None
) -> list[dict[str, Any]]:
    return [
        {
            "table": table,
            "filename": upload.safe_name,
            "sha256": hashlib.sha256(upload.data).hexdigest(),
            "size_bytes": len(upload.data),
            "rows": (rows or {}).get(table),
        }
        for table, upload in sorted(uploads.items())
    ]


def _lock_period(conn: Connection, dataset_key: str, period: str) -> UUID:
    """Create the period row if needed and lock it (the same lock publication takes)."""
    conn.execute(
        pg_insert(dataset_periods)
        .values(dataset_key=dataset_key, period=period)
        .on_conflict_do_nothing(index_elements=["dataset_key", "period"])
    )
    period_id: UUID = conn.execute(
        select(dataset_periods.c.id)
        .where(dataset_periods.c.dataset_key == dataset_key, dataset_periods.c.period == period)
        .with_for_update()
    ).scalar_one()
    return period_id


def _record_attempt(
    conn: Connection,
    principal: Principal,
    *,
    period_id: UUID,
    status: str,
    started_at: datetime,
    files: list[dict[str, Any]],
    errors: dict[str, Any] | None = None,
    version_id: UUID | None = None,
) -> dict[str, Any]:
    row = (
        conn.execute(
            insert(ingestion_attempts)
            .values(
                dataset_period_id=period_id,
                status=status,
                initiated_by=principal.user_id,
                started_at=started_at,
                files=files,
                errors=errors,
                dataset_version_id=version_id,
            )
            .returning(ingestion_attempts)
        )
        .mappings()
        .one()
    )
    return _attempt_view(dict(row))


def _attempt_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "status": row["status"],
        "initiated_by": str(row["initiated_by"]),
        "started_at": row["started_at"].isoformat(),
        "finished_at": row["finished_at"].isoformat(),
        "files": row["files"],
        "errors": row["errors"],
        "dataset_version_id": str(row["dataset_version_id"]) if row["dataset_version_id"] else None,
    }


def _copy_rows(conn: Connection, version_id: UUID, table: ParsedTable) -> None:
    """COPY one table's rows. Needs only INSERT; the seal guard checks every row."""
    raw = cast(PsycopgConnection[Any], conn.connection.driver_connection)
    with (
        raw.cursor() as cursor,
        cursor.copy(
            "COPY data.version_rows (dataset_version_id, table_name, row_num, cells) FROM STDIN"
        ) as copy,
    ):
        for row_num, row in enumerate(table.rows, start=1):
            cells = json.dumps(
                dict(zip(table.columns, row, strict=True)),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            copy.write_row((version_id, table.name, row_num, cells))


def _create_version(
    conn: Connection,
    principal: Principal,
    active: ActiveConfig,
    *,
    period_id: UUID,
    period: str,
    digest: str,
    parsed: dict[str, ParsedTable],
    uploads: dict[str, Upload],
) -> UUID:
    earlier = conn.execute(
        select(dataset_versions.c.id, dataset_versions.c.label).where(
            dataset_versions.c.dataset_period_id == period_id,
            dataset_versions.c.status == "ACTIVE",
        )
    ).all()
    # Supersede first: only one ACTIVE version per period is allowed at any moment.
    conn.execute(
        update(dataset_versions)
        .where(dataset_versions.c.id.in_([e.id for e in earlier]))
        .values(status="SUPERSEDED")
    )
    seq = (
        1
        + conn.execute(
            select(func.coalesce(func.max(dataset_versions.c.seq), 0)).where(
                dataset_versions.c.dataset_period_id == period_id
            )
        ).scalar_one()
    )
    label = f"{active.dataset_key}-{period}-v{seq}"
    version_id: UUID = conn.execute(
        insert(dataset_versions)
        .values(
            dataset_period_id=period_id,
            seq=seq,
            label=label,
            contract_version_id=active.contract_version_id,
            content_hash=digest,
            hash_algorithm=HASH_ALGORITHM,
            columns={name: table.columns for name, table in parsed.items()},
            row_counts={name: len(table.rows) for name, table in parsed.items()},
            created_by=principal.user_id,
        )
        .returning(dataset_versions.c.id)
    ).scalar_one()
    for name in sorted(parsed):
        _copy_rows(conn, version_id, parsed[name])
        upload = uploads[name]
        conn.execute(
            insert(raw_files).values(
                dataset_version_id=version_id,
                table_name=name,
                filename=upload.safe_name,
                sha256=hashlib.sha256(upload.data).hexdigest(),
                size_bytes=len(upload.data),
                bytes=upload.data,
            )
        )
    conn.execute(
        update(dataset_periods)
        .where(dataset_periods.c.id == period_id)
        .values(last_activity_at=func.now())
    )
    audit.record(
        conn,
        actor=principal,
        event_type="VERSION_CREATED",
        entity_type="dataset_version",
        entity_id=str(version_id),
        dataset_version_id=version_id,
        payload={
            "label": label,
            "period": period,
            "content_hash": digest,
            "row_counts": {name: len(table.rows) for name, table in parsed.items()},
        },
    )
    for old in earlier:
        audit.record(
            conn,
            actor=None,
            event_type="VERSION_SUPERSEDED",
            entity_type="dataset_version",
            entity_id=str(old.id),
            dataset_version_id=old.id,
            payload={"label": old.label, "superseded_by": label},
        )
    return version_id


def ingest(
    principal: Principal,
    engine: Engine,
    settings: Settings,
    dataset_key: str,
    period: str,
    files: dict[str, Upload | None],
) -> IngestResult:
    """Upload one period's files (FS §3). Returns the new version, or the existing one when
    the content is unchanged. Raises on pre-check and structural failures."""
    require(principal, Permission.INGEST)
    started_at = datetime.now(UTC)
    with unit_of_work(engine) as conn:
        active = config_service.get_active(conn, dataset_key)
    tables = active.contract.tables

    # 1. Pre-checks. No attempt record, but the rejection is audited.
    try:
        validate_period(period, started_at.date())
        for name in sorted(tables):
            if files.get(name) is None:
                raise SentinelError(
                    422, "MISSING_TABLE_FILE", f"The file for table '{name}' is missing.",
                    {"table": name},
                )  # fmt: skip
        uploads = {name: cast(Upload, files[name]) for name in tables}
        for name, upload in sorted(uploads.items()):
            if len(upload.data) > settings.max_file_bytes:
                limit_mb = settings.max_file_bytes // (1024 * 1024)
                raise SentinelError(
                    413, "FILE_TOO_LARGE",
                    f"The file for table '{name}' exceeds the {limit_mb} MB limit.",
                    {"table": name, "limit_bytes": settings.max_file_bytes},
                )  # fmt: skip
    except SentinelError as exc:
        with unit_of_work(engine) as conn:
            audit.record(
                conn,
                actor=principal,
                event_type="INGESTION_REJECTED",
                entity_type="dataset_period",
                entity_id=f"{dataset_key}/{period[:20]}",
                payload={"code": exc.code},
            )
        raise

    # 2. Structural parse. A failure is recorded as a FAILED attempt.
    parsed = {
        name: parse_table(name, tables[name], uploads[name].data, settings.max_rows)
        for name in sorted(tables)
    }
    total = sum(t.error_total for t in parsed.values())
    if total:
        reported = [e.as_dict() for t in parsed.values() for e in t.errors][:100]
        with unit_of_work(engine) as conn:
            period_id = _lock_period(conn, dataset_key, period)
            attempt = _record_attempt(
                conn, principal, period_id=period_id, status="FAILED", started_at=started_at,
                files=_file_facts(uploads), errors={"errors": reported, "total": total},
            )  # fmt: skip
            audit.record(
                conn,
                actor=principal,
                event_type="INGESTION_FAILED",
                entity_type="ingestion_attempt",
                entity_id=attempt["id"],
                payload={"period": period, "error_total": total,
                         "codes": sorted({str(e["code"]) for e in reported})},
            )  # fmt: skip
        limit_note = (
            f" The row limit is {settings.max_rows} rows per table."
            if any(e["code"] == "ROW_LIMIT_EXCEEDED" for e in reported)
            else ""
        )
        raise SentinelError(
            422, "INGESTION_STRUCTURAL_ERROR",
            f"The upload was rejected: {total} structural error(s).{limit_note}",
            {"errors": reported, "total": total, "attempt_id": attempt["id"]},
        )  # fmt: skip

    # 3. Hash, then create the version or report unchanged content.
    digest = content_hash(
        active.contract_version_id, {n: (t.columns, t.rows) for n, t in parsed.items()}
    )
    row_counts = {name: len(table.rows) for name, table in parsed.items()}
    facts = _file_facts(uploads, row_counts)
    try:
        with unit_of_work(engine) as conn:
            period_id = _lock_period(conn, dataset_key, period)
            current = conn.execute(
                select(dataset_versions.c.id, dataset_versions.c.content_hash).where(
                    dataset_versions.c.dataset_period_id == period_id,
                    dataset_versions.c.status == "ACTIVE",
                )
            ).one_or_none()
            if current is not None and current.content_hash == digest:
                attempt = _record_attempt(
                    conn, principal, period_id=period_id, status="DUPLICATE_CONTENT",
                    started_at=started_at, files=facts, version_id=current.id,
                )  # fmt: skip
                audit.record(
                    conn,
                    actor=principal,
                    event_type="INGESTION_DUPLICATE",
                    entity_type="ingestion_attempt",
                    entity_id=attempt["id"],
                    dataset_version_id=current.id,
                    payload={"period": period},
                )
                return IngestResult(False, attempt, _version_view(conn, current.id))
            version_id = _create_version(
                conn, principal, active, period_id=period_id, period=period, digest=digest,
                parsed=parsed, uploads=uploads,
            )  # fmt: skip
            attempt = _record_attempt(
                conn, principal, period_id=period_id, status="SUCCEEDED", started_at=started_at,
                files=facts, version_id=version_id,
            )  # fmt: skip
            return IngestResult(True, attempt, _version_view(conn, version_id))
    except SentinelError:
        raise
    except Exception as exc:
        # FR-003.6: the transaction rolled back, so no version data exists. Record the attempt.
        with unit_of_work(engine) as conn:
            period_id = _lock_period(conn, dataset_key, period)
            attempt = _record_attempt(
                conn, principal, period_id=period_id, status="FAILED", started_at=started_at,
                files=facts, errors={"code": "INTERNAL_ERROR", "type": type(exc).__name__},
            )  # fmt: skip
            audit.record(
                conn,
                actor=principal,
                event_type="INGESTION_FAILED",
                entity_type="ingestion_attempt",
                entity_id=attempt["id"],
                payload={"period": period, "codes": ["INTERNAL_ERROR"]},
            )
        raise


# ---- queries -----------------------------------------------------------------------------
def _version_rows_query() -> Any:
    return select(
        dataset_versions,
        dataset_periods.c.dataset_key,
        dataset_periods.c.period,
        users.c.display_name.label("created_by_name"),
    ).select_from(
        dataset_versions.join(
            dataset_periods, dataset_periods.c.id == dataset_versions.c.dataset_period_id
        ).join(users, users.c.id == dataset_versions.c.created_by)
    )


def _as_version(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "label": row["label"],
        "dataset_key": row["dataset_key"],
        "period": row["period"],
        "seq": row["seq"],
        "status": row["status"],
        "content_hash": row["content_hash"],
        "hash_algorithm": row["hash_algorithm"],
        "contract_version_id": str(row["contract_version_id"]),
        "columns": row["columns"],
        "row_counts": row["row_counts"],
        "created_by": {"id": str(row["created_by"]), "display_name": row["created_by_name"]},
        "created_at": row["created_at"].astimezone(UTC).isoformat().replace("+00:00", "Z"),
    }


def _version_view(conn: Connection, version_id: UUID) -> dict[str, Any]:
    row = (
        conn.execute(_version_rows_query().where(dataset_versions.c.id == version_id))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise SentinelError(404, "VERSION_NOT_FOUND", "Dataset version not found.")
    return _as_version(row)


def get_version(principal: Principal, conn: Connection, version_id: UUID) -> dict[str, Any]:
    require(principal, Permission.READ)
    return _version_view(conn, version_id)


def list_periods(principal: Principal, conn: Connection, dataset_key: str) -> list[dict[str, Any]]:
    """Every period of the dataset, newest first, with its current version if it has one."""
    require(principal, Permission.READ)
    config_service.get_active(conn, dataset_key)  # 404 for an unknown dataset
    periods = conn.execute(
        select(dataset_periods.c.id, dataset_periods.c.period)
        .where(dataset_periods.c.dataset_key == dataset_key)
        .order_by(dataset_periods.c.period.desc())
    ).all()
    current = {
        row["dataset_period_id"]: _as_version(row)
        for row in conn.execute(
            _version_rows_query().where(
                dataset_periods.c.dataset_key == dataset_key, dataset_versions.c.status == "ACTIVE"
            )
        ).mappings()
    }
    return [{"period": p.period, "current_version": current.get(p.id)} for p in periods]


def get_period(
    principal: Principal, conn: Connection, dataset_key: str, period: str
) -> dict[str, Any]:
    require(principal, Permission.READ)
    period_id = conn.execute(
        select(dataset_periods.c.id).where(
            dataset_periods.c.dataset_key == dataset_key, dataset_periods.c.period == period
        )
    ).scalar_one_or_none()
    if period_id is None:
        raise not_found("Period")
    versions = conn.execute(
        _version_rows_query()
        .where(dataset_versions.c.dataset_period_id == period_id)
        .order_by(dataset_versions.c.seq.desc())
    ).mappings()
    attempts = conn.execute(
        select(ingestion_attempts)
        .where(ingestion_attempts.c.dataset_period_id == period_id)
        .order_by(ingestion_attempts.c.started_at.desc(), ingestion_attempts.c.id)
    ).mappings()
    return {
        "period": period,
        "versions": [_as_version(v) for v in versions],
        "ingestion_attempts": [_attempt_view(dict(a)) for a in attempts],
    }


def get_raw_file(
    principal: Principal, conn: Connection, version_id: UUID, table: str
) -> dict[str, Any]:
    """The original upload, byte for byte (FR-004.4)."""
    require(principal, Permission.DOWNLOAD_RAW)
    row = (
        conn.execute(
            select(raw_files).where(
                raw_files.c.dataset_version_id == version_id, raw_files.c.table_name == table
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise not_found("Raw file")
    return {"filename": row["filename"], "sha256": row["sha256"], "bytes": bytes(row["bytes"])}


def recompute_content_hash(conn: Connection, version_id: UUID) -> str:
    """Rebuild the hash from stored rows (FR-004.1; publication check E3 uses this)."""
    version = conn.execute(
        select(dataset_versions.c.contract_version_id, dataset_versions.c.columns).where(
            dataset_versions.c.id == version_id
        )
    ).one()

    def rows(table: str, columns: list[str]) -> Any:
        result = conn.execute(
            select(version_rows.c.cells)
            .where(
                version_rows.c.dataset_version_id == version_id, version_rows.c.table_name == table
            )
            .order_by(version_rows.c.row_num)
        )
        return ([cells.get(c) for c in columns] for (cells,) in result)

    return content_hash(
        version.contract_version_id,
        {table: (columns, rows(table, columns)) for table, columns in version.columns.items()},
    )
