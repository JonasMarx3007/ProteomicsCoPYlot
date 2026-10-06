"""Upload size limits hold whether or not the upload reports its size.

Split out of test_small_bugs.py (2026-10-02)."""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]

from app.services import upload_limits
from app.services.completeness_tools import (
    _missing_value_plot_from_matrix,
    _peptide_quantity_column,
)



class _StreamOnlyUpload:

    def __init__(self, payload: bytes) -> None:
        self.file = io.BytesIO(payload)
        self.size = None
        self.filename = "payload.csv"


def test_oversized_upload_is_rejected_when_size_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(upload_limits, "upload_max_bytes", lambda: 100)

    class Sized:
        size = 101
        file = io.BytesIO(b"x" * 101)

    with pytest.raises(ValueError):
        upload_limits.ensure_upload_size(Sized(), label="Test upload")


def test_oversized_upload_is_rejected_when_size_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(upload_limits, "upload_max_bytes", lambda: 100)
    with pytest.raises(ValueError):
        upload_limits.ensure_upload_size(_StreamOnlyUpload(b"x" * 500), label="Test upload")


def test_acceptable_upload_passes_and_stream_is_rewound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(upload_limits, "upload_max_bytes", lambda: 1000)
    upload = _StreamOnlyUpload(b"abc123" * 10)
    upload_limits.ensure_upload_size(upload, label="Test upload")
    assert upload.file.read() == b"abc123" * 10


def test_unseekable_stream_does_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(upload_limits, "upload_max_bytes", lambda: 1000)

    class Unseekable:
        size = None

        def __init__(self) -> None:
            self._data = io.BytesIO(b"y" * 50)

        @property
        def file(self):
            outer = self

            class _Inner:
                def read(self, n: int = -1) -> bytes:
                    return outer._data.read(n)

                def tell(self):
                    raise OSError("not seekable")

            return _Inner()

    upload_limits.ensure_upload_size(Unseekable(), label="Test upload")
