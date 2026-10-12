from __future__ import annotations

import json
import logging
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any, Literal, get_args

import pandas as pd

from app.schemas.annotation import (
    AnnotationFilterConfig,
    AnnotationImputationInfo,
    FilterMode,
    MetadataSource,
    NormalizationMethod,
    PhosprotAggregationMode,
    phosprot_filter_config,
)
from pydantic import ValidationError as PydanticValidationError

from app.schemas.data_tools import ImputationRunRequest
from app.services.annotation_processor import compute_annotation, compute_annotation_from_metadata
from app.services.annotation_store import save_annotation
from app.services.dataset_reader import read_dataframe
from app.services.dataset_store import save_peptide_path, save_table_dataset, set_active_package
from app.services.data_tools import require_imputable_kind, skipped_sample_warnings
from app.services.functions import choose_best_source, impute_values_with_diagnostics
from app.services.metadata_upload_store import (
    create_profile as create_metadata_profile,
    list_profiles as list_metadata_profiles,
    save_uploaded_metadata,
    set_active_profile as set_active_metadata_profile,
)
from app.services.session_context import get_session_id, session_isolation_enabled
from app.services.env_settings import TRUTHY_VALUES, env_flag

DatasetKind = Literal["protein", "phospho", "phosprot"]

LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
# How these config files spell "not provided". `phospho_file`, `meta_phospho_file`
# and the rest all use the literal string "none", so any key that reads a value
# out of a config has to treat it as absence rather than as a bad value.
NOT_PROVIDED_VALUES = {"", "none", "off", "disabled", "false", "0"}
# Must contain at least one character that is not a dot: the name is used as a
# single path segment, so a name of "." or ".." would resolve outside its own
# project directory. Names come from admin-controlled config today, but the
# containment should not depend on that staying true.
_PROJECT_NAME_RE = re.compile(r"^(?=.*[^.])[A-Za-z0-9_.-]{1,128}$")
_SESSION_BOOTSTRAP_LOCK = RLock()
_SESSION_BOOTSTRAP_CONFIG: dict[str, str] = {}


@dataclass
class ViewerBootstrapResult:
    loaded_datasets: list[str] = field(default_factory=list)
    loaded_annotations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _imputation_default(field_name: str) -> Any:
    """The tool's own default for an imputation parameter.

    Read from `ImputationRunRequest` rather than restated here, so "the standard
    setting" means the same thing in a viewer project as it does in the tool.
    These drifted before: a viewer config that named only a mode ran with
    adjustStd 1.0 and sampleWise off, while the same request from the tool used
    0.3 and on.
    """
    return ImputationRunRequest.model_fields[field_name].get_default(
        call_default_factory=True
    )


