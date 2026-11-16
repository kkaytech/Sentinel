#!/usr/bin/env python3
"""PoC-1 harness: PostgreSQL validation performance at load scale (ARD §10.1).

    poc.py setup                    create the sentinel_poc database, migrate, add PoC tables
    poc.py load                     W10: measure ingestion, then load three versions
    poc.py validate --label A       W1-W9 (+P0, X1): timings, plans, catalogue check
    poc.py publish  --label A       W11: typed snapshot plus canonical CSV hashing

Runs as sentinel_app, like the application. sentinel_owner is used only by `setup`; the
superuser only creates the database and runs VACUUM between measurements.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import os
import platform
import statistics
import subprocess
import sys
import time
import uuid
from decimal import Decimal
from pathlib import Path

import psycopg

import workloads as wl

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = HERE / "out"
RESULTS = HERE / "results"
PLANS = HERE / "plans"
DATA = OUT / "load"
STATE = OUT / "state.json"
DB = "sentinel_poc"
CONTRACT_VERSION_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
PERIOD = "2026-10"
DATASETS = ["defective", "corrected", "clean"]


def dsn(user: str, dbname: str = DB) -> str:
    return psycopg.conninfo.make_conninfo(
        host=os.environ.get("POC_PGHOST", "localhost"),
        port=os.environ.get("POC_PGPORT", "55433"),
        user=user,
        password=os.environ.get(f"POC_{user.upper()}_PASSWORD", "poc"),
        dbname=dbname,
    )


def admin(sql: str, dbname: str = DB) -> None:
    with psycopg.connect(dsn(os.environ.get("POC_SUPERUSER", "sentinel_admin"), dbname),
                         autocommit=True) as conn:  # fmt: skip
        conn.execute(sql)


def app() -> psycopg.Connection:
    return psycopg.connect(dsn("sentinel_app"))


def state() -> dict:
    return json.loads(STATE.read_text())


def summary(samples: list[float]) -> dict:
    return {"median_s": round(statistics.median(samples), 4), "max_s": round(max(samples), 4),
            "runs_s": [round(s, 4) for s in samples]}  # fmt: skip


def environment(conn: psycopg.Connection) -> dict:
    rows = conn.execute(
        "SELECT name, setting, unit, source FROM pg_settings "
        "WHERE source NOT IN ('default', 'override') OR name IN "
        "('work_mem', 'shared_buffers', 'hash_mem_multiplier', 'max_parallel_workers_per_gather',"
        " 'jit', 'effective_cache_size', 'server_version', 'lc_collate') ORDER BY name"
    ).fetchall()
    locale = conn.execute(
        "SELECT datcollate, datctype FROM pg_database WHERE datname = current_database()"
    ).fetchone()
    return {
        "server_version": conn.execute("SHOW server_version").fetchone()[0],
        "database_locale": list(locale),
        "settings": {r[0]: f"{r[1]}{r[2] or ''} ({r[3]})" for r in rows},
        "host": {"machine": platform.machine(), "system": platform.platform(),
                 "cpus": os.cpu_count(), "python": platform.python_version()},
    }  # fmt: skip


# ---- setup -------------------------------------------------------------------------------
def cmd_setup(_: argparse.Namespace) -> None:
    admin(f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)", "postgres")
    admin(f"CREATE DATABASE {DB} OWNER sentinel_owner ENCODING 'UTF8' TEMPLATE template0", "postgres")
    owner = psycopg.conninfo.conninfo_to_dict(dsn("sentinel_owner"))
    url = "postgresql+psycopg://{user}:{password}@{host}:{port}/{dbname}".format(**owner)
    subprocess.run(
        [str(REPO / "backend/.venv/bin/alembic"), "upgrade", "head"],
        cwd=REPO / "backend", env={**os.environ, "SENTINEL_OWNER_DATABASE_URL": url}, check=True,
    )  # fmt: skip
    with psycopg.connect(dsn("sentinel_owner")) as conn:
        conn.execute((HERE / "schema.sql").read_text())
    OUT.mkdir(exist_ok=True)
    STATE.write_text(json.dumps({"versions": {}}))
    print("setup complete")


# ---- W10 ingestion -----------------------------------------------------------------------
def ingest(conn: psycopg.Connection, dataset: str, label: str) -> dict:
    """Parse, hash (SENTINEL-CONTENT-V1, ARD §8.3.1) and COPY one version. Caller commits."""
    t0 = time.perf_counter()
    directory = DATA / dataset
    digest = hashlib.sha256()

    def line(text: str) -> None:
        digest.update(text.encode("utf-8") + b"\n")

    line("SENTINEL-CONTENT-V1")
    line(f"contract:{CONTRACT_VERSION_ID}")
    compact = {"ensure_ascii": False, "separators": (",", ":")}
    raw: dict[str, bytes] = {}
    staged: list[tuple[str, int, str]] = []
    columns: dict[str, list[str]] = {}
    counts: dict[str, int] = {}
    for table in sorted(wl.CONTRACT):
        raw[table] = (directory / f"{table}.csv").read_bytes()
        reader = csv.reader(io.StringIO(raw[table].decode("utf-8-sig"), newline=""))
        header = [h.strip() for h in next(reader)]
        if header != wl.CONTRACT[table]:
            raise ValueError(f"{table}: header does not match the contract")
        columns[table] = header
        line(f"table:{table}")
        line("columns:" + json.dumps(header, **compact))
        n = 0
        for n, row in enumerate(reader, start=1):  # noqa: B007
            if len(row) != len(header):
                raise ValueError(f"{table} line {n + 1}: RAGGED_ROW")
            line(json.dumps(row, **compact))
            staged.append((table, n, json.dumps(dict(zip(header, row, strict=True)), **compact)))
        counts[table] = n
    t_parsed = time.perf_counter()

    version_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO app.dataset_versions (id, label, contract_version_id, content_hash,"
            " hash_algorithm, columns, row_counts) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (version_id, label, CONTRACT_VERSION_ID, digest.hexdigest(), "SENTINEL-CONTENT-V1",
             json.dumps(columns), json.dumps(counts)),
        )  # fmt: skip
        for table, data in raw.items():
            cur.execute(
                "INSERT INTO data.raw_files VALUES (%s, %s, %s, %s, %s, %s)",
                (version_id, table, f"{table}.csv", hashlib.sha256(data).hexdigest(), len(data), data),
            )
        with cur.copy(
            "COPY data.version_rows (dataset_version_id, table_name, row_num, cells) FROM STDIN"
        ) as copy:
            for table, n, cells in staged:
                copy.write_row((version_id, table, n, cells))
    t_copied = time.perf_counter()
    return {"version_id": str(version_id), "content_hash": digest.hexdigest(), "row_counts": counts,
            "parse_hash_s": t_parsed - t0, "insert_copy_s": t_copied - t_parsed,
            "total_s": t_copied - t0}  # fmt: skip


def sizes(conn: psycopg.Connection) -> dict:
    row = conn.execute(
        "SELECT pg_table_size('data.version_rows'), pg_indexes_size('data.version_rows'),"
        " (SELECT count(*) FROM data.version_rows)"
    ).fetchone()
    return {"table_bytes": row[0], "index_bytes": row[1], "rows": row[2]}


def cmd_load(args: argparse.Namespace) -> None:
    result: dict = {"workload": "W10", "measured": [], "committed": {}}
    with app() as conn:
        result["environment"] = environment(conn)
        conn.rollback()
        for i in range(args.warmup + args.runs):
            timing = ingest(conn, "defective", f"measure-{i}")
            conn.rollback()  # measured loads leave no version behind
            admin("VACUUM data.version_rows")
            if i >= args.warmup:
                result["measured"].append(timing)
            print(f"W10 run {i}: {timing['total_s']:.2f}s "
                  f"(parse+hash {timing['parse_hash_s']:.2f}s, copy {timing['insert_copy_s']:.2f}s)")  # fmt: skip
        versions = {}
        for dataset in DATASETS:
            timing = ingest(conn, dataset, f"SUPINV-{PERIOD}-{dataset}")
            t0 = time.perf_counter()
            conn.commit()
            timing["commit_s"] = time.perf_counter() - t0
            versions[dataset] = timing["version_id"]
            result["committed"][dataset] = timing
            if dataset == DATASETS[0]:
                result["storage_one_version"] = sizes(conn)
                conn.rollback()
            print(f"loaded {dataset}: {timing['total_s'] + timing['commit_s']:.2f}s")
        result["storage_three_versions"] = sizes(conn)
    if not args.skip_analyze:
        admin("VACUUM ANALYZE data.version_rows")
    result["analyzed_after_load"] = not args.skip_analyze
    for key in ("total_s", "parse_hash_s", "insert_copy_s"):
        result[key] = summary([m[key] for m in result["measured"]])
    STATE.write_text(json.dumps({"versions": versions}))
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "W10-load.json").write_text(json.dumps(result, indent=1))
    print(f"W10 median {result['total_s']['median_s']}s max {result['total_s']['max_s']}s; "
          f"storage per version {result['storage_one_version']}")  # fmt: skip


# ---- plan reading ------------------------------------------------------------------------
def read_plan(plan: dict) -> dict:
    """Pull out what ARD §10.1 says to look for in each plan."""
    scans, spills, worst = [], [], {"ratio": 1.0}

    def walk(node: dict) -> None:
        kind = node["Node Type"]
        if node.get("Relation Name") == "version_rows":
            scans.append(kind + (f" ({node['Index Name']})" if "Index Name" in node else ""))
        if node.get("Sort Space Type") == "Disk":
            spills.append(f"{kind}: {node.get('Sort Method')} {node.get('Sort Space Used')}kB on disk")
        if node.get("Hash Batches", 1) > 1:
            spills.append(f"{kind}: {node['Hash Batches']} batches")
        if node.get("Disk Usage", 0) > 0:
            spills.append(f"{kind}: {node.get('Disk Usage', 0)}kB on disk")
        if node.get("Storage") == "Disk":
            spills.append(f"{kind}: storage on disk")
        est, actual = node.get("Plan Rows", 0), node.get("Actual Rows", 0) * node.get("Actual Loops", 1)
        if est and actual:
            ratio = max(est / actual, actual / est)
            if ratio > worst["ratio"]:
                worst.update(ratio=round(ratio, 1), node=kind, estimated=est, actual=round(actual))
        for child in node.get("Plans", []):
            walk(child)

    root = plan["Plan"]
    walk(root)
    return {
        "execution_ms": plan["Execution Time"],
        "planning_ms": plan["Planning Time"],
        "version_rows_access": sorted(set(scans)),
        "spills": spills,
        "temp_blocks_written": root.get("Temp Written Blocks", 0),
        "shared_hit_blocks": root.get("Shared Hit Blocks", 0),
        "shared_read_blocks": root.get("Shared Read Blocks", 0),
        "worst_row_estimate": worst,
    }


# ---- W1-W9 validation --------------------------------------------------------------------
def start_run(cur: psycopg.Cursor, version_id: str) -> tuple[uuid.UUID, dict[str, uuid.UUID]]:
    run_id = uuid.uuid4()
    start, end = period_bounds()
    cur.execute(
        "INSERT INTO app.validation_runs VALUES (%s, %s, %s, %s, 'RUNNING')",
        (run_id, version_id, PERIOD, end + dt.timedelta(days=15)),
    )
    findings = {r: uuid.uuid4() for r in wl.RULES}
    cur.executemany(
        "INSERT INTO app.findings VALUES (%s, %s, %s)", [(f, run_id, r) for r, f in findings.items()]
    )
    return run_id, findings


def period_bounds() -> tuple[dt.date, dt.date]:
    year, month = (int(p) for p in PERIOD.split("-"))
    nxt = dt.date(year + (month == 12), month % 12 + 1, 1)
    return dt.date(year, month, 1), nxt - dt.timedelta(days=1)


def verify(cur: psycopg.Cursor, run_id: uuid.UUID, findings: dict, catalogue: dict) -> list[str]:
    """Compare everything the run wrote with the generator's catalogue. Empty list = exact match."""
    problems: list[str] = []
    expected_all = catalogue["expected_findings"]
    for unknown in set(expected_all) - set(wl.RULES):
        problems.append(f"{unknown}: in the catalogue but not implemented")
    for rule_id in wl.RULES:
        expected = expected_all.get(rule_id, {"rows": [], "groups": None})
        cur.execute(
            "SELECT row_num, record_key, group_no, is_canonical FROM app.finding_records"
            " WHERE finding_id = %s ORDER BY ordinal", (findings[rule_id],),
        )  # fmt: skip
        actual = cur.fetchall()
        got = sorted([r[0], r[1]] for r in actual)
        if got != expected["rows"]:
            want = {tuple(r) for r in expected["rows"]}
            have = {tuple(r) for r in got}
            problems.append(f"{rule_id}: {len(have)} found vs {len(want)} planted; "
                            f"missing {sorted(want - have)[:3]}, unexpected {sorted(have - want)[:3]}")  # fmt: skip
        if expected["groups"] is not None:
            groups: dict[int, list[int]] = {}
            for row_num, _, group_no, _ in actual:
                groups.setdefault(group_no, []).append(row_num)
            if sorted(sorted(g) for g in groups.values()) != expected["groups"]:
                problems.append(f"{rule_id}: group membership differs")
            canonical = {r[0] for r in actual if r[3]}
            if canonical != {g[0] for g in expected["groups"]}:
                problems.append(f"{rule_id}: canonical records differ")
    cur.execute(
        "SELECT category, currency, amount, record_count, unquantifiable_count"
        " FROM app.run_impact_totals WHERE run_id = %s", (run_id,),
    )  # fmt: skip
    totals: dict = {}
    for category, currency, amount, records, unquantifiable in cur.fetchall():
        totals.setdefault(category, {})[currency] = {
            "amount": f"{amount:.2f}", "record_count": records, "unquantifiable_count": unquantifiable}  # fmt: skip
    if totals != {k: v for k, v in catalogue["expected_impact_totals"].items() if v}:
        problems.append(f"impact totals differ: {totals} vs {catalogue['expected_impact_totals']}")
    cur.execute(
        "SELECT currency, supplier_id, scope, value FROM app.kpi_values WHERE run_id = %s", (run_id,)
    )
    kpi: dict = {}
    for currency, supplier, scope, value in cur.fetchall():
        kpi.setdefault((currency, supplier), {})[scope.lower()] = f"{value:.2f}"
    want_kpi = {(k["currency"], k["supplier_id"]): {"as_reported": k["as_reported"],
                "fully_adjusted": k["fully_adjusted"]} for k in catalogue["expected_kpi02"]}  # fmt: skip
    if kpi != want_kpi:
        diff = [k for k in set(kpi) | set(want_kpi) if kpi.get(k) != want_kpi.get(k)]
        problems.append(f"KPI-02 differs for {len(diff)} supplier/currency pairs, e.g. {diff[:3]}")
    return problems


