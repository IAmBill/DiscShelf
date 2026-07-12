#!/usr/bin/python3

import json
import unittest
from pathlib import Path

from discshelf_core import (
    MANIFEST_SUFFIX,
    ManifestError,
    build_command,
    cache_home,
    config_home,
    data_home,
    load_manifest,
    resolve_path,
    validate_manifest,
)


ROOT = Path(__file__).resolve().parents[1]


class CoreTests(unittest.TestCase):
    def test_current_manifests_and_commands(self):
        manifests = sorted((ROOT / "games" / "dreamcast").glob("*.json"))
        self.assertEqual(len(manifests), 3)
        for path in manifests:
            manifest = load_manifest(path)
            for index, disc in enumerate(manifest["discs"]):
                command = build_command(manifest, path, index)
                self.assertEqual(command[1:3], ["-L", "/flycast_libretro.so"])
                self.assertEqual(command[-1], resolve_path(disc["path"], path.parent))

    def test_relative_paths_and_placeholders(self):
        manifest = {
            "version": 1,
            "title": "Relative Test",
            "launch": {
                "command": "bin/emulator",
                "arguments": ["{disc_index}", "{disc_number}", "{disc_path}"],
            },
            "discs": [{"label": "One", "path": "roms/disc one.chd"}],
        }
        validate_manifest(manifest)
        path = Path("/games/example/game.discshelf.json")
        self.assertEqual(
            build_command(manifest, path, 0),
            ["/games/example/bin/emulator", "0", "1", "/games/example/roms/disc one.chd"],
        )

    def test_invalid_values_are_rejected(self):
        invalid = {
            "version": 1,
            "title": "Invalid",
            "background": {"dim": 1.5},
            "launch": {"command": "/bin/true"},
            "discs": [{"label": "Disc", "path": "disc.chd"}],
        }
        with self.assertRaises(ManifestError):
            validate_manifest(invalid)

    def test_stable_xdg_paths(self):
        env = {
            "XDG_DATA_HOME": "/data",
            "XDG_CONFIG_HOME": "/config",
            "XDG_CACHE_HOME": "/cache",
        }
        self.assertEqual(data_home(env), Path("/data/discshelf"))
        self.assertEqual(config_home(env), Path("/config/discshelf"))
        self.assertEqual(cache_home(env), Path("/cache/discshelf"))
        self.assertEqual(MANIFEST_SUFFIX, ".discshelf.json")

    def test_shenmue_two_fixture_targets_descriptors(self):
        fixture = json.loads(
            (ROOT / "tests/fixtures/scanner/shenmue-2-expected.json").read_text()
        )
        self.assertTrue(all(Path(path).is_file() for path in fixture["discs"]))
        self.assertTrue(all(path.endswith(".mds") for path in fixture["discs"]))
        self.assertEqual(
            Path(fixture["commonAncestor"]) / f"{fixture['title']}{MANIFEST_SUFFIX}",
            Path(fixture["manifestPath"]),
        )


if __name__ == "__main__":
    unittest.main()
