"""Deterministic, self-contained notebook archives built from trusted plot recipes."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from importlib.metadata import version
import io
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import platform
import re
import sys
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

import pandas as pd

from app.app_version import APP_VERSION
from app.services.notebook_source import NotebookSource
from app.services.notebook_limits import notebook_memory_budgets

_DISTRIBUTIONS = {"PIL": "Pillow", "sklearn": "scikit-learn", "Bio": "biopython",
                  "matplotlib_venn": "matplotlib-venn", "umap": "umap-learn"}


def portable_filename(value: str) -> str:
    return PureWindowsPath(PurePosixPath(value).name).name.replace("\x00", "")


def _json(value) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False).encode("utf-8")


def _cell(kind: str, text: str) -> dict:
    result = {"cell_type": kind, "metadata": {}, "source": text.splitlines(keepends=True)}
    if kind == "code":
        result.update(execution_count=None, outputs=[])
    return result


def dataframe_bytes(frame: pd.DataFrame) -> bytes:
    """Parquet preserves floating-point values, nulls, column types and the index."""
    stream = io.BytesIO()
    portable = frame.copy(deep=False)
    portable.attrs = {}  # Input-file paths or private importer state are not scientific columns.
    portable.to_parquet(stream, engine="pyarrow", index=True)
    return stream.getvalue()


def _fonts_used(value) -> dict[str, str]:
    """The face each font choice in these settings resolved to on this server."""
    from app.services.plot_styling import FONT_ELEMENT_KEYS, FONT_KEY, PLOT_FONTS, installed_family
    keys = {FONT_KEY, *FONT_ELEMENT_KEYS.values()}
    found: dict[str, str] = {}

    def walk(item):
        if isinstance(item, dict):
            for key, child in item.items():
                choice = str(child).strip().lower() if key in keys and child is not None else ''
                if choice in PLOT_FONTS:
                    found[choice] = installed_family(PLOT_FONTS[choice][0])
                else:
                    walk(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                walk(child)

    walk(value)
    return dict(sorted(found.items()))


# The last cell: every figure or text output is compared with the one CoPYlot
# produced, so "it ran" can no longer be mistaken for "it reproduced".
_VERIFY_CELL = """# Compare every output with the one CoPYlot produced.
results = []
for original in sorted(Path('resources').rglob('original.*')):
    folder = original.parent.relative_to('resources')
    output_dir = Path('outputs') / folder if folder.parts else Path('.')
    reproduced = output_dir / ('reproduced' + original.suffix)
    candidates = sorted(output_dir.glob('reproduced*' + original.suffix))
    if not reproduced.exists() and len(candidates) == 1:
        reproduced = candidates[0]
    if not reproduced.exists():
        results.append(('not written', original))
    else:
        results.append(('identical' if reproduced.read_bytes() == original.read_bytes() else 'DIFFERENT', reproduced))
for status, path in results:
    print(f'{status:>11}  {path}')
if not results:
    print('No figure to compare; the tables were checked exactly above.')
elif all(status == 'identical' for status, _ in results):
    print('Every output is byte-identical to the one CoPYlot produced.')
else:
    from matplotlib import font_manager
    installed = {font.name for font in font_manager.fontManager.ttflist}
    missing = sorted({face for face in manifest.get('fonts', {}).values() if face not in installed})
    hint = (f' The export used the font(s) {", ".join(missing)}, which this machine does not have; '
            'install them or the text is drawn in another face.' if missing else '')
    raise AssertionError('Some outputs differ from the ones CoPYlot produced. The numbers were checked '
        'exactly above, so the difference is in the drawing: most often a different font, or package '
        'versions other than those in requirements.txt.' + hint)
