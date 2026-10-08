"""Upload size limits hold whether or not the upload reports its size.

Split out of test_small_bugs.py (2026-10-02)."""
from __future__ import annotations

import io
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

from app.services import upload_limits


@pytest.mark.parametrize('raw,expected', [
    (None, None), ('', None), ('  ', None), ('invalid', None), ('2.5', None),
    ('0', 1), ('-7', 1), ('1', 1), (' 42 ', 42), ('+42', 42),
    (str(10**40), 10**40),
])
def test_upload_and_restore_limit_parsing_preserves_boundaries(monkeypatch, raw, expected):
    from app.services import restore_state

    limits = [
        (upload_limits.upload_max_bytes, 'COPYLOT_UPLOAD_MAX_BYTES', 64 * 1024**3),
        (upload_limits.upload_max_cells, 'COPYLOT_UPLOAD_MAX_CELLS', 10_000_000_000),
        (upload_limits.upload_max_columns, 'COPYLOT_UPLOAD_MAX_COLUMNS', 20_000),
        (upload_limits.upload_max_frame_bytes, 'COPYLOT_UPLOAD_MAX_FRAME_BYTES', 8 * 1024**3),
        (restore_state.restore_upload_max_bytes, 'COPYLOT_RESTORE_UPLOAD_MAX_BYTES', 64 * 1024**2),
        (restore_state.restore_expanded_max_bytes, 'COPYLOT_RESTORE_EXPANDED_MAX_BYTES', 256 * 1024**2),
        (restore_state.restore_replacement_max_bytes, 'COPYLOT_RESTORE_REPLACEMENT_MAX_BYTES', 64 * 1024**3),
        (restore_state.restore_replacements_total_max_bytes, 'COPYLOT_RESTORE_REPLACEMENTS_TOTAL_MAX_BYTES', 128 * 1024**3),
        (restore_state.restore_table_max_rows, 'COPYLOT_RESTORE_TABLE_MAX_ROWS', 5_000_000),
        (restore_state.restore_table_max_columns, 'COPYLOT_RESTORE_TABLE_MAX_COLUMNS', 50_000),
        (restore_state.restore_table_max_cells, 'COPYLOT_RESTORE_TABLE_MAX_CELLS', 50_000_000),
        (restore_state.restore_replacement_max_files, 'COPYLOT_RESTORE_REPLACEMENT_MAX_FILES', 256),
        (restore_state.restore_manifest_max_chars, 'COPYLOT_RESTORE_MANIFEST_MAX_CHARS', 1_000_000),
    ]
    monkeypatch.setattr(upload_limits, '_memory_capacity_bytes', lambda: 32 * 1024**3)
    for _, setting, _ in limits:
        monkeypatch.delenv(setting, raising=False)
    for getter, setting, default in limits:
        if raw is not None:
            monkeypatch.setenv(setting, raw)
        assert getter() == (default if expected is None else expected), setting
        monkeypatch.delenv(setting, raising=False)


def test_restore_replacement_limits_inherit_configured_upload_budget(monkeypatch):
    from app.services import restore_state

    monkeypatch.setenv('COPYLOT_UPLOAD_MAX_BYTES', '123456')
    monkeypatch.delenv('COPYLOT_RESTORE_REPLACEMENT_MAX_BYTES', raising=False)
    monkeypatch.delenv('COPYLOT_RESTORE_REPLACEMENTS_TOTAL_MAX_BYTES', raising=False)
    assert restore_state.restore_replacement_max_bytes() == 123456
    assert restore_state.restore_replacements_total_max_bytes() == 246912
    monkeypatch.setenv('COPYLOT_RESTORE_REPLACEMENT_MAX_BYTES', '100000')
    assert restore_state.restore_replacements_total_max_bytes() == 200000



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
