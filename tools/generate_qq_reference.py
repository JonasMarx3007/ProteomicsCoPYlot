"""Rebuild the synthetic Q-Q reference: python tools/generate_qq_reference.py."""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import stats


def create_figure():
    probabilities = (np.arange(300) + 0.5) / 300
    examples = [
        ("Normal — a straight line", stats.norm.ppf(probabilities)),
        ("Right-skewed — a curve", stats.lognorm.ppf(probabilities, s=0.7)),
        ("Heavy tails — both ends depart", stats.t.ppf(probabilities, df=3)),
    ]
    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 11}):
        figure, axes = plt.subplots(1, 3, figsize=(15, 4.8), layout="constrained")
        for axis, (title, values) in zip(axes, examples):
            (theoretical, ordered), (slope, intercept, _) = stats.probplot(values)
            axis.scatter(theoretical, ordered, s=10, color="#334155", alpha=0.8, linewidths=0)
            axis.plot(theoretical, intercept + slope * theoretical, color="#2563eb", linewidth=2)
            axis.set(title=title, xlabel="Theoretical normal quantiles", ylabel="Ordered values")
            axis.set_axisbelow(True)
            axis.grid(color="#e2e8f0", linewidth=0.8)
            axis.spines[["top", "right"]].set_visible(False)
            for spine in axis.spines.values():
                spine.set_color("#cbd5e1")
        figure.supxlabel("Synthetic distribution examples • blue lines: least-squares fits", fontsize=10)
    return figure


if __name__ == "__main__":
    output = Path(__file__).resolve().parents[1] / "frontend/public/assets/qqnorm.jpg"
    figure = create_figure()
    figure.savefig(output, dpi=160, pil_kwargs={"quality": 95})
    plt.close(figure)
