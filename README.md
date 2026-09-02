# staccato

Turn a folder of still images (iPhone HEIC, JPEG, PNG, ...) into a timelapse
video, with crossfade-style transitions and an optional inserted video clip
or two.

> **Status:** `staccato build` and `staccato align` are both implemented
> and tested.

## Requirements

- [`ffmpeg`](https://ffmpeg.org/) **version 7.0 or later**, on your `PATH`,
  built with `libx264`. This version floor is not arbitrary: real iPhone
  photos are encoded as a tiled/grid HEIC (multiple independently-decodable
  HEVC tiles, not one plain frame — confirmed by inspecting real files with
  `ffprobe`), and ffmpeg's `mov` demuxer only gained support for that tiled
  HEIF structure via patches from February 2024, landing in ffmpeg 7.x.
  Older ffmpeg can open plain single-frame HEIC but fails on real photos
  with `moov atom not found`.
  - **macOS (Homebrew):** `brew install ffmpeg` — currently ships 9.x, well
    past the floor.
  - **Linux:** check `ffmpeg -version` before assuming your distro's
    package is new enough. Ubuntu 24.04's `apt-get install ffmpeg` gives
    you 6.1.1, which predates tiled-HEIF support entirely and will fail on
    real iPhone photos (this bit our own CI — see
    [tests/test_integration.py](tests/test_integration.py), which probes
    for this capability directly and skips the affected tests rather than
    assuming a version number). Homebrew also works on Linux and tracks
    current ffmpeg releases, so it's a reliable way to get a new-enough
    build there too.
- [`exiftool`](https://exiftool.org/) on your `PATH`, used to read capture
  timestamps for ordering (`brew install exiftool`).

## Install

**For development (run and test locally, from a clone of this repo):**

```
python3 -m venv .venv
source .venv/bin/activate       # .venv\Scripts\activate on Windows
pip install -e ".[dev]"
staccato --help
```

A virtual environment isn't optional busywork here — recent Python
installs (Homebrew, Debian/Ubuntu system Python) refuse a bare `pip
install` outside one ([PEP 668](https://peps.python.org/pep-0668/)), so
the venv step above is what makes `pip install -e ".[dev]"` work at all.
`-e` means edits to the source take effect immediately, no reinstall
needed; `[dev]` pulls in `pytest` too (see [Testing](#testing)). Once
installed, `staccato` and `pytest` both work as long as this venv is
active — reactivate it in new shells with the `source` line above.

**From source, non-editable:**

```
pip install .
```

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
| `--cache` / `--no-cache` | `--cache` | See [Normalization cache](#normalization-cache). |
| `--crf <n>` | `23` | libx264 quality factor, 0 (lossless) to 51 (worst). Lower = larger file. Mutually exclusive with `--size`. See [File size](#file-size). |
| `--size <level>` | — | Shortcut for `--crf`, framed by output size instead of a quality number: `smallest`/`smaller`/`default`/`larger`/`largest`. Mutually exclusive with `--crf`. See [File size](#file-size). |
| `--preset <name>` | `medium` | libx264 encoder effort (`ultrafast` … `veryslow`). Slower = smaller file at the same `--crf`, at the cost of encode time. See [File size](#file-size). |
| `-h`, `--help` | | Show help. |
| `-v`, `--version` | | Show version. |

If neither `--duration-per-image` nor `--total-duration` is given, and none
is set in the config file, `--total-duration 120` is assumed.

Flags override matching values from the config file; the config file
overrides built-in defaults.

### File size

`--max-dimension` (resolution) affects file size, but it's usually not the
most effective lever, and it's the one visible change to the actual video.
Three more, all about how hard the encoder compresses rather than what it's
encoding:

- **`--crf <n>`** — the direct libx264 knob. Lower is higher quality and a
  larger file; higher is smaller and lossier. Default `23`. Roughly
  logarithmic: **+6 ≈ half the file size, −6 ≈ double it** (content-
  dependent, not exact).
- **`--size <level>`** — the same knob, framed the other way round: you're
  choosing "smaller/larger file," and `crf` is just the mechanism.
  `smallest`=35, `smaller`=29, `default`=23, `larger`=17, `largest`=11 —
  each step is one of those ±6 doublings/halvings. Mutually exclusive with
  `--crf` (pick whichever way you think about it).
- **`--preset <name>`** — how hard the encoder searches for a good
  compression, independent of `--crf`. The usual x264 wisdom is that slower
  presets shrink the file at the same `--crf` for free (just costing encode
  time) — but measured on a real 179-image build at both 600px and 1920px,
  `slow` vs `medium` at identical `--crf` made **no measurable difference**
  (within ~1%, and slow was occasionally very slightly *larger*). This
  content is mostly static, slowly-changing crossfades, which apparently
  doesn't leave much for a slower mode-decision search to find — the usual
  rule of thumb just doesn't hold here. `--crf`/`--size` is the lever that
  actually works for this kind of content; don't expect much from
  `--preset` beyond slower encodes.

None of these three affect the [normalization cache](#normalization-cache)
— they only change the final encode step, so switching between them on a
re-run is always fast regardless of `--cache`.

### Normalization cache

Decoding and scaling images (the "normalize" step — see
[How it works](#how-it-works)) is the expensive part of a build, and it
doesn't depend on transitions, durations, or ordering at all — only on the
source file itself and `--max-dimension`. So normalized frames are cached
by default, keyed by each source file's path/size/mtime plus the target
dimensions: re-running `build` against the same images with only
`--transition`/`--duration-per-image`/etc. changed skips normalization
entirely and jumps straight to assembling the video.

Each independent image is also normalized in parallel (bounded to your CPU
core count), since normalizing one image has no dependency on any other.
Together, on a 179-image real-world run, this took a build from **10:38
(cold, sequential) → 2:41 (cold, parallel) → 1:18 (warm cache, only the
transition changed)**.

The cache lives at `~/.cache/staccato` (override with `$STACCATO_CACHE_DIR`
or `$XDG_CACHE_HOME`) and isn't size-limited — clear it manually
(`rm -rf ~/.cache/staccato`) if it grows larger than you'd like.
`--no-cache` neither reads nor writes it, for a guaranteed-fresh decode
(e.g. after upgrading ffmpeg) without touching cached results from other
runs.

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
   scaled/padded to a common frame size) via `ffmpeg`, in parallel across
   images and cached — see [Normalization cache](#normalization-cache).
2. Each normalized image (or inserted video clip) becomes one input, held
   for its configured duration.
3. Adjacent inputs are joined with a chained `xfade` filtergraph, producing
   the configured transition and overlap timing.
4. The result is encoded as H.264 / `yuv420p` MP4 with `+faststart`, for
   broad playback compatibility (QuickTime, mobile browsers, etc.).

## `staccato align`

Corrects frame-to-frame drift in images shot from roughly the same
physical position over time — the motivating case is a construction site
photographed periodically, hand-held rather than tripod-mounted, so
framing drifts slightly shot to shot. `align` is a separate preprocessing
step: it reads a directory of images and writes a directory of aligned
ones, which then becomes ordinary input to `staccato build` — no special
handling needed on `build`'s side.

```
staccato align <input-dir> [options]
```

Requires the optional `align` extra: `pip install staccato[align]` (adds
OpenCV and NumPy). See [ARCHITECTURE.md](ARCHITECTURE.md#staccato-align)
for the full design — why ECC over feature-matching, why images are
aligned sequentially within a group rather than all against one fixed
reference, how drift and alignment failures are handled, and the
thumbnail-first workflow below.

### Options

| Flag | Default | Description |
|---|---|---|
| `-o`, `--output <dir>` | `./aligned` | Output directory for aligned images. |
| `-c`, `--config <file>` | `<input-dir>/staccato.toml` if present | Config file for `[[align.group]]` — see [CONFIG.md](CONFIG.md). |
| `--max-dimension <px>` | `1920` | Decode/scale images to this size before aligning. Independent of `build`'s own `--max-dimension` — see [Thumbnail-first workflow](#thumbnail-first-workflow). |
| `--warp <model>` | `euclidean` | `euclidean` (translation + rotation) or `affine` (+ scale/shear; tolerates more drift, more risk of misreading real scene change as camera motion). |
| `--crop` / `--no-crop` | `--crop` | Crop each group to its common aligned region, removing warp borders. |
| `--cache` / `--no-cache` | `--cache` | Cache ECC transforms — see [Transform cache](#transform-cache). |

With no config file, every image in `<input-dir>` is treated as one
group, ordered chronologically by EXIF capture time, keyed on the
earliest. Use `[[align.group]]` in `staccato.toml` to define multiple
groups — see [CONFIG.md](CONFIG.md#align).

### Thumbnail-first workflow

`align`'s `--max-dimension` is independent of `build`'s. Point it at a
small size first for a fast pass (tens of seconds instead of minutes even
across hundreds of images), inspect whether the grouping/key choices and
warp model produce sane results, adjust `staccato.toml` and re-iterate
quickly — then bump `--max-dimension` up for the real, full-resolution
output once you're happy:

```
staccato align ./photos --max-dimension 400 -o ./aligned-preview
staccato build ./aligned-preview -o preview.mp4 --duration-per-image 0.3

# happy with it? run the real pass:
staccato align ./photos --max-dimension 1920 -o ./aligned
staccato build ./aligned -o timelapse.mp4
```

Each resolution is a fully independent cache entry (both the [normalize
cache](#normalization-cache) `align` reuses and its own transform cache),
so the preview and full-resolution passes never interfere with each
other, and switching back to a resolution you've already run is instant.

### Transform cache

The expensive part of `align` is ECC's iterative optimization, which
scales with pixel count. Because chained alignment makes each image's
result depend on everything before it in its group, what's cached is the
small transform matrix for each image (not the image itself), keyed on a
hash of the image's whole chain prefix plus `--warp`/`--max-dimension`.
This means touching an early image in a chain correctly invalidates every
cached transform after it — that's not a bug to work around, since drift
genuinely is chain-dependent. `--no-cache` neither reads nor writes it.
The cache shares its root with the [normalization
cache](#normalization-cache) (`~/.cache/staccato`, override with
`$STACCATO_CACHE_DIR`).

### Example

```
staccato align ./photos -o ./aligned --max-dimension 400   # fast preview
staccato align ./photos -o ./aligned                        # full-res, once happy
staccato build ./aligned -o timelapse.mp4
```

## Testing

With the development venv from [Install](#install) active:

```
pytest                      # everything
pytest -m "not integration" # fast unit tests only, no ffmpeg/exiftool needed
```

Unit tests cover the ordering/config/transition/duration logic with no
external tools involved. A couple of `integration`-marked tests actually
invoke `ffmpeg`/`ffprobe`/`exiftool` against `samples/` to check the real
pipeline end to end; they're skipped automatically if those tools aren't
on `PATH`.

## Roadmap

- Per-image motion (Ken Burns-style pan/zoom), independent of transitions.
- Seeding a full-resolution `align` run's ECC optimization from a prior
  thumbnail-resolution run's result, for a faster and more reliable
  full-res pass — see the note at the end of
  [ARCHITECTURE.md](ARCHITECTURE.md#staccato-align).
