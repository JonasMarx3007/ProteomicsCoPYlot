import io
from types import SimpleNamespace

import pytest
from fastapi import UploadFile

from app.services import upload_limits as limits


def test_large_precursor_report_fits_logical_budgets(monkeypatch):
    monkeypatch.delenv('COPYLOT_UPLOAD_MAX_BYTES', raising=False)
    monkeypatch.delenv('COPYLOT_UPLOAD_MAX_CELLS', raising=False)
    limits.ensure_table_within_cell_budget(500 * 100_000, 70)
    assert limits.upload_max_cells() == 10_000_000_000
    assert limits.upload_max_bytes() == 64 * 1024**3
    upload = UploadFile(io.BytesIO(), size=40 * 1024**3, filename='precursors.tsv')
    limits.ensure_upload_size(upload)
    upload.size = 65 * 1024**3
    with pytest.raises(ValueError, match='upload limit'):
        limits.ensure_upload_size(upload)


@pytest.mark.parametrize('ram,budget', [(32, 8), (256, 64), (1024, 128)])
def test_default_frame_budget_reserves_ram_for_processing_copies(monkeypatch, ram, budget):
    monkeypatch.delenv('COPYLOT_UPLOAD_MAX_FRAME_BYTES', raising=False)
    monkeypatch.setattr(limits, '_memory_capacity_bytes', lambda: ram * 1024**3)
    assert limits.upload_max_frame_bytes() == budget * 1024**3
    limits.ensure_frame_bytes_within_budget(budget * 1024**3)
    with pytest.raises(ValueError, match='COPYLOT_UPLOAD_MAX_FRAME_BYTES'):
        limits.ensure_frame_bytes_within_budget(budget * 1024**3 + 1)


def test_memory_budget_override_and_safe_detection_fallback(monkeypatch):
    monkeypatch.setattr(limits, '_memory_capacity_bytes', lambda: None)
    monkeypatch.delenv('COPYLOT_UPLOAD_MAX_FRAME_BYTES', raising=False)
    assert limits.upload_max_frame_bytes() == 1024**3
    monkeypatch.setenv('COPYLOT_UPLOAD_MAX_FRAME_BYTES', str(48 * 1024**3))
    assert limits.upload_max_frame_bytes() == 48 * 1024**3
    monkeypatch.setenv('COPYLOT_UPLOAD_MAX_FRAME_BYTES', 'invalid')
    assert limits.upload_max_frame_bytes() == 1024**3


def test_memory_detection_without_sysconf_uses_safe_fallback(monkeypatch):
    monkeypatch.setattr(limits, 'os', SimpleNamespace(name='posix'))
    assert limits._memory_capacity_bytes() is None


@pytest.mark.parametrize('v2,v1,expected', [('max', 'max', 256), (str(16 * 1024**3), 'max', 16),
                                         ('max', str(8 * 1024**3), 8)])
def test_visible_container_memory_limit_is_respected(monkeypatch, v2, v1, expected):
    monkeypatch.setattr(limits, 'os', SimpleNamespace(name='posix',
        sysconf=lambda name: {'SC_PHYS_PAGES': 256 * 1024**3 // 4096, 'SC_PAGE_SIZE': 4096}[name]))
    monkeypatch.setattr(limits, 'Path', lambda path: SimpleNamespace(read_text=lambda:
        v2 if path.endswith('memory.max') else v1))
    assert limits._memory_capacity_bytes() == expected * 1024**3


def test_excel_preflight_accepts_large_sheets_without_materializing_them(monkeypatch):
    import openpyxl
    from app.services.dataset_reader import _ensure_workbook_within_budget
    monkeypatch.delenv('COPYLOT_UPLOAD_MAX_CELLS', raising=False)
    monkeypatch.setattr(openpyxl, 'load_workbook', lambda *a, **k: SimpleNamespace(
        worksheets=[SimpleNamespace(max_row=1_048_576, max_column=70)], close=lambda: None))
    _ensure_workbook_within_budget(io.BytesIO())
