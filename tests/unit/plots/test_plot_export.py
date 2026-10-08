from types import SimpleNamespace
from contextlib import nullcontext

import pytest

from app.services.plot_export import cm_to_inch, cm_to_px, to_png_bytes


@pytest.mark.parametrize('renderer', ['app', 'notebook'])
def test_auto_fit_limits_match_the_app_request_limits(renderer):
    import inspect
    from app.services import notebook_qc, plot_export, plot_limits

    module = plot_export if renderer == 'app' else notebook_qc._qc_module('coverage')
    assert module.MAX_AUTO_FIT_CM == plot_limits.MAX_PLOT_WIDTH_CM
    assert module.MAX_AUTO_FIT_CM == plot_limits.MAX_PLOT_HEIGHT_CM
    assert module.MAX_AUTO_FIT_PIXELS == plot_limits.MAX_PLOT_PIXELS
    parameters = inspect.signature(module.fit_figure_to_labels).parameters
    assert parameters['max_width_cm'].default == plot_limits.MAX_PLOT_WIDTH_CM
    assert parameters['max_height_cm'].default == plot_limits.MAX_PLOT_HEIGHT_CM
    assert parameters['max_pixels'].default == plot_limits.MAX_PLOT_PIXELS


@pytest.mark.parametrize('tight,transparent', [(False, False), (True, False), (False, True), (True, True)])
def test_png_export_preserves_options_bytes_and_closes_figure(tight, transparent):
    calls = []

    def savefig(stream, **options):
        calls.append(options)
        stream.write(b'png-content')

    layout = []
    fig = SimpleNamespace(
        savefig=savefig, _copylot_transparent_background=transparent,
        tight_layout=lambda **kwargs: layout.append(kwargs),
        canvas=SimpleNamespace(draw=lambda: None, get_renderer=lambda: None),
        get_tightbbox=lambda _: None, get_size_inches=lambda: (4, 3),
    )
    closed = []
    result = to_png_bytes(fig, SimpleNamespace(close=closed.append, rc_context=lambda _: nullcontext()), dpi=40, tight=tight)
    expected = {'format': 'png', 'dpi': 72}
    assert layout == ([{'pad': 0.8}] if tight else [])
    if transparent:
        expected['transparent'] = True
    assert result == b'png-content'
    assert calls == [expected]
    assert closed == [fig]


@pytest.mark.parametrize('cm,inches,pixels', [(1.27, 0.5, 320), (2.54, 1, 320), (25.4, 10, 960)])
def test_plot_units_preserve_physical_size_and_minimum_viewport(cm, inches, pixels):
    assert cm_to_inch(cm) == pytest.approx(inches)
    assert cm_to_px(cm) == pixels


@pytest.mark.parametrize('cm', [0, -1, float('nan'), float('inf')])
def test_invalid_physical_dimensions_are_rejected(cm):
    with pytest.raises(ValueError, match='dimensions'):
        cm_to_inch(cm)


def test_wrapped_comparison_labels_keep_every_character():
    from app.services.comparison_tools import _wrap_label

    label = '[6]  A_long_sample_filename-with-punctuation_1234567890'
    wrapped = _wrap_label(label, 4)
    assert '\n' in wrapped
    assert wrapped.replace('\n', '') == label


