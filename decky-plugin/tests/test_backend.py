#!/usr/bin/env python3

import asyncio
import importlib.util
import json
import logging
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


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

    def test_manifest_appearance_settings_round_trip(self):
        source = ROOT / "games/dreamcast/shenmue.json"
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "shenmue.discshelf.json"
            manifest.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            background = Path(directory) / "background.png"
            music = Path(directory) / "music.mp3"
            disc_image = Path(directory) / "disc.chd"
            disc_artwork = Path(directory) / "disc.png"
            background.touch()
            music.touch()
            disc_image.touch()
            disc_artwork.touch()
            with mock.patch.object(backend, "manifest_paths", return_value=([manifest], [Path(directory)])):
                settings = backend.manifest_settings(manifest)
                settings.update(
                    preset="compact",
                    columns=3,
                    rows=2,
                    backgroundImage=str(background),
                    backgroundDim=0.6,
                    musicPath=str(music),
                    musicVolume=0.25,
                    musicLoop=False,
                    discs=[
                        {
                            "label": "Bonus Disc",
                            "path": str(disc_image),
                            "artwork": str(disc_artwork),
                            "animation": {
                                "type": "wiggle",
                                "delay": 1.5,
                                "revolutionsPerMinute": 12,
                                "angle": 25,
                                "distance": 8,
                                "period": 2.0,
                            },
                        }
                    ],
                )
                updated = backend.save_manifest_settings(manifest, settings)

            self.assertEqual(updated["preset"], "compact")
            self.assertEqual(updated["columns"], 3)
            self.assertEqual(updated["backgroundImage"], str(background))
            self.assertEqual(updated["musicPath"], str(music))
            self.assertEqual(updated["discs"][0]["label"], "Bonus Disc")
            self.assertEqual(updated["discs"][0]["animation"]["type"], "wiggle")
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(payload["selector"]["layout"]["rows"], 2)
            self.assertFalse(payload["music"]["loop"])
            self.assertEqual(payload["discs"][0]["path"], str(disc_image))
            self.assertEqual(payload["discs"][0]["animation"]["angle"], 25.0)

    def test_manifest_settings_reject_unsupported_media(self):
        source = ROOT / "games/dreamcast/shenmue.json"
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "shenmue.discshelf.json"
            manifest.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            unsupported = Path(directory) / "background.txt"
            unsupported.touch()
            with mock.patch.object(backend, "manifest_paths", return_value=([manifest], [Path(directory)])):
                settings = backend.manifest_settings(manifest)
                settings["backgroundImage"] = str(unsupported)
                with self.assertRaisesRegex(ValueError, "unsupported file type"):
                    backend.save_manifest_settings(manifest, settings)

    def test_manifest_settings_require_at_least_one_disc(self):
        source = ROOT / "games/dreamcast/shenmue.json"
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "shenmue.discshelf.json"
            manifest.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            with mock.patch.object(backend, "manifest_paths", return_value=([manifest], [Path(directory)])):
                settings = backend.manifest_settings(manifest)
                settings["discs"] = []
                with self.assertRaisesRegex(ValueError, "at least one disc"):
                    backend.save_manifest_settings(manifest, settings)

    def test_image_preview_returns_a_data_url(self):
        source = ROOT / "games/dreamcast/shenmue.json"
        with tempfile.TemporaryDirectory() as directory:
            manifest = (Path(directory) / "shenmue.discshelf.json").resolve()
            manifest.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            artwork = Path(directory) / "disc.png"
            artwork.write_bytes(b"preview-image")
            plugin = backend.Plugin()
            with mock.patch.object(backend, "manifest_paths", return_value=([manifest], [Path(directory)])):
                result = asyncio.run(plugin.get_image_preview(str(manifest), str(artwork)))
            self.assertTrue(result["ok"])
            self.assertTrue(result["dataUrl"].startswith("data:image/png;base64,"))

    def test_music_preview_uses_host_library_environment(self):
        account = types.SimpleNamespace(pw_name="bazzite", pw_uid=1000)
        with mock.patch.dict(
            backend.os.environ,
            {"LD_LIBRARY_PATH": "/steam/runtime", "LD_PRELOAD": "/steam/runtime/preload.so"},
        ):
            environment = backend.preview_environment(account)
        self.assertEqual(environment["LD_LIBRARY_PATH"], "/usr/lib64:/usr/lib:/lib64:/lib")
        self.assertNotIn("LD_PRELOAD", environment)
        self.assertEqual(environment["SDL_AUDIODRIVER"], "pulseaudio")


if __name__ == "__main__":
    unittest.main()
