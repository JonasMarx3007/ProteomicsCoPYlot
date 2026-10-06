from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]

from app.services.dataset_reader import read_dataframe


def _read(name: str, payload: bytes):
    return read_dataframe(name, io.BytesIO(payload))


@pytest.mark.parametrize(
    "name,payload,expected",
    [
        ("page.csv", b"<html><head><title>404</title></head><body>nope</body></html>", "no data rows"),
        ("headeronly.csv", b"ProteinNames,s1,s2\n", "no data rows"),
        ("onecol.csv", b"ProteinNames\nP1\nP2\n", "only 1 column"),
    ],
)
def test_a_file_that_is_not_a_table_is_refused(name: str, payload: bytes, expected: str) -> None:
    """These parse, and hold nothing usable.

    A saved error page, a truncated export and a file read with the wrong
    separator all used to return 200 with a success preview, so the mistake
    surfaced several screens later as an empty analysis.
    """
    with pytest.raises(ValueError, match=expected):
        _read(name, payload)


@pytest.mark.parametrize(
    "name,payload,expected",
    [
        ("empty.csv", b"", "empty or has no header row"),
        ("ragged.csv", b"a,b,c\n1,2,3\n4,5,6,7,8\n", "same number of columns"),
        ("utf16.tsv", "a\tb\n1\t2\n".encode("utf-16"), "NUL byte"),
    ],
)
def test_a_parser_failure_is_explained_in_the_users_terms(
    name: str, payload: bytes, expected: str
) -> None:
    """The parser's own words are not an explanation a biologist can act on."""
    with pytest.raises(ValueError) as excinfo:
        _read(name, payload)
    message = str(excinfo.value)
    assert expected in message
    assert name in message
    for leak in ("Traceback", "C error", "codec can't decode", "No columns to parse"):
        assert leak not in message, f"raw parser text reached the user: {message}"


def test_a_real_report_table_is_untouched() -> None:
    frame = pd.DataFrame(
        {"ProteinNames": [f"P{i}" for i in range(50)],
         **{f"s{j}": [1.0] * 50 for j in range(6)}}
    )
    out = _read("real.csv", frame.to_csv(index=False).encode())
    assert out.shape == (50, 7)


def test_a_two_column_metadata_table_is_still_accepted() -> None:
    """Metadata is the narrowest legitimate upload, so the column floor must clear it."""
    payload = b"sample,condition\ns1,WT\ns2,WT\ns3,GRK\n"
    assert _read("meta.csv", payload).shape == (3, 2)


def test_a_nul_byte_in_a_header_is_refused_not_silently_truncated() -> None:
    """pandas' C parser treats NUL as a terminator.

    A header written as Protein<NUL>Names arrives as "Protein", so the column is
    silently renamed and every later lookup for the real name misses. The
    character is gone before any of our code sees the frame, so it has to be
    caught in the raw bytes.
    """
    payload = b"Protein" + bytes([0]) + b"Names,s1,s2" + bytes([10]) + b"P1,1,2" + bytes([10])
    with pytest.raises(ValueError, match="NUL byte"):
        _read("nul.csv", payload)


def test_ordinary_text_with_no_nul_is_untouched() -> None:
    payload = bytes([10]).join([b"ProteinNames,s1,s2", b"P1,1,2", b""])
    assert _read("clean.csv", payload).shape == (1, 3)
