"""Reference datasets for tests, produced by the generator (FR-017, PRD §12.6).

The generator's catalogue is the oracle: expected values come from what was planted, never
from the code under test.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

GENERATOR = Path(__file__).resolve().parents[2] / "scripts" / "generate_reference_data.py"
PERIOD = "2026-10"


def _generator() -> Any:
    spec = importlib.util.spec_from_file_location("generate_reference_data", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def generate(root: Path, name: str, scale: str = "demo", dataset: str | None = None) -> Path:
    out = root / name
    if not out.exists():
        _generator().generate(20261015, scale, dataset or name, PERIOD, out)
    return out


def catalogue(directory: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((directory / "catalogue.json").read_text())
    return data


def upload(
    client: TestClient,
    headers: dict[str, str],
    *,
    suppliers: bytes,
    invoices: bytes,
    period: str = PERIOD,
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/datasets/SUPINV/periods/{period}/ingestions",
        files={
            "suppliers": ("suppliers.csv", suppliers, "text/csv"),
            "invoices": ("invoices.csv", invoices, "text/csv"),
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    version: dict[str, Any] = response.json()["version"]
    return version


def upload_dataset(client: TestClient, headers: dict[str, str], directory: Path) -> dict[str, Any]:
    return upload(
        client,
        headers,
        suppliers=(directory / "suppliers.csv").read_bytes(),
        invoices=(directory / "invoices.csv").read_bytes(),
    )


def run(client: TestClient, headers: dict[str, str], version_id: str) -> dict[str, Any]:
    response = client.post(f"/api/v1/versions/{version_id}/runs", headers=headers)
    assert response.status_code == 202, response.text
    result: dict[str, Any] = response.json()
    return result


def completed(client: TestClient, headers: dict[str, str], version_id: str) -> dict[str, Any]:
    result = run(client, headers, version_id)
    assert result["status"] == "COMPLETED", result["error_detail"]
    return result
