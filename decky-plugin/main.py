#!/usr/bin/env python3
"""Decky backend for the DiscShelf baseline management plugin."""

from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import os
import pwd
import shutil
import tempfile
from pathlib import Path
from typing import Any

import decky  # type: ignore


USER_HOME = Path(decky.DECKY_USER_HOME)
INSTALLED_RUNTIME = USER_HOME / ".local/share/discshelf/bin/discshelf"
DEVELOPMENT_RUNTIME = USER_HOME / "DiscShelf/discshelf"
PLATFORM_ROOT = USER_HOME / "Emulation/roms"
DEVELOPMENT_MANIFEST_ROOT = USER_HOME / "DiscShelf/games"
MANIFEST_SUFFIX = ".discshelf.json"
LAYOUTS = {
    "list": {"columns": 1, "rows": 4},
    "showcase": {"columns": 1, "rows": 1},
    "strip": {"columns": 4, "rows": 1},
    "compact": {"columns": 2, "rows": 2},
    "wide-grid": {"columns": 3, "rows": 2},
}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".svg", ".webp"}
AUDIO_EXTENSIONS = {".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav"}


def runtime_candidates() -> list[tuple[str, Path]]:
    return [
        ("installed", INSTALLED_RUNTIME),
        ("development", DEVELOPMENT_RUNTIME),
    ]


def preview_environment(account: pwd.struct_passwd) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        HOME=str(USER_HOME),
        USER=account.pw_name,
        LOGNAME=account.pw_name,
        PATH="/usr/local/bin:/usr/bin:/bin",
        LD_LIBRARY_PATH="/usr/lib64:/usr/lib:/lib64:/lib",
        XDG_RUNTIME_DIR=f"/run/user/{account.pw_uid}",
        DBUS_SESSION_BUS_ADDRESS=f"unix:path=/run/user/{account.pw_uid}/bus",
        PULSE_SERVER=f"unix:/run/user/{account.pw_uid}/pulse/native",
        SDL_AUDIODRIVER="pulseaudio",
    )
    # Decky inherits Steam's runtime loader configuration. Host binaries such
    # as ffplay must not preload Steam/Decky libraries.
    environment.pop("LD_PRELOAD", None)
    return environment


def find_runtime() -> tuple[str, Path] | None:
    for source, path in runtime_candidates():
        if path.is_file() and os.access(path, os.X_OK):
            return source, path
    return None


def manifest_paths() -> tuple[list[Path], list[Path]]:
    roots = [PLATFORM_ROOT, DEVELOPMENT_MANIFEST_ROOT]
    found: set[Path] = set()
    if PLATFORM_ROOT.is_dir():
        found.update(path.resolve() for path in PLATFORM_ROOT.rglob(f"*{MANIFEST_SUFFIX}"))
    # Keep the prototype manifests visible until migration writes adjacent files.
    if DEVELOPMENT_MANIFEST_ROOT.is_dir():
        found.update(path.resolve() for path in DEVELOPMENT_MANIFEST_ROOT.rglob("*.json"))
    return sorted(found), roots


def resolve_manifest(path: str | Path) -> Path:
    manifest = Path(path).expanduser().resolve()
    allowed, _roots = manifest_paths()
    if manifest not in allowed:
        raise ValueError("Manifest is outside discovered roots")
    return manifest


def read_manifest(path: str | Path) -> tuple[Path, dict[str, Any]]:
    manifest = resolve_manifest(path)
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read manifest: {error}") from error
    validation = summarize_manifest_payload(payload)
    if not validation["valid"]:
        raise ValueError(validation["error"])
    return manifest, payload


def summarize_manifest_payload(payload: Any) -> dict[str, Any]:
    result = {"valid": False, "error": None}
    try:
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise ValueError("Unsupported manifest version")
        title = payload.get("title")
        discs = payload.get("discs")
        launch = payload.get("launch")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("Missing title")
        if not isinstance(discs, list) or not discs:
            raise ValueError("No discs configured")
        if not isinstance(launch, dict) or not launch.get("command"):
            raise ValueError("Missing launch command")
        result["valid"] = True
    except (ValueError, TypeError) as error:
        result["error"] = str(error)
    return result


def summarize_manifest(path: Path) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "path": str(path),
        "title": path.stem.removesuffix(".discshelf"),
        "discCount": 0,
        "layout": "unknown",
        "valid": False,
        "error": None,
    }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        validation = summarize_manifest_payload(payload)
        if not validation["valid"]:
            raise ValueError(validation["error"])
        title = payload["title"]
        discs = payload["discs"]
        summary.update(
            title=title,
            discCount=len(discs),
            layout=payload.get("selector", {}).get("layout", {}).get("preset", "list"),
            valid=True,
        )
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as error:
        summary["error"] = str(error)
    return summary


