#!/usr/bin/env python3
"""Scan a topic queue and checkpoint one verified public entry.

Semantic identity and entry quality remain the caller's responsibility.
Exit 2 means invalid input/evidence; exit 3 means stale state/publication failure.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile

_OBSIDIAN_SHARED_MODULES = ('atomic_move',)

# --- obsidian shared-layer bootstrap (canonical; see shared/CONVENTIONS.md) ---
import os as _os, sys as _sys
_here = _os.path.dirname(_os.path.realpath(__file__))
_required = tuple(_m + ".py" for _m in (
    globals().get("_OBSIDIAN_SHARED_MODULES") or ("slugify",)))
_env = _os.environ.get("OBSIDIAN_VAULT_SHARED")
if _env:                                   # explicit override: authoritative, no fallback
    _tried = [_os.path.abspath(_os.path.expanduser(_env))]
else:                                      # plugin-relative walk-up, at most 5 levels
    _tried, _d = [], _here
    for _ in range(5):
        _tried.append(_os.path.join(_d, "shared", "scripts"))
        _d = _os.path.dirname(_d)
    _tried.append(_here)                   # extracted skill with co-located helpers
_missing = {_p: [_m for _m in _required if not _os.path.isfile(_os.path.join(_p, _m))]
            for _p in _tried if _os.path.isdir(_p)}
_shared = next((_p for _p in _tried if _p in _missing and not _missing[_p]), None)
if _shared is None:
    raise SystemExit("""obsidian: cannot find the plugin's shared/scripts/ folder, which holds
the one canonical copy of the conventions this script depends on. A usable
folder must contain these required module(s): %s
Looked for:
  %s
