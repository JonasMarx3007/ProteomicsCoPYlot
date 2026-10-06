from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

CASES = [
    ("PEPTIDEK", 0, 0, "textbook fully tryptic peptide"),
    ("PEPKTIDEK", 1, 1, "one genuine internal missed cleavage"),
    ("PEPKTIDRSEQK", 2, 2, "two internal missed cleavages"),
    ("SAMPLERPEPTIDEK", 0, 0, "R-P is not a cleavage site under either rule"),
    ("PEPKPTIDEK", 0, 1, "K-P: blocked for trypsin, cleaved by Lys-C"),
    ("PEPKTIDE", 1, 1, "protein C-terminal peptide with an internal K"),
    ("KAEPTIDE", 1, 1, "leading K, genuinely missed"),
    ("PEPTIDE", 0, 0, "no cleavable residue at all"),
    ("MKRPSTKPEPR", 1, 2, "K-P and R-P in one peptide; C-terminal R excluded"),
    ("", 0, 0, "empty sequence"),
    ("K", 0, 0, "single residue is the C-terminus, never a missed cleavage"),
]


def _backend():
    from app.services.peptide_tools import count_missed_cleavages

    return count_missed_cleavages


def _notebook():
    spec = importlib.util.spec_from_file_location(
        "_nb_mc", ROOT / "proteomicscopylot" / "notebook_functions.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["_nb_mc"] = module
    spec.loader.exec_module(module)
    return module.count_missed_cleavages


@pytest.mark.parametrize("implementation", ["backend", "notebook"])
@pytest.mark.parametrize("peptide,trypsin,trypsin_lysc,reason", CASES)
def test_missed_cleavage_counts(
    implementation: str, peptide: str, trypsin: int, trypsin_lysc: int, reason: str
) -> None:
    count = _backend() if implementation == "backend" else _notebook()
    assert count(peptide, "trypsin") == trypsin, f"{implementation} trypsin: {reason}"
    assert count(peptide, "trypsin_lysc") == trypsin_lysc, (
        f"{implementation} trypsin/Lys-C: {reason}"
    )


def test_backend_and_notebook_agree_exactly() -> None:
    backend, notebook = _backend(), _notebook()
    for peptide, _, _, reason in CASES:
        for protease in ("trypsin", "trypsin_lysc"):
            assert backend(peptide, protease) == notebook(peptide, protease), (
                f"backend and notebook disagree on {peptide!r} ({protease}): {reason}"
            )


def test_c_terminal_residue_is_never_a_missed_cleavage() -> None:
    backend = _backend()
    for protease in ("trypsin", "trypsin_lysc"):
        assert backend("PEPTIDE", protease) == backend("PEPTIDEK", protease)
        assert backend("PEPKTIDE", protease) == backend("PEPKTIDEK", protease)


def test_protease_aliases_and_rejection() -> None:
    from app.services.peptide_tools import normalize_protease

    assert normalize_protease("Trypsin") == "trypsin"
    for alias in ("trypsin/lysc", "Trypsin-LysC", "trypsin_lys_c", "TRYPSIN_LYSC"):
        assert normalize_protease(alias) == "trypsin_lysc"
    with pytest.raises(ValueError):
        normalize_protease("chymotrypsin")
