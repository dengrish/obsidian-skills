#!/usr/bin/env python3
"""Render a local Lottie animation (JSON or dotLottie) to a scratch GIF.

    python3 '<skill>/scripts/lottie_to_gif.py' '<lottie source>' '<figure-scratch>/lottie_render.gif'
    python3 '<skill>/scripts/lottie_to_gif.py' --test

SOURCE is a local file: the `path` that `fetch_images.py fetch` returned, or a
Lottie file the user supplied. OUT is a new scratch pathname outside the vault.
An OUT at or below a folder holding `.obsidian/`, or one that already exists,
is refused before the animation is read or a browser starts; the final copy
creates OUT exclusively, so an occupant that appears during the render is
refused too. The GIF is published into the vault later, by
`fetch_images.py place`.

The renderer detects JSON versus a dotLottie ZIP, bounds every JSON read at
25 MB, and for dotLottie v1/v2 loads the manifest's active/initial animation
(or its first animation), never a ZIP member chosen by order. It refuses
animation expressions and external image or font assets, which take the
poster/link fallback. It renders with lottie-web in headless Chromium on
white, caps the longest side at 960 px and the frames at about 150, and
discards a blank middle frame or a GIF over 8 MB.

Chromium gets a fresh temporary profile and may fetch only the pinned
lottie-web build from cdnjs; every other request, including any the animation
makes, is aborted. `--lottie-js` passes an already-available local copy of
that build instead. `OBSIDIAN_CHROMIUM_EXECUTABLE` selects a permitted
existing Chromium by absolute path.

Exit 0 with an `OK` line; 1 on any failure; 2 for a blank render; 3 for a GIF
over 8 MB. Nothing is left at OUT unless the exit is 0. Playwright and Pillow
are imported only for a render, so `--test` needs neither.
"""

import argparse
import io
import json
import math
import os
import re
import sys
import tempfile
import warnings
import zipfile


LOTTIE_CDN = "https://cdnjs.cloudflare.com/ajax/libs/bodymovin/5.12.2/lottie.min.js"
MAX_JSON_BYTES = 25 * 1024 * 1024
MAX_GIF_BYTES = 8_000_000
MAX_SIDE = 960
MAX_FRAMES = 150
CSP = ("default-src 'none'; script-src 'unsafe-inline' "
       "https://cdnjs.cloudflare.com; style-src 'unsafe-inline'; "
       "img-src data: blob:; font-src data:; connect-src 'none'")
ANIMATION_ID_RE = re.compile(r"[A-Za-z0-9._ -]+")


def animation_path(manifest):
    """The ZIP member of a dotLottie manifest's selected animation."""
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
                or not ANIMATION_ID_RE.fullmatch(animation_id)
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
        selected = manifest.get("activeAnimationId")
        folder = "animations"
    selected = selected or ids[0]
    if not isinstance(selected, str) or selected not in ids:
        raise ValueError("dotLottie initial animation is not in the manifest")
    return "%s/%s.json" % (folder, selected)


def reject_duplicate_members(z):
    """Refuse a ZIP whose member names repeat (which one is read is ambiguous)."""
    seen, duplicates = set(), set()
    for info in z.infolist():
        if info.filename in seen:
            duplicates.add(info.filename)
        seen.add(info.filename)
    if duplicates:
        raise ValueError("dotLottie ZIP has duplicate member names: %s" %
                         ", ".join(repr(name) for name in sorted(duplicates)))


def _read_member(z, name, what, cap):
    try:
        info = z.getinfo(name)
    except KeyError:
        raise ValueError("dotLottie ZIP has no %s (%s)" % (what, name)) from None
    if info.file_size > cap:
        raise ValueError("%s exceeds the size cap" % what)
    with z.open(info) as source:
        raw = source.read(cap + 1)
    if len(raw) > cap:
        raise ValueError("%s exceeds the size cap" % what)
    return json.loads(raw.decode("utf-8-sig"))


def load_anim(src, cap=MAX_JSON_BYTES):
    """The animation JSON object from a Lottie JSON file or a dotLottie ZIP."""
    if zipfile.is_zipfile(src):
        with zipfile.ZipFile(src) as z:
            reject_duplicate_members(z)
            manifest = _read_member(z, "manifest.json", "dotLottie manifest", cap)
            return _read_member(z, animation_path(manifest),
                                "expanded animation JSON", cap)
    if os.path.getsize(src) > cap:
        raise ValueError("animation JSON exceeds the size cap")
    with open(src, "rb") as source:
        raw = source.read(cap + 1)
    if len(raw) > cap:
        raise ValueError("animation JSON exceeds the size cap")
    return json.loads(raw.decode("utf-8-sig"))


