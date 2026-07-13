#!/usr/bin/env python3

import importlib.util
import logging
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
fake_decky = types.SimpleNamespace(
    DECKY_USER_HOME=str(Path.home()),
    logger=logging.getLogger("discshelf-decky-test"),
)
sys.modules.setdefault("decky", fake_decky)
spec = importlib.util.spec_from_file_location("discshelf_decky_backend", ROOT / "decky-plugin/main.py")
backend = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(backend)


class BackendTests(unittest.TestCase):
    def test_development_runtime_is_found(self):
        runtime = backend.find_runtime()
        self.assertIsNotNone(runtime)
        self.assertEqual(runtime[0], "development")

    def test_current_manifests_are_summarized(self):
        paths, roots = backend.manifest_paths()
        self.assertIn(Path.home() / "DiscShelf/games", roots)
        summaries = [backend.summarize_manifest(path) for path in paths]
        valid = [item for item in summaries if item["valid"]]
        self.assertGreaterEqual(len(valid), 3)
        self.assertIn("Shenmue", {item["title"] for item in valid})

    def test_invalid_manifest_summary_does_not_raise(self):
        summary = backend.summarize_manifest(ROOT / "README.md")
        self.assertFalse(summary["valid"])
        self.assertIsNotNone(summary["error"])


if __name__ == "__main__":
    unittest.main()
