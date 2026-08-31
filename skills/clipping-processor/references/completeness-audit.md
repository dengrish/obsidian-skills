# Completeness audit against the source page (step 12)

**Read this when** you are about to audit a clipping against its live page — i.e. every clipping whose step-2 fetch succeeded and wasn't a paywall stub. Skip it when the fetch failed, the page was paywalled, or the input is a PDF; in those cases the audit is declared `SKIPPED — <reason>` and this file has nothing to add.

- Fetching: static-first, browser on sparse signal
- **1.** Media inventory from the raw HTML (including Lottie sources and responsive variants)
- **2.** Matching against what's already in the note; filtering decoratives
- **3.** Recovering downloadable figures, with the caption fallback chain
- **3b.** Converting Lottie animations to GIF (browser detection, disk gating, the embedded converter)
- **4.** Flagging what can't be recovered
- **5.** Checking for missing text and sections

Web Clipper silently drops content — most often inline SVG diagrams, lazy-loaded images, animations, interactive widgets, and occasionally whole paragraphs or sections (content behind "read more" expanders, or a truncated long article). This step compares the polished note against the live page and **recovers what can be cleanly recovered, flags what can't.** It is explicitly best-effort: a static fetch can't see everything a browser renders, and most animations/interactives can't be captured as files (Lottie animations are the exception — they're JSON and can be converted to GIF when their source is reachable; see sub-part 3b). The goal is to surface gaps for the user, not to guarantee a perfect mirror.

