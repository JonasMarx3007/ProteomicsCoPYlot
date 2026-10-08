"""Cross-pipeline checks for partial imputation and non-default Venn detection."""
import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.services import functions
from app.services.comparison_tools import _feature_set_from_condition
from app.services.phosprot_tools import transform_phosprot
from proteomicscopylot import notebook_functions as notebook


def _sites():
    samples = ['A1', 'A2', 'B1', 'B2']
    meta = pd.DataFrame({'sample': samples, 'condition': ['A', 'A', 'B', 'B']})
    observed = pd.DataFrame({
        'Protein_group': ['P', 'P'], 'Gene_group': ['G', 'G'],
        'UPD_seq': ['AS', 'AT'], 'PTM_localization': [0.9, 0.95], 'PTM_Collapse_key': ['P_S1', 'P_T2'],
        'A1': [10., np.nan], 'A2': [np.nan, np.nan], 'B1': [11., 12.], 'B2': [13., 14.],
    })
    supplied = observed.copy()
    supplied[samples] = supplied[samples].fillna(3.)
    return samples, meta, observed, supplied


def _mean_sites():
    samples, meta, _, _ = _sites()
    supplied = pd.DataFrame({
        'Protein_group': ['P', 'P', 'P', 'Q'], 'Gene_group': ['G', 'G', 'G', 'H'],
        'UPD_seq': ['AS', 'AT', 'AY', 'AS'], 'PTM_localization': [.9] * 4,
        'PTM_Collapse_key': ['P_S1', 'P_T2', 'P_Y3', 'Q_S1'],
        'A1': [10., 20., 1., 2.], 'A2': [12., 22., 2., 3.],
        'B1': [11., 21., 3., 4.], 'B2': [13., 23., np.nan, np.nan],
    })
    observed = supplied.copy()
    observed.loc[2, 'A1'] = np.nan  # Imputed, but excluded from every mean.
    observed.loc[1, 'A2'] = np.nan  # One of two contributing sites was imputed.
    observed.loc[:1, 'B1'] = np.nan  # Both contributing sites were imputed.
    return samples, meta, observed, supplied


@pytest.mark.parametrize('scale', ['linear', 'log2'])
def test_mean_provenance_counts_only_contributors(scale):
    samples, meta, observed, supplied = _mean_sites()
    frames = []
    for collapse, module in ((transform_phosprot, functions), (notebook.transform_phosprot, notebook)):
        frame = collapse(supplied, meta, mode='mean', data_scale=scale, coverage_data=observed)
        frames.append(frame)
        p = frame.set_index('Phosphoprotein').loc['P']
        assert p[[f'site_supplied__{s}' for s in samples]].tolist() == [2, 2, 2, 2]
        assert p[[f'site_measured__{s}' for s in samples]].tolist() == [2, 1, 0, 2]
        assert p[[f'site_observed__{s}' for s in samples]].tolist() == [2, 2, 1, 2]
        assert p['site_num_eligible'] == 3
        states = module.site_observed_imputed_mask(frame, samples)
        assert states.iloc[0].tolist() == [0, 2, 1, 0]
        assert states.iloc[1].tolist() == [-1] * 4  # No complete site for Q.
        counts = module.imputed_value_counts(states, {'A': samples[:2], 'B': samples[2:]})
        assert counts[['n_measured__A', 'n_fully_imputed__A', 'n_partially_imputed__A']].iloc[0].tolist() == [1, 0, 1]
        assert counts[['n_measured__B', 'n_fully_imputed__B', 'n_partially_imputed__B']].iloc[0].tolist() == [1, 1, 0]
        expected = np.log2((np.exp2(supplied.loc[:1, samples]) if scale == 'log2'
                            else supplied.loc[:1, samples]).mean(axis=0))
        np.testing.assert_allclose(p[samples].astype(float), expected)
    pd.testing.assert_frame_equal(*frames, check_dtype=False)