@dataclass
class ViewerImputationConfig:
    mode: str = "none"
    q_value: float = field(default_factory=lambda: _imputation_default("qValue"))
    adjust_std: float = field(default_factory=lambda: _imputation_default("adjustStd"))
    down_shift: float = field(default_factory=lambda: _imputation_default("downShift"))
    width: float = field(default_factory=lambda: _imputation_default("width"))
    seed: int = field(default_factory=lambda: _imputation_default("seed"))
    sample_wise: bool = field(default_factory=lambda: _imputation_default("sampleWise"))


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
    _validate_log2_flags(package_configs)
    _validate_metadata_requirements(package_configs, base_dir)
    _validate_processing_settings(package_configs)

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
                LOGGER.exception(
                    "Viewer dataset read failed for %s:%s at %s",
                    package_name,
                    kind,
                    absolute_path,
                )
                result.warnings.append(
                    f"{package_name}:{kind} file could not be read. Check the server log."
                )
                continue
            save_table_dataset(
                filename=absolute_path.name,
                kind=kind,
                frame=frame,
                source_path=str(absolute_path),
                # Provenance for an already-collapsed file; nothing is collapsed here.
                phosprot_aggregation=(
                    _phosprot_aggregation(package_config, result.warnings)
                    if kind == "phosprot"
                    else None
                ),
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
                LOGGER.exception(
                    "Viewer peptide path load failed for %s at %s",
                    package_name,
                    peptide_path,
                )
                result.warnings.append(
                    f"{package_name}:peptide path could not be loaded. Check the server log."
                )

        imputation_configs = {
            kind: _imputation_config(package_config, kind, result.warnings)
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
            except ValueError as exc:
                if profile_name not in list_metadata_profiles(package_name=package_name):
                    result.warnings.append(f"{package_name}:{profile_name}: {exc}")
                    continue
            except Exception as exc:
                LOGGER.exception(
                    "Viewer metadata profile creation failed for %s:%s",
                    package_name,
                    profile_name,
                )
                result.warnings.append(
                    f"{package_name}:{profile_name} metadata profile could not be created. "
                    "Check the server log."
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
                    filter_config=_filter_config(package_config, "protein", result.warnings),
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
                    filter_config=_filter_config(package_config, "phospho", result.warnings),
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
                    phosprot_aggregation=_phosprot_aggregation(package_config),
                    frame=frames["phosprot"],
                    metadata=phospho_metadata,
                    filter_config=_filter_config(package_config, "phosphoprotein", result.warnings),
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
    phosprot_aggregation: PhosprotAggregationMode | None = None,
) -> None:
    try:
        source_frame = frame

        if metadata is not None:
            computed = compute_annotation_from_metadata(
                data=source_frame,
                metadata=metadata,
                is_log2_transformed=is_log2_transformed,
                min_present=filter_config.minPresent,
                filter_mode=filter_config.mode,
                filter_method=filter_config.method,
                min_percentage=filter_config.minPercentage,
                normalization=filter_config.normalization,
            )
            metadata_source = metadata_source_with_metadata
        else:
            computed = compute_annotation(
                data=source_frame,
                conditions=[],
                is_log2_transformed=is_log2_transformed,
                min_present=filter_config.minPresent,
                filter_mode=filter_config.mode,
                filter_method=filter_config.method,
                min_percentage=filter_config.minPercentage,
                normalization=filter_config.normalization,
            )
            metadata_source = "auto" if computed.auto_detected else "manual"

        warnings = list(computed.warnings)
        imputed_data = pd.DataFrame()
        imputation_error = ""
        if metadata is not None:
            try:
                # Order matters and follows `data_tools._best_imputation_source`:
                # the kind is refused before a source is chosen, so a
                # phosphoprotein project whose filter also kept nothing is told
                # the same thing by the viewer as by the tool. A project that
                # asked for no imputation has nothing to refuse.
                if imputation_config.mode != "none":
                    require_imputable_kind(kind)
                # Same source precedence, and the same refusal to substitute
                # unfiltered data for an empty filter, that the tool's own
                # imputation route uses. This used to be an inline chain here
                # that silently fell back to log2 data when the filter kept
                # nothing, so a viewer project could show unfiltered values
                # while reporting a filter.
                _, imputation_source = choose_best_source(
                    computed.filtered_data, computed.log2_data, source_frame
                )
                imputation_info, imputed_data, imputation_notes = (
                    _viewer_imputation_result(
                        frame=imputation_source,
                        metadata=computed.metadata,
                        config=imputation_config,
                    )
                )
                warnings.extend(imputation_notes)
            except ValueError as exc:
                # These carry the tool's own user-facing explanation -- an empty
                # filter, a refused phosphoprotein imputation, too little spread
                # for a global draw. Surface the reason rather than burying it
                # in the server log; the viewer has no other way to say it.
                LOGGER.warning(
                    "Viewer imputation refused for %s:%s: %s", package_name, kind, exc
                )
                imputation_info = _unapplied_imputation_info(imputation_config)
                imputation_error = str(exc).strip() or "check the server log"
            except Exception as exc:
                LOGGER.exception(
                    "Viewer imputation generation failed for %s:%s",
                    package_name,
                    kind,
                )
                imputation_info = _unapplied_imputation_info(imputation_config)
                imputation_error = "check the server log"
        else:
            imputation_info = AnnotationImputationInfo(mode="none", applied=False)

        if imputation_info.mode != "none":
            if imputation_info.mode == "numerical":
                imputation_settings = (
                    f"downShift={imputation_info.downShift}, width={imputation_info.width}"
                )
            else:
                imputation_settings = (
                    f"qValue={imputation_info.qValue}, adjustStd={imputation_info.adjustStd}"
                )
            if imputation_info.applied and not imputed_data.empty:
                warnings.append(
                    "Viewer imputation was generated and stored for selectable statistics; "
                    "original data is retained for completeness, QC, and missing-value plots "
                    f"(mode={imputation_info.mode}, {imputation_settings}, seed={imputation_info.seed}, "
                    f"sampleWise={imputation_info.sampleWise}, samples={imputation_info.sampleCount}, "
                    f"missing={imputation_info.missingBefore}->{imputation_info.missingAfter})."
                )
            else:
                reason = imputation_error or "no matching sample columns were available"
                warnings.append(
                    "Viewer imputation was configured but was not applied: "
                    f"{reason.rstrip('.')}. Non-imputed data will not be substituted."
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
            imputed_data=imputed_data,
            package_name=package_name,
            metadata_profile_name=metadata_profile_name,
            phosprot_aggregation=phosprot_aggregation,
        )
        profile_suffix = (
            f":{metadata_profile_name}" if str(metadata_profile_name or "").strip() else ""
        )
        result.loaded_annotations.append(f"{package_name}:{kind}{profile_suffix}")
    except Exception as exc:
        LOGGER.exception(
            "Viewer annotation bootstrap failed for %s:%s:%s",
            package_name,
            kind,
            metadata_profile_name or "default",
        )
        profile_suffix = (
            f":{metadata_profile_name}" if str(metadata_profile_name or "").strip() else ""
        )
        result.warnings.append(
            f"{package_name}:{kind}{profile_suffix} annotation bootstrap failed. "
            "Check the server log."
        )


# A published project is read and processed once per configuration file and
# version; every visitor gets the result, not a fresh load. Measured on 10k x
# 100 data, a fresh load took 0.6-0.9 s and ~55 MB per visitor.
_SHARED_STORES = ("dataset", "metadata", "annotation", "condition_palette", "peptide_metadata",
                  "localization_cutoff")
_SHARED_TEMPLATES: dict[str, tuple[dict[str, Any], ViewerBootstrapResult]] = {}
_SHARED_TEMPLATE_LIMIT = 8
_SHARED_TEMPLATE_LOCK = RLock()


def _shared_template_key(config_path: Path) -> str:
    try:
        stamp = config_path.stat().st_mtime_ns
    except OSError:
        stamp = 0
    return f"{config_path.resolve()}@{stamp}"


def _session_copy(snapshot: Any) -> Any:
    """A session's own copy of a loaded project; the matrices themselves are shared.

    pandas >= 3 always copies on write, so a shallow frame copy keeps every
    session's changes to itself while the values are stored once. Older pandas
    has no copy-on-write, so there each session gets deep frame copies: the
    project is still read and parsed only once.
    """
    import copy

    deep = int(pd.__version__.split(".", 1)[0]) < 3
    memo: dict[int, Any] = {}

    def collect(value: Any, depth: int = 0) -> None:
        if depth > 8 or value is None or id(value) in memo:
            return
        if isinstance(value, (pd.DataFrame, pd.Series)):
            memo[id(value)] = value.copy(deep=deep)
            return
        if isinstance(value, dict):
            for item in value.values():
                collect(item, depth + 1)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                collect(item, depth + 1)
        elif hasattr(value, "__dict__"):
            for item in vars(value).values():
                collect(item, depth + 1)

    collect(snapshot)
    return copy.deepcopy(snapshot, memo)


def load_viewer_state_shared(config_path: Path, *, force_reload: bool = False) -> ViewerBootstrapResult:
    """Copy a shared project into this session, rebuilding it on explicit refresh."""
    from app.services import restore_state
    from app.services.session_context import reset_session_id, set_session_id

    key = _shared_template_key(config_path)
    with _SHARED_TEMPLATE_LOCK:
        template = _SHARED_TEMPLATES.get(key)
        if template is None or force_reload:
            import hashlib

            template_session = "viewertemplate_" + hashlib.sha256(key.encode()).hexdigest()[:32]
            token = set_session_id(template_session)
            try:
                for store in _SHARED_STORES:
                    getattr(restore_state, f"restore_{store}_session_state")(None)
                result = load_viewer_state(config_path)
                snapshots = {store: getattr(restore_state, f"snapshot_{store}_session_state")()
                             for store in _SHARED_STORES}
            finally:
                try:
                    # Also discard partially loaded state if rebuilding fails.
                    for store in _SHARED_STORES:
                        getattr(restore_state, f"restore_{store}_session_state")(None)
                finally:
                    reset_session_id(token)
            template = (snapshots, result)
            for stale in [name for name in _SHARED_TEMPLATES if name.split("@")[0] == key.split("@")[0]]:
                _SHARED_TEMPLATES.pop(stale, None)
            while len(_SHARED_TEMPLATES) >= _SHARED_TEMPLATE_LIMIT:
                _SHARED_TEMPLATES.pop(next(iter(_SHARED_TEMPLATES)))
            _SHARED_TEMPLATES[key] = template
    snapshots, result = template
    for store in _SHARED_STORES:
        getattr(restore_state, f"restore_{store}_session_state")(_session_copy(snapshots[store]))
    return ViewerBootstrapResult(loaded_datasets=list(result.loaded_datasets),
                                 loaded_annotations=list(result.loaded_annotations),
                                 warnings=list(result.warnings))


def forget_shared_viewer_templates() -> None:
    with _SHARED_TEMPLATE_LOCK:
        _SHARED_TEMPLATES.clear()


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


def _filter_config(
    config: dict[str, Any],
    suffix: str,
    warnings: list[str] | None = None,
) -> AnnotationFilterConfig:
    """Build a filter config from the viewer config file.

    Unrecognised values fall back rather than raising, so one bad key cannot stop
    a shared project from loading. That fallback is now reported: a typo in
    `normalization` silently resolved to "none", leaving loading differences
    uncorrected for every viewer of that deployment.
    """
    min_present = _config_int(config, f"filter_min_{suffix}", 0)
    min_percentage = _float_from_any(config.get(f"filter_percentage_{suffix}", 70.0), default=70.0)
    min_percentage = min(100.0, max(0.0, min_percentage))
    method = str(config.get(f"filter_method_{suffix}", "at_least_n")).strip().lower()
    if method not in {"at_least_n", "percentage"}:
        method = "at_least_n"
    mode_raw = _config_string(config, f"filter_mode_{suffix}")
    mode = _normalize_filter_mode(mode_raw)
    # Read per-kind first, then a shared key, so protein and phosphosite datasets
    # can share a normalization setting. Phosphoprotein is the deliberate
    # exception because its phosphosite source was normalized before collapse.
    if suffix in {"phosprot", "phosphoprotein"}:
        # Phosphoprotein files are collapsed from already-normalized
        # phosphosite values and must not be normalized a second time.
        normalization = "none"
    else:
        normalization_raw = (
            _config_string(config, f"normalization_{suffix}")
            or _config_string(config, "normalization")
            or "none"
        )
        normalization = _normalize_normalization(normalization_raw)
        if warnings is not None:
            raw_text = str(normalization_raw or "").strip()
            if (
                raw_text
                and normalization == "none"
                and raw_text.lower() not in NOT_PROVIDED_VALUES
            ):
                warnings.append(
                    f"Viewer config normalization {raw_text!r} for {suffix} was not recognised; "
                    "no normalization was applied."
                )
    if warnings is not None:
        mode_text = str(mode_raw or "").strip()
        if mode_text and mode_text.lower().replace("-", "_").replace(" ", "_") not in {
            "per_group", "in_at_least_one_group", "inatleastonegroup", "overall"
        }:
            warnings.append(
                f"Viewer config filter mode {mode_text!r} for {suffix} was not recognised; "
                f"{mode} was used."
            )
    resolved = AnnotationFilterConfig(
        method=method,
        minPresent=min_present,
        minPercentage=min_percentage,
        mode=mode,
        normalization=normalization,
    )
    return (
        phosprot_filter_config(resolved)
        if suffix in {"phosprot", "phosphoprotein"}
        else resolved
    )


def _imputation_config(
    config: dict[str, Any],
    kind: DatasetKind,
    warnings: list[str] | None = None,
) -> ViewerImputationConfig:
    raw = config.get("imputation")
    if raw is None:
        return ViewerImputationConfig()

    entry: Any = raw
    if isinstance(raw, dict):
        # The filter and log2 keys of the same config spell this level
        # "phosphoprotein", so a per-level imputation override written that way
        # has to be honoured too -- it used to resolve to no imputation at all.
        for key in (kind, *(("phosphoprotein",) if kind == "phosprot" else ())):
            kind_entry = raw.get(key)
            if kind_entry is not None:
                entry = kind_entry
                break

    if isinstance(entry, str):
        return ViewerImputationConfig(mode=_normalize_imputation_mode(entry, warnings))

    if not isinstance(entry, dict):
        return ViewerImputationConfig()

    def _first_present(*keys: str) -> Any:
        """The first spelling the config actually uses, else None.

        A chained ``entry.get(a, entry.get(b, <literal>))`` evaluates its inner
        default eagerly, so when the config named none of the spellings that
        literal was returned and the tool's own default could never apply. An
        explicit value always won, then as now; what was unreachable was
        "standard". Absence is reported as None so the caller can fall back to
        `ImputationRunRequest` -- one source for what standard means.
        """
        for key in keys:
            if key not in entry:
                continue
            value = entry[key]
            # The shipped reference config writes "none" for parameters it does
            # not set, so that spelling has to mean absent -- not a bad value,
            # and not False. Only "none" and empty: "false" and "0" are real
            # answers here, unlike in a file path.
            if isinstance(value, str) and value.strip().lower() in {"", "none"}:
                continue
            return value
        return None

    mode = _normalize_imputation_mode(
        str(_first_present("method", "mode") or "none"), warnings
    )
    q_value = _float_from_any(
        _first_present("q_value", "qValue", "q", "shift"),
        default=_imputation_default("qValue"),
    )
    adjust_std = _float_from_any(
        _first_present(
            "adjust_std", "adjustStd", "adj_std",
            "variance_modification", "varianceModification",
        ),
        default=_imputation_default("adjustStd"),
    )
    down_shift = _float_from_any(
        _first_present("down_shift", "downShift"),
        default=_imputation_default("downShift"),
    )
    width = _float_from_any(_first_present("width"), default=_imputation_default("width"))
    seed = _int_from_any(_first_present("seed"), default=_imputation_default("seed"))
    sample_wise_raw = _first_present("sample_wise", "sampleWise")
    sample_wise = (
        _imputation_default("sampleWise")
        if sample_wise_raw is None
        else _bool_from_any(sample_wise_raw)
    )

    return ViewerImputationConfig(
        mode=mode,
        q_value=q_value,
        adjust_std=adjust_std,
        down_shift=down_shift,
        width=width,
        seed=seed,
        sample_wise=sample_wise,
    )


def _unapplied_imputation_info(
    config: ViewerImputationConfig,
) -> AnnotationImputationInfo:
    """Describe an imputation that was configured but did not run.

    This is the failure path, so it must not fail. `AnnotationImputationInfo`
    constrains its fields (`seed` is `ge=0`, `qValue` is a probability), and the
    config values reaching here came straight out of a JSON file without going
    through `ImputationRunRequest`. Echoing an out-of-range one back raised a
    ValidationError *inside* the except block, which escaped and took down every
    annotation in the package -- so a single mistyped `seed` cost a viewer the
    whole project rather than its imputation.
    """
    try:
        return AnnotationImputationInfo(
            mode=config.mode,
            applied=False,
            qValue=config.q_value,
            adjustStd=config.adjust_std,
            downShift=config.down_shift,
            width=config.width,
            seed=config.seed,
            sampleWise=config.sample_wise,
        )
    except PydanticValidationError:
        # The settings are unreportable, but the fact that imputation was asked
        # for and did not happen still is, and that is the part a reader needs.
        LOGGER.warning(
            "Viewer imputation settings are out of range and cannot be reported: %r",
            config,
        )
        return AnnotationImputationInfo(mode=config.mode, applied=False)


def _viewer_imputation_result(
    *,
    frame: pd.DataFrame,
    metadata: pd.DataFrame,
    config: ViewerImputationConfig,
) -> tuple[AnnotationImputationInfo, pd.DataFrame, list[str]]:
    if config.mode == "none":
        return AnnotationImputationInfo(mode="none", applied=False), pd.DataFrame(), []

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
        return (
            AnnotationImputationInfo(
                mode=config.mode,
                applied=False,
                qValue=config.q_value,
                adjustStd=config.adjust_std,
                downShift=config.down_shift,
                width=config.width,
                seed=config.seed,
                sampleWise=config.sample_wise,
                sampleCount=0,
            ),
            pd.DataFrame(),
            [],
        )

    diagnostics = impute_values_with_diagnostics(
        data=frame,
        sample_columns=sample_columns,
        q=config.q_value,
        adj_std=config.adjust_std,
        seed=config.seed,
        sample_wise=config.sample_wise,
        method=config.mode,
        down_shift=config.down_shift,
        width=config.width,
    )
    return (
        AnnotationImputationInfo(
            mode=config.mode,
            applied=True,
            qValue=config.q_value,
            adjustStd=config.adjust_std,
            downShift=config.down_shift,
            width=config.width,
            seed=config.seed,
            sampleWise=config.sample_wise,
            sampleCount=len(sample_columns),
            missingBefore=diagnostics.missing_before,
            missingAfter=diagnostics.missing_after,
        ),
        diagnostics.imputed_data,
        # The tool names the samples it could not draw for; so must the viewer,
        # or a project reports a full imputation while some values stayed missing.
        skipped_sample_warnings(diagnostics),
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


FALSY_VALUES = {"0", "false", "no", "off"}


_LOG2_FLAG_KEYS: tuple[tuple[str, str], ...] = (
    ("protein_file", "protein"),
    ("phospho_file", "phospho"),
    ("phosprot_file", "phosphoprotein"),
)


def _parse_log2_flag(raw: Any) -> bool | None:
    """true/false in any of the spellings the config files use, else None."""
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw in (0, 1):
        return bool(raw)
    if isinstance(raw, str):
        text = raw.strip().lower()
        if text in TRUTHY_VALUES:
            return True
        if text in FALSY_VALUES:
            return False
    return None


def _validate_log2_flags(package_configs: dict[str, dict[str, Any]]) -> None:
    """Every level with a file must say whether that file is already log2 transformed.

    The viewer never auto-detects the scale and does not fall back: a linear
    matrix loaded as log2 gives fold changes, CVs and tests that are
    numerically valid and wrong everywhere, so a config that leaves the
    question open is refused as a whole, before any file is read.
    """
    problems: list[str] = []
    for package_name, package_config in package_configs.items():
        for file_key, suffix in _LOG2_FLAG_KEYS:
            file_value = str(package_config.get(file_key, "") or "").strip()
            if file_value.lower() in NOT_PROVIDED_VALUES:
                continue
            key = f"log2_transform_{suffix}"
            if key not in package_config:
                problems.append(f"'{package_name}' has '{file_key}' but no '{key}'")
            elif _parse_log2_flag(package_config.get(key)) is None:
                problems.append(
                    f"'{package_name}' has an unreadable '{key}': {package_config.get(key)!r}"
                )
    if problems:
        raise ValueError(
            "viewer_config.json must state for every dataset file whether it is already log2 "
            "transformed (log2_transform_protein / log2_transform_phospho / "
            "log2_transform_phosphoprotein: true or false). " + "; ".join(problems) + "."
        )


_METADATA_REQUIREMENTS: tuple[tuple[str, str], ...] = (
    ("protein_file", "meta_file"),
    ("phospho_file", "meta_phospho_file"),
    ("phosprot_file", "meta_phospho_file"),
)


def _configured_file(config: dict[str, Any], key: str) -> str | None:
    """The configured path text, or None when the key is absent or a placeholder."""
    value = str(config.get(key, "") or "").strip()
    if not value or value.lower() in NOT_PROVIDED_VALUES or value.lower() in {"null", "na", "n/a", "-"}:
        return None
    return value


def _validate_metadata_requirements(
    package_configs: dict[str, dict[str, Any]], base_dir: Path
) -> None:
    """Every dataset file needs its metadata in every profile, and the file must exist.

    A dataset without sample metadata is not a pipeline: nothing can be
    annotated, filtered or tested, and the level would sit in the viewer as an
    unusable table. Like the log2 flag, this is refused as a whole before any
    file is read, listing every gap.
    """
    problems: list[str] = []
    for package_name, package_config in package_configs.items():
        levels = [
            (file_key, meta_key)
            for file_key, meta_key in _METADATA_REQUIREMENTS
            if _configured_file(package_config, file_key) is not None
        ]
        if not levels:
            continue
        profiles = _extract_metadata_profile_configs(package_config, warnings=[], package_name=package_name)
        if not profiles:
            problems.append(f"'{package_name}' has dataset files but no metadata (meta_file / metadata_profiles)")
            continue
        for profile_name, profile_config in profiles.items():
            for file_key, meta_key in levels:
                raw = _configured_file(profile_config, meta_key)
                if raw is None:
                    problems.append(f"'{package_name}' profile '{profile_name}' has '{file_key}' but no '{meta_key}'")
                    continue
                path = _resolve_data_path(raw, base_dir)
                if not path.is_file():
                    problems.append(
                        f"'{package_name}' profile '{profile_name}': '{meta_key}' does not exist ({raw})"
                    )
    if problems:
        raise ValueError(
            "viewer_config.json must provide sample metadata for every dataset file "
            "(meta_file for protein_file; meta_phospho_file for phospho_file and phosprot_file). "
            + "; ".join(dict.fromkeys(problems)) + "."
        )


_FILTER_LEVELS: tuple[tuple[str, str], ...] = (
    ("protein_file", "protein"),
    ("phospho_file", "phospho"),
    ("phosprot_file", "phosphoprotein"),
)
_FILTER_MODES = {"per_group", "in_at_least_one_group", "inatleastonegroup", "overall"}


def _is_absent_setting(value: Any) -> bool:
    """A missing key, or the "none" placeholder the shipped configs use for it."""
    if value is None:
        return True
    return isinstance(value, str) and value.strip().lower() in {"", "none"}


def _validate_filter_settings(package_configs: dict[str, dict[str, Any]]) -> list[str]:
    """Filtering is off unless configured; once configured, nothing is defaulted.

    A level with no `filter_*_<level>` key is unfiltered. As soon as one of
    them is present the filter is "on", and then the method, the mode and the
    method's threshold must all be stated and recognised -- a config that says
    `filter_min_protein: 3` and nothing else would otherwise run with a mode
    and a method it never chose. Normalization likewise: absent means none, a
    value must be one the tool knows.
    """
    problems: list[str] = []
    for package_name, package_config in package_configs.items():
        for file_key, suffix in _FILTER_LEVELS:
            if _configured_file(package_config, file_key) is None:
                continue
            keys = {name: f"{name}_{suffix}" for name in ("filter_min", "filter_percentage", "filter_method", "filter_mode")}
            present = {name: key for name, key in keys.items() if key in package_config}
            where = f"'{package_name}' level '{suffix}'"
            if present:
                method = package_config.get(keys["filter_method"])
                if "filter_method" not in present:
                    problems.append(f"{where}: filtering is configured but '{keys['filter_method']}' is missing (at_least_n or percentage)")
                    method = None
                else:
                    method = str(method or "").strip().lower()
                    if method not in {"at_least_n", "percentage"}:
                        problems.append(f"{where}: '{keys['filter_method']}' must be at_least_n or percentage, got {package_config.get(keys['filter_method'])!r}")
                        method = None
                if "filter_mode" not in present:
                    problems.append(f"{where}: filtering is configured but '{keys['filter_mode']}' is missing (per_group, in_at_least_one_group or overall)")
                else:
                    mode_text = str(package_config.get(keys["filter_mode"]) or "").strip().lower().replace("-", "_").replace(" ", "_")
                    if mode_text not in _FILTER_MODES:
                        problems.append(f"{where}: '{keys['filter_mode']}' must be per_group, in_at_least_one_group or overall, got {package_config.get(keys['filter_mode'])!r}")
                if method == "at_least_n":
                    value = package_config.get(keys["filter_min"])
                    if "filter_min" not in present or _is_absent_setting(value):
                        problems.append(f"{where}: method at_least_n needs '{keys['filter_min']}'")
                    elif _int_from_any(value, default=-1) < 0:
                        problems.append(f"{where}: '{keys['filter_min']}' must be a whole number >= 0, got {value!r}")
                elif method == "percentage":
                    value = package_config.get(keys["filter_percentage"])
                    if "filter_percentage" not in present or _is_absent_setting(value):
                        problems.append(f"{where}: method percentage needs '{keys['filter_percentage']}'")
                    else:
                        number = _float_from_any(value, default=-1.0)
                        if not 0.0 <= number <= 100.0:
                            problems.append(f"{where}: '{keys['filter_percentage']}' must be between 0 and 100, got {value!r}")
            if suffix != "phosphoprotein":
                for key in (f"normalization_{suffix}", "normalization"):
                    if key not in package_config:
                        continue
                    raw = package_config.get(key)
                    if _is_absent_setting(raw) or str(raw).strip().lower() in NOT_PROVIDED_VALUES:
                        continue
                    if _normalize_normalization(str(raw)) == "none":
                        problems.append(f"{where}: '{key}' {raw!r} is not a normalization the tool knows")
                    break
    return problems


_IMPUTATION_PARAMETERS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "numerical": (
        ("down_shift", ("down_shift", "downShift")),
        ("width", ("width",)),
        ("seed", ("seed",)),
        ("sample_wise", ("sample_wise", "sampleWise")),
    ),
    "quantile": (
        ("q_value", ("q_value", "qValue", "q", "shift")),
        ("adjust_std", ("adjust_std", "adjustStd", "adj_std", "variance_modification", "varianceModification")),
        ("seed", ("seed",)),
        ("sample_wise", ("sample_wise", "sampleWise")),
    ),
}


def _validate_imputation_settings(package_configs: dict[str, dict[str, Any]]) -> list[str]:
    """Imputation is off unless configured; once a mode is on, every parameter is stated.

    `imputation` absent, or its mode "none", means no imputation. A mode that
    is on (numerical or quantile, in any spelling the tool accepts) must come
    with all of that mode's parameters; a parameter written as "none" counts
    as missing. An unknown mode is refused rather than quietly meaning none.
    """
    problems: list[str] = []
    for package_name, package_config in package_configs.items():
        raw = package_config.get("imputation")
        if raw is None:
            continue
        levels = [suffix for file_key, suffix in _FILTER_LEVELS if _configured_file(package_config, file_key) is not None]
        for suffix in levels:
            kind = "phosprot" if suffix == "phosphoprotein" else suffix
            entry: Any = raw
            if isinstance(raw, dict):
                for key in (kind, *(("phosphoprotein",) if kind == "phosprot" else ())):
                    if raw.get(key) is not None:
                        entry = raw.get(key)
                        break
            where = f"'{package_name}' level '{suffix}': imputation"
            if isinstance(entry, str):
                mode_raw, params = entry, {}
            elif isinstance(entry, dict):
                params = entry
                mode_raw = next((entry[k] for k in ("method", "mode") if not _is_absent_setting(entry.get(k))), "none")
            else:
                problems.append(f"{where} must be a mode name or an object, got {type(entry).__name__}")
                continue
            if _is_absent_setting(mode_raw):
                continue
            mode = _normalize_imputation_mode(str(mode_raw))
            if mode == "none":
                if str(mode_raw).strip().lower() not in NOT_PROVIDED_VALUES:
                    problems.append(f"{where} mode {mode_raw!r} is not one the tool knows ({', '.join(sorted(imputation_methods()))})")
                continue
            for name, spellings in _IMPUTATION_PARAMETERS[mode]:
                if all(_is_absent_setting(params.get(spelling)) for spelling in spellings):
                    problems.append(f"{where} mode {mode} is on but '{name}' is not set")
                    continue
                value = next(params[s] for s in spellings if not _is_absent_setting(params.get(s)))
                field_name = {"down_shift": "downShift", "sample_wise": "sampleWise", "q_value": "qValue", "adjust_std": "adjustStd"}.get(name, name)
                if name == "sample_wise":
                    parsed = _parse_log2_flag(value)
                elif name == "seed":
                    parsed = _int_from_any(value, default=-1)
                else:
                    parsed = _float_from_any(value, default=float("nan"))
                    if isinstance(value, bool) or not math.isfinite(parsed):
                        parsed = None
                try:
                    ImputationRunRequest(kind=kind, method=mode, **{field_name: parsed})
                except PydanticValidationError:
                    problems.append(f"{where}: '{name}' has an invalid value {value!r}")
    return problems


def _validate_processing_settings(package_configs: dict[str, dict[str, Any]]) -> None:
    problems = _validate_filter_settings(package_configs) + _validate_imputation_settings(package_configs)
    if problems:
        raise ValueError(
            "viewer_config.json turns on filtering or imputation without stating its settings "
            "(absent keys mean off; once on, every setting of the chosen method must be given). "
            + "; ".join(dict.fromkeys(problems)) + "."
        )


def _log2_flag(config: dict[str, Any], suffix: str) -> bool:
    """The validated `log2_transform_<suffix>` flag (see `_validate_log2_flags`)."""
    value = _parse_log2_flag(config.get(f"log2_transform_{suffix}"))
    if value is None:
        raise ValueError(
            f"'log2_transform_{suffix}' is missing or unreadable in the viewer config."
        )
    return value


def _normalize_filter_mode(raw: str) -> FilterMode:
    value = raw.strip().lower().replace("-", "_").replace(" ", "_")
    if value in {"in_at_least_one_group", "inatleastonegroup"}:
        return "in_at_least_one_group"
    if value == "overall":
        return "overall"
    return "per_group"


def _normalize_normalization(raw: str) -> NormalizationMethod:
    """Map a viewer-config normalization value onto a supported method.

    Validated against the schema rather than a hardcoded set, and unknown values
    fall back to "none" rather than raising, so one bad key cannot stop a shared
    project from loading.
    """
    value = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if value in {"", "off", "disabled", "false", "0"}:
        return "none"
    if value in {"median_centering", "median_center", "mediancentering"}:
        return "median"
    if value in {"quantile_normalization", "quantiles"}:
        return "quantile"
    if value in set(get_args(NormalizationMethod)):
        return value  # type: ignore[return-value]
    return "none"


def imputation_methods() -> set[str]:
    """The methods the tool will actually impute with, per its own schema."""
    return set(get_args(ImputationRunRequest.model_fields["method"].annotation))


def _normalize_imputation_mode(raw: str, warnings: list[str] | None = None) -> str:
    """Map a viewer-config imputation value onto a method the tool supports.

    Unknown values fall back to "none" rather than passing through, matching how
    normalization, filter mode and collapse mode are handled here. A mode that
    passed through was stored on the annotation as if it were real, and the
    report then described an imputation that never ran.
    """
    value = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if value in NOT_PROVIDED_VALUES:
        return "none"
    if value in {"normal", "gaussian"}:
        return "quantile"
    if value in {"left_shifted_normal", "perseus", "numerical"}:
        return "numerical"
    if value in imputation_methods():
        return value
    if warnings is not None:
        warnings.append(
            f"Viewer config imputation mode {str(raw).strip()!r} was not recognised; "
            "no imputation was applied. Expected "
            + ", ".join(sorted(imputation_methods()))
            + "."
        )
    return "none"


def viewer_mode_enabled() -> bool:
    return env_flag("COPYLOT_VIEWER_MODE")


def _viewer_portal_enabled() -> bool:
    if not viewer_mode_enabled():
        return False
    return env_flag("COPYLOT_VIEWER_PORTAL_ENABLED")


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
    # The modification time is part of the key, not just the path. Keyed on the
    # path alone, a session that had already bootstrapped kept serving the
    # matrices it loaded first: an administrator could change the filter, swap a
    # data file or add a dataset in `viewer_config.json`, reload the page, and
    # be shown the previous project with nothing to say the edit had not taken.
    try:
        stamp = config_path.stat().st_mtime_ns
    except OSError:
        stamp = 0
    config_key = f"{config_path.resolve()}@{stamp}"
    if not force_reload:
        with _SESSION_BOOTSTRAP_LOCK:
            already_loaded = _SESSION_BOOTSTRAP_CONFIG.get(session_id) == config_key
        # The marker says the project was loaded; the stores say whether it still
        # is. Session cleanup (idle timeout, session cap) empties the stores, and
        # trusting the marker alone then served a returning visitor an empty project.
        if already_loaded and _session_still_loaded():
            return None

    result = load_viewer_state_shared(config_path, force_reload=force_reload)
    with _SESSION_BOOTSTRAP_LOCK:
        _SESSION_BOOTSTRAP_CONFIG[session_id] = config_key
    return result


def _session_still_loaded() -> bool:
    """True while this session's dataset store still holds a published dataset."""
    from app.services.dataset_store import session_has_datasets

    return session_has_datasets()


def forget_viewer_session_bootstrap(session_id: str | None = None) -> None:
    """Drop the "already loaded" marker of a session whose data was discarded."""
    with _SESSION_BOOTSTRAP_LOCK:
        _SESSION_BOOTSTRAP_CONFIG.pop(session_id if session_id is not None else get_session_id(), None)


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
        LOGGER.exception(
            "Viewer metadata read failed for %s:%s:%s at %s",
            package_name,
            profile_name,
            key,
            path,
        )
        warnings.append(
            f"{package_name}:{profile_name}:{key} metadata could not be read. "
            "Check the server log."
        )
        return None


def _read_table_from_path(path: Path) -> pd.DataFrame:
    with path.open("rb") as handle:
        return read_dataframe(path.name, handle)


def _phosprot_aggregation(
    config: dict[str, Any],
    warnings: list[str] | None = None,
) -> PhosprotAggregationMode | None:
    """How the phosphoprotein file being loaded was already collapsed.

    The viewer never collapses anything: it is handed a phosphoprotein matrix
    that was produced elsewhere. `collapse_mode` in the config is therefore
    provenance, not an instruction -- but it is provenance the tool needs.
    `robust_site_median` centres every site on its own across-sample median, so
    those values are ratios to that median rather than abundances, and
    `phosprot_values_are_centred` reads this to label the axes accordingly.

    Dropping it, as this loader used to, made a shared phosphoprotein project
    label ratios as "Intensity" for everyone viewing it.

    Validated against the schema rather than a hardcoded set, and an
    unrecognised value falls back to None with a warning rather than raising,
    matching how normalization and filter mode are handled here.
    """
    raw = _config_string(config, "collapse_mode")
    if not raw:
        return None
    value = raw.strip().lower().replace("-", "_").replace(" ", "_")
    # These configs spell "not provided" as the string "none" -- `phospho_file`,
    # `meta_phospho_file` and the rest all use it. A protein-only project that
    # writes `"collapse_mode": "none"` is stating there is nothing to describe,
    # so it must not be reported as a typo.
    if value in NOT_PROVIDED_VALUES:
        return None
    if value in set(get_args(PhosprotAggregationMode)):
        return value  # type: ignore[return-value]
    if warnings is not None:
        warnings.append(
            f"Viewer config collapse_mode {raw!r} was not recognised; the "
            "phosphoprotein values will be described as intensities. Expected "
            + ", ".join(sorted(get_args(PhosprotAggregationMode)))
            + "."
        )
    return None


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
        return int(value) if math.isfinite(value) and value.is_integer() else default
    if isinstance(value, str):
        text = value.strip().replace(",", ".")
        if not text:
            return default
        try:
            number = float(text)
            return int(number) if math.isfinite(number) and number.is_integer() else default
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
        LOGGER.warning("Viewer configuration path for %s was not found: %s", label, path)
        warnings.append(f"{label} was not found. Check the server log.")
        return None

    if not path.is_file():
        LOGGER.warning("Viewer configuration path for %s is not a file: %s", label, path)
        warnings.append(f"{label} is not a regular file. Check the server log.")
        return None

    return path


def _is_deactivated_placeholder(raw: str, path: Path) -> bool:
    if raw.endswith(("/", "\\")):
        return True
    return path.exists() and path.is_dir()
