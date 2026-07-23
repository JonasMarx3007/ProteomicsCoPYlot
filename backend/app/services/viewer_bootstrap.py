from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any, Literal

import pandas as pd

from app.schemas.annotation import (
    AnnotationFilterConfig,
    AnnotationImputationInfo,
    FilterMode,
    MetadataSource,
)
from app.services.annotation_processor import compute_annotation, compute_annotation_from_metadata
from app.services.annotation_store import save_annotation
from app.services.dataset_reader import read_dataframe
from app.services.dataset_store import save_peptide_path, save_table_dataset, set_active_package
from app.services.functions import impute_values_with_diagnostics
from app.services.metadata_upload_store import (
    create_profile as create_metadata_profile,
    save_uploaded_metadata,
    set_active_profile as set_active_metadata_profile,
)
from app.services.session_context import get_session_id, session_isolation_enabled

DatasetKind = Literal["protein", "phospho", "phosprot"]

LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
TRUTHY_VALUES = {"1", "true", "yes", "on"}
_PROJECT_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_SESSION_BOOTSTRAP_LOCK = RLock()
_SESSION_BOOTSTRAP_CONFIG: dict[str, str] = {}


@dataclass
class ViewerBootstrapResult:
    loaded_datasets: list[str] = field(default_factory=list)
    loaded_annotations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ViewerImputationConfig:
    mode: str = "none"
    q_value: float = 0.01
    adjust_std: float = 1.0
    seed: int = 1337
    sample_wise: bool = False


