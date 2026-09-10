from __future__ import annotations

import io


def to_png_bytes(fig, plt, dpi: int = 150, tight: bool = True) -> bytes:
    buf = io.BytesIO()
    save_kwargs = {"format": "png", "dpi": max(72, int(dpi))}
    if tight:
        save_kwargs["bbox_inches"] = "tight"
    if getattr(fig, "_copylot_transparent_background", False):
        save_kwargs["transparent"] = True
    fig.savefig(buf, **save_kwargs)
    plt.close(fig)
    return buf.getvalue()


def cm_to_inch(value_cm: float) -> float:
    return max(1.0, float(value_cm) / 2.54)


def cm_to_px(value_cm: float) -> int:
    return max(320, int(round((cm_to_inch(value_cm) * 96.0))))
