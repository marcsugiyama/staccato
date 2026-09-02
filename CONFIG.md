# Config file reference

`staccato` reads an optional [TOML](https://toml.io/) file for anything
beyond the common case that `staccato build`'s flags cover directly:
per-image overrides, inserted video clips, explicit ordering, and (once
implemented) image-alignment preprocessing.

By convention, this file is named `staccato.toml` and lives in the same
directory as the images it describes, so the two travel together. Point at
a different file with `--config`.

**Precedence:** CLI flags override values in `[build]`, which override
built-in defaults. Nothing in this file is required — an empty or absent
config file just means "use the defaults."

## `[build]`

Global settings for `staccato build`. All fields are optional and mirror
the CLI flags of the same purpose (see [README.md](README.md#options)).

```toml
[build]
duration_per_image = 0.77      # seconds; decimals allowed
# total_duration = 120         # alternative to duration_per_image; mutually exclusive
transition_duration = 0.1      # seconds
transition = "fade"            # see README.md#transitions
order = "timestamp"            # "timestamp" | "filename" | "explicit"
fps = 30
max_dimension = 1920
crf = 23                        # or use size instead; mutually exclusive
preset = "medium"
output = "construction-timelapse.mp4"
```

| Field | Type | Notes |
|---|---|---|
| `duration_per_image` | float (seconds) | Mutually exclusive with `total_duration`. |
| `total_duration` | float (seconds) | Mutually exclusive with `duration_per_image`. |
| `transition_duration` | float (seconds) | Overlaps adjacent images' display windows; see README's [Transitions](README.md#transitions). |
| `transition` | string | One of the values listed in the README, or `random` (see below), or `raw:<xfade-name>`. |
| `order` | string | `"timestamp"`, `"filename"`, or `"explicit"`. `"explicit"` requires `order_list` (below). |
| `order_list` | array of strings | Required when `order = "explicit"`. Complete, ordered list of filenames to include — files not listed are excluded. |
| `random_pool` | array of strings | Used when `transition = "random"`. Pool of transition types to pick from per junction. Defaults to all non-`cut` types if omitted. |
| `fps` | integer | Output frame rate. |
| `max_dimension` | integer | Caps the longer output edge, in pixels; `0` disables the cap. Default `1920`. |
| `crf` | integer (0-51) | libx264 quality factor; lower = larger/better. Default `23`. Mutually exclusive with `size`. See README's [File size](README.md#file-size). |
| `size` | string | `"smallest"`, `"smaller"`, `"default"`, `"larger"`, or `"largest"` — a `crf` shortcut framed by output size. Mutually exclusive with `crf`. |
| `preset` | string | libx264 encoder effort: `ultrafast` … `veryslow`. Default `medium`. See README's [File size](README.md#file-size) for a measured caveat about its actual effect on this kind of content. |
| `output` | string | Output file path. Overridden by `-o`/`--output` if given. |

### Explicit ordering example

```toml
[build]
order = "explicit"
order_list = [
  "IMG_2993.HEIC",
  "IMG_3016.HEIC",
  "IMG_3054.HEIC",   # note: out of chronological order, and IMG_3024 dropped
]
```

## `[[segment]]`

Zero or more per-image/per-clip overrides. You only need an entry for
files that differ from the defaults — everything else in the scanned (or
`order_list`'d) sequence uses `[build]`'s settings untouched.

```toml
[[segment]]
file = "IMG_3054.HEIC"
duration = 3.0                 # hold longer on this one
transition_in = "wipe-left"    # override the transition leading into it

[[segment]]
file = "walkthrough.mov"
type = "video"
after = "IMG_3041.HEIC"        # insert after this file, since it's not part of the image scan
trim_start = 2.0
trim_end = 8.0
```

| Field | Type | Applies to | Notes |
|---|---|---|---|
| `file` | string | all | Filename (relative to the input directory). |
| `type` | `"image"` \| `"video"` | all | Inferred from file extension if omitted. |
| `duration` | float (seconds) | image | Overrides `duration_per_image` for this image. |
| `transition_in` | string | all | Overrides `transition` for the junction before this segment. |
| `transition_out` | string | all | Overrides `transition` for the junction after this segment. |
| `after` | string | insertions | Filename of the segment this one is inserted immediately after. Required when `file` isn't already part of the base sequence (e.g. a video clip). Mutually exclusive with `before`. |
| `before` | string | insertions | Same as `after`, but inserts immediately before the named segment. |
| `trim_start` | float (seconds) | video | Start offset within the source clip. |
| `trim_end` | float (seconds) | video | End offset within the source clip. |

A `[[segment]]` entry whose `file` matches something already in the base
sequence (from the directory scan or `order_list`) is treated as an
**override** — `after`/`before` are ignored for those. If `file` doesn't
match anything in the base sequence, `after` or `before` is required so
`staccato` knows where to splice it in.

## `[align]`

Configuration for `staccato align`, a separate preprocessing subcommand
that corrects frame-to-frame drift for images shot from roughly the same
physical position (e.g. a construction site photographed over months).
`align` writes corrected images to a new directory; that directory is then
used as ordinary input to `staccato build`. See
[ARCHITECTURE.md](ARCHITECTURE.md#staccato-align) for the full design
rationale — this section is the field reference.

Alignment is **sequential within each group**: the key anchors the first
pairwise alignment, and each subsequent image aligns against the
*previous image's already-aligned result*, not against the fixed key —
this keeps every pairwise comparison between visually similar (adjacent)
images, which is what makes alignment work reliably over a long,
gradually-changing series. Groups are where you manually reset the chain
to a fresh anchor (e.g. after a big visible change like scaffolding
coming down). No `[align]` section at all is valid and means: one
implicit group spanning every image in the input directory, ordered
chronologically, keyed on the earliest.

```toml
[align]
method = "ecc"                 # only option currently
warp = "euclidean"             # "euclidean" (default, translation+rotation) | "affine"
crop = true                    # crop each group to its common aligned region
max_dimension = 1920           # decode/scale to this size before aligning; separate from build's
output = "aligned"             # output directory for aligned images

[[align.group]]
key = "IMG_2993.HEIC"          # starting anchor; chain proceeds chronologically from here
images = ["IMG_2993.HEIC", "IMG_3016.HEIC", "IMG_3024.HEIC"]

[[align.group]]
key = "IMG_3041.HEIC"          # a fresh anchor -- resets drift accumulated in the group above
images = ["IMG_3041.HEIC", "IMG_3054.HEIC"]
```

| Field | Type | Notes |
|---|---|---|
| `method` | string | `"ecc"` — intensity-based alignment (`cv2.findTransformECC`); the only option currently. Deliberately not feature-matching, which performs poorly here since the scene's own features (framing, siding, scaffolding) are what's changing between shots. |
| `warp` | string | `"euclidean"` (default: translation + rotation only) or `"affine"` (+ scale/shear, tolerates more drift but more likely to misattribute real scene change as camera motion). |
| `crop` | boolean | Default `true`. Crops each group to the common region valid across every image in its chain, removing warp borders. `false` keeps full frames with visible borders. |
| `max_dimension` | integer | Decode/scale images to this size before aligning. Independent of `build`'s own `max_dimension` — lower it for a fast preview pass; see [ARCHITECTURE.md](ARCHITECTURE.md#staccato-align). Default `1920`. |
| `output` | string | Output directory for aligned images. Overridden by `-o`/`--output` if given. Default `aligned`. |
| `[[align.group]]` | array of tables | One group per chain. A group boundary is a manual drift-reset point. |
| `align.group.key` | string | Filename of the starting anchor for this group's chain. |
| `align.group.images` | array of strings | Filenames in this group, including the key, in the order the chain should process them (typically chronological). |

## Full example

```toml
# staccato.toml — lives alongside the photos it describes

[build]
duration_per_image = 0.77
transition_duration = 0.1
transition = "fade"
order = "timestamp"
fps = 30
output = "construction-timelapse.mp4"

[[segment]]
file = "IMG_3054.HEIC"
duration = 3.0
transition_in = "wipe-left"

[[segment]]
file = "walkthrough.mov"
type = "video"
after = "IMG_3041.HEIC"
trim_start = 2.0
trim_end = 8.0

[align]
method = "ecc"
warp = "euclidean"
crop = true

[[align.group]]
key = "IMG_2993.HEIC"
images = ["IMG_2993.HEIC", "IMG_3016.HEIC", "IMG_3024.HEIC"]

[[align.group]]
key = "IMG_3041.HEIC"
images = ["IMG_3041.HEIC", "IMG_3054.HEIC"]
```