def bootstrap_viewer_mode_if_enabled() -> None:
    if not viewer_mode_enabled():
        return

    # With session isolation enabled, defer bootstrap to request-time middleware.
    # This keeps local/dev startup immediate while preserving per-session semantics.
    if session_isolation_enabled():
        LOGGER.info("Viewer mode startup bootstrap skipped (session isolation enabled).")
        return

    # Viewer portal mode performs project bootstrap per authenticated session.
    if _viewer_portal_enabled():
        LOGGER.info("Viewer mode started with portal auth enabled; waiting for per-session login bootstrap.")
        return

    try:
        result = bootstrap_current_viewer_session(force_reload=True)
    except Exception:
        LOGGER.exception("Failed to initialize viewer mode during startup.")
        return

    if result is None:
        LOGGER.info("Viewer mode startup skipped (no session bootstrap required).")
        return

    config_path = _resolve_config_path()
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
    package_configs = _extract_named_dataset_packages(config)
    if not package_configs:
        raise ValueError("viewer_config.json must define at least one named dataset package under 'datasets'.")

    first_package_name = next(iter(package_configs.keys()))

    for package_name, package_config in package_configs.items():
        set_active_package(package_name)

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
                config=package_config,
                key=key,
                base_dir=base_dir,
                warnings=result.warnings,
                label=f"{package_name}:{kind} file",
            )
            if absolute_path is None:
                continue

            try:
                frame = _read_table_from_path(absolute_path)
            except Exception as exc:
                result.warnings.append(
                    f"{package_name}:{kind} file read failed ({absolute_path}): {exc}"
                )
                continue
            save_table_dataset(
                filename=absolute_path.name,
                kind=kind,
                frame=frame,
                source_path=str(absolute_path),
            )
            frames[kind] = frame
            result.loaded_datasets.append(f"{package_name}:{kind}")

        peptide_path = _resolve_config_file_path(
            config=package_config,
            key="peptide_file",
            base_dir=base_dir,
            warnings=result.warnings,
            label=f"{package_name}:peptide file",
        ) or _resolve_config_file_path(
            config=package_config,
            key="peptide_path",
            base_dir=base_dir,
            warnings=result.warnings,
            label=f"{package_name}:peptide path",
        )
        if peptide_path is not None:
            try:
                resolved = peptide_path.resolve()
                save_peptide_path(str(resolved))
                result.loaded_datasets.append(f"{package_name}:peptide")
            except Exception as exc:
                result.warnings.append(
                    f"{package_name}:peptide path load failed ({peptide_path}): {exc}"
                )

        imputation_configs = {
            kind: _imputation_config(package_config, kind)
            for kind in ("protein", "phospho", "phosprot")
        }

        profile_configs = _extract_metadata_profile_configs(
            package_config,
            warnings=result.warnings,
            package_name=package_name,
        )
        first_loaded_profile: str | None = None
        first_declared_profile: str | None = None

        for profile_name, profile_config in profile_configs.items():
            if first_declared_profile is None:
                first_declared_profile = profile_name
            try:
                create_metadata_profile(profile_name, package_name=package_name)
            except ValueError:
                # Profile already exists in this package; continue.
                pass
            except Exception as exc:
                result.warnings.append(
                    f"{package_name}:{profile_name} metadata profile create failed: {exc}"
                )

            protein_metadata = _load_metadata(
                profile_config,
                "meta_file",
                base_dir,
                result.warnings,
                package_name=package_name,
                profile_name=profile_name,
            )
            phospho_metadata = _load_metadata(
                profile_config,
                "meta_phospho_file",
                base_dir,
                result.warnings,
                package_name=package_name,
                profile_name=profile_name,
            )

            if protein_metadata is None and phospho_metadata is None:
                continue

            if first_loaded_profile is None:
                first_loaded_profile = profile_name

            if protein_metadata is not None:
                save_uploaded_metadata(
                    "protein",
                    _config_filename(profile_config, "meta_file", fallback=f"{profile_name}_meta_file"),
                    protein_metadata,
                    package_name=package_name,
                    profile_name=profile_name,
                )
            if phospho_metadata is not None:
                save_uploaded_metadata(
                    "phospho",
                    _config_filename(
                        profile_config,
                        "meta_phospho_file",
                        fallback=f"{profile_name}_meta_phospho_file",
                    ),
                    phospho_metadata,
                    package_name=package_name,
                    profile_name=profile_name,
                )

            if frames["protein"] is not None and protein_metadata is not None:
                _bootstrap_annotation(
                    package_name=package_name,
                    kind="protein",
                    frame=frames["protein"],
                    metadata=protein_metadata,
                    filter_config=_filter_config(package_config, "protein"),
                    is_log2_transformed=_log2_flag(package_config, "protein"),
                    metadata_source_with_metadata="uploaded",
                    metadata_profile_name=profile_name,
                    imputation_config=imputation_configs["protein"],
                    result=result,
                )

            if frames["phospho"] is not None and phospho_metadata is not None:
                _bootstrap_annotation(
                    package_name=package_name,
                    kind="phospho",
                    frame=frames["phospho"],
                    metadata=phospho_metadata,
                    filter_config=_filter_config(package_config, "phospho"),
                    is_log2_transformed=_log2_flag(package_config, "phospho"),
                    metadata_source_with_metadata="uploaded",
                    metadata_profile_name=profile_name,
                    imputation_config=imputation_configs["phospho"],
                    result=result,
                )

            if frames["phosprot"] is not None and phospho_metadata is not None:
                _bootstrap_annotation(
                    package_name=package_name,
                    kind="phosprot",
                    frame=frames["phosprot"],
                    metadata=phospho_metadata,
                    filter_config=_filter_config(package_config, "phosphoprotein"),
                    is_log2_transformed=_log2_flag(package_config, "phosphoprotein"),
                    metadata_source_with_metadata="shared_phospho",
                    metadata_profile_name=profile_name,
                    imputation_config=imputation_configs["phosprot"],
                    result=result,
                )

        preferred_profile = first_loaded_profile or first_declared_profile
        if preferred_profile is not None:
            set_active_metadata_profile(preferred_profile, package_name=package_name)

    set_active_package(first_package_name)

    return result