def cmd_validate(args: argparse.Namespace) -> None:
    dataset = args.dataset
    version_id = state()["versions"][dataset]
    catalogue = json.loads((DATA / dataset / "catalogue.json").read_text())
    loads = validation_workloads = wl.validation_workloads()
    start, end = period_bounds()
    per_workload: dict[str, list[float]] = {w.id: [] for w in loads}
    totals_w1_w9: list[float] = []
    totals_all: list[float] = []
    problems: list[str] = []
    counts: dict[str, int] = {}

    with app() as conn:
        env = environment(conn)
        conn.rollback()

        def one_run(explain: bool) -> dict:
            plans: dict = {}
            cursor_cls = psycopg.ClientCursor if explain else psycopg.Cursor
            with cursor_cls(conn) as cur:
                if args.work_mem:
                    cur.execute(f"SET LOCAL work_mem = '{int(args.work_mem)}MB'")
                run_id, findings = start_run(cur, version_id)
                base = wl.base_params(version_id, run_id, findings, start, end)
                elapsed: dict[str, float] = {}
                for workload in validation_workloads:
                    t0 = time.perf_counter()
                    for stmt in workload.statements:
                        params = {**base, "f": findings.get(stmt.rule)}
                        if explain:
                            cur.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + stmt.sql, params)
                            plans[f"{workload.id}-{stmt.name}"] = cur.fetchone()[0][0]
                        else:
                            cur.execute(stmt.sql, params)
                    elapsed[workload.id] = time.perf_counter() - t0
                found = verify(cur, run_id, findings, catalogue)
                cur.execute(
                    "SELECT f.rule_id, count(*) FROM app.finding_records r JOIN app.findings f"
                    " ON f.id = r.finding_id WHERE f.run_id = %s GROUP BY 1 ORDER BY 1", (run_id,),
                )  # fmt: skip
                counts.update(dict(cur.fetchall()))
            conn.rollback()  # every measured run starts from the same state
            return {"elapsed": elapsed, "problems": found, "plans": plans}

        for i in range(args.warmup + args.runs):
            run = one_run(explain=False)
            w1_w9 = sum(run["elapsed"][w.id] for w in loads if w.in_w1_w9)
            everything = sum(run["elapsed"].values())
            tag = "warm-up" if i < args.warmup else "measured"
            print(f"{tag} run {i}: W1-W9 {w1_w9:.3f}s, all rules {everything:.3f}s, "
                  f"catalogue {'MATCH' if not run['problems'] else 'MISMATCH'}")  # fmt: skip
            problems.extend(run["problems"])
            if i >= args.warmup:
                totals_w1_w9.append(w1_w9)
                totals_all.append(everything)
                for wid, seconds in run["elapsed"].items():
                    per_workload[wid].append(seconds)
        plan_summary = {}
        if not args.no_explain:
            explained = one_run(explain=True)
            problems.extend(explained["problems"])
            plan_dir = PLANS / args.label
            plan_dir.mkdir(parents=True, exist_ok=True)
            for name, plan in explained["plans"].items():
                (plan_dir / f"{name}.json").write_text(json.dumps(plan, indent=1))
                plan_summary[name] = read_plan(plan)

    result = {
        "label": args.label, "dataset": dataset, "variant": "A (JSONB, primary key only)",
        "work_mem_override_mb": args.work_mem, "runs": args.runs, "warmup": args.warmup,
        "environment": env,
        "full_run_w1_w9": summary(totals_w1_w9),
        "full_run_all_rules": summary(totals_all),
        "workloads": {w.id: {"title": w.title, "statements": [s.name for s in w.statements],
                             **summary(per_workload[w.id])} for w in loads},
        "finding_record_counts": counts,
        "catalogue_match": not problems,
        "catalogue_problems": sorted(set(problems)),
        "plans": plan_summary,
    }  # fmt: skip
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"validate-{args.label}.json").write_text(json.dumps(result, indent=1, default=str))
    print(f"\n{'workload':<6}{'median s':>10}{'max s':>9}  title")
    for w in loads:
        s = result["workloads"][w.id]
        print(f"{w.id:<6}{s['median_s']:>10.3f}{s['max_s']:>9.3f}  {w.title}")
    print(f"W1-W9 full run: median {result['full_run_w1_w9']['median_s']}s, "
          f"max {result['full_run_w1_w9']['max_s']}s")  # fmt: skip
    print(f"all rules:      median {result['full_run_all_rules']['median_s']}s, "
          f"max {result['full_run_all_rules']['max_s']}s")  # fmt: skip
    for name, p in plan_summary.items():
        print(f"  {name:<28} {p['execution_ms']:>8.1f} ms  {', '.join(p['version_rows_access'])}"
              f"  temp={p['temp_blocks_written']}  est/act x{p['worst_row_estimate']['ratio']}"
              f"  {'; '.join(p['spills'])}")  # fmt: skip
    print("catalogue:", "EXACT MATCH" if not problems else "MISMATCH")
    for problem in sorted(set(problems)):
        print("  -", problem)
    if problems:
        sys.exit(1)


