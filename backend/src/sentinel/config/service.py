"""Configuration loading, versioning and activation (FR-002).

Files are validated as a whole before anything is stored. A new immutable version is created
only when the canonical content differs from the active version, so reloading unchanged files
is a no-op (FR-002.2) and an invalid file leaves the active version in place (FR-002.1).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from pydantic import BaseModel, ValidationError
from sqlalchemy import Connection, Engine, func, insert, select, update

from sentinel import audit
from sentinel.config.models import Contract, RuleSet, validate_contract, validate_rule_set
from sentinel.config.tables import active_config, config_versions
from sentinel.shared import hooks
from sentinel.shared.authz import Permission, Principal, require
from sentinel.shared.db import unit_of_work
from sentinel.shared.errors import SentinelError, not_found

log = logging.getLogger("sentinel.config")
CONTRACT_FILE, RULES_FILE = "contract.yaml", "rules.yaml"


def config_invalid(errors: list[str]) -> SentinelError:
    return SentinelError(
        422,
        "CONFIG_INVALID",
        f"Configuration rejected: {len(errors)} error(s).",
        {"errors": errors},
    )


@dataclass(frozen=True)
class LoadedConfig:
    contract: Contract
    rules: RuleSet
    sources: dict[str, str]  # kind -> file text
    canonical: dict[str, str]  # kind -> canonical JSON
    hashes: dict[str, str]  # kind -> sha256 of the canonical JSON


@dataclass(frozen=True)
class ActiveConfig:
    dataset_key: str
    contract_version_id: UUID
    rule_set_version_id: UUID
    contract: Contract
    rules: RuleSet


@dataclass(frozen=True)
class ReloadResult:
    changed: bool
    contract_version_id: UUID
    rule_set_version_id: UUID

    def as_dict(self) -> dict[str, Any]:
        return {
            "changed": self.changed,
            "contract_version_id": str(self.contract_version_id),
            "rule_set_version_id": str(self.rule_set_version_id),
            # Staleness propagation arrives with the review tables (M1 step 4, FS §2.6).
            "stale_counts": {"issues": 0, "waivers": 0, "review_requests": 0},
        }


def canonical_json(model: BaseModel) -> str:
    return json.dumps(
        model.model_dump(mode="json", by_alias=True),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _parse[T: BaseModel](path: Path, model: type[T], errors: list[str]) -> tuple[T | None, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        errors.append(f"{path.name}: file cannot be read")
        return None, ""
    try:
        return model.model_validate(yaml.safe_load(text)), text
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = f" at line {mark.line + 1}" if mark is not None else ""
        errors.append(f"{path.name}: invalid YAML{line}")
    except ValidationError as exc:
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"])
            errors.append(f"{path.name}: {loc}: {err['msg']}")
    return None, text


def load_files(dataset_dir: Path) -> LoadedConfig:
    """Parse and validate both files. Raises CONFIG_INVALID naming every offending item."""
    errors: list[str] = []
    contract, contract_text = _parse(dataset_dir / CONTRACT_FILE, Contract, errors)
    rules, rules_text = _parse(dataset_dir / RULES_FILE, RuleSet, errors)
    if contract is not None:
        errors.extend(f"{CONTRACT_FILE}: {m}" for m in validate_contract(contract))
    if contract is not None and rules is not None and not errors:
        errors.extend(f"{RULES_FILE}: {m}" for m in validate_rule_set(rules, contract))
    if errors or contract is None or rules is None:
        raise config_invalid(errors)
    canonical = {"CONTRACT": canonical_json(contract), "RULE_SET": canonical_json(rules)}
    return LoadedConfig(
        contract=contract,
        rules=rules,
        sources={"CONTRACT": contract_text, "RULE_SET": rules_text},
        canonical=canonical,
        hashes={k: hashlib.sha256(v.encode("utf-8")).hexdigest() for k, v in canonical.items()},
    )


def dataset_dirs(config_dir: Path) -> list[Path]:
    root = config_dir / "datasets"
    return sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []


def activate(conn: Connection, actor: Principal | None, loaded: LoadedConfig) -> ReloadResult:
    """Store and activate whichever of the two files changed. One audit event when changed."""
    key = loaded.contract.dataset_key
    current = (
        conn.execute(
            select(active_config).where(active_config.c.dataset_key == key).with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    column = {"CONTRACT": "contract_version_id", "RULE_SET": "rule_set_version_id"}
    ids: dict[str, UUID] = {}
    changed: list[str] = []
    for kind in ("CONTRACT", "RULE_SET"):
        active_hash = None
        if current is not None:
            ids[kind] = current[column[kind]]
            active_hash = conn.execute(
                select(config_versions.c.content_sha256).where(config_versions.c.id == ids[kind])
            ).scalar_one()
        if active_hash != loaded.hashes[kind]:
            ids[kind] = conn.execute(
                insert(config_versions)
                .values(
                    kind=kind,
                    dataset_key=key,
                    content_sha256=loaded.hashes[kind],
                    source_text=loaded.sources[kind],
                    canonical_json=loaded.canonical[kind],
                    loaded_by=actor.user_id if actor is not None else None,
                )
                .returning(config_versions.c.id)
            ).scalar_one()
            changed.append(kind)
    values = {"contract_version_id": ids["CONTRACT"], "rule_set_version_id": ids["RULE_SET"]}
    if current is None:
        conn.execute(insert(active_config).values(dataset_key=key, **values))
    elif changed:
        conn.execute(
            update(active_config)
            .where(active_config.c.dataset_key == key)
            .values(activated_at=func.now(), **values)
        )
    if "RULE_SET" in changed and current is not None:
        hooks.emit(
            hooks.RULE_SET_ACTIVATED, conn, dataset_key=key, rule_set_version_id=ids["RULE_SET"]
        )
    if changed:
        audit.record(
            conn,
            actor=actor,
            event_type="CONFIG_ACTIVATED",
            entity_type="config",
            entity_id=key,
            payload={
                "changed": changed,
                "contract_version_id": str(ids["CONTRACT"]),
                "rule_set_version_id": str(ids["RULE_SET"]),
                "content_sha256": {k: loaded.hashes[k] for k in changed},
            },
        )
    return ReloadResult(bool(changed), ids["CONTRACT"], ids["RULE_SET"])


def reload(principal: Principal, conn: Connection, config_dir: Path) -> list[ReloadResult]:
    """ADMIN-triggered reload (FR-002). Validates every dataset before activating any."""
    require(principal, Permission.RELOAD_CONFIG)
    loaded = [load_files(d) for d in dataset_dirs(config_dir)]
    if not loaded:
        raise config_invalid([f"no dataset configuration found under {config_dir.name}/datasets"])
    results = [activate(conn, principal, item) for item in loaded]
    if not any(r.changed for r in results):
        audit.record(
            conn,
            actor=principal,
            event_type="CONFIG_RELOAD_UNCHANGED",
            entity_type="config",
            entity_id=",".join(item.contract.dataset_key for item in loaded),
        )
    return results


def record_rejection(conn: Connection, principal: Principal, error_count: int) -> None:
    audit.record(
        conn,
        actor=principal,
        event_type="CONFIG_REJECTED",
        entity_type="config",
        entity_id="reload",
        payload={"error_count": error_count},
    )


def load_at_startup(engine: Engine, config_dir: Path) -> None:
    """Activate the files on disk. Invalid files keep the stored version, or stop a first start."""
    try:
        loaded = [load_files(d) for d in dataset_dirs(config_dir)]
    except SentinelError as exc:
        with unit_of_work(engine) as conn:
            has_active = conn.execute(select(func.count()).select_from(active_config)).scalar_one()
        if not has_active:
            raise RuntimeError(
                f"Invalid configuration and no active version: {exc.details}"
            ) from exc
        log.error("config_invalid_at_startup", extra={"error_count": len(exc.details["errors"])})
        return
    with unit_of_work(engine) as conn:
        for item in loaded:
            activate(conn, None, item)


@lru_cache(maxsize=64)
def _parsed(version_id: UUID, kind: str, canonical: str) -> Contract | RuleSet:
    model: type[Contract] | type[RuleSet] = Contract if kind == "CONTRACT" else RuleSet
    return model.model_validate_json(canonical)


def _load_version(conn: Connection, version_id: UUID, kind: str) -> Contract | RuleSet:
    row = conn.execute(
        select(config_versions.c.canonical_json).where(
            config_versions.c.id == version_id, config_versions.c.kind == kind
        )
    ).one_or_none()
    if row is None:
        raise not_found("Configuration version")
    return _parsed(version_id, kind, row.canonical_json)


def get_contract(conn: Connection, version_id: UUID) -> Contract:
    contract = _load_version(conn, version_id, "CONTRACT")
    assert isinstance(contract, Contract)
    return contract


def get_rule_set(conn: Connection, version_id: UUID) -> RuleSet:
    rules = _load_version(conn, version_id, "RULE_SET")
    assert isinstance(rules, RuleSet)
    return rules


def get_active(conn: Connection, dataset_key: str) -> ActiveConfig:
    row = (
        conn.execute(select(active_config).where(active_config.c.dataset_key == dataset_key))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise not_found("Dataset")
    return ActiveConfig(
        dataset_key=dataset_key,
        contract_version_id=row["contract_version_id"],
        rule_set_version_id=row["rule_set_version_id"],
        contract=get_contract(conn, row["contract_version_id"]),
        rules=get_rule_set(conn, row["rule_set_version_id"]),
    )


def describe(principal: Principal, conn: Connection, dataset_key: str) -> dict[str, Any]:
    """The active contract and rule set for display (Doc 4 §3.2)."""
    require(principal, Permission.READ)
    active = get_active(conn, dataset_key)
    hashes = dict(
        conn.execute(
            select(config_versions.c.id, config_versions.c.content_sha256).where(
                config_versions.c.id.in_([active.contract_version_id, active.rule_set_version_id])
            )
        ).all()
    )
    return {
        "dataset_key": dataset_key,
        "contract_version": {
            "id": str(active.contract_version_id),
            "content_sha256": hashes[active.contract_version_id],
            "contract": active.contract.model_dump(mode="json", by_alias=True),
        },
        "rule_set_version": {
            "id": str(active.rule_set_version_id),
            "content_sha256": hashes[active.rule_set_version_id],
        },
        "rules": [
            {**r.model_dump(mode="json"), "waivable": r.is_waivable}
            for r in sorted(active.rules.rules, key=lambda r: r.id)
        ],
    }
