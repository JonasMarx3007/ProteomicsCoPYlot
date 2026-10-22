"""Collect release notices and matching source; fail rather than ship missing licences."""
from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import io
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import zipfile

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True).stdout


def conda_licenses(prefix: Path) -> list[tuple[dict, list[tuple[str, str]]]]:
    """Read native-library notices from the retained Conda package cache."""
    result = []
    for path in sorted((prefix / "conda-meta").glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if not record.get("files"):
            continue  # Empty metapackages have no redistributable files.
        cache = record.get("link", {}).get("source")
        licenses = Path(cache) / "info/licenses" if cache else None
        texts = [(str(p.relative_to(licenses)), p.read_text(encoding="utf-8", errors="replace"))
                 for p in sorted(licenses.rglob("*")) if p.is_file()] if licenses else []
        # Some packages (notably GCC runtimes) install their notices alongside
        # the libraries instead of storing them in info/licenses.
        for filename in sorted(record["files"]):
            relative = Path(filename)
            if (any(part.lower() in {"licenses", "licences"} for part in relative.parts)
                    or relative.name.lower().startswith(("license", "licence", "copying", "copyright", "notice"))):
                installed = (prefix / relative).resolve()
                if not installed.is_relative_to(prefix.resolve()):
                    raise ValueError(f"Conda licence path escapes the environment: {filename}")
                if installed.is_file():
                    texts.append((filename, installed.read_text(encoding="utf-8", errors="replace")))
        if not texts and record["name"] == "libsqlite" and record.get("license") == "blessing":
            # SQLite publishes its public-domain dedication in the C header.
            header = prefix / "include/sqlite3.h"
            if header.is_file():
                notice = header.read_text(encoding="utf-8").split("*/", 1)[0] + "*/"
                if "The author disclaims copyright" in notice:
                    texts.append(("include/sqlite3.h (opening notice)", notice))
        if not texts:
            raise ValueError(f"Missing Conda licence texts for {record['name']}; retain the package cache.")
        result.append((record, texts))
    return result


def clean_revision(root: Path) -> str:
    if git(root, "status", "--porcelain", "--untracked-files=normal").strip():
        raise ValueError("Commit the reviewed source before building a distributable release.")
    return git(root, "rev-parse", "HEAD").decode().strip()


def license_texts(distribution) -> list[tuple[str, str]]:
    """Include licence/notice files shipped in wheels, including native-library notices."""
    found = []
    for entry in sorted(distribution.files or [], key=str):
        name = Path(str(entry)).name.lower()
        if name.startswith(("license", "licence", "notice", "copying", "copyright", "ofl.", "ftl.")):
            path = Path(distribution.locate_file(entry))
            if path.is_file():
                found.append((str(entry).replace("\\", "/"), path.read_text(encoding="utf-8", errors="replace")))
    if not found:
        # Older wheels sometimes carry the complete licence only in METADATA.
        text = distribution.metadata.get("License", "")
        if len(text) > 200 and ("permission" in text.lower() or "redistribution" in text.lower()):
            found.append(("METADATA/License", text))
    if not found:
        for record, texts in conda_licenses(Path(sys.prefix)):
            if canonicalize_name(record["name"]) == canonicalize_name(distribution.metadata["Name"]):
                return texts
    if not found:
        raise ValueError(f"No licence text found for {distribution.metadata['Name']}; fix the build environment.")
    return found


def collect_notices(root: Path) -> tuple[str, list[dict[str, str]]]:
    lines = ["Third-party notices for this release", "",
             "This software is based in part on the work of the FreeType Team.",
             "This software is based in part on the work of the Independent JPEG Group.", ""]
    packages = []
    locked = re.findall(r"^([A-Za-z0-9_.-]+)==([^\s;]+)$",
                        (root / "backend/requirements-runtime.lock").read_text(), re.M)
    if not locked:
        raise ValueError("Production dependency lock is empty.")
    pending = dict(locked)
    pending["pyinstaller"] = None
    seen = set()
    while pending:
        name, expected = pending.popitem()
        normalized = canonicalize_name(name)
        if normalized in seen:
            continue
        seen.add(normalized)
        distribution = metadata.distribution(name)
        # Include transitive dependencies of the actual installed versions,
        # not just the packages known when the repository lock was generated.
        for dependency in distribution.requires or []:
            requirement = Requirement(dependency)
            if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
                pending.setdefault(requirement.name, None)
        source = f"https://pypi.org/project/{name}/{distribution.version}/#files"
        packages.append({"name": name, "version": distribution.version, "source": source,
                         "locked_version": expected or "transitive/build dependency"})
        lines.extend([f"## {name} {distribution.version}", f"Unmodified upstream source: {source}", ""])
        for filename, text in license_texts(distribution):
            lines.extend([f"### {filename}", text, ""])
    python_license = next((p for p in (
        Path(sys.base_prefix) / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE",
        Path(sys.base_prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "LICENSE.txt",
    ) if p.is_file()), None)
    if python_license is None:
        raise ValueError("CPython licence file is missing from this Python installation.")
    lines.extend([f"## CPython {platform.python_version()}",
                  f"Source: https://www.python.org/ftp/python/{platform.python_version()}/",
                  python_license.read_text(encoding="utf-8"), ""])
    frontend = root / "frontend/dist/THIRD_PARTY_LICENSES.md"
    if not frontend.is_file() or not frontend.read_text(encoding="utf-8").strip():
        raise ValueError("Frontend dependency licences are missing; rebuild the frontend.")
    lines.extend(["## Frontend dependencies", frontend.read_text(encoding="utf-8")])
    for record, texts in conda_licenses(Path(sys.prefix)):
        lines.extend([f"## Conda {record['name']} {record['version']} ({record['build']})",
                      f"Package: {record.get('url', '')}", ""])
        for filename, text in texts:
            lines.extend([f"### {filename}", text, ""])
    return "\n".join(lines), packages


def source_archive(root: Path) -> bytes:
    data = git(root, "archive", "--format=zip", "--prefix=source/", "HEAD")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in archive.namelist():
            parts = Path(name).parts
            if ".." in parts or any(p in {"local", ".git", ".env", "node_modules", ".venv"} for p in parts):
                raise ValueError(f"Private or generated path in source release: {name}")
    return data


def prepare(root: Path, output: Path) -> None:
    revision = clean_revision(root)
    notices, packages = collect_notices(root)
    source = source_archive(root)
    # Do not make a half-updated legal folder if an input fails validation.
    output.mkdir(parents=True, exist_ok=True)
    for name in ("LICENSE", "NOTICE"):
        shutil.copyfile(root / name, output / name)
    (output / "THIRD_PARTY_NOTICES.txt").write_text(notices, encoding="utf-8")
    (output / "CoPYlot-source.zip").write_bytes(source)
    manifest = {"revision": revision, "python": platform.python_version(), "platform": platform.platform(),
                "packages": packages, "source_sha256": hashlib.sha256(source).hexdigest()}
    conda_packages = [{key: record.get(key) for key in ("name", "version", "build", "url", "sha256")}
                      for record, _ in conda_licenses(Path(sys.prefix))]
    if conda_packages:
        manifest["conda_packages"] = conda_packages
    (output / "release-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (output / "build-requirements.txt").write_text(
        "\n".join(f"{p['name']}=={p['version']}" for p in packages) + "\n", encoding="utf-8")
    (output / "README.txt").write_text(
        "Distribute this complete release ZIP, including the source and notices.\n"
        "CoPYlot is GPL-3.0-only, without warranty; see LICENSE and NOTICE.\n"
        "CoPYlot-source.zip contains the corresponding application source and build scripts.\n"
        "See source/docs/INSTALLATION.md for build instructions; build-requirements.txt\n"
        "pins the actual build environment, including deviations from the repository lock.\n"
        "Third-party components retain their own terms. Exact dependency source locations\n"
        "are listed in THIRD_PARTY_NOTICES.txt and release-manifest.json.\n"
        "This bundle does not include R. Install R with Bioconductor vsn and limma separately\n"
        "to use VSN normalization or the moderated t-tests.\n",
        encoding="utf-8")


def finish(root: Path, legal: Path, executable: Path) -> Path:
    manifest = json.loads((legal / "release-manifest.json").read_text(encoding="utf-8"))
    if clean_revision(root) != manifest["revision"]:
        raise ValueError("Source changed during the build; rebuild before releasing.")
    if not executable.is_file() or executable.stat().st_size == 0:
        raise ValueError("Built executable is missing or empty.")
    source = legal / "CoPYlot-source.zip"
    if hashlib.sha256(source.read_bytes()).hexdigest() != manifest["source_sha256"]:
        raise ValueError("Corresponding source archive changed during the build.")
    manifest["executable_sha256"] = hashlib.sha256(executable.read_bytes()).hexdigest()
    output = executable.with_name(executable.stem + "-release.zip")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(executable, executable.name)
        for name in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.txt", "CoPYlot-source.zip", "README.txt", "build-requirements.txt"):
            archive.write(legal / name, name)
        archive.writestr("release-manifest.json", json.dumps(manifest, indent=2) + "\n")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "finish"))
    parser.add_argument("--legal-dir", required=True, type=Path)
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.root, args.legal_dir)
    elif args.executable is None:
        parser.error("finish requires --executable")
    else:
        print(finish(args.root, args.legal_dir, args.executable))


if __name__ == "__main__":
    main()
