import pandas as pd
import pytest

from app.schemas.stats import AnovaRequest
from app.services import stats_tools
from app.services.runtime_cache import invalidate_runtime_cache


@pytest.mark.parametrize("pairs,expected", [
    (["s1", "s2", "s1", "s2"], True),
    (["s1", "s2", " s1 ", ""], True),
    (["s1", "s1", "s2", "s2"], False),
    (["", None, " ", None], False),
    (["s1", "s2", "s3", "s4"], False),
])
def test_warning_requires_links_across_analyzed_conditions(pairs, expected):
    metadata = pd.DataFrame({"sample": ["A1", "A2", "B1", "B2"],
                             "condition": ["A", "A", "B", "B"], "pair_id": pairs})
    assert bool(stats_tools._anova_pairing_warning(metadata, metadata["sample"].tolist())) == expected
    assert stats_tools._anova_pairing_warning(metadata, ["A1", "A2"]) is None
    assert stats_tools._anova_pairing_warning(metadata.drop(columns="pair_id"), ["A1", "A2"]) is None


def test_anova_warns_without_changing_results(monkeypatch):
    frame = pd.DataFrame({"ProteinNames": ["P1", "P2"],
                          "A1": [1., 4.], "A2": [2., 5.], "B1": [4., 6.], "B2": [6., 9.]})
    metadata = pd.DataFrame({"sample": ["A1", "A2", "B1", "B2"], "condition": ["A", "A", "B", "B"]})
    monkeypatch.setattr(stats_tools, "_stats_source", lambda *a, **k: ("filtered", frame, metadata, []))
    monkeypatch.setattr(stats_tools, "_imputation_mask", lambda *a, **k: None)
    request = AnovaRequest(kind="protein", dataSource="filtered")
    independent = stats_tools.run_anova(request)
    metadata["pair_id"] = ["s1", "s2", "s1", "s2"]
    invalidate_runtime_cache("test-pairing-update", all_sessions=True)
    paired = stats_tools.run_anova(request)
    assert paired.rows == independent.rows
    assert not any("Pairing IDs" in warning for warning in independent.warnings)
    assert any("2 shared ID(s)" in warning and "ignores these links" in warning for warning in paired.warnings)