@pytest.mark.parametrize('fmt', ['png', 'pdf'])
@pytest.mark.parametrize('decoration', ['labels', 'legend', 'colorbar'])
def test_export_preserves_canvas_dimensions_and_labels(fmt, decoration):
    import io
    import re
    import matplotlib.pyplot as plt
    from PIL import Image
    from app.services.plot_export import plot_output_format

    width, height = 18 / 2.54, 12 / 2.54
    fig, ax = plt.subplots(figsize=(width, height))
    ax.plot([0, 1], [1, 2], label='Treatment condition')
    ax.set_title('Comparison of measured intensities')
    ax.set_xlabel('Sample')
    ax.set_ylabel('Intensity')
    if decoration == 'legend':
        ax.legend(loc='upper left', bbox_to_anchor=(1.02, 1))
    elif decoration == 'colorbar':
        fig.colorbar(ax.imshow([[0, 1], [2, 3]]), ax=ax)
    token = plot_output_format.set(fmt)
    try:
        content = to_png_bytes(fig, plt, dpi=150)
    finally:
        plot_output_format.reset(token)
    if fmt == 'png':
        with Image.open(io.BytesIO(content)) as image:
            assert image.width == pytest.approx(width * 150, abs=1)
            assert image.height == pytest.approx(height * 150, abs=1)
    else:
        box = re.search(rb'/MediaBox\s*\[([^\]]+)\]', content)
        assert list(map(float, box[1].split())) == pytest.approx([0, 0, width * 72, height * 72])
    assert ax.get_title() == 'Comparison of measured intensities'
    assert ax.get_xlabel() == 'Sample'


@pytest.mark.parametrize('tight', [False, True])
def test_impossible_label_layout_fails_after_bounded_fitting_without_clipping(tight):
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(2, 1.5))
    ax.set_title('A deliberately very long unwrapped title ' * 40)
    with pytest.raises(ValueError, match='Increase width/height'):
        to_png_bytes(fig, plt, tight=tight)
    assert all(size <= 60 / 2.54 for size in fig.get_size_inches())
    assert not plt.fignum_exists(fig.number)


def _label_heavy_heatmap(plt, width_cm=20.0, height_cm=12.0):
    """A pathway-heatmap-shaped figure whose labels cannot fit the canvas."""
    import numpy as np

    genes = [f'GENE{index:02d}_long_pathway_member_label' for index in range(48)]
    columns = [f'condition_with_a_long_name_{index}' for index in range(14)]
    fig, ax = plt.subplots(figsize=(width_cm / 2.54, height_cm / 2.54))
    image = ax.imshow(np.arange(len(genes) * len(columns)).reshape(len(genes), len(columns)), aspect='auto')
    ax.set_xticks(np.arange(len(columns)))
    ax.set_xticklabels(columns, rotation=90)
    ax.set_yticks(np.arange(len(genes)))
    ax.set_yticklabels(genes)
    ax.set_title('A representative GO term (log2 Intensity; median across mapped features)')
    fig.colorbar(image, ax=ax).set_label('log2 Intensity')
    fig.tight_layout()
    return fig


def test_requested_size_is_a_floor_so_label_heavy_figures_still_render():
    import io
    import matplotlib.pyplot as plt
    from PIL import Image
    from app.services.plot_export import fit_figure_to_labels

    automatic = to_png_bytes(_label_heavy_heatmap(plt), plt, dpi=150)
    assert automatic.startswith(b'\x89PNG')

    fig = _label_heavy_heatmap(plt)
    requested = tuple(fig.get_size_inches())
    width, height = fit_figure_to_labels(fig, plt, dpi=150)
    assert width >= requested[0] and height >= requested[1]
    assert (width, height) != requested
    content = to_png_bytes(fig, plt, dpi=150)
    with Image.open(io.BytesIO(content)) as image:
        # The DPI the caller asked for survives the resize.
        assert image.info['dpi'][0] == pytest.approx(150, abs=1)
        assert image.width == pytest.approx(width * 150, abs=2)


def test_auto_fit_never_shrinks_a_figure_that_already_fits():
    import matplotlib.pyplot as plt
    from app.services.plot_export import fit_figure_to_labels

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.plot([0, 1], [1, 2])
    try:
        assert fit_figure_to_labels(fig, plt, dpi=150) == pytest.approx((8, 6))
    finally:
        plt.close(fig)


