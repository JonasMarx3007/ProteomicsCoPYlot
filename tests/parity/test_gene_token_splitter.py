"""One splitting rule for gene and protein-group cells in the app, the pip package and R (2026-10-22).

The three gene splitters used to carry their own `;` loop next to the shared
`split_tokens` (used for accessions). They delegate to it now. This test pins
two things: for every `;`-separated input the result is exactly what the former
loops returned (the legacy rule is reproduced here verbatim), and the two
differences are the same in all three: a `,` also separates members, and a
cell that is just the text "nan" (a stringified missing value) is empty.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd
import pytest

from app.services import stats_tools
from proteomicscopylot import notebook_functions as nb

ROOT = Path(__file__).resolve().parents[2]

LEGACY_INPUTS = ["AKT1", " MTOR ", "A;B", "A; B ;C", ";;", "", "   ", None, np.nan, float("nan"),
                 "A;A;a", "P12345-2;Q9Y6K9", "GENE_1;GENE_2;", 12345, 1.5, "A;B", "b;c"]
COMMA_INPUTS = ["AKT1, MTOR", "A,B;C", " , ", "X;Y,Z", None, np.nan, ""]


def legacy_tokens(values) -> list[str]:
    """The loop every implementation had before 2026-10-22, `;` only."""
    genes: set[str] = set()
    for value in values:
        if value is None or pd.isna(value):
            continue
        if isinstance(value, (float, np.floating)) and not np.isfinite(value):
            continue
        text = str(value).strip()
        genes.update(token.strip() for token in text.split(";") if token.strip())
    return sorted(genes)


def r_tokens(values, tmp_path) -> list[str]:
    from app.services.r_runtime import detect_r_runtime
    frame = pd.DataFrame({"value": [None if v is None else v for v in values]})
    frame.to_csv(tmp_path / "values.csv", index=False)
    script = tmp_path / "split.R"
    script.write_text(
        "args <- commandArgs(TRUE)\nsource(args[1])\n"
        "values <- read.csv(args[2], check.names=FALSE, colClasses='character', na.strings=c('', 'NA'))$value\n"
        "cat(jsonlite::toJSON(as.list(.different_gene_tokens(values)), auto_unbox=TRUE))\n",
        encoding="utf-8")
    result = subprocess.run([detect_r_runtime()["executable"], str(script),
                             str(ROOT / "proteomicscopylot/notebook_functions.R"), str(tmp_path / "values.csv")],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return [str(x) for x in json.loads(result.stdout)]


def test_semicolon_inputs_split_exactly_as_before_in_app_and_pip() -> None:
    expected = legacy_tokens(LEGACY_INPUTS)
    assert expected == ["1.5", "12345", "A", "AKT1", "B", "C", "GENE_1", "GENE_2", "MTOR", "P12345-2", "Q9Y6K9", "a", "b", "c"]
    assert stats_tools._genes_from_values(LEGACY_INPUTS) == expected
    assert nb._different_gene_tokens(LEGACY_INPUTS) == expected
    assert nb._different_gene_tokens(pd.Series(LEGACY_INPUTS, dtype=object)) == expected
    for value in LEGACY_INPUTS:
        assert sorted(set(stats_tools._gene_tokens(value))) == legacy_tokens([value])


def test_a_comma_now_separates_members_the_same_way_in_app_and_pip() -> None:
    expected = ["A", "AKT1", "B", "C", "MTOR", "X", "Y", "Z"]
    assert stats_tools._genes_from_values(COMMA_INPUTS) == expected
    assert nb._different_gene_tokens(COMMA_INPUTS) == expected
    assert legacy_tokens(COMMA_INPUTS) != expected, "this is an intended change"


def test_a_cell_that_is_just_nan_text_is_empty_in_app_and_pip() -> None:
    assert legacy_tokens(["nan"]) == ["nan"], "the former loops kept it"
    assert stats_tools._genes_from_values(["nan"]) == nb._different_gene_tokens(["nan"]) == []
    # inside a group the text stays a member, as `split_tokens` has always done for accessions
    assert stats_tools._genes_from_values(["A;nan"]) == nb._different_gene_tokens(["A;nan"]) == ["A", "nan"]


@pytest.mark.requires_r("jsonlite")
def test_r_splits_the_same_cells(tmp_path) -> None:
    # The csv round trip turns numbers into text, so compare what R can read:
    # the string inputs, which cover every rule (blanks, NaN text, repeats, case).
    strings = [v for v in LEGACY_INPUTS if isinstance(v, str) or v is None]
    assert sorted(r_tokens(strings, tmp_path)) == nb._different_gene_tokens(strings)
    commas = [v for v in COMMA_INPUTS if isinstance(v, str) or v is None]
    assert sorted(r_tokens(commas, tmp_path)) == nb._different_gene_tokens(commas)
    assert r_tokens(["nan"], tmp_path) == [] and r_tokens(["A;nan"], tmp_path) == ["A", "nan"]