def _bootstrap_annotation(
    *,
    package_name: str,
    kind: DatasetKind,
    frame: pd.DataFrame,
    metadata: pd.DataFrame | None,
    filter_config: AnnotationFilterConfig,
    is_log2_transformed: bool,
    metadata_source_with_metadata: MetadataSource,
    metadata_profile_name: str | None,
    imputation_config: ViewerImputationConfig,
    result: ViewerBootstrapResult,
) -> None:
    try:
        source_frame = frame
        imputation_info = (
            _viewer_imputation_info(
                frame=frame,
                metadata=metadata,
                config=imputation_config,
            )
            if metadata is not None
            else AnnotationImputationInfo(mode="none", applied=False)
        )

        if metadata is not None:
            computed = compute_annotation_from_metadata(
                data=source_frame,
                metadata=metadata,
                is_log2_transformed=is_log2_transformed,
                min_present=filter_config.minPresent,
                filter_mode=filter_config.mode,
            )
            metadata_source = metadata_source_with_metadata
        else:
            computed = compute_annotation(
                data=source_frame,
                conditions=[],
                is_log2_transformed=is_log2_transformed,
                min_present=filter_config.minPresent,
                filter_mode=filter_config.mode,
            )
            metadata_source = "auto" if computed.auto_detected else "manual"

        warnings = list(computed.warnings)
        if imputation_info.mode != "none":
            warnings.append(
                "Viewer imputation configured for selectable statistics only; "
                "original data is retained for completeness, QC, and missing-value plots "
                f"(mode={imputation_info.mode}, qValue={imputation_info.qValue}, "
                f"adjustStd={imputation_info.adjustStd}, seed={imputation_info.seed}, "
                f"sampleWise={imputation_info.sampleWise}, samples={imputation_info.sampleCount}, "
                f"missing={imputation_info.missingBefore}->{imputation_info.missingAfter})."
            )
        else:
            warnings.append("Viewer imputation: none.")

        save_annotation(
            kind=kind,
            source_data=source_frame,
            metadata=computed.metadata,
            log2_data=computed.log2_data,
            filtered_data=computed.filtered_data,
            is_log2_transformed=computed.is_log2_transformed,
            metadata_source=metadata_source,
            filter_config=filter_config,
            auto_detected=computed.auto_detected,
            warnings=warnings,
            log2_auto_detected=computed.log2_auto_detected,
            imputation=imputation_info,
            package_name=package_name,
            metadata_profile_name=metadata_profile_name,
        )
        profile_suffix = (
            f":{metadata_profile_name}" if str(metadata_profile_name or "").strip() else ""
        )
        result.loaded_annotations.append(f"{package_name}:{kind}{profile_suffix}")
    except Exception as exc:
        profile_suffix = (
            f":{metadata_profile_name}" if str(metadata_profile_name or "").strip() else ""
        )
        result.warnings.append(
            f"{package_name}:{kind}{profile_suffix} annotation bootstrap failed: {exc}"
        )


