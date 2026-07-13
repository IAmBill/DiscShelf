#!/usr/bin/python3
"""Fullscreen, controller-friendly selector for DiscShelf manifests."""

from __future__ import annotations

import argparse
import ctypes
import math
import os
import shlex
import sys
import time
import warnings
from pathlib import Path
from typing import Any

from discshelf_core import (
    LAYOUTS,
    RUNTIME_VERSION,
    ManifestError,
    build_command,
    load_manifest,
    resolve_path,
)

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

try:
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst  # noqa: E402
except (ImportError, ValueError):
    Gst = None


class BackgroundMusic:
    def __init__(self, path: str, volume: float, loop: bool):
        if Gst is None:
            raise RuntimeError("GStreamer is not available")
        Gst.init(None)
        self.loop = loop
        self.player = Gst.ElementFactory.make("playbin", "discshelf-music")
        if self.player is None:
            raise RuntimeError("GStreamer playbin is not available")
        self.player.set_property("uri", Gst.filename_to_uri(path))
        self.player.set_property("volume", volume)
        bus = self.player.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_message)
        self.player.set_state(Gst.State.PLAYING)

    def on_message(self, _bus, message) -> None:
        if message.type == Gst.MessageType.EOS:
            if self.loop:
                self.player.seek_simple(
                    Gst.Format.TIME,
                    Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                    0,
                )
            else:
                self.stop()
        elif message.type == Gst.MessageType.ERROR:
            error, _debug = message.parse_error()
            print(f"DiscShelf music: {error.message}", file=sys.stderr)
            self.stop()

    def stop(self) -> None:
        if self.player is not None:
            self.player.set_state(Gst.State.NULL)


class AnimatedArtwork(Gtk.DrawingArea):
    """Artwork renderer with delayed, selection-driven transforms."""

    def __init__(
        self,
        path: str,
        width: int,
        height: int,
        animation: dict[str, Any],
        expand: bool = False,
    ):
        super().__init__()
        self.set_size_request(width, height)
        self.set_hexpand(expand)
        self.set_vexpand(expand)
        self.animation = animation
        self.active = False
        self.started_at = 0.0
        self.timer_id = None
        self.pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
        self.set_draw_func(self.draw_artwork)

    def set_active(self, active: bool) -> None:
        if self.active == active:
            return
        self.active = active
        self.started_at = time.monotonic()
        if self.timer_id is not None:
            GLib.source_remove(self.timer_id)
            self.timer_id = None
        if active and self.animation.get("type", "none") != "none":
            self.timer_id = GLib.timeout_add(16, self.tick)
        self.queue_draw()

    def tick(self) -> bool:
        if not self.active:
            self.timer_id = None
            return False
        self.queue_draw()
        return True

    def transform(self) -> tuple[float, float]:
        elapsed = time.monotonic() - self.started_at
        delay = float(self.animation.get("delay", 2.5))
        if not self.active or elapsed < delay:
            return 0.0, 0.0
        elapsed -= delay
        animation_type = self.animation.get("type", "none")
        if animation_type == "spin":
            rpm = float(self.animation.get("revolutionsPerMinute", 12))
            return (elapsed * rpm * 6) % 360, 0.0
        if animation_type == "wiggle":
            period = max(0.1, float(self.animation.get("period", 1.8)))
            phase = elapsed * math.tau / period
            angle = float(self.animation.get("angle", 30)) * math.sin(phase)
            distance = float(self.animation.get("distance", 10))
            return angle, distance * math.sin(phase * 2)
        return 0.0, 0.0

    def draw_artwork(self, _area, context, width: int, height: int) -> None:
        angle, vertical_offset = self.transform()
        pix_width, pix_height = self.pixbuf.get_width(), self.pixbuf.get_height()
        scale = min(
            max(1, width - 28) / pix_width,
            max(1, height - 28) / pix_height,
        )
        context.save()
        context.translate(width / 2, height / 2 + vertical_offset)
        context.rotate(math.radians(angle))
        context.scale(scale, scale)
        context.translate(-pix_width / 2, -pix_height / 2)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            Gdk.cairo_set_source_pixbuf(context, self.pixbuf, 0, 0)
        context.paint()
        context.restore()