def validate_anim(anim):
    """Refuse what the renderer must not run or fetch."""
    if not isinstance(anim, dict):
        raise ValueError("animation must be a JSON object")
    for field in ("w", "h", "fr"):
        value = anim.get(field)
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value <= 0):
            raise ValueError("animation %s must be positive and finite" % field)
    for field in ("ip", "op"):
        value = anim.get(field, 0)
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value)):
            raise ValueError("animation %s must be a finite number" % field)
    if int(anim.get("op", 0)) <= int(anim.get("ip", 0)):
        raise ValueError("animation has no frames")
    for asset in anim.get("assets") or []:
        path = asset.get("p") if isinstance(asset, dict) else None
        if path and (not isinstance(path, str)
                     or not path.startswith("data:image/") or asset.get("u")):
            raise ValueError("external image assets require the poster/link fallback")
    fonts = anim.get("fonts") if isinstance(anim.get("fonts"), dict) else {}
    for font in fonts.get("list") or []:
        path = font.get("fPath") if isinstance(font, dict) else None
        if path and (not isinstance(path, str) or not path.startswith("data:")):
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


def render_plan(anim):
    """``(width, height, frame step, frame count, GIF frame duration ms)``."""
    w, h, fps = anim["w"], anim["h"], anim["fr"]
    n_total = int(anim["op"]) - int(anim.get("ip", 0))
    scale = min(1.0, MAX_SIDE / max(w, h))
    width, height = max(1, int(w * scale)), max(1, int(h * scale))
    step = max(1, -(-n_total // MAX_FRAMES))
    return width, height, step, n_total, max(20, int(1000 / fps * step))


def render_request_allowed(url):
    return url == LOTTIE_CDN


def json_for_script(obj):
    """JSON that is safe inside a <script> element.

    Every string field of the animation is text an author on the open web
    chose, and a "</script>" in one of them would close the tag early and run
    whatever follows as a second script. Escaping "<" as \\u003c is still
    valid JSON, decodes to the same string, and cannot close a tag;
    ensure_ascii covers U+2028/U+2029, which are line terminators to a JS
    parser.
    """
    return json.dumps(obj, ensure_ascii=True).replace("<", "\\u003c")


def lottie_script(local_js=None):
    """The lottie-web script tag: an inlined local copy, or the pinned CDN."""
    if local_js:
        with open(local_js, encoding="utf-8", errors="strict") as source:
            code = source.read()
        # `</script` can only occur inside a JS string or regex literal, where
        # `<\/` means the same thing and cannot close the element early.
        return "<script>" + re.sub(r"</(script)", r"<\\/\1", code,
                                   flags=re.I) + "</script>"
    return '<script src="' + LOTTIE_CDN + '"></script>'


def page_html(anim, width, height, script_tag):
    return """<!doctype html><html><head><meta charset="utf-8">
    <meta http-equiv="Content-Security-Policy" content="%s">
    <style>html,body{margin:0;padding:0;background:#fff}#c{width:%dpx;height:%dpx}</style>
    %s</head><body><div id="c"></div><script>
    window.anim = lottie.loadAnimation({container:document.getElementById("c"),
      renderer:"svg", loop:false, autoplay:false, animationData:%s,
      rendererSettings:{progressiveLoad:false, preserveAspectRatio:"xMidYMid meet"}});
    window.ready=false; window.anim.addEventListener("DOMLoaded",()=>{window.ready=true;});
    </script></body></html>""" % (CSP, width, height, script_tag,
                                  json_for_script(anim))


class OutputRefused(ValueError):
    """An OUT this renderer will not write: inside a vault, or occupied."""


def inside_vault(path):
    """Is ``path`` at or below a directory holding `.obsidian/`?"""
    d = os.path.dirname(os.path.realpath(path))
    while True:
        if os.path.isdir(os.path.join(d, ".obsidian")):
            return True
        parent = os.path.dirname(d)
        if parent == d:
            return False
        d = parent


def check_output(out):
    """Refuse an OUT inside an Obsidian vault or already occupied."""
    if inside_vault(out):
        raise OutputRefused("%s is inside an Obsidian vault; render to a scratch "
                            "path and publish with fetch_images.py place" % out)
    if os.path.lexists(out):
        raise OutputRefused("%s already exists; choose a new scratch path" % out)


def publish_scratch(tmp, out):
    """Copy ``tmp`` to a new ``out`` exclusively, then remove ``tmp``.

    ``out`` is still scratch, but it may belong to another run: it is created
    exclusively, streamed completely, and only the inode this run created is
    removed if copying or verification fails.
    """
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
            target.flush()
            os.fsync(target.fileno())
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


def render(src, out, local_js=None):
    """Render ``src`` to the new scratch GIF ``out``; returns the exit code."""
    check_output(out)
    from playwright.sync_api import sync_playwright
    from PIL import Image, ImageStat
    anim = load_anim(src)
    validate_anim(anim)
    width, height, step, n_total, duration = render_plan(anim)
    html = page_html(anim, width, height, lottie_script(local_js))
    frames = []
    with sync_playwright() as p:
        executable = os.environ.get("OBSIDIAN_CHROMIUM_EXECUTABLE")
        browser = p.chromium.launch(
            **({"executable_path": executable} if executable else {}))
        try:
            context = browser.new_context(
                viewport={"width": width, "height": height},
                service_workers="block")
            context.route("**/*", lambda route: route.continue_()
                          if render_request_allowed(route.request.url)
                          else route.abort())
            page = context.new_page()
            page.set_content(html)
            page.wait_for_function("window.ready === true", timeout=30000)
            canvas = page.locator("#c")
            for i in range(0, n_total, step):
                # goToAndStop takes a frame relative to the composition's
                # in-point; lottie-web adds ip itself, and adding it here
                # makes nonzero-ip clips blank.
                page.evaluate("window.anim.goToAndStop(%d, true)" % i)
                frames.append(Image.open(io.BytesIO(
                    canvas.screenshot(omit_background=False))).convert("RGBA"))
        finally:
            browser.close()
    palette = []
    for frame in frames:
        background = Image.new("RGBA", frame.size, (255, 255, 255, 255))
        background.alpha_composite(frame)
        palette.append(background.convert("P", palette=Image.ADAPTIVE, colors=256))
    fd, tmp = tempfile.mkstemp(prefix="lottie_render.", suffix=".gif")
    os.close(fd)
    try:
        palette[0].save(tmp, save_all=True, append_images=palette[1:],
                        duration=duration, loop=0, disposal=2, optimize=True)
        middle = ImageStat.Stat(frames[len(frames) // 2].convert("L"))
        if middle.stddev[0] < 2:
            print("BLANK render (stddev<2) - discarding", file=sys.stderr)
            return 2
        if os.path.getsize(tmp) > MAX_GIF_BYTES:
            print("GIF too large - discarding", file=sys.stderr)
            return 3
        publish_scratch(tmp, out)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    print("OK %s  %d bytes  %d frames  mid-stddev=%.1f"
          % (out, os.path.getsize(out), len(frames), middle.stddev[0]))
    return 0


# --- self-test ----------------------------------------------------------------

def run_self_test():
    cases = []

    def check(label, got, want):
        cases.append((label, got == want, got, want))

    def refused(fn, *args, **kwargs):
        try:
            fn(*args, **kwargs)
        except ValueError as exc:
            return str(exc)
        return None

    anim = {"w": 400, "h": 300, "fr": 30, "ip": 0, "op": 60, "layers": []}

    check("v1 manifest selects its active animation",
          animation_path({"version": "1.0", "activeAnimationId": "b",
                          "animations": [{"id": "a"}, {"id": "b"}]}),
          "animations/b.json")
    check("v1 manifest without a selection takes the first animation",
          animation_path({"version": "1", "animations": [{"id": "a"}]}),
          "animations/a.json")
    check("v2 manifest selects its initial animation",
          animation_path({"version": "2.0", "initial": {"animation": "b"},
                          "animations": [{"id": "a"}, {"id": "b"}]}),
          "a/b.json")
    for label, manifest in (
            ("an unknown version", {"version": "3", "animations": [{"id": "a"}]}),
            ("no animations", {"version": "1", "animations": []}),
            ("a path-like id", {"version": "1", "animations": [{"id": "../x"}]}),
            ("a duplicate id", {"version": "1",
                                "animations": [{"id": "a"}, {"id": "a"}]}),
            ("a selection outside the list",
             {"version": "1", "activeAnimationId": "z",
              "animations": [{"id": "a"}]}),
            ("a non-object v2 initial",
             {"version": "2", "initial": "a", "animations": [{"id": "a"}]})):
        check("manifest with %s is refused" % label,
              refused(animation_path, manifest) is not None, True)

    check("a plain animation validates", refused(validate_anim, anim), None)
    for label, bad in (
            ("a non-object", []),
            ("zero width", dict(anim, w=0)),
            ("an infinite frame rate", dict(anim, fr=float("inf"))),
            ("a boolean height", dict(anim, h=True)),
            ("no frames", dict(anim, op=0)),
            ("an external image asset",
             dict(anim, assets=[{"p": "img.png", "u": "images/"}])),
            ("a data image with a base URL",
             dict(anim, assets=[{"p": "data:image/png;base64,AA", "u": "x/"}])),
            ("an external font",
             dict(anim, fonts={"list": [{"fPath": "https://x.test/f.woff"}]})),
            ("an expression",
             dict(anim, layers=[{"ks": {"o": {"x": "time * 2"}}}]))):
        check("animation with %s is refused" % label,
              refused(validate_anim, bad) is not None, True)
    check("inline data assets and fonts are allowed",
          refused(validate_anim, dict(
              anim, assets=[{"p": "data:image/png;base64,AA", "u": ""}],
              fonts={"list": [{"fPath": "data:font/woff;base64,AA"}]})), None)

    check("render plan caps the longest side and frame count",
          render_plan(dict(anim, w=1920, h=1080, op=600)),
          (960, 540, 4, 600, 133))
    check("render plan keeps a small animation's size and every frame",
          render_plan(anim), (400, 300, 1, 60, 33))
    check("render plan counts frames from a nonzero in-point",
          render_plan(dict(anim, ip=10, op=40))[3], 30)

    hostile = {"nm": "</script><script>alert(1)</script> "}
    encoded = json_for_script(hostile)
    check("script-embedded JSON cannot close its tag or break a JS line",
          ("<" in encoded, " " in encoded, json.loads(encoded) == hostile),
          (False, False, True))
    html = page_html(dict(anim, nm="</script>"), 400, 300, lottie_script())
    check("the page pins its CSP and loads only the pinned CDN build",
          (CSP in html, html.count("</script>"), LOTTIE_CDN in html),
          (True, 2, True))
    check("only the pinned lottie-web URL may load",
          (render_request_allowed(LOTTIE_CDN),
           render_request_allowed(LOTTIE_CDN + "?x"),
           render_request_allowed("https://evil.test/lottie.min.js")),
          (True, False, False))

    with tempfile.TemporaryDirectory() as tmp:
        def path(name):
            return os.path.join(tmp, name)

        with open(path("a.json"), "w", encoding="utf-8") as fh:
            json.dump(anim, fh)
        check("a Lottie JSON file loads", load_anim(path("a.json")), anim)
        check("a JSON file over the cap is refused",
              refused(load_anim, path("a.json"), cap=10) is not None, True)
        with open(path("bad.json"), "wb") as fh:
            fh.write(b"\xff\xfe not utf-8")
        check("undecodable JSON is refused",
              isinstance(_raises(load_anim, path("bad.json")), ValueError), True)

        def dotlottie(name, members):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                with zipfile.ZipFile(path(name), "w") as z:
                    for member, data in members:
                        z.writestr(member, data)
            return path(name)

        other = dict(anim, nm="other")
        v1 = dotlottie("v1.lottie", [
            ("manifest.json", json.dumps({"version": "1", "activeAnimationId": "b",
                                          "animations": [{"id": "a"}, {"id": "b"}]})),
            ("animations/a.json", json.dumps(other)),
            ("animations/b.json", json.dumps(anim))])
        check("a dotLottie v1 loads its selected animation, not the first member",
              load_anim(v1), anim)
        v2 = dotlottie("v2.lottie", [
            ("manifest.json", json.dumps({"version": "2", "animations": [{"id": "x"}]})),
            ("a/x.json", json.dumps(anim))])
        check("a dotLottie v2 loads its animation", load_anim(v2), anim)
        dup = dotlottie("dup.lottie", [
            ("manifest.json", json.dumps({"version": "1", "animations": [{"id": "a"}]})),
            ("animations/a.json", json.dumps(anim)),
            ("animations/a.json", json.dumps(other))])
        check("a ZIP with duplicate member names is refused",
              "duplicate member" in (refused(load_anim, dup) or ""), True)
        bare = dotlottie("bare.lottie", [("animations/a.json", json.dumps(anim))])
        check("a ZIP without a manifest is refused as dotLottie input",
              "no dotLottie manifest" in (refused(load_anim, bare) or ""), True)
        check("an animation member over the cap is refused",
              "exceeds the size cap" in (refused(load_anim, v2, cap=60) or ""),
              True)

        with open(path("page.js"), "w", encoding="utf-8") as fh:
            fh.write("var lottie = {};")
        check("a local lottie-web copy is inlined",
              lottie_script(path("page.js")), "<script>var lottie = {};</script>")
        with open(path("evil.js"), "w", encoding="utf-8") as fh:
            fh.write("x = '</SCRIPT><script>alert(1)';")
        check("a local copy cannot close its script element early",
              lottie_script(path("evil.js")),
              "<script>x = '<\\/SCRIPT><script>alert(1)';</script>")

        with open(path("render.gif"), "wb") as fh:
            fh.write(b"GIF89a" + b"\0" * 100)
        with open(path("taken.gif"), "wb") as fh:
            fh.write(b"someone else's")
        outcome = _raises(publish_scratch, path("render.gif"), path("taken.gif"))
        with open(path("taken.gif"), "rb") as fh:
            kept = fh.read()
        check("an occupied output is refused and left unchanged",
              (isinstance(outcome, FileExistsError), kept,
               os.path.exists(path("render.gif"))),
              (True, b"someone else's", True))
        publish_scratch(path("render.gif"), path("out.gif"))
        check("a free output receives the complete GIF and the temp is removed",
              (os.path.getsize(path("out.gif")), os.path.exists(path("render.gif"))),
              (106, False))

        # The refusals come first: a missing SOURCE would otherwise fail
        # with an OSError, and a missing Playwright with an ImportError.
        missing = path("no-such.json")
        outcome = _raises(render, missing, path("taken.gif"))
        check("an occupied OUT is refused before any source read or render",
              (type(outcome).__name__, "already exists" in str(outcome)),
              ("OutputRefused", True))
        vault = path("vault")
        os.makedirs(os.path.join(vault, ".obsidian"))
        os.makedirs(os.path.join(vault, "Sources", "Images"))
        for label, out in (
                ("a vault attachment folder",
                 os.path.join(vault, "Sources", "Images", "x.gif")),
                ("the vault root", os.path.join(vault, "x.gif"))):
            outcome = _raises(render, missing, out)
            check("an OUT in %s is refused before any render, writing nothing"
                  % label, (type(outcome).__name__, os.path.lexists(out)),
                  ("OutputRefused", False))
        check("a free scratch OUT outside any vault passes the preflight",
              refused(check_output, path("fresh.gif")), None)

    failed = [c for c in cases if not c[1]]
    for label, _ok, got, want in failed:
        print("FAIL %s\n  got:  %r\n  want: %r" % (label, got, want))
    print("%d/%d self-test cases pass" % (len(cases) - len(failed), len(cases)))
    return 1 if failed else 0


def _raises(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except Exception as exc:
        return exc
    return None


# --- command line ---------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", nargs="?", metavar="SOURCE",
                    help="local Lottie JSON or dotLottie file")
    ap.add_argument("out", nargs="?", metavar="OUT",
                    help="new scratch GIF path, created exclusively")
    ap.add_argument("--lottie-js", metavar="PATH",
                    help="an already-available local copy of the pinned "
                         "lottie-web build, used instead of the CDN")
    ap.add_argument("--test", action="store_true", help="run the self-test")
    args = ap.parse_args(argv)
    if args.test:
        return run_self_test()
    if not args.source or not args.out:
        ap.error("give SOURCE and OUT (or --test)")
    try:
        return render(args.source, args.out, args.lottie_js)
    except Exception as exc:
        print("FAILED: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
