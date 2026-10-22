"""Editing one pairing never silently changes another paired comparison.

A pair ID names one subject in every condition. Saving an A-B pairing used to
clear every ID in A and B and hand out fresh ones, A's old ID first -- so the ID
that tied b2 to c2 was gone, and the next B vs C paired test matched other
subjects or fewer of them without a word.

Now a save keeps every ID a third condition still carries, refuses an edit that
would merge two subjects, and the paired test names the samples it left out.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.schemas.annotation import AnnotationFilterConfig, SamplePairAssignment
from app.services import annotation_store as store
from app.services.functions import paired_sample_columns, unpaired_samples_note
from app.services.stats_tools import _volcano_dataframe

SAMPLES = [f"{c}{i}" for c in "abc" for i in (1, 2, 3)]


def _frame() -> pd.DataFrame:
    rng = np.random.default_rng(0)
    subject = rng.normal(0, 2, size=(60, 3))
    data = {f"{c}{i}": 20 + subject[:, i - 1] + rng.normal(0, 0.2, 60) for c in "abc" for i in (1, 2, 3)}
    frame = pd.DataFrame(data)
    frame["GeneNames"] = [f"G{k}" for k in range(60)]
    return frame


@pytest.fixture
def frame():
    return _frame()


@pytest.fixture
def saved(frame):
    def _save(pair_ids: list[str]) -> None:
        meta = pd.DataFrame({"sample": SAMPLES, "condition": [s[0].upper() for s in SAMPLES], "pair_id": pair_ids})
        store.reset_all_annotations()
        store.save_annotation(
            kind="protein", source_data=frame, metadata=meta, log2_data=frame, filtered_data=frame,
            is_log2_transformed=True, metadata_source="uploaded", filter_config=AnnotationFilterConfig(),
            auto_detected=False, warnings=[],
        )
    yield _save
    store.reset_all_annotations()


def _pair(*pairs: tuple[str, str]) -> list[SamplePairAssignment]:
    return [SamplePairAssignment(condition1Sample=a, condition2Sample=b) for a, b in pairs]


def _ids() -> dict[str, str]:
    meta = store.get_annotation("protein").metadata
    return {s: str(p) for s, p in zip(meta["sample"], meta["pair_id"])}


def _bc_pairs() -> tuple[list[str], list[str]]:
    return paired_sample_columns(store.get_annotation("protein").metadata, "B", "C")


SHARED = ["s1", "s2", "s3"] * 3


def test_swapping_partners_is_refused_when_both_are_subjects_elsewhere(saved) -> None:
    # Every condition shares s1..s3: a1 and b2 are different subjects in C, so
    # pairing them would merge two subjects. Before, the save went through and
    # B vs C quietly matched other subjects.
    saved(SHARED)
    before = _ids()
    with pytest.raises(ValueError, match="two different subjects"):
        store.update_annotation_pairing("protein", "A", "B", _pair(("a1", "b2"), ("a2", "b1"), ("a3", "b3")))
    assert _ids() == before
    assert _bc_pairs() == (["b1", "b2", "b3"], ["c1", "c2", "c3"])


def test_swapping_partners_only_on_the_side_without_links(saved) -> None:
    # Only B and C share subjects; A's IDs are its own. A may be re-matched freely
    # and takes B's IDs, so B vs C is untouched.
    saved(["x1", "x2", "x3"] + ["s1", "s2", "s3"] * 2)
    store.update_annotation_pairing("protein", "A", "B", _pair(("a1", "b2"), ("a2", "b1"), ("a3", "b3")))
    assert _bc_pairs() == (["b1", "b2", "b3"], ["c1", "c2", "c3"])
    assert _ids()["a1"] == _ids()["b2"] == "s2"
    assert _ids()["a2"] == _ids()["b1"] == "s1"


def test_excluding_a_pair_shared_with_c_is_refused_without_changes(saved, monkeypatch) -> None:
    saved(SHARED)
    before = _ids()
    def unexpected_write(*args, **kwargs):
        pytest.fail("A rejected edit must not write uploaded metadata")
    monkeypatch.setattr(store, "update_uploaded_metadata_pair_ids", unexpected_write)
    with pytest.raises(ValueError, match="Cannot exclude a3 and b3.*also links them to C"):
        store.update_annotation_pairing("protein", "A", "B", _pair(("a1", "b1"), ("a2", "b2")))
    assert _ids() == before
    assert _bc_pairs() == (["b1", "b2", "b3"], ["c1", "c2", "c3"])


def test_leaving_a_sample_unpaired_keeps_its_link_to_c(saved) -> None:
    saved(["x1", "x2", "x3"] + ["s1", "s2", "s3"] * 2)
    store.update_annotation_pairing("protein", "A", "B", _pair(("a1", "b1"), ("a2", "b2")))
    ids = _ids()
    assert ids["a3"] == "", "a3 had no link elsewhere and was left unpaired"
    assert ids["b3"] == "s3", "b3 still pairs with c3"
    assert _bc_pairs() == (["b1", "b2", "b3"], ["c1", "c2", "c3"])


def test_missing_b3_does_not_block_a3_c3_link(saved) -> None:
    saved(SHARED)
    stored = store.get_annotation("protein")
    stored.metadata = stored.metadata.loc[stored.metadata["sample"] != "b3"].copy()
    result = store.update_annotation_pairing("protein", "A", "B", _pair(("a1", "b1"), ("a2", "b2")))
    assert paired_sample_columns(result.metadata, "A", "B") == (["a1", "a2"], ["b1", "b2"])
    assert paired_sample_columns(result.metadata, "A", "C") == (["a1", "a2", "a3"], ["c1", "c2", "c3"])


def test_excluding_shared_pair_returns_explanation_to_ui(saved, client) -> None:
    saved(SHARED)
    before = _ids()
    response = client.put("/api/annotations/pairing", json={
        "kind": "protein", "condition1": "A", "condition2": "B",
        "pairs": [pair.model_dump() for pair in _pair(("a1", "b1"), ("a2", "b2"))],
    })
    assert response.status_code == 400
    assert "Keeping those links would include this pair in the test" in response.json()["detail"]
    assert _ids() == before


def test_a_with_its_own_ids_adopts_b_ids_and_b_vs_c_still_works(saved) -> None:
    saved(["x1", "x2", "x3"] + ["s1", "s2", "s3"] * 2)
    store.update_annotation_pairing("protein", "A", "B", _pair(("a1", "b1"), ("a2", "b2"), ("a3", "b3")))
    assert _bc_pairs() == (["b1", "b2", "b3"], ["c1", "c2", "c3"])
    assert [_ids()[s] for s in ("a1", "a2", "a3")] == ["s1", "s2", "s3"]


def test_the_reviews_case_keeps_three_b_vs_c_pairs(saved) -> None:
    saved(["x1", "", ""] + ["s1", "s2", "s3"] * 2)
    store.update_annotation_pairing("protein", "A", "B", _pair(("a1", "b1"), ("a2", "b2"), ("a3", "b3")))
    assert _bc_pairs() == (["b1", "b2", "b3"], ["c1", "c2", "c3"])


def test_contradicting_a_kept_link_is_refused(saved) -> None:
    # a1 has no link; b3 is subject s3 in C, and so is a3. Pairing a1 with b3
    # gives a1 the ID s3 while a3, left unpaired, must keep s3: a contradiction.
    saved(["", "", "s3"] + ["s1", "s2", "s3"] * 2)
    before = _ids()
    with pytest.raises(ValueError, match="unpaired"):
        store.update_annotation_pairing("protein", "A", "B", _pair(("a1", "b3"),))
    assert _ids() == before


def test_two_conditions_behave_as_before(saved) -> None:
    saved(["", "", ""] * 3)
    store.update_annotation_pairing("protein", "A", "B", _pair(("a1", "b1"), ("a3", "b2")))
    ids = _ids()
    assert ids["a1"] == ids["b1"] and ids["a3"] == ids["b2"] and ids["a1"] != ids["a3"]
    assert ids["a2"] == "" and ids["b3"] == ""


def test_the_paired_test_names_the_samples_it_left_out(frame) -> None:
    meta = pd.DataFrame({"sample": SAMPLES, "condition": [s[0].upper() for s in SAMPLES],
                         "pair_id": ["s1", "s2", "s3", "s1", "s2", "", "s1", "s2", "s9"]})
    note = unpaired_samples_note(meta, "B", "C")
    assert note == "Paired test: 2 sample(s) without a partner left out: b3, c3."
    assert unpaired_samples_note(meta, "A", "B") == "Paired test: 2 sample(s) without a partner left out: a3, b3."
    assert unpaired_samples_note(meta.assign(pair_id=SHARED), "B", "C") is None
    _, _, result, warnings = _volcano_dataframe(
        kind="protein", condition1="B", condition2="C", identifier="gene", p_value_threshold=0.05,
        log2fc_threshold=1, test_type="paired", use_uncorrected=False, data_source="data",
        frame_override=frame, metadata_override=meta,
    )
    assert set(result.n_pairs) == {2}
    assert note in warnings
