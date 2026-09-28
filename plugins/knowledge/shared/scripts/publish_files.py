"""Snapshot, verify and publish reviewed vault files without clobbering edits.

A command line for the SAFE_WRITES.md recipe on regular files: the version a
workflow read is recorded with ``atomic_move.regular_file_snapshot``, a new
file is published with ``atomic_move.publish_new`` and a replacement with
``atomic_move.replace_expected`` against that recorded version. PATH is
vault-relative (forward slashes) or absolute and must resolve inside the
vault's real path. A leaf symlink is never followed.

  snapshot --vault VAULT [-o OUT [--replace]] PATH...
      Record each path before the workflow reads it: absent, or a regular
      file's identity, digest, mode and size. ``-o`` merges into an existing
      snapshot file and keeps the earlier record of a path already there,
      failing when that path no longer matches it. ``--replace`` instead
      records the named paths afresh, before the workflow re-reads them.
  verify --vault VAULT --snapshots SNAP.json
      Report each recorded path as unchanged, changed, appeared, removed or
      unsafe.
  publish --vault VAULT --snapshots SNAP.json --manifest MANIFEST.json
          [--create-dir DIR] [--dry-run]
      Publish a JSON list of {"path": <vault-relative target>, "draft":
      <absolute draft path>}: new files first, then replacements. A path that
      already equals its draft is skipped, so the same command can be rerun
      after a partial failure. Any failed precheck publishes nothing; the
      first publication failure stops the run and leaves later paths pending.

Every command prints JSON and exits 1 unless everything is clean.
Run ``python3 publish_files.py --test`` for the self-test.
"""
import argparse
import contextlib
import errno
import hashlib
import io
import json
import os
import shutil
import stat
import sys
import tempfile

# Keep the sibling publication helper available when a harness imports this
# file directly by path instead of executing it as a script.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import atomic_move  # noqa: E402


STAGE_PREFIX = ".knowledge-publish-"
STAGED_NAME = "staged"
NEW_FILE_MODE = 0o644


class InputError(ValueError):
    """An argument or input file that the command cannot use."""


def _describe(exc):
    return "%s: %s" % (type(exc).__name__, exc)


def _inside(path, root):
    prefix = root.rstrip(os.sep) + os.sep
    return path == root or path.startswith(prefix)


def _vault(path):
    """``(given absolute path, real path)`` of an existing vault directory."""
    if not os.path.isdir(path):
        raise InputError("vault %s is not a directory" % path)
    return os.path.abspath(path), os.path.realpath(path)


def vault_key(vault, path):
    """PATH's normalized vault-relative key; refuse one outside the vault."""
    given, real = vault
    if not isinstance(path, str) or not path or "\0" in path:
        raise InputError("path must be a non-empty string")
    if os.path.isabs(path):
        absolute = os.path.normpath(path)
        for root in (given, real):
            if _inside(absolute, root):
                rel = os.path.relpath(absolute, root)
                break
        else:
            parent = os.path.realpath(os.path.dirname(absolute))
            if not _inside(parent, real):
                raise InputError("%s is outside the vault" % path)
            rel = os.path.relpath(
                os.path.join(parent, os.path.basename(absolute)), real)
    else:
        rel = os.path.normpath(path)
    if (rel in (os.curdir, os.pardir) or rel.startswith(os.pardir + os.sep)
            or os.path.isabs(rel)):
        raise InputError("%s is outside the vault" % path)
    parent = os.path.realpath(os.path.join(real, os.path.dirname(rel)))
    if not _inside(parent, real):
        raise InputError("%s resolves outside the vault" % path)
    return rel.replace(os.sep, "/")


def _target(vault, key):
    return os.path.join(vault[1], *key.split("/"))


