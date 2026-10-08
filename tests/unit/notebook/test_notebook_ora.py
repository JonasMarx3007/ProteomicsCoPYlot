from notebook_replay_support import set_original_path

import io
import json
import subprocess
import sys
from zipfile import ZipFile

import pandas as pd
import pytest

from app.schemas.stats import EnrichmentRequest, EnrichmentResultResponse, EnrichmentTerm
from app.services import stats_tools
from app.services.notebook_archive import NotebookRecipe, build_notebook_archive, dataframe_bytes
from app.services.notebook_ora import ora_module, ora_source


@pytest.fixture
def database(monkeypatch):
    frame = pd.DataFrame([
        ('BP', 'GO:1', 'A biological process with a long descriptive name ' * 3, 'A;B;C'),
        ('MF', 'GO:2', 'Molecular function', 'A;B'),
        ('CC', 'GO:3', 'Zero overlap for the A/B query', 'D;E'),
        ('BP', 'GO:4', 'Another process', 'B;C;D'),
        ('BP', 'GO:5', 'Tied molecular membership', 'A;B'),
    ], columns=['ontology', 'term', 'description', 'genes'])
    monkeypatch.setattr(stats_tools, 'load_go_db', lambda: frame.copy())
    return frame


@pytest.mark.parametrize('pvalues', [[1.0], [1.0, 1.0], [0.99, 0.99], [0.01, 0.01], [0.01, 0.5]])
def test_ora_colorbar_has_nonnegative_nondegenerate_range(monkeypatch, pvalues):
    terms = [EnrichmentTerm(source='BP', termId=f'GO:{i}', name=f'Term {i}',
        termSize=2, intersectionSize=1, querySize=2, geneRatio=0.5, hitPercent=50,
        pValue=p, adjPValue=p, intersectingGenes=['A']) for i, p in enumerate(pvalues)]
    result = EnrichmentResultResponse(kind='protein', sourceUsed='data', backgroundMode='experiment',
        backgroundSize=5, annotatedBackgroundSize=5, databaseSha256='fixture', testedTermCount=len(terms), upTerms=terms)
    payload = EnrichmentRequest(kind='protein', condition1='A', condition2='B')
    monkeypatch.setattr(stats_tools, 'run_enrichment', lambda _: result)
    def inspect(figure, plt, **kwargs):
        norm = figure.axes[0].collections[0].norm
        assert 0 <= norm.vmin < norm.vmax
        assert min(figure.axes[1].get_yticks()) >= 0
        plt.close(figure)
        return b'checked'
    monkeypatch.setattr(stats_tools, '_to_png_bytes', inspect)
    assert stats_tools.ora_plot_png(payload, 'up', dpi=80) == b'checked'


@pytest.mark.parametrize('background', [None, ['A', 'B', 'D', 'outside'], []])
@pytest.mark.parametrize('query', [['A', 'B'], [' A ', 'A', 'B', 'outside'], [], ['outside']])
@pytest.mark.parametrize('top_n', [1, 10])
@pytest.mark.parametrize('sizes', [(1, 5), (2, 2)])
def test_portable_ora_matches_app_universe_and_statistics(database, background, query, top_n, sizes):
    effective, eligible = stats_tools._prepare_ora_universe(background, *sizes)
    counts = {}
    terms = stats_tools._enrichment_terms(query, top_n, 1, effective, eligible, counts)
    actual = ora_module().calculate_enrichment(database, query, background,
        min_term_size=sizes[0], max_term_size=sizes[1], top_n=top_n, adj_p_value_cutoff=1)
    assert actual == {'terms': [term.model_dump() for term in terms], 'counts': counts,
                      'annotatedBackground': sorted(effective)}


def test_display_limits_do_not_change_correction_family(database):
    module = ora_module()
    all_terms = module.calculate_enrichment(database, ['A', 'B'], None,
        min_term_size=1, max_term_size=5, top_n=10, adj_p_value_cutoff=1)
    limited = module.calculate_enrichment(database, ['A', 'B'], None,
        min_term_size=1, max_term_size=5, top_n=1, adj_p_value_cutoff=1)
    assert limited['terms'] == all_terms['terms'][:1]
    assert all_terms['counts'] == dict(searchSpace=5, overlapTested=4, passingCutoff=4, displayed=4)
    assert limited['counts'] == dict(searchSpace=5, overlapTested=4, passingCutoff=4, displayed=1)
    strict = module.calculate_enrichment(database, ['A', 'B'], None,
        min_term_size=1, max_term_size=5, adj_p_value_cutoff=1e-30)
    assert strict['counts'] == dict(searchSpace=5, overlapTested=4, passingCutoff=0, displayed=0)


