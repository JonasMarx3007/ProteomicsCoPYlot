"""Both notebook plots assign modification counts to full sample identities."""
import json
from pathlib import Path
import subprocess

import matplotlib.pyplot as plt
import pandas as pd
import pytest

from proteomicscopylot import notebook_functions as nb

ROOT = Path(__file__).resolve().parents[2]
CASES = [
    ('exact-collision', ['ctrl_01', 'treat_01'], ['ctrl_01', 'treat_01'], [1, 2]),
    ('metadata-order', ['ctrl_01', 'treat_01'], ['treat_01', 'ctrl_01'], [2, 1]),
    ('numeric-fallback', ['run_01', 'run_02'], ['sample_01', 'sample_02'], [1, 2]),
    ('mixed', ['ctrl_01', 'run_02'], ['ctrl_01', 'sample_02'], [1, 2]),
    ('data-collision', ['ctrl_01', 'treat_01'], ['sample_01', 'sample_02'], None),
    ('metadata-collision', ['run_01', 'run_02'], ['ctrl_01', 'treat_01'], None),
]


def run_r(data, meta, show_id, tmp_path):
    from app.services.r_runtime import detect_r_runtime
    data.to_csv(tmp_path / 'data.csv', index=False)
    meta.to_csv(tmp_path / 'meta.csv', index=False)
    script = tmp_path / 'plot.R'
    script.write_text('''
args <- commandArgs(TRUE)
source(args[1])
data <- read.csv(args[2], check.names=FALSE)
meta <- read.csv(args[3], check.names=FALSE)
pdf(NULL)
captured <- NULL
captured_labels <- NULL
barplot <- function(height, ...) {
  captured <<- height
  captured_labels <<- list(...)$names.arg
  graphics::barplot(height, ...)
}
result <- tryCatch({
  invisible(modification_plot(data, meta, id=as.logical(args[4]), legend=FALSE))
  list(counts=as.numeric(captured), labels=as.character(captured_labels))
}, error=function(e) list(error=conditionMessage(e)))
invisible(dev.off())
cat(jsonlite::toJSON(result, auto_unbox=TRUE))
''', encoding='utf-8')
    result = subprocess.run([detect_r_runtime()['executable'], str(script),
        str(ROOT / 'proteomicscopylot/notebook_functions.R'), str(tmp_path / 'data.csv'),
        str(tmp_path / 'meta.csv'), 'TRUE' if show_id else 'FALSE'],
        capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize('language', ['Python', pytest.param('R', marks=pytest.mark.requires_r('jsonlite'))])
@pytest.mark.parametrize('show_id', [False, True])
@pytest.mark.parametrize('case,runs,samples,expected', CASES, ids=[case[0] for case in CASES])
def test_modification_counts_follow_sample_identity(language, show_id, case, runs, samples, expected, tmp_path):
    data = pd.DataFrame({
        'File.Name': [runs[0], runs[0], runs[1], runs[1]],
        'Modified.Sequence': ['PEP(UniMod:35)A', 'PEP(UniMod:35)B'] * 2,
        'Precursor.Quantity': [100., 0., 100., 200.],
    })
    meta = pd.DataFrame({'sample': samples, 'condition': ['first', 'second']})
    original = data.copy(deep=True)
    original_meta = meta.copy(deep=True)
    if language == 'Python':
        try:
            fig = nb.modification_plot(data, meta, id=show_id, legend=False)
        except ValueError as error:
            result = {'error': str(error)}
        else:
            result = {'counts': [bar.get_height() for bar in fig.axes[0].patches],
                      'labels': [label.get_text() for label in fig.axes[0].get_xticklabels()]}
            plt.close(fig)
    else:
        result = run_r(data, meta, show_id, tmp_path)
    if expected is None:
        assert 'ambiguous' in result['error']
        assert 'ctrl_01' in result['error'] and 'treat_01' in result['error']
    else:
        assert 'error' not in result, result
        assert result['counts'] == expected
        labels = ['first_1', 'second_1']
        if show_id:
            labels = [f'{label}\n({nb.extract_id_or_number(sample)})' for label, sample in zip(labels, samples)]
        assert result['labels'] == labels
    pd.testing.assert_frame_equal(data, original)
    pd.testing.assert_frame_equal(meta, original_meta)
