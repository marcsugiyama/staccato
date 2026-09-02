# Architecture

Internal design notes: module responsibilities, data flow, and the
reasoning behind non-obvious decisions. [README.md](README.md) and
[CONFIG.md](CONFIG.md) describe *how to use* staccato; this describes
*how it works inside* and *why it's built this way*, for whoever (human
or AI) picks this up next without wanting to reverse-engineer intent from
the code.

## `staccato build`

### Module map

| Module | Responsibility |
|---|---|
| `cli.py` | Argument parsing, CLI/config merge precedence, orchestration. |
| `config.py` | `staccato.toml` loading; `BuildOptions` resolution (CLI > config > default). |
| `sequence.py` | Turns `(input dir, order, order_list, [[segment]] overrides)` into an ordered list of `ResolvedSegment`, and resolves each segment's display duration. |
| `exif.py` | Batched `exiftool` capture-timestamp reads, for `order = "timestamp"`. |
| `transitions.py` | Schema transition names (`wipe-left`) → ffmpeg `xfade` names (`wipeleft`); resolves `cut`/`random`/`raw:`. |
| `timing.py` | Pure math: xfade offset computation, deriving a default per-image duration from a target total duration. |
| `ffmpeg_pipeline.py` | The actual ffmpeg work: normalize (decode/orient/scale), build and run the `xfade` filtergraph command. |
| `cache.py` | Content-addressed cache for normalized frames. |
| `deps.py` | Checks `ffmpeg`/`ffprobe`/`exiftool` are on `PATH`. |

### Data flow

```
input dir + staccato.toml
  -> scan_base_files()          (sequence.py: directory scan or order_list, sorted)
  -> apply_segment_overrides()  (sequence.py: [[segment]] overrides/insertions)
  -> resolve_durations()        (sequence.py + timing.py: per-segment display length)
  -> build_video()              (ffmpeg_pipeline.py)
       -> normalize each image in parallel, cached (cache.py)
       -> compute xfade offsets (timing.py)
       -> build one ffmpeg -filter_complex command, run it
  -> output .mp4
```

### Why two ffmpeg passes, not one

The obvious design is one `ffmpeg` invocation: N inputs, one filtergraph
scaling/padding each and chaining `xfade` between them. That's what the
first implementation did, and it fell over at real scale (179 iPhone
photos): normalizing at full native resolution (~4032x3024) inside that
one command meant N simultaneous decoded buffers held in memory
regardless of the eventual output size, which was enough to start
swapping — turning a ~3s/image linear operation into "still running after
20 minutes." Splitting into normalize-then-assemble, with normalize
scaling down to the target size immediately, fixed it: see git history
around the `--max-dimension` and normalize-time-scaling changes for the
measurements.

