"""Isolated, loopback-only backend for the serial Playwright suite."""
import os
from pathlib import Path
import sys
import tempfile
import json
import hashlib

import uvicorn


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    with tempfile.TemporaryDirectory(prefix="copylot-browser-") as directory:
        # Set before importing the application: uploads and plot caches must not
        # share paths with a developer's running analysis.
        tempfile.tempdir = directory
        os.environ.update(TMP=directory, TEMP=directory, TMPDIR=directory)
        viewer = os.environ.get("COPYLOT_BROWSER_VIEWER") == "1"
        if viewer:
            from app.services import viewer_bootstrap
            from app.services.password_hashing import hash_password
            root = Path(directory)
            # Redirect project discovery to synthetic fixtures, never local user projects.
            viewer_bootstrap.PROJECT_ROOT = root
            project = root / "viewer_data" / "Synthetic"
            project.mkdir(parents=True)
            samples = [f"{group}{i}" for group in "AB" for i in range(1, 5)]
            table = project / "protein.csv"
            table.write_text("ProteinNames,GeneNames," + ",".join(samples) + "\n" + "\n".join(
                f"SYNTHETIC{i},GENE{i}," + ",".join(str(12 + i + j * .15 + (j % 3) * .03) for j in range(8))
                for i in range(12)), encoding="utf-8")
            meta = project / "metadata.csv"
            meta.write_text("sample,condition,pair_id\n" + "\n".join(f"{s},{s[0]},{s[1:]}" for s in samples), encoding="utf-8")
            config = project / "viewer_config.json"
            config.write_text(json.dumps({"datasets": {"Synthetic": {
                "protein_file": str(table), "meta_file": str(meta),
                "log2_transform_protein": True, "filter_min_protein": 3,
                "filter_method_protein": "at_least_n", "filter_mode_protein": "per_group",
                "imputation": {"mode": "none"},
            }}}), encoding="utf-8")
            access = root / "viewer_access.json"
            qr_access = root / "viewer_qr_access.json"
            qr_access.write_text(json.dumps({"tokens": [{"project": "Synthetic",
                "token_sha256": hashlib.sha256(b"synthetic-browser-qr-only").hexdigest()}]}), encoding="utf-8")
            access.write_text(json.dumps({"credentials": [{"project": "Synthetic",
                "password_pbkdf2_sha256": hash_password("synthetic-browser-test-only")
            }]}), encoding="utf-8")
            os.environ.update(COPYLOT_VIEWER_MODE="1", COPYLOT_VIEWER_PORTAL_ENABLED="1",
                              COPYLOT_SESSION_ISOLATION="1", COPYLOT_VIEWER_CONFIG=str(config),
                              COPYLOT_VIEWER_ACCESS_FILE=str(access),
                              COPYLOT_VIEWER_QR_ACCESS_FILE=str(qr_access))
            second = root / "viewer_data" / "Second"
            second.mkdir()
            second_table = second / "protein.csv"
            second_table.write_text("\n".join(table.read_text(encoding="utf-8").replace("SYNTHETIC", "SECOND").splitlines()[:7]), encoding="utf-8")
            second_config = json.loads(config.read_text(encoding="utf-8"))
            second_config["datasets"]["Synthetic"]["protein_file"] = str(second_table)
            (second / "viewer_config.json").write_text(json.dumps(second_config), encoding="utf-8")
            entries = json.loads(access.read_text(encoding="utf-8"))
            entries["credentials"].append({"project": "Second",
                "password_pbkdf2_sha256": hash_password("synthetic-second-password")})
            access.write_text(json.dumps(entries), encoding="utf-8")
        elif os.environ.get("COPYLOT_BROWSER_TOOL_AUTH") == "1":
            from app.services.password_hashing import hash_password
            access = Path(directory) / "tool_access.json"
            access.write_text(json.dumps({
                "password_pbkdf2_sha256": hash_password("synthetic-tool-password"),
                "tokens": [{"token_sha256": hashlib.sha256(b"synthetic-browser-link-only").hexdigest()}],
            }), encoding="utf-8")
            os.environ.update(COPYLOT_TOOL_ACCESS_ENABLED="1", COPYLOT_TOOL_ACCESS_FILE=str(access), COPYLOT_SESSION_ISOLATION="1")
        if os.environ.get("COPYLOT_BROWSER_ASSISTANT_STUB") == "1":
            from app.services import scientific_assistant
            scientific_assistant._execution_profile = lambda *args: ("extended", 4, 2000)
            def scripted_completion(request, instruction, data, **kwargs):
                if "task" in kwargs["schema"]["properties"]:
                    reply = {"task": "current_plot"}
                    if request.message.startswith("Focus canvas on phosphosite "):
                        reply = {"task": "canvas_focus", "focus": {"kind": "phospho", "query": request.message.removeprefix("Focus canvas on phosphosite "), "conditions": ["A", "B"]}}
                    elif request.message == "Focus canvas on protein P0":
                        reply = {"task": "canvas_focus", "focus": {"kind": "protein", "query": "P0", "conditions": ["A", "B"]}}
                    elif request.message == "Focus canvas on all phosphosites on protein P0":
                        reply = {"task": "canvas_focus", "focus": {"kind": "phospho", "query": "P0", "allSites": True, "conditions": ["A", "B"]}}
                    if request.view.module == "analysis.canvas" and "oraList" in request.view.mode.get("tiles", []):
                        reply["module"] = "stats.ora"
                elif "source" in kwargs["schema"]["properties"]:
                    reply = {"source": "current_result", "query": ""}
                else:
                    catalogue = json.loads(data)["catalogue"]
                    role = "observations" if catalogue["observations"] else "methods"
                    reply = {role: [catalogue[role][0]["id"]] if catalogue[role] else []}
                return "scripted-no-inference", json.dumps(reply)
            scientific_assistant.assistant_completion = scripted_completion
        uvicorn.run("app.main:app", host="127.0.0.1", port=8188 if viewer else 8187, log_level="warning")