"""


@dataclass(frozen=True)
class NotebookRecipe:
    # Only server-owned adapters may supply executable cells or function names.
    plot_name: str
    source: NotebookSource
    calculation: str
    settings: dict
    provenance: dict
    original_filename: str
    resources: dict[str, bytes]
    uses_imputed_input: bool = False
    imputation_recipe: str = ""
    preparation: str = "data = pd.read_parquet(RESOURCES / 'input.parquet')"
    input_explanation: str = "The exact input matrix is included to preserve the displayed figure's inputs."
    calculation_sections: tuple[tuple[str, str], ...] = ()


def build_notebook_archive(recipe: NotebookRecipe) -> tuple[str, bytes]:
    if recipe.uses_imputed_input and not recipe.imputation_recipe.strip():
        raise ValueError("Imputed input requires its documented reconstruction recipe.")
    for name in recipe.resources:
        path = PurePosixPath(name)
        if not name or path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
            raise ValueError("Resources must have safe relative archive names.")
    if "input.parquet" not in recipe.resources or "metadata.parquet" not in recipe.resources:
        raise ValueError("The exact input matrix and metadata must be captured.")
    if sum(map(len, recipe.resources.values())) > notebook_memory_budgets()[0]:
        raise ValueError("Notebook resources exceed COPYLOT_NOTEBOOK_SESSION_MEMORY_MB; increase it on a suitably sized machine.")
    for code in (recipe.preparation, recipe.calculation, *(code for _, code in recipe.calculation_sections)):
        compile(code, "notebook", "exec")
    packages = {"pandas", "pyarrow"}
    packages.update(_DISTRIBUTIONS.get(name, name) for name in recipe.source.imports
                    if name not in sys.stdlib_module_names)
    # Notebook hosting/display are not installed in the production server.
    requirements = []
    for package in sorted(packages - {"jupyterlab", "IPython", "ipython"}):
        requirements.append(f"{package}=={version(package)}")
    requirements.extend(["ipython>=8,<10", "jupyterlab>=4,<5"])
    # The pins are the server's exact versions, which need its Python or newer.
    python_minimum = ".".join(platform.python_version_tuple()[:2])
    python_note = (f"Python {python_minimum} or newer is required (exported with Python "
                   f"{platform.python_version()}); the pinned versions do not install on older Python.")
    filename = portable_filename(recipe.original_filename)
    settings = _json(recipe.settings)
    resources = {f"resources/{name}": value for name, value in recipe.resources.items()}
    resources["resources/settings.json"] = settings
    resources["functions.py"] = recipe.source.code.encode("utf-8")
    manifest = {
        "schemaVersion": 1, "toolVersion": APP_VERSION,
        "pythonVersion": platform.python_version(), "platform": platform.system(),
        "originalFilename": filename, "plot": recipe.plot_name,
        "usesImputedInput": recipe.uses_imputed_input, "provenance": recipe.provenance,
        "requirements": requirements, "pythonRequires": f">={python_minimum}",
        # A report keeps each section's settings in its own file.
        "fonts": _fonts_used([recipe.settings, *(json.loads(value) for name, value in recipe.resources.items()
                                                 if name.endswith("settings.json"))]),
        "sha256": {name: sha256(value).hexdigest() for name, value in sorted(resources.items())},
    }
    # Values from filenames, labels and controls live in JSON, never executable cells.
    notebook = {
        "nbformat": 4, "nbformat_minor": 4,
        "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                     "language_info": {"name": "python", "version": platform.python_version()}},
        "cells": [
            _cell("markdown", f"# {recipe.plot_name}\n\nCoPYlot {APP_VERSION}.\n\n"
                  "Extract the whole ZIP, install requirements.txt and run the cells in order. "
                  "The manifest records the exported inputs and implementation. " + python_note
                  + " The last cell compares every output with the one CoPYlot produced.\n\n" + recipe.input_explanation),
            _cell("code", "import sys\n"
                  f"if sys.version_info < {tuple(int(part) for part in python_minimum.split('.'))!r}:\n"
                  f"    raise RuntimeError({python_note!r})\n"
                  "from pathlib import Path\nimport json\nimport hashlib\nimport pandas as pd\n"
                  "import functions\n\nRESOURCES = Path('resources')\n"
                  + (f"# Original filename: {json.dumps(filename, ensure_ascii=True)}\n" if filename else "")
                  + ("data_path = Path('YOUR_ORIGINAL_DATA_FILE')  # Required: select your original uploaded file.\n"
                     if recipe.provenance.get('inputReplay') == 'original-file' else
                     "# Original-file paths, where needed, are configured in the preparation cell below.\n") +
                  "manifest = json.loads(Path('manifest.json').read_text(encoding='utf-8'))\n"
                  "verify_original_export = True  # Set False only after intentionally editing exported files.\n"
                  "if verify_original_export:\n"
                  "    for name, expected in manifest['sha256'].items():\n"
                  "        actual = hashlib.sha256(Path(name).read_bytes()).hexdigest()\n"
                  "        if actual != expected:\n"
                  "            raise ValueError(f'Export file changed: {name}')\n"
                  "settings = json.loads((RESOURCES / 'settings.json').read_text(encoding='utf-8'))\n"
                  "metadata = pd.read_parquet(RESOURCES / 'metadata.parquet')\n"),
        ],
    }
    if recipe.uses_imputed_input:
        notebook["cells"].append(_cell("code", "# Imputation was already performed in CoPYlot. Do not draw values again.\n"
            "# The following documents how the captured input was produced:\n" + "\n".join(
                "# " + line for line in recipe.imputation_recipe.splitlines()) + "\n"))
    notebook["cells"].append(_cell("code", recipe.preparation + "\n"))
    if recipe.calculation_sections:
        for heading, code in recipe.calculation_sections:
            notebook["cells"].extend([_cell("markdown", heading), _cell("code", code + "\n")])
    else:
        notebook["cells"].append(_cell("code", recipe.calculation + "\n"))
    notebook["cells"].append(_cell("code", _VERIFY_CELL))
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", recipe.plot_name).strip("_")[:100] or "Plot"
    license_root = Path(sys._MEIPASS) / "notebook_sources" if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[3]
    files = {**resources, "LICENSE": (license_root / "LICENSE").read_bytes(), "manifest.json": _json(manifest),
             "requirements.txt": (f"# {python_note}\n" + "\n".join(requirements) + "\n").encode(),
             f"{stem}.ipynb": _json(notebook)}
    stream = io.BytesIO()
    with ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, content)
    return stem + ".zip", stream.getvalue()
