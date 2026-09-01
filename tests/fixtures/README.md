Fixtures that aren't real photos -- synthetic files generated specifically
to exercise a code path, so there's no licensing question and they can be
regenerated exactly if ever needed.

## tiled.heic

A genuinely tile/grid-encoded HEIC (24 independently-decodable 512x512
HEVC tiles forming a 1600x1200 image), matching how real iPhone photos
are actually structured internally -- not just any HEIC file. This
specific structure is what triggers ffmpeg's "Simple and complex
filtering cannot be used together for the same stream" error when a
scaling `-vf` is combined with the decode in one command (HEIC's tiled
reconstruction uses its own internal complex filtergraph). See
`normalize_image` in `src/staccato/ffmpeg_pipeline.py` for the fix
(scale in a second pass over the already-decoded PNG instead).

Generated with:

```
ffmpeg -f lavfi -i "testsrc2=size=1600x1200:rate=1:duration=1" -frames:v 1 source.png
heif-enc --cut-tiles 512 -q 80 -o tiled.heic source.png
```

`heif-enc` comes from `brew install libheif`.
