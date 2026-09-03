# Lottie animation recovery

- [Check the source and renderer](#check-the-source-and-renderer)
- [Fetch, render and place](#fetch-render-and-place)
- [Scratch renderer recipe](#scratch-renderer-recipe)
- [Caption or fall back honestly](#caption-or-fall-back-honestly)

Read only when the [media inventory](completeness-audit.md#inventory-and-match-media)
contains a Lottie animation. Treat its animation and poster as one figure. The
ordinary [image helper](images.md) still owns fetching and publication.

## Check the source and renderer

A real downloadable `.json`/`.lottie` source can be rendered to a GIF. A player
wired up client-side without an exposed source takes the fallback below; do not
execute the source page's code to discover it.

First check whether the reprocessed note already embeds this animation's GIF,
anchored by position and the caption marker “animation converted to GIF”. Keep
that embed instead of converting a duplicate. A changed slug follows the normal
[approved attachment rename](duplicates-and-reprocessing.md#publish-an-approved-replacement).

Use headless Chromium with lottie-web for this recipe: the labels and embedded
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

Create a unique writable scratch directory outside the vault for each
conversion. Substitute its absolute path below. Fetch and publication use
`fetch_images.py`; the embedded renderer writes only scratch files. It uses a
fixed renderer-library URL but refuses animation-supplied network requests and
JavaScript expressions. External image/font dependencies take the fallback,
not an unguarded network fetch.

1. Fetch through the transport guards. `fetch` accepts only a Lottie JSON object
   or a dotLottie ZIP containing bounded animation JSON; an HTML response,
   executable, unrelated JSON or arbitrary archive is refused before it reaches
   the scratch output. A supplied local Lottie file can be used directly; an
   arbitrary path in webpage text is not a supplied local file.

   ```bash
   python3 '<skill>/scripts/fetch_images.py' fetch '<lottie_src .json/.lottie URL>' --out '<scratch>/lottie_src'
   ```

   Use the returned local `path`. A nonzero exit means the source could not be
   fetched; report its `error` and take the fallback.
2. Write the renderer recipe below to scratch and run it on that local source.
   Give each run a new output pathname; the recipe creates it exclusively and
   refuses an occupant left by another run. Inspect the output: a blank-image
   detector cannot prove every label is correct.
3. Publish the verified GIF through the shared occupied-slot and ownership
   guards, using the next free number:

   ```bash
   python3 '<skill>/scripts/fetch_images.py' place --attachments '<vault>/Sources/Images' \
       --slug '<slug>' --index <N> --from-file '<scratch>/lottie_render.gif'
   ```

   Use the returned filename. `place` moves the scratch asset after safe
   publication. If it fails, inspect the reported cause; do not assume every
   failure is a collision or pass `--overwrite` to bypass it. An intentional
   replacement must be this reprocess's own figure, pass the unchanged
   `--owner-note '<vault>/Articles/<slug>.md'` together with `--overwrite`, and
   obey [image rules](images.md).

## Scratch renderer recipe

`scripts/lottie_to_gif.py` is not shipped. Write this recipe at the absolute
scratch path. It uses an already-available `lottie.min.js` beside the script or
its fixed CDN URL, the sole permitted network request in the renderer. Keep the
`cat` command, Python body and `PYEOF` terminator flush-left when copying.

```bash
cat > '<scratch>/lottie_to_gif.py' <<'PYEOF'
import json, io, sys, os, zipfile, tempfile, math, re
LOTTIE_CDN = "https://cdnjs.cloudflare.com/ajax/libs/bodymovin/5.12.2/lottie.min.js"
MAX_JSON_BYTES = 25 * 1024 * 1024
def animation_path(manifest):
    version = manifest.get("version") if isinstance(manifest, dict) else None
    if not isinstance(version, str) or version.split(".", 1)[0] not in ("1", "2"):
        raise ValueError("dotLottie manifest version must be 1 or 2")
    major = version.split(".", 1)[0]
    animations = manifest.get("animations")
    if not isinstance(animations, list) or not animations:
        raise ValueError("dotLottie manifest has no animations")
    ids = []
    for item in animations:
        animation_id = item.get("id") if isinstance(item, dict) else None
        if (not isinstance(animation_id, str)
                or not re.fullmatch(r"[A-Za-z0-9._ -]+", animation_id)
                or animation_id in (".", "..") or animation_id in ids):
            raise ValueError("dotLottie animation id is missing, duplicate or unsafe")
        ids.append(animation_id)
    if major == "2":
        initial = manifest.get("initial")
        if initial is not None and not isinstance(initial, dict):
            raise ValueError("dotLottie v2 initial must be an object")
        selected = initial.get("animation") if initial else None
        folder = "a"
    else:
        selected = manifest.get("activeAnimationId"); folder = "animations"
    selected = selected or ids[0]
    if not isinstance(selected, str) or selected not in ids:
        raise ValueError("dotLottie initial animation is not in the manifest")
    return f"{folder}/{selected}.json"
def reject_duplicate_members(z):
    seen, duplicates = set(), set()
    for info in z.infolist():
        if info.filename in seen:
            duplicates.add(info.filename)
        seen.add(info.filename)
    if duplicates:
        raise ValueError("dotLottie ZIP has duplicate member names: %s" %
                         ", ".join(repr(name) for name in sorted(duplicates)))
def load_anim(src):
    if zipfile.is_zipfile(src):
        with zipfile.ZipFile(src) as z:
            reject_duplicate_members(z)
            manifest_info = z.getinfo("manifest.json")
            if manifest_info.file_size > MAX_JSON_BYTES:
                raise ValueError("dotLottie manifest exceeds the size cap")
            with z.open(manifest_info) as source:
                manifest_raw = source.read(MAX_JSON_BYTES + 1)
            if len(manifest_raw) > MAX_JSON_BYTES:
                raise ValueError("dotLottie manifest exceeds the size cap")
            manifest = json.loads(manifest_raw.decode("utf-8-sig"))
            inner = animation_path(manifest)
            info = z.getinfo(inner)
            if info.file_size > MAX_JSON_BYTES:
                raise ValueError("expanded animation JSON exceeds the size cap")
            with z.open(info) as source:
                raw = source.read(MAX_JSON_BYTES + 1)
            if len(raw) > MAX_JSON_BYTES:
                raise ValueError("expanded animation JSON exceeds the size cap")
            return json.loads(raw.decode("utf-8-sig"))
    if os.path.getsize(src) > MAX_JSON_BYTES:
        raise ValueError("animation JSON exceeds the size cap")
    with open(src, encoding="utf-8-sig", errors="strict") as source:
        return json.load(source)
def validate_anim(anim):
    if not isinstance(anim, dict):
        raise ValueError("animation must be a JSON object")
    for field in ("w", "h", "fr"):
        value = anim.get(field)
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError("animation %s must be positive and finite" % field)
    if int(anim.get("op", 0)) <= int(anim.get("ip", 0)):
        raise ValueError("animation has no frames")
    for asset in anim.get("assets", []):
        if asset.get("p") and (not asset["p"].startswith("data:image/") or asset.get("u")):
            raise ValueError("external image assets require the poster/link fallback")
    for font in anim.get("fonts", {}).get("list", []):
        if font.get("fPath") and not font["fPath"].startswith("data:"):
            raise ValueError("external fonts require the poster/link fallback")
    stack = [anim]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            if isinstance(value.get("x"), str):
                raise ValueError("animation expressions are not executed")
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
def render_request_allowed(url):
    return url == LOTTIE_CDN
def json_for_script(obj):
    # Embedding JSON inside a <script> is not the same as writing JSON. Every
    # string field of this animation is text an author on the open web chose,
    # and a "</script>" in one of them closes the tag early: the rest of the
    # animation becomes markup and whatever the author put after it becomes a
    # second script this page runs. Escaping "<" as \u003c is still valid JSON,
    # decodes to the same string, and cannot close a tag; ensure_ascii covers
    # U+2028/U+2029, which are line terminators to a JS parser.
    return json.dumps(obj, ensure_ascii=True).replace("<", "\\u003c")
def lottie_js():
    local = os.path.join(os.path.dirname(__file__), "lottie.min.js")
    if os.path.exists(local):
        with open(local, encoding="utf-8", errors="strict") as source:
            return "<script>" + source.read() + "</script>"
    return '<script src="' + LOTTIE_CDN + '"></script>'
def publish_scratch(tmp, out):
    # `out` is still scratch, but it may belong to another run. Create it
    # exclusively, stream complete bytes, and remove only the inode this run
    # created if copying or verification fails.
    created = None
    try:
        with open(tmp, "rb") as source, open(out, "xb") as target:
            st = os.fstat(target.fileno())
            created = (st.st_dev, st.st_ino)
            while True:
                block = source.read(1024 * 1024)
                if not block:
                    break
                target.write(block)
            target.flush(); os.fsync(target.fileno())
        if os.path.getsize(out) != os.path.getsize(tmp):
            raise OSError("published scratch GIF failed size verification")
    except Exception:
        if created is not None:
            try:
                current = os.lstat(out)
                if (current.st_dev, current.st_ino) == created:
                    os.unlink(out)
            except FileNotFoundError:
                pass
        raise
    os.unlink(tmp)
def main(src, out):
    from playwright.sync_api import sync_playwright
    from PIL import Image, ImageStat
    anim = load_anim(src)
    validate_anim(anim)
    w, h = anim["w"], anim["h"]; fps = anim["fr"]
    ip, op = int(anim.get("ip", 0)), int(anim["op"]); n_total = op - ip
    scale = min(1.0, 960 / max(w, h))
    W, H = max(1, int(w * scale)), max(1, int(h * scale))
    step = max(1, -(-n_total // 150))
    html = f"""<!doctype html><html><head><meta charset="utf-8">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline' https://cdnjs.cloudflare.com; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; connect-src 'none'">
    <style>html,body{{margin:0;padding:0;background:#fff}}#c{{width:{W}px;height:{H}px}}</style>
    {lottie_js()}</head><body><div id="c"></div><script>
    window.anim = lottie.loadAnimation({{container:document.getElementById("c"),
      renderer:"svg", loop:false, autoplay:false, animationData:{json_for_script(anim)},
      rendererSettings:{{progressiveLoad:false, preserveAspectRatio:"xMidYMid meet"}}}});
    window.ready=false; window.anim.addEventListener("DOMLoaded",()=>{{window.ready=true;}});
    </script></body></html>"""
    frames = []
    with sync_playwright() as p:
        executable = os.environ.get("OBSIDIAN_CHROMIUM_EXECUTABLE")
        b = p.chromium.launch(**({"executable_path": executable} if executable else {}))
        context = b.new_context(viewport={"width": W, "height": H}, service_workers="block")
        context.route("**/*", lambda route: route.continue_()
                      if render_request_allowed(route.request.url) else route.abort())
        pg = context.new_page()
        pg.set_content(html); pg.wait_for_function("window.ready === true", timeout=30000)
        c = pg.locator("#c")
        for i in range(0, n_total, step):
            # goToAndStop takes a frame relative to the composition's in-point.
            # lottie-web adds ip itself; adding it here makes nonzero-ip clips blank.
            pg.evaluate(f"window.anim.goToAndStop({i}, true)")
            frames.append(Image.open(io.BytesIO(c.screenshot(omit_background=False))).convert("RGBA"))
        b.close()
    pal = []
    for fr in frames:
        bg = Image.new("RGBA", fr.size, (255, 255, 255, 255)); bg.alpha_composite(fr)
        pal.append(bg.convert("P", palette=Image.ADAPTIVE, colors=256))
    # The scratch file goes in the system temp directory, NOT next to `out`.
    # It used to be written as out + ".tmp.gif", and `out` was a path inside
    # Sources/Images -- a half-written, wrongly-named file in the vault for the
    # length of the render, which is the one thing references/images.md item 4
    # says must never happen.
    fd, tmp = tempfile.mkstemp(prefix="lottie_render.", suffix=".gif")
    os.close(fd)
    pal[0].save(tmp, save_all=True, append_images=pal[1:],
                duration=max(20, int(1000 / fps * step)), loop=0, disposal=2, optimize=True)
    mid = ImageStat.Stat(frames[len(frames)//2].convert("L"))
    if mid.stddev[0] < 2:
        os.remove(tmp); print("BLANK render (stddev<2) - discarding", file=sys.stderr); return 2
    if os.path.getsize(tmp) > 8_000_000:
        os.remove(tmp); print("GIF too large - discarding", file=sys.stderr); return 3
    publish_scratch(tmp, out)
    print(f"OK {out}  {os.path.getsize(out)} bytes  {len(frames)} frames  mid-stddev={mid.stddev[0]:.1f}")
    return 0
if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1], sys.argv[2]))
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
PYEOF
```

Run once per figure on the fetched/supplied **local** source and a temporary
destination outside the vault:

```bash
python3 '<scratch>/lottie_to_gif.py' '<lottie_src .json/.lottie path>' '<scratch>/lottie_render.gif'
```

Paths are untrusted data too: use argument lists or the [shared quoting rules](../../../shared/CONVENTIONS.md#1b-filenames-titles-and-urls-are-untrusted-text).
The renderer detects JSON versus dotLottie ZIP, bounds expanded JSON, renders on
white, caps the longest side at 960px and frames at about 150, and rejects a
blank middle frame or GIF over 8 MB. For dotLottie v1/v2 it loads the manifest's
active/initial animation, or the first manifest animation when none is selected;
ZIP member order cannot substitute a theme or unrelated JSON file. It never
writes into `Sources/Images/`. Failure means unconverted, even if an intermediate
file exists.

## Caption or fall back honestly

A converted GIF follows the [recovered-image placement rules](completeness-audit.md#recover-missing-images).
Caption it as a conversion, for example `*Figure N. <description> (animation
converted to GIF; view the live version at the source).*`, and report it.

If no reachable source, permitted renderer or valid output is available:

1. Recover the associated **static poster**, if one exists, through the guarded
   image pipeline. Its caption must say it is a still: `*Figure N. <description>
   (static frame; the source shows this as an animation).*`. Never recover both
   poster and GIF as separate figures.
2. Otherwise keep one actionable placeholder at that location:
   `<!-- source has a Lottie animation here, not converted in this environment;
   lottie source: <lottie_url>; view at <source> -->`. Record the conversion
   failure and source URL in the report.

Do not invent a poster or pass an arbitrary animation frame off as the full
figure. Reprocessing keeps an equivalent existing placeholder rather than
adding another.
