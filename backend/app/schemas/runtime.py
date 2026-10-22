from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class NormalizationCapabilityResponse(BaseModel):
    """Normalization methods this installation can actually run.

    `methods` includes 'vsn' only when Rscript and the Bioconductor package are
    both present, since VSN is delegated to the reference implementation rather
    than reimplemented.
    """

    methods: list[str]
    vsnAvailable: bool
    vsnUnavailableReason: str | None = None
    vsnPackageVersion: str | None = None


class StatisticsCapabilityResponse(BaseModel):
    """Statistical tests this installation can actually run.

    `testTypes` includes the four moderated (limma) tests only when Rscript and
    the Bioconductor package are both present, as `methods` does for VSN.
    """

    testTypes: list[str]
    moderatedAvailable: bool
    moderatedUnavailableReason: str | None = None
    limmaPackageVersion: str | None = None


class RRuntimeStatusResponse(BaseModel):
    available: bool
    diagnosticsHidden: bool = False
    executable: str | None = None
    version: str | None = None
    versionOutput: str | None = None
    detectedFrom: Literal["env", "path", "common_path"] | None = None
    candidates: list[str] = Field(default_factory=list)
    error: str | None = None
