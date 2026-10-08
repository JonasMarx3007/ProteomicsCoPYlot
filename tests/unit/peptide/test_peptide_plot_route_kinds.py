from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.mark.parametrize(
    ("path", "renderer_name"),
    [
        (
            "/api/plots/completeness/peptide/missing-value.png",
            "completeness_missing_value_plot_peptide",
        ),
        (
            "/api/plots/completeness/precursor/missing-value.png",
            "completeness_missing_value_plot_precursor",
        ),
        ("/api/plots/qc/peptide/coverage.png", "qc_peptide_coverage_plot"),
        ("/api/plots/qc/precursor/coverage.png", "qc_peptide_coverage_plot"),
    ],
)
def test_peptide_plot_levels_reach_their_renderers(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    renderer_name: str,
) -> None:
    received: dict[str, object] = {}

    def render(**kwargs: object) -> bytes:
        received.update(kwargs)
        return b"png"

    if renderer_name == "qc_peptide_coverage_plot":
        from app.services import notebook_peptide
        monkeypatch.setattr(notebook_peptide, "render_coverage", lambda **kwargs: (render(**kwargs), ""))
    else:
        from app.services import notebook_completeness
        monkeypatch.setattr(notebook_completeness, "render_peptide_missing_values",
                            lambda level, **kwargs: (render(level=level, **kwargs), ""))
    with TestClient(app) as client:
        response = client.get(path, params={"quantityColumn": "LFQ intensity"})

    assert response.status_code == 200
    assert response.content == b"png"
    assert received["quantity_column"] == "LFQ intensity"
    if renderer_name == "qc_peptide_coverage_plot":
        assert received["level"] == path.split("/")[4]


@pytest.mark.parametrize('level', ['peptide', 'precursor'])
@pytest.mark.parametrize('case,expected,error', [
    ('peptide_only', 'r2', None), ('protein_precedence', 'r1', None),
    ('unmatched', None, 'does not match'), ('protein_unannotated', None, 'Protein annotation'),
    ('peptide_unannotated', None, 'Peptide annotation'), ('partial_overlap', 'r2', None),
    ('selected_all_na', None, 'no usable quantity'),
])
def test_completeness_honors_coverage_annotation_selection(monkeypatch, level, case, expected, error):
    from types import SimpleNamespace
    import pandas as pd
    from app.services import peptide_tools, plot_images, completeness_tools

    frame = pd.DataFrame({'File.Name': ['r1', 'r2', 'r1', 'r2'],
        'Stripped.Sequence': ['AAA', 'AAA', 'BBB', 'BBB'],
        'Precursor.Id': ['AAA2', 'AAA2', 'BBB2', 'BBB2'],
        'Precursor.Quantity': [10., 10., 10., 0.]})
    if case == 'selected_all_na':
        frame.loc[frame['File.Name'] == 'r2', 'Precursor.Quantity'] = float('nan')
    def metadata(samples):
        return pd.DataFrame({'sample': samples, 'condition': ['C'] * len(samples)})
    protein_loaded = case in {'protein_precedence', 'unmatched', 'protein_unannotated'}
    protein_meta = metadata(['other9'] if case == 'unmatched' else ['r1'])
    peptide_meta = metadata(['r2', 'absent9'] if case == 'partial_overlap' else ['r2'])
    monkeypatch.setattr(peptide_tools, 'get_peptide_frame', lambda: frame)
    monkeypatch.setattr(peptide_tools, 'get_current_dataset', lambda _: object() if protein_loaded else None)
    monkeypatch.setattr(peptide_tools, 'get_annotation', lambda _: None if case == 'protein_unannotated' else SimpleNamespace(metadata=protein_meta))
    monkeypatch.setattr(peptide_tools, 'get_peptide_metadata', lambda: None if case == 'peptide_unannotated' else SimpleNamespace(frame=peptide_meta))
    render = getattr(completeness_tools, 'completeness_missing_value_plot_' + level)
    if error:
        with pytest.raises(ValueError, match=error):
            render()
        if case != 'selected_all_na':
            with pytest.raises(ValueError, match=error):
                plot_images.qc_peptide_coverage_plot(level=level)
        return
    matrices = []
    monkeypatch.setattr(completeness_tools, '_missing_value_plot_from_matrix', lambda matrix, **kw: matrices.append(matrix) or b'png')
    assert render() == b'png'
    assert list(matrices[0].columns) == [expected]
    def inspect(fig, plt, **kw):
        try:
            assert [bar.get_height() for bar in fig.axes[0].patches] == matrices[0].notna().sum().tolist()
        finally:
            plt.close(fig)
        return b'png'
    monkeypatch.setattr(plot_images, '_to_png_bytes', inspect)
    assert plot_images.qc_peptide_coverage_plot(level=level) == b'png'
