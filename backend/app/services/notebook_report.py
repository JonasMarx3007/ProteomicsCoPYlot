"""A report freezes one collection of the same recipes used by individual exports."""
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
import ast
import io
import json
import logging

import pandas as pd

from app.services.notebook_archive import NotebookRecipe, dataframe_bytes, portable_filename
from app.services.notebook_preprocessing import report_recipe_sink
from app.services.notebook_snapshots import snapshots
from app.services.notebook_source import (
    NotebookSource, extract_notebook_source, function_definition, merge_source, module_source,
)

LOGGER = logging.getLogger(__name__)
_active = ContextVar('report_notebook', default=None)


@dataclass
class ReportRecipes:
    recipes: list[NotebookRecipe] = field(default_factory=list)
    size: int = 0
    # Sections the report shows but the notebook cannot reproduce. The notebook
    # is still offered for the rest and names these, rather than being withheld.
    omitted: list[str] = field(default_factory=list)

    def append(self, recipe):
        size = sum(map(len, recipe.resources.values())) + len(recipe.source.code.encode())
        if self.size + size > 128 * 1024 * 1024:
            raise ValueError('Report notebook exceeds the 128 MiB resource limit.')
        self.recipes.append(recipe)
        self.size += size


_SECTION_NAMES = {
    'qc_coverage_plot': 'Coverage', 'qc_boxplot_plot': 'Intensity Boxplot', 'qc_cv_plot': 'Coefficient of Variation',
    'qc_intensity_histogram_plot': 'Intensity Distribution', 'qc_correlation_plot': 'Sample Correlation',
    'qc_pca_plot': 'PCA', 'qc_pca_interactive_html': 'Interactive PCA', 'qc_abundance_plot': 'Abundance',
    'qc_abundance_interactive_html': 'Interactive Abundance', 'qc_peptide_coverage_plot': 'Coverage',
    'peptide_rt_plot': 'Retention Time', 'peptide_modification_plot': 'Modifications',
    'peptide_missed_cleavage_plot': 'Missed Cleavages', 'phosphosite_plot_png': 'Phosphosite Counts',
    'phospho_coverage_png': 'Phosphosite Coverage', 'completeness_missing_value_plot': 'Missing Value Plot',
    'completeness_missing_value_plot_peptide': 'Missing Value Plot', 'volcano_png': 'Volcano Plot',
    'volcano_html': 'Interactive Volcano Plot', 'qc_coverage_table': 'Coverage summary table',
    'qc_boxplot_table': 'Boxplot summary table', 'qc_cv_table': 'CV summary table',
}


def _section_label(renderer, args, options):
    """How the report names this part, for the list of sections the notebook leaves out."""
    name = getattr(renderer, '__name__', str(renderer))
    first = args[0] if args else None
    kind = options.get('kind') or getattr(first, 'kind', None) or (first if isinstance(first, str) else '')
    if name.startswith('peptide_') or name.endswith('_peptide') or name == 'qc_peptide_coverage_plot':
        kind = 'peptide'
    label = _SECTION_NAMES.get(name, name.replace('_', ' '))
    if getattr(first, 'condition1', None):
        label += f' ({first.condition1} vs {first.condition2})'
    return f'{str(kind).capitalize()} — {label}' if kind else label


def _volcano_counts(table):
    """The counts the report's volcano paragraph states, from the volcano table itself."""
    counts = {'upregulated': int((table['significance'] == 'Upregulated').sum()),
              'downregulated': int((table['significance'] == 'Downregulated').sum()),
              'notSignificant': int((table['significance'] == 'Not significant').sum()),
              'unavailable': int((table['significance'] == 'Unavailable').sum()),
              'tested': int(len(table))}
    significant = table[table['significance'].isin(['Upregulated', 'Downregulated'])]
    if len(significant) and 'imputed_values' in table:
        counts['significantWithImputedValues'] = int((significant['imputed_values'].fillna(0) > 0).sum())
    return counts