class _SDLControllerAxisEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_uint32),
        ("timestamp", ctypes.c_uint32),
        ("which", ctypes.c_int32),
        ("axis", ctypes.c_uint8),
        ("padding1", ctypes.c_uint8),
        ("padding2", ctypes.c_uint8),
        ("padding3", ctypes.c_uint8),
        ("value", ctypes.c_int16),
        ("padding4", ctypes.c_uint16),
    ]


class _SDLControllerButtonEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_uint32),
        ("timestamp", ctypes.c_uint32),
        ("which", ctypes.c_int32),
        ("button", ctypes.c_uint8),
        ("state", ctypes.c_uint8),
        ("padding1", ctypes.c_uint8),
        ("padding2", ctypes.c_uint8),
    ]


class _SDLControllerDeviceEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_uint32),
        ("timestamp", ctypes.c_uint32),
        ("which", ctypes.c_int32),
    ]


class _SDLEvent(ctypes.Union):
    _fields_ = [
        ("type", ctypes.c_uint32),
        ("axis", _SDLControllerAxisEvent),
        ("button", _SDLControllerButtonEvent),
        ("device", _SDLControllerDeviceEvent),
        ("padding", ctypes.c_uint8 * 56),
    ]


class SDLControllerInput:
    """Small SDL2 bridge used only for controller navigation events."""

    SDL_INIT_GAMECONTROLLER = 0x00002000
    SDL_CONTROLLERAXISMOTION = 0x650
    SDL_CONTROLLERBUTTONDOWN = 0x651
    SDL_CONTROLLERDEVICEADDED = 0x653
    SDL_CONTROLLER_AXIS_LEFTX = 0
    SDL_CONTROLLER_AXIS_LEFTY = 1
    SDL_CONTROLLER_BUTTON_A = 0
    SDL_CONTROLLER_BUTTON_B = 1
    SDL_CONTROLLER_BUTTON_DPAD_UP = 11
    SDL_CONTROLLER_BUTTON_DPAD_DOWN = 12
    SDL_CONTROLLER_BUTTON_DPAD_LEFT = 13
    SDL_CONTROLLER_BUTTON_DPAD_RIGHT = 14

    def __init__(self, on_up, on_down, on_left, on_right, on_accept, on_back) -> None:
        self.on_up = on_up
        self.on_down = on_down
        self.on_left = on_left
        self.on_right = on_right
        self.on_accept = on_accept
        self.on_back = on_back
        self.controllers: list[int] = []
        self.axis_directions = {self.SDL_CONTROLLER_AXIS_LEFTX: 0, self.SDL_CONTROLLER_AXIS_LEFTY: 0}
        self.sdl = None
        try:
            self.sdl = ctypes.CDLL("libSDL2-2.0.so.0")
            self.sdl.SDL_GameControllerOpen.restype = ctypes.c_void_p
            self.sdl.SDL_InitSubSystem(self.SDL_INIT_GAMECONTROLLER)
            for index in range(self.sdl.SDL_NumJoysticks()):
                self.open_controller(index)
            GLib.timeout_add(16, self.poll)
        except OSError:
            self.sdl = None

    def open_controller(self, index: int) -> None:
        if self.sdl and self.sdl.SDL_IsGameController(index):
            controller = self.sdl.SDL_GameControllerOpen(index)
            if controller:
                self.controllers.append(controller)

    def poll(self) -> bool:
        if not self.sdl:
            return False
        event = _SDLEvent()
        while self.sdl.SDL_PollEvent(ctypes.byref(event)):
            if event.type == self.SDL_CONTROLLERDEVICEADDED:
                self.open_controller(event.device.which)
            elif event.type == self.SDL_CONTROLLERBUTTONDOWN:
                actions = {
                    self.SDL_CONTROLLER_BUTTON_A: self.on_accept,
                    self.SDL_CONTROLLER_BUTTON_B: self.on_back,
                    self.SDL_CONTROLLER_BUTTON_DPAD_UP: self.on_up,
                    self.SDL_CONTROLLER_BUTTON_DPAD_DOWN: self.on_down,
                    self.SDL_CONTROLLER_BUTTON_DPAD_LEFT: self.on_left,
                    self.SDL_CONTROLLER_BUTTON_DPAD_RIGHT: self.on_right,
                }
                action = actions.get(event.button.button)
                if action:
                    action()
            elif (
                event.type == self.SDL_CONTROLLERAXISMOTION
                and event.axis.axis in self.axis_directions
            ):
                direction = -1 if event.axis.value < -16000 else 1 if event.axis.value > 16000 else 0
                if direction != self.axis_directions[event.axis.axis]:
                    if event.axis.axis == self.SDL_CONTROLLER_AXIS_LEFTX:
                        action = self.on_left if direction < 0 else self.on_right
                    else:
                        action = self.on_up if direction < 0 else self.on_down
                    if direction:
                        action()
                    self.axis_directions[event.axis.axis] = direction
        return True