A second, unrelated ffmpeg limitation forced the same split for a
different reason: a tiled/grid-encoded HEIC (which is how real iPhone
photos are actually stored — dozens of independently-decodable HEVC
tiles, not one frame) makes ffmpeg reconstruct it via its own internal
complex filtergraph, and ffmpeg refuses to combine that with an
additional `-vf` scale filter on the same output ("Simple and complex
filtering cannot be used together for the same stream"). So even
disregarding the memory issue, HEIC decode and scaling can't be one
ffmpeg command — normalize does decode-then-scale as two `ffmpeg` calls
internally for exactly this reason (see `normalize_image`'s docstring).

### Caching and parallelism

Normalizing (decode + scale) is independent per image and doesn't depend
on anything else in the config (not transitions, not durations, not
ordering) — only on the source file's identity and the target dimensions.
So:

- Each image normalizes in its own thread (`ThreadPoolExecutor`, bounded
  to `os.cpu_count()`), since `subprocess.run` releases the GIL while
  waiting on the child `ffmpeg` process — this is real OS parallelism,
  not just Python-level concurrency.
- Results are cached by `cache.py`, keyed on `(source path, size, mtime,
  target width x height)` — not file content, since hashing hundreds of
  megabytes of HEIC on every run just to check the cache would defeat
  the point.

Net effect on a real 179-image build: 10:38 (cold, sequential, pre-fix)
→ 2:41 (cold, parallel) → 1:18 (warm cache, only a transition changed).

## `staccato align`

Status: designed, not yet fully implemented as of this writing — this
section is the spec the implementation follows, written first so intent
doesn't have to be reverse-engineered from the code later.

### Purpose

Corrects frame-to-frame drift in a series of images shot from roughly
the same physical position over time (the motivating case: a construction
site photographed periodically over months, camera hand-held rather than
tripod-mounted, so framing drifts slightly shot to shot). `align` is a
**separate preprocessing step**, not part of `build`: it reads a
directory of source images and writes a directory of aligned images,
which then becomes ordinary input to `staccato build` — clean seam, no
coupling beyond "a folder of images in, a folder of images out."

### Algorithm: ECC, not feature-matching

OpenCV offers two broad families for this: feature-matching (ORB/SIFT +
`findHomography`) and direct intensity-based alignment
(`cv2.findTransformECC`). Feature-matching is the wrong tool here
specifically *because* the subject is a construction site: the visual
features being matched are themselves disappearing and changing between
shots (scaffolding goes up and comes down, walls change color, framing
becomes drywall), which is exactly the situation feature detectors handle
badly. ECC instead directly maximizes pixel-intensity correlation between
two images under a chosen geometric transform — it doesn't need stable
discrete features, just an overall scene that's mostly the same between
two *adjacent* (not distant) shots.

### Warp model: Euclidean by default

ECC supports translation-only, Euclidean (translation + rotation),
affine (+ scale/shear), or full homography. Homography is the most
flexible but the most dangerous here: with enough degrees of freedom, and
a scene that's genuinely changing underneath it (not just camera
motion), ECC's optimizer can converge on a transform that "explains away"
real construction changes as if they were perspective distortion,
producing a warped, wrong-looking result rather than failing loudly.
Euclidean (translation + rotation only) is the default: it directly
matches the actual failure mode being corrected (a hand-held phone at
roughly the same spot drifts in position and tilts slightly, it doesn't
change lens or perspective), and it's the least likely to misattribute
real scene change as camera motion. Affine is available as an opt-in for
users who need to tolerate more drift and accept the higher risk.

### Sequential chaining, not one fixed reference per group

The obvious design is: pick one reference ("key") image per group, align
every other image in the group against it. This fails in practice for a
long-running series: an image from month 6 may look nothing like the key
from month 1 (different construction phase entirely), so ECC has little
chance of converging well, or converges on a bad answer.

Instead, alignment is **sequential within a group**: the key anchors the
first pairwise alignment, and each subsequent image aligns against the
*previous image's already-aligned output* — image 2 aligns to the key,
image 3 aligns to image 2's aligned result, and so on down the chain.
This means every pairwise ECC problem is between two images that are
actually similar (adjacent in time), which is what ECC needs to work
well, and it removes any need to hand-pick "which images belong in one
group" based on visual similarity to a single reference — a chain handles
gradual change naturally.

The known cost of this approach is **drift accumulation** (the same
phenomenon visual-odometry/SLAM chains contend with): each pairwise
alignment carries some small error, and chaining means those errors
compound across the sequence rather than average out, so alignment
quality can degrade the further you get from the group's key. The
mitigation is **groups as manual re-anchor points**: `[[align.group]]`
boundaries reset the chain to a fresh key, so a user who notices drift
(or a genuine subject change, like scaffolding coming down) can restart
alignment from a new reference at that point. Groups aren't required —
no config at all means one implicit group spanning every image, ordered
chronologically, keyed on the first image — because chaining, not the
group boundary, is what makes that viable as a default.

**Transforms are composed, not re-applied to already-warped pixels.**
Each image's transform is computed and stored *relative to the group's
key* (composing each pairwise transform into a single cumulative one),
and that cumulative transform is applied exactly once, directly to the
original decoded source image. The alternative — warp image 2, then align
image 3 against image 2's *resampled* output, warp that, and so on —
would compound resampling blur across the chain in addition to whatever
alignment error accumulates; this design avoids that entirely.

### Failure handling

`cv2.findTransformECC` can fail to converge (raises `cv2.error`) on a bad
pair — a real risk given how much a construction site's appearance
changes over months. On failure for image *i*: log a warning, and reuse
the *previous* image's cumulative transform for image *i*'s own output
too, rather than resetting it to identity — a smooth, slightly-stale
alignment reads far better in a timelapse than a jarring snap back to
unaligned for one frame. Critically, the running anchor does *not*
advance to include image *i*: the next image still compares against the
last known-good aligned frame, not against image *i*'s (unverified)
output. This means one bad pair can't propagate a *garbage* transform
forward — worst case a stale one — and doesn't corrupt the rest of the
chain. Each successful alignment's correlation coefficient (ECC's own
confidence score) is retained per image so weak links are visible after
the fact rather than silently accepted; a `cache.get_or_compute_transform`
hit doesn't have a fresh score to report (only the transform itself is
cached, not the score), so that case reports the score as unknown rather
than a stale or fabricated number.

