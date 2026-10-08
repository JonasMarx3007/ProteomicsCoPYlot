from notebook_replay_support import set_original_path

import io
import json
import subprocess
import sys
from zipfile import ZipFile

import pandas as pd
import pytest

from app.schemas.annotation import AnnotationFilterConfig, AnnotationGenerateRequest
from app.services.annotation_store import get_annotation
from app.services.dataset_store import get_current_dataset
from app.services.phosprot_tools import aggregate_from_phospho
from app.services.notebook_pca import render_pca
from app.services.notebook_provenance import NotebookProvenanceError
from app.services.notebook_qc import snapshots
from app.services.notebook_archive import build_notebook_archive
from app.services.session_context import get_session_id


@pytest.mark.parametrize('source', ['non_imputed', 'imputed'])
@pytest.mark.parametrize('mode', ['mean', 'robust_site_median'])
@pytest.mark.parametrize('interactive', [False, True])
def test_collapse_history_survives_reannotation_restore_and_notebook(phosphosites, tmp_path, source, mode, interactive):
    from app.api.routes_annotations import generate_annotation
    from app.services.restore_state import export_state_blob, decode_restore_blob, apply_restore_state
    annotation = aggregate_from_phospho(mode, source)
    historical = annotation.phosprot_lineage.model_dump()
    assert annotation.imputation is None and annotation.imputed_data.empty
    assert historical['source'] == ('imputed' if source == 'imputed' else 'filtered')
    assert (historical['imputation'] is not None) == (source == 'imputed')
    # Editing today's upstream parameters must never rewrite yesterday's collapse history.
    get_annotation('phospho').imputation.seed = 999
    assert get_current_dataset('phosprot').phosprot_lineage.model_dump() == historical
    assert get_annotation('phosprot').phosprot_lineage.model_dump() == historical
    generate_annotation(AnnotationGenerateRequest(kind='phosprot', isLog2Transformed=True,
        conditions=[{'name': group, 'columns': [f'{group}{i}' for i in range(1, 5)]} for group in 'AB'],
        filter=AnnotationFilterConfig(minPresent=0)))
    assert get_annotation('phosprot').phosprot_lineage.model_dump() == historical
    state = decode_restore_blob(export_state_blob(portable=True))
    apply_restore_state(state, {})
    assert get_annotation('phosprot').phosprot_lineage.model_dump() == historical
    assert get_current_dataset('phosprot').phosprot_lineage.model_dump() == historical
    options = {} if interactive else {'dpi': 80}
    actual, token = render_pca('phosprot', interactive=interactive, **options)
    if not interactive:
        from app.services.plot_images import qc_pca_plot
        assert actual == qc_pca_plot('phosprot', **options)
    recipe = snapshots.get(get_session_id(), token)
    assert recipe.provenance['upstreamCollapse'] == historical
    assert recipe.uses_imputed_input == (source == 'imputed')
    if source == 'imputed':
        assert 'seed=87' in recipe.imputation_recipe
        assert 'BEFORE' in recipe.imputation_recipe
        assert recipe.provenance['imputation']['seed'] == 87
    _, payload = build_notebook_archive(recipe)
    with ZipFile(io.BytesIO(payload)) as archive:
        archive.extractall(tmp_path)
        name = next(name for name in archive.namelist() if name.endswith('.ipynb'))
    notebook = json.loads((tmp_path / name).read_text())
    cells = '\n'.join(''.join(cell['source']) for cell in notebook['cells'] if cell['cell_type'] == 'code')
    cells = set_original_path(cells, tmp_path)
    result = subprocess.run([sys.executable, '-I', '-c', "import sys; sys.path.insert(0, '.');\n" + cells],
                            cwd=tmp_path, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    if interactive:
        assert (tmp_path / 'reproduced.html').read_text(encoding='utf-8') == actual
    else:
        assert (tmp_path / 'reproduced.png').read_bytes() == actual


def test_unknown_or_inconsistent_history_cannot_enable_export(phosphosites):
    annotation = aggregate_from_phospho('mean', 'imputed')
    annotation.phosprot_lineage.imputation.seed = None
    with pytest.raises(NotebookProvenanceError):
        render_pca('phosprot')


@pytest.mark.parametrize('method', ['UMAP', 't-SNE'])
@pytest.mark.parametrize('interactive', [False, True])
def test_phosprot_embedding_matches_the_original_renderer(phosphosites, monkeypatch, method, interactive):
    from app.services import plot_images
    from app.services.plot_webgl import force_svg_rendering
    aggregate_from_phospho('robust_site_median', 'imputed')
    options = dict(method=method, umap_n_neighbors=3, tsne_perplexity=3)
    if interactive:
        monkeypatch.setattr(plot_images, '_plotly_html', lambda figure: force_svg_rendering(figure).to_json())
        expected = plot_images.qc_pca_interactive_html('phosprot', **options)
    else:
        options['dpi'] = 80
        expected = plot_images.qc_pca_plot('phosprot', **options)
    actual, token = render_pca('phosprot', interactive=interactive, **options)
    recipe = snapshots.get(get_session_id(), token)
    assert recipe.uses_imputed_input
    assert recipe.provenance['inputScale'] == 'site-centered log2 ratios'
    if interactive:
        assert json.loads(recipe.resources['figure.json']) == json.loads(expected)
    else:
        assert actual == expected


def test_pairing_preserves_history_and_replacement_upload_clears_it(phosphosites):
    from app.schemas.annotation import SamplePairAssignment
    from app.services.annotation_store import update_annotation_pairing
    from app.services.phosprot_tools import upload_phosprot
    original = aggregate_from_phospho('mean', 'imputed')
    historical = original.phosprot_lineage.model_dump()
    assert historical['imputation']['toolVersion'] == historical['toolVersion']
    update_annotation_pairing('phosprot', 'A', 'B', [
        SamplePairAssignment(condition1Sample=f'A{i}', condition2Sample=f'B{i}') for i in range(1, 5)])
    assert get_annotation('phosprot').phosprot_lineage.model_dump() == historical
    uploaded = upload_phosprot(original.source_data.copy(), 'replacement.csv', True)
    assert uploaded.phosprot_lineage is None
    assert get_current_dataset('phosprot').phosprot_lineage is None
    with pytest.raises(NotebookProvenanceError):
        render_pca('phosprot')


def test_missing_history_preserves_the_displayed_plot(phosphosites):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes_plots import router
    annotation = aggregate_from_phospho('mean', 'imputed')
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get('/api/plots/qc/phosprot/pca.png?dpi=80')
        assert response.status_code == 200
        assert response.headers['X-CoPYlot-Notebook']
        annotation.phosprot_lineage = None
        fallback = client.get('/api/plots/qc/phosprot/pca.png?dpi=80')
        assert fallback.status_code == 200
        assert fallback.content == response.content
        assert 'X-CoPYlot-Notebook' not in fallback.headers
        assert 'X-CoPYlot-Notice' in fallback.headers


def _execute_archive(recipe, tmp_path):
    _, payload = build_notebook_archive(recipe)
    with ZipFile(io.BytesIO(payload)) as archive:
        archive.extractall(tmp_path)
        name = next(name for name in archive.namelist() if name.endswith('.ipynb'))
    notebook = json.loads((tmp_path / name).read_text())
    cells = '\n'.join(''.join(cell['source']) for cell in notebook['cells'] if cell['cell_type'] == 'code')
    cells = set_original_path(cells, tmp_path)
    result = subprocess.run([sys.executable, '-I', '-c', "import sys; sys.path.insert(0, '.');\n" + cells],
                            cwd=tmp_path, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('mode,source', [('mean', 'non_imputed'), ('robust_site_median', 'imputed'), ('robust_site_median', 'non_imputed')])
@pytest.mark.parametrize('plot', ['coverage', 'boxplot', 'cv', 'histogram', 'abundance', 'correlation'])
def test_phosprot_qc_plot_table_and_independent_replay(phosphosites, tmp_path, mode, source, plot):
    from app.services import plot_images, table_functions
    from app.services.notebook_qc import render_qc, QC_RENDERERS, PAIRED_PLOTS
    aggregate_from_phospho(mode, source)
    options = {'dpi': 80, 'advanced': {'conditionColors': {'B': '#771133'}}}
    expected = getattr(plot_images, QC_RENDERERS[plot])('phosprot', **options)
    actual, token = render_qc('phosprot', plot=plot, **options)
    assert actual == expected
    recipe = snapshots.get(get_session_id(), token)
    assert recipe.settings['centered'] == (mode == 'robust_site_median')
    assert recipe.uses_imputed_input == (source == 'imputed')
    assert recipe.provenance['imputationAppliedToThisPlot'] == recipe.uses_imputed_input
    assert recipe.provenance['upstreamCollapse']['aggregation'] == mode
    if source == 'imputed':
        assert 'seed=87' in recipe.imputation_recipe
        assert 'non-imputed' not in recipe.input_explanation
        assert 'ratios' in recipe.provenance['inputScale']
    if plot in PAIRED_PLOTS:
        table = getattr(table_functions, f'qc_{plot}_table')('phosprot')
        pd.testing.assert_frame_equal(table, pd.read_parquet(io.BytesIO(recipe.resources['table.parquet'])))
    _execute_archive(recipe, tmp_path)
    assert (tmp_path / 'reproduced.png').read_bytes() == actual


@pytest.mark.parametrize('mode,source', [('mean', 'non_imputed'), ('robust_site_median', 'imputed'), ('robust_site_median', 'non_imputed')])
def test_phosprot_interactive_abundance_labels_and_replay(phosphosites, tmp_path, monkeypatch, mode, source):
    from app.services import plot_images
    from app.services.notebook_interactive import render_abundance
    from app.services.plot_webgl import force_svg_rendering
    aggregate_from_phospho(mode, source)
    monkeypatch.setattr(plot_images, '_plotly_html', lambda figure: force_svg_rendering(figure).to_json())
    expected = plot_images.qc_abundance_interactive_html('phosprot', condition='B')
    html, token = render_abundance('phosprot', condition='B')
    recipe = snapshots.get(get_session_id(), token)
    assert json.loads(recipe.resources['figure.json']) == json.loads(expected)
    assert recipe.settings['centered'] == (mode == 'robust_site_median')
    assert recipe.uses_imputed_input == (source == 'imputed')
    _execute_archive(recipe, tmp_path)
    assert (tmp_path / 'reproduced.html').read_text(encoding='utf-8') == html


@pytest.mark.parametrize('path', ['coverage.png', 'boxplot.png', 'cv.png', 'intensity-histogram.png',
                                  'abundance.png', 'correlation.png', 'abundance-interactive.html'])
def test_qc_without_historical_lineage_still_renders(phosphosites, path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes_plots import router
    annotation = aggregate_from_phospho('robust_site_median', 'imputed')
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        url = f'/api/plots/qc/phosprot/{path}?dpi=80'
        response = client.get(url)
        assert response.status_code == 200, response.text[:200]
        assert response.headers['X-CoPYlot-Notebook']
        annotation.phosprot_lineage = None
        fallback = client.get(url)
        assert fallback.status_code == 200, fallback.text[:200]
        assert 'X-CoPYlot-Notebook' not in fallback.headers
        if path.endswith('.png'):
            assert fallback.content == response.content


@pytest.mark.parametrize('plot,options', [
    ('coverage', {'summary': True, 'text': True}),
    ('boxplot', {'mode': 'Single', 'text': True}),
    ('correlation', {'method': 'Ellipse', 'include_id': True}),
])
def test_phosprot_qc_alternate_views_match(phosphosites, plot, options):
    from app.services import plot_images
    from app.services.notebook_qc import render_qc, QC_RENDERERS
    aggregate_from_phospho('robust_site_median', 'imputed')
    expected = getattr(plot_images, QC_RENDERERS[plot])('phosprot', dpi=80, **options)
    actual, token = render_qc('phosprot', plot=plot, dpi=80, **options)
    assert token
    assert actual == expected
