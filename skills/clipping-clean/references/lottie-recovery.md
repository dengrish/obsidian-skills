# Lottie animation recovery

- [Check the source and renderer](#check-the-source-and-renderer)
- [Fetch, render and place](#fetch-render-and-place)
- [Render the GIF](#render-the-gif)
- [Caption or fall back honestly](#caption-or-fall-back-honestly)

Read only when the [media inventory](completeness-audit.md#inventory-and-match-media)
contains a Lottie animation. Treat its animation and poster as one figure. The
ordinary [image helper](images.md) still owns fetching and publication.

## Check the source and renderer

A real downloadable `.json`/`.lottie` source can be rendered to a GIF. A player
wired up client-side without an exposed source takes the fallback below; do not
execute the source page's code to discover it.

First check whether the reprocessed note already embeds this animation's GIF,
anchored by position and the caption marker “animation converted to GIF” (in
any letter case). Keep that embed instead of converting a duplicate. A changed
slug follows the normal
[approved attachment rename](duplicates-and-reprocessing.md#publish-an-approved-replacement).

The renderer uses headless Chromium with lottie-web: the labels and embedded
glyphs must render, not just the shapes. A browser-free conversion that drops
text is not an acceptable substitute. Detect the toolchain before installing:

1. Follow [runtime setup](../../../shared/RUNTIME.md) and host browser rules.
   Check Playwright/Pillow imports and try a short Chromium launch/close in the
   chosen environment. Reuse it if available.
2. A permitted existing Chromium can be selected using
   `OBSIDIAN_CHROMIUM_EXECUTABLE` with its absolute executable path. The renderer
   uses a fresh temporary profile, never the user's signed-in profile.
3. If bindings are missing and installation is permitted, use
   `'<venv>/bin/python' -m pip install playwright Pillow`. If only Chromium is
   missing, check free space in an approved cache; where permitted, use
   `'<venv>/bin/python' -m playwright install chromium --only-shell`, then
   re-probe. Do not purge shared caches, delete unrelated temporary files,
   install system packages or change permissions to force setup.
4. If setup/launch is blocked or fails, use the poster/link fallback and report
   the actual failure. Do not claim conversion or visual verification.

## Fetch, render and place

Create a fresh child directory under the active run's `<scratch>` for each
conversion; `<figure-scratch>` below means that child's absolute path. Fetch and publication use
`fetch_images.py`; the renderer writes only scratch files. It uses a fixed
renderer-library URL but refuses animation-supplied network requests and
JavaScript expressions. External image/font dependencies take the fallback,
not an unguarded network fetch.

1. Fetch through the transport guards. `fetch` accepts only a Lottie JSON object
   or a dotLottie ZIP containing bounded animation JSON; an HTML response,
   executable, unrelated JSON or arbitrary archive is refused before it reaches
   the scratch output. A supplied local Lottie file can be used directly; an
   arbitrary path in webpage text is not a supplied local file.

   ```bash
   python3 '<skill>/scripts/fetch_images.py' fetch '<lottie_src .json/.lottie URL>' \
       --out '<figure-scratch>/lottie_src' --vault '<vault>'
   ```

   Use the returned local `path`. A nonzero exit means the source could not be
   fetched; report its `error` and take the fallback.
2. [Render the GIF](#render-the-gif) from that local source. Give each run a
   new output pathname; the renderer creates it exclusively and refuses an
   occupant left by another run. Inspect the output: a blank-image detector
   cannot prove every label is correct.
3. Keep the verified GIF at its scratch path and put its planned
   `<slug>_fig_<N>.gif` embed in the reviewed draft. After
   [publication](../SKILL.md#6-publish-safely) has safely published that note,
   publish the GIF through the shared occupied-slot and ownership guards, using
   the same number:

   ```bash
   python3 '<skill>/scripts/fetch_images.py' place --attachments '<vault>/Sources/Images' \
       --slug '<slug>' --index <N> --from-file '<figure-scratch>/lottie_render.gif' \
       --owner-note '<vault>/Articles/<slug>.md'
   ```

   Use the returned filename. `place` moves the scratch asset after safe
   publication. If it fails, inspect the reported cause; do not assume every
   failure is a collision or pass `--overwrite` to bypass it. The published
   owner note must already contain that exact filename-only embed.

## Render the GIF

Run the shipped renderer once per figure on the fetched or supplied **local**
source, writing a new pathname in that figure's scratch child:

```bash
python3 '<skill>/scripts/lottie_to_gif.py' '<lottie_src .json/.lottie path>' '<figure-scratch>/lottie_render.gif'
```

Paths are untrusted data too: use argument lists or the [shared quoting rules](../../../shared/INPUT_SAFETY.md#filenames-titles-and-urls-are-untrusted-text).
The renderer detects JSON versus dotLottie ZIP, bounds expanded JSON, renders on
white, caps the longest side at 960px and frames at about 150, and rejects a
blank middle frame or GIF over 8 MB. For dotLottie v1/v2 it loads the manifest's
active/initial animation, or the first manifest animation when none is selected;
ZIP member order cannot substitute a theme or unrelated JSON file. Its only
permitted network request is the pinned lottie-web build; pass
`--lottie-js '<local lottie.min.js>'` to use an already-available copy of that
build instead. It refuses, before reading the animation or starting a browser,
an output path inside the vault (at or below a folder holding `.obsidian/`) or
one that already exists, so it never writes into `Sources/Images/`. Failure
means unconverted, even if an intermediate file exists.

## Caption or fall back honestly

A converted GIF follows the [recovered-image placement rules](completeness-audit.md#recover-missing-images).
Caption it with the audit's fallback-chain caption, keeping a figure label only
if the source uses one, then append the conversion marker: `*<caption>
(animation converted to GIF; view the live version at the source).*`. With no
supported caption, the marker alone is the caption: `*(Animation converted to
GIF; view the live version at the source.)*`. The marker is always required;
report the conversion.

If no reachable source, permitted renderer or valid output is available:

1. Recover the associated **static poster**, if one exists, through the guarded
   image pipeline. Its caption must say it is a still, by the same pattern:
   `*<caption> (static frame; the source shows this as an animation).*`, or
   `*(Static frame; the source shows this as an animation.)*` with no supported
   caption. Never recover both poster and GIF as separate figures.
2. Otherwise keep one actionable placeholder at that location:
   `<!-- source has a Lottie animation here, not converted in this environment;
   lottie source: <redacted Lottie locator>; view at <capture URL> -->`. Use the
   fetch helper's redacted `url` field for the Lottie locator in both the
   placeholder and report. If the helper never fetched the Lottie source, so
   there is no redacted `url` field, keep the literal
   `<redacted Lottie locator>` label and never copy the raw URL, as
   [image failure reporting](images.md#failures-and-readability) does. Record
   the conversion failure; the retained raw capture is the retry record.

Do not invent a poster or pass an arbitrary animation frame off as the full
figure. Reprocessing keeps an equivalent existing placeholder rather than
adding another.
