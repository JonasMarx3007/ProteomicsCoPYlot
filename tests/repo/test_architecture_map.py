"""Public map generation stays offline, deterministic and limited to source structure."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("architecture_map", ROOT / "tools/build_architecture_map.py")
map_tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(map_tool)


def example():
    return {
        map_tool.TEMPLATE: '<script type="application/json">__MODEL__</script>',
        map_tool.SCHEMA: json.dumps({"paths": {"/api/plots/qc/{kind}/pca.png": {"get": {}}}}),
        "backend/app/api/plots_qc.py": (
            "from app.services.plot_images import draw\nrouter = APIRouter()\n"
            "@router.get('/qc/{kind}/pca.png')\ndef pca(kind):\n    return helper()\n"
            "def helper():\n    return draw()\n"
        ),
        "backend/app/services/plot_images.py": (
            "'''Private prose should never be published.'''\n"
            "from app.services.functions import calculate\ndef draw():\n    return calculate()\n"
        ),
        "backend/app/services/functions.py": "def calculate():\n    return 1\n",
        "frontend/src/lib/api.ts": "export function getPca(kind) { return fetch(`/api/plots/qc/${kind}/pca.png`); }",
        "frontend/src/features/qc/Page.tsx": "import { getPca } from '../../lib/api';\ngetPca('protein');",
    }


class ArchitectureMapTests(unittest.TestCase):
    def test_routes_wrappers_and_dependencies_are_connected(self):
        model = map_tool.build_model(example())
        endpoint, = model["endpoints"]
        self.assertEqual(endpoint["pages"], ["qc"])
        self.assertEqual(endpoint["calls"], ["plot_images.draw"])
        self.assertTrue(any(n["label"] == "functions" and n["col"] == 3 for n in model["nodes"]))
        ids = {n["id"] for n in model["nodes"]}
        self.assertTrue(all(link["s"] in ids and link["t"] in ids for link in model["links"]))

    def test_output_is_deterministic_and_does_not_copy_prose(self):
        sources = example()
        first = map_tool.render(sources)
        self.assertEqual(first, map_tool.render(dict(reversed(list(sources.items())))))
        self.assertNotIn("Private prose", first)
        self.assertNotIn("return calculate", first)

    def test_missing_published_routes_fail_instead_of_silently_disappearing(self):
        sources = example()
        del sources["backend/app/api/plots_qc.py"]
        with self.assertRaisesRegex(ValueError, "Published routes missing"):
            map_tool.build_model(sources)

    def test_embedded_data_cannot_close_the_script(self):
        model = {"note": "</script><script>alert(1)</script>"}
        with patch.object(map_tool, "build_model", return_value=model):
            output = map_tool.render(example())
        self.assertEqual(output.count("</script>"), 1)
        data = output.split(">", 1)[1].rsplit("<", 1)[0]
        self.assertEqual(json.loads(data), model)

    def test_only_versioned_source_is_read(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ("backend/app/main.py", "local/private.py", "viewer_data/private.py", "backend/app/untracked.py"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("pass", encoding="utf-8")
            listing = "backend/app/main.py\0local/private.py\0viewer_data/private.py\0"
            with patch.object(map_tool.subprocess, "check_output", return_value=listing):
                self.assertEqual(map_tool.read_sources(root), {"backend/app/main.py": "pass"})

    def test_real_map_covers_the_published_api_without_private_details(self):
        sources = map_tool.read_sources(ROOT)
        model = map_tool.build_model(sources)
        self.assertGreater(len(model["endpoints"]), 100)
        text = json.dumps(model).lower()
        for forbidden in ("local/", "file://"):
            self.assertNotIn(forbidden, text)
        self.assertNotRegex(text, r"[a-z]:\\|(?:\d{1,3}\.){3}\d{1,3}")
        self.assertIn("default-src 'none'", sources[map_tool.TEMPLATE])
        self.assertNotIn('<script src=', sources[map_tool.TEMPLATE])


if __name__ == "__main__":
    unittest.main()
