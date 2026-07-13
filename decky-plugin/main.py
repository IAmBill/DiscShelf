#!/usr/bin/env python3
"""Decky backend for the DiscShelf baseline management plugin."""

from __future__ import annotations

import asyncio
import json
import os
import pwd
from pathlib import Path
from typing import Any

import decky  # type: ignore


USER_HOME = Path(decky.DECKY_USER_HOME)
INSTALLED_RUNTIME = USER_HOME / ".local/share/discshelf/bin/discshelf"
DEVELOPMENT_RUNTIME = USER_HOME / "DiscShelf/discshelf"
PLATFORM_ROOT = USER_HOME / "Emulation/roms"
DEVELOPMENT_MANIFEST_ROOT = USER_HOME / "DiscShelf/games"
MANIFEST_SUFFIX = ".discshelf.json"


def runtime_candidates() -> list[tuple[str, Path]]:
    return [
        ("installed", INSTALLED_RUNTIME),
        ("development", DEVELOPMENT_RUNTIME),
    ]


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
        if payload.get("version") != 1:
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
        summary.update(
            title=title,
            discCount=len(discs),
            layout=payload.get("selector", {}).get("layout", {}).get("preset", "list"),
            valid=True,
        )
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as error:
        summary["error"] = str(error)
    return summary


class Plugin:
    async def _main(self):
        self.loop = asyncio.get_running_loop()
        decky.logger.info("DiscShelf backend loaded")

    async def _unload(self):
        decky.logger.info("DiscShelf backend unloaded")

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

    async def launch_manifest(self, path: str) -> dict[str, Any]:
        runtime = find_runtime()
        if runtime is None:
            return {"ok": False, "pid": None, "error": "DiscShelf runtime not found"}
        manifest = Path(path).expanduser().resolve()
        allowed, _roots = manifest_paths()
        if manifest not in allowed:
            return {"ok": False, "pid": None, "error": "Manifest is outside discovered roots"}
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