@pytest.fixture
def exported_layout(monkeypatch):
    import matplotlib.pyplot as plt
    from matplotlib.backend_bases import FigureCanvasBase
    from app.services.plot_export import _tick_label_space

    measurements = {}
    close = plt.close

    def capture_and_close(fig=None):
        try:
            if hasattr(fig, 'canvas'):
                renderer = fig.canvas.get_renderer()
                measurements[fig] = (
                    fig.get_tightbbox(renderer).frozen(),
                    _tick_label_space(fig, renderer),
                )
        finally:
            close(fig)
            if hasattr(fig, 'canvas'):
                # Closing may discard the renderer, depending on the backend.
                FigureCanvasBase(fig)

    monkeypatch.setattr(plt, 'close', capture_and_close)
    return measurements


@pytest.mark.parametrize('fmt', ['png', 'pdf', 'svg'])
def test_crowded_condition_legend_fits_automatically_and_keeps_data(fmt, exported_layout):
    import matplotlib.pyplot as plt
    import numpy as np
    from app.services.plot_export import plot_output_format

    fig, ax = plt.subplots(figsize=(20 / 2.54, 10 / 2.54))
    for index in range(16):
        ax.plot([0, 1], [index, index + 1], label=f'Condition {index + 1}')
    ax.legend(loc='upper left', bbox_to_anchor=(1.05, 1))
    before = [line.get_xydata().copy() for line in ax.lines]
    token = plot_output_format.set(fmt)
    try:
        content = to_png_bytes(fig, plt, dpi=150)
    finally:
        plot_output_format.reset(token)
    assert content
    assert len(ax.get_legend().get_texts()) == 16
    for line, expected in zip(ax.lines, before):
        np.testing.assert_array_equal(line.get_xydata(), expected)
    bounds, _ = exported_layout[fig]
    width, height = fig.get_size_inches()
    assert bounds.x0 >= -1 / 150 and bounds.y0 >= -1 / 150
    assert bounds.x1 <= width + 1 / 150 and bounds.y1 <= height + 1 / 150
    assert not plt.fignum_exists(fig.number)


def test_many_sample_labels_get_space_without_being_hidden_or_shrunk(exported_layout):
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(20 / 2.54, 10 / 2.54))
    labels = [f'Condition{index // 6}_{index % 6 + 1}' for index in range(96)]
    ax.bar(range(96), [1] * 96)
    ax.set_xticks(range(96), labels, rotation=90, fontsize=9)
    assert to_png_bytes(fig, plt, dpi=150).startswith(b'\x89PNG')
    assert [label.get_text() for label in ax.get_xticklabels()] == labels
    assert all(label.get_fontsize() == 9 for label in ax.get_xticklabels())
    _, tick_space = exported_layout[fig]
    assert max(tick_space) <= 1 / 150
    assert fig.get_figwidth() > 20 / 2.54
    assert not plt.fignum_exists(fig.number)


def test_auto_fit_pixel_budget_holds_when_only_one_dimension_can_grow():
    import matplotlib.pyplot as plt
    from app.services.plot_export import fit_figure_to_labels

    fig, ax = plt.subplots(figsize=(8, 2))
    ax.set_title('A very long title ' * 30)
    try:
        width, height = fit_figure_to_labels(fig, plt, dpi=300, max_pixels=1_600_000)
        assert width >= 8 and height >= 2
        assert width * height * 300**2 <= 1_600_000 + 1
    finally:
        plt.close(fig)


def test_auto_fit_stays_inside_the_allowed_canvas_and_pixel_budget():
    import matplotlib.pyplot as plt
    from app.services.plot_export import (
        MAX_AUTO_FIT_CM,
        MAX_AUTO_FIT_PIXELS,
        cm_to_inch,
        fit_figure_to_labels,
    )

    fig, ax = plt.subplots(figsize=(2, 1.5))
    ax.set_title('A deliberately very long unwrapped title ' * 40)
    try:
        width, height = fit_figure_to_labels(fig, plt, dpi=600)
        assert width <= cm_to_inch(MAX_AUTO_FIT_CM) + 1e-6
        assert height <= cm_to_inch(MAX_AUTO_FIT_CM) + 1e-6
        assert (width * 600) * (height * 600) <= MAX_AUTO_FIT_PIXELS
        # A pathological label still cannot be rendered by cropping it away.
        with pytest.raises(ValueError, match='Increase width/height'):
            to_png_bytes(fig, plt, dpi=600)
    finally:
        if plt.fignum_exists(fig.number):
            plt.close(fig)