def _extract_named_dataset_packages(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = config.get("datasets")
    if not isinstance(raw, dict):
        raise ValueError(
            "viewer_config.json must define a 'datasets' object. "
            "Example: {\"datasets\": {\"DatasetA\": { ... }, \"DatasetB\": { ... }}}"
        )

    out: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        name = str(key or "").strip()
        if not name:
            continue
        if not isinstance(value, dict):
            raise ValueError(f"Dataset package '{name}' must map to an object of file/parameter keys.")
        out[name] = value
    return out


def _filter_config(config: dict[str, Any], suffix: str) -> AnnotationFilterConfig:
    min_present = _config_int(config, f"filter_min_{suffix}", 0)
    mode_raw = _config_string(config, f"filter_mode_{suffix}")
    mode = _normalize_filter_mode(mode_raw)
    return AnnotationFilterConfig(minPresent=min_present, mode=mode)


def _imputation_config(config: dict[str, Any], kind: DatasetKind) -> ViewerImputationConfig:
    raw = config.get("imputation")
    if raw is None:
        return ViewerImputationConfig()

    entry: Any = raw
    if isinstance(raw, dict):
        kind_entry = raw.get(kind)
        if kind_entry is not None:
            entry = kind_entry

    if isinstance(entry, str):
        return ViewerImputationConfig(mode=_normalize_imputation_mode(entry))

    if not isinstance(entry, dict):
        return ViewerImputationConfig()

    mode = _normalize_imputation_mode(str(entry.get("mode", "none")))
    q_value = _float_from_any(
        entry.get(
            "q_value",
            entry.get("qValue", entry.get("q", entry.get("shift", 0.01))),
        ),
        default=0.01,
    )
    adjust_std = _float_from_any(
        entry.get(
            "adjust_std",
            entry.get(
                "adjustStd",
                entry.get(
                    "adj_std",
                    entry.get("variance_modification", entry.get("varianceModification", 1.0)),
                ),
            ),
        ),
        default=1.0,
    )
    seed = _int_from_any(entry.get("seed", 1337), default=1337)
    sample_wise = _bool_from_any(entry.get("sample_wise", entry.get("sampleWise", False)))

    return ViewerImputationConfig(
        mode=mode,
        q_value=q_value,
        adjust_std=adjust_std,
        seed=seed,
        sample_wise=sample_wise,
    )


def _viewer_imputation_info(
    *,
    frame: pd.DataFrame,
    metadata: pd.DataFrame,
    config: ViewerImputationConfig,
) -> AnnotationImputationInfo:
    if config.mode == "none":
        return AnnotationImputationInfo(mode="none", applied=False)

    metadata_samples = (
        metadata.get("sample", pd.Series([], dtype="object"))
        .dropna()
        .astype(str)
        .tolist()
    )
    sample_columns = [sample for sample in metadata_samples if sample in frame.columns]
    # Preserve metadata sample order while removing duplicates.
    sample_columns = list(dict.fromkeys(sample_columns))
    if not sample_columns:
        return AnnotationImputationInfo(
            mode=config.mode,
            applied=False,
            qValue=config.q_value,
            adjustStd=config.adjust_std,
            seed=config.seed,
            sampleWise=config.sample_wise,
            sampleCount=0,
        )

    diagnostics = impute_values_with_diagnostics(
        data=frame,
        sample_columns=sample_columns,
        q=config.q_value,
        adj_std=config.adjust_std,
        seed=config.seed,
        sample_wise=config.sample_wise,
    )
    return AnnotationImputationInfo(
        mode=config.mode,
        applied=False,
        qValue=config.q_value,
        adjustStd=config.adjust_std,
        seed=config.seed,
        sampleWise=config.sample_wise,
        sampleCount=len(sample_columns),
        missingBefore=diagnostics.missing_before,
        missingAfter=diagnostics.missing_after,
    )


def _extract_metadata_profile_configs(
    config: dict[str, Any],
    *,
    warnings: list[str],
    package_name: str,
) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}

    # Backward-compatible single-profile config keys.
    if "meta_file" in config or "meta_phospho_file" in config:
        profiles["Metadata"] = {
            "meta_file": config.get("meta_file", ""),
            "meta_phospho_file": config.get("meta_phospho_file", ""),
        }

    raw_profiles = config.get("metadata_profiles")
    if raw_profiles is None:
        return profiles
    if not isinstance(raw_profiles, dict):
        warnings.append(
            f"{package_name}:metadata_profiles must be an object; ignoring invalid value."
        )
        return profiles

    for raw_name, raw_value in raw_profiles.items():
        profile_name = str(raw_name or "").strip()
        if not profile_name:
            continue

        if isinstance(raw_value, str):
            # Shorthand: protein metadata only.
            profiles[profile_name] = {
                "meta_file": raw_value,
                "meta_phospho_file": "none",
            }
            continue

        if isinstance(raw_value, dict):
            profiles[profile_name] = {
                "meta_file": raw_value.get("meta_file", ""),
                "meta_phospho_file": raw_value.get("meta_phospho_file", ""),
            }
            continue

        warnings.append(
            f"{package_name}:{profile_name} metadata profile must be a string or object; ignoring."
        )

    return profiles


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


def _normalize_imputation_mode(raw: str) -> str:
    value = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if value in {"", "none", "off", "disabled", "false", "0"}:
        return "none"
    if value in {"normal", "gaussian", "left_shifted_normal"}:
        return "normal"
    return value


def _viewer_mode_enabled() -> bool:
    raw = os.getenv("COPYLOT_VIEWER_MODE", "").strip().lower()
    return raw in TRUTHY_VALUES


def viewer_mode_enabled() -> bool:
    return _viewer_mode_enabled()