def test_portable_ora_matches_bundled_database():
    database = stats_tools.load_go_db()
    query = sorted({gene.strip() for text in database['genes'].head(20)
                    for gene in str(text).split(';') if gene.strip()})[:30]
    assert query
    background, eligible = stats_tools._prepare_ora_universe(None, 5, 500)
    counts = {}
    terms = stats_tools._enrichment_terms(query, 10, 1, background, eligible, counts)
    assert terms
    actual = ora_module().calculate_enrichment(database, query, None, min_term_size=5,
        max_term_size=500, top_n=10, adj_p_value_cutoff=1)
    assert actual['terms'] == [term.model_dump() for term in terms]
    assert actual['counts'] == counts
    assert actual['annotatedBackground'] == sorted(background)


@pytest.mark.parametrize('source,direction,background', [
    ('volcano', 'up', 'experiment'), ('volcano', 'down', 'global'),
    ('volcano_control', 'up', 'experiment'), ('anova', 'cluster', 'experiment')])
def test_ora_standalone_notebook_recalculates_and_renders_exact_plot(database, monkeypatch, tmp_path,
                                                                   source, direction, background):
    payload = EnrichmentRequest(kind='protein', source=source, condition1='A', condition2='B',
        condition1Control='C', condition2Control='D', selectedCluster=2 if source == 'anova' else None,
        minTermSize=1, maxTermSize=5, topN=4, adjPValueCutoff=1, backgroundMode=background)
    genes = ['A', 'B', 'C', 'D', 'E'] if background == 'experiment' else None
    calculation = dict(min_term_size=1, max_term_size=5, top_n=4, adj_p_value_cutoff=1)
    computed = ora_module().calculate_enrichment(database, ['A', 'B'], genes, **calculation)
    terms_key = {'up': 'upTerms', 'down': 'downTerms', 'cluster': 'clusterTerms'}[direction]
    result = EnrichmentResultResponse(kind='protein', sourceUsed='data', selectedCluster=payload.selectedCluster,
        backgroundMode=background, backgroundSize=5, annotatedBackgroundSize=5, databaseSha256='fixture',
        testedTermCount=5, **{terms_key: [EnrichmentTerm(**term) for term in computed['terms']]})
    monkeypatch.setattr(stats_tools, 'run_enrichment', lambda _: result)
    figure_settings = dict(direction=direction, width_cm=20, height_cm=12, dpi=80,
        advanced={'conditionLabels': {'A': 'Treatment'}, 'yTickLabelSize': 9, 'xLabelSize': 11})
    expected = stats_tools.ora_plot_png(payload, **figure_settings)
    actual = ora_module().render_plot(result.model_dump(), payload.model_dump(), **figure_settings)
    assert actual == expected
    recipe = NotebookRecipe(plot_name='ORA', source=ora_source(), original_filename='example.tsv',
        settings={'request': payload.model_dump(), 'result': result.model_dump(), 'figure': figure_settings,
                  'background': genes, 'calculation': calculation, 'termsKey': terms_key},
        provenance={'replayBoundary': 'Frozen query and background; synthetic database for this test'},
        resources={'input.parquet': dataframe_bytes(database), 'metadata.parquet': dataframe_bytes(pd.DataFrame())},
        calculation="from IPython.display import display, Image\n"
            "calculated = functions.calculate_enrichment(data, ['A', 'B'], settings['background'], **settings['calculation'])\n"
            "assert calculated['terms'] == settings['result'][settings['termsKey']]\n"
            "settings['result'][settings['termsKey']] = calculated['terms']\n"
            "table = pd.DataFrame(calculated['terms'])\ntable.to_csv('terms.csv', index=False)\ndisplay(table)\n"
            "image = functions.render_plot(settings['result'], settings['request'], **settings['figure'])\n"
            "Path('reproduced.png').write_bytes(image)\ndisplay(Image(data=image))")
    _, blob = build_notebook_archive(recipe)
    with ZipFile(io.BytesIO(blob)) as archive:
        archive.extractall(tmp_path)
        name = next(name for name in archive.namelist() if name.endswith('.ipynb'))
    notebook = json.loads((tmp_path / name).read_text())
    cells = '\n'.join(''.join(cell['source']) for cell in notebook['cells'] if cell['cell_type'] == 'code')
    cells = set_original_path(cells, tmp_path)
    replay = subprocess.run([sys.executable, '-I', '-c', "import sys;sys.path.insert(0,'.');\n" + cells],
        cwd=tmp_path, capture_output=True, text=True, timeout=90)
    assert replay.returncode == 0, replay.stderr
    assert (tmp_path / 'reproduced.png').read_bytes() == actual


