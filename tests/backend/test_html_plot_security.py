from html.parser import HTMLParser
import importlib

import pandas as pd
import plotly.graph_objects as go
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import report_function
from app.services.html_security import GENERATED_HTML_CSP


ATTACK = "</script><script id='injected'>window.injected=1</script><img src=x onerror='window.injected=2'>"


class Tags(HTMLParser):
    def __init__(self, document):
        super().__init__()
        self.tags = []
        self.feed(document)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


@pytest.mark.parametrize('module', ['plot_images', 'stats_tools', 'phospho_tools', 'peptide_tools', 'comparison_tools'])
def test_plotly_labels_cannot_break_out_of_script_or_add_event_handlers(module):
    # Every field here carries text straight out of an uploaded table: protein
    # and gene names into `text` and `hovertext`, condition names into `name`
    # and the tick labels, the whole identifier into `customdata`. The figure
    # JSON is embedded inside an inline `<script>`, so the only thing between an
    # uploaded identifier and executable script is plotly's serialiser escaping
    # `<` and `/`. That is a third-party guarantee, which is exactly the kind
    # worth pinning.
    fig = go.Figure(go.Scatter(
        x=[1], y=[2], text=[ATTACK], mode='markers+text',
        hovertext=[ATTACK], name=ATTACK, customdata=[ATTACK],
        hovertemplate='%{hovertext}<extra></extra>',
    ))
    fig.update_layout(title=ATTACK)
    fig.update_xaxes(tickmode='array', tickvals=[1], ticktext=[ATTACK], title=ATTACK)
    fig.update_yaxes(title=ATTACK)
    document = importlib.import_module(f'app.services.{module}')._plotly_html(fig)
    tags = Tags(document).tags
    assert [attrs['content'] for tag, attrs in tags if tag == 'meta' and attrs.get('http-equiv') == 'Content-Security-Policy'] == [GENERATED_HTML_CSP]
    assert not any(attrs.get('id') == 'injected' for _, attrs in tags)
    assert not any(key.startswith('on') for _, attrs in tags for key in attrs)
    assert not any(tag == 'img' for tag, _ in tags)
    # And the raw sequence never appears at all: one script element, opened and
    # closed once, with the attack text escaped inside it.
    assert document.count('<script') == document.count('</script>')
    assert "</script><script id='injected'>" not in document


def test_report_text_and_nested_plot_boundary():
    document = report_function._table_to_html(ATTACK, pd.DataFrame({'label': [ATTACK]}))
    assert not any(tag in {'script', 'img'} for tag, _ in Tags(document).tags)
    frames = Tags(report_function._plotly_to_iframe('<script>/* plot */</script>')).tags
    assert frames[0][1]['sandbox'] == 'allow-scripts allow-downloads'
    assert frames[0][1]['srcdoc'] == '<script>/* plot */</script>'


def test_direct_plot_html_is_sandboxed_but_api_json_is_not():
    table = 'Kinase,Log2(Frequency Factor),Adjusted p-value\nAKT1,2,0.01\n'
    with TestClient(app) as client:
        response = client.post('/api/plots/phospho/ksea-volcano.html', files={
            'fileSt': ('st.csv', table, 'text/csv'),
            'fileTnc': ('y.csv', table, 'text/csv'),
        }, data={"condition1": "A", "condition2": "B", "condition1Control": "C", "condition2Control": "D"})
        assert response.status_code == 200, response.text
        assert "(A - C) - (B - D)" in response.text
        assert response.headers['content-security-policy'] == GENERATED_HTML_CSP + '; sandbox allow-scripts allow-downloads'
        assert 'content-security-policy' not in client.get('/api/health').headers
