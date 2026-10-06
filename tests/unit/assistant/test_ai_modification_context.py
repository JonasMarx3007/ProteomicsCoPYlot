from __future__ import annotations

import numpy as np
import pandas as pd

from app.services import ai_functions, peptide_tools


SEQUENCES = [
    "PEP[UniMod:4]TIDE",
    "PEP[UniMod:40]TIDE",
    "PEP[UNIMOD:400]TIDE",
    "PEP[Carbamidomethylation]TIDE",
    "PEP[unimod:35]TIDE",
    "PEP[UniMod:350]TIDE",
    "PEP[UniMod:1][UniMod:35]TIDE",
    "PEP[UniMod:10]TIDE",
    "PEP[Deacetylation]TIDE",
]


def test_shared_modification_classifier_is_boundary_safe_and_scale_aware() -> None:
    frame = pd.DataFrame(
        {
            "Modified.Sequence": SEQUENCES,
            "sample_a": [1, 1, 1, 1, 1, 1, 1, 1, 1],
            "sample_b": [0, 1, 1, np.inf, 1, 1, 1, 1, 1],
        }
    )

    counts = peptide_tools.peptide_modification_counts(
        frame,
        sequence_column="Modified.Sequence",
        sample_columns=["sample_a", "sample_b"],
    )

    assert counts.loc["sample_a"].to_dict() == {
        "Carbamidomethylation": 2,
        "Oxidation": 2,
        "Acetylation": 1,
        "UniqueTrackedModifiedPeptides": 4,
    }
    assert counts.loc["sample_b", "Carbamidomethylation"] == 0
    assert counts.loc["sample_b", "Oxidation"] == 2
    assert counts.loc["sample_b", "Acetylation"] == 1
    assert counts.loc["sample_b", "UniqueTrackedModifiedPeptides"] == 2


def test_shared_modification_classifier_counts_duplicate_sequences_once() -> None:
    frame = pd.DataFrame(
        {
            "Modified.Sequence": ["PEP[UniMod:4]TIDE", "PEP[UniMod:4]TIDE"],
            "sample_a": [1.0, 2.0],
        }
    )

    counts = peptide_tools.peptide_modification_counts(
        frame,
        sequence_column="Modified.Sequence",
        sample_columns=["sample_a"],
    )

    assert counts.loc["sample_a", "Carbamidomethylation"] == 1
    assert counts.loc["sample_a", "UniqueTrackedModifiedPeptides"] == 1


def test_ai_modification_context_uses_shared_counts_and_correct_scientific_terms(monkeypatch) -> None:
    frame = pd.DataFrame(
        {
            "File.Name": ["sample_1.raw"] * len(SEQUENCES),
            "Modified.Sequence": SEQUENCES,
            "Precursor.Quantity": [1.0] * len(SEQUENCES),
        }
    )
    metadata = pd.DataFrame(
        {"sample": ["sample_1.raw"], "id": ["1"], "label": ["control_1"], "condition": ["control"]}
    )
    monkeypatch.setattr(ai_functions, "get_peptide_frame", lambda: frame.copy())
    monkeypatch.setattr(
        ai_functions._plot_images,
        "_peptide_coverage_metadata",
        lambda source, include_id: metadata.copy(),
    )

    text = ai_functions.peptide_modification_plot()["data"]["text"]

    assert "Carbamidomethylation" in text
    assert "Carbamylation" not in text
    assert "carbamylation=" not in text
    assert "carbamidomethylation=2" in text
    assert "oxidation=2" in text
    assert "acetylation=1" in text
    assert "class_assignment_total=5" in text
    assert "unique_tracked_modified_peptides=4" in text
    assert "UniMod:4_does_not_match_UniMod:40_or_UniMod:400" in text