def observe(target):
    """``(state, token, error)`` for one path, never following a symlink."""
    try:
        item = os.lstat(target)
    except FileNotFoundError:
        return "absent", None, None
    except OSError as exc:
        return "unsafe", None, _describe(exc)
    if stat.S_ISLNK(item.st_mode):
        return "unsafe", None, "a symlink occupies the path; it is not followed"
    if not stat.S_ISREG(item.st_mode):
        return "unsafe", None, "a non-regular file occupies the path"
    try:
        return "file", atomic_move.regular_file_snapshot(target), None
    except (OSError, UnicodeError) as exc:
        return "unsafe", None, _describe(exc)


def _record(key, state, token, error):
    if state == "file":
        return {"path": key, "state": "file",
                "identity": list(token.identity), "digest": token.digest,
                "mode": token.mode, "size": token.size}
    if state == "absent":
        return {"path": key, "state": "absent"}
    return {"path": key, "state": state, "error": error}


def _expected(record):
    return atomic_move.RegularFileSnapshot(
        identity=tuple(record["identity"]), digest=record["digest"],
        mode=record["mode"], size=record["size"])


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _usable(record):
    if not isinstance(record, dict) or not isinstance(record.get("path"), str):
        return False
    if record.get("state") == "absent":
        return True
    identity = record.get("identity")
    return (record.get("state") == "file"
            and isinstance(identity, list) and len(identity) == 3
            and all(_is_int(value) for value in identity)
            and isinstance(record.get("digest"), str)
            and _is_int(record.get("mode")) and _is_int(record.get("size")))


def compare(record, observed):
    """``(status, detail)`` of an ``observe`` result against its record."""
    state, token, error = observed
    if state == "unsafe":
        return "unsafe", error
    if record["state"] == "absent":
        if state == "absent":
            return "unchanged", None
        return "appeared", "a file now occupies a path recorded as absent"
    if state == "absent":
        return "removed", "the recorded file is gone"
    expected = _expected(record)
    if token == expected:
        return "unchanged", None
    differ = [name for name, same in (
        ("bytes", (token.digest, token.size) == (expected.digest, expected.size)),
        ("identity", token.identity == expected.identity),
        ("mode", token.mode == expected.mode)) if not same]
    return "changed", "%s differ from the snapshot" % ", ".join(differ)


def _read_json(path, what):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        raise InputError("cannot read the %s %s (%s)"
                         % (what, path, _describe(exc))) from exc


def load_snapshots(path, vault):
    """Records of a snapshot file by path, earlier record first."""
    data = _read_json(path, "snapshot file")
    if not isinstance(data, dict) or not isinstance(data.get("snapshots"), list):
        raise InputError("%s is not a snapshot file" % path)
    if data.get("vault") != vault[1]:
        raise InputError("%s records vault %r, not %r"
                         % (path, data.get("vault"), vault[1]))
    records = {}
    for record in data["snapshots"]:
        if not _usable(record):
            raise InputError("%s has an unusable record: %r" % (path, record))
        records.setdefault(record["path"], record)
    return records