def manifest_settings(path: str | Path) -> dict[str, Any]:
    manifest, payload = read_manifest(path)
    layout = payload.get("selector", {}).get("layout", {})
    preset = layout.get("preset", "list")
    if preset == "widegrid":
        preset = "wide-grid"
    defaults = LAYOUTS.get(preset, LAYOUTS["list"])
    background = payload.get("background", {})
    music = payload.get("music", {})
    discs = []
    for disc in payload["discs"]:
        animation = disc.get("animation", {})
        discs.append(
            {
                "label": disc.get("label", ""),
                "path": disc.get("path", ""),
                "artwork": disc.get("artwork", ""),
                "animation": {
                    "type": animation.get("type", "none"),
                    "delay": animation.get("delay", 2.5),
                    "revolutionsPerMinute": animation.get("revolutionsPerMinute", 12),
                    "angle": animation.get("angle", 30),
                    "distance": animation.get("distance", 10),
                    "period": animation.get("period", 1.8),
                },
            }
        )
    return {
        "path": str(manifest),
        "title": payload["title"],
        "preset": preset,
        "columns": layout.get("columns", defaults["columns"]),
        "rows": layout.get("rows", defaults["rows"]),
        "backgroundImage": background.get("image", ""),
        "backgroundDim": background.get("dim", 0.7),
        "musicPath": music.get("path", ""),
        "musicVolume": music.get("volume", 0.35),
        "musicLoop": music.get("loop", True),
        "discs": discs,
    }


def _number(value: Any, label: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    if value < minimum or value > maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}")
    return float(value)


def _media_path(value: Any, label: str, extensions: set[str], manifest_dir: Path) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a path")
    if not value:
        return ""
    path = Path(value).expanduser()
    resolved = path if path.is_absolute() else manifest_dir / path
    if not resolved.is_file():
        raise ValueError(f"{label} does not exist")
    if resolved.suffix.lower() not in extensions:
        raise ValueError(f"{label} has an unsupported file type")
    return str(resolved.resolve()) if path.is_absolute() else value


def _content_path(value: Any, label: str, manifest_dir: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty path")
    path = Path(value).expanduser()
    resolved = path if path.is_absolute() else manifest_dir / path
    if not resolved.is_file():
        raise ValueError(f"{label} does not exist")
    return str(resolved.resolve()) if path.is_absolute() else value


def _disc_settings(value: Any, index: int, manifest_dir: Path) -> dict[str, Any]:
    number = index + 1
    if not isinstance(value, dict):
        raise ValueError(f"Disc {number} must be an object")
    label = value.get("label")
    if not isinstance(label, str) or not label.strip():
        raise ValueError(f"Disc {number} requires a label")
    artwork = _media_path(
        value.get("artwork", ""), f"Disc {number} artwork", IMAGE_EXTENSIONS, manifest_dir
    )
    animation = value.get("animation", {})
    if not isinstance(animation, dict):
        raise ValueError(f"Disc {number} animation must be an object")
    animation_type = animation.get("type", "none")
    if animation_type not in {"none", "spin", "wiggle"}:
        raise ValueError(f"Disc {number} has an unknown animation type")
    normalized_animation: dict[str, Any] = {
        "type": animation_type,
        "delay": _number(animation.get("delay", 2.5), f"Disc {number} delay", 0, 30),
    }
    if animation_type == "spin":
        normalized_animation["revolutionsPerMinute"] = _number(
            animation.get("revolutionsPerMinute", 12), f"Disc {number} speed", 1, 120
        )
    elif animation_type == "wiggle":
        normalized_animation.update(
            angle=_number(animation.get("angle", 30), f"Disc {number} angle", 0, 360),
            distance=_number(animation.get("distance", 10), f"Disc {number} distance", 0, 100),
            period=_number(animation.get("period", 1.8), f"Disc {number} period", 0.1, 30),
        )
    return {
        "label": label.strip(),
        "path": _content_path(value.get("path"), f"Disc {number} content", manifest_dir),
        "artwork": artwork,
        "animation": normalized_animation,
    }


def save_manifest_settings(path: str | Path, settings: Any) -> dict[str, Any]:
    manifest, payload = read_manifest(path)
    if not isinstance(settings, dict):
        raise ValueError("Settings must be an object")

    preset = settings.get("preset")
    if preset not in LAYOUTS:
        raise ValueError("Unknown layout preset")
    columns = settings.get("columns")
    rows = settings.get("rows")
    if isinstance(columns, bool) or not isinstance(columns, int) or columns < 1 or columns > 8:
        raise ValueError("Columns must be an integer between 1 and 8")
    if isinstance(rows, bool) or not isinstance(rows, int) or rows < 1 or rows > 8:
        raise ValueError("Rows must be an integer between 1 and 8")
    background_image = _media_path(
        settings.get("backgroundImage", ""), "Background image", IMAGE_EXTENSIONS, manifest.parent
    )
    music_path = _media_path(
        settings.get("musicPath", ""), "Background music", AUDIO_EXTENSIONS, manifest.parent
    )
    background_dim = _number(settings.get("backgroundDim", 0.7), "Background dim", 0, 1)
    music_volume = _number(settings.get("musicVolume", 0.35), "Music volume", 0, 1)
    music_loop = settings.get("musicLoop", True)
    if not isinstance(music_loop, bool):
        raise ValueError("Music loop must be true or false")
    discs = settings.get("discs")
    if not isinstance(discs, list) or not discs:
        raise ValueError("A manifest must contain at least one disc")
    normalized_discs = [
        _disc_settings(disc, index, manifest.parent) for index, disc in enumerate(discs)
    ]

    payload["selector"] = {"layout": {"preset": preset, "columns": columns, "rows": rows}}
    payload["background"] = {"image": background_image, "dim": background_dim}
    payload["music"] = {"path": music_path, "volume": music_volume, "loop": music_loop}
    payload["discs"] = normalized_discs

    source_stat = manifest.stat()
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=manifest.parent, prefix=f".{manifest.name}.", delete=False
        ) as temporary:
            temporary_name = temporary.name
            json.dump(payload, temporary, indent=2, ensure_ascii=False)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_stat = os.stat(temporary_name)
        if (temporary_stat.st_mode & 0o7777) != (source_stat.st_mode & 0o7777):
            os.chmod(temporary_name, source_stat.st_mode & 0o7777)
        if (temporary_stat.st_uid, temporary_stat.st_gid) != (source_stat.st_uid, source_stat.st_gid):
            os.chown(temporary_name, source_stat.st_uid, source_stat.st_gid)
        os.replace(temporary_name, manifest)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return manifest_settings(manifest)