**This step always produces a verdict** — never skip it silently. The audit ran or it didn't, and either outcome must be reported in step 14 as one of these explicit statuses:
- `Completeness audit: <N> recovered, <M> flagged, <K> decoratives skipped` (ran successfully — list each below the verdict line).
- `Completeness audit: no gaps found` (ran, page and clip matched).
- `Completeness audit: SKIPPED — <reason>` (couldn't run; valid reasons are required browser/network access unavailable, fetch failed, paywall stub, 404, source URL unreachable, or the page is so JS-dependent that **even a rendered browser fetch** came back with nothing usable — say which. **A sparse *static* fetch is not one of them**: it is the trigger to upgrade to a rendered fetch, per sub-part 1, and skipping on a thin `curl` drops the audit on exactly the SPA-hosted articles most likely to be missing figures, behind a verdict line that reads as legitimate). A run that produces a polished note **without** any audit verdict in the report is incomplete and should be flagged in the step-13 review.

Skip only when there's no reliable basis for comparison: the step-2 source fetch failed, the page is paywalled, required browser/network access is unavailable, or the page is so JS-dependent that even the available browser (sub-part 1) returns essentially the article-skeleton chrome and no body content. In batch mode the audit runs once per file like every other step; it adds a second fetch per clipping, so it's the heaviest step in the pipeline — that's expected, not a reason to skip it silently.

**Two inputs, two jobs.** This step needs both views of the page, and uses each for what it's good at:
- the **raw HTML** (fetch fresh, e.g. `curl -sL -A "Mozilla/5.0 …" '<source>'` — the browser User-Agent is required, see Conventions; without it Cloudflare-fronted sites return a challenge page instead of the article) — for *media/markup* detection, because figure tags, inline SVG, and lazy-load attributes only exist in the markup; the extracted-text view from step 2 returns extracted text that hides them;
- step 2's already-fetched **extracted text** — for *prose-gap* detection (sub-part 5), because comparing article prose needs the readability-extracted text, not the raw markup with all its nav/ads/boilerplate. Don't re-derive readability extraction by hand from the raw HTML — reuse what step 2 already produced. (If step 2's extracted text is no longer in context by the time you reach this step, re-fetch it with the host's web-fetch tool — not curl — which returns the readability-extracted text directly.)

**Static first, browser-render on sparse signal.** Most editorial pages are server-rendered: a `curl` returns the full markup with all figures present. Some (single-page-app blogs, dashboards, increasingly some news sites) inject the article body and figures client-side, and a `curl` returns a near-empty skeleton with essentially no content. Don't pay the Chromium-launch cost on every fetch; do it only when the static fetch was sparse:

1. Start with `curl -sL -A "Mozilla/5.0 …" '<source>'` (browser UA mandatory — see Conventions) and count signals — `<img>` tags, `<p>` tags, total bytes, and the page's claimed word count if `og:description`/JSON-LD `wordCount` is present. If the response is suspiciously small *and* matches a Cloudflare challenge shape (contains `cf-mitigated`, `Just a moment…`, `__cf_chl`, or similar), treat the static fetch as failed and go straight to the browser upgrade — don't mistake a block page for a sparse article.
2. **Trigger the browser upgrade if any of these hold:** under ~15 `<p>` tags total, or under ~10 KB of body content after stripping `<head>` / `<script>` / `<style>`, or zero `<img>` on a page whose title clearly implies a figure-rich article, or `og:type=article` with `wordCount` > 1000 but the static markup contains fewer paragraphs than that word count implies. These are heuristics; on borderline cases, lean toward upgrading (the cost of one extra Chromium launch is low vs. silently under-counting).
3. **Upgrade with an available browser tool** and inspect the rendered article and media. Follow that tool's permitted inspection surface; do not assume raw HTML extraction is available. If standalone Playwright is available and permitted, `goto(url, wait_until="networkidle", timeout=30000)` and `page.content()` can supply the rendered HTML. When only visible/DOM inspection is available, inventory what it exposes and report any limits. Do this **once** per audit, not per element. Note in the report which path was used (`audit fetched via browser (sparse static fetch)` or `audit fetched via curl`) so a future regression is visible.
4. If even the rendered fetch is sparse (the page is truly hostile to non-interactive access, or hit a paywall stub), declare the audit `SKIPPED — JS-rendered page returned no usable content` per the verdict requirement above and proceed without it.

For most pages (including server-rendered editorial sites like Quanta, traditional news, magazines, and most blogs) the static path is sufficient — verified empirically that Quanta's curl returns the same `<img>`/`<figure>` count as a Playwright render. The upgrade pays off on genuinely SPA-only sites where the static fetch would otherwise silently under-count and the audit would falsely report "no gaps."

**1. Get the page's media inventory (from raw HTML).** Inventory every figure-like and media element, with its caption/alt text and nearest heading (for anchoring):
- `<img>`, including lazy-loaded variants (`data-src`, `data-lazy-src`, `srcset`, `<picture><source>`), of any extension **including `.svg`**;
- inline `<svg>…</svg>` diagrams (these have no URL — they're markup);
- `<video>`/`<source>`, `<canvas>`, and animation/interactive containers (`<iframe>` embeds, animation-library elements). **Lottie animations specifically** are worth capturing the *source URL* for, because unlike other animations they can often be converted to a GIF (see recovery sub-part 3b). Look for `<lottie-player src="…">` / `<dotlottie-player src="…">` web-components, a `<div>` with `data-animation-path` / `data-src` pointing at a `.json` or `.lottie`, or a bare `.json`/`.lottie` URL referenced in nearby markup or inline script. Record that URL alongside the element. If no source URL is exposed in the static HTML (the player is wired up client-side), there's nothing to convert — it'll fall through to a placeholder.
  - **Associate each animation with its static fallback when there is one, and treat them as ONE figure.** Some pages ship the same figure two ways at once: a `<lottie-player>` for the animation *plus* a static `<img>`/`<picture>` poster as a no-JS / small-screen fallback, often in the very same `<figure>`. (Some Quanta pieces do this — a `<lottie-player src="…Topology_X.json">` beside a sibling `<img src="…Mobilev3.svg">`. But many don't: the condensed-mathematics topology piece ships its three `<lottie-player>`s with *no* sibling poster at all. So treat a poster as opportunistic — check for one, don't assume it exists.) When a `<lottie-player>`/animation and a static image *do* sit in the same `<figure>` or container, record them as a single figure carrying both a `lottie_src` and a `fallback_img` — **not** two separate figures; when there's no sibling poster, the figure carries only a `lottie_src`. This matters because the recovery rules below treat a Lottie's poster very differently from a genuinely standalone image.
  - **Collapse responsive variants of one figure.** The same figure also appears in desktop and mobile variants (`Topology_Fig2_Desktopv1.json` + `Fig2_MOBILE.json`; `…Fig5…Desktopv3.svg` + `…Fig5…Mobilev3.svg`), usually inside sibling `hide--xs` / `hide--s` wrappers. These are one figure, not two — count and recover it once, and **prefer the desktop variant** (the vault is read on a computer). Don't emit a desktop *and* a mobile copy of the same diagram.
- `<figure>`/`<figcaption>` groupings.
- If the raw HTML looks sparse relative to what the article clearly contains (a JS-rendered page where figures are injected client-side), say so in the report — a static fetch under-counts, so the audit's "missing" list may itself be incomplete.

**2. Match against what's already in the note — and bias toward "already present."** Line up the page's media inventory with the images already in the note body. **Note the two image shapes you may be matching against:**
- *Fresh run* — step 6 just downloaded the clip's images, and the body still corresponds to URLs you saw this run, so matching page→note by source URL is reliable.
- *Reprocess* — the body's images are already `![[slug_fig_N]]` embeds with **no source URL**, so you can only match by caption/alt text and document position. This matching is fuzzy, so **bias hard toward assuming a page figure is already present**: only treat a page figure as "missing" when you're confident it has no counterpart among the existing embeds (e.g. its caption/alt clearly matches nothing, and the count of page figures exceeds the count of embeds). When in doubt, assume present and do **not** re-download — a duplicated figure is a worse, more confusing outcome than a missed recovery, and the user can re-run if something's genuinely absent. Count the existing `![[…]]` embeds first; if it already equals or exceeds the page's figure count, recover nothing.

What matches is fine; focus only on what's on the page but confidently absent from the note.

**Filter out decorative images before recovering anything.** Magazine-style articles routinely include small "spot illustrations" — section-break decorations, page ornaments, atmospheric graphics that aren't figures the reader is meant to engage with. Quanta is the canonical case: a page commonly carries 2–4 `<img>` tags with filenames like `TearInTopology-Spot01.webp`, `…-Spot02.webp`, `…-Spot03-v2-scaled.webp` placed between body paragraphs purely as visual breathers. These should **not** be recovered as figures — embedding them produces bare captionless interrupts in the prose, exactly the failure mode an early version of this skill hit (multiple captionless `_fig_N.webp` embeds wedged into the article body). They should also **not** be flagged in sub-part 4 as "missed content"; they were never content.

A page image is decorative when **multiple of these signals coincide** (no single one is reliable on its own — the Belan SVG diagrams also have `alt=""`):
- *Empty `alt` attribute* (`alt=""` is the accessibility-conformant marker for "this is decoration, screen readers should skip it"). **Necessary but not sufficient.**
- *Not inside a `<figure>` with a `<figcaption>`* — substantive figures on most editorial pages are wrapped in `<figure>…<figcaption>`; decoratives are loose `<img>` between `<p>` paragraphs.
- *No caption-shaped text adjacent* — the surrounding paragraphs are pure body prose with no "Credit:", "Photo:", "Figure N", or italic attribution line near the image.
- *Filename or class name carries decoration signals* — `Spot\d+`, `Ornament`, `Divider`, `Banner`, `Badge`, `Ad`, `Promo`, `Spacer`, `Hero` (when paired with no caption), or repeating tokens (`Spot01`, `Spot02`, `Spot03` of the same series within one page).
- *Used as an ad/promo/series banner* — alt text like "Ad for…", "An ad for…", classes containing `is-l`/`fit-x fill-h`, or filename containing `MathSeries-Banner`, `MathSeries-Badge`, etc. Recognize these and skip them regardless of position.

**Be conservative — only skip when at least two of these hold together** (e.g. `alt=""` AND filename matches a decoration pattern, or `alt=""` AND no figcaption AND no caption-shaped text in either adjacent paragraph). A real figure that happens to lack alt text shouldn't be dropped; the cost of including a borderline-decorative image (one captionless embed in a body) is small, while the cost of dropping a real diagram is high. When in doubt, recover and let the user delete.

For each skipped decorative, log it briefly in the report (`Decorative skipped: TearInTopology-Spot01.webp (spot illustration)`) so the user can see the audit considered it and made the call — not silently dropped.

**Order of recovery — Lottie before static images.** Process each missing figure as a single unit, and **handle any figure that has a reachable Lottie source via sub-part 3b *first*.** Only figures with no Lottie go through sub-part 3's image recovery. This ordering is the whole point of the association rule in sub-part 1: a Lottie's static `<img>` poster is *not* an independent figure to recover — it's the fallback for an animation that 3b will convert to a GIF. If you recover the poster here, you both lose the animation and (worse) leave the figure looking "done" so 3b never runs. **So: if a figure has a `lottie_src`, skip it in sub-part 3 and let 3b handle it; recover the static image here only when the figure has no Lottie at all.** (When 3b *can't* convert the Lottie — no reachable source, or Chromium unavailable — its own fallback chain recovers that `fallback_img` poster as a clearly-labeled still, so the poster is used there rather than lost; see sub-part 3b.) (This is exactly the bug that made an early version save Quanta's topology diagrams as static `.svg` posters instead of converting the Lotties — the SVG fallback got grabbed first.)

**3. Recover what's cleanly recoverable.** For a missed figure **with no Lottie source** that has a real downloadable URL (`<img src>` / `<source>` — any extension, **including `.svg`**, which is the single most common Web Clipper miss):
- download it through step 6's pipeline (temp path → MIME-detect → move to `Sources/Images/<slug>_fig_<N>.<ext>`, continuing the figure counter from the highest `_fig_N` already in the note). Note the `_fig_N` suffix is only a unique filename token, not a promise of document order — a recovered image inserted between fig_2 and fig_3 still takes the next free number (e.g. fig_9), and that's fine; the displayed "Figure N" lives in the caption, the filename token just has to be unique.
- insert the embed at the right place in the body, anchored by its caption/alt text or the sentence it sat beside on the page; if the location isn't determinable with confidence, place it after the most-related paragraph and flag the placement as approximate;
- **Caption the embed using this fallback chain** (the page often gives diagram-style figures no `<figcaption>` at all, and bare embeds wedged into prose read as broken — but invented captions read as fabrication, so be conservative):
  1. **Page-provided caption** — a sibling `<figcaption>`, or a short caption-shaped element (`<p>`/`<div>`/italic line) immediately under the figure with credit/figure-description shape ("Source:", "Credit:", "Figure N", a `Photographer / Publication` line, or a short descriptive sentence). Use step 6's caption-normalization rules on it.
  2. **Credit synthesized from the image URL** — many editorial outlets bake the photographer/illustrator into the filename: Quanta uses `crMarkBelan_…`, others use `-credit-`, `-by-`, `-photo-`, or `©Name` segments. When the page itself has no caption text but the filename clearly carries a credit (`cr[A-Z][a-zA-Z]+`, `credit[-_][a-zA-Z]+`, etc.), emit a credit-only italic line: `*Mark Belan / Quanta Magazine.*`. Don't fabricate the affiliation if it isn't decodable — just `*Mark Belan.*`.
  3. **Description synthesized from the immediately-preceding paragraph's lead-in** — when neither a page caption nor a filename credit is available, look at the paragraph **immediately before** the figure for a colon-ended lead-in ("…like so:", "…as follows:", "…for instance:", "…as below:", "All these intervals are open sets:", or a sentence describing a construction the figure illustrates). If you find one, write a short italic descriptor that paraphrases what the figure shows in the surrounding context, and **mark it as synthesized**: `*Cantor set construction: line segment with successively removed middle thirds (synthesized from context).*`. Two firm constraints — (a) draw only from the *immediately preceding* paragraph (not later prose, not the article generally), and (b) the synthesized text must paraphrase content the lead-in actually contains; don't invent details the surrounding prose didn't already say. The `(synthesized from context)` marker is mandatory so the user can verify or rewrite.
  4. **Bare embed** — only when none of the above yields a candidate (the figure has no caption, no decodable credit, and no informative lead-in). A bare embed is the right fallback over fabrication.

  In all cases, follow step 6's caption-normalization rules (single italic line, strip inner emphasis, ASCII-fold decorative Unicode, etc.).

**3b. Convert Lottie animations to GIF when the source is reachable.** A Lottie animation is JSON-driven, so unlike a `<canvas>` or `<video>` it *can* be rendered to an animated GIF that Obsidian embeds like any image. Do this only when sub-part 1 found a real, downloadable source URL (`.json` or `.lottie`); if the player was wired up client-side with no exposed source, there's nothing to convert — fall through to the fallback chain at the end of this sub-part (its poster step still applies if the figure has one).
- **Idempotency on reprocess (check first).** On a reprocess the body may already contain the GIF this step produced last run — an `![[slug_fig_N.gif]]` embed whose caption carries the "animation converted to GIF" marker, anchored where this Lottie sits. If so, **don't re-convert** — that would duplicate the figure. Treat the existing GIF embed as already covering this Lottie (rename it like any other embed if the slug changed, per step 6's reprocess branch) and move on. Convert only when no such embed exists yet.
- **Toolchain — render with headless Chromium driving lottie-web** (the canonical Lottie reference renderer). This isn't a preference; it's the only engine that renders Lottie *text layers*. These animations bake their axis labels, numbers, and annotations in as text (Quanta's carry an embedded glyph table plus a "Pangram" font), and every browser-free renderer drops them: `rlottie-python` runs but silently omits all text, and `python-lottie`/`cairosvg` renders the labels blank because its cairo path doesn't use the embedded glyphs. (Note: `python-lottie` ≥ 0.7.2 no longer *crashes* on text layers — an older version raised `'TextDocument' has no attribute 'color'` — but blank labels are just as useless, so the conclusion is unchanged.) A topology number line with no numbers is worse than no figure, so lottie-web it is. The full recipe is **embedded inline below** (written to a temp file at runtime) rather than shipped as a sidecar file, to keep the optional rendering recipe alongside its usage. Whole-plugin installs carry the scripts and references on both hosts.
  - **Get a working browser — detect first, install only what is missing.** Follow `shared/RUNTIME.md` and the host's browser/tool rules. Check whether the chosen Python already imports Playwright and Pillow, then try a short Chromium launch and close. If it works, reuse it.
    1. If the bindings are missing and installation is permitted, install them in the selected virtual environment:
       ```bash
       '<venv>/bin/python' -m pip install playwright Pillow
       ```
    2. If only the browser is missing, check free space in an approved writable cache. Where the host permits a separate browser installation, use `'<venv>/bin/python' -m playwright install chromium --only-shell`, then re-probe. Do not delete unrelated temporary files, purge shared caches, install system packages, or change permission settings to make setup succeed.
    3. If setup is blocked or the launch still fails, use the poster/link fallback below. Report the actual failure (missing bindings, blocked download, unavailable browser, disk space, or missing system library). Do not claim an animation was converted or visually verified.

- **Convert in three stages, and only the middle one is the heredoc below.** Create a unique writable temporary directory for this conversion (`mktemp -d` or Python's `tempfile.mkdtemp()`); substitute its absolute path for `<scratch>` in every command below. Do not reuse scratch files across Codex and Claude sessions. The download and the final write into the vault both go through `scripts/fetch_images.py`; the heredoc renders, and touches neither the network nor `Sources/Images/`. That split is not tidiness. The converter used to do all three itself, and the two it should not have been doing came with none of step 6's guards: it fetched the Lottie URL — text lifted straight out of the page being clipped — with a bare `urlopen`, so no scheme allowlist (`file:` and `ftp:` both work there), no refusal of a host resolving to loopback or `169.254.169.254`, no re-check at a redirect hop, no size cap and no wall-clock cap; and it wrote its output with `os.replace()` straight into `Sources/Images/`, so no slug validation, no path containment, and no refusal of an occupied slot — a pre-seeded GIF from a previous run was overwritten and the script exited 0. `Sources/Images/` is flat and shared with `pdf-figure-extractor` and `paper-summarizer` (`CONVENTIONS.md` §8), so the file it replaced was not necessarily this note's.
  1. **Fetch the source** with `fetch_images.py fetch`, which applies exactly the transport guards step 6's downloads get, and writes to a temp path **outside** the vault (a Lottie is JSON, not an image, so `download` will not carry it — that is what `fetch` is for):
     ```bash
     python3 '<skill>/scripts/fetch_images.py' fetch '<lottie_src .json/.lottie URL>' --out '<scratch>/lottie_src'
     ```
     It prints JSON with the `path` it wrote and, on failure, an `error` — treat a non-zero exit as an unreachable source and fall through to the fallback chain. A Lottie that came from a **local** file needs no fetch; pass its path to the renderer directly.
  2. **Render** it to a GIF at a temp path, with the heredoc converter below (the next bullet).
  3. **Place the GIF** with `fetch_images.py place`, which is step 6's write path: it validates the slug, checks the destination is really inside `Sources/Images/`, **refuses an occupied `<slug>_fig_<N>.*` slot** rather than overwriting it, and picks the extension from the file's own bytes — so a blank or failed render named `.gif` is refused instead of embedded:
     ```bash
     python3 '<skill>/scripts/fetch_images.py' place --attachments '<vault>/Sources/Images' \
         --slug '<image_slug>' --index <N> --from-file '<scratch>/lottie_render.gif'
     ```
     The rendered file is **moved**, not copied. Use the shared figure counter for `<N>` (the next free `_fig_N` in the note). If `place` reports `ok: false`, the slot belongs to something else — settle that the way step 3 settles a stem collision; do not pass `--overwrite` to get past it unless this is a reprocess of your own figure.
- **The renderer is embedded here on purpose, not shipped as a sidecar file.** Earlier versions kept the Python in `scripts/lottie_to_gif.py` next to this SKILL.md; that failed in practice because the install of this skill does **not** reliably carry the `scripts/` folder along with `SKILL.md`, and a bare relative path like `scripts/lottie_to_gif.py` wouldn't resolve from the working directory anyway — so the skill reported the script "absent" and every Lottie fell through to a placeholder. To make this self-sufficient, **write the converter to a temp file at runtime from the source below, then run it.** No installed sidecar, no path assumptions. It needs `lottie-web` (bodymovin); rather than vendoring 300 KB of JS inline, the script fetches it from cdnjs at convert time — that is the browser's own fetch of a fixed CDN URL this file chose, not a fetch of anything the clipped page supplied. Write it once per run with the command block below. **The `cat` command and its heredoc are intentionally flush-left (column 0), not indented into this list** — a `<<'PYEOF'` terminator must start at column 0 or the shell never matches it and silently swallows the rest of the file, and the Python body must be unindented to parse. Run it exactly as written. (Authoring note for anyone editing this skill: **every code block here that is meant to be extracted and run — this heredoc, the sibling-indent detector and the structural-skeleton extractor in step 13 — must be fenced at column 0, never nested inside a list item.** A block indented for visual nesting comes out with leading whitespace on every line and dies on `IndentationError`/an unmatched heredoc terminator the moment it's run. This bit three separate scripts during development; keep runnable blocks flush-left.)

```bash
cat > '<scratch>/lottie_to_gif.py' <<'PYEOF'
import json, io, sys, os, shutil, zipfile, tempfile
def load_anim(src):
    if zipfile.is_zipfile(src):
        with zipfile.ZipFile(src) as z:
            inner = next(n for n in z.namelist()
                         if n.endswith(".json") and n != "manifest.json")
            return json.loads(z.read(inner).decode("utf-8"))
    return json.load(open(src, encoding="utf-8"))
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
        return "<script>" + open(local).read() + "</script>"
    return ('<script src="https://cdnjs.cloudflare.com/ajax/libs/'
            'bodymovin/5.12.2/lottie.min.js"></script>')
def main(src, out):
    from playwright.sync_api import sync_playwright
    from PIL import Image, ImageStat
    anim = load_anim(src)
    w, h = anim["w"], anim["h"]; fps = anim["fr"]
    ip, op = int(anim.get("ip", 0)), int(anim["op"]); n_total = op - ip
    scale = min(1.0, 960 / max(w, h))
    W, H = max(1, int(w * scale)), max(1, int(h * scale))
    step = max(1, -(-n_total // 150))
    html = f"""<!doctype html><html><head><meta charset="utf-8">
    <style>html,body{{margin:0;padding:0;background:#fff}}#c{{width:{W}px;height:{H}px}}</style>
    {lottie_js()}</head><body><div id="c"></div><script>
    window.anim = lottie.loadAnimation({{container:document.getElementById("c"),
      renderer:"svg", loop:false, autoplay:false, animationData:{json_for_script(anim)},
      rendererSettings:{{progressiveLoad:false, preserveAspectRatio:"xMidYMid meet"}}}});
    window.ready=false; window.anim.addEventListener("DOMLoaded",()=>{{window.ready=true;}});
    </script></body></html>"""
    frames = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(viewport={"width": W, "height": H}).new_page()
        pg.set_content(html); pg.wait_for_function("window.ready === true", timeout=30000)
        c = pg.locator("#c")
        for i in range(0, n_total, step):
            pg.evaluate(f"window.anim.goToAndStop({i + ip}, true)")
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
    shutil.move(tmp, out)
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
  Then one call per figure, passing the **local** Lottie source (stage 1's `--out` path, or a path the page shipped) and a **temp** destination outside the vault:
  ```bash
  python3 '<scratch>/lottie_to_gif.py' '<lottie_src .json/.lottie path>' '<scratch>/lottie_render.gif'
  ```

  **Single quotes on the source.** It is a path derived from a URL lifted out of the page being clipped, so it is text an author on the open web chose; inside `"…"` a `$(…)` in it is a command the shell runs before Python starts (`CONVENTIONS.md` §1b).
  It content-detects raw `.json` vs. dotLottie zip, renders on white via lottie-web, caps the longest side at 960px and frames at ~150 (output ~120–230 KB), writes to a scratch file in the system temp directory, and only moves the GIF to the destination after verifying it's a valid, non-blank GIF (middle-frame grayscale stddev ≥ 2 — the check that catches a text-dropping engine) of sane size. On any failure or blank render it exits non-zero and writes nothing. **It does not fetch, and it does not write into `Sources/Images/`** — stage 1 and stage 3 above own those, and they are the only two steps in this sub-part that are allowed to touch the network or the vault. If the script exits non-zero, treat the Lottie as unconverted and fall through to the fallback chain.
- **Embed and caption** a converted GIF like a recovered image (sub-part 3's placement rules), noting in the caption that it's a converted animation, e.g. `*Figure N. <description> (animation converted to GIF; view the live version at the source).*` Record the conversion in the report.
- **Fallback chain when conversion can't run** (no reachable source, Chromium unavailable, or the script failed) — degrade in order rather than jumping straight to a bare placeholder:
  1. **Static fallback poster, if the figure has one.** Sub-part 1 may have associated a `fallback_img` with this Lottie (a sibling `<img>` / `.svg` / `.webp` the page ships for no-JS). Recover *that* through sub-part 3's image pipeline and caption it honestly as a still: `*Figure N. <description> (static frame; the source shows this as an animation).*`. The publisher's own static diagram beats a comment. The one firm rule: the caption must say it's a still — never present the poster as if it were the animation. (Many pages — including the Quanta condensed-mathematics piece — ship *no* poster for their Lotties; then there's nothing to recover here and you go straight to step 2.)
  2. **Otherwise, a flagged placeholder that records the source URL**, so it's actionable — a rerun in a Chromium-capable environment, or the user, can convert it later: `<!-- source has a Lottie animation here, not converted in this environment; lottie source: <lottie_url>; view at <source> -->`. List it in the report with the reason conversion didn't run.

**4. Flag what can't be cleanly recovered** — don't guess, don't fabricate. **Idempotency on reprocess:** a previous audit's placeholder comments survive in the body (step 1 strips only the Summary callout, not the body). Before adding a placeholder for an uncapturable element, check whether an equivalent `<!-- source has … -->` comment is already sitting at that location — if so, leave the existing one and don't add a second. Likewise, a reprocess should not strip a still-valid placeholder from a prior run. The goal is that reprocessing the same file repeatedly converges — placeholders neither duplicate nor disappear.
- *Inline `<svg>` diagrams.* You may best-effort serialize a **self-contained** `<svg>` to `Sources/Images/<slug>_fig_<N>.svg` and embed it — but only if it's genuinely standalone. If it depends on external CSS/fonts/JS or `<use href="#…">` external defs (so it won't render on its own), **don't save a broken file.** Leave a flagged placeholder at the location (`<!-- source has an inline SVG diagram here, not capturable as a static file; view at <source> -->`) and list it in the report. (Note: an `<svg>` or `.svg` that is a *Lottie's static fallback* is not handled here at all — sub-part 1 associated it with its animation and sub-part 3b converts the Lottie to GIF instead. This bullet is only for SVG diagrams that have no Lottie behind them.)
- *Animations, video, `<canvas>`, interactive widgets.* These can't be captured as a faithful static asset. Leave a flagged placeholder at the location (`<!-- source has an animation/interactive figure here, not captured; view at <source> -->`) with a one-line description, and list it in the report. Never grab a poster frame or one animation still and pass it off as the figure. (Lotties are handled entirely by sub-part 3b — convert, else the static poster captioned as a still, else an actionable source-URL placeholder — so don't emit a second placeholder for them here.)

**5. Check for missing text/sections.** Using step 2's **extracted text** (not the raw HTML), compare the page's main article text against the note's body. Flag substantial gaps: a heading or section present on the page but absent from the note, or a run of body paragraphs the clip dropped (truncation, "read more" expanders, content the clipper skipped). **Don't auto-insert large blocks of missing prose** — the clip is the user's curated capture, and extracted page text can differ from what they deliberately kept. Instead report what's missing and where, with enough detail (the missing heading; the first several words of the dropped passage) that the user can re-clip or paste it in. Ignore expected differences: the nav/ads/share chrome the clip correctly removed, minor whitespace/wording artifacts from extraction, and any content the user already chose to drop on a prior run (don't keep re-flagging the same intentional omission every reprocess — a gap that was flagged before and is still absent is the user's settled choice, so mention it at most briefly).

If the body changed here (recovered images inserted, placeholders added), re-save the file and re-check the affected regions against the step-13 checklist. Everything recovered or flagged goes in the report (step 14).