def test_pathway_heatmap_renders_at_the_page_default_size(monkeypatch):
    import numpy as np
    import pandas as pd
    from app.services import stats_tools

    # A real GO term: forty-odd member genes and a description that is one long
    # unwrapped line once it becomes the figure title.
    pathway = (
        'positive regulation of transcription from RNA polymerase II promoter '
        'in response to endoplasmic reticulum stress'
    )
    genes = [f'GENE{index:02d}_pathway_member' for index in range(48)]
    samples = [f'sample_identifier_{index}' for index in range(14)]
    frame = pd.DataFrame({'GeneNames': genes})
    for position, sample in enumerate(samples):
        frame[sample] = np.linspace(1.0, 20.0, len(genes)) + position
    metadata = pd.DataFrame(
        {'sample': samples, 'condition': [f'condition_long_name_{index // 7}' for index in range(len(samples))]}
    )
    monkeypatch.setattr(
        stats_tools, '_stats_source', lambda kind, data_source='data': ('data', frame, metadata, [])
    )
    monkeypatch.setattr(
        stats_tools,
        'load_go_db',
        lambda: pd.DataFrame({'description': [pathway], 'genes': [';'.join(genes)]}),
    )

    content = stats_tools.pathway_heatmap_png(
        kind='protein',
        pathway=pathway,
        conditions=[],
        value_type='log2',
        include_id=True,
        header=True,
        remove_empty=True,
        cluster_rows=False,
        cluster_cols=False,
        width_cm=20,
        height_cm=12,
        dpi=150,
    )
    assert content.startswith(b'\x89PNG')


def test_every_bundled_pathway_name_renders_at_the_page_default_size(monkeypatch) -> None:
    """The title is wrapped, not grown into, and no residual overflow survives.

    Two cases the first fix missed, both found by rendering real Gene Ontology
    descriptions at the page's own 20 x 12 cm default:

    * the longest description in the bundled table is 187 characters, which is
      one unbreakable line wider than any canvas this page would sensibly be
      given -- growing the figure cannot fix it, wrapping can;
    * a short title with long gene labels still ended a hundredth of an inch
      outside after the grow passes, because ``tight_layout`` hands the extra
      room straight back to the axes. The residual is now absorbed into the
      margins instead.
    """
    import numpy as np
    import pandas as pd

    from app.services import stats_tools

    longest = (
        'oxidoreductase activity, acting on paired donors, with incorporation '
        'or reduction of molecular oxygen, reduced flavin or flavoprotein as '
        'one donor, and incorporation of one atom of oxygen'
    )
    short_title_long_labels = 'oxidation-dependent protein catabolic process'
    assert len(longest) > 180

    for pathway in (longest, short_title_long_labels):
        genes = [f'LONGGENENAME{index:02d}_HUMAN' for index in range(18)]
        samples = [f'sample_{index}' for index in range(8)]
        frame = pd.DataFrame({'GeneNames': genes})
        for position, sample in enumerate(samples):
            frame[sample] = np.linspace(1.0, 20.0, len(genes)) + position
        metadata = pd.DataFrame(
            {'sample': samples, 'condition': ['WT'] * 4 + ['GRK'] * 4}
        )
        monkeypatch.setattr(
            stats_tools, '_stats_source', lambda kind, data_source='data': ('data', frame, metadata, [])
        )
        monkeypatch.setattr(
            stats_tools,
            'load_go_db',
            lambda: pd.DataFrame({'description': [pathway], 'genes': [';'.join(genes)]}),
        )

        content = stats_tools.pathway_heatmap_png(
            kind='protein',
            pathway=pathway,
            conditions=[],
            value_type='z',
            include_id=False,
            header=True,
            remove_empty=True,
            cluster_rows=False,
            cluster_cols=False,
            width_cm=20,
            height_cm=12,
            dpi=150,
        )
        assert content.startswith(b'\x89PNG'), pathway


