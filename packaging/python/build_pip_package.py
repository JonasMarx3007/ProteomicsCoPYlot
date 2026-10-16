from __future__ import annotations

import os
import re
import runpy
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RELEASE_ROOT = ROOT / "release" / "python"


def project_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    try:
        project_section = text.split("[project]", 1)[1].split("\n[", 1)[0]
    except IndexError as exc:
        raise RuntimeError("pyproject.toml has no [project] section.") from exc
    match = re.search(r'^version\s*=\s*"([^"]+)"\s*$', project_section, flags=re.MULTILINE)
    if match is None:
        raise RuntimeError("pyproject.toml has no project version.")
    version = match.group(1)
    package_version = runpy.run_path(str(ROOT / "proteomicscopylot" / "_version.py"))[
        "__version__"
    ]
    if version != package_version:
        raise RuntimeError("Python package version files do not agree.")
    return version


def expected_artifact_names(version: str) -> set[str]:
    return {
        f"proteomicscopylot-{version}-py3-none-any.whl",
        f"proteomicscopylot-{version}.tar.gz",
    }


def release_label(version: str) -> str:
    match = re.fullmatch(r"(\d+\.\d+\.\d+)b(\d+)", version)
    return f"{match.group(1)}-beta.{match.group(2)}" if match else version


def release_output_dir(version: str) -> Path:
    output = (RELEASE_ROOT / release_label(version)).resolve()
    release_root = RELEASE_ROOT.resolve()
    if output.parent != release_root:
        raise RuntimeError("Invalid Python release output directory.")
    return output


def prepare_release_output(output: Path) -> None:
    release_root = RELEASE_ROOT.resolve()
    if output.resolve().parent != release_root:
        raise RuntimeError("Refusing to clean an unmanaged release directory.")
    if release_root.exists():
        shutil.rmtree(release_root)
    output.mkdir(parents=True)


def prepare_build_output() -> None:
    build_output = (ROOT / "build").resolve()
    if build_output.parent != ROOT.resolve():
        raise RuntimeError("Refusing to clean an unmanaged build directory.")
    if build_output.exists():
        shutil.rmtree(build_output)


def validate_artifact_set(output: Path, version: str) -> list[Path]:
    artifacts = sorted(path for path in output.iterdir() if path.is_file())
    actual = {path.name for path in artifacts}
    expected = expected_artifact_names(version)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise RuntimeError(
            f"Invalid Python release artifact set; missing={missing}, unexpected={unexpected}."
        )
    return artifacts


def main() -> None:
    # The repository has a local "build/" directory. Remove the project root
    # so "python -m build" resolves the installed PyPA build package.
    root_text = str(ROOT).lower()
    sys.path = [
        entry
        for entry in sys.path
        if entry and os.path.abspath(entry).lower() != root_text
    ]

    if len(sys.argv) > 1:
        raise SystemExit("This release builder does not accept output overrides.")

    version = project_version()
    output = release_output_dir(version)
    prepare_release_output(output)
    prepare_build_output()
    sys.argv = [
        "build",
        "--sdist",
        "--wheel",
        "--outdir",
        str(output),
        str(ROOT),
    ]
    runpy.run_module("build", run_name="__main__")
    artifacts = validate_artifact_set(output, version)
    print("Verified Python release artifacts:")
    for artifact in artifacts:
        print(artifact)


if __name__ == "__main__":
    main()
