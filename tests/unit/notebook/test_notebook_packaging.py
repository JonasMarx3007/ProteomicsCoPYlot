import importlib
from pathlib import Path
import re
import shutil
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def source_bundle(tmp_path, monkeypatch):
    # 2026-10-02: one list for both desktop builds instead of a copy in each.
    listing = (ROOT / 'packaging/notebook_sources.txt').read_text(encoding='utf-8')
    names = [line.strip() for line in listing.splitlines() if line.strip() and not line.startswith('#')]
    for script in ('packaging/windows/build_exe_windows.ps1', 'packaging/macos/build_all_macos_variants.sh'):
        text = (ROOT / script).read_text(encoding='utf-8')
        assert 'notebook_sources.txt' in text, f'{script} does not read the shared list'
        assert not re.search(r'services[/\\\\](?:functions|stats_tools)\.py', text), f'{script} still lists sources itself'
    destination = tmp_path / 'notebook_sources'
    destination.mkdir()
    for name in names:
        shutil.copyfile(ROOT / 'backend/app/services' / name, destination / name)
    shutil.copyfile(ROOT / 'proteomicscopylot/notebook_functions.py', destination / 'notebook_functions.py')
    shutil.copyfile(ROOT / 'proteomicscopylot/_core.py', destination / '_core.py')
    shutil.copyfile(ROOT / 'LICENSE', destination / 'LICENSE')
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path), raising=False)
    return destination


CASES = [
    ('qc', 'qc_source', (plot,)) for plot in ['coverage', 'boxplot', 'cv', 'histogram', 'abundance', 'correlation']
] + [
    ('preprocessing', 'preprocessing_source', (collapse, vsn)) for collapse in [False, True] for vsn in [False, True]
] + [
    ('pca', 'pca_source', (interactive, method)) for interactive in [False, True] for method in ['pca', 'umap', 't-sne']
] + [
    ('comparison', 'comparison_source', ('pearson', False)),
    ('comparison', 'comparison_source', ('pearson', True)),
    ('comparison', 'comparison_source', ('venn', False)),
    ('completeness', 'completeness_source', ('missing-value',)),
    ('completeness', 'completeness_source', ('missing-heatmap',)),
    ('volcano', 'volcano_source', (False,)), ('volcano', 'volcano_source', (True,)),
    ('regulation', 'regulation_source', (False,)), ('regulation', 'regulation_source', (True,)),
    ('ora', 'ora_source', ('volcano',)), ('ora', 'ora_source', ('anova',)),
    ('phospho', 'category_source', ('distribution',)), ('phospho', 'category_source', ('sty',)),
] + [(module, function, ()) for module, function in [
    ('single', 'box_source'), ('single', 'line_source'), ('single', 'heatmap_source'),
    ('anova', 'anova_source'), ('pathway', 'pathway_source'), ('sequence', 'sequence_source'),
    ('ksea', 'table_source'), ('interactive', 'abundance_source'),
    ('peptide', 'coverage_source'), ('peptide', 'missed_cleavage_source'),
    ('peptide', 'modification_source'), ('peptide', 'rt_source'), ('peptide', 'interactive_rt_source'),
    ('phospho', 'count_source'), ('phospho', 'coverage_source')]]


@pytest.mark.parametrize('module,function,arguments', CASES)
def test_frozen_source_bundle_supports_notebook_extraction(source_bundle, module, function, arguments):
    from app.services.notebook_archive import _DISTRIBUTIONS

    factory = getattr(importlib.import_module(f'app.services.notebook_{module}'), function)
    factory.cache_clear()
    try:
        source = factory(*arguments)
        compile(source.code, 'functions.py', 'exec')
        assert not any(name == 'app' or name.startswith('app.') for name in source.imports)
        required = {'pandas', 'pyarrow'} | {
            _DISTRIBUTIONS.get(name, name) for name in source.imports
            if name not in sys.stdlib_module_names and name != 'IPython'
        }
        # Copied explicitly by distribution name: whether --collect-all also copies
        # a distribution's metadata for an import name depends on the PyInstaller version.
        listing = (ROOT / 'packaging/notebook_distributions.txt').read_text(encoding='utf-8')
        listed = {line.strip() for line in listing.splitlines() if line.strip() and not line.startswith('#')}
        assert required <= listed, f'notebook_distributions.txt is missing {required - listed}'
        for script in ['packaging/windows/build_exe_windows.ps1',
                       'packaging/macos/build_all_macos_variants.sh']:
            text = (ROOT / script).read_text()
            assert 'notebook_distributions.txt' in text and '--copy-metadata' in text, (
                f'{script} does not copy the listed version metadata')
    finally:
        factory.cache_clear()


def test_frozen_archive_includes_license_and_no_backend_import(source_bundle):
    import io
    from zipfile import ZipFile
    from app.services.notebook_archive import build_notebook_archive
    from test_notebook_export import recipe
    _, payload = build_notebook_archive(recipe())
    with ZipFile(io.BytesIO(payload)) as archive:
        assert archive.read('LICENSE') == (source_bundle / 'LICENSE').read_bytes()
        assert b'from app.' not in archive.read('functions.py')


def test_frozen_report_archive_includes_section_functions(source_bundle):
    import io
    from zipfile import ZipFile
    from app.services.notebook_archive import build_notebook_archive
    from app.services.notebook_report import combine_report
    from test_notebook_export import recipe
    _, payload = build_notebook_archive(combine_report('Report', [recipe()]))
    with ZipFile(io.BytesIO(payload)) as archive:
        assert b'load_functions' in archive.read('functions.py')
        assert b'coverage_plot' in archive.read('resources/section_001/functions.py')
