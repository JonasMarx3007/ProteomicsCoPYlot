from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

import pandas as pd
import pytest

from app.services.notebook_archive import NotebookRecipe, build_notebook_archive, dataframe_bytes
from app.services.notebook_source import extract_notebook_source
from app.services.notebook_qc import _source
from app.services.notebook_snapshots import NotebookSnapshots

ROOT = Path(__file__).resolve().parents[3]


def test_source_subset_closes_over_helpers_and_constants_without_running_module():
    source = '''
import math
import os
FACTOR = 2
def unused():
    raise RuntimeError("must not be included")
def helper(x):
    return math.sqrt(x) * FACTOR
def plot(x):
    return helper(x)
raise RuntimeError("module import must never run")
'''
    result = extract_notebook_source(source, ("plot",))
    assert result.functions == ("helper", "plot")
    assert result.imports == ("math",)
    assert "unused" not in result.code and "import os" not in result.code
    namespace = {}
    exec(result.code, namespace)
    assert namespace["plot"](9) == 6


def test_local_names_do_not_pull_in_unrelated_global_functions():
    source = 'def other():\n    return 1\ndef plot(other):\n    return other + 2\n'
    result = extract_notebook_source(source, ("plot",))
    assert result.functions == ("plot",)


def test_decorators_are_preserved_with_their_dependencies():
    source = 'from functools import lru_cache\n@lru_cache(maxsize=1)\ndef plot():\n    return 1\n'
    result = extract_notebook_source(source, ("plot",))
    namespace = {}
    exec(result.code, namespace)
    assert namespace["plot"]() == 1
    assert namespace["plot"].cache_info().misses == 1


@pytest.mark.parametrize("source", [
    'def plot():\n    return missing_helper()\n',
    'def plot():\n    return globals()["hidden"]()\n',
    'from app.services.functions import secret\ndef plot():\n    return secret()\n',
    'def plot():\n    return 1\ndef plot():\n    return 2\n',
])
def test_incomplete_or_dynamic_source_is_rejected(source):
    with pytest.raises(ValueError):
        extract_notebook_source(source, ("plot",))


def test_source_extraction_retains_nested_global_dependencies():
    source = 'VALUE = 4\ndef plot():\n    def inner():\n        return VALUE\n    return inner()\n'
    result = extract_notebook_source(source, ("plot",))
    namespace = {}
    exec(result.code, namespace)
    assert namespace["plot"]() == 4


def test_parquet_preserves_exact_numbers_missingness_index_and_dtypes():
    frame = pd.DataFrame({"sample": [0.0, 1.0000000000000002, float("nan")],
                          "identifier": ["001", "", "protein"]}, index=[5, 1, 8])
    frame.index.name = "feature"
    restored = pd.read_parquet(io.BytesIO(dataframe_bytes(frame)))
    pd.testing.assert_frame_equal(frame, restored, check_exact=True)


def test_dataframe_private_attrs_are_not_exported_or_changed_in_original():
    frame = pd.DataFrame({"x": [1.]})
    frame.attrs["source_path"] = r"C:\Users\private\data.tsv"
    payload = dataframe_bytes(frame)
    assert not pd.read_parquet(io.BytesIO(payload)).attrs
    assert frame.attrs["source_path"].startswith("C:")


def recipe(**changes):
    frame = pd.DataFrame({"ProteinNames": ["P1", "P2"], "A1": [1., 2.], "A2": [2., 3.]})
    metadata = pd.DataFrame({"sample": ["A1", "A2"], "condition": ["A", "A"]})
    # Through `_source`, which inlines the shared core the way every export does.
    source = extract_notebook_source(_source("notebook_functions.py"), ("coverage_plot",))
    values = dict(plot_name="Coverage Plot", source=source,
                  calculation="figure = functions.coverage_plot(data, metadata, **settings)\nfigure.savefig('reproduced.png')",
                  settings={"id": False, "dpi": 100}, provenance={"normalization": "none"},
                  original_filename=r"C:\Users\private-user\research\example.tsv",
                  resources={"input.parquet": dataframe_bytes(frame), "metadata.parquet": dataframe_bytes(metadata)})
    values.update(changes)
    return NotebookRecipe(**values)


