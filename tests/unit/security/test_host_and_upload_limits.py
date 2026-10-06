from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

ROOT = Path(__file__).resolve().parents[3]

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
    # This security test exercises a configured ceiling, not a production-size default.
    monkeypatch.setenv("COPYLOT_UPLOAD_MAX_CELLS", "50000000")
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


def test_an_oversized_delimited_table_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COPYLOT_UPLOAD_MAX_CELLS", "200000")
    rows, columns = 60_000, 10
    frame = pd.DataFrame(np.zeros((rows, columns)))
    buffer = io.BytesIO(frame.to_csv(index=False).encode())
    with pytest.raises(ValueError, match="cell limit"):
        read_dataframe("big.csv", buffer)


def test_an_oversized_workbook_is_refused_from_its_dimensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import openpyxl

    monkeypatch.setenv("COPYLOT_UPLOAD_MAX_CELLS", "200000")
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    for _ in range(30_000):
        sheet.append([0] * 10)
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)

    read_calls: list[str] = []
    original = pd.read_excel

    def spy(*args, **kwargs):
        read_calls.append("read_excel")
        return original(*args, **kwargs)

    monkeypatch.setattr(pd, "read_excel", spy)
    with pytest.raises(ValueError, match="cell limit"):
        read_dataframe("big.xlsx", buffer)
    assert not read_calls, (
        "the workbook was rejected only after pandas materialised it; the shape is "
        "in the worksheet dimensions, so it must be refused before that"
    )


@pytest.mark.parametrize("name,sep", [("t.csv", ","), ("t.tsv", "	")])
def test_an_ordinary_delimited_table_still_reads(name: str, sep: str) -> None:
    frame = pd.DataFrame(np.arange(500).reshape(100, 5), columns=list("abcde"))
    buffer = io.BytesIO(frame.to_csv(index=False, sep=sep).encode())
    out = read_dataframe(name, buffer)
    assert out.shape == (100, 5)


def test_a_table_spanning_several_chunks_is_reassembled_intact() -> None:
    rows = 120_000
    frame = pd.DataFrame({"a": np.arange(rows), "b": np.arange(rows) * 2})
    buffer = io.BytesIO(frame.to_csv(index=False).encode())
    out = read_dataframe("many.csv", buffer)
    assert len(out) == rows, "chunked reading must not drop or duplicate rows"
    assert out["a"].iloc[-1] == rows - 1


def _big_cell_parquet(cells: int = 40, size: int = 1024 * 1024) -> io.BytesIO:
    """A file that is tiny on disk and large in memory.

    Every value is distinct so parquet cannot dictionary encode them away, which
    is what makes the footer's uncompressed size an honest floor here and a
    misleading one when the values repeat.
    """
    filler = "x" * size
    frame = pd.DataFrame({"a": [filler + str(i) for i in range(cells)]})
    buffer = io.BytesIO()
    frame.to_parquet(buffer, compression="gzip")
    buffer.seek(0)
    return buffer


def test_a_small_file_that_expands_a_long_way_is_refused(monkeypatch) -> None:
    """Rows x columns measures shape, and memory does not care about shape.

    Forty cells is nothing against the cell budget, and the file is well under
    the byte limit as it arrives. Only the materialised size sees the problem.
    """
    monkeypatch.setenv("COPYLOT_UPLOAD_MAX_FRAME_BYTES", str(8 * 1024 * 1024))
    buffer = _big_cell_parquet()
    assert len(buffer.getvalue()) < 8 * 1024 * 1024, "the file itself must be under the limit"
    with pytest.raises(ValueError, match="expands to"):
        read_dataframe("bomb.parquet", buffer)


def test_a_pathologically_wide_table_is_refused(monkeypatch) -> None:
    """Per-column overhead is invisible to a byte count of the data."""
    monkeypatch.setenv("COPYLOT_UPLOAD_MAX_COLUMNS", "500")
    frame = pd.DataFrame({f"c{i}": [1.0] for i in range(2_000)})
    buffer = io.BytesIO(frame.to_csv(index=False).encode())
    with pytest.raises(ValueError, match="columns, above"):
        read_dataframe("wide.csv", buffer)


def test_a_delimited_file_of_large_cells_is_refused(monkeypatch) -> None:
    monkeypatch.setenv("COPYLOT_UPLOAD_MAX_FRAME_BYTES", str(4 * 1024 * 1024))
    row = ",".join(["y" * 200_000, "z" * 200_000])
    payload = chr(10).join(["a,b"] + [row] * 40)
    with pytest.raises(ValueError, match="expands to"):
        read_dataframe("fat.csv", io.BytesIO(payload.encode()))