### Built on `build`'s normalize step, not a separate decoder

`align` calls `ffmpeg_pipeline.normalize_image()` — the same function
`build` uses — as its own first step, rather than reimplementing HEIC
decode/orientation handling. This means:

- All of the hard-won HEIC correctness work (tiled-grid reconstruction,
  EXIF-orientation auto-rotation, the scale/pad-can't-combine-with-tiled-
  decode workaround) is inherited for free.
- `align` gets its own `--max-dimension`, independent of whatever `build`
  eventually uses. Since the normalize cache key includes target
  dimensions, a fast low-resolution pass (tune grouping/key choices,
  inspect results) and a slow full-resolution pass (the real output) are
  cleanly separate cache entries with no interference either direction —
  this is the intended **"thumbnail first, then commit"** workflow.
  Re-running at a *different* resolution recomputes ECC from scratch at
  that resolution (transforms aren't currently shared/scaled between
  resolutions — see below for why that's a reasonable future refinement,
  not a current gap).

ECC's cost scales with pixel count, so working on already-normalized
(scaled-down) images rather than raw multi-megapixel photos is also just
faster on its own merits, independent of the thumbnail-workflow benefit.

### Caching: transforms, not output images

Because chained alignment makes every image's result depend on everything
before it in its group's chain, the cache key can't be just "this one
source file" the way normalize's cache is. What's cached is the small
**cumulative transform matrix** for image *i* (a handful of floats, not
an image), keyed on a hash of the whole prefix: `(warp model, method,
[(path, mtime, size) for every file from the group's key through image
i])`.

This split — cache the expensive part (ECC estimation) separately from
the cheap part (applying the matrix, cropping, writing the file, copying
EXIF) — matters because those two costs are wildly different and can be
invalidated independently: toggling `--crop` on/off, for instance, should
never force ECC to re-run.

The chain-prefix key also means invalidation is automatically correct:
changing an early image in a chain invalidates every cached transform
downstream of it in that chain, which is exactly right, since drift is
chain-dependent — not something to special-case around.

### Cropping (optional, on by default)

After warping, an image has black borders wherever warped content
doesn't cover the original frame — normal for any registration technique.
`--crop`/`--no-crop` (default on) computes the common valid rectangle
across every image in a chain (including the unwarped key) and crops all
of them to that intersection, producing a clean, border-free result at
the cost of a slightly smaller frame than the originals. `--no-crop`
keeps full frames with visible borders — useful for inspecting alignment
quality before committing to a crop, or for users who want to crop
differently themselves downstream.

### Output contract: how the aligned directory feeds back into `build`

`align`'s output directory is designed to be ordinary `build` input with
no special handling required on `build`'s side:

- **Filenames are sequence-numbered** in chain-processing order (e.g.
  `0001_IMG_2993.png`), which alone guarantees `build`'s
  `order = "filename"` sorts correctly — this doesn't depend on any
  metadata surviving the round-trip.
- **EXIF `DateTimeOriginal` is copied from the original source** onto
  each output PNG as a best-effort second layer (`exiftool
  -TagsFromFile`; verified PNG can carry this via the modern `eXIf`
  chunk). If that copy ever fails for some reason, it's a warning, not a
  hard error — the sequence-numbered filename already guarantees correct
  ordering independent of whether EXIF survives. This keeps
  `order = "timestamp"` usable on aligned output too, and preserves real
  capture dates rather than losing them.

### Config shape

Supersedes the earlier reserved sketch in [CONFIG.md](CONFIG.md) (written
before the sequential-chaining design was settled — CONFIG.md reflects
the current version):

```toml
[align]
method = "ecc"
warp = "euclidean"   # "euclidean" (default) | "affine"
crop = true

[[align.group]]
key = "IMG_2993.HEIC"     # starting anchor; chain proceeds chronologically from here
images = ["IMG_2993.HEIC", "IMG_3016.HEIC", "IMG_3024.HEIC"]
```

No `[align]` section at all is valid and means: one implicit group of
every image in the input directory, chronologically ordered, keyed on the
earliest.

### Possible future refinement: seeding full-res ECC from the thumbnail pass

`cv2.findTransformECC` accepts an initial-guess matrix. A thumbnail pass's
result could seed the full-resolution pass's optimization (scaling the
translation component appropriately), which would likely make the
full-resolution pass both faster and more likely to converge correctly,
informed by the thumbnail having already found the right ballpark. Not
implemented initially — each resolution currently computes its own result
independently — but worth revisiting if full-resolution ECC convergence
or speed turns out to be a problem in practice.
