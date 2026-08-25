from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient

from app.main import _host_is_allowed, app
from app.services.dataset_reader import read_dataframe
from app.services.upload_limits import (
    ensure_table_within_cell_budget,
    upload_max_cells,
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.mark.parametrize(
    "host",
    ["localhost", "localhost:8000", "127.0.0.1", "127.0.0.1:5173", "[::1]", "[::1]:8000", ""],
)
def test_local_hosts_are_served(host: str) -> None:
    assert _host_is_allowed(host)


@pytest.mark.parametrize(
    "host",
    ["evil.attacker.example", "attacker.test:8000", "localhost.evil.example", "127.0.0.1.evil.example"],
)
def test_foreign_hosts_are_refused(host: str) -> None:
    assert not _host_is_allowed(host), (
        f"{host!r} was accepted; a rebound hostname resolving to 127.0.0.1 makes the "
        "request same-origin, so the Host header is the only thing left to check"
    )


def test_a_rebound_host_is_rejected_over_http(client: TestClient) -> None:
    response = client.get("/api/health", headers={"host": "evil.attacker.example"})
    assert response.status_code == 400
    assert "Host" in response.json()["detail"]


def test_a_configured_host_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    assert not _host_is_allowed("proteomics.institute.example")
    monkeypatch.setenv("COPYLOT_ALLOWED_HOSTS", "proteomics.institute.example")
    assert _host_is_allowed("proteomics.institute.example")
    assert _host_is_allowed("proteomics.institute.example:8443")
    assert not _host_is_allowed("evil.attacker.example")


def test_an_ordinary_table_fits_the_cell_budget() -> None:
    ensure_table_within_cell_budget(20_000, 40, label="Upload")


def test_a_table_over_the_budget_is_refused() -> None:
    budget = upload_max_cells()
    with pytest.raises(ValueError, match="cell limit"):
        ensure_table_within_cell_budget(budget // 10 + 1, 11, label="Upload")


def test_a_compressed_parquet_bomb_is_refused_before_it_is_materialised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows, columns = 4_000_000, 14
    buffer = io.BytesIO()
    table = pa.table(
        {f"c{i}": pa.array(np.zeros(rows, dtype="float64")) for i in range(columns)}
    )
    pq.write_table(table, buffer, compression="gzip")
    compressed = len(buffer.getvalue())
    buffer.seek(0)

    assert compressed < 5_000_000, (
        f"fixture is {compressed} bytes; the point is that it sits far below the "
        "byte limit while expanding past it once parsed"
    )

    materialised: list[str] = []
    original_read = pq.ParquetFile.read

    def spy(self, *args, **kwargs):
        materialised.append("read")
        return original_read(self, *args, **kwargs)

    monkeypatch.setattr(pq.ParquetFile, "read", spy)

    with pytest.raises(ValueError, match="cell limit"):
        read_dataframe("bomb.parquet", buffer)

    assert not materialised, (
        "the bomb was rejected only after being read into memory; the shape is in "
        "the parquet metadata, so it must be refused before allocating 448 MB"
    )
