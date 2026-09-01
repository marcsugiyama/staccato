# staccato

Turn a folder of still images (iPhone HEIC, JPEG, PNG, ...) into a timelapse
video, with crossfade-style transitions and an optional inserted video clip
or two.

> **Status:** this documents the planned CLI. Implementation in progress.

## Requirements

- [`ffmpeg`](https://ffmpeg.org/) on your `PATH`, built with HEIF demuxer
  support and `libx264` (Homebrew's `ffmpeg` formula covers both:
  `brew install ffmpeg`).
- [`exiftool`](https://exiftool.org/) on your `PATH`, used to read capture
  timestamps for ordering (`brew install exiftool`).

## Install

**From source (works today):**

```
pip install .
```

or, for development, `pip install -e .`.

**Planned, once a release is published:**

- **Homebrew (macOS & Linux):** `brew install marcsugiyama/staccato/staccato`
  — a Homebrew formula can declare `ffmpeg` and `exiftool` as dependencies,
  so this pulls in everything needed automatically. Homebrew runs on Linux
  too, so this covers both platforms from one formula/tap.
- **pipx (any OS with Python 3.11+):** `pipx install staccato` — installs
  into an isolated environment without touching your system Python. You'll
  need `ffmpeg` and `exiftool` on your `PATH` yourself; see
  [Requirements](#requirements).

The align feature's dependencies (OpenCV, NumPy) are an optional extra
(`pip install staccato[align]`) so installing the base tool stays light.

## Usage

```
staccato build <input-dir> [options]
```

`<input-dir>` is a folder of images (and optionally a config file — see
[CONFIG.md](CONFIG.md)). By default, images are:

- filtered to recognized image extensions (`.heic`, `.jpg`, `.jpeg`, `.png`, ...),
- ordered by capture timestamp (see [Ordering](#ordering)),
- each shown for an equal duration,
- joined by a crossfade.

### Options

| Flag | Default | Description |
|---|---|---|
| `-o`, `--output <file>` | `timelapse.mp4` | Output video path. |
| `-c`, `--config <file>` | `<input-dir>/staccato.toml` if present | Config file for per-image overrides, inserted clips, ordering lists, etc. See [CONFIG.md](CONFIG.md). |
| `--duration-per-image <secs>` | — | Seconds each image is shown. Decimals allowed (e.g. `0.77`). Mutually exclusive with `--total-duration`. |
| `--total-duration <secs>` | — | Target total video length; per-image duration is derived. Mutually exclusive with `--duration-per-image`. |
| `--transition-duration <secs>` | `0.1` | Length of the crossfade between adjacent images. This overlaps adjacent display windows rather than adding to them — see [Transitions](#transitions). |
| `--transition <type>` | `fade` | Transition style. See [Transitions](#transitions). |
| `--order <mode>` | `timestamp` | `timestamp` or `filename`. (`explicit` ordering is config-file-only — see [CONFIG.md](CONFIG.md).) |
| `--fps <n>` | `30` | Output frame rate. |
| `--max-dimension <px>` | `1920` | Caps the longer output edge; images are downscaled (never upscaled) to fit. `0` disables the cap and encodes at native resolution — slower and much larger output, since iPhone photos run well beyond 1080p. |
| `-h`, `--help` | | Show help. |
| `-v`, `--version` | | Show version. |

If neither `--duration-per-image` nor `--total-duration` is given, and none
is set in the config file, `--total-duration 120` is assumed.

Flags override matching values from the config file; the config file
overrides built-in defaults.

### Ordering

- **`timestamp`** (default) — sorts by EXIF `DateTimeOriginal`. Files
  without EXIF data fall back to filesystem mtime. Ties are broken by
  filename.
- **`filename`** — plain lexicographic sort. Works correctly for iPhone's
  zero-padded `IMG_####` naming; may misorder inconsistently-padded names.
- **`explicit`** — the full file list and order come from `order_list` in
  the config file, which also acts as an inclusion filter (files not
  listed are skipped). Config-file-only; see [CONFIG.md](CONFIG.md).

### Transitions

Crossfades and wipes are implemented via ffmpeg's `xfade` filter. Supported
values for `--transition` / the config file's `transition` fields:

| Value | Description |
|---|---|
| `cut` | Hard cut, no crossfade. |
| `fade` | Classic crossfade/dissolve (default). |
| `fadeblack` | Fade through black. |
| `fadewhite` | Fade through white. |
| `wipe-left`, `wipe-right`, `wipe-up`, `wipe-down` | Directional wipe. |
| `slide-left`, `slide-right`, `slide-up`, `slide-down` | Directional slide. |
| `circleopen`, `circleclose` | Circular reveal. |
| `pixelize` | Pixelate through the transition. |
| `random` | Pick randomly per transition from a pool (config-file-only; see [CONFIG.md](CONFIG.md)). |
| `raw:<name>` | Pass any [ffmpeg `xfade` transition name](https://ffmpeg.org/ffmpeg-filters.html#xfade) straight through. |

Transition duration is **subtracted** from, not added to, the surrounding
images' display time — each transition overlaps the tail of one image's
window with the head of the next, so:

```
total_duration = (n_images × duration_per_image) − ((n_images − 1) × transition_duration)
```

### Examples

Quick timelapse, all defaults, ~2 minutes total:

```
staccato build ./photos -o house.mp4
```

Faster pace, explicit per-image duration, snappier wipe transition:

```
staccato build ./photos --duration-per-image 0.5 --transition-duration 0.1 --transition wipe-left
```

Using a config file for per-image overrides and an inserted video clip
(see [CONFIG.md](CONFIG.md)):

```
staccato build ./photos --config ./photos/staccato.toml -o house.mp4
```

## How it works

1. Images are decoded and normalized (orientation-corrected via EXIF,
   scaled/padded to a common frame size) via `ffmpeg`.
2. Each normalized image (or inserted video clip) becomes one input, held
   for its configured duration.
3. Adjacent inputs are joined with a chained `xfade` filtergraph, producing
   the configured transition and overlap timing.
4. The result is encoded as H.264 / `yuv420p` MP4 with `+faststart`, for
   broad playback compatibility (QuickTime, mobile browsers, etc.).

## Testing

```
pip install -e ".[dev]"
pytest                      # everything
pytest -m "not integration" # fast unit tests only, no ffmpeg/exiftool needed
```

Unit tests cover the ordering/config/transition/duration logic with no
external tools involved. A couple of `integration`-marked tests actually
invoke `ffmpeg`/`ffprobe`/`exiftool` against `samples/` to check the real
pipeline end to end; they're skipped automatically if those tools aren't
on `PATH`.

## Roadmap

- `staccato align` — a separate preprocessing subcommand for correcting
  frame-to-frame drift in images shot from roughly the same position
  (e.g. a construction site photographed weekly). Outputs aligned images
  to a new directory, which then feed into `staccato build` like any
  other input. See the `[align]` section in [CONFIG.md](CONFIG.md) for
  the reserved (not yet implemented) config shape.
- Per-image motion (Ken Burns-style pan/zoom), independent of transitions.