_VOLCANO_COUNTS_CODE = (
    "\ncounts = functions.functions_report_counts(table)\n"
    "assert counts == json.loads((RESOURCES / 'counts.json').read_text(encoding='utf-8'))\n"
    "Path('reproduced_counts.json').write_text(json.dumps(counts, indent=2), encoding='utf-8', newline='')\n"
    "print(f\"{counts['upregulated']} upregulated, {counts['downregulated']} downregulated, \"\n"
    "      f\"{counts['notSignificant']} not significant, {counts['unavailable']} without a p-value, \"\n"
    "      f\"out of {counts['tested']} tested.\")\n")


def _render(name, *args, **options):
    from app.services import notebook_qc as qc, notebook_pca as pca
    from app.services import notebook_peptide as peptide, notebook_phospho as phospho
    from app.services import notebook_completeness as completeness, notebook_interactive as interactive
    from app.services.notebook_volcano import render_volcano

    qc_names = {renderer: plot for plot, renderer in qc.QC_RENDERERS.items()}
    if name in qc_names:
        return qc.render_qc(*args, plot=qc_names[name], **options)
    adapters = {
        'qc_pca_plot': pca.render_pca,
        'qc_pca_interactive_html': lambda **kw: pca.render_pca(interactive=True, **kw),
        'qc_abundance_interactive_html': interactive.render_abundance,
        'qc_peptide_coverage_plot': peptide.render_coverage,
        'peptide_rt_plot': peptide.render_rt,
        'peptide_modification_plot': peptide.render_modification,
        'peptide_missed_cleavage_plot': peptide.render_missed_cleavage,
        'phosphosite_plot_png': phospho.render_counts,
        'phospho_coverage_png': phospho.render_coverage,
        'completeness_missing_value_plot': lambda **kw: completeness.render_completeness(plot='missing-value', **kw),
        'completeness_missing_value_plot_peptide': lambda **kw: completeness.render_peptide_missing_values('peptide', **kw),
        'volcano_png': render_volcano,
        'volcano_html': lambda *a, **kw: render_volcano(*a, interactive=True, **kw),
    }
    return adapters[name](*args, **options)


def report_plot(renderer, *args, **options):
    collector = _active.get()
    if collector is None:
        return renderer(*args, **options)
    before = len(collector.recipes)
    try:
        content, token = _render(renderer.__name__, *args, **options)
        if not token or len(collector.recipes) != before + 1:
            del collector.recipes[before:]
            collector.omitted.append(_section_label(renderer, args, options))
        else:
            recipe = collector.recipes[-1]
            kind = recipe.provenance.get('kind', '')
            if recipe.provenance.get('plot') == 'volcano':
                table = pd.read_parquet(io.BytesIO(recipe.resources['table.parquet']))
                recipe = replace(recipe,
                    resources={**recipe.resources, 'counts.json': json.dumps(_volcano_counts(table)).encode()},
                    source=extract_notebook_source(_merge_counts(recipe.source.code),
                        (*recipe.source.functions, 'functions_report_counts')),
                    calculation=recipe.calculation + _VOLCANO_COUNTS_CODE)
            collector.recipes[-1] = replace(recipe, plot_name=f'{kind.capitalize()} — {recipe.plot_name}')
        return content
    except Exception:
        # An unavailable export must not take a working HTML report away.
        LOGGER.exception('Report notebook adapter failed: %s', renderer.__name__)
        del collector.recipes[before:]
        collector.omitted.append(_section_label(renderer, args, options))
        return renderer(*args, **options)


def _merge_counts(code):
    counts = _definition_renamed(module_source('notebook_report.py'), '_volcano_counts', 'functions_report_counts')
    return merge_source(code, counts)


def _definition_renamed(source, name, new_name):
    return function_definition(source, name).replace(f'def {name}(', f'def {new_name}(', 1)


