DESTINATIONS = {
    "data.imputation": "Data / Imputation", "qc.coverage": "QC Pipeline / Coverage Plot", "qc.cv": "QC Pipeline / Cov Plot", "qc.boxplot": "QC Pipeline / Boxplot Intensity",
    "qc.pca": "QC Pipeline / Principal Component Analysis", "qc.correlation": "QC Pipeline / Correlation Plot",
    "completeness.missingPlot": "Completeness / Missing Value Plot", "completeness.heatmap": "Completeness / Missing Value Heatmap",
    "stats.volcano": "Statistical Analysis / Volcano Plot", "stats.ora": "Statistical Analysis / GO Enrichment (ORA)",
    "singleProtein.boxplot": "Single Protein / Protein Boxplot", "singleProtein.lineplot": "Single Protein / Protein Lineplot",
    "singleProtein.heatmap": "Single Protein / Phosphosites on Protein Heatmap", "phospho.ksea": "Phospho-specific / KSEA",
    "phospho.distribution": "Phospho-specific / Phosphosite Distribution", "comparison.pearson": "Comparison / Pearson Correlation",
    "summary.report": "Summary / Report", "analysis.canvas": "Analysis",
}


PLAN = '{"task":"current_plot"}'


VALID = '{"observations":["e0r0"]}'


def _control(id, label, type="number", value="0", **extra):
    return {"id": id, "label": label, "type": type, "value": value, "permission": "view",
            "appearance": label not in {"Test type", "Protein / Site"}, **extra}


def _labels_view():
    return {"module": "singleProtein.boxplot", "mode": {"kind": "phospho"}, "advancedOptions": True, "controls": [
        _control("rot", "X axis / X tick label rotation", value="0"),
        _control("dpi", "DPI", value="300"),
        _control("width", "Width (cm)", value="20"),
        _control("nameA", "Condition names / A", "text", ""),
        _control("nameB", "Condition names / B", "text", ""),
        _control("colA", "Condition colors / A", "color", "#64748b"),
        _control("colB", "Condition colors / B", "color", "#64748b"),
    ]}


def _site_view(value="K17"):
    return {"module": "singleProtein.boxplot", "mode": {"kind": "phospho"},
            "controls": [_control("site", "Protein / Site", "select", value,
                                  options=[f"K{i}" for i in range(40)], optionCount=80)]}


def _styling_view():
    return {"module": "singleProtein.boxplot", "advancedOptions": True, "controls": [
        {"id": "top", "label": "Top border", "type": "checkbox", "value": True, "permission": "view", "appearance": True},
        {"id": "rot", "label": "X tick label rotation", "type": "number", "value": "0", "permission": "view", "appearance": True},
        {"id": "color", "label": "Condition colour / A", "type": "color", "value": "#1f77b4", "permission": "view", "appearance": True},
        {"id": "extra", "label": "Title", "type": "text", "value": "", "permission": "view", "appearance": True},
        {"id": "more", "label": "Subtitle", "type": "text", "value": "", "permission": "view", "appearance": True},
    ]}


def _view(module="data.annotation", **extra):
    return {"module": module, "mode": {"kind": "phospho"}, "destinations": DESTINATIONS, **extra}


def _volcano_view():
    return {"module": "stats.volcano", "mode": {"kind": "phospho"}, "destinations": {"stats.volcano": "Volcano", "qc.cv": "CV"},
            "controls": [_control("test", "Test type", "select", "unpaired", options=["unpaired", "unpaired_welch", "paired"], optionCount=3)]}