def test_no_terms_and_wrong_direction_keep_existing_errors(database):
    result = EnrichmentResultResponse(kind='protein', sourceUsed='data', backgroundMode='experiment',
        backgroundSize=5, annotatedBackgroundSize=5, databaseSha256='fixture', testedTermCount=5)
    request = EnrichmentRequest(kind='protein', condition1='A', condition2='B').model_dump()
    with pytest.raises(ValueError, match='No upregulated enrichment terms'):
        ora_module().render_plot(result.model_dump(), request, direction='up')
    with pytest.raises(ValueError, match='up or down'):
        ora_module().render_plot(result.model_dump(), request, direction='cluster')
    with pytest.raises(ValueError, match='Minimum term size'):
        ora_module().calculate_enrichment(database, ['A'], None, min_term_size=5, max_term_size=2)


@pytest.fixture
def analysis_database(monkeypatch):
    database = pd.DataFrame([
        ('BP', 'GO:1', 'All observed genes', ';'.join(f'G{i}' for i in range(20))),
        ('MF', 'GO:2', 'First subset', ';'.join(f'G{i}' for i in range(8))),
        ('CC', 'GO:3', 'Second subset', ';'.join(f'G{i}' for i in range(7, 20))),
    ], columns=['ontology', 'term', 'description', 'genes'])
    monkeypatch.setattr(stats_tools, 'load_go_db', lambda: database.copy())
    return database


@pytest.mark.parametrize('mode,source,direction,background', [
    ('volcano', 'data', 'up', 'experiment'), ('volcano', 'imputed', 'down', 'global'),
    ('volcano_control', 'filtered', 'up', 'experiment'), ('anova', 'imputed', 'cluster', 'experiment')])
def test_captured_ora_reruns_upstream_statistics(inputs, analysis_database, tmp_path, mode, source, direction, background):
    from app.services.notebook_ora import render_ora
    from app.services.notebook_qc import snapshots
    from app.services.session_context import get_session_id
    payload = EnrichmentRequest(kind='protein', source=mode, dataSource=source,
        condition1='A', condition2='B', condition1Control='C', condition2Control='D',
        pValueThreshold=1, log2fcThreshold=0, selectedCluster=1 if mode == 'anova' else None,
        nClusters=3, minTermSize=1, maxTermSize=30, adjPValueCutoff=1, backgroundMode=background)
    image, token = render_ora(payload, direction=direction, dpi=80)
    assert image == stats_tools.ora_plot_png(payload, direction=direction, dpi=80)
    recipe = snapshots.get(get_session_id(), token)
    assert recipe.uses_imputed_input == (source == 'imputed')
    if source == 'imputed':
        assert 'seed=77' in recipe.imputation_recipe
    assert 'CC BY 4.0' in recipe.resources['GO_ATTRIBUTION.txt'].decode()
    assert recipe.provenance['databaseSha256'] == stats_tools._go_database_sha256()
    _, blob = build_notebook_archive(recipe)
    with ZipFile(io.BytesIO(blob)) as archive:
        archive.extractall(tmp_path)
        name = next(name for name in archive.namelist() if name.endswith('.ipynb'))
    notebook = json.loads((tmp_path / name).read_text())
    cells = '\n'.join(''.join(cell['source']) for cell in notebook['cells'] if cell['cell_type'] == 'code')
    cells = set_original_path(cells, tmp_path)
    replay = subprocess.run([sys.executable, '-I', '-c', "import sys;sys.path.insert(0,'.');\n" + cells],
        cwd=tmp_path, capture_output=True, text=True, timeout=90)
    assert replay.returncode == 0, replay.stderr
    assert (tmp_path / 'reproduced.png').read_bytes() == image