# ---- W11 publication snapshot ------------------------------------------------------------
def canonical_csv_hashes(cur: psycopg.Cursor, publication_id: uuid.UUID) -> dict:
    """SENTINEL-SNAPSHOT-V1 (ARD §8.3.2): canonical CSV per table and the snapshot hash."""
    hashes = {}
    for table, key in (("invoices", "invoice_id"), ("suppliers", "supplier_id")):
        columns = wl.CONTRACT[table]
        digest = hashlib.sha256()
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(columns)
        cur.execute(
            f"SELECT {', '.join(columns)} FROM published.{table}"  # noqa: S608 - contract names
            f' WHERE publication_id = %s ORDER BY {key} COLLATE "C"', (publication_id,),
        )  # fmt: skip
        rows = 0
        while batch := cur.fetchmany(10_000):
            for row in batch:
                writer.writerow(
                    "" if v is None else f"{v:.2f}" if isinstance(v, Decimal) else
                    v.isoformat() if isinstance(v, dt.date) else v for v in row
                )  # fmt: skip
            rows += len(batch)
            digest.update(buffer.getvalue().encode("utf-8"))
            buffer.seek(0)
            buffer.truncate()
        digest.update(buffer.getvalue().encode("utf-8"))
        hashes[table] = {"rows": rows, "sha256": digest.hexdigest()}
    lines = "".join(f"{t}:{hashes[t]['sha256']}\n" for t in sorted(hashes))
    return {"tables": hashes, "snapshot_hash": hashlib.sha256(lines.encode()).hexdigest()}


