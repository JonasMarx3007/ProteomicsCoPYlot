from __future__ import annotations

import gzip
import json
from itertools import combinations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.annotation import AnnotationFilterConfig
from app.services.annotation_store import (
    list_annotation_profiles,
    reset_all_annotations,
    save_annotation,
)
from app.services.dataset_store import create_package, reset_all_datasets, set_active_package
from app.services.metadata_upload_store import (
    MAX_MANUAL_METADATA_PROFILES,
    create_profile,
    delete_profile,
    get_active_profile,
    get_uploaded_metadata,
    list_auto_generated_profiles,
    list_profiles,
    reset_all_uploaded_metadata,
    save_uploaded_metadata,
    set_active_profile,
)
from app.services.restore_state import apply_restore_state, export_state_blob


def _create_manual_profiles(package_name: str) -> list[str]:
    names = [f"Profile{i}" for i in range(1, MAX_MANUAL_METADATA_PROFILES + 1)]
    for name in names:
        create_profile(name, package_name=package_name)
    return names


def test_five_manual_profiles_generate_every_combination() -> None:
    package = "metadata-profile-limit-combinations"
    manual_profiles = _create_manual_profiles(package)

    expected_auto_profiles = {
        "-".join(source_profiles)
        for size in range(2, len(manual_profiles) + 1)
        for source_profiles in combinations(manual_profiles, size)
    }
    assert set(list_auto_generated_profiles(package_name=package)) == expected_auto_profiles
    assert len(expected_auto_profiles) == 26

    with pytest.raises(ValueError, match="at most 5 manual metadata profiles"):
        create_profile("Profile6", package_name=package)
    assert "Profile6" not in list_profiles(package_name=package)


def test_implicit_profile_creation_cannot_bypass_the_limit() -> None:
    package = "metadata-profile-limit-implicit"
    _create_manual_profiles(package)

    with pytest.raises(ValueError, match="at most 5 manual metadata profiles"):
        get_uploaded_metadata("protein", package_name=package, profile_name="Profile6")
    assert "Profile6" not in list_profiles(package_name=package)


def test_converting_an_auto_profile_to_manual_obeys_the_limit() -> None:
    package = "metadata-profile-limit-auto-conversion"
    _create_manual_profiles(package)
    frame = pd.DataFrame({"sample": ["sample1"], "condition": ["control"]})

    with pytest.raises(ValueError, match="at most 5 manual metadata profiles"):
        save_uploaded_metadata(
            "protein",
            "metadata.csv",
            frame,
            package_name=package,
            profile_name="Profile1-Profile2",
        )
    assert "Profile1-Profile2" in list_auto_generated_profiles(package_name=package)


def test_a_populated_legacy_default_counts_toward_the_limit() -> None:
    package = "metadata-profile-limit-populated-default"
    frame = pd.DataFrame({"sample": ["sample1"], "condition": ["control"]})
    save_uploaded_metadata(
        "protein",
        "metadata.csv",
        frame,
        package_name=package,
        profile_name="Metadata",
    )
    for index in range(1, MAX_MANUAL_METADATA_PROFILES):
        profile_name = f"Profile{index}"
        create_profile(profile_name, package_name=package)
        save_uploaded_metadata(
            "protein",
            f"{profile_name}.csv",
            frame,
            package_name=package,
            profile_name=profile_name,
        )

    assert len(list_auto_generated_profiles(package_name=package)) == 26
    with pytest.raises(ValueError, match="at most 5 manual metadata profiles"):
        create_profile("Profile5", package_name=package)


def test_profile_creation_api_returns_a_clear_error_for_profile_six() -> None:
    package = "metadata-profile-limit-api"
    create_package(package)
    set_active_package(package)
    try:
        with TestClient(app) as client:
            for index in range(1, MAX_MANUAL_METADATA_PROFILES + 1):
                response = client.post(
                    "/api/datasets/metadata/profiles/create",
                    json={"profileName": f"ApiProfile{index}"},
                )
                assert response.status_code == 200

            rejected = client.post(
                "/api/datasets/metadata/profiles/create",
                json={"profileName": "ApiProfile6"},
            )
        assert rejected.status_code == 400
        assert "at most 5 manual metadata profiles" in rejected.json()["detail"]
    finally:
        reset_all_uploaded_metadata()
        reset_all_datasets()


def test_five_profiles_and_all_combinations_survive_state_restore() -> None:
    package = "metadata-profile-limit-restore"
    frame = pd.DataFrame({"sample": ["sample1"], "condition": ["control"]})
    reset_all_datasets()
    reset_all_uploaded_metadata()
    try:
        create_package(package)
        set_active_package(package)
        manual_profiles = _create_manual_profiles(package)
        for profile_name in manual_profiles:
            save_uploaded_metadata(
                "protein",
                f"{profile_name}.csv",
                frame,
                package_name=package,
                profile_name=profile_name,
            )

        active_auto_profile = "-".join(manual_profiles)
        set_active_profile(active_auto_profile, package_name=package)
        payload = json.loads(gzip.decompress(export_state_blob()).decode("utf-8"))

        reset_all_datasets()
        reset_all_uploaded_metadata()
        apply_restore_state(payload, {})

        auto_profiles = set(list_auto_generated_profiles(package_name=package))
        restored_manual_profiles = {
            name
            for name in list_profiles(package_name=package)
            if name != "Metadata" and name not in auto_profiles
        }
        assert restored_manual_profiles == set(manual_profiles)
        assert len(auto_profiles) == 26
        assert get_active_profile(package_name=package) == active_auto_profile
    finally:
        reset_all_uploaded_metadata()
        reset_all_datasets()