def test_ai_does_not_duplicate_unimod_matching_logic(monkeypatch) -> None:
    """The AI context reports whatever the shared classifier counts.

    The shared counter is wrapped so that its answer carries a marker (1000
    extra carbamidomethylated peptides on every sample). If the context reports
    the marked totals, it took its numbers from the shared classifier; a second
    copy of the UniMod matching inside the AI code would report the unmarked
    count instead, and would also leave the wrapper uncalled.
    """
    frame = pd.DataFrame(
        {
            "File.Name": ["sample_1.raw"] * len(SEQUENCES),
            "Modified.Sequence": SEQUENCES,
            "Precursor.Quantity": [1.0] * len(SEQUENCES),
        }
    )
    metadata = pd.DataFrame(
        {"sample": ["sample_1.raw"], "id": ["1"], "label": ["control_1"], "condition": ["control"]}
    )
    monkeypatch.setattr(ai_functions, "get_peptide_frame", lambda: frame.copy())
    monkeypatch.setattr(
        ai_functions._plot_images,
        "_peptide_coverage_metadata",
        lambda source, include_id: metadata.copy(),
    )

    real_counts = peptide_tools.peptide_modification_counts
    calls: list[int] = []

    def marked_counts(*args, **kwargs):
        calls.append(1)
        counts = real_counts(*args, **kwargs).copy()
        counts["Carbamidomethylation"] = counts["Carbamidomethylation"] + 1000
        return counts

    monkeypatch.setattr(peptide_tools, "peptide_modification_counts", marked_counts)
    # The AI module imports the shared counter under a private alias; that alias
    # is redirected only when it really is the shared function, so a local copy
    # of the logic under the same name is not silently replaced by the wrapper.
    if getattr(ai_functions, "_peptide_modification_counts", None) is real_counts:
        monkeypatch.setattr(ai_functions, "_peptide_modification_counts", marked_counts)

    text = ai_functions.peptide_modification_plot()["data"]["text"]

    assert calls, "the AI context never asked the shared classifier"
    assert "carbamidomethylation=1002" in text
    assert "class_assignment_total=1005" in text


def test_shared_missed_cleavage_summary_uses_protease_and_detection_contract() -> None:
    frame = pd.DataFrame(
        {
            "Stripped.Sequence": ["AKPQR", "AKPQR", "ARPK", "AKQR"],
            "sample_a": [1.0, 2.0, np.inf, 0.0],
        }
    )

    trypsin = peptide_tools.peptide_missed_cleavage_summary(
        frame,
        sequence_column="Stripped.Sequence",
        sample_columns=["sample_a"],
        protease="trypsin",
    )
    trypsin_lysc = peptide_tools.peptide_missed_cleavage_summary(
        frame,
        sequence_column="Stripped.Sequence",
        sample_columns=["sample_a"],
        protease="trypsin_lysc",
    )

    assert trypsin[["Count", "Occurrences"]].to_dict("records") == [
        {"Count": 0, "Occurrences": 1}
    ]
    assert trypsin_lysc[["Count", "Occurrences"]].to_dict("records") == [
        {"Count": 1, "Occurrences": 1}
    ]


def test_ai_missed_cleavage_context_uses_selected_backend_rule(monkeypatch) -> None:
    frame = pd.DataFrame(
        {
            "File.Name": ["sample_1.raw"] * 3,
            "Stripped.Sequence": ["AKPQR", "ARPK", "AKQR"],
            "Precursor.Quantity": [1.0, 1.0, 1.0],
        }
    )
    metadata = pd.DataFrame(
        {"sample": ["sample_1.raw"], "id": ["1"], "label": ["control_1"], "condition": ["control"]}
    )
    monkeypatch.setattr(ai_functions, "get_peptide_frame", lambda: frame.copy())
    monkeypatch.setattr(
        ai_functions._plot_images,
        "_peptide_coverage_metadata",
        lambda source, include_id: metadata.copy(),
    )

    text = ai_functions.peptide_missed_cleavage_plot(
        mode={"protease": "trypsin_lysc"}
    )["data"]["text"]

    assert "protease=trypsin_lysc" in text
    assert "protease_label=Trypsin / Lys-C" in text
    assert "trypsin_lysc_cleaves_KP_but_still_blocks_RP" in text
    assert "distribution_percent=0:33.33;1:66.67" in text
