from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from app.schemas.annotation import AnnotationFilterConfig, FilterMode, MetadataSource
from app.services.annotation_processor import compute_annotation, compute_annotation_from_metadata
from app.services.annotation_store import save_annotation
from app.services.dataset_reader import read_dataframe
from app.services.dataset_store import save_peptide_path, save_table_dataset
from app.services.metadata_upload_store import save_uploaded_metadata

DatasetKind = Literal["protein", "phospho", "phosprot"]

LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_VIEWER_CONFIG_PATH = PROJECT_ROOT / "viewer_config.json"
TRUTHY_VALUES = {"1", "true", "yes", "on"}


@dataclass
class ViewerBootstrapResult:
    loaded_datasets: list[str] = field(default_factory=list)
    loaded_annotations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def bootstrap_viewer_mode_if_enabled() -> None:
    if not _viewer_mode_enabled():
        return

    config_path = _resolve_config_path()
    if not config_path.exists():
        LOGGER.warning("Viewer mode enabled but config file was not found: %s", config_path)
        return

    try:
        result = load_viewer_state(config_path)
    except Exception:
        LOGGER.exception("Failed to initialize viewer mode from %s", config_path)
        return

    LOGGER.info(
        "Viewer mode initialized from %s (datasets: %s, annotations: %s)",
        config_path,
        ", ".join(result.loaded_datasets) if result.loaded_datasets else "none",
        ", ".join(result.loaded_annotations) if result.loaded_annotations else "none",
    )
    for warning in result.warnings:
        LOGGER.warning("Viewer bootstrap warning: %s", warning)


def load_viewer_state(config_path: Path) -> ViewerBootstrapResult:
    result = ViewerBootstrapResult()

    with config_path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)

    if not isinstance(config, dict):
        raise ValueError("viewer_config.json must contain a JSON object.")

    base_dir = config_path.parent
    frames: dict[DatasetKind, pd.DataFrame | None] = {
        "protein": None,
        "phospho": None,
        "phosprot": None,
    }

    for kind, key in (
        ("protein", "protein_file"),
        ("phospho", "phospho_file"),
        ("phosprot", "phosprot_file"),
    ):
        absolute_path = _resolve_config_file_path(
            config=config,
            key=key,
            base_dir=base_dir,
            warnings=result.warnings,
            label=f"{kind} file",
        )
        if absolute_path is None:
            continue

        frame = _read_table_from_path(absolute_path)
        save_table_dataset(filename=absolute_path.name, kind=kind, frame=frame)
        frames[kind] = frame
        result.loaded_datasets.append(kind)

    peptide_path = _resolve_config_file_path(
        config=config,
        key="peptide_file",
        base_dir=base_dir,
        warnings=result.warnings,
        label="peptide file",
    ) or _resolve_config_file_path(
        config=config,
        key="peptide_path",
        base_dir=base_dir,
        warnings=result.warnings,
        label="peptide path",
    )
    if peptide_path is not None:
        resolved = peptide_path.resolve()
        save_peptide_path(str(resolved))
        result.loaded_datasets.append("peptide")

    protein_metadata = _load_metadata(config, "meta_file", base_dir, result.warnings)
    phospho_metadata = _load_metadata(config, "meta_phospho_file", base_dir, result.warnings)

    if protein_metadata is not None:
        save_uploaded_metadata(
            "protein",
            _config_filename(config, "meta_file", fallback="meta_file"),
            protein_metadata,
        )
    if phospho_metadata is not None:
        save_uploaded_metadata(
            "phospho",
            _config_filename(config, "meta_phospho_file", fallback="meta_phospho_file"),
            phospho_metadata,
        )

    if frames["protein"] is not None:
        _bootstrap_annotation(
            kind="protein",
            frame=frames["protein"],
            metadata=protein_metadata,
            filter_config=_filter_config(config, "protein"),
            is_log2_transformed=_log2_flag(config, "protein"),
            metadata_source_with_metadata="uploaded",
            result=result,
        )

    if frames["phospho"] is not None:
        _bootstrap_annotation(
            kind="phospho",
            frame=frames["phospho"],
            metadata=phospho_metadata,
            filter_config=_filter_config(config, "phospho"),
            is_log2_transformed=_log2_flag(config, "phospho"),
            metadata_source_with_metadata="uploaded",
            result=result,
        )

    if frames["phosprot"] is not None:
        _bootstrap_annotation(
            kind="phosprot",
            frame=frames["phosprot"],
            metadata=phospho_metadata,
            filter_config=_filter_config(config, "phosphoprotein"),
            is_log2_transformed=_log2_flag(config, "phosphoprotein"),
            metadata_source_with_metadata="shared_phospho",
            result=result,
        )

    return result


