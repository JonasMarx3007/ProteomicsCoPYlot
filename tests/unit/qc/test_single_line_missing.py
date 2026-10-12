import numpy as np
import pandas as pd
import pytest

from app.services import single_protein_tools as single


@pytest.fixture
def data(monkeypatch):
    samples = ['A1', 'A2', 'A3', 'B1']
    frame = pd.DataFrame({'ProteinNames': ['P1', 'P2', 'P3'], 'GeneNames': ['G1', 'G2', 'G3'],
        'A1': [2., np.nan, 0.], 'A2': [np.nan, np.nan, 3.],
        'A3': [4., np.nan, np.inf], 'B1': [np.nan, np.nan, -2.]})
    metadata = pd.DataFrame({'sample': samples, 'condition': ['A', 'A', 'A', 'B']})
    monkeypatch.setattr(single, '_analysis_frame', lambda *a, **k: (frame.copy(), samples, metadata.copy()))
    monkeypatch.setattr(single, 'phosprot_values_are_centred', lambda _: False)
    return frame


@pytest.mark.parametrize('identifier,proteins', [('workflow', ['P1', 'P2']), ('genes', ['G1', 'G2'])])
def test_missing_samples_remain_in_table_without_increasing_observed_count(data, identifier, proteins):
    table = single.single_protein_lineplot_table('protein', proteins, [], identifier=identifier)
    assert len(table) == 8
    first = table[table.Feature == proteins[0]]
    assert first.Sample.tolist() == ['A_1', 'A_2', 'A_3', 'B_1']
    assert first.Value.isna().tolist() == [False, True, False, True]
    assert first.SampleCount.eq(2).all()
    absent = table[table.Feature == proteins[1]]
    assert absent.Value.isna().all()
    assert absent.SampleCount.eq(0).all()


@pytest.mark.parametrize('low', [False, True])
def test_line_connects_observations_or_draws_unmarked_na_vertices(data, monkeypatch, low):
    captured = []
    def capture(fig, plt, **_):
        ax = fig.axes[0]
        captured.extend((line.get_xdata(), line.get_ydata(), line.get_markevery()) for line in ax.lines)
        assert [label.get_text() for label in ax.get_xticklabels()] == ['A_1', 'A_2', 'A_3', 'B_1']
        plt.close(fig)
        return b'figure'
    monkeypatch.setattr(single, '_to_png_bytes', capture)
    original = data.copy(deep=True)
    assert single.single_protein_lineplot_plot('protein', ['P1', 'P2', 'P3'], [], show_na_low=low) == b'figure'
    x, y, markers = captured[0]
    np.testing.assert_array_equal(x, [0, 1, 2, 3] if low else [0, 2])
    np.testing.assert_array_equal(y, [2., 0., 4., 0.] if low else [2., 4.])
    assert markers == ([0, 2] if low else None)
    assert len(captured[1][0]) == (4 if low else 0)
    assert captured[1][2] == ([] if low else None)
    # A real log2 zero remains a measured point; infinity is treated as missing.
    np.testing.assert_array_equal(captured[2][1], [0., 3., 0., -2.] if low else [0., 3., -2.])
    assert captured[2][2] == ([0, 1, 3] if low else None)
    pd.testing.assert_frame_equal(data, original)


@pytest.mark.parametrize('low', [False, True])
def test_completely_unmeasured_feature_still_renders_its_sample_axis(data, low):
    image = single.single_protein_lineplot_plot('protein', ['P2'], [], show_na_low=low, dpi=72)
    assert image.startswith(b'\x89PNG')


@pytest.mark.parametrize('low', [False, True])
def test_ai_context_distinguishes_baseline_vertices_from_measured_values(data, low):
    from app.services.ai_functions import single_protein_lineplot
    summary = single_protein_lineplot(mode={'proteins': ['P1'], 'showNaLow': low})['summary']
    assert 'n_values=2' in summary
    assert ('display_only_log2_0_vertices' in summary) == low
