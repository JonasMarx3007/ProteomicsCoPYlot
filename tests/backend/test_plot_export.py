from types import SimpleNamespace
from contextlib import nullcontext

import pytest

from app.services.plot_export import cm_to_inch, cm_to_px, to_png_bytes


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
def test_impossible_label_layout_fails_without_resizing_or_clipping(tight):
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(2, 1.5))
    ax.set_title('A deliberately very long unwrapped title ' * 5)
    with pytest.raises(ValueError, match='Increase width/height'):
        to_png_bytes(fig, plt, tight=tight)
    assert tuple(fig.get_size_inches()) == (2, 1.5)
    assert not plt.fignum_exists(fig.number)