@pytest.mark.requires_r('jsonlite')
def test_mean_contributor_counts_match_r(tmp_path, rscript):
    samples, meta, observed, supplied = _mean_sites()
    for name, frame in [('observed', observed), ('supplied', supplied), ('metadata', meta)]:
        frame.to_csv(tmp_path / f'{name}.csv', index=False)
    source = Path(__file__).resolve().parents[2] / 'proteomicscopylot/notebook_functions.R'
    script = f'''
source({json.dumps(source.as_posix())})
setwd({json.dumps(tmp_path.as_posix())})
observed <- read.csv('observed.csv', check.names=FALSE)
supplied <- read.csv('supplied.csv', check.names=FALSE)
meta <- read.csv('metadata.csv', check.names=FALSE)
for (scale in c('linear', 'log2')) {{
  collapsed <- transform_phosprot(supplied, meta, mode='mean', data_scale=scale, coverage_data=observed)
  states <- site_observed_imputed_mask(collapsed, meta$sample)
  stopifnot(all(states[1,] == c(0,2,1,0)), all(states[2,] == -1))
  write.csv(collapsed, paste0(scale, '.csv'), row.names=FALSE)
}}
'''
    result = subprocess.run([rscript, '-e', script], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    for scale in ('linear', 'log2'):
        expected = transform_phosprot(supplied, meta, mode='mean', data_scale=scale, coverage_data=observed)
        actual = pd.read_csv(tmp_path / f'{scale}.csv')
        columns = samples + [c for c in expected.columns if c.startswith('site_')]
        np.testing.assert_allclose(actual[columns], expected[columns], equal_nan=True)


@pytest.mark.parametrize('mode', ['mean', 'sum_ignore_na', 'sum_propagate_na', 'robust_site_median'])
def test_collapse_and_contribution_categories_match_python(mode):
    samples, meta, observed, supplied = _sites()
    backend = transform_phosprot(supplied, meta, mode=mode, data_scale='log2', coverage_data=observed)
    package = notebook.transform_phosprot(supplied, meta, mode=mode, data_scale='log2', coverage_data=observed)
    pd.testing.assert_frame_equal(backend, package, check_dtype=False)
    groups = {'A': samples[:2], 'B': samples[2:]}
    for module, frame in ((functions, backend), (notebook, package)):
        counts = module.imputed_value_counts(module.site_observed_imputed_mask(frame, samples), groups)
        assert counts[['n_measured__A', 'n_fully_imputed__A', 'n_partially_imputed__A']].iloc[0].tolist() == [0, 1, 1]
        assert counts[['n_measured__B', 'n_fully_imputed__B', 'n_partially_imputed__B']].iloc[0].tolist() == [2, 0, 0]


@pytest.mark.parametrize('minimum', [1, 2])
def test_venn_membership_matches_backend(minimum, monkeypatch):
    samples, meta, _, supplied = _sites()
    data = supplied[samples].copy()
    data.index = ['X', 'Y']
    data.insert(0, 'ProteinNames', data.index)
    data.loc['Y', 'A2'] = np.nan
    captured = []
    monkeypatch.setattr(notebook, 'venn2', lambda sets, **kw: captured.extend(sets))
    figure = notebook.overlap_plot_condition(data, meta, 'A', 'B', min_present=minimum)
    notebook.plt.close(figure)
    assert captured == [_feature_set_from_condition(data, meta, 'ProteinNames', c, minimum) for c in ['A', 'B']]


@pytest.mark.requires_r('jsonlite')
def test_r_contribution_categories_and_venn_options_match(tmp_path, rscript):
    samples, meta, observed, supplied = _sites()
    for name, frame in [('observed', observed), ('supplied', supplied), ('metadata', meta)]:
        frame.to_csv(tmp_path / f'{name}.csv', index=False)
    source = Path(__file__).resolve().parents[2] / 'proteomicscopylot/notebook_functions.R'
    script = f'''
source({json.dumps(source.as_posix())})
setwd({json.dumps(tmp_path.as_posix())})
observed <- read.csv('observed.csv', check.names=FALSE)
supplied <- read.csv('supplied.csv', check.names=FALSE)
meta <- read.csv('metadata.csv', check.names=FALSE)
for (mode in c('mean', 'sum_ignore_na', 'sum_propagate_na', 'robust_site_median')) {{
  collapsed <- transform_phosprot(supplied, meta, mode=mode, data_scale='log2', coverage_data=observed)
  counts <- imputed_value_counts(site_observed_imputed_mask(collapsed, meta$sample), list(A=c('A1','A2'), B=c('B1','B2')))
  stopifnot(counts$n_measured__A == 0, counts$n_fully_imputed__A == 1, counts$n_partially_imputed__A == 1,
            counts$n_measured__B == 2, counts$imputed_values == 2)
  write.csv(collapsed, paste0(mode, '.csv'), row.names=FALSE)
}}
.venn_base <- function(sets, ...) {{ captured <<- sets; invisible(NULL) }}
data <- supplied[, meta$sample]; rownames(data) <- c('X','Y'); data$A2[2] <- NA
for (minimum in 1:2) {{
  overlap_plot_condition(data, meta, 'A', 'B', min_present=minimum)
  stopifnot(identical(unname(captured[[1]]), if (minimum == 1) c('X','Y') else 'X'))
}}
'''
    result = subprocess.run([rscript, '-e', script], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    for mode in ['mean', 'sum_ignore_na', 'sum_propagate_na', 'robust_site_median']:
        expected = transform_phosprot(supplied, meta, mode=mode, data_scale='log2', coverage_data=observed)
        actual = pd.read_csv(tmp_path / f'{mode}.csv')
        np.testing.assert_allclose(actual[samples], expected[samples], rtol=1e-12)
