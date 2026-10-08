"""The CV method sentence says which values the CVs were computed on.

The sentence used to say "original uploaded linear intensities before
application normalization" whatever the session had done; with median or
quantile normalization the CVs are computed on the normalized values (back-
transformed to linear), and after VSN on the unnormalized data of the same
rows. With no normalization the original wording stands.
"""
from __future__ import annotations

import pandas as pd
import pytest

from app.schemas.annotation import AnnotationFilterConfig
from app.schemas.assistant import Evidence
from app.services import ai_functions
from app.services.annotation_store import reset_all_annotations, save_annotation
from app.services.assistant_methods import cv_method_text
from app.services.assistant_narrative import answer_catalogue, assemble_answer
from app.schemas.assistant import ScientificAnswer


def test_no_normalization_keeps_the_original_sentence() -> None:
    text = cv_method_text("none")
    assert "original uploaded linear intensities before application of imputation" in text
    assert cv_method_text(None) == text


def test_a_normalization_is_named_only_when_applied() -> None:
    median = cv_method_text("median")
    assert "median-normalized values back-transformed to linear intensities, before imputation" in median
    assert "original uploaded" not in median
    vsn = cv_method_text("vsn")
    assert "unnormalized intensities of the same rows" in vsn and "VSN" in vsn


@pytest.fixture
def annotated():
    samples = ["A1", "A2", "A3", "B1", "B2", "B3"]
    frame = pd.DataFrame({"ProteinNames": [f"P{i}" for i in range(20)],
                          **{s: [20.0 + i * 0.1 + j for i in range(20)] for j, s in enumerate(samples)}})
    meta = pd.DataFrame({"sample": samples, "condition": ["A"] * 3 + ["B"] * 3})

    def install(normalization: str):
        reset_all_annotations()
        save_annotation(kind="protein", source_data=frame, metadata=meta, log2_data=frame, filtered_data=frame,
                        is_log2_transformed=True, metadata_source="manual",
                        filter_config=AnnotationFilterConfig(normalization=normalization),
                        auto_detected=False, warnings=[])

    yield install
    reset_all_annotations()


@pytest.mark.parametrize("normalization,expected", [
    ("none", "original uploaded linear intensities before application of imputation"),
    ("median", "median-normalized values back-transformed"),
])
def test_the_evidence_and_the_answer_follow_the_session(annotated, normalization, expected) -> None:
    annotated(normalization)
    text = ai_functions.qc_cov_plot("protein")["summary"]
    line = next(line for line in text.splitlines() if line.startswith("cov_formula|"))
    assert f"normalization={normalization}" in line
    evidence = [Evidence(tool="qc_cov_plot", status="available", text=text)]
    catalogue, values = answer_catalogue(evidence, "qc.cv", "Explain how the CV is calculated and on which scale")
    method = next(row for row in catalogue["methods"] if "sample standard deviation" in row["text"])
    assert expected in method["text"]
    answer = assemble_answer(ScientificAnswer(methods=[method["id"]]), catalogue, values, evidence)
    assert expected in answer
