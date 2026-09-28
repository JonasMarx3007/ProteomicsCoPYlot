"""Plotting helpers shared by every plot module.

The matplotlib/plotly/seaborn imports are deferred so the API can start
without the plotting stack installed and name the missing package when a
plot is first requested. The Plotly HTML wrapper is the one document every
interactive figure is served in; it used to exist five times with drifting
copies (different minimum heights, one with a ResizeObserver), so the same
figure resized differently depending on which page had drawn it.
"""

from __future__ import annotations

from app.services.html_security import GENERATED_HTML_META
from app.services.plot_webgl import force_svg_rendering


def get_plt():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        return plt
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "matplotlib is required for plot rendering. Install it with: pip install matplotlib"
        ) from exc


def get_plt_with_ticker():
    """pyplot and matplotlib.ticker together, for modules that format axes."""
    plt = get_plt()
    import matplotlib.ticker as mtick

    return plt, mtick


def get_plotly():
    """plotly.express and plotly.graph_objects, in that order."""
    try:
        import plotly.express as px
        import plotly.graph_objects as go

        return px, go
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "plotly is required for interactive plots. Install it with: pip install plotly"
        ) from exc


def get_plotly_go():
    return get_plotly()[1]


def get_plotly_px():
    return get_plotly()[0]


def get_sns():
    try:
        import seaborn as sns

        return sns
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "seaborn is required for heatmap rendering. Install it with: pip install seaborn"
        ) from exc


def plotly_html(fig) -> str:
    fig = force_svg_rendering(fig)
    bg = str(getattr(fig.layout, "paper_bgcolor", None) or "#fff").strip() or "#fff"
    body = fig.to_html(
        full_html=False,
        include_plotlyjs=True,
        config={"displaylogo": False, "responsive": True},
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"{GENERATED_HTML_META}"
        "<style>"
        f"html,body{{margin:0;padding:0;background:{bg};width:100%;height:100%;}}"
        "#plot-root{width:100%;height:100%;}"
        ".js-plotly-plot,.plotly-graph-div,.plot-container,.svg-container{width:100%!important;height:100%!important;min-height:420px;}"
        "</style>"
        "</head><body>"
        "<div id='plot-root'>"
        f"{body}"
        "</div>"
        "<script>"
        "(function(){"
        "function firstPlot(){"
        "return document.querySelector('.js-plotly-plot,.plotly-graph-div');"
        "}"
        "function resolveLayoutHeight(el){"
        "if(!el){return 0;}"
        "var value=0;"
        "if(el.layout && Number.isFinite(Number(el.layout.height))){value=Number(el.layout.height);}"
        "else if(el._fullLayout && Number.isFinite(Number(el._fullLayout.height))){value=Number(el._fullLayout.height);}"
        "return Math.max(0,value);"
        "}"
        "function resizePlot(){"
        "var el=firstPlot();"
        "if(!(el && window.Plotly)){return;}"
        "var root=document.getElementById('plot-root');"
        "var rootWidth=(root && Number(root.clientWidth))||0;"
        "var rootHeight=(root && Number(root.clientHeight))||0;"
        "var viewportWidth=Math.max(360,rootWidth,(window.innerWidth||0)-8);"
        "var viewportHeight=Math.max(420,rootHeight,(window.innerHeight||0)-8);"
        "var layoutHeight=resolveLayoutHeight(el);"
        "var nextHeight=Math.max(layoutHeight,viewportHeight);"
        "window.Plotly.relayout(el,{width:viewportWidth,height:nextHeight,autosize:true}).catch(function(){});"
        "window.Plotly.Plots.resize(el);"
        "}"
        "window.addEventListener('load', resizePlot);"
        "window.addEventListener('resize', resizePlot);"
        "if(window.ResizeObserver){"
        "var rootEl=document.getElementById('plot-root');"
        "if(rootEl){(new ResizeObserver(function(){resizePlot();})).observe(rootEl);}"
        "}"
        "setTimeout(resizePlot, 80);"
        "setTimeout(resizePlot, 260);"
        "setTimeout(resizePlot, 800);"
        "setTimeout(resizePlot, 1500);"
        "})();"
        "</script>"
        "</body></html>"
    )


def truncate_hover_text(value: object, max_len: int) -> str:
    """A hover label short enough to stay inside the tooltip. Empty reads "n/a"."""
    text = str(value or "").strip()
    if not text:
        return "n/a"
    if len(text) <= max_len:
        return text
    if max_len <= 1:
        return text[:1]
    return f"{text[: max_len - 1]}..."