Fix: install the whole plugin tree, or set OBSIDIAN_VAULT_SHARED to the
shared/scripts/ directory (unset it to use the plugin-relative walk-up).
Do NOT paste a second copy of the algorithm into this skill -- a divergent
copy is the bug the shared layer exists to prevent.""" % (
    ", ".join(_required), "\n  ".join(
        _p + (" (not a directory)" if _p not in _missing else
              " (missing: %s)" % ", ".join(_missing[_p]))
        for _p in _tried)))
_sys.path[:] = [_p for _p in _sys.path if _p not in (_shared, _here)]
_sys.path.insert(0, _shared)               # shared/scripts/ FIRST
if _here != _shared:
    _sys.path.insert(1, _here)              # sibling modules before unrelated paths
# --- end bootstrap ---

import atomic_move

SCHEMA = "obsidian-wiki-add-backlog-v1"
LIST = re.compile(r"^([-+*]|[0-9]{1,9}[.)])([ \t]+)(.*)$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
NOTICE = "File evidence is verified; semantic identity and note quality require caller judgment."


class Conflict(ValueError):
    """A reviewed snapshot no longer authorizes a write."""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def absolute_leaf(path):
    path = Path(os.path.abspath(os.path.expanduser(os.fspath(path))))
    return path.parent.resolve(strict=True) / path.name


def read_stable(path):
    """Bind exact bytes to the shared stable regular-file publication token."""
    expected = atomic_move.regular_file_snapshot(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as handle:
        opened = os.fstat(handle.fileno())
        data = handle.read()
        identity = (opened.st_dev, opened.st_ino, stat.S_IFMT(opened.st_mode))
    if (identity != expected.identity or digest(data) != expected.digest
            or len(data) != expected.size
            or atomic_move.regular_file_snapshot(path) != expected):
        raise Conflict("file changed during reading: %s" % path)
    data.decode("utf-8")
    return data, expected


def token_json(token):
    return {"identity": dict(zip(("device", "inode", "kind"), token.identity)),
            "sha256": token.digest, "size": token.size, "mode": token.mode}


def parse_queue(data):
    """Parse flush-left list requests without normalizing any source bytes."""
    lines = data.decode("utf-8").splitlines(keepends=True)
    source_digest = digest(data)
    items, reports = [], []
    completed = 0
    frontmatter = bool(lines and lines[0].lstrip("\ufeff").strip() == "---")
    fence, comment, parent, offset = None, False, None, 0
    for number, raw in enumerate(lines, 1):
        start = offset
        offset += len(raw.encode("utf-8"))
        line = raw.rstrip("\r\n")
        if frontmatter:
            if number > 1 and line.strip() in ("---", "..."):
                frontmatter = False
            continue
        if fence:
            if re.fullmatch(r" {0,3}" + re.escape(fence[0]) +
                            "{" + str(fence[1]) + r",}[ \t]*", line):
                fence = None
            continue
        # Hide comments without letting apparent requests or fences inside
        # them become syntax. Keep the visible part of an inline request.
        visible = []
        cursor = 0
        while cursor < len(line):
            if comment:
                end = line.find("-->", cursor)
                if end < 0:
                    break
                comment, cursor = False, end + 3
            else:
                begin = line.find("<!--", cursor)
                if begin < 0:
                    visible.append(line[cursor:])
                    break
                visible.append(line[cursor:begin])
                comment, cursor = True, begin + 4
        clean = "".join(visible)
        # A comment before/in the list marker is not a flush-left request.
        original_match = LIST.match(line)
        if clean != line and (original_match is None or
                              not clean.startswith(original_match[1] + original_match[2])):
            continue
        opening = FENCE.match(clean)
        if opening:
            fence = (opening[1][0], len(opening[1]))
            parent = None
            continue
        match = LIST.match(clean)
        if not match:
            if parent is not None and clean[:1] in (" ", "\t"):
                parent["context_lines"].append(clean)
            elif clean.strip():
                parent = None
            continue
        parent = None
        body = match[3]
        prefix = match[1] + match[2]
        if original_match and prefix != original_match[1] + original_match[2]:
            reports.append({"line": number, "raw_line": line,
                            "reason": "comment interrupts list marker"})
            continue
        marker = re.match(r"^\[([^\]]*)\](?:[ \t]+|$)", body)
        if marker and original_match and not original_match[3].startswith(marker[0]):
            reports.append({"line": number, "raw_line": line,
                            "reason": "comment interrupts checkbox marker"})
            continue
        if marker and marker[1] in ("x", "X"):
            completed += 1
            continue
        if marker and marker[1] != " ":
            reports.append({"line": number, "raw_line": line,
                            "reason": "custom or malformed checkbox state"})
            continue
        bracket = re.match(r"^\[[^\]\r\n]*\]", body)
        link = body.startswith("[[") or re.match(r"^\[[^\]\r\n]*\](?:\(|\[)", body)
        if bracket and not marker and not link:
            reports.append({"line": number, "raw_line": line,
                            "reason": "checkbox lacks separating whitespace"})
            continue
        text_value = (body[marker.end():] if marker else body).strip()
        if not text_value:
            reports.append({"line": number, "raw_line": line,
                            "reason": "empty request"})
            continue
        state = "unchecked" if marker else "unmarked"
        patch_start = start + len(prefix.encode("utf-8")) + (1 if marker else 0)
        item = {"id": digest((source_digest + ":" + str(start)).encode("ascii")),
                "ordinal": len(items), "line": number, "list_marker": match[1],
                "marker_state": state, "text": text_value, "context_lines": [],
                "raw_line": line, "patch_start": patch_start}
        items.append(item)
        parent = item
    if frontmatter or fence or comment:
        reports.append({"line": len(lines), "reason": "unclosed frontmatter, fence or comment"})
    return items, reports, {"pending": len(items), "completed_skipped": completed,
                            "report_only": len(reports)}


def scan_document(path):
    path = absolute_leaf(path)
    data, token = read_stable(path)
    items, reports, counts = parse_queue(data)
    source = token_json(token)
    source["bytes_base64"] = base64.b64encode(data).decode("ascii")
    report = {"schema": SCHEMA, "operation": "scan", "backlog": str(path),
              "source": source, "items": items, "report_only": reports, "counts": counts}
    report["integrity_sha256"] = digest(json.dumps(
        report, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return report


def write_snapshot(report, output):
    output = absolute_leaf(output)
    if output == Path(report["backlog"]) or any(p.casefold() == "wiki" for p in output.parts):
        raise ValueError("snapshot must be private, outside Wiki and distinct from backlog")
    stage = Path(tempfile.mkdtemp(prefix=".wiki-add-scan-", dir=output.parent))
    try:
        staged = stage / "snapshot.json"
        with staged.open("xb") as handle:
            handle.write((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            atomic_move.set_private_mode(handle, 0o600)
            handle.flush()
            os.fsync(handle.fileno())
        atomic_move.publish_new(staged, output, atomic_move.regular_file_snapshot,
                                stage_parent=output.parent)
    except Exception as exc:
        raise Conflict("snapshot publication failed; recovery directory %s: %s" % (stage, exc)) from exc
    shutil.rmtree(stage, ignore_errors=True)


def complete(snapshot, item_id, wiki, entry):
    raw, _ = read_stable(absolute_leaf(snapshot))
    saved = json.loads(raw)
    if not isinstance(saved, dict) or saved.get("schema") != SCHEMA:
        raise ValueError("not a wiki-add snapshot")
    current = scan_document(saved["backlog"])
    # This also verifies all IDs, offsets, exact bytes and checksum. A checksum
    # detects accidental inconsistency; it is not an authorization signature.
    if current != saved:
        raise Conflict("backlog or snapshot changed; rescan and reconsider pending items")
    selected = next((item for item in current["items"] if item["id"] == item_id), None)
    if selected is None:
        raise ValueError("item is not pending in this snapshot")
    wiki = Path(wiki).resolve(strict=True)
    if not wiki.is_dir():
        raise ValueError("Wiki must be a directory")
    entry = absolute_leaf(entry)
    if entry.suffix != ".md" or not entry.is_relative_to(wiki):
        raise ValueError("entry evidence must be a Markdown file inside the selected Wiki")
    entry_bytes, proof = read_stable(entry)
    if not entry_bytes.strip():
        raise ValueError("entry evidence is empty")
    backlog = Path(current["backlog"])
    source = current["source"]
    identity = source["identity"]
    expected = atomic_move.RegularFileSnapshot(
        (identity["device"], identity["inode"], identity["kind"]),
        source["sha256"], source["mode"], source["size"])
    if proof.identity == expected.identity:
        raise ValueError("backlog itself cannot be entry evidence")
    data = base64.b64decode(source["bytes_base64"], validate=True)
    at = selected["patch_start"]
    after = (data[:at] + b"x" + data[at + 1:] if selected["marker_state"] == "unchecked"
             else data[:at] + b"[x] " + data[at:])
    stage_parent = backlog.parent
    while stage_parent == wiki or stage_parent.is_relative_to(wiki):
        stage_parent = stage_parent.parent
    stage = Path(tempfile.mkdtemp(prefix=".wiki-add-complete-", dir=stage_parent))
    try:
        staged = stage / "backlog.md"
        with staged.open("xb") as handle:
            handle.write(after)
            atomic_move.set_private_mode(handle, expected.mode)
            handle.flush()
            os.fsync(handle.fileno())
        if atomic_move.regular_file_snapshot(entry) != proof:
            raise Conflict("entry evidence changed before checkpoint")
        published = atomic_move.replace_expected(
            staged, backlog, expected, atomic_move.regular_file_snapshot, stage,
            stage_parent=stage_parent)
    except Exception as exc:
        raise Conflict("completion failed; recovery directory %s: %s" % (stage, exc)) from exc
    shutil.rmtree(stage, ignore_errors=True)
    return {"schema": SCHEMA, "operation": "complete", "result": "completed",
            "item": selected, "backlog": {"path": str(backlog),
            "before_sha256": expected.digest, "after_sha256": published.digest},
            "entry": {"path": str(entry), **token_json(proof)}, "judgment_notice": NOTICE}


def run_self_tests():
    """Exercise queue parsing and guarded completion in temporary trees."""
    import contextlib
    import io
    from unittest import mock

    cases = []

    def check(label, got, want=True):
        cases.append((label, got == want, got, want))

    def raises(kind, call):
        try:
            call()
        except kind:
            return True
        except Exception as exc:
            return type(exc).__name__
        return False

    def save_scan(queue, snapshot):
        report = scan_document(queue)
        write_snapshot(report, snapshot)
        return report

    with tempfile.TemporaryDirectory(prefix="wiki-add-backlog-test-") as tmp:
        root = Path(tmp)
        wiki = root / "Wiki"
        wiki.mkdir()
        entry = wiki / "topic.md"
        entry.write_bytes(b"---\ntitle: Topic\n---\nTopic body.\n")

        fixture = (
            b"---\r\ntitle: Queue\r\n---\r\n"
            b"- [ ] Alpha\r\n"
            b"  - nested request-like context\r\n"
            b"  explanation\r\n"
            b"1. Beta \xe2\x80\x94 caf\xc3\xa9 <!-- inline context -->\r\n"
            b"- [x] Done\r\n"
            b"- [X] Also done\r\n"
            b"- [?] Custom\r\n"
            b"- [??]No-space custom\r\n"
            b"- [ ]\r\n"
            b"```text\r\n- [ ] Fenced\r\n```\r\n"
            b"<!--\r\n- [ ] Commented\r\n-->\r\n"
            b"- Alpha\r\n")
        parsed, reports, counts = parse_queue(fixture)
        check("frontmatter, fences, and comments are excluded",
              [item["text"] for item in parsed],
              ["Alpha", "Beta \u2014 caf\u00e9", "Alpha"])
        check("numbered and unordered markers are retained",
              [item["list_marker"] for item in parsed], ["-", "1.", "-"])
        check("nested lines remain context rather than requests",
              parsed[0]["context_lines"],
              ["  - nested request-like context", "  explanation"])
        check("duplicate request text gets distinct item ids",
              parsed[0]["id"] != parsed[2]["id"])
        check("checked items are skipped and counted",
              counts["completed_skipped"], 2)
        check("custom, malformed, and empty states are report-only",
              (counts["report_only"], len(reports)), (3, 3))
        check("Unicode survives inventory text exactly",
              parsed[1]["text"], "Beta \u2014 caf\u00e9")

        # One CRLF queue without a final newline covers both patch forms and
        # proves that a fresh scan, rather than a stale item id, is required.
        queue = root / "queue.md"
        queue.write_bytes(b"- [ ] Cr\xc3\xa8me\r\n2. Plain")
        os.chmod(queue, 0o640)
        entry_before = entry.read_bytes()
        first_snapshot = root / "first.json"
        first = save_scan(queue, first_snapshot)
        first_id = first["items"][0]["id"]
        first_result = complete(first_snapshot, first_id, wiki, entry)
        check("unchecked completion changes only the marker byte",
              queue.read_bytes(), b"- [x] Cr\xc3\xa8me\r\n2. Plain")
        check("completion preserves queue permissions",
              stat.S_IMODE(queue.stat().st_mode), 0o640)
        check("completion never changes entry evidence bytes",
              entry.read_bytes(), entry_before)
        check("completion reports before/after and entry evidence",
              (first_result["result"], first_result["entry"]["sha256"],
               first_result["judgment_notice"]),
              ("completed", digest(entry_before), NOTICE))
        check("a stale completed item id cannot be replayed",
              raises(Conflict, lambda: complete(
                  first_snapshot, first_id, wiki, entry)))

        second_snapshot = root / "second.json"
        second = save_scan(queue, second_snapshot)
        check("refreshed scan skips the completed item",
              (second["counts"]["pending"],
               second["counts"]["completed_skipped"]), (1, 1))
        complete(second_snapshot, second["items"][0]["id"], wiki, entry)
        check("unmarked completion inserts a marker byte-exactly",
              queue.read_bytes(), b"- [x] Cr\xc3\xa8me\r\n2. [x] Plain")

        # Missing, outside, and symlink evidence must leave a fresh queue
        # byte-for-byte untouched. Exercise the CLI's documented exit 2 for
        # the common missing-proof path as well as direct validation errors.
        def pending_case(name):
            q = root / (name + "-queue.md")
            s = root / (name + "-snapshot.json")
            q.write_bytes(("- [ ] " + name + "\n").encode("utf-8"))
            report = save_scan(q, s)
            return q, s, report["items"][0]["id"], q.read_bytes()

        missing_q, missing_s, missing_id, missing_before = pending_case("missing")
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            missing_rc = main([
                "complete", "--snapshot", str(missing_s), "--item", missing_id,
                "--wiki", str(wiki), "--entry", str(wiki / "missing.md")])
        check("missing entry evidence is exit 2 and does not mark the queue",
              (missing_rc, missing_q.read_bytes()), (2, missing_before))

        outside = root / "outside.md"
        outside.write_bytes(b"Outside evidence.\n")
        outside_q, outside_s, outside_id, outside_before = pending_case("outside")
        check("outside entry evidence is rejected",
              raises(ValueError, lambda: complete(
                  outside_s, outside_id, wiki, outside)))
        check("outside-evidence refusal preserves the queue",
              outside_q.read_bytes(), outside_before)

        symlink_q, symlink_s, symlink_id, symlink_before = pending_case("symlink")
        symlink_entry = wiki / "linked.md"
        os.symlink(outside, symlink_entry)
        check("symlink entry evidence is rejected",
              raises(OSError, lambda: complete(
                  symlink_s, symlink_id, wiki, symlink_entry)))
        check("symlink-evidence refusal preserves the queue",
              symlink_q.read_bytes(), symlink_before)

        stale_q, stale_s, stale_id, _ = pending_case("stale")
        stale_q.write_bytes(b"- [ ] stale\nlate editor bytes\n")
        check("a stale queue snapshot is rejected",
              raises(Conflict, lambda: complete(
                  stale_s, stale_id, wiki, entry)))
        check("stale refusal preserves the later editor bytes",
              stale_q.read_bytes(), b"- [ ] stale\nlate editor bytes\n")

        forged_q, forged_s, forged_id, forged_before = pending_case("forged")
        forged = json.loads(forged_s.read_text(encoding="utf-8"))
        forged["items"][0]["text"] = "different request"
        forged_s.write_text(json.dumps(forged), encoding="utf-8")
        check("an inconsistent or forged snapshot is rejected",
              raises(Conflict, lambda: complete(
                  forged_s, forged_id, wiki, entry)))
        check("forged-snapshot refusal preserves the queue",
              forged_q.read_bytes(), forged_before)

        race_q, race_s, race_id, _ = pending_case("race")
        race_bytes = b"- [ ] race\na concurrent editor won\n"
        real_replace = atomic_move.replace_expected

        def racing_replace(*args, **kwargs):
            race_q.write_bytes(race_bytes)
            return real_replace(*args, **kwargs)

        proof_before = entry.read_bytes()
        with mock.patch.object(atomic_move, "replace_expected",
                               side_effect=racing_replace):
            raced = raises(Conflict, lambda: complete(
                race_s, race_id, wiki, entry))
        check("a publication race fails closed and retains recovery staging",
              (raced, bool(list(root.glob(".wiki-add-complete-*")))),
              (True, True))
        check("a publication race preserves both later queue and proof note",
              (race_q.read_bytes(), entry.read_bytes()),
              (race_bytes, proof_before))

        exclusive_q = root / "exclusive.md"
        exclusive_q.write_bytes(b"- One\n")
        exclusive_report = scan_document(exclusive_q)
        exclusive_out = root / "exclusive.json"
        write_snapshot(exclusive_report, exclusive_out)
        snapshot_before = exclusive_out.read_bytes()
        check("snapshot output is exclusive and cannot be overwritten",
              raises(Conflict, lambda: write_snapshot(
                  exclusive_report, exclusive_out)))
        check("exclusive-output refusal preserves the first snapshot",
              exclusive_out.read_bytes(), snapshot_before)
        wiki_out = wiki / "snapshot.json"
        check("snapshot output inside Wiki is rejected",
              raises(ValueError, lambda: write_snapshot(
                  exclusive_report, wiki_out)))

    failed = 0
    for label, ok, got, want in cases:
        if not ok:
            print("FAIL: %s\n  expected %r, got %r" % (label, want, got))
            failed += 1
    if failed:
        print("%d/%d self-test cases failed" % (failed, len(cases)))
        return 1
    print("%d/%d self-test cases pass" % (len(cases), len(cases)))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true", help="run temporary-file self-tests")
    commands = parser.add_subparsers(dest="command")
    scan = commands.add_parser("scan", help="inventory pending top-level requests")
    scan.add_argument("backlog")
    scan.add_argument("--out", required=True, help="new private snapshot file")
    checkpoint = commands.add_parser("complete", help="check off one reviewed item")
    checkpoint.add_argument("--snapshot", required=True, help="private scan snapshot")
    checkpoint.add_argument("--item", required=True, help="pending item id from that scan")
    checkpoint.add_argument("--wiki", required=True, help="selected Wiki directory")
    checkpoint.add_argument("--entry", required=True, help="verified public Markdown entry")
    args = parser.parse_args(argv)
    if args.test:
        return run_self_tests()
    if not args.command:
        parser.error("choose scan or complete")
    try:
        if args.command == "scan":
            report = scan_document(args.backlog)
            write_snapshot(report, args.out)
        else:
            report = complete(args.snapshot, args.item, args.wiki, args.entry)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Conflict as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 3
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