class Plugin:
    async def _main(self):
        self.loop = asyncio.get_running_loop()
        self.preview_process = None
        decky.logger.info("DiscShelf backend loaded")

    async def _unload(self):
        await self._stop_music_preview()
        decky.logger.info("DiscShelf backend unloaded")

    async def _stop_music_preview(self) -> None:
        process = getattr(self, "preview_process", None)
        self.preview_process = None
        if process is None or process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()

    async def get_runtime_status(self) -> dict[str, Any]:
        runtime = find_runtime()
        if runtime is None:
            return {
                "available": False,
                "path": None,
                "version": None,
                "source": None,
                "error": "DiscShelf runtime not found",
            }
        source, path = runtime
        try:
            process = await asyncio.create_subprocess_exec(
                str(path),
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5)
            if process.returncode != 0:
                raise RuntimeError(stderr.decode().strip() or f"Exit {process.returncode}")
            return {
                "available": True,
                "path": str(path),
                "version": stdout.decode().strip(),
                "source": source,
                "error": None,
            }
        except (OSError, RuntimeError, asyncio.TimeoutError) as error:
            return {
                "available": False,
                "path": str(path),
                "version": None,
                "source": source,
                "error": str(error),
            }

    async def scan_manifests(self) -> dict[str, Any]:
        paths, roots = await asyncio.to_thread(manifest_paths)
        manifests = await asyncio.to_thread(
            lambda: [summarize_manifest(path) for path in paths]
        )
        return {
            "manifests": manifests,
            "roots": [str(root) for root in roots],
        }

    async def get_manifest_settings(self, path: str) -> dict[str, Any]:
        try:
            settings = await asyncio.to_thread(manifest_settings, path)
            return {"ok": True, "settings": settings, "error": None}
        except (OSError, ValueError) as error:
            return {"ok": False, "settings": None, "error": str(error)}

    async def update_manifest_settings(self, path: str, settings: dict[str, Any]) -> dict[str, Any]:
        try:
            updated = await asyncio.to_thread(save_manifest_settings, path, settings)
            return {"ok": True, "settings": updated, "error": None}
        except (OSError, ValueError) as error:
            return {"ok": False, "settings": None, "error": str(error)}

    async def preview_music(self, manifest_path: str, music_path: str, volume: float) -> dict[str, Any]:
        try:
            manifest = resolve_manifest(manifest_path)
            normalized = _media_path(
                music_path, "Background music", AUDIO_EXTENSIONS, manifest.parent
            )
            if not normalized:
                raise ValueError("Select a background music file first")
            preview_path = Path(normalized)
            if not preview_path.is_absolute():
                preview_path = manifest.parent / preview_path
            preview_volume = _number(volume, "Music volume", 0, 1)
            player = shutil.which("ffplay")
            if player is None:
                raise ValueError("ffplay is not installed")
            await self._stop_music_preview()
            account = pwd.getpwnam(USER_HOME.name)
            environment = preview_environment(account)
            self.preview_process = await asyncio.create_subprocess_exec(
                player,
                "-nodisp",
                "-autoexit",
                "-loglevel",
                "error",
                "-volume",
                str(round(preview_volume * 100)),
                str(preview_path.resolve()),
                start_new_session=True,
                user=account.pw_uid,
                group=account.pw_gid,
                env=environment,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.sleep(0.75)
            if self.preview_process.returncode is not None:
                stderr = await self.preview_process.stderr.read()
                self.preview_process = None
                detail = stderr.decode(errors="replace").strip()
                raise ValueError(detail or "Audio preview exited before playback started")
            return {"ok": True, "error": None}
        except (KeyError, OSError, ValueError) as error:
            return {"ok": False, "error": str(error)}

    async def stop_music_preview(self) -> dict[str, Any]:
        await self._stop_music_preview()
        return {"ok": True, "error": None}

    async def get_image_preview(self, manifest_path: str, image_path: str) -> dict[str, Any]:
        try:
            manifest = resolve_manifest(manifest_path)
            normalized = _media_path(
                image_path, "Artwork", IMAGE_EXTENSIONS, manifest.parent
            )
            if not normalized:
                return {"ok": True, "dataUrl": None, "error": None}
            preview_path = Path(normalized)
            if not preview_path.is_absolute():
                preview_path = manifest.parent / preview_path
            if preview_path.stat().st_size > 16 * 1024 * 1024:
                raise ValueError("Artwork preview is limited to 16 MB")
            mime_type = mimetypes.guess_type(preview_path.name)[0] or "application/octet-stream"
            if not mime_type.startswith("image/"):
                raise ValueError("Artwork is not a supported image")
            encoded = base64.b64encode(preview_path.read_bytes()).decode("ascii")
            return {
                "ok": True,
                "dataUrl": f"data:{mime_type};base64,{encoded}",
                "error": None,
            }
        except (OSError, ValueError) as error:
            return {"ok": False, "dataUrl": None, "error": str(error)}

    async def launch_manifest(self, path: str) -> dict[str, Any]:
        runtime = find_runtime()
        if runtime is None:
            return {"ok": False, "pid": None, "error": "DiscShelf runtime not found"}
        try:
            manifest = resolve_manifest(path)
        except ValueError as error:
            return {"ok": False, "pid": None, "error": str(error)}
        summary = summarize_manifest(manifest)
        if not summary["valid"]:
            return {"ok": False, "pid": None, "error": summary["error"]}
        try:
            account = pwd.getpwnam(Path(decky.DECKY_USER_HOME).name)
            environment = os.environ.copy()
            environment.update(
                HOME=str(USER_HOME),
                USER=account.pw_name,
                LOGNAME=account.pw_name,
                DISPLAY=environment.get("DISPLAY", ":0"),
                WAYLAND_DISPLAY=environment.get("WAYLAND_DISPLAY", "wayland-0"),
                XDG_RUNTIME_DIR=f"/run/user/{account.pw_uid}",
                DBUS_SESSION_BUS_ADDRESS=f"unix:path=/run/user/{account.pw_uid}/bus",
            )
            process = await asyncio.create_subprocess_exec(
                str(runtime[1]),
                str(manifest),
                start_new_session=True,
                user=account.pw_uid,
                group=account.pw_gid,
                env=environment,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            loop = getattr(self, "loop", asyncio.get_running_loop())
            loop.create_task(self._log_child_exit(process, summary["title"]))
            return {"ok": True, "pid": process.pid, "error": None}
        except (KeyError, OSError) as error:
            return {"ok": False, "pid": None, "error": str(error)}

    async def _log_child_exit(self, process, title: str) -> None:
        stdout, stderr = await process.communicate()
        if stdout:
            decky.logger.info("DiscShelf %s stdout: %s", title, stdout.decode(errors="replace").strip())
        if stderr:
            decky.logger.warning("DiscShelf %s stderr: %s", title, stderr.decode(errors="replace").strip())
        decky.logger.info("DiscShelf %s exited with %s", title, process.returncode)