def _bootstrap_annotation(
    *,
    kind: DatasetKind,
    frame: pd.DataFrame,
    metadata: pd.DataFrame | None,
    filter_config: AnnotationFilterConfig,
    is_log2_transformed: bool,
    metadata_source_with_metadata: MetadataSource,
    result: ViewerBootstrapResult,
) -> None:
    try:
        if metadata is not None:
            computed = compute_annotation_from_metadata(
                data=frame,
                metadata=metadata,
                is_log2_transformed=is_log2_transformed,
                min_present=filter_config.minPresent,
                filter_mode=filter_config.mode,
            )
            metadata_source = metadata_source_with_metadata
        else:
            computed = compute_annotation(
                data=frame,
                conditions=[],
                is_log2_transformed=is_log2_transformed,
                min_present=filter_config.minPresent,
                filter_mode=filter_config.mode,
            )
            metadata_source = "auto" if computed.auto_detected else "manual"

        save_annotation(
            kind=kind,
            source_data=frame,
            metadata=computed.metadata,
            log2_data=computed.log2_data,
            filtered_data=computed.filtered_data,
            is_log2_transformed=is_log2_transformed,
            metadata_source=metadata_source,
            filter_config=filter_config,
            auto_detected=computed.auto_detected,
            warnings=computed.warnings,
        )
        result.loaded_annotations.append(kind)
    except Exception as exc:
        result.warnings.append(f"{kind} annotation bootstrap failed: {exc}")


def _filter_config(config: dict[str, Any], suffix: str) -> AnnotationFilterConfig:
    min_present = _config_int(config, f"filter_min_{suffix}", 0)
    mode_raw = _config_string(config, f"filter_mode_{suffix}")
    mode = _normalize_filter_mode(mode_raw)
    return AnnotationFilterConfig(minPresent=min_present, mode=mode)


def _log2_flag(config: dict[str, Any], suffix: str) -> bool:
    raw = config.get(f"log2_transform_{suffix}", True)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    if isinstance(raw, str):
        return raw.strip().lower() in TRUTHY_VALUES
    return True


def _normalize_filter_mode(raw: str) -> FilterMode:
    value = raw.strip().lower().replace("-", "_").replace(" ", "_")
    if value in {"in_at_least_one_group", "inatleastonegroup"}:
        return "in_at_least_one_group"
    return "per_group"


def _viewer_mode_enabled() -> bool:
    raw = os.getenv("COPYLOT_VIEWER_MODE", "").strip().lower()
    return raw in TRUTHY_VALUES


def _resolve_config_path() -> Path:
    raw_path = os.getenv("COPYLOT_VIEWER_CONFIG", "").strip()
    if not raw_path:
        return DEFAULT_VIEWER_CONFIG_PATH
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _resolve_data_path(raw_path: str, base_dir: Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def _load_metadata(
    config: dict[str, Any],
    key: str,
    base_dir: Path,
    warnings: list[str],
) -> pd.DataFrame | None:
    path = _resolve_config_file_path(
        config=config,
        key=key,
        base_dir=base_dir,
        warnings=warnings,
        label=f"metadata file for {key}",
    )
    if path is None:
        return None
    return _read_table_from_path(path)


def _read_table_from_path(path: Path) -> pd.DataFrame:
    with path.open("rb") as handle:
        return read_dataframe(path.name, handle)


def _config_string(config: dict[str, Any], key: str) -> str:
    value = config.get(key, "")
    if not isinstance(value, str):
        return ""
    return value.strip()


def _config_filename(config: dict[str, Any], key: str, fallback: str) -> str:
    raw = _config_string(config, key)
    if not raw:
        return fallback
    return Path(raw).name or fallback


def _config_int(config: dict[str, Any], key: str, default: int) -> int:
    value = config.get(key, default)
    if isinstance(value, bool):
        return max(0, int(value))
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):
        return max(0, int(value))
    if isinstance(value, str):
        try:
            return max(0, int(float(value.replace(",", "."))))
        except ValueError:
            return max(0, default)
    return max(0, default)


def _resolve_config_file_path(
    *,
    config: dict[str, Any],
    key: str,
    base_dir: Path,
    warnings: list[str],
    label: str,
) -> Path | None:
    raw = _config_string(config, key)
    if not raw:
        return None

    path = _resolve_data_path(raw, base_dir)
    if _is_deactivated_placeholder(raw, path):
        return None

    if not path.exists():
        warnings.append(f"{label} not found: {path}")
        return None

    if not path.is_file():
        warnings.append(f"{label} is not a file: {path}")
        return None

    return path


def _is_deactivated_placeholder(raw: str, path: Path) -> bool:
    if raw.endswith(("/", "\\")):
        return True
    return path.exists() and path.is_dir()
