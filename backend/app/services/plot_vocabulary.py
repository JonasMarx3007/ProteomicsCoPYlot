"""The advanced panel's vocabularies: marker shapes, fonts, themes and line styles.

These are the names the frontend panel, the request schema
(`app.schemas.plot_settings`) and both renderers (matplotlib figures and
plotly interactive plots) agree on. Nothing here imports a renderer, so the
schema can build its `Literal` types from these without pulling in
`plot_styling` and everything matplotlib behind it.
"""
from __future__ import annotations


# One name per shape, and the spelling each renderer wants for it. A shape set
# in the advanced panel has to draw the same marker in the figure and in the
# interactive plot beside it, and matplotlib and plotly agree on none of their
# own names -- so the panel's vocabulary is neither of theirs.
MARKER_SHAPES: dict[str, tuple[str, str]] = {
    # name:        (matplotlib, plotly)
    "circle": ("o", "circle"),
    "square": ("s", "square"),
    "diamond": ("D", "diamond"),
    "triangle-up": ("^", "triangle-up"),
    "triangle-down": ("v", "triangle-down"),
    "cross": ("P", "cross"),
    "x": ("X", "x"),
    "star": ("*", "star"),
    "pentagon": ("p", "pentagon"),
    "hexagon": ("h", "hexagon"),
}


# The faces a figure may be drawn in, and what each renderer has to be told to
# get one. Journals ask for Arial, Helvetica or Times New Roman; what is
# installed in this image is the Liberation family, whose metrics are identical
# to those three, so a figure drawn here measures the same as one drawn on a
# machine that has the originals.
#
# Every list ends at a DejaVu face, which ships with matplotlib. A family name
# matplotlib cannot resolve is a warning on stderr and a silent substitution --
# the figure comes back in the wrong face and nothing in the response says so --
# and ending each list at something that is certainly present means there is
# never anything to substitute.
PLOT_FONTS: dict[str, tuple[tuple[str, ...], str]] = {
    # name:          (matplotlib family list,                       plotly CSS stack)
    "helvetica": (
        ("Liberation Sans", "Helvetica", "Arial", "DejaVu Sans"),
        "Helvetica, Arial, 'Liberation Sans', sans-serif",
    ),
    "times": (
        ("Liberation Serif", "Times New Roman", "Times", "DejaVu Serif"),
        "'Times New Roman', Times, 'Liberation Serif', serif",
    ),
    "courier": (
        ("Liberation Mono", "Courier New", "Courier", "DejaVu Sans Mono"),
        "'Courier New', Courier, 'Liberation Mono', monospace",
    ),
    "dejavu-sans": (("DejaVu Sans",), "'DejaVu Sans', Verdana, sans-serif"),
    "dejavu-serif": (("DejaVu Serif",), "'DejaVu Serif', Georgia, serif"),
}


PLOT_THEME_MAP: dict[str, dict[str, str]] = {
    "white": {
        "mpl_figure": "#ffffff",
        "mpl_axes": "#ffffff",
        "text": "#111827",
        "axis": "#111827",
        "grid": "#e5e7eb",
        "plotly_template": "plotly_white",
        "plotly_paper": "#ffffff",
        "plotly_plot": "#ffffff",
    },
    "minimal": {
        "mpl_figure": "#ffffff",
        "mpl_axes": "#ffffff",
        "text": "#111827",
        "axis": "#111827",
        "grid": "#f1f5f9",
        "plotly_template": "simple_white",
        "plotly_paper": "#ffffff",
        "plotly_plot": "#ffffff",
    },
    "soft_gray": {
        "mpl_figure": "#f8fafc",
        "mpl_axes": "#ffffff",
        "text": "#0f172a",
        "axis": "#334155",
        "grid": "#cbd5e1",
        "plotly_template": "plotly_white",
        "plotly_paper": "#f8fafc",
        "plotly_plot": "#ffffff",
    },
    "presentation": {
        "mpl_figure": "#ffffff",
        "mpl_axes": "#ffffff",
        "text": "#020617",
        "axis": "#020617",
        "grid": "#d1d5db",
        "plotly_template": "presentation",
        "plotly_paper": "#ffffff",
        "plotly_plot": "#ffffff",
    },
    "dark": {
        "mpl_figure": "#111827",
        "mpl_axes": "#0f172a",
        "text": "#e5e7eb",
        "axis": "#cbd5e1",
        "grid": "#334155",
        "plotly_template": "plotly_dark",
        "plotly_paper": "#111827",
        "plotly_plot": "#0f172a",
    },
}


LINE_STYLE_NAMES = {"solid", "dashed", "dotted", "dashdot"}
