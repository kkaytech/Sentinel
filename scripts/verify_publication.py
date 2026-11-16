#!/usr/bin/env python3
"""Verify a Sentinel publication export offline (PUB-006). Standard library only.

    python scripts/verify_publication.py <publication.zip> [--expected-manifest-sha256 <hex>]

Exit codes: 0 VERIFIED, 1 FAILED, 2 usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile


def verify(path: str, expected_manifest_sha256: str | None) -> list[str]:
    problems: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if "manifest.json" not in names:
            return ["manifest.json is missing"]
        manifest_bytes = archive.read("manifest.json")
        manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
        print(f"manifest.json sha256: {manifest_sha}")
        if expected_manifest_sha256 and manifest_sha != expected_manifest_sha256.lower():
            problems.append("manifest.json does not match the expected SHA-256")
        manifest = json.loads(manifest_bytes)
        snapshot = manifest["snapshot"]
        hashes = {}
        for table in snapshot["tables"]:
            entry = f"{table['name']}.csv"
            if entry not in names:
                problems.append(f"{entry} is missing")
                continue
            data = archive.read(entry)
            hashes[table["name"]] = hashlib.sha256(data).hexdigest()
            rows = max(data.count(b"\n") - 1, 0) if table["rows"] == 0 else None
            if hashes[table["name"]] != table["sha256"]:
                problems.append(f"{entry}: SHA-256 differs from the manifest")
            if rows not in (None, 0):
                problems.append(f"{entry}: expected no data rows")
            print(f"{entry}: {'ok' if hashes[table['name']] == table['sha256'] else 'MISMATCH'}")
        lines = "".join(f"{name}:{hashes[name]}\n" for name in sorted(hashes))
        if hashlib.sha256(lines.encode("utf-8")).hexdigest() != snapshot["snapshot_hash"]:
            problems.append("snapshot hash differs from the manifest")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a Sentinel publication export.")
    parser.add_argument("zip_path")
    parser.add_argument("--expected-manifest-sha256")
    try:
        args = parser.parse_args()
    except SystemExit:
        return 2
    try:
        problems = verify(args.zip_path, args.expected_manifest_sha256)
    except (OSError, zipfile.BadZipFile, KeyError, ValueError) as exc:
        print(f"FAILED: the package cannot be read ({type(exc).__name__})")
        return 1
    if problems:
        print("FAILED")
        for problem in problems:
            print(f" - {problem}")
        return 1
    print("VERIFIED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