def _write_json(path, data):
    fd, temporary = tempfile.mkstemp(
        prefix=".snapshots-", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def cmd_snapshot(vault_arg, paths, output=None, replace=False):
    try:
        vault = _vault(vault_arg)
        records = {}
        if output is not None:
            output = os.path.abspath(output)
            if _inside(os.path.realpath(os.path.dirname(output)), vault[1]):
                raise InputError("the snapshot file %s must be outside the "
                                 "vault, in the run's scratch" % output)
            if os.path.lexists(output):
                records = load_snapshots(output, vault)
    except InputError as exc:
        return {"ok": False, "error": str(exc)}, 1

    ok = True
    results = []
    for path in paths:
        try:
            key = vault_key(vault, path)
        except InputError as exc:
            ok = False
            results.append({"path": path, "state": "refused", "error": str(exc)})
            continue
        observed = observe(_target(vault, key))
        if key in records and not replace:
            status, detail = compare(records[key], observed)
            kept = "kept the earlier record"
            if status != "unchanged":
                ok = False
                kept += (", which no longer matches (%s: %s); use --replace "
                         "when re-reading the path" % (status, detail))
            results.append(dict(records[key], detail=kept))
            continue
        record = _record(key, *observed)
        if observed[0] == "unsafe":
            ok = False
            results.append(record)
            continue
        results.append(dict(record, detail="replaced the earlier record")
                       if key in records else record)
        records[key] = record

    if output is not None:
        try:
            _write_json(output, {"vault": vault[1],
                                 "snapshots": list(records.values())})
        except OSError as exc:
            return {"ok": False, "error": "cannot write %s (%s)"
                    % (output, _describe(exc))}, 1
    return {"ok": ok, "vault": vault[1], "snapshots": results}, 0 if ok else 1


def cmd_verify(vault_arg, snapshots):
    try:
        vault = _vault(vault_arg)
        records = load_snapshots(snapshots, vault)
    except InputError as exc:
        return {"ok": False, "error": str(exc)}, 1
    results = []
    for key, record in records.items():
        try:
            if vault_key(vault, key) != key:
                raise InputError("%s is not a normalized vault path" % key)
        except InputError as exc:
            status, detail = "unsafe", str(exc)
        else:
            status, detail = compare(record, observe(_target(vault, key)))
        entry = {"path": key, "status": status}
        if detail:
            entry["detail"] = detail
        results.append(entry)
    ok = all(entry["status"] == "unchanged" for entry in results)
    return {"ok": ok, "vault": vault[1], "results": results}, 0 if ok else 1


def _load_manifest(path):
    items = _read_json(path, "manifest")
    if not isinstance(items, list) or not all(
            isinstance(item, dict) and isinstance(item.get("path"), str)
            and isinstance(item.get("draft"), str) for item in items):
        raise InputError('%s is not a JSON list of {"path", "draft"} objects'
                         % path)
    return items


def _read_draft(draft):
    if not os.path.isabs(draft):
        raise InputError("draft %s is not an absolute path" % draft)
    try:
        if not stat.S_ISREG(os.lstat(draft).st_mode):
            raise InputError("draft %s is not a regular file" % draft)
        with open(draft, "rb") as fh:
            return fh.read()
    except OSError as exc:
        raise InputError("draft %s is missing or unreadable (%s)"
                         % (draft, _describe(exc))) from exc


def _new_file_mode():
    mask = os.umask(0o022)
    os.umask(mask)
    return NEW_FILE_MODE & ~mask


def _stage_location(vault_real, directory):
    """A same-device parent for the run's private stage, or ``None``."""
    device = os.stat(directory).st_dev
    if os.stat(vault_real).st_dev == device:
        return vault_real
    parent = os.path.dirname(directory)
    if os.stat(parent).st_dev == device:
        return parent
    return None


def _refuse(plan, detail):
    plan.update(action="refused", detail=detail)
    return plan


def _plan(vault, records, item, create_dir, new_mode):
    """Check one manifest item without writing; return its planned action."""
    plan = {"path": item["path"]}
    try:
        key = vault_key(vault, item["path"])
    except InputError as exc:
        return _refuse(plan, str(exc))
    plan["path"] = key
    record = records.get(key)
    if record is None:
        return _refuse(plan, "no snapshot record; snapshot the path before "
                             "reading it")
    try:
        data = _read_draft(item["draft"])
    except InputError as exc:
        return _refuse(plan, str(exc))
    target = _target(vault, key)
    plan.update(_target=target, _data=data,
                _digest=hashlib.sha256(data).hexdigest())
    observed = observe(target)
    if (observed[0] == "file"
            and (observed[1].digest, observed[1].size)
            == (plan["_digest"], len(data))):
        plan.update(action="unchanged", detail="already equals the draft")
        return plan
    status, detail = compare(record, observed)
    if status != "unchanged":
        return _refuse(plan, "%s: %s" % (status, detail))

    directory = os.path.dirname(target)
    make_dir = False
    if record["state"] == "absent" and not os.path.isdir(directory):
        rel_dir = os.path.dirname(key)
        if os.path.lexists(directory):
            return _refuse(plan, "%s is not a directory" % rel_dir)
        if rel_dir != create_dir:
            return _refuse(plan, "the target directory %s does not exist; %s"
                           % (rel_dir, "pass --create-dir %s to create it"
                              % rel_dir if "/" not in rel_dir else
                              "--create-dir creates only a direct child of "
                              "the vault"))
        make_dir = True
    try:
        location = _stage_location(
            vault[1], vault[1] if make_dir else os.path.realpath(directory))
    except OSError as exc:
        return _refuse(plan, "cannot inspect the target directory (%s)"
                       % _describe(exc))
    if location is None:
        return _refuse(plan, "LinkUnavailable: no parent on the target's "
                             "filesystem can hold the private stage")
    if record["state"] == "absent":
        plan.update(action="create", _mode=new_mode)
    else:
        plan.update(action="replace", _mode=record["mode"],
                    _expected=_expected(record))
    plan.update(_make_dir=make_dir, _location=location)
    return plan


def _publish_one(vault, plan, stage_parent, made_dirs):
    """Stage, publish and read back one planned create or replacement."""
    target = plan["_target"]
    directory = os.path.dirname(target)
    if plan["_make_dir"] and directory not in made_dirs:
        os.mkdir(directory)
        made_dirs.add(directory)
        item = os.lstat(directory)
        if (stat.S_ISLNK(item.st_mode) or not stat.S_ISDIR(item.st_mode)
                or os.path.realpath(directory) != directory):
            raise atomic_move.PublicationConflict(
                "%s is not the real directory just created" % directory)
    if not _inside(os.path.realpath(directory), vault[1]):
        raise atomic_move.PublicationConflict(
            "%s now resolves outside the vault" % directory)

    stage_dir = tempfile.mkdtemp(prefix="file-", dir=stage_parent)
    plan["stage_dir"] = stage_dir
    staged = os.path.join(stage_dir, STAGED_NAME)
    with open(staged, "xb") as fh:
        fh.write(plan["_data"])
        fh.flush()
        atomic_move.set_private_mode(fh, plan["_mode"])
        os.fsync(fh.fileno())
    snapshot = atomic_move.regular_file_snapshot
    if plan["action"] == "create":
        published = atomic_move.publish_new(
            staged, target, snapshot, stage_parent)
    else:
        published = atomic_move.replace_expected(
            staged, target, plan["_expected"], snapshot, stage_dir,
            stage_parent=stage_parent)
    after = snapshot(target)
    if (after != published
            or (after.digest, after.size) != (plan["_digest"], len(plan["_data"]))):
        raise atomic_move.PublicationConflict(
            "%s does not read back as the draft bytes" % plan["path"])
    shutil.rmtree(stage_dir, ignore_errors=True)
    del plan["stage_dir"]


def cmd_publish(vault_arg, snapshots, manifest, create_dir=None,
                dry_run=False):
    try:
        vault = _vault(vault_arg)
        records = load_snapshots(snapshots, vault)
        items = _load_manifest(manifest)
        if create_dir is not None:
            create_dir = os.path.normpath(create_dir)
            if (os.sep in create_dir or os.path.isabs(create_dir)
                    or create_dir in (os.curdir, os.pardir)):
                raise InputError("--create-dir must name a direct child of "
                                 "the vault, not %s" % create_dir)
    except InputError as exc:
        return {"ok": False, "error": str(exc)}, 1

    new_mode = _new_file_mode()
    plans = [_plan(vault, records, item, create_dir, new_mode)
             for item in items]
    keys = [plan["path"] for plan in plans]
    for plan in plans:
        if keys.count(plan["path"]) > 1:
            _refuse(plan, "listed more than once in the manifest")
    writes = [plan for plan in plans if plan["action"] in ("create", "replace")]
    for plan in writes:
        if plan["_location"] != writes[0]["_location"]:
            _refuse(plan, "LinkUnavailable: on a different filesystem from "
                          "this run's private stage; publish it separately")

    refused = any(plan["action"] == "refused" for plan in plans)
    for plan in plans:
        if plan["action"] == "create":
            plan["detail"] = "would create" + (
                " after creating %s" % os.path.dirname(plan["path"])
                if plan["_make_dir"] else "")
        elif plan["action"] == "replace":
            plan["detail"] = "would replace the snapshotted version"
    if refused and not dry_run:
        for plan in plans:
            if plan["action"] in ("create", "replace"):
                plan.update(action="pending",
                            detail="not attempted: another path was refused")

    stage_parent = None
    if not refused and not dry_run:
        order = ([plan for plan in plans if plan["action"] == "create"]
                 + [plan for plan in plans if plan["action"] == "replace"])
        failed = False
        made_dirs = set()
        for plan in order:
            if failed:
                plan.update(action="pending",
                            detail="not attempted after an earlier failure")
                continue
            done = "created" if plan["action"] == "create" else "replaced"
            try:
                if stage_parent is None:
                    stage_parent = tempfile.mkdtemp(
                        prefix=STAGE_PREFIX, dir=plan["_location"])
                _publish_one(vault, plan, stage_parent, made_dirs)
            except (OSError, ValueError) as exc:
                failed = True
                plan.update(action="failed", error=type(exc).__name__,
                            detail=str(exc))
                recovery = getattr(exc, "recovery_path", None)
                if recovery:
                    plan["recovery_path"] = recovery
            else:
                plan.update(action=done, detail=done + " and read back")
        if stage_parent is not None:
            with contextlib.suppress(OSError):
                os.rmdir(stage_parent)

    ok = all(plan["action"] in ("created", "replaced", "unchanged",
                                "create", "replace") for plan in plans)
    payload = {"ok": ok, "results": [
        {key: value for key, value in plan.items() if not key.startswith("_")}
        for plan in plans]}
    if stage_parent is not None and os.path.lexists(stage_parent):
        payload["stage_parent"] = stage_parent
    return payload, 0 if ok else 1


def run_self_test():
    """Exercise snapshot, verify and publish on temporary vaults."""
    cases = []

    def check(label, got, want):
        cases.append((label, got == want, got, want))

    def put(path, body, mode=None):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(body)
        if mode is not None:
            os.chmod(path, mode)
        return path

    def read(path):
        with open(path, "rb") as fh:
            return fh.read()

    def actions(payload):
        return [entry["action"] for entry in payload.get("results", ())]

    with tempfile.TemporaryDirectory(prefix="publish-files-test.") as root:
        vault = os.path.join(root, "vault")
        scratch = os.path.join(root, "scratch")
        outside = os.path.join(root, "outside")
        for folder in (os.path.join(vault, "Wiki"), scratch, outside):
            os.makedirs(folder)

        def wiki(name):
            return os.path.join(vault, "Wiki", name)

        def draft(name, body):
            return put(os.path.join(scratch, "drafts", name), body)

        def manifest(name, pairs):
            path = os.path.join(scratch, name)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump([{"path": p, "draft": d} for p, d in pairs], fh)
            return path

        def stage_parents():
            return [name for name in os.listdir(vault)
                    if name.startswith(STAGE_PREFIX)]

        snap = os.path.join(scratch, "snapshots.json")
        put(wiki("old.md"), b"old\n", 0o600)
        payload, code = cmd_snapshot(
            vault, ["Wiki/old.md", "Wiki/new.md",
                    os.path.join(vault, "Wiki", "abs.md")], snap)
        check("snapshot records a file and absent paths by vault key",
              (code, [r["state"] for r in payload["snapshots"]],
               payload["snapshots"][0]["digest"]
               == hashlib.sha256(b"old\n").hexdigest(),
               payload["snapshots"][2]["path"],
               len(load_snapshots(snap, _vault(vault)))),
              (0, ["file", "absent", "absent"], True, "Wiki/abs.md", 3))

        merge = os.path.join(scratch, "merge.json")
        put(wiki("merge.md"), b"read version\n")
        cmd_snapshot(vault, ["Wiki/merge.md"], merge)
        payload, same_code = cmd_snapshot(vault, ["Wiki/merge.md"], merge)
        same_detail = payload["snapshots"][0]["detail"]
        put(wiki("merge.md"), b"later edit\n")
        payload, code = cmd_snapshot(
            vault, ["Wiki/merge.md", "Wiki/other.md"], merge)
        stored = load_snapshots(merge, _vault(vault))
        check("snapshot -o merge keeps the earlier record and flags a change",
              (same_code, same_detail, code, stored["Wiki/merge.md"]["digest"]
               == hashlib.sha256(b"read version\n").hexdigest(),
               sorted(stored), "no longer matches (changed: bytes differ"
               in payload["snapshots"][0]["detail"]),
              (0, "kept the earlier record", 1, True,
               ["Wiki/merge.md", "Wiki/other.md"], True))

        put(wiki("other.md"), b"other\n")
        payload, code = cmd_snapshot(vault, ["Wiki/merge.md"], merge,
                                     replace=True)
        check("snapshot --replace refreshes only the named paths",
              (code, payload["snapshots"][0]["detail"],
               [r["status"] for r in cmd_verify(vault, merge)[0]["results"]]),
              (0, "replaced the earlier record", ["unchanged", "appeared"]))

        os.symlink(outside, os.path.join(vault, "Link"))
        escape = os.path.join(scratch, "escape.json")
        payload, code = cmd_snapshot(
            vault, ["../outside/x.md", os.path.join(outside, "x.md"),
                    "Link/x.md"], escape)
        check("paths escaping the vault are refused and not stored",
              (code, [r["state"] for r in payload["snapshots"]],
               load_snapshots(escape, _vault(vault))),
              (1, ["refused"] * 3, {}))

        os.symlink(wiki("old.md"), wiki("alias.md"))
        payload, code = cmd_snapshot(vault, ["Wiki/alias.md"], escape)
        check("a symlink target is unsafe, not followed, and not stored",
              (code, payload["snapshots"][0]["state"],
               load_snapshots(escape, _vault(vault))),
              (1, "unsafe", {}))

        payload, code = cmd_snapshot(
            vault, ["Wiki/x.md"], os.path.join(vault, "snap.json"))
        check("a snapshot file inside the vault is refused",
              (code, os.path.lexists(os.path.join(vault, "snap.json"))),
              (1, False))

        states = os.path.join(scratch, "states.json")
        put(wiki("edit.md"), b"v1\n")
        put(wiki("gone.md"), b"v1\n")
        cmd_snapshot(vault, ["Wiki/edit.md", "Wiki/gone.md", "Wiki/late.md"],
                     states)
        payload, clean_code = cmd_verify(vault, states)
        put(wiki("edit.md"), b"v2\n")
        os.unlink(wiki("gone.md"))
        put(wiki("late.md"), b"late\n")
        payload, code = cmd_verify(vault, states)
        check("verify reports changed, removed and appeared paths",
              (clean_code, code, [r["status"] for r in payload["results"]]),
              (0, 1, ["changed", "removed", "appeared"]))

        first = manifest("first.json", [
            ("Wiki/new.md", draft("new.md", b"new\n")),
            ("Wiki/old.md", draft("old.md", b"replacement\n"))])
        payload, code = cmd_publish(vault, snap, first, dry_run=True)
        check("--dry-run plans every path and writes nothing",
              (code, actions(payload), os.path.lexists(wiki("new.md")),
               read(wiki("old.md")), stage_parents()),
              (0, ["create", "replace"], False, b"old\n", []))

        payload, code = cmd_publish(vault, snap, first)
        check("publish creates and replaces with the recorded mode",
              (code, actions(payload), read(wiki("new.md")),
               read(wiki("old.md")),
               stat.S_IMODE(os.stat(wiki("old.md")).st_mode),
               stat.S_IMODE(os.stat(wiki("new.md")).st_mode)),
              (0, ["created", "replaced"], b"new\n", b"replacement\n",
               0o600, _new_file_mode()))
        check("the stage parent is removed after success",
              ("stage_parent" in payload, stage_parents()), (False, []))

        before = [atomic_move.file_identity(wiki(n))
                  for n in ("new.md", "old.md")]
        payload, code = cmd_publish(vault, snap, first)
        check("a rerun skips paths that already equal their drafts",
              (code, actions(payload),
               [atomic_move.file_identity(wiki(n))
                for n in ("new.md", "old.md")] == before),
              (0, ["unchanged", "unchanged"], True))

        guard = os.path.join(scratch, "guard.json")
        put(wiki("changed.md"), b"read\n")
        cmd_snapshot(vault, ["Wiki/changed.md", "Wiki/fresh.md",
                             "Wiki/appeared.md"], guard)
        put(wiki("changed.md"), b"editor save\n")
        payload, code = cmd_publish(vault, guard, manifest("changed.json", [
            ("Wiki/fresh.md", draft("fresh.md", b"fresh\n")),
            ("Wiki/changed.md", draft("changed.md", b"ours\n"))]))
        check("a file changed after its snapshot refuses the whole run",
              (code, actions(payload), os.path.lexists(wiki("fresh.md")),
               read(wiki("changed.md"))),
              (1, ["pending", "refused"], False, b"editor save\n"))

        put(wiki("appeared.md"), b"late\n")
        payload, code = cmd_publish(vault, guard, manifest("appeared.json", [
            ("Wiki/appeared.md", draft("appeared.md", b"ours\n"))]))
        check("a file that appeared after an absent snapshot is refused",
              (code, actions(payload), read(wiki("appeared.md"))),
              (1, ["refused"], b"late\n"))

        payload, code = cmd_publish(vault, guard, manifest("unknown.json", [
            ("../outside/x.md", draft("x.md", b"x\n")),
            ("Wiki/unsnapped.md", draft("x.md", b"x\n"))]))
        check("an escaping or unsnapshotted manifest path is refused",
              (code, actions(payload), os.listdir(outside),
               os.path.lexists(wiki("unsnapped.md"))),
              (1, ["refused", "refused"], [], False))

        payload, code = cmd_publish(vault, guard, manifest("nodraft.json", [
            ("Wiki/fresh.md", os.path.join(scratch, "missing.md"))]))
        check("a missing draft is refused",
              (code, actions(payload), os.path.lexists(wiki("fresh.md"))),
              (1, ["refused"], False))

        topics = os.path.join(scratch, "topics.json")
        cmd_snapshot(vault, ["Topics/t.md"], topics)
        topic_manifest = manifest("topics-manifest.json", [
            ("Topics/t.md", draft("t.md", b"topic\n"))])
        payload, code = cmd_publish(vault, topics, topic_manifest)
        check("a missing target directory is refused without --create-dir",
              (code, actions(payload),
               os.path.lexists(os.path.join(vault, "Topics"))),
              (1, ["refused"], False))
        payload, code = cmd_publish(vault, topics, topic_manifest,
                                    create_dir="Topics")
        check("--create-dir creates exactly that direct child first",
              (code, actions(payload),
               os.path.isdir(os.path.join(vault, "Topics"))
               and not os.path.islink(os.path.join(vault, "Topics")),
               read(os.path.join(vault, "Topics", "t.md"))),
              (0, ["created"], True, b"topic\n"))

        partial = os.path.join(scratch, "partial.json")
        put(wiki("p2.md"), b"p2 old\n")
        put(wiki("p3.md"), b"p3 old\n")
        cmd_snapshot(vault, ["Wiki/p1.md", "Wiki/p2.md", "Wiki/p3.md"],
                     partial)
        partial_manifest = manifest("partial-manifest.json", [
            ("Wiki/p2.md", draft("p2.md", b"p2 new\n")),
            ("Wiki/p3.md", draft("p3.md", b"p3 new\n")),
            ("Wiki/p1.md", draft("p1.md", b"p1 new\n"))])
        real_link = atomic_move.link_noreplace

        def refuse_p2(source, destination):
            if (os.path.basename(destination) == "p2.md"
                    and os.path.basename(source) == STAGED_NAME):
                raise atomic_move.LinkUnavailable(
                    source, destination, OSError(errno.ENOTSUP, "injected refusal"))
            return real_link(source, destination)

        atomic_move.link_noreplace = refuse_p2
        try:
            payload, code = cmd_publish(vault, partial, partial_manifest)
        finally:
            atomic_move.link_noreplace = real_link
        failed = payload["results"][0]
        check("a partial failure reports published, failed and pending paths",
              (code, actions(payload), failed.get("error"),
               read(os.path.join(failed.get("stage_dir", ""), STAGED_NAME)),
               read(wiki("p1.md")), read(wiki("p2.md")), read(wiki("p3.md")),
               os.path.isdir(payload.get("stage_parent", ""))),
              (1, ["failed", "pending", "created"], "LinkUnavailable",
               b"p2 new\n", b"p1 new\n", b"p2 old\n", b"p3 old\n", True))
        payload, code = cmd_publish(vault, partial, partial_manifest)
        check("the same command reruns cleanly after the partial failure",
              (code, actions(payload), read(wiki("p2.md")),
               read(wiki("p3.md")), "stage_parent" in payload),
              (0, ["replaced", "replaced", "unchanged"], b"p2 new\n",
               b"p3 new\n", False))

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["verify", "--vault", vault, "--snapshots", snap])
        check("the CLI prints JSON and exits 1 for a stale snapshot",
              (code, json.loads(out.getvalue())["ok"]), (1, False))

    failed = [case for case in cases if not case[1]]
    for label, ok, got, want in failed:
        print("FAIL  %s\n        got  %r\n        want %r" % (label, got, want))
    print("%d/%d self-test cases pass" % (len(cases) - len(failed), len(cases)))
    return 1 if failed else 0