def test_a_wrapped_title_keeps_its_words_and_fits_the_width() -> None:
    from app.services.stats_tools import _wrapped_title

    text = 'oxidoreductase activity, acting on paired donors, with incorporation of oxygen'
    wrapped = _wrapped_title(text, width_cm=20)
    assert wrapped.split() == text.split(), 'wrapping must not lose or split words'
    assert all(len(line) <= 100 for line in wrapped.split('\n'))
    assert _wrapped_title('short enough', width_cm=20) == 'short enough'


def _ora_result(names, *, direction='up', background='experiment', selected_cluster=None):
    """An enrichment result carrying the given term names, and nothing else real.

    The ORA figure is drawn from the terms alone, so a stub is enough to put a
    given set of Gene Ontology descriptions in front of the renderer -- which is
    the only thing these tests are about.
    """
    from app.schemas.stats import EnrichmentResultResponse, EnrichmentTerm

    terms = [
        EnrichmentTerm(
            source='GO:BP',
            termId=f'GO:{index:07d}',
            name=name,
            termSize=120 + index,
            intersectionSize=3 + index * 2,
            querySize=40,
            geneRatio=(3 + index * 2) / 40,
            hitPercent=2.0 + index,
            pValue=10.0 ** -(index + 2),
            adjPValue=10.0 ** -(index + 1),
            intersectingGenes=[f'GENE{index}'],
        )
        for index, name in enumerate(names)
    ]
    return EnrichmentResultResponse(
        kind='protein',
        sourceUsed='data',
        selectedCluster=selected_cluster,
        clusterTerms=terms if selected_cluster else [],
        upTerms=terms if direction == 'up' else [],
        downTerms=terms if direction == 'down' else [],
        backgroundMode=background,
        backgroundSize=5000,
        annotatedBackgroundSize=18000,
        databaseSha256='0' * 64,
        testedTermCount=len(terms),
    )


@pytest.mark.parametrize(
    'direction,expected',
    [('up', 'Upregulated in WT'), ('down', 'Downregulated in WT')],
)
def test_the_ora_title_names_the_first_condition_and_only_that_one(direction, expected):
    """A volcano here is condition1 minus condition2, so the direction belongs to
    condition 1. Naming condition 2 as well states the same fact twice and is
    what makes a reader stop to work out which way round the figure is."""
    from app.schemas.stats import EnrichmentRequest
    from app.services.stats_tools import _ora_direction_texts

    payload = EnrichmentRequest(kind='protein', condition1='WT', condition2='GRK')
    heading, missing = _ora_direction_texts(
        payload, _ora_result(['term'], direction=direction), direction, None
    )
    assert heading == expected
    assert 'GRK' not in heading
    assert missing == expected.split()[0].lower()


def test_the_ora_title_follows_a_condition_renamed_in_the_appearance_panel():
    from app.schemas.stats import EnrichmentRequest
    from app.services.stats_tools import _ora_direction_texts

    payload = EnrichmentRequest(kind='protein', condition1='WT', condition2='GRK')
    heading, _ = _ora_direction_texts(
        payload, _ora_result(['term']), 'up', {'conditionLabels': {'WT': 'Wild type'}}
    )
    assert heading == 'Upregulated in Wild type'