def test_archive_is_deterministic_and_path_free():
    item = recipe()
    name, first = build_notebook_archive(item)
    assert name == "Coverage_Plot.zip"
    assert first == build_notebook_archive(item)[1]
    with ZipFile(io.BytesIO(first)) as archive:
        for member in archive.infolist():
            assert member.date_time == (1980, 1, 1, 0, 0, 0)
            assert b"private-user" not in archive.read(member)
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["toolVersion"] == "1.0.0"
        assert manifest["originalFilename"] == "example.tsv"
        assert "coverage_plot" in archive.read("functions.py").decode()
        assert "volcano_plot" not in archive.read("functions.py").decode()


def test_filename_cannot_inject_notebook_code():
    _, content = build_notebook_archive(recipe(original_filename="evil\n__import__('os').system('bad').tsv"))
    with ZipFile(io.BytesIO(content)) as archive:
        notebook = json.loads(archive.read("Coverage_Plot.ipynb"))
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            code = "".join(cell["source"])
            compile(code, "notebook", "exec")
            assert not any(line.startswith("__import__") for line in code.splitlines())


@pytest.mark.parametrize("name", ["../secret", "/secret", "C:/secret", "a\\secret"])
def test_zip_member_traversal_is_rejected(name):
    item = recipe()
    with pytest.raises(ValueError, match="relative"):
        build_notebook_archive(recipe(resources={**item.resources, name: b"bad"}))


def test_imputed_export_requires_recipe_and_never_executes_it():
    with pytest.raises(ValueError, match="documented"):
        build_notebook_archive(recipe(uses_imputed_input=True))
    _, content = build_notebook_archive(recipe(uses_imputed_input=True,
        imputation_recipe="imputed_data = impute_values(filtered_data, metadata, q=0.01, seed=1337)"))
    with ZipFile(io.BytesIO(content)) as archive:
        notebook = json.loads(archive.read("Coverage_Plot.ipynb"))
    comments = ["".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code"]
    assert any("# imputed_data = impute_values" in code for code in comments)
    assert any("pd.read_parquet" in code and "input.parquet" in code for code in comments)


def test_exported_notebook_runs_outside_repository_without_copylot(tmp_path):
    _, content = build_notebook_archive(recipe())
    with ZipFile(io.BytesIO(content)) as archive:
        archive.extractall(tmp_path)
    notebook = json.loads((tmp_path / "Coverage_Plot.ipynb").read_text())
    code = "\n".join("".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code")
    runner = "import sys; sys.path.insert(0, '.');\n" + code
    completed = subprocess.run([sys.executable, "-I", "-c", runner], cwd=tmp_path,
                               capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stderr
    assert (tmp_path / "reproduced.png").read_bytes().startswith(b"\x89PNG")


def test_modified_export_resources_are_detected_before_calculation(tmp_path):
    _, content = build_notebook_archive(recipe())
    with ZipFile(io.BytesIO(content)) as archive:
        archive.extractall(tmp_path)
    (tmp_path / "resources/settings.json").write_text('{"dpi": 73}')
    notebook = json.loads((tmp_path / "Coverage_Plot.ipynb").read_text())
    setup = "".join(notebook["cells"][1]["source"])
    completed = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, '.');\n" + setup],
                               cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert completed.returncode != 0
    assert "Export file changed: resources/settings.json" in completed.stderr


def test_render_snapshot_is_immutable_and_owned_by_one_session():
    store = NotebookSnapshots()
    item = recipe()
    token = store.capture("owner", item)
    item.settings["dpi"] = 600
    assert store.get("owner", token).settings["dpi"] == 100
    returned = store.get("owner", token)
    returned.settings["dpi"] = 900
    assert store.get("owner", token).settings["dpi"] == 100
    with pytest.raises(KeyError):
        store.get("other-session", token)
    store.clear_session("owner")
    with pytest.raises(KeyError):
        store.get("owner", token)


def test_snapshots_expire_and_have_per_session_limits():
    clock = [0]
    store = NotebookSnapshots(per_session=1, ttl=10, clock=lambda: clock[0])
    first = store.capture("owner", recipe())
    second = store.capture("owner", recipe())
    with pytest.raises(KeyError):
        store.get("owner", first)
    assert store.get("owner", second)
    clock[0] = 11
    with pytest.raises(KeyError):
        store.get("owner", second)


def test_oversized_snapshot_is_rejected_without_evicting_existing_data():
    store = NotebookSnapshots(max_bytes=1)
    with pytest.raises(ValueError, match="memory"):
        store.capture("owner", recipe())
