from types import SimpleNamespace

import pytest

from app.services.plot_export import cm_to_inch, cm_to_px, to_png_bytes


@pytest.mark.parametrize('tight,transparent', [(False, False), (True, False), (False, True), (True, True)])
def test_png_export_preserves_options_bytes_and_closes_figure(tight, transparent):
    calls = []

    def savefig(stream, **options):
        calls.append(options)
        stream.write(b'png-content')

    fig = SimpleNamespace(savefig=savefig, _copylot_transparent_background=transparent)
    closed = []
    result = to_png_bytes(fig, SimpleNamespace(close=closed.append), dpi=40, tight=tight)
    expected = {'format': 'png', 'dpi': 72}
    if tight:
        expected['bbox_inches'] = 'tight'
    if transparent:
        expected['transparent'] = True
    assert result == b'png-content'
    assert calls == [expected]
    assert closed == [fig]


@pytest.mark.parametrize('cm,inches,pixels', [(0, 1, 320), (2.54, 1, 320), (25.4, 10, 960)])
def test_plot_units_preserve_existing_minima(cm, inches, pixels):
    assert cm_to_inch(cm) == pytest.approx(inches)
    assert cm_to_px(cm) == pixels