def cmd_publish(args: argparse.Namespace) -> None:
    version_id = state()["versions"]["corrected"]
    samples: dict[str, list[float]] = {"insert_s": [], "export_hash_s": [], "total_s": []}
    snapshot_hashes = set()
    plan_summary = {}
    with app() as conn:
        env = environment(conn)
        conn.rollback()

        def one_run(explain: bool) -> None:
            cursor_cls = psycopg.ClientCursor if explain else psycopg.Cursor
            with cursor_cls(conn) as cur:
                publication_id = uuid.uuid4()
                t0 = time.perf_counter()
                cur.execute("INSERT INTO app.publications (id, dataset_version_id) VALUES (%s, %s)",
                            (publication_id, version_id))  # fmt: skip
                params = {f"c_{c}": c for cols in wl.CONTRACT.values() for c in cols}
                params.update(pub=publication_id, v=version_id)
                for stmt in wl.publish_statements():
                    params["t"] = stmt.name.removeprefix("snapshot_")
                    if explain:
                        cur.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + stmt.sql, params)
                        plan = cur.fetchone()[0][0]
                        (PLANS / args.label).mkdir(parents=True, exist_ok=True)
                        (PLANS / args.label / f"W11-{stmt.name}.json").write_text(json.dumps(plan, indent=1))
                        plan_summary[f"W11-{stmt.name}"] = read_plan(plan)
                    else:
                        cur.execute(stmt.sql, params)
                t1 = time.perf_counter()
                snapshot = canonical_csv_hashes(cur, publication_id)
                t2 = time.perf_counter()
            conn.rollback()
            admin("VACUUM published.invoices, published.suppliers")
            if not explain:
                snapshot_hashes.add(json.dumps(snapshot, sort_keys=True))
                return t1 - t0, t2 - t1

        for i in range(args.warmup + args.runs):
            insert_s, export_s = one_run(explain=False)
            print(f"W11 run {i}: insert {insert_s:.2f}s, export+hash {export_s:.2f}s")
            if i >= args.warmup:
                samples["insert_s"].append(insert_s)
                samples["export_hash_s"].append(export_s)
                samples["total_s"].append(insert_s + export_s)
        one_run(explain=True)
    result = {"workload": "W11", "label": args.label, "environment": env,
              **{k: summary(v) for k, v in samples.items()},
              "snapshot_deterministic": len(snapshot_hashes) == 1,
              "snapshot": json.loads(next(iter(snapshot_hashes))), "plans": plan_summary}  # fmt: skip
    (RESULTS / f"W11-publish-{args.label}.json").write_text(json.dumps(result, indent=1))
    print(f"W11 median {result['total_s']['median_s']}s max {result['total_s']['max_s']}s; "
          f"deterministic snapshot hash: {result['snapshot_deterministic']}")  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup").set_defaults(func=cmd_setup)
    for name, func in (("load", cmd_load), ("validate", cmd_validate), ("publish", cmd_publish)):
        p = sub.add_parser(name)
        p.add_argument("--runs", type=int, default=5)
        p.add_argument("--warmup", type=int, default=1)
        p.add_argument("--label", default="A")
        p.set_defaults(func=func)
        if name == "load":
            p.add_argument("--skip-analyze", action="store_true")
        if name == "validate":
            p.add_argument("--dataset", choices=DATASETS, default="defective")
            p.add_argument("--work-mem", type=int, help="SET LOCAL work_mem (MB) for the run")
            p.add_argument("--no-explain", action="store_true")
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
