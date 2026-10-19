"""Check a release bundle and time process launch to a responding frontend.

Uses only the Python standard library, so the checking environment does not
provide any of the application's dependencies. Browser rendering is not timed.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import zipfile


def stream_digest(stream) -> str:
    result = hashlib.sha256()
    while block := stream.read(1024 * 1024):
        result.update(block)
    return result.hexdigest()


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return stream_digest(stream)


def check_bundle(bundle: Path, executable: Path, revision: str) -> None:
    with zipfile.ZipFile(bundle) as archive:
        if archive.testzip() is not None:
            raise ValueError("Release ZIP failed its CRC check")
        required = {executable.name, "LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.txt",
                    "CoPYlot-source.zip", "README.txt", "build-requirements.txt",
                    "release-manifest.json"}
        if set(archive.namelist()) != required or len(archive.namelist()) != len(required):
            raise ValueError("Release bundle contents do not match")
        if os.name != "nt" and not (archive.getinfo(executable.name).external_attr >> 16) & 0o111:
            raise ValueError("Release ZIP does not preserve executable permissions")
        manifest = json.loads(archive.read("release-manifest.json"))
        if manifest["revision"] != revision:
            raise ValueError("Release source revision does not match")
        with archive.open(executable.name) as stream:
            bundled_hash = stream_digest(stream)
        if bundled_hash != digest(executable) or bundled_hash != manifest["executable_sha256"]:
            raise ValueError("Release executable hash does not match")
        with archive.open("CoPYlot-source.zip") as stream:
            if stream_digest(stream) != manifest["source_sha256"]:
                raise ValueError("Release source hash does not match")


@contextmanager
def runtime_directory(parent: Path):
    temporary = tempfile.TemporaryDirectory(prefix="copylot-startup-", dir=parent)
    try:
        yield temporary.name
    finally:
        # Windows may briefly retain DLL handles after the process tree exits.
        for attempt in range(40):
            try:
                temporary.cleanup()
                break
            except PermissionError:
                if attempt == 39:
                    raise
                time.sleep(0.25)


def measure(executable: Path, ai: bool, version: str, output: Path, trial: int) -> dict:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(path: str, timeout: float = 10):
        try:
            with opener.open(base + path, timeout=timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    # Isolate all unpacked runtime files and delete only this run's temporary tree.
    with runtime_directory(output.parent) as work:
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("COPYLOT_", "VITE_"))}
        env.update(TMP=work, TEMP=work, TMPDIR=work, MPLBACKEND="Agg")
        with output.with_suffix(f".trial-{trial}.log").open("wb") as log:
            started = time.perf_counter()
            proc = subprocess.Popen(
                [str(executable), "--host", "127.0.0.1", "--port", str(port), "--no-browser"],
                cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
            )
            try:
                while time.perf_counter() - started < 300:
                    if proc.poll() is not None:
                        raise RuntimeError(f"Application exited with status {proc.returncode}; see {log.name}")
                    try:
                        code, body = get("/api/health", timeout=0.5)
                        if code == 200 and json.loads(body).get("frontendAvailable"):
                            code, body = get("/", timeout=0.5)
                            if code == 200 and b"<html" in body.lower():
                                seconds = time.perf_counter() - started
                                break
                    except (OSError, urllib.error.URLError):
                        pass
                    time.sleep(0.1)
                else:
                    raise TimeoutError(f"Application not ready after 300 seconds; see {log.name}")
                code, body = get("/build-mode.json")
                if code != 200 or json.loads(body) != {"appMode": "analysis", "aiEnabled": ai}:
                    raise ValueError("Embedded frontend mode does not match")
                code, body = get("/openapi.json")
                if code != 200 or json.loads(body)["info"]["version"] != version:
                    raise ValueError("Embedded backend version does not match")
                code, _ = get("/api/chat/provider-defaults")
                if code != (200 if ai else 404):
                    raise ValueError("Embedded AI mode does not match")
                return {"trial": trial, "seconds": round(seconds, 2), "version": version,
                        "ai_enabled": ai, "health": "passed", "frontend": "passed"}
            finally:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    try:
                        os.killpg(proc.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                try:
                    proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    if os.name != "nt":
                        os.killpg(proc.pid, signal.SIGKILL)
                    else:
                        proc.kill()
                    proc.wait()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--revision")
    parser.add_argument("--version", required=True, help="Python/backend version, e.g. 1.0.0b1")
    parser.add_argument("--ai", action="store_true")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.runs < 1 or (args.bundle and not args.revision):
        parser.error("Use at least one run and supply --revision with --bundle")
    executable = args.executable.resolve(strict=True)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.bundle:
        check_bundle(args.bundle, executable, args.revision)
    results = []
    for trial in range(1, args.runs + 1):
        result = measure(executable, args.ai, args.version, output, trial)
        results.append(result)
        print(json.dumps(result), flush=True)
        output.write_text(json.dumps({"executable": executable.name,
                                     "sha256": digest(executable), "runs": results}, indent=2) + "\n")


if __name__ == "__main__":
    main()