class DiscShelfWindow(Gtk.ApplicationWindow):
    def __init__(self, application, manifest, manifest_path, windowed, dry_run, layout_override=None):
        super().__init__(application=application, title=manifest["title"])
        self.manifest = manifest
        self.manifest_path = manifest_path
        self.dry_run = dry_run
        self.music_player = None
        configured = manifest.get("selector", {}).get("layout", {})
        self.preset = layout_override or configured.get("preset", "list")
        if self.preset not in LAYOUTS:
            self.preset = "list"
        defaults = LAYOUTS[self.preset]
        self.columns = max(1, int(configured.get("columns", defaults["columns"])))
        self.rows = max(1, int(configured.get("rows", defaults["rows"])))
        if layout_override:
            self.columns, self.rows = defaults["columns"], defaults["rows"]
        self.selected_index = 0
        self.selection_widget = None
        self.showcase_stack = None
        self.artwork_widgets: dict[int, AnimatedArtwork] = {}
        self.artwork_display_widgets: dict[int, Gtk.Widget] = {}
        self.card_widgets: list[Gtk.Widget] = []
        self.input_mode = "controller"
        self.mouse_suppressed_until = 0.0

        self.set_default_size(1100, 760)
        self.add_css_class("discshelf")
        if not windowed:
            self.fullscreen()

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        root.set_hexpand(True)
        root.set_vexpand(True)
        for setter, value in ((root.set_margin_top, 38), (root.set_margin_bottom, 38)):
            setter(value)
        scene = Gtk.Overlay()
        background = manifest.get("background", {})
        background_path = background.get("image", "").strip()
        resolved_background = resolve_path(background_path, manifest_path.parent) if background_path else ""
        if resolved_background and Path(resolved_background).is_file():
            backdrop = Gtk.Picture.new_for_filename(resolved_background)
            backdrop.set_content_fit(Gtk.ContentFit.COVER)
            backdrop.set_can_shrink(True)
        else:
            backdrop = Gtk.Box()
            backdrop.add_css_class("background-solid")
        scene.set_child(backdrop)
        shade = Gtk.Box(hexpand=True, vexpand=True)
        shade.add_css_class("background-dim")
        shade.set_opacity(float(background.get("dim", 0.7)) if background_path else 0)
        shade.set_can_target(False)
        scene.add_overlay(shade)
        scene.add_overlay(root)
        scene.add_overlay(self.build_screen_edge_fades())
        self.set_child(scene)

        title = Gtk.Label(label=manifest["title"], xalign=0)
        title.add_css_class("title")
        title.set_margin_start(56)
        title.set_margin_end(56)
        root.append(title)
        subtitle = Gtk.Label(label=f"Select a disc  •  {self.preset.replace('-', ' ').title()}", xalign=0)
        subtitle.add_css_class("subtitle")
        subtitle.set_margin_start(56)
        subtitle.set_margin_end(56)
        root.append(subtitle)

        if self.preset == "list":
            selector = self.build_list()
        elif self.preset == "showcase":
            selector = self.build_showcase()
        else:
            selector = self.build_grid()
        root.append(selector)

        footer = Gtk.Label(label="D-pad / Stick  Navigate     A / Enter  Select     B / Esc  Back", xalign=0)
        footer.add_css_class("footer")
        footer.set_margin_start(56)
        footer.set_margin_end(56)
        root.append(footer)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.on_key_pressed)
        self.add_controller(keys)
        scroll = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.BOTH_AXES
            | Gtk.EventControllerScrollFlags.DISCRETE
        )
        scroll.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        scroll.connect("scroll", self.on_mouse_scroll)
        self.add_controller(scroll)
        self.controller_input = SDLControllerInput(
            lambda: self.controller_action(self.select_up),
            lambda: self.controller_action(self.select_down),
            lambda: self.controller_action(self.select_left),
            lambda: self.controller_action(self.select_right),
            lambda: self.controller_action(self.activate_selected),
            lambda: self.controller_action(self.close),
        )
        self.set_input_mode("controller")
        self.update_selection()
        GLib.timeout_add(150, self.update_responsive_sizes)
        self.connect("close-request", self.on_close_request)
        self.start_music()

    def start_music(self) -> None:
        music = self.manifest.get("music", {})
        music_path = music.get("path", "").strip()
        if not music_path:
            return
        resolved = resolve_path(music_path, self.manifest_path.parent)
        if not Path(resolved).is_file():
            print(f"DiscShelf music: file not found: {resolved}", file=sys.stderr)
            return
        try:
            self.music_player = BackgroundMusic(
                resolved,
                float(music.get("volume", 0.35)),
                bool(music.get("loop", True)),
            )
        except RuntimeError as error:
            print(f"DiscShelf music: {error}", file=sys.stderr)

    def stop_music(self) -> None:
        if self.music_player is not None:
            self.music_player.stop()
            self.music_player = None

    def on_close_request(self, _window) -> bool:
        self.stop_music()
        return False

    def artwork(
        self, index: int, width: int, height: int, expand: bool = False
    ) -> Gtk.Widget:
        disc = self.manifest["discs"][index]
        artwork_path = disc.get("artwork", "").strip()
        resolved = resolve_path(artwork_path, self.manifest_path.parent) if artwork_path else ""
        if resolved and Path(resolved).is_file():
            widget = AnimatedArtwork(
                resolved, width, height, disc.get("animation", {}), expand
            )
            widget.set_tooltip_text(f"{disc['label']} artwork")
            widget.add_css_class("disc-artwork")
            self.artwork_widgets[index] = widget
        else:
            widget = Gtk.Label(label=str(index + 1))
            widget.add_css_class("disc-artwork-placeholder")
        widget.set_size_request(width, height)
        self.artwork_display_widgets[index] = widget
        return widget

    def set_input_mode(self, mode: str) -> None:
        self.input_mode = mode
        if mode == "controller":
            self.mouse_suppressed_until = time.monotonic() + 0.8
        elif mode == "keyboard":
            self.mouse_suppressed_until = time.monotonic() + 0.4
        self.set_cursor_from_name("default" if mode == "mouse" else "none")

    def controller_action(self, action) -> None:
        self.set_input_mode("controller")
        action()

    def select_index(self, index: int, direction: int = 0) -> None:
        if index < 0 or index >= len(self.manifest["discs"]):
            return
        self.selected_index = index
        self.update_selection(direction)

    def attach_mouse_selection(self, widget: Gtk.Widget, index: int) -> None:
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", lambda _motion, _x, _y: self.mouse_select(index))
        widget.add_controller(motion)
        click = Gtk.GestureClick()
        click.connect("pressed", lambda _click, _count, _x, _y: self.mouse_select(index))
        widget.add_controller(click)

    def mouse_select(self, index: int) -> None:
        if time.monotonic() < self.mouse_suppressed_until:
            return
        self.set_input_mode("mouse")
        if index != self.selected_index:
            self.select_index(index, index - self.selected_index)

    def on_mouse_scroll(self, _controller, delta_x: float, delta_y: float) -> bool:
        if not delta_x and not delta_y:
            return False
        self.set_input_mode("mouse")
        delta = delta_x if abs(delta_x) > abs(delta_y) else delta_y
        self.move(1 if delta > 0 else -1)
        return True

    def build_list(self) -> Gtk.Widget:
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        box.add_css_class("disc-list")
        box.connect("row-activated", lambda _box, row: self.launch(row.disc_index))
        box.connect("row-selected", self.on_list_row_selected)
        for index, disc in enumerate(self.manifest["discs"]):
            row = Gtk.ListBoxRow()
            row.disc_index = index
            content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
            for setter in (content.set_margin_top, content.set_margin_bottom): setter(8)
            for setter in (content.set_margin_start, content.set_margin_end): setter(20)
            content.append(self.artwork(index, 144, 82))
            label = Gtk.Label(label=disc["label"], xalign=0, hexpand=True)
            label.add_css_class("disc-label")
            content.append(label)
            row.set_child(content)
            box.append(row)
            self.attach_mouse_selection(row, index)
            self.card_widgets.append(content)
        scroller.set_child(box)
        self.selection_widget = box
        return scroller

    def build_showcase(self) -> Gtk.Widget:
        self.showcase_stack = Gtk.Stack(
            transition_duration=280,
            transition_type=Gtk.StackTransitionType.SLIDE_LEFT,
            vexpand=True,
            hexpand=True,
        )
        for index, disc in enumerate(self.manifest["discs"]):
            page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
            page.set_valign(Gtk.Align.FILL)
            page.set_halign(Gtk.Align.FILL)
            page.set_vexpand(True)
            page.set_hexpand(True)
            page.append(self.artwork(index, 680, 390, expand=True))
            label = Gtk.Label(label=disc["label"])
            label.add_css_class("showcase-label")
            page.append(label)
            self.attach_mouse_selection(page, index)
            self.showcase_stack.add_named(page, str(index))
        return self.showcase_stack

    @staticmethod
    def draw_edge_fade(_area, context, width, height, edge) -> None:
        cairo = __import__("cairo")
        vertical = edge in ("top", "bottom")
        gradient = cairo.LinearGradient(0, 0, 0, height) if vertical else cairo.LinearGradient(0, 0, width, 0)
        opaque_at_end = edge in ("right", "bottom")
        edge_alpha = 0.82
        if opaque_at_end:
            gradient.add_color_stop_rgba(0, 0, 0, 0, 0)
            gradient.add_color_stop_rgba(1, 0, 0, 0, edge_alpha)
        else:
            gradient.add_color_stop_rgba(0, 0, 0, 0, edge_alpha)
            gradient.add_color_stop_rgba(1, 0, 0, 0, 0)
        context.rectangle(0, 0, width, height)
        context.set_source(gradient)
        context.fill()

    def build_screen_edge_fades(self) -> Gtk.Widget:
        """Transparent, non-interactive fade layer sized by the full window."""
        layer = Gtk.Overlay(hexpand=True, vexpand=True)
        layer.set_child(Gtk.Box(hexpand=True, vexpand=True))
        layer.set_can_target(False)
        for edge, alignment in (("left", Gtk.Align.START), ("right", Gtk.Align.END)):
            fade = Gtk.DrawingArea(
                halign=alignment,
                valign=Gtk.Align.FILL,
                hexpand=False,
                vexpand=True,
            )
            fade.set_size_request(96, -1)
            fade.set_can_target(False)
            fade.set_draw_func(self.draw_edge_fade, edge)
            layer.add_overlay(fade)
        return layer

    def build_grid(self) -> Gtk.Widget:
        horizontal = self.preset == "strip"
        scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC if horizontal else Gtk.PolicyType.NEVER,
                            Gtk.PolicyType.NEVER if horizontal else Gtk.PolicyType.AUTOMATIC)
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.SINGLE,
                           column_spacing=18, row_spacing=10,
                           homogeneous=True, valign=Gtk.Align.CENTER)
        flow.add_css_class("disc-grid")
        flow.set_min_children_per_line(len(self.manifest["discs"]) if horizontal else self.columns)
        flow.set_max_children_per_line(len(self.manifest["discs"]) if horizontal else self.columns)
        flow.connect("child-activated", lambda _flow, child: self.launch(child.disc_index))
        flow.connect("selected-children-changed", self.on_flow_selection_changed)
        card_width = 220 if horizontal else (310 if self.columns == 2 else 250)
        art_height = 150 if horizontal else (170 if self.columns == 2 else 135)
        for index, disc in enumerate(self.manifest["discs"]):
            child = Gtk.FlowBoxChild()
            child.disc_index = index
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            card.set_size_request(card_width, art_height + 70)
            card.set_margin_top(8); card.set_margin_bottom(8)
            card.set_margin_start(12); card.set_margin_end(12)
            card.append(self.artwork(index, card_width - 24, art_height))
            label = Gtk.Label(label=disc["label"], wrap=True, justify=Gtk.Justification.CENTER)
            label.add_css_class("grid-label")
            card.append(label)
            child.set_child(card)
            flow.append(child)
            self.attach_mouse_selection(child, index)
            self.card_widgets.append(card)
        scroller.set_child(flow)
        self.selection_widget = flow
        return scroller

    def update_responsive_sizes(self) -> bool:
        """Fit the configured visible rows/columns to the current allocation."""
        width, height = self.get_width(), self.get_height()
        if width < 200 or height < 200 or self.preset == "showcase":
            return True

        # Header, footer, outer margins, and root spacing occupy about 222 px.
        # Keep a small buffer so exactly-visible rows never trigger a scrollbar.
        available_height = max(180, height - 226)
        if self.preset == "list":
            artwork_height = max(72, int(available_height / self.rows) - 24)
            artwork_width = max(116, int(artwork_height * 1.6))
            for artwork in self.artwork_display_widgets.values():
                artwork.set_size_request(artwork_width, artwork_height)
        else:
            visible_columns = self.columns
            visible_rows = 1 if self.preset == "strip" else self.rows
            gap_width = 18 * max(0, visible_columns - 1)
            gap_height = 10 * max(0, visible_rows - 1)
            card_width = max(
                170,
                int((width - gap_width - 72 - (24 * visible_columns)) / visible_columns),
            )
            allocated_card_height = max(
                150,
                int(
                    (available_height - gap_height - (16 * visible_rows) - 8)
                    / visible_rows
                ),
            )
            artwork_width = max(140, card_width - 32)
            if self.preset == "strip":
                artwork_height = max(
                    100, min(artwork_width, available_height - 68)
                )
                card_height = artwork_height + 52
            else:
                card_height = allocated_card_height
                artwork_height = max(100, min(card_height - 52, artwork_width))
            for card in self.card_widgets:
                card.set_size_request(card_width, card_height)
            for artwork in self.artwork_display_widgets.values():
                artwork.set_size_request(artwork_width, artwork_height)
        return True

    def on_key_pressed(self, _controller, keyval, _keycode, _state) -> bool:
        actions = {Gdk.KEY_Up: self.select_up, Gdk.KEY_Down: self.select_down,
                   Gdk.KEY_Left: self.select_left, Gdk.KEY_Right: self.select_right,
                   Gdk.KEY_Return: self.activate_selected, Gdk.KEY_KP_Enter: self.activate_selected,
                   Gdk.KEY_Escape: self.close, Gdk.KEY_BackSpace: self.close}
        action = actions.get(keyval)
        if action:
            self.set_input_mode("keyboard")
            action()
            return True
        return False

    def on_list_row_selected(self, _listbox, row) -> None:
        if row is not None and row.disc_index != self.selected_index:
            self.select_index(row.disc_index, row.disc_index - self.selected_index)

    def on_flow_selection_changed(self, flowbox) -> None:
        selected = flowbox.get_selected_children()
        if selected and selected[0].disc_index != self.selected_index:
            index = selected[0].disc_index
            self.select_index(index, index - self.selected_index)

    def move(self, offset: int) -> None:
        self.selected_index = (self.selected_index + offset) % len(self.manifest["discs"])
        self.update_selection(offset)

    def select_up(self) -> None:
        if self.preset in ("list", "showcase", "strip"):
            self.move(-1)
            return
        target = self.selected_index - self.columns
        if target < 0:
            column = self.selected_index % self.columns
            last_row_start = ((len(self.manifest["discs"]) - 1) // self.columns) * self.columns
            target = min(last_row_start + column, len(self.manifest["discs"]) - 1)
        self.selected_index = target
        self.update_selection(-self.columns)

    def select_down(self) -> None:
        if self.preset in ("list", "showcase", "strip"):
            self.move(1)
            return
        target = self.selected_index + self.columns
        if target >= len(self.manifest["discs"]):
            target = min(self.selected_index % self.columns, len(self.manifest["discs"]) - 1)
        self.selected_index = target
        self.update_selection(self.columns)

    def select_left(self) -> None: self.move(-1)
    def select_right(self) -> None: self.move(1)

    def update_selection(self, direction: int = 0) -> None:
        for index, artwork in self.artwork_widgets.items():
            artwork.set_active(index == self.selected_index)
        if self.preset == "showcase":
            if direction:
                transition = (Gtk.StackTransitionType.SLIDE_LEFT
                              if direction > 0 else Gtk.StackTransitionType.SLIDE_RIGHT)
                self.showcase_stack.set_transition_type(transition)
            self.showcase_stack.set_visible_child_name(str(self.selected_index))
        elif self.preset == "list":
            row = self.selection_widget.get_row_at_index(self.selected_index)
            self.selection_widget.select_row(row)
            row.grab_focus()
        else:
            child = self.selection_widget.get_child_at_index(self.selected_index)
            self.selection_widget.select_child(child)
            child.grab_focus()

    def activate_selected(self) -> None:
        self.launch(self.selected_index)

    def launch(self, disc_index: int) -> None:
        command = build_command(self.manifest, self.manifest_path, disc_index)
        self.stop_music()
        if self.dry_run:
            print(shlex.join(command), flush=True)
            self.close()
            return
        try:
            os.execv(command[0], command)
        except OSError as error:
            dialog = Gtk.AlertDialog(message="Could not launch the selected disc")
            dialog.set_detail(str(error))
            dialog.show(self)


class DiscShelfApplication(Gtk.Application):
    def __init__(self, manifest_path: Path, windowed: bool, dry_run: bool, layout_override=None) -> None:
        super().__init__(
            application_id="io.github.discshelf.App",
            flags=Gio.ApplicationFlags.NON_UNIQUE,
        )
        self.manifest_path = manifest_path
        self.windowed = windowed
        self.dry_run = dry_run
        self.layout_override = layout_override
        self.manifest = load_manifest(manifest_path)

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        css = Gtk.CssProvider()
        css.load_from_string(
            """
            window.discshelf { background: #10141c; color: #f5f7fa; }
            .background-solid { background: #10141c; }
            .background-dim { background: #000000; }
            .title { font-size: 40px; font-weight: 800; }
            .subtitle { color: #aeb7c4; font-size: 20px; }
            .disc-list { background: transparent; }
            .disc-list row {
                background: transparent;
                margin: 3px 0;
                opacity: 0.72;
            }
            .disc-list row:selected {
                background: transparent;
                color: #1a9fff;
                opacity: 1;
            }
            .disc-grid { background: transparent; }
            .disc-grid flowboxchild {
                background: transparent;
                border: none;
                opacity: 0.68;
            }
            .disc-grid flowboxchild:selected {
                background: transparent;
                color: #1a9fff;
                opacity: 1;
            }
            .disc-artwork-placeholder {
                background: transparent;
                border: none;
                font-size: 32px;
                font-weight: 800;
            }
            .disc-label { font-size: 25px; font-weight: 650; }
            .grid-label { font-size: 19px; font-weight: 700; }
            .showcase-label { font-size: 30px; font-weight: 800; }
            .footer { color: #aeb7c4; font-size: 17px; }
            """
        )
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def do_activate(self) -> None:
        window = DiscShelfWindow(
            self, self.manifest, self.manifest_path, self.windowed, self.dry_run,
            self.layout_override,
        )
        window.present()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch a DiscShelf game manifest")
    parser.add_argument("--version", action="version", version=f"DiscShelf {RUNTIME_VERSION}")
    parser.add_argument("manifest", type=Path, help="DiscShelf JSON manifest")
    parser.add_argument("--windowed", action="store_true", help="Do not use fullscreen")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the command instead of launching"
    )
    parser.add_argument(
        "--validate", action="store_true", help="Validate the manifest and exit"
    )
    parser.add_argument(
        "--layout", choices=["list", "showcase", "strip", "compact", "wide-grid"],
        help="Temporarily override the manifest layout",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        manifest = load_manifest(args.manifest.resolve())
        if args.validate:
            for index in range(len(manifest["discs"])):
                build_command(manifest, args.manifest.resolve(), index)
            print(f"Valid: {manifest['title']} ({len(manifest['discs'])} discs)")
            return 0
        return DiscShelfApplication(
            args.manifest.resolve(), args.windowed, args.dry_run, args.layout
        ).run(sys.argv[:1])
    except ManifestError as error:
        print(f"DiscShelf: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
