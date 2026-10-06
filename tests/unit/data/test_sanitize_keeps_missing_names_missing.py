"""Missing text cells stay missing on every pandas version.

`astype(str)` on pandas < 3 turns NaN/None into the words "nan" and "None",
which then pass every name check and become labels, ORA input and export
values. pandas 3 keeps them missing, so the same file read differently
depending on the installed version.
"""

from __future__ import annotations

import io

import numpy as np
import pandas as pd

from app.services.dataset_reader import read_dataframe, sanitize_dataframe


def test_missing_text_cells_do_not_become_the_words_nan_or_none():
    frame = pd.DataFrame(
        {
            "ProteinNames": ["P1", None, "P3", np.nan],
            "Genes": [np.nan, "G2", None, "G4"],
            "S1": [1.0, np.nan, 3.0, 4.0],
        }
    )
    out = sanitize_dataframe(frame)
    for column in ("ProteinNames", "Genes"):
        values = out[column].tolist()
        assert not any(isinstance(v, str) and v.lower() in {"nan", "none"} for v in values), values
        assert out[column].isna().sum() == 2, values
    assert out["ProteinNames"].tolist()[0] == "P1" and out["Genes"].tolist()[1] == "G2"
    # Numeric columns are untouched.
    assert out["S1"].dtype.kind == "f" and np.isnan(out["S1"].iloc[1])


def test_a_file_with_empty_name_cells_reads_the_same_way():
    text = "ProteinNames\tGenes\tS1\tS2\nP1\t\t10\t11\n\tG2\t12\t13\n"
    frame = read_dataframe("report.tsv", io.BytesIO(text.encode("utf-8")))
    assert frame["GeneNames"].isna().iloc[0] and frame["ProteinNames"].isna().iloc[1]
    assert "nan" not in frame["GeneNames"].astype("string").str.lower().fillna("").tolist()