def _viewer_portal_enabled() -> bool:
    if not viewer_mode_enabled():
        return False
    return str(os.getenv("COPYLOT_VIEWER_PORTAL_ENABLED", "")).strip().lower() in TRUTHY_VALUES


def _resolve_config_path() -> Path:
    raw_path = os.getenv("COPYLOT_VIEWER_CONFIG", "").strip()
    if not raw_path:
        project_name = _viewer_project_name_from_env()
        if project_name:
            candidate = _default_project_viewer_config_path(project_name)
            if candidate is not None:
                return candidate
        return _default_viewer_config_path()
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def bootstrap_current_viewer_session(*, force_reload: bool = False) -> ViewerBootstrapResult | None:
    if not viewer_mode_enabled():
        return None

    config_path = _resolve_config_path()
    if not config_path.exists():
        raise FileNotFoundError(f"Viewer config file was not found: {config_path}")

    session_id = get_session_id()
    config_key = str(config_path.resolve())
    if not force_reload:
        with _SESSION_BOOTSTRAP_LOCK:
            if _SESSION_BOOTSTRAP_CONFIG.get(session_id) == config_key:
                return None

    result = load_viewer_state(config_path)
    with _SESSION_BOOTSTRAP_LOCK:
        _SESSION_BOOTSTRAP_CONFIG[session_id] = config_key
    return result


def _default_viewer_config_path() -> Path:
    for local_override in (
        PROJECT_ROOT / "local" / "viewer_config.local.json",
        PROJECT_ROOT / "viewer_config.local.json",
    ):
        if local_override.is_file():
            return local_override
    return PROJECT_ROOT / "viewer_config.json"


def _viewer_project_name_from_env() -> str:
    raw = str(os.getenv("COPYLOT_VIEWER_PROJECT", "")).strip()
    if not raw:
        return ""
    if _PROJECT_NAME_RE.fullmatch(raw):
        return raw
    return ""


def _project_viewer_config_candidates(project_name: str) -> list[Path]:
    return [
        PROJECT_ROOT / "viewer_data" / "local" / project_name / "viewer_config.local.json",
        PROJECT_ROOT / "viewer_data" / "local" / project_name / "viewer_config.json",
        PROJECT_ROOT / "viewer_data" / project_name / "viewer_config.local.json",
        PROJECT_ROOT / "viewer_data" / project_name / "viewer_config.json",
        PROJECT_ROOT / "viewer_data" / "projects" / project_name / "viewer_config.local.json",
        PROJECT_ROOT / "viewer_data" / "projects" / project_name / "viewer_config.json",
    ]


def resolve_viewer_project_config(project_name: str) -> Path | None:
    name = str(project_name or "").strip()
    if not _PROJECT_NAME_RE.fullmatch(name):
        return None
    for candidate in _project_viewer_config_candidates(name):
        if candidate.is_file():
            return candidate
    return None


def list_viewer_projects() -> list[str]:
    roots = [
        PROJECT_ROOT / "viewer_data" / "local",
        PROJECT_ROOT / "viewer_data",
        PROJECT_ROOT / "viewer_data" / "projects",
    ]
    out: set[str] = set()
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for child in root.iterdir():
            if not child.is_dir():
                continue
            project = str(child.name).strip()
            if not _PROJECT_NAME_RE.fullmatch(project):
                continue
            if resolve_viewer_project_config(project) is not None:
                out.add(project)
    return sorted(out)


def _default_project_viewer_config_path(project_name: str) -> Path | None:
    return resolve_viewer_project_config(project_name)


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
    *,
    package_name: str,
    profile_name: str,
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
    try:
        return _read_table_from_path(path)
    except Exception as exc:
        warnings.append(
            f"{package_name}:{profile_name}:{key} metadata read failed ({path}): {exc}"
        )
        return None


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


def _float_from_any(value: Any, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", ".")
        if not text:
            return default
        try:
            return float(text)
        except ValueError:
            return default
    return default


def _int_from_any(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip().replace(",", ".")
        if not text:
            return default
        try:
            return int(float(text))
        except ValueError:
            return default
    return default


def _bool_from_any(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in TRUTHY_VALUES
    return False


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

    if raw.strip().lower() in {"none", "null", "na", "n/a", "-"}:
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
