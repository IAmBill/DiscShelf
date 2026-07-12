# DiscShelf architecture and stable paths

DiscShelf separates its reusable domain model from presentation and process
integration:

```text
discshelf_core.py
├── manifest loading and validation
├── path resolution
├── launch command construction
└── stable XDG paths

renderers
├── current GTK/Game Mode runtime
└── possible future Decky/Steam renderer
```

Both renderers must consume the same versioned manifest and core launch model.
Steam interception or a Decky-native renderer must not be embedded in the
manifest format.

## Stable user paths

- Runtime installed by Decky: `~/.local/share/discshelf/bin/discshelf`
- Runtime support files: `~/.local/share/discshelf/runtime/`
- Plugin/runtime state: `~/.local/share/discshelf/state/`
- User configuration: `~/.config/discshelf/`
- Replaceable cache and scanner results: `~/.cache/discshelf/`
- Logs: `~/.local/state/discshelf/` when available, otherwise the data state
  directory

Game manifests are deliberately not centralized. The scanner writes a
`<Game Title>.discshelf.json` file into the nearest common ancestor containing
that game's disc set. This makes manifests portable with their ROMs.

The prototype executable and manifests remain in `/home/bazzite/DiscShelf`
until Decky installation and Steam-shortcut migration are implemented. Existing
paths must continue working throughout migration.
