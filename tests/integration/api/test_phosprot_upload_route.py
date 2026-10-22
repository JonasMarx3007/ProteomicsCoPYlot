"""A collapsed phosphoprotein matrix can be uploaded instead of collapsed (D17, route added 2026-10-22).

The upload rides on the phospho annotation's sample sheet and filter, exactly
as `upload_phosprot` always did; the route only makes it reachable from the page.
"""
import io

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.annotation import AnnotationFilterConfig
from app.services import annotation_store
from app.services.dataset_store import get_current_dataset, reset_all_datasets


@pytest.fixture
def client():
    annotation_store.reset_all_annotations()
    reset_all_datasets()
    with TestClient(app) as test_client:
        yield test_client
    annotation_store.reset_all_annotations()
    reset_all_datasets()


def _seed_phospho_annotation():
    frame = pd.DataFrame({"Protein_group": ["P1_S10", "P2_S20"], "A": [10., 11.], "B": [12., 13.]})
    annotation_store.save_annotation(
        kind="phospho", source_data=frame, log2_data=frame, filtered_data=frame,
        metadata=pd.DataFrame({"sample": ["A", "B"], "condition": ["ctrl", "treat"]}),
        is_log2_transformed=True, metadata_source="manual", filter_config=AnnotationFilterConfig(minPresent=0),
        auto_detected=False, warnings=[],
    )


def _upload(client, text: str, **form):
    return client.post("/api/annotations/phosprot/upload",
                       files={"file": ("collapsed.csv", io.BytesIO(text.encode()), "text/csv")}, data=form)


def test_the_upload_becomes_the_phosphoprotein_annotation(client) -> None:
    _seed_phospho_annotation()
    response = _upload(client, "Protein_group,Gene_group,A,B\nP1,G1,20,22\nP2,G2,21,23\n", isLog2Transformed="true")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "phosprot"
    assert any("uploaded manually" in warning for warning in body["warnings"])
    dataset = get_current_dataset("phosprot")
    assert dataset.filename == "collapsed.csv" and dataset.phosprot_aggregation == "uploaded"
    stored = annotation_store.get_annotation("phosprot")
    assert list(stored.metadata["sample"]) == ["A", "B"], "the phospho sample sheet is inherited"
    assert stored.filtered_data["A"].tolist() == [20., 21.]


def test_the_scale_is_detected_when_not_given(client) -> None:
    _seed_phospho_annotation()
    rows = "".join(f"P{i},{1_000_000 + 7_000 * i},{1_200_000 + 9_000 * i}\n" for i in range(1, 25))
    response = _upload(client, "Protein_group,A,B\n" + rows)
    assert response.status_code == 200, response.text
    assert any("auto-detected" in warning for warning in response.json()["warnings"])
    assert annotation_store.get_annotation("phosprot").is_log2_transformed is False


def test_without_the_phospho_annotation_or_matching_samples_it_is_refused(client) -> None:
    assert _upload(client, "Protein_group,A,B\nP1,20,22\n").status_code == 400
    _seed_phospho_annotation()
    response = _upload(client, "Protein_group,X,Y\nP1,20,22\n")
    assert response.status_code == 400
    assert "sample columns" in response.json()["detail"]
    assert get_current_dataset("phosprot") is None, "a refused upload changes nothing"
