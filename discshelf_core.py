"""GUI-independent DiscShelf manifest and launch-command support."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

RUNTIME_VERSION = "0.2.0-dev"
MANIFEST_VERSION = 1
MANIFEST_SUFFIX = ".discshelf.json"

LAYOUTS = {
    "list": {"columns": 1, "rows": 4},
    "showcase": {"columns": 1, "rows": 1},
    "strip": {"columns": 4, "rows": 1},
    "compact": {"columns": 2, "rows": 2},
    "wide-grid": {"columns": 3, "rows": 2},
    # Accepted for compatibility with early prototype manifests.
    "widegrid": {"columns": 3, "rows": 2},
}


class ManifestError(ValueError):
    """Raised when a DiscShelf manifest is malformed or unsupported."""


def data_home(environment: Mapping[str, str] | None = None) -> Path:
    """Return the stable per-user DiscShelf data directory."""
    env = os.environ if environment is None else environment
    base = Path(env.get("XDG_DATA_HOME", "~/.local/share")).expanduser()
    return base / "discshelf"


def config_home(environment: Mapping[str, str] | None = None) -> Path:
    """Return the stable per-user DiscShelf configuration directory."""
    env = os.environ if environment is None else environment
    base = Path(env.get("XDG_CONFIG_HOME", "~/.config")).expanduser()
    return base / "discshelf"


def cache_home(environment: Mapping[str, str] | None = None) -> Path:
    """Return the stable per-user DiscShelf cache directory."""
    env = os.environ if environment is None else environment
    base = Path(env.get("XDG_CACHE_HOME", "~/.cache")).expanduser()
    return base / "discshelf"


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ManifestError(f"Could not read {path}: {error}") from error
    validate_manifest(manifest)
    return manifest


def validate_manifest(manifest: Any) -> None:
    if not isinstance(manifest, dict):
        raise ManifestError("Manifest root must be an object")
    if manifest.get("version") != MANIFEST_VERSION:
        raise ManifestError(f"Only DiscShelf manifest version {MANIFEST_VERSION} is supported")
    if not isinstance(manifest.get("title"), str) or not manifest["title"].strip():
        raise ManifestError("Manifest requires a non-empty title")

    selector = manifest.get("selector", {})
    if not isinstance(selector, dict):
        raise ManifestError("selector must be an object")
    layout = selector.get("layout", {})
    if not isinstance(layout, dict):
        raise ManifestError("selector.layout must be an object")
    if layout.get("preset", "list") not in LAYOUTS:
        raise ManifestError("Unknown layout preset")
    for dimension in ("columns", "rows"):
        if dimension in layout and (
            not isinstance(layout[dimension], int) or isinstance(layout[dimension], bool)
            or layout[dimension] < 1
        ):
            raise ManifestError(f"selector.layout.{dimension} must be a positive integer")

    background = manifest.get("background", {})
    if not isinstance(background, dict):
        raise ManifestError("background must be an object")
    _optional_string(background, "image", "background.image")
    _optional_number(background, "dim", "background.dim", 0, 1)

    music = manifest.get("music", {})
    if not isinstance(music, dict):
        raise ManifestError("music must be an object")
    _optional_string(music, "path", "music.path")
    _optional_number(music, "volume", "music.volume", 0, 1)
    if "loop" in music and not isinstance(music["loop"], bool):
        raise ManifestError("music.loop must be true or false")

    launch = manifest.get("launch")
    if not isinstance(launch, dict):
        raise ManifestError("Manifest requires a launch object")
    if not isinstance(launch.get("command"), str) or not launch["command"]:
        raise ManifestError("launch.command must be a non-empty string")
    arguments = launch.get("arguments", [])
    if not isinstance(arguments, list) or not all(isinstance(item, str) for item in arguments):
        raise ManifestError("launch.arguments must be an array of strings")
    _optional_string(launch, "playlist", "launch.playlist")

    discs = manifest.get("discs")
    if not isinstance(discs, list) or not discs:
        raise ManifestError("Manifest requires at least one disc")
    for index, disc in enumerate(discs):
        _validate_disc(disc, index)


def _validate_disc(disc: Any, index: int) -> None:
    number = index + 1
    if not isinstance(disc, dict):
        raise ManifestError(f"Disc {number} must be an object")
    if not isinstance(disc.get("label"), str) or not disc["label"].strip():
        raise ManifestError(f"Disc {number} requires a label")
    if not isinstance(disc.get("path"), str) or not disc["path"]:
        raise ManifestError(f"Disc {number} requires a path")
    _optional_string(disc, "artwork", f"Disc {number} artwork")
    animation = disc.get("animation", {})
    if not isinstance(animation, dict):
        raise ManifestError(f"Disc {number} animation must be an object")
    animation_type = animation.get("type", "none")
    if animation_type not in ("none", "spin", "wiggle"):
        raise ManifestError(f"Disc {number} has an unknown animation type")
    _optional_number(animation, "delay", f"Disc {number} animation.delay", 0)
    _optional_number(
        animation, "revolutionsPerMinute", f"Disc {number} animation.revolutionsPerMinute", 0
    )
    _optional_number(animation, "angle", f"Disc {number} animation.angle", 0, 360)
    _optional_number(animation, "distance", f"Disc {number} animation.distance", 0)
    _optional_number(animation, "period", f"Disc {number} animation.period", 0.1)


def _optional_string(container: dict[str, Any], key: str, label: str) -> None:
    if key in container and not isinstance(container[key], str):
        raise ManifestError(f"{label} must be a path string")


def _optional_number(
    container: dict[str, Any], key: str, label: str, minimum: float, maximum: float | None = None
) -> None:
    if key not in container:
        return
    value = container[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ManifestError(f"{label} must be a number")
    if value < minimum or (maximum is not None and value > maximum):
        bounds = f"between {minimum} and {maximum}" if maximum is not None else f"at least {minimum}"
        raise ManifestError(f"{label} must be {bounds}")


def resolve_path(value: str, manifest_dir: Path) -> str:
    path = Path(os.path.expandvars(os.path.expanduser(value)))
    if not path.is_absolute():
        path = manifest_dir / path
    return str(path.resolve())


def build_command(manifest: dict[str, Any], manifest_path: Path, disc_index: int) -> list[str]:
    discs = manifest["discs"]
    if disc_index < 0 or disc_index >= len(discs):
        raise ManifestError(f"Disc index {disc_index} is out of range")
    disc = discs[disc_index]
    launch = manifest["launch"]
    manifest_dir = manifest_path.parent.resolve()
    values = {
        "disc_path": resolve_path(disc["path"], manifest_dir),
        "disc_index": str(disc_index),
        "disc_number": str(disc_index + 1),
        "manifest_dir": str(manifest_dir),
    }
    if "playlist" in launch:
        values["playlist"] = resolve_path(launch["playlist"], manifest_dir)

    def substitute(argument: str) -> str:
        for name, value in values.items():
            argument = argument.replace("{" + name + "}", value)
        return argument

    command = resolve_path(launch["command"], manifest_dir)
    return [command, *(substitute(argument) for argument in launch.get("arguments", []))]
