"""Python and R heatmaps select whole protein-group members, never substrings."""
import json
from pathlib import Path
import subprocess

import matplotlib.pyplot as plt
import pandas as pd
import pytest

from proteomicscopylot import notebook_functions as nb

ROOT = Path(__file__).resolve().parents[2]
GROUPS = ['P12345', ' Q67890 ; p12345 ', 'AP12345X', 'P12345-2', None, '',
          'P.123', 'PX123', 'P[123]', ' ; P12345 ; ', 'Q67890']
CASES = [('P12345', [0, 1, 9]), (' \t p12345 \t ', [0, 1, 9]),
         (' q67890 ', [1, 10]), ('AP12345X', [2]), ('p12345-2', [3]),
         ('P.123', [6]), ('P[123]', [8]), ('P123', []), ('   ', []), (None, [])]


def r_heatmap(data, meta, query, tmp_path):
    from app.services.r_runtime import detect_r_runtime
    data.to_csv(tmp_path / 'data.csv', index=False)
    meta.to_csv(tmp_path / 'meta.csv', index=False)
    script = tmp_path / 'heatmap.R'
    script.write_text('''
args <- commandArgs(TRUE)
source(args[1])
data <- read.csv(args[2], check.names=FALSE, na.strings="")
meta <- read.csv(args[3], check.names=FALSE)
query <- jsonlite::fromJSON(args[4])
pdf(NULL)
captured <- NULL
original_plot <- .plot_heatmap
.plot_heatmap <- function(m, ...) {
  captured <<- m
  original_plot(m, ...)
}
result <- tryCatch({
  invisible(phossite_on_prot_regulation(data, meta, query, id=FALSE))
  list(rows=rownames(captured), values=unname(captured))
}, error=function(e) list(error=conditionMessage(e)))
invisible(dev.off())
cat(jsonlite::toJSON(result, auto_unbox=FALSE, matrix="rowmajor"))
''', encoding='utf-8')
    result = subprocess.run([detect_r_runtime()['executable'], str(script),
        str(ROOT / 'proteomicscopylot/notebook_functions.R'), str(tmp_path / 'data.csv'),
        str(tmp_path / 'meta.csv'), json.dumps(query)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize('language', ['Python', pytest.param('R', marks=pytest.mark.requires_r('jsonlite'))])
@pytest.mark.parametrize('query,expected', CASES)
def test_heatmap_selects_exact_members(language, query, expected, tmp_path, monkeypatch):
    data = pd.DataFrame({'Protein_group': GROUPS,
        'PTM_Collapse_key': [f'protein~S{i}_M1' for i in range(len(GROUPS))],
        'A1': [10. + i for i in range(len(GROUPS))],
        'B1': [20. + i for i in range(len(GROUPS))]})
    meta = pd.DataFrame({'sample': ['A1', 'B1'], 'condition': ['A', 'B']})
    original = data.copy(deep=True)
    original_meta = meta.copy(deep=True)
    if language == 'Python':
        captured = []
        plot = nb.sns.heatmap

        def capture(frame, **kwargs):
            captured.append(frame.copy())
            return plot(frame, **kwargs)

        monkeypatch.setattr(nb.sns, 'heatmap', capture)
        try:
            fig = nb.phossite_on_prot_regulation(data, meta, query, id=False)
        except ValueError as error:
            result = {'error': [str(error)]}
        else:
            result = {'rows': captured[0].index.tolist(), 'values': captured[0].values.tolist()}
            plt.close(fig)
    else:
        result = r_heatmap(data, meta, query, tmp_path)
    if expected:
        assert 'error' not in result, result
        assert result['rows'] == [f'S{i}_M1' for i in expected]
        assert result['values'] == [[10. + i, 20. + i] for i in expected]
    else:
        assert 'No data found for protein' in result['error'][0]
    pd.testing.assert_frame_equal(data, original)
    pd.testing.assert_frame_equal(meta, original_meta)
