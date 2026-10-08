"""Opt-in real-image smoke check: python tests/docker_runtime_check.py IMAGE.

Uses disposable credentials/data, loopback ports and a locally trusted test TLS
certificate. Requires Docker and the backend development Python environment.
The small TLS proxy tests transport, not a production reverse-proxy deployment.
"""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import ssl
import subprocess
import sys
import tempfile
import threading
import time

import httpx2 as httpx
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.services.password_hashing import hash_password


def docker(*args):
    return subprocess.run(["docker", *args], check=True, capture_output=True, text=True).stdout.strip()


def check(client, method, path, **kwargs):
    response = client.request(method, path, **kwargs)
    assert response.is_success, f"{method} {path}: {response.status_code} {response.text[:300]}"
    return response


def main(image):
    name = "copylot-runtime-check-" + secrets.token_hex(4)
    password = secrets.token_urlsafe(32)
    with tempfile.TemporaryDirectory(prefix="copylot-docker-check-") as directory:
        root = Path(directory)
        (root / "auth.json").write_text(json.dumps({"password_pbkdf2_sha256": hash_password(password)}))
        docker("run", "--rm", "--network", "none", "--mount", f"type=bind,source={root},target=/check",
               image, "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
               "-keyout", "/check/key.pem", "-out", "/check/cert.pem", "-subj", "/CN=localhost",
               "-addext", "subjectAltName=DNS:localhost")
        started = False
        proxy = None
        try:
            docker("run", "-d", "--name", name, "--read-only", "--cap-drop", "ALL",
                   "--security-opt", "no-new-privileges:true", "--pids-limit", "256",
                   "--memory", "4g", "--cpus", "2", "--tmpfs", "/tmp:rw,nosuid,noexec,size=1g",
                   "-p", "127.0.0.1::10000", "--mount", f"type=bind,source={root / 'auth.json'},target=/app/local/tool_access.local.json,readonly",
                   "-e", "COPYLOT_TOOL_ACCESS_ENABLED=1", "-e", "COPYLOT_SESSION_ISOLATION=1",
                   "-e", "COPYLOT_SESSION_COOKIE_SECURE=1", "-e", "COPYLOT_TRUSTED_PROXY_IPS=",
                   "-e", "MPLCONFIGDIR=/tmp/matplotlib", "-e", "XDG_CACHE_HOME=/tmp/cache", image)
            started = True
            assert docker("exec", name, "id", "-u") == "10001"
            docker("exec", name, "python", "-m", "pip", "check")
            port = int(docker("port", name, "10000/tcp").rsplit(":", 1)[1])

            class Proxy(BaseHTTPRequestHandler):
                def do_GET(self):
                    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
                    headers = {k: v for k, v in self.headers.items()
                               if k.lower() not in {"connection", "forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto"}}
                    body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                    try:
                        connection.request(self.command, self.path, body, headers)
                        response = connection.getresponse()
                        self.send_response(response.status)
                        for key, value in response.getheaders():
                            if key.lower() not in {"transfer-encoding", "connection"}:
                                self.send_header(key, value)
                        self.end_headers()
                        self.wfile.write(response.read())
                    finally:
                        connection.close()

                do_POST = do_GET

                def log_message(self, *args):
                    pass

            for attempt in range(60):
                try:
                    if httpx.get(f"http://127.0.0.1:{port}/api/tool/auth/status", timeout=2, trust_env=False).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(1)
            else:
                raise AssertionError("Container did not become ready")
            proxy = ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
            tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            tls.load_cert_chain(root / "cert.pem", root / "key.pem")
            proxy.socket = tls.wrap_socket(proxy.socket, server_side=True)
            threading.Thread(target=proxy.serve_forever, daemon=True).start()
            context = ssl.create_default_context(cafile=str(root / "cert.pem"))
            url = f"https://localhost:{proxy.server_port}"
            with httpx.Client(base_url=url, verify=context, trust_env=False, timeout=120) as a, httpx.Client(base_url=url, verify=context, trust_env=False, timeout=120) as b:
                assert a.get("/api/datasets/current").status_code == 401
                assert a.get("/", headers={"Host": "untrusted.invalid"}).status_code == 400
                assert "<html" in check(a, "GET", "/").text.lower()
                for client in (a, b):
                    login = check(client, "POST", "/api/tool/auth/login", json={"password": password})
                    cookie = login.headers["set-cookie"].lower()
                    assert "secure" in cookie and "httponly" in cookie and "samesite=lax" in cookie
                assert a.cookies != b.cookies
                assert check(a, "GET", "/api/runtime/r").json()["available"]
                assert check(a, "GET", "/api/runtime/normalization").json()["vsnAvailable"]
                rng = np.random.default_rng(4)
                samples = [f"{group}{i}" for group in "AB" for i in range(4)]
                matrix = rng.normal(20, 2, (100, 1)) + rng.normal(0, .3, (100, 8))
                matrix[:20, 4:] += 2
                frame = pd.DataFrame(2 ** matrix, columns=samples)
                frame.insert(0, "ProteinNames", [f"SYNTHETIC{i}" for i in range(100)])
                frame.insert(1, "GeneNames", [f"GENE{i}" for i in range(100)])
                check(a, "POST", "/api/datasets/upload", data={"kind": "protein"}, files={"file": ("synthetic.csv", frame.to_csv(index=False).encode())})
                meta = "sample,condition,pair_id\n" + "\n".join(f"{s},{s[0]},{s[1:]}" for s in samples)
                check(a, "POST", "/api/annotations/metadata/upload", data={"kind": "protein"}, files={"file": ("metadata.csv", meta.encode())})
                check(a, "POST", "/api/annotations/generate", json={"kind": "protein", "isLog2Transformed": False, "filter": {"minPresent": 3, "normalization": "vsn"}})
                assert check(b, "GET", "/api/datasets/current").json()["protein"] is None
                params = {"kind": "protein", "condition1": "A", "condition2": "B", "testType": "unpaired_welch"}
                before = check(a, "POST", "/api/stats/volcano/run", json=params).json()
                assert before["totalRows"] == 100
                assert a.post("/api/datasets/table-path", json={"kind": "protein", "path": "/etc/passwd"}, headers={"X-Forwarded-For": "127.0.0.1"}).status_code == 403
                check(b, "POST", "/api/tool/auth/logout")
                assert b.get("/api/datasets/current").status_code == 401
                assert check(a, "GET", "/api/tool/auth/status").json()["authenticated"]
                print("PASS: hardened startup, TLS/cookies, auth/isolation/logout, R/VSN, analysis, local-path denial and dependencies", flush=True)
                blob = check(a, "POST", "/api/restore/export", json={"portable": True, "uiState": {"smoke": True}}).content
                check(a, "POST", "/api/restore/browser-session-reset")
                missing = a.post("/api/restore/import", files={"stateFile": ("smoke.copylotstate", blob)})
                assert missing.status_code == 409
                needed = missing.json()["missingFiles"]
                manifest = [{"packageName": item["packageName"], "kind": item["kind"]} for item in needed]
                restored = check(a, "POST", "/api/restore/import",
                                 data={"replacementsManifest": json.dumps(manifest)},
                                 files=[("stateFile", ("smoke.copylotstate", blob)),
                                        *[("replacements", ("synthetic.csv", frame.to_csv(index=False).encode())) for _ in needed]]).json()
                assert restored["ok"] and restored["uiState"]["smoke"]
                after = check(a, "POST", "/api/stats/volcano/run", json=params).json()
                assert before["rows"] == after["rows"]
            print("PASS: hardened image startup, TLS/cookies, auth/isolation, R/VSN, analysis, portable restore, local-path denial and dependencies")
        finally:
            if proxy:
                proxy.shutdown()
                proxy.server_close()
            if started:
                docker("rm", "-f", name)


if __name__ == "__main__":
    main(sys.argv[1])