def test_ora_snapshot_routes_are_frozen_and_owner_scoped(inputs, analysis_database, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes_plots import router
    from app.services.annotation_store import get_annotation
    from app.services.session_context import set_session_id, reset_session_id
    monkeypatch.setenv('COPYLOT_SESSION_ISOLATION', '1')
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        path = '/api/plots/stats/protein/ora/up'
        response = client.get(path + '.png?condition1=A&condition2=B&pValueThreshold=1&log2fcThreshold=0&minTermSize=1&maxTermSize=30&adjPValueCutoff=1&dpi=80')
        assert response.status_code == 200, response.text
        token = response.headers['X-CoPYlot-Notebook']
        url = path + f'/tables?snapshot={token}'
        original = client.get(url)
        assert original.status_code == 200, original.text
        zip_url = f'/api/plots/notebooks/{token}.zip'
        archive = client.get(zip_url).content
        get_annotation('protein').log2_data.loc[:, 'A1'] = 999
        analysis_database.loc[:, 'genes'] = 'different'
        assert client.get(url).json() == original.json()
        assert client.get(zip_url).content == archive
        assert client.get(url.replace('/up/', '/down/')).status_code == 409
        assert client.get(url.replace('/protein/', '/phosprot/')).status_code == 409
        other = set_session_id('another-owner')
        try:
            assert client.get(url).status_code == 404
            assert client.get(zip_url).status_code == 404
        finally:
            reset_session_id(other)


def test_no_term_snapshot_is_exportable_without_rendering(inputs, analysis_database, tmp_path):
    from app.services.notebook_ora import render_ora
    from app.services.notebook_qc import snapshots
    from app.services.session_context import get_session_id
    payload = EnrichmentRequest(kind='protein', condition1='A', condition2='B',
        pValueThreshold=1, minTermSize=1, maxTermSize=30, adjPValueCutoff=1e-30)
    content, token = render_ora(payload, direction='up', table_only=True)
    assert content == b''
    recipe = snapshots.get(get_session_id(), token)
    assert not json.loads(recipe.resources['result.json'])['upTerms']
    assert not any(name.startswith('original.') for name in recipe.resources)
    _, blob = build_notebook_archive(recipe)
    with ZipFile(io.BytesIO(blob)) as archive:
        archive.extractall(tmp_path)
        name = next(name for name in archive.namelist() if name.endswith('.ipynb'))
    notebook = json.loads((tmp_path / name).read_text())
    cells = '\n'.join(''.join(cell['source']) for cell in notebook['cells'] if cell['cell_type'] == 'code')
    cells = set_original_path(cells, tmp_path)
    replay = subprocess.run([sys.executable, '-I', '-c', "import sys;sys.path.insert(0,'.');\n" + cells],
        cwd=tmp_path, capture_output=True, text=True, timeout=90)
    assert replay.returncode == 0, replay.stderr
    assert not (tmp_path / 'reproduced.png').exists()
    assert 'No enriched terms passed' in replay.stdout


@pytest.mark.parametrize('source', ['data', 'imputed'])
def test_phosphoprotein_ora_keeps_collapse_history(phosphosites, monkeypatch, source):
    from app.services.phosprot_tools import aggregate_from_phospho
    from app.services.notebook_ora import render_ora
    from app.services.notebook_qc import snapshots
    from app.services.session_context import get_session_id
    database = pd.DataFrame([('BP', 'GO:1', 'Protein group term', 'P0;P1;P2;P3')],
                            columns=['ontology', 'term', 'description', 'genes'])
    monkeypatch.setattr(stats_tools, 'load_go_db', lambda: database)
    annotation = aggregate_from_phospho('mean', source)
    payload = EnrichmentRequest(kind='phosprot', condition1='A', condition2='B', pValueThreshold=1,
        log2fcThreshold=0, minTermSize=1, maxTermSize=30, adjPValueCutoff=1)
    result = stats_tools.run_enrichment(payload)
    direction = 'up' if result.upTerms else 'down'
    image, token = render_ora(payload, direction=direction, dpi=80)
    assert image == stats_tools.ora_plot_png(payload, direction=direction, dpi=80)
    recipe = snapshots.get(get_session_id(), token)
    assert recipe.provenance['upstreamCollapse'] == annotation.phosprot_lineage.model_dump()
    assert recipe.uses_imputed_input == (source == 'imputed')
    if source == 'imputed':
        assert 'seed=87' in recipe.imputation_recipe