def _configure_utf8_stdio():
    """Keep Unicode paths and diagnostics readable under non-UTF-8 locales."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (OSError, ValueError):
                pass


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="publish_files.py", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--test", action="store_true",
                        help="run the built-in self-test")
    sub = parser.add_subparsers(dest="command")
    snapshot = sub.add_parser("snapshot", help="record paths before reading them")
    snapshot.add_argument("--vault", required=True)
    snapshot.add_argument("-o", "--output", metavar="OUT",
                          help="snapshot file to create or merge into")
    snapshot.add_argument("--replace", action="store_true",
                          help="replace the earlier records of these paths")
    snapshot.add_argument("paths", nargs="+", metavar="PATH")
    verify = sub.add_parser("verify", help="recheck every recorded path")
    verify.add_argument("--vault", required=True)
    verify.add_argument("--snapshots", required=True, metavar="SNAP.json")
    publish = sub.add_parser("publish", help="publish reviewed drafts")
    publish.add_argument("--vault", required=True)
    publish.add_argument("--snapshots", required=True, metavar="SNAP.json")
    publish.add_argument("--manifest", required=True, metavar="MANIFEST.json")
    publish.add_argument("--create-dir", metavar="DIR",
                         help="missing direct child of the vault to create")
    publish.add_argument("--dry-run", action="store_true",
                         help="check and plan without writing")
    return parser


def main(argv=None):
    _configure_utf8_stdio()
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.test:
        return run_self_test()
    if args.command == "snapshot":
        payload, code = cmd_snapshot(args.vault, args.paths, args.output,
                                     args.replace)
    elif args.command == "verify":
        payload, code = cmd_verify(args.vault, args.snapshots)
    elif args.command == "publish":
        payload, code = cmd_publish(args.vault, args.snapshots, args.manifest,
                                    args.create_dir, args.dry_run)
    else:
        parser.print_help()
        return 2
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
