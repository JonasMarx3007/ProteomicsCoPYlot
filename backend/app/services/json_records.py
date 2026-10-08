"""DataFrame rows as JSON-ready records.

`frame.where(notna, None)` alone does not do this: on a float column (and, with
pandas 3, on string columns) the None is stored back as NaN. Converting to
object first is what turns every missing value into None.
"""
from __future__ import annotations

import pandas as pd


def json_records(frame: pd.DataFrame, rows: int | None = None) -> list[dict[str, object]]:
    """The first `rows` rows (all when None) with missing values as None."""
    head = frame if rows is None else frame.head(rows)
    return head.astype(object).where(head.notna(), None).to_dict(orient="records")
