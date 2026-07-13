# DiscShelf prototype

THIS PROJECT WAS BUILT WITH THE SUPPORT OF CHAT-GPT 5.6 Sol.

DiscShelf presents a fullscreen list of discs and replaces itself with the
configured emulator launcher after a selection. It uses GTK 4 and PyGObject,
which are already installed on Bazzite.

The prototype is currently version `0.2.0-dev`. Query it without opening the
interface:

```sh
/home/bazzite/DiscShelf/discshelf --version
```

Reusable manifest validation, path handling, and command construction live in
`discshelf_core.py`; the GTK runtime imports that module. The formal manifest
definition is `schema/discshelf-manifest-v1.schema.json`. Architecture and
future scanner behavior are recorded under `docs/`.

## Disc artwork

Each disc can specify optional PNG, JPEG, WebP, or SVG artwork:

```json
{
  "label": "Disc 1",
  "artwork": "/home/bazzite/Pictures/discs/disc-1.svg",
  "path": "/home/bazzite/Emulation/roms/dreamcast/game-disc-1.chd"
}
```

Artwork paths can be absolute or relative to the manifest file. Leave
`artwork` as an empty string to show the numbered placeholder. Missing artwork
also falls back to the placeholder rather than preventing the game from
launching.

## Background

Set one launcher-level background image and the black dimming strength:

```json
"background": {
  "image": "/home/bazzite/Pictures/discshelf/shenmue-background.jpg",
  "dim": 0.7
}
```

The image uses full-screen `cover` sizing. `dim` accepts values from `0` to
`1`; `0.7` places a 70% black layer over the image.

## Background music

DiscShelf can play optional launcher-level music while the selector is open:

```json
"music": {
  "path": "/home/bazzite/Music/shenmue-selector.mp3",
  "volume": 0.35,
  "loop": true
}
```

Paths can be absolute or relative to the manifest. Volume ranges from `0` to
`1`. Music loops by default and stops immediately when a disc launches or the
selector closes. Leave `path` blank to disable music without removing the
configuration block. A missing or unplayable file reports an error but does
not prevent the selector or game from launching.

## Selected-disc animations

Animations begin after a disc remains selected for its configured delay. They
stop and reset as soon as selection moves away.

Continuous spin:

```json
"animation": {
  "type": "spin",
  "delay": 2.5,
  "revolutionsPerMinute": 12
}
```

Back-and-forth rotation with vertical movement:

```json
"animation": {
  "type": "wiggle",
  "delay": 2.5,
  "angle": 30,
  "distance": 10,
  "period": 1.8
}
```

Use `"type": "none"` to disable animation for an individual disc. Delay and
period values are seconds, angle is degrees in each direction, and distance is
pixels.

## Layouts

Set `selector.layout.preset` to one of:

- `list`: vertically scrolling artwork rows.
- `showcase`: one large centered selection at a time.
- `strip`: a single horizontally scrolling artwork row.
- `compact`: a 2×2 grid.
- `wide-grid`: a 3×2 grid.

The optional `columns` and `rows` values override a preset's defaults. Rows
describe the intended visible viewport; additional discs scroll naturally.
To preview a layout without changing a manifest, use for example:

```sh
/home/bazzite/DiscShelf/discshelf --windowed --dry-run --layout compact \
  /home/bazzite/DiscShelf/games/dreamcast/shenmue.json
```

## Run

For example:

```sh
/home/bazzite/DiscShelf/discshelf \
  /home/bazzite/DiscShelf/games/dreamcast/shenmue.json
```

Use the D-pad or left stick to choose, A to launch, and B to return to Steam.
The arrow keys, Enter, Escape, and Backspace provide equivalent keyboard
controls. Mouse movement highlights entries, clicks select them, and the wheel
moves through Showcase. Controller input has priority over keyboard input;
both hide the pointer and briefly suppress hover changes so a stationary mouse
cannot steal selection.

For desktop testing without starting RetroArch:

```sh
/home/bazzite/DiscShelf/discshelf --windowed --dry-run \
  /home/bazzite/DiscShelf/games/dreamcast/shenmue.json
```

Validate a manifest without opening a window:

```sh
/home/bazzite/DiscShelf/discshelf --validate MANIFEST.json
```

Run the core compatibility tests:

```sh
cd /home/bazzite/DiscShelf
python3 -m unittest discover -s tests -v
```

## Baseline Decky plugin

The first Decky management plugin lives in `decky-plugin/`. It currently:

- detects the installed or development DiscShelf runtime and reports its
  version;
- recursively discovers adjacent `*.discshelf.json` manifests under platform
  ROM roots;
- keeps the three prototype manifests visible until they are migrated;
- summarizes validation state, disc count, and layout;
- launches a valid manifest for testing from Game Mode;
- does not modify Steam shortcuts or ROM directories.

Build and test it with:

```sh
cd /home/bazzite/DiscShelf/decky-plugin
pnpm install
pnpm test
pnpm build
python3 -m unittest discover -s tests -v
```

For local development, build first and then run
`scripts/deploy-local.sh` through `pkexec` or `sudo`. The deployment script
copies only the plugin runtime files and restarts `plugin_loader.service`.

## Steam shortcut

Set the target to `/home/bazzite/DiscShelf/discshelf` and the launch options
to the absolute path of one game JSON file. No Proton compatibility tool is
needed.