def test_an_xlsx_that_expands_a_long_way_is_refused(monkeypatch) -> None:
    """The zip directory reports uncompressed size without decompressing.

    Excel caps a cell at 32,767 characters, so a workbook cannot carry the
    megabyte-sized cells a parquet file can -- it has to get there with many
    cells instead. Distinct values, so the shared-string table cannot fold them
    into one.
    """
    monkeypatch.setenv("COPYLOT_UPLOAD_MAX_FRAME_BYTES", str(2 * 1024 * 1024))
    frame = pd.DataFrame({"a": [("y" * 30_000) + str(i) for i in range(300)]})
    buffer = io.BytesIO()
    frame.to_excel(buffer, index=False)
    buffer.seek(0)
    assert len(buffer.getvalue()) < 2 * 1024 * 1024, "the file itself must be under the limit"
    with pytest.raises(ValueError, match="expands to"):
        read_dataframe("bomb.xlsx", buffer)


def test_an_oversized_xlsx_is_refused_without_decompressing_it(monkeypatch, tmp_path) -> None:
    """A zip's central directory carries each member's uncompressed size.

    So the expanded cost is knowable from the archive's index alone, without
    inflating a single entry. Without that, the workbook is refused only after
    openpyxl and pandas have already built it.
    """
    monkeypatch.setenv("COPYLOT_UPLOAD_MAX_FRAME_BYTES", str(2 * 1024 * 1024))
    frame = pd.DataFrame({"a": [("y" * 30_000) + str(i) for i in range(300)]})
    path = tmp_path / "bomb.xlsx"
    frame.to_excel(path, index=False)
    del frame

    consumed = _bytes_consumed_before_refusing("bomb.xlsx", path)
    assert consumed < path.stat().st_size, (
        f"read {consumed:,} of {path.stat().st_size:,} bytes; the archive index "
        "alone should have been enough to refuse it"
    )


def test_a_realistic_report_is_not_caught_by_any_of_the_budgets() -> None:
    """The bundled protein dataset's shape, at the shipped defaults."""
    frame = pd.DataFrame(
        {"ProteinNames": [f"P{i}" for i in range(7_490)],
         **{f"s{j}": np.arange(7_490, dtype=float) for j in range(18)}}
    )
    buffer = io.BytesIO(frame.to_csv(index=False).encode())
    assert read_dataframe("real.csv", buffer).shape == (7_490, 19)


class _CountingReader(io.RawIOBase):
    """A stream that records how many bytes were actually pulled from it."""

    def __init__(self, raw: io.BufferedReader) -> None:
        self.raw = raw
        self.count = 0

    def read(self, size: int = -1) -> bytes:
        block = self.raw.read(size)
        self.count += len(block)
        return block

    def readinto(self, buffer) -> int:  # type: ignore[no-untyped-def]
        read = self.raw.readinto(buffer)
        self.count += read or 0
        return read or 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def seek(self, offset: int, whence: int = 0) -> int:
        return self.raw.seek(offset, whence)

    def tell(self) -> int:
        return self.raw.tell()


def _bytes_consumed_before_refusing(name: str, path) -> int:
    with open(path, "rb") as raw:
        counter = _CountingReader(raw)
        with pytest.raises(ValueError):
            read_dataframe(name, counter)
        return counter.count


def test_an_oversized_delimited_file_is_refused_without_reading_it(monkeypatch, tmp_path) -> None:
    """Refusing is not enough; it has to refuse before paying the cost.

    Row-based chunking cannot bound this on its own: at 50,000 rows per chunk a
    file of 400 enormous rows is a single chunk, so the loop would read all of it
    before weighing any of it. Delimited text is not compressed, so its length is
    an honest floor and can be checked before the parser starts.
    """
    monkeypatch.setenv("COPYLOT_UPLOAD_MAX_FRAME_BYTES", str(4 * 1024 * 1024))
    row = ",".join(["y" * 100_000, "z" * 100_000])
    path = tmp_path / "fat.csv"
    path.write_text(chr(10).join(["a,b"] + [row] * 400), encoding="utf-8")
    assert path.stat().st_size > 15 * 4 * 1024 * 1024

    consumed = _bytes_consumed_before_refusing("fat.csv", path)
    assert consumed == 0, f"read {consumed:,} bytes of a file it was always going to refuse"


def test_an_oversized_parquet_is_refused_without_materialising_all_of_it(
    monkeypatch, tmp_path
) -> None:
    """Parquet is compressed, so length says nothing; it is read in batches instead."""
    monkeypatch.setenv("COPYLOT_UPLOAD_MAX_FRAME_BYTES", str(4 * 1024 * 1024))
    filler = "x" * (1024 * 1024)
    frame = pd.DataFrame({"a": [filler + str(i) for i in range(120)]})
    path = tmp_path / "bomb.parquet"
    frame.to_parquet(path, compression="gzip")
    del frame

    # Distinct values, so the footer cannot dictionary encode them away and its
    # reported size is honest: the refusal comes from the metadata alone, before
    # a single row group is decompressed.
    consumed = _bytes_consumed_before_refusing("bomb.parquet", path)
    assert consumed < path.stat().st_size, (
        f"read {consumed:,} of {path.stat().st_size:,} bytes; the footer alone "
        "should have been enough to refuse it"
    )
