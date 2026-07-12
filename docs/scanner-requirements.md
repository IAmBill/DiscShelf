# Scanner requirements

The production scanner recursively traverses each configured platform root. It
must not require every disc to be in the same immediate directory.

## Candidate grouping

Signals include:

- explicit `disc`, `disk`, `cd`, or `side` markers in filenames;
- equivalent markers in ancestor directory names;
- a common normalized game title after removing only explicit disc markers;
- sequential disc numbers;
- a shared emulator and compatible launch command;
- the nearest common ancestor of all selected launch files.

Sequel numbers remain part of the normalized title. `Shenmue` and `Shenmue 2`
must never merge merely because one title ends in a number.

## Compound images

For paired MDF/MDS images, `.mds` is the launchable descriptor and `.mdf` is a
sidecar data file. A pair represents one disc, not two candidates. Equivalent
descriptor/sidecar formats should be handled through format adapters.

## Manifest placement

The output path is the nearest shared ancestor plus
`<Normalized Title>.discshelf.json`:

```text
dreamcast/Shenmue 2/Shenmue 2.discshelf.json
```

Root-level sets remain in the platform root. Existing manifests are updated
only through an explicit, reversible action.

## Review data

Every candidate group exposes a confidence level and reasons. Users can edit
membership and the output location before creation. Scanner discovery itself
is read-only.

## Emulator capability database and playlist migration

DiscShelf maintains a versioned database of known emulator adapters. Each
adapter records at least:

- executable, Flatpak ID, core, and command-pattern identifiers;
- supported playlist formats, such as M3U;
- whether the emulator accepts a playlist as launch content;
- whether it can select an initial playlist entry from the command line;
- the initial-disc flag and whether its index is zero- or one-based;
- supported disc-image and descriptor formats;
- known save, state, and game-identity implications;
- a tested adapter version and applicable emulator version range.

When a high-confidence multi-disc group uses an emulator with playlist
support, but its individual Steam targets launch disc images directly, the
review screen offers a playlist migration. The proposed action:

1. Creates one canonical playlist beside the game files or in their nearest
   common ancestor.
2. Preserves disc ordering and uses paths relative to the playlist when
   practical.
3. Configures every DiscShelf choice to launch that same playlist.
4. Uses the adapter's initial-disc option when available so the selected disc
   opens first while retaining native in-emulator disc swapping.
5. Falls back to direct per-disc commands when initial-entry selection is not
   supported; reordered temporary playlists require a separate compatibility
   warning because they can affect game identity, saves, or states.

Playlist creation is always previewed and opt-in. DiscShelf validates every
referenced image before changing Steam shortcuts, backs up the original
targets, and records enough information to remove the generated playlist and
restore the individual entries. Existing user-authored playlists are detected
and preserved rather than overwritten.