def report_table(renderer, *args, **options):
    frame = renderer(*args, **options)
    collector = _active.get()
    if collector is None or frame.empty:
        return frame
    plot = {'qc_coverage_table': 'coverage', 'qc_boxplot_table': 'boxplot', 'qc_cv_table': 'cv'}[renderer.__name__]
    kind = options.get('kind', args[0] if args else None)
    for recipe in reversed(collector.recipes):
        if recipe.provenance.get('kind') == kind and recipe.provenance.get('plot') == plot:
            table_bytes = recipe.resources.get('table.parquet')
            if table_bytes is not None and pd.read_parquet(io.BytesIO(table_bytes)).equals(frame):
                return frame  # Already calculated alongside the matching figure.
    before = len(collector.recipes)
    try:
        from app.services.notebook_qc import render_qc
        _, token = render_qc(*args, plot=plot, **options)
        if not token or len(collector.recipes) != before + 1:
            raise ValueError('Missing report table recipe.')
        recipe = collector.recipes[-1]
        pd.testing.assert_frame_equal(pd.read_parquet(io.BytesIO(recipe.resources['table.parquet'])), frame)
        code = recipe.calculation[recipe.calculation.index('table_options ='):]
        roots = tuple(dict.fromkeys(node.attr for node in ast.walk(ast.parse(recipe.preparation + '\n' + code))
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == 'functions'))
        collector.recipes[-1] = replace(recipe, plot_name=f'{kind.capitalize()} {plot} summary table',
            source=extract_notebook_source(recipe.source.code, roots),
            resources={key: value for key, value in recipe.resources.items() if not key.startswith('original.')},
            provenance={**recipe.provenance, 'outputs': ['table']},
            calculation='from IPython.display import display\n' + code)
    except Exception:
        LOGGER.exception('Report summary table notebook unavailable')
        del collector.recipes[before:]
        collector.omitted.append(_section_label(renderer, args, options))
    return frame


def record_sample_mapping(title, mapping):
    collector = _active.get()
    if collector is None:
        return
    try:
        metadata = mapping.drop(columns=['label'])
        source = extract_notebook_source(module_source('functions.py'), ('sample_label_frame',))
        collector.append(NotebookRecipe(plot_name=f'Sample mapping — {title}', source=source,
            settings={}, provenance={'inputReplay': 'captured-metadata', 'outputs': ['table']},
            original_filename='', resources={'input.parquet': dataframe_bytes(metadata),
                'metadata.parquet': dataframe_bytes(metadata), 'table.parquet': dataframe_bytes(mapping)},
            input_explanation='Sample labels are regenerated from the report’s captured annotation metadata.',
            calculation="from IPython.display import display\n"
                "table = functions.sample_label_frame(metadata)\n"
                "pd.testing.assert_frame_equal(table, pd.read_parquet(RESOURCES / 'table.parquet'), check_exact=True)\n"
                "table.to_csv('reproduced_table.csv', index=False)\ndisplay(table)"))
    except Exception:
        LOGGER.exception('Report sample mapping notebook unavailable')
        collector.omitted.append(f'Sample mapping — {title}')