def test_an_anova_cluster_ora_title_names_the_cluster_rather_than_a_condition():
    from app.schemas.stats import EnrichmentRequest
    from app.services.stats_tools import _ora_direction_texts

    payload = EnrichmentRequest(
        kind='protein', source='anova', selectedCluster=3, condition1='WT', condition2='GRK'
    )
    heading, missing = _ora_direction_texts(
        payload, _ora_result(['term'], selected_cluster=3), 'cluster', None
    )
    assert heading == 'ANOVA Cluster 3'
    assert missing == 'ANOVA cluster 3'


# The longest Gene Ontology description in the bundled table, a canvas smaller
# than the smallest the page offers, and fonts big enough that the labels cannot
# all be drawn at the size that was asked for.
_LONGEST_GO_NAME = (
    'oxidoreductase activity, acting on paired donors, with incorporation '
    'or reduction of molecular oxygen, reduced flavin or flavoprotein as '
    'one donor, and incorporation of one atom of oxygen'
)


@pytest.mark.parametrize(
    'width_cm,height_cm,dpi,advanced',
    [
        (26, 12, 300, None),
        (8, 6, 150, None),
        (1, 1, 72, None),
        (26, 12, 300, {'yTickLabelSize': 22, 'titleElement': {'size': 30},
                       'xLabelElement': {'size': 20}, 'yLabelElement': {'size': 20}}),
        (60, 60, 72, {'yTickLabelSize': 26}),
        (12, 30, 150, {'yTickLabelSize': 18, 'titleVisible': False}),
    ],
)
def test_an_ora_figure_is_drawn_however_long_the_terms_and_however_large_the_font(
    monkeypatch, width_cm, height_cm, dpi, advanced
):
    """No combination of terms, canvas and font sizes may answer with an error.

    ``to_png_bytes`` refuses to render a figure whose labels spill off the
    canvas, and a page that answers a legitimate set of controls with
    "Plot labels do not fit" has failed the user. The renderer grows the canvas
    first and, only when the largest allowed canvas still cannot hold them,
    gives up font size rather than giving up the figure.
    """
    from app.schemas.stats import EnrichmentRequest
    from app.services import stats_tools

    names = [_LONGEST_GO_NAME] + [f'{_LONGEST_GO_NAME[:60]} {index}' for index in range(24)]
    monkeypatch.setattr(
        stats_tools, 'run_enrichment', lambda payload: _ora_result(names)
    )
    payload = EnrichmentRequest(kind='protein', condition1='WT', condition2='GRK')
    content = stats_tools.ora_plot_png(
        payload,
        direction='up',
        advanced=advanced,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
    )
    assert content.startswith(b'\x89PNG')


def test_the_ora_canvas_grows_for_its_labels_and_never_shrinks_below_the_request(monkeypatch):
    """Width and height are a floor. Thirty terms need more height than twelve
    centimetres, and the figure that comes back must have taken it."""
    from app.schemas.stats import EnrichmentRequest
    from app.services import stats_tools

    monkeypatch.setattr(
        stats_tools,
        'run_enrichment',
        lambda payload: _ora_result([f'{_LONGEST_GO_NAME[:70]} {index}' for index in range(30)]),
    )
    captured = {}

    real = stats_tools._to_png_bytes

    def capture(fig, plt, dpi=150, tight=True):
        captured['inches'] = tuple(float(value) for value in fig.get_size_inches())
        return real(fig, plt, dpi=dpi, tight=tight)

    monkeypatch.setattr(stats_tools, '_to_png_bytes', capture)
    stats_tools.ora_plot_png(
        EnrichmentRequest(kind='protein', condition1='WT', condition2='GRK'),
        direction='up',
        width_cm=26,
        height_cm=12,
        dpi=150,
    )
    width_in, height_in = captured['inches']
    assert width_in >= cm_to_inch(26) - 0.01, 'the requested width is a floor'
    assert height_in > cm_to_inch(12), 'thirty terms must have grown the canvas'
