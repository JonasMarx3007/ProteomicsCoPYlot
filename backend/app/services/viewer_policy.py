"""Explicit viewer permissions. New API operations are denied until reviewed.

Entries name complete route templates, never URL prefixes. Keep data/figure
exports, session selections and reviewed analysis POSTs available; processing,
notebook exports and model management are intentionally absent.
"""
from starlette.routing import compile_path


VIEWER_ALLOWED_OPERATIONS = frozenset({
    ('POST', '/api/analysis/volcano/data'),
    ('GET', '/api/annotations/current/{kind}'),
    ('GET', '/api/annotations/current/{kind}/filtered/download'),
    ('GET', '/api/annotations/current/{kind}/metadata/download'),
    ('GET', '/api/annotations/current/{kind}/source/download'),
    ('POST', '/api/annotations/log2-detect'),
    ('GET', '/api/annotations/metadata/current/{kind}'),
    ('POST', '/api/chat/assistant'),
    ('GET', '/api/chat/assistant-progress/{progress_id}'),
    ('GET', '/api/chat/cloud-consent/{provider}'),
    ('POST', '/api/chat/cloud-consent/{provider}/grant'),
    ('POST', '/api/chat/cloud-consent/{provider}/revoke'),
    ('GET', '/api/chat/gpu-status'),
    ('POST', '/api/chat/local-models'),
    ('GET', '/api/chat/model-capability'),
    ('GET', '/api/chat/models'),
    ('GET', '/api/chat/provider-defaults'),
    ('GET', '/api/data-tools/completeness/{kind}/tables'),
    ('GET', '/api/data-tools/condition-colors/{kind}'),
    ('GET', '/api/data-tools/distribution/{kind}'),
    ('GET', '/api/data-tools/phospho-localization-cutoff'),
    ('POST', '/api/data-tools/phospho-localization-cutoff'),
    ('POST', '/api/datasets/active'),
    ('GET', '/api/datasets/current'),
    ('POST', '/api/datasets/metadata/profiles/active'),
    ('GET', '/api/health'),
    ('GET', '/api/peptide/metadata/current'),
    ('GET', '/api/peptide/overview'),
    ('GET', '/api/peptide/quantity-options'),
    ('GET', '/api/peptide/sequence-coverage'),
    ('GET', '/api/plots/comparison/{kind}/options'),
    ('GET', '/api/plots/comparison/{kind}/pearson-table'),
    ('GET', '/api/plots/comparison/{kind}/pearson.html'),
    ('GET', '/api/plots/comparison/{kind}/pearson.png'),
    ('GET', '/api/plots/comparison/{kind}/venn-table'),
    ('GET', '/api/plots/comparison/{kind}/venn.png'),
    ('GET', '/api/plots/completeness/{kind}/missing-heatmap.png'),
    ('GET', '/api/plots/completeness/{kind}/missing-value.png'),
    ('GET', '/api/plots/distribution/{kind}/qqnorm.png'),
    ('GET', '/api/plots/imputation/{kind}/after-imputation.png'),
    ('GET', '/api/plots/imputation/{kind}/before-missing.png'),
    ('GET', '/api/plots/imputation/{kind}/overall-fit.png'),
    ('GET', '/api/plots/peptide/missed-cleavage.png'),
    ('GET', '/api/plots/peptide/modification.png'),
    ('GET', '/api/plots/peptide/rt-interactive.html'),
    ('GET', '/api/plots/peptide/rt.png'),
    ('GET', '/api/plots/phospho/coverage-table'),
    ('GET', '/api/plots/phospho/coverage.png'),
    ('GET', '/api/plots/phospho/distribution-table'),
    ('GET', '/api/plots/phospho/distribution.png'),
    ('GET', '/api/plots/phospho/ksea-table'),
    ('POST', '/api/plots/phospho/ksea-volcano.html'),
    ('GET', '/api/plots/phospho/options'),
    ('GET', '/api/plots/phospho/phosphosite-plot-table'),
    ('GET', '/api/plots/phospho/phosphosite-plot.png'),
    ('GET', '/api/plots/phospho/phosprot-regulation-table'),
    ('GET', '/api/plots/phospho/phosprot-regulation.html'),
    ('GET', '/api/plots/phospho/sty-table'),
    ('GET', '/api/plots/phospho/sty.png'),
    ('GET', '/api/plots/qc/{kind}/abundance-interactive.html'),
    ('GET', '/api/plots/qc/{kind}/abundance.png'),
    ('GET', '/api/plots/qc/{kind}/boxplot-table'),
    ('GET', '/api/plots/qc/{kind}/boxplot.png'),
    ('GET', '/api/plots/qc/{kind}/correlation.png'),
    ('GET', '/api/plots/qc/{kind}/coverage-table'),
    ('GET', '/api/plots/qc/{kind}/coverage.png'),
    ('GET', '/api/plots/qc/{kind}/cv-table'),
    ('GET', '/api/plots/qc/{kind}/cv.png'),
    ('GET', '/api/plots/qc/{kind}/intensity-histogram.png'),
    ('GET', '/api/plots/qc/{kind}/options'),
    ('GET', '/api/plots/qc/{kind}/pca-features'),
    ('GET', '/api/plots/qc/{kind}/pca-interactive.html'),
    ('GET', '/api/plots/qc/{kind}/pca.png'),
    ('GET', '/api/plots/single-protein/{kind}/boxplot-table'),
    ('GET', '/api/plots/single-protein/{kind}/boxplot.png'),
    ('GET', '/api/plots/single-protein/{kind}/heatmap-table'),
    ('GET', '/api/plots/single-protein/{kind}/heatmap.png'),
    ('GET', '/api/plots/single-protein/{kind}/lineplot-table'),
    ('GET', '/api/plots/single-protein/{kind}/lineplot-unmatched'),
    ('GET', '/api/plots/single-protein/{kind}/lineplot.png'),
    ('GET', '/api/plots/single-protein/{kind}/options'),
    ('GET', '/api/plots/stats/{kind}/anova-tables'),
    ('GET', '/api/plots/stats/{kind}/anova.png'),
    ('GET', '/api/plots/stats/{kind}/ora/{direction}.png'),
    ('GET', '/api/plots/stats/{kind}/ora/{direction}/tables'),
    ('GET', '/api/plots/stats/{kind}/pathway-heatmap.png'),
    ('GET', '/api/plots/stats/{kind}/simulation.html'),
    ('GET', '/api/plots/stats/{kind}/volcano-control.html'),
    ('GET', '/api/plots/stats/{kind}/volcano-control.png'),
    ('GET', '/api/plots/stats/{kind}/volcano-table'),
    ('GET', '/api/plots/stats/{kind}/volcano.html'),
    ('GET', '/api/plots/stats/{kind}/volcano.png'),
    ('POST', '/api/restore/browser-session-reset'),
    ('GET', '/api/runtime/normalization'),
    ('GET', '/api/runtime/plotly-{version}.js'),
    ('GET', '/api/runtime/r'),
    ('GET', '/api/runtime/statistics'),
    ('POST', '/api/stats/anova/run'),
    ('GET', '/api/stats/options/{kind}'),
    ('POST', '/api/stats/ora/list/run'),
    ('POST', '/api/stats/ora/run'),
    ('GET', '/api/stats/pathways'),
    ('POST', '/api/stats/simulation/run'),
    ('POST', '/api/stats/volcano-control/run'),
    ('POST', '/api/stats/volcano/run'),
    ('POST', '/api/summary/report'),
    ('GET', '/api/summary/tables'),
    ('POST', '/api/tool/auth/link-login'),
    ('POST', '/api/tool/auth/login'),
    ('POST', '/api/tool/auth/logout'),
    ('GET', '/api/tool/auth/status'),
    ('POST', '/api/viewer/auth/login'),
    ('POST', '/api/viewer/auth/logout'),
    ('POST', '/api/viewer/auth/qr-login'),
    ('GET', '/api/viewer/auth/status'),
})

_AUTH_PATHS = frozenset(
    path for _, path in VIEWER_ALLOWED_OPERATIONS
    if path.startswith(("/api/viewer/auth/", "/api/tool/auth/"))
)
_ALLOWED_PATTERNS = tuple(
    (method, compile_path(path)[0]) for method, path in VIEWER_ALLOWED_OPERATIONS
)


def auth_route(path: str) -> bool:
    return path.rstrip("/") in _AUTH_PATHS


def viewer_request_allowed(method: str, path: str) -> bool:
    # Preserve FastAPI's trailing-slash redirects without broadening templates.
    path = path.rstrip("/") or "/"
    return any(
        method.upper() == allowed_method and pattern.fullmatch(path) is not None
        for allowed_method, pattern in _ALLOWED_PATTERNS
    )