def load_functions(path, name):
    """Separate modules keep section-specific scientific helpers from colliding."""
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def combine_report(title, recipes, omitted=()):
    loader = extract_notebook_source(module_source('notebook_report.py'), ('load_functions',))
    imports = tuple(sorted(set(loader.imports).union(*(recipe.source.imports for recipe in recipes))))
    resources = {'input.parquet': dataframe_bytes(pd.DataFrame()),
                 'metadata.parquet': dataframe_bytes(pd.DataFrame())}
    sections, provenance, inputs = [], [], {}
    for index, recipe in enumerate(recipes, 1):
        section = f'section_{index:03d}'
        resources.update({f'{section}/{key}': value for key, value in recipe.resources.items()})
        resources[f'{section}/functions.py'] = recipe.source.code.encode()
        resources[f'{section}/settings.json'] = json.dumps(recipe.settings, allow_nan=False).encode()
        filename = portable_filename(recipe.original_filename)
        # Warnings belong to the screen, never to the report or its export.
        section_provenance = {key: value for key, value in recipe.provenance.items() if key != 'warnings'}
        item = {'section': section, 'name': recipe.plot_name, 'originalFilename': filename,
                'usesImputedInput': recipe.uses_imputed_input, 'provenance': section_provenance}
        provenance.append(item)
        code = (f"RESOURCES = ROOT_RESOURCES / '{section}'\n"
            f"functions = report_functions.load_functions(RESOURCES / 'functions.py', '{section}')\n"
            "settings = json.loads((RESOURCES / 'settings.json').read_text(encoding='utf-8'))\n"
            "metadata = pd.read_parquet(RESOURCES / 'metadata.parquet')\n"
            f"Path('outputs/{section}').mkdir(parents=True, exist_ok=True)\n")
        if recipe.provenance.get('inputReplay') == 'original-file':
            key = recipe.provenance['kind']
            if key in inputs and inputs[key] != filename:
                raise ValueError('Conflicting original uploads in the report.')
            inputs[key] = filename
            code += f'data_path = data_paths[{json.dumps(key)}]\n'
        if recipe.uses_imputed_input:
            if not recipe.imputation_recipe.strip():
                raise ValueError('Imputation history is required for every imputed report section.')
            code += '# Reuse the exact imputed matrix; do not draw new values.\n'
            code += ''.join('# ' + line + '\n' for line in recipe.imputation_recipe.splitlines())
            item['imputationRecipe'] = recipe.imputation_recipe
        code += recipe.preparation + '\n' + recipe.calculation
        # Existing recipes use fixed output basenames; isolate those, not their calculations.
        code = code.replace("'reproduced", f"'outputs/{section}/reproduced")
        code = code.replace('"reproduced', f'"outputs/{section}/reproduced')
        sections.append((f'## {index}. {recipe.plot_name}\n\n{recipe.input_explanation}', code))
    preparation = ('report_functions = functions\nROOT_RESOURCES = RESOURCES\n\n'
                   '# Set each path once, using the original uploaded files (filenames below).\n'
                   'data_paths = {\n')
    for kind, filename in inputs.items():
        preparation += f'    {json.dumps(kind)}: Path("YOUR_ORIGINAL_DATA_FILE"),  # {json.dumps(filename)}\n'
    preparation += '}\n'
    return NotebookRecipe(plot_name=title + ' — Report',
        source=NotebookSource(loader.code, loader.functions, imports), settings={},
        provenance={'inputReplay': 'report-sections', 'sections': provenance, 'originalFiles': inputs,
                    'omittedSections': list(omitted)},
        original_filename='', resources=resources, preparation=preparation, calculation='',
        uses_imputed_input=any(recipe.uses_imputed_input for recipe in recipes),
        imputation_recipe='Only sections marked usesImputedInput use captured imputation. Exact parameters and '
            'the corresponding reconstruction code are documented separately in those sections and in the manifest.',
        calculation_sections=tuple(sections), input_explanation=
            'This notebook reproduces the plots, summary tables and volcano counts of the generated report. '
            'The report\u2019s prose (methods paragraphs and any text you wrote) is not regenerated. '
            'Set the original-file paths below, then run from top to bottom. Each section contains its '
            'own calculation code and settings; outputs are saved in separate numbered folders. '
            'Only sections that actually use imputed values reuse their documented captured matrix. '
            'The manifest identifies imputation separately for every section.' + (
            '\n\nNot reproduced here, because their export could not be prepared: '
            + '; '.join(omitted) + '.' if omitted else ''))


def report_with_notebook(builder, payload):
    from app.services.runtime_cache import runtime_cache_version
    from app.services.session_context import get_session_id
    revision = runtime_cache_version()
    collector = ReportRecipes()
    active_token = _active.set(collector)
    sink_token = report_recipe_sink.set(collector.append)
    try:
        result = builder(payload)
    finally:
        report_recipe_sink.reset(sink_token)
        _active.reset(active_token)
    try:
        from app.services.viewer_bootstrap import viewer_mode_enabled
        if viewer_mode_enabled():
            return result  # Viewers download the report, not its notebook.
        if runtime_cache_version() != revision:
            raise ValueError('The data changed while the report was generated.')
        if collector.recipes:
            recipe = combine_report(payload.title.strip() or 'CoPYlot', collector.recipes, collector.omitted)
            result.notebookToken = snapshots.capture(get_session_id(), recipe)
            result.notebookOmitted = list(collector.omitted)
    except Exception:
        LOGGER.exception('Full report notebook unavailable')
        result.notebookError = ('The full report notebook could not be captured reproducibly. '
            'Regenerate the report after loading and annotating the original files. '
            'Large reports may exceed the 128 MiB export limit.')
    return result