def test_deleting_a_source_removes_dependents_and_frees_a_slot() -> None:
    package = "metadata-profile-delete-source"
    frame = pd.DataFrame({"sample": ["sample1"], "condition": ["control"]})
    for profile_name in ("Profile1", "Profile2", "Profile3"):
        create_profile(profile_name, package_name=package)
        save_uploaded_metadata(
            "protein",
            f"{profile_name}.csv",
            frame,
            package_name=package,
            profile_name=profile_name,
        )
    set_active_profile("Profile1-Profile2", package_name=package)

    deleted = delete_profile("Profile2", package_name=package)

    assert set(deleted) == {
        "Profile2",
        "Profile1-Profile2",
        "Profile2-Profile3",
        "Profile1-Profile2-Profile3",
    }
    assert set(list_auto_generated_profiles(package_name=package)) == {"Profile1-Profile3"}
    assert get_active_profile(package_name=package) == "Profile1"
    assert "Profile2" not in list_profiles(package_name=package)
    create_profile("Profile4", package_name=package)


def test_generated_profiles_cannot_be_deleted_directly() -> None:
    package = "metadata-profile-delete-generated"
    create_profile("Profile1", package_name=package)
    create_profile("Profile2", package_name=package)

    with pytest.raises(ValueError, match="generated automatically"):
        delete_profile("Profile1-Profile2", package_name=package)
    assert "Profile1-Profile2" in list_auto_generated_profiles(package_name=package)


def test_deleting_the_legacy_default_resets_but_preserves_the_fallback() -> None:
    package = "metadata-profile-delete-default"
    frame = pd.DataFrame({"sample": ["sample1"], "condition": ["control"]})
    save_uploaded_metadata(
        "protein",
        "metadata.csv",
        frame,
        package_name=package,
        profile_name="Metadata",
    )

    assert delete_profile("Metadata", package_name=package) == ["Metadata"]
    assert list_profiles(package_name=package) == ["Metadata"]
    assert get_active_profile(package_name=package) == "Metadata"
    assert get_uploaded_metadata(
        "protein", package_name=package, profile_name="Metadata"
    ) is None


def test_delete_api_removes_source_and_dependent_annotations() -> None:
    package = "metadata-profile-delete-api"
    reset_all_datasets()
    reset_all_uploaded_metadata()
    reset_all_annotations()
    try:
        create_package(package)
        set_active_package(package)
        source_data = pd.DataFrame(
            {"ProteinNames": ["P1"], "sample1": [20.0], "sample2": [21.0]}
        )
        metadata1 = pd.DataFrame(
            {"sample": ["sample1", "sample2"], "condition": ["A", "B"]}
        )
        metadata2 = pd.DataFrame(
            {"sample": ["sample1", "sample2"], "condition": ["X", "Y"]}
        )
        for profile_name, metadata in (("Profile1", metadata1), ("Profile2", metadata2)):
            create_profile(profile_name, package_name=package)
            save_uploaded_metadata(
                "protein",
                f"{profile_name}.csv",
                metadata,
                package_name=package,
                profile_name=profile_name,
            )
            save_annotation(
                kind="protein",
                source_data=source_data,
                metadata=metadata,
                log2_data=source_data,
                filtered_data=source_data,
                is_log2_transformed=True,
                metadata_source="uploaded",
                filter_config=AnnotationFilterConfig(),
                auto_detected=False,
                warnings=[],
                package_name=package,
                metadata_profile_name=profile_name,
            )
        combined = get_uploaded_metadata(
            "protein",
            package_name=package,
            profile_name="Profile1-Profile2",
        )
        assert combined is not None
        save_annotation(
            kind="protein",
            source_data=source_data,
            metadata=combined.frame,
            log2_data=source_data,
            filtered_data=source_data,
            is_log2_transformed=True,
            metadata_source="uploaded",
            filter_config=AnnotationFilterConfig(),
            auto_detected=False,
            warnings=[],
            package_name=package,
            metadata_profile_name="Profile1-Profile2",
        )
        set_active_profile("Profile1-Profile2", package_name=package)

        with TestClient(app) as client:
            response = client.request(
                "DELETE",
                "/api/datasets/metadata/profiles/delete",
                json={"profileName": "Profile1"},
            )

        assert response.status_code == 200, response.text
        assert response.json()["activeMetadataProfile"] == "Profile2"
        assert response.json()["autoGeneratedMetadataProfiles"] == []
        annotation_profiles = list_annotation_profiles(
            package_name=package,
            include_empty=True,
        )
        assert "Profile1" not in annotation_profiles
        assert "Profile1-Profile2" not in annotation_profiles
        assert "Profile2" in annotation_profiles
    finally:
        reset_all_annotations()
        reset_all_uploaded_metadata()
        reset_all_datasets()
