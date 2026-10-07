"""Snapshot, verify, publish, remove and move reviewed vault files without clobbering edits.

A command line for the SAFE_WRITES.md recipe on regular files: the version a
workflow read is recorded with ``atomic_move.regular_file_snapshot``, a new
file is published with ``atomic_move.publish_new`` and a replacement with
``atomic_move.replace_expected`` against that recorded version, a removal with
``atomic_move.remove_expected`` and a move with ``atomic_move.move_noreplace``.
PATH is vault-relative (forward slashes) or absolute and must resolve inside
the vault's real path. A leaf symlink is never followed. A case alias of an
existing file is unsafe, and a Unicode normalization variant is replaced
under its on-disk spelling, so a replacement never renames the file. Manifest
paths that differ only in case or normalization are refused.

``--owned-dir DIR`` (repeatable; ``snapshot``, ``verify`` and ``publish``)
names a direct child of the vault that must be one readable real directory.
A path under it is refused when DIR is a symlink, not a directory,
unreadable, spelled differently on disk, or shares its case/Unicode identity
with another entry. An absent DIR passes; only ``--create-dir`` creates it.

  snapshot --vault VAULT [-o OUT [--replace]] [--owned-dir DIR] PATH...
      Record each path before the workflow reads it: absent, or a regular
      file's identity, digest, mode and size. ``-o`` merges into an existing
      snapshot file and keeps the earlier record of a path already there,
      failing when that path no longer matches it. ``--replace`` instead
      records the named paths afresh, before the workflow re-reads them.
  verify --vault VAULT --snapshots SNAP.json [--owned-dir DIR]
      Report each recorded path as unchanged, changed, appeared, removed or
      unsafe.
  publish --vault VAULT --snapshots SNAP.json --manifest MANIFEST.json
          [--create-dir DIR] [--owned-dir DIR] [--dry-run]
      Publish a JSON list of {"path": <vault-relative target>, "draft":
      <absolute draft path>}: new files first, then replacements. A path that
      already equals its draft is skipped, so the same command can be rerun
      after a partial failure. Any failed precheck publishes nothing; the
      first publication failure stops the run and leaves later paths pending.
      ``--create-dir`` creates a missing direct child of the vault, and
      refuses its paths when the vault holds a case or Unicode variant of
      that name.
  remove --vault VAULT --snapshots SNAP.json PATH...
      Remove each recorded file with ``atomic_move.remove_expected`` only
      while its bytes, identity and mode match the record. A path with no
      record, or one that changed, is refused, and any refusal removes
      nothing. A path that is already absent is reported and skipped.
  move --vault VAULT --snapshots SNAP.json SRC DST
      Move a recorded file that still matches its record to an unoccupied DST
      in an existing directory with ``atomic_move.move_noreplace``. A DST that
      differs from SRC only in the file name's case or Unicode normalization
      respells the same file in place; no other file may share that name's
      case/Unicode identity. Record DST with ``snapshot --replace`` before
      publishing to it.

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
import unicodedata

# Keep the sibling publication helper available when a harness imports this
# file directly by path instead of executing it as a script.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import atomic_move  # noqa: E402
from portable_names import portable_identity  # noqa: E402


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


def _listed_spelling(name, names):
    """NAME as a directory listing spells it, exactly or up to Unicode
    normalization (the exact spelling first), or ``None``."""
    if name in names:
        return name
    wanted = unicodedata.normalize("NFC", name)
    return next((n for n in names
                 if unicodedata.normalize("NFC", n) == wanted), None)


def _direct_child(value, flag):
    """VALUE as a direct child of the vault; refuse anything else."""
    name = os.path.normpath(value)
    if (os.sep in name or os.path.isabs(name)
            or name in (os.curdir, os.pardir)):
        raise InputError("%s must name a direct child of the vault, not %s"
                         % (flag, value))
    return name


def _root_owners(vault, name):
    """The vault's direct children that share NAME's case/Unicode identity."""
    wanted = portable_identity(name)
    return sorted(n for n in os.listdir(vault[1])
                  if portable_identity(n) == wanted)


def _owned_dir_error(vault, name):
    """Why NAME/ is not one readable real directory, or ``None``.

    An absent NAME/ is not an error: its paths observe as absent, and only
    ``--create-dir`` creates it.
    """
    try:
        owners = _root_owners(vault, name)
    except OSError as exc:
        return "cannot list the vault (%s)" % _describe(exc)
    if not owners:
        return None
    if owners != [name]:
        return ("%s/ has other or differently spelled owners: %s"
                % (name, ", ".join(owners)))
    path = os.path.join(vault[1], name)
    try:
        item = os.lstat(path)
        if stat.S_ISLNK(item.st_mode):
            return "%s/ is a symlink; it is not followed" % name
        if not stat.S_ISDIR(item.st_mode):
            return "%s/ is not a directory" % name
        os.listdir(path)
    except OSError as exc:
        return "%s/ is unreadable (%s)" % (name, _describe(exc))
    return None


def _owned_dir_refusal(vault, key, owned_dirs):
    """Refusal detail for KEY under an unsafe ``--owned-dir``, or ``None``."""
    if "/" not in key:
        return None
    first = key.split("/", 1)[0]
    for name in owned_dirs:
        if portable_identity(first) == portable_identity(name):
            if first != name:
                return "spell the owned directory %s/, not %s/" % (name, first)
            return _owned_dir_error(vault, name)
    return None


def observe(target):
    """``(state, token, error)`` for one path, never following a symlink."""
    try:
        item = os.lstat(target)
    except FileNotFoundError:
        return "absent", None, None
    except OSError as exc:
        return "unsafe", None, _describe(exc)
    # A case-insensitive filesystem finds the file under an alias spelling,
    # and publishing through that spelling would rename it.
    name = os.path.basename(target)
    try:
        names = os.listdir(os.path.dirname(target))
    except OSError as exc:
        return "unsafe", None, _describe(exc)
    if _listed_spelling(name, names) is None:
        actual = [n for n in names
                  if portable_identity(n) == portable_identity(name)]
        return "unsafe", None, (
            "the path exists on disk as %s; use that spelling"
            % (actual[0] if actual else "a different spelling"))
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


def cmd_snapshot(vault_arg, paths, output=None, replace=False, owned_dirs=()):
    try:
        vault = _vault(vault_arg)
        owned_dirs = [_direct_child(name, "--owned-dir") for name in owned_dirs]
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
        refusal = _owned_dir_refusal(vault, key, owned_dirs)
        if refusal:
            ok = False
            results.append({"path": key, "state": "refused", "error": refusal})
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


def cmd_verify(vault_arg, snapshots, owned_dirs=()):
    try:
        vault = _vault(vault_arg)
        records = load_snapshots(snapshots, vault)
        owned_dirs = [_direct_child(name, "--owned-dir") for name in owned_dirs]
    except InputError as exc:
        return {"ok": False, "error": str(exc)}, 1
    results = []
    for key, record in records.items():
        try:
            if vault_key(vault, key) != key:
                raise InputError("%s is not a normalized vault path" % key)
            refusal = _owned_dir_refusal(vault, key, owned_dirs)
            if refusal:
                raise InputError(refusal)
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


def _plan(vault, records, item, create_dir, new_mode, owned_dirs=()):
    """Check one manifest item without writing; return its planned action."""
    plan = {"path": item["path"]}
    try:
        key = vault_key(vault, item["path"])
    except InputError as exc:
        return _refuse(plan, str(exc))
    plan["path"] = key
    refusal = _owned_dir_refusal(vault, key, owned_dirs)
    if refusal:
        return _refuse(plan, refusal)
    if (create_dir is not None and "/" in key
            and portable_identity(key.split("/", 1)[0])
            == portable_identity(create_dir)):
        try:
            owners = _root_owners(vault, create_dir)
        except OSError as exc:
            return _refuse(plan, "cannot list the vault (%s)" % _describe(exc))
        if owners not in ([], [create_dir]):
            return _refuse(plan, "the vault holds %s, a case or Unicode "
                                 "variant of --create-dir %s"
                           % (", ".join(owners), create_dir))
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
    if record["state"] == "file":
        # Replace under the listed spelling: a normalization-insensitive
        # filesystem would otherwise store the requested spelling instead.
        try:
            listed = _listed_spelling(os.path.basename(target),
                                      os.listdir(os.path.dirname(target)))
        except OSError as exc:
            return _refuse(plan, "cannot inspect the target directory (%s)"
                           % _describe(exc))
        if listed is not None:
            target = os.path.join(os.path.dirname(target), listed)
            plan["_target"] = target

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
        twins = _root_owners(vault, os.path.basename(directory))
        if twins:
            raise atomic_move.PublicationConflict(
                "the vault now holds %s; not creating %s"
                % (", ".join(twins), os.path.basename(directory)))
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
                dry_run=False, owned_dirs=()):
    try:
        vault = _vault(vault_arg)
        records = load_snapshots(snapshots, vault)
        items = _load_manifest(manifest)
        if create_dir is not None:
            create_dir = _direct_child(create_dir, "--create-dir")
        owned_dirs = [_direct_child(name, "--owned-dir") for name in owned_dirs]
    except InputError as exc:
        return {"ok": False, "error": str(exc)}, 1

    new_mode = _new_file_mode()
    plans = [_plan(vault, records, item, create_dir, new_mode, owned_dirs)
             for item in items]
    keys = [portable_identity(plan["path"]) for plan in plans]
    for plan, key in zip(plans, keys):
        if keys.count(key) > 1:
            _refuse(plan, "listed more than once in the manifest (up to case "
                          "or Unicode normalization)")
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
                refusal = _owned_dir_refusal(vault, plan["path"], owned_dirs)
                if refusal:
                    raise atomic_move.PublicationConflict(refusal)
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


def _plan_removal(vault, records, path):
    """Check one path for ``remove`` without writing; return its plan."""
    plan = {"path": path}
    try:
        key = vault_key(vault, path)
    except InputError as exc:
        return _refuse(plan, str(exc))
    plan["path"] = key
    record = records.get(key)
    if record is None:
        return _refuse(plan, "no snapshot record; snapshot the path before "
                             "reading it")
    target = _target(vault, key)
    observed = observe(target)
    if observed[0] == "absent":
        plan.update(action="absent", detail="already absent")
        return plan
    status, detail = compare(record, observed)
    if status != "unchanged":
        return _refuse(plan, "%s: %s" % (status, detail))
    try:
        location = _stage_location(vault[1],
                                   os.path.realpath(os.path.dirname(target)))
    except OSError as exc:
        return _refuse(plan, "cannot inspect the target directory (%s)"
                       % _describe(exc))
    if location is None:
        return _refuse(plan, "LinkUnavailable: no parent on the target's "
                             "filesystem can hold the private stage")
    plan.update(action="remove", _target=target, _expected=_expected(record),
                _location=location)
    return plan


def cmd_remove(vault_arg, snapshots, paths):
    try:
        vault = _vault(vault_arg)
        records = load_snapshots(snapshots, vault)
    except InputError as exc:
        return {"ok": False, "error": str(exc)}, 1

    plans = [_plan_removal(vault, records, path) for path in paths]
    keys = [portable_identity(plan["path"]) for plan in plans]
    for plan, key in zip(plans, keys):
        if keys.count(key) > 1:
            _refuse(plan, "listed more than once (up to case or Unicode "
                          "normalization)")
    removals = [plan for plan in plans if plan["action"] == "remove"]
    for plan in removals:
        if plan["_location"] != removals[0]["_location"]:
            _refuse(plan, "LinkUnavailable: on a different filesystem from "
                          "this run's private stage; remove it separately")
    if any(plan["action"] == "refused" for plan in plans):
        for plan in plans:
            if plan["action"] == "remove":
                plan.update(action="pending",
                            detail="not attempted: another path was refused")

    stage_parent = None
    failed = False
    for plan in plans:
        if plan["action"] != "remove":
            continue
        if failed:
            plan.update(action="pending",
                        detail="not attempted after an earlier failure")
            continue
        try:
            if stage_parent is None:
                stage_parent = tempfile.mkdtemp(
                    prefix=STAGE_PREFIX, dir=plan["_location"])
            stage_dir = tempfile.mkdtemp(prefix="remove-", dir=stage_parent)
            plan["stage_dir"] = stage_dir
            removed = atomic_move.remove_expected(
                plan["_target"], plan["_expected"],
                atomic_move.regular_file_snapshot, stage_dir,
                stage_parent=stage_parent)
        except (OSError, ValueError) as exc:
            failed = True
            plan.update(action="failed", error=type(exc).__name__,
                        detail=str(exc))
            recovery = getattr(exc, "recovery_path", None)
            if recovery:
                plan["recovery_path"] = recovery
        else:
            # The stage now holds only the verified recorded version.
            shutil.rmtree(stage_dir, ignore_errors=True)
            del plan["stage_dir"]
            plan.update(action="removed" if removed else "absent",
                        detail="removed the snapshotted version" if removed
                        else "already absent")
    if stage_parent is not None:
        with contextlib.suppress(OSError):
            os.rmdir(stage_parent)

    ok = all(plan["action"] in ("removed", "absent") for plan in plans)
    payload = {"ok": ok, "results": [
        {key: value for key, value in plan.items() if not key.startswith("_")}
        for plan in plans]}
    if stage_parent is not None and os.path.lexists(stage_parent):
        payload["stage_parent"] = stage_parent
    return payload, 0 if ok else 1


def _respelling_source(record, target, dst_target):
    """Check a same-file respelling without writing.

    Returns ``(source, problem)``: the source's listed path to move, or a
    refusal detail. ``(None, None)`` means the folder already lists the
    recorded file under the destination spelling.
    """
    directory = os.path.dirname(target)
    wanted = os.path.basename(dst_target)
    try:
        names = os.listdir(directory)
    except OSError as exc:
        return None, "cannot inspect the source directory (%s)" % _describe(exc)
    owners = [n for n in names
              if portable_identity(n) == portable_identity(wanted)]
    if (owners == [wanted]
            and compare(record, observe(dst_target))[0] == "unchanged"):
        return None, None
    status, detail = compare(record, observe(target))
    if status != "unchanged":
        return None, "%s: %s" % (status, detail)
    listed = _listed_spelling(os.path.basename(target), names)
    others = sorted(n for n in owners if n != listed)
    if others:
        return None, ("the destination is occupied by %s, a different file "
                      "with the same case/Unicode identity" % ", ".join(others))
    source = os.path.join(directory, listed)
    try:
        if os.path.lexists(dst_target):
            here, there = os.lstat(source), os.lstat(dst_target)
            if (here.st_dev, here.st_ino) != (there.st_dev, there.st_ino):
                return None, "the destination is occupied"
    except OSError as exc:
        return None, "cannot inspect the destination (%s)" % _describe(exc)
    return source, None


def cmd_move(vault_arg, snapshots, source, destination):
    try:
        vault = _vault(vault_arg)
        records = load_snapshots(snapshots, vault)
    except InputError as exc:
        return {"ok": False, "error": str(exc)}, 1

    result = {"path": source, "to": destination}

    def refused(detail):
        result.update(action="refused", detail=detail)
        return {"ok": False, "results": [result]}, 1

    try:
        key = vault_key(vault, source)
        result["path"] = key
        dst_key = vault_key(vault, destination)
        result["to"] = dst_key
    except InputError as exc:
        return refused(str(exc))
    if key == dst_key:
        return refused("the destination is the source")
    respell = portable_identity(key) == portable_identity(dst_key)
    if respell and os.path.dirname(key) != os.path.dirname(dst_key):
        return refused("a respelling changes only the file name; spell the "
                       "directory as the source does")
    done = "respelled" if respell else "moved"
    record = records.get(key)
    if record is None:
        return refused("no snapshot record; snapshot the path before "
                       "reading it")
    if record["state"] != "file":
        return refused("the source is recorded as absent")
    target = _target(vault, key)
    dst_target = _target(vault, dst_key)
    if respell:
        target, problem = _respelling_source(record, target, dst_target)
        if target is None and problem is None:
            result.update(action=done, detail="already respelled; snapshot "
                          "--replace the new spelling before publishing to it")
            return {"ok": True, "results": [result]}, 0
        if problem:
            return refused(problem)
    else:
        status, detail = compare(record, observe(target))
        if (status == "removed"
                and compare(record, observe(dst_target))[0] == "unchanged"):
            result.update(action=done, detail="already moved; snapshot "
                          "--replace the destination before publishing to it")
            return {"ok": True, "results": [result]}, 0
        if status != "unchanged":
            return refused("%s: %s" % (status, detail))
        if not os.path.isdir(os.path.dirname(dst_target)):
            return refused("the destination directory %s does not exist"
                           % os.path.dirname(dst_key))
        occupant = observe(dst_target)
        if occupant[0] != "absent":
            return refused("the destination is occupied"
                           + (" (%s)" % occupant[2] if occupant[2] else ""))
    try:
        location = _stage_location(vault[1],
                                   os.path.realpath(os.path.dirname(target)))
    except OSError as exc:
        return refused("cannot inspect the source directory (%s)"
                       % _describe(exc))
    if location is None:
        return refused("LinkUnavailable: no parent on the source's "
                       "filesystem can hold the private stage")

    stage_parent = None
    try:
        stage_parent = tempfile.mkdtemp(prefix=STAGE_PREFIX, dir=location)
        atomic_move.move_noreplace(
            target, dst_target, expected=_expected(record).identity,
            stage_parent=stage_parent)
    except (OSError, ValueError) as exc:
        result.update(action="failed", error=type(exc).__name__,
                      detail=str(exc))
        recovery = getattr(exc, "recovery_paths", None)
        if recovery:
            result["recovery_paths"] = list(recovery)
    else:
        result.update(action=done, detail="%s the snapshotted version; "
                      "snapshot --replace the destination before publishing "
                      "to it" % done)
        if respell:
            try:
                kept = os.path.basename(dst_target) in os.listdir(
                    os.path.dirname(dst_target))
            except OSError:
                kept = False
            if not kept:
                result.update(action="failed", error="SpellingNotKept",
                              detail="the folder does not list the respelled "
                              "file as %s; the filesystem keeps another "
                              "spelling" % os.path.basename(dst_key))
    payload = {"ok": result["action"] == done, "results": [result]}
    if stage_parent is not None:
        with contextlib.suppress(OSError):
            os.rmdir(stage_parent)
        if os.path.lexists(stage_parent):
            payload["stage_parent"] = stage_parent
    return payload, 0 if payload["ok"] else 1


def run_self_test():
    """Exercise every command on temporary vaults."""
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

        removal = os.path.join(scratch, "removal.json")
        put(wiki("rm-keep.md"), b"keep\n")
        put(wiki("rm-edit.md"), b"read\n")
        cmd_snapshot(vault, ["Wiki/rm-keep.md", "Wiki/rm-edit.md"], removal)
        put(wiki("rm-edit.md"), b"editor save\n")
        payload, code = cmd_remove(vault, removal, [
            "Wiki/rm-keep.md", "Wiki/rm-edit.md", "Wiki/rm-unsnapped.md"])
        check("remove refuses a changed or unsnapshotted path and removes "
              "nothing",
              (code, actions(payload),
               "changed: bytes differ" in payload["results"][1]["detail"],
               read(wiki("rm-keep.md")), read(wiki("rm-edit.md")),
               stage_parents()),
              (1, ["pending", "refused", "refused"], True, b"keep\n",
               b"editor save\n", []))
        payload, code = cmd_remove(vault, removal, ["Wiki/rm-keep.md"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rerun_code = main(["remove", "--vault", vault, "--snapshots",
                               removal, "Wiki/rm-keep.md"])
        check("remove deletes the recorded version and a rerun skips it",
              (code, actions(payload), os.path.lexists(wiki("rm-keep.md")),
               stage_parents(), rerun_code,
               actions(json.loads(out.getvalue()))),
              (0, ["removed"], False, [], 0, ["absent"]))

        moves = os.path.join(scratch, "moves.json")
        put(wiki("mv-src.md"), b"moved\n", 0o600)
        put(wiki("mv-edit.md"), b"read\n")
        put(wiki("mv-taken.md"), b"occupant\n")
        cmd_snapshot(vault, ["Wiki/mv-src.md", "Wiki/mv-edit.md"], moves)
        put(wiki("mv-edit.md"), b"editor save\n")
        refusals = [cmd_move(vault, moves, src, dst) for src, dst in (
            ("Wiki/mv-edit.md", "Wiki/mv-free.md"),
            ("Wiki/mv-src.md", "Wiki/mv-taken.md"),
            ("Wiki/mv-src.md", "Gone/mv-src.md"),
            ("Wiki/mv-unsnapped.md", "Wiki/mv-free.md"))]
        check("move refuses a changed source and an occupied or missing "
              "destination",
              ([(code, actions(payload)) for payload, code in refusals],
               "changed: bytes differ"
               in refusals[0][0]["results"][0]["detail"],
               "occupied" in refusals[1][0]["results"][0]["detail"],
               os.path.lexists(wiki("mv-free.md")), read(wiki("mv-src.md")),
               read(wiki("mv-edit.md")), read(wiki("mv-taken.md")),
               stage_parents()),
              ([(1, ["refused"])] * 4, True, True, False, b"moved\n",
               b"editor save\n", b"occupant\n", []))
        identity = atomic_move.file_identity(wiki("mv-src.md"))
        payload, code = cmd_move(vault, moves, "Wiki/mv-src.md",
                                 "Wiki/mv-dst.md")
        check("move publishes the recorded inode at a free destination",
              (code, actions(payload), os.path.lexists(wiki("mv-src.md")),
               read(wiki("mv-dst.md")),
               atomic_move.file_identity(wiki("mv-dst.md")) == identity,
               stat.S_IMODE(os.stat(wiki("mv-dst.md")).st_mode),
               stage_parents()),
              (0, ["moved"], False, b"moved\n", True, 0o600, []))
        payload, code = cmd_move(vault, moves, "Wiki/mv-src.md",
                                 "Wiki/mv-dst.md")
        check("a rerun of a finished move reports it moved",
              (code, actions(payload), read(wiki("mv-dst.md"))),
              (0, ["moved"], b"moved\n"))

        def spellings(name):
            return sorted(n for n in os.listdir(os.path.join(vault, "Wiki"))
                          if portable_identity(n) == portable_identity(name))

        respells = os.path.join(scratch, "respells.json")
        put(wiki("Resp.md"), b"respell\n", 0o600)
        put(wiki("Resp-edit.md"), b"read\n")
        cmd_snapshot(vault, ["Wiki/Resp.md", "Wiki/Resp-edit.md"], respells)
        put(wiki("Resp-edit.md"), b"editor save\n")
        refusals = [cmd_move(vault, respells, src, dst) for src, dst in (
            ("Wiki/Resp-edit.md", "Wiki/resp-edit.md"),
            ("Wiki/Resp.md", "wiki/resp.md"))]
        check("a respelling refuses a changed source or a respelled directory",
              ([(code, actions(payload)) for payload, code in refusals],
               "changed: bytes differ"
               in refusals[0][0]["results"][0]["detail"],
               "only the file name" in refusals[1][0]["results"][0]["detail"],
               spellings("resp-edit.md"), spellings("resp.md"),
               read(wiki("Resp-edit.md"))),
              ([(1, ["refused"])] * 2, True, True, ["Resp-edit.md"],
               ["Resp.md"], b"editor save\n"))
        identity = atomic_move.file_identity(wiki("Resp.md"))
        payload, code = cmd_move(vault, respells, "Wiki/Resp.md",
                                 "Wiki/resp.md")
        check("a case-only respelling keeps the recorded inode, bytes and mode",
              (code, actions(payload), spellings("resp.md"),
               read(wiki("resp.md")),
               atomic_move.file_identity(wiki("resp.md")) == identity,
               stat.S_IMODE(os.stat(wiki("resp.md")).st_mode),
               stage_parents(),
               [n for n in os.listdir(os.path.join(vault, "Wiki"))
                if n.startswith(".")]),
              (0, ["respelled"], ["resp.md"], b"respell\n", True, 0o600, [],
               []))
        payload, code = cmd_move(vault, respells, "Wiki/Resp.md",
                                 "Wiki/resp.md")
        check("a rerun of a finished respelling reports it respelled",
              (code, actions(payload),
               "already respelled" in payload["results"][0]["detail"],
               spellings("resp.md")),
              (0, ["respelled"], True, ["resp.md"]))

        put(wiki("Café resp.md"), b"nfd\n")
        cmd_snapshot(vault, ["Wiki/Café resp.md"], respells)
        payload, code = cmd_move(vault, respells, "Wiki/Café resp.md",
                                 "Wiki/Café resp.md")
        check("a Unicode-only respelling stores the requested spelling",
              (code, actions(payload), spellings("Café resp.md"),
               read(wiki("Café resp.md"))),
              (0, ["respelled"], ["Café resp.md"], b"nfd\n"))

        put(wiki("Twin.md"), b"twin\n")
        if not os.path.lexists(wiki("tWIN.md")):
            put(wiki("twin.md"), b"other twin\n")
            twins = os.path.join(scratch, "twins.json")
            cmd_snapshot(vault, ["Wiki/Twin.md"], twins)
            payload, code = cmd_move(vault, twins, "Wiki/Twin.md",
                                     "Wiki/twin.md")
            check("a respelling never takes a distinct case-variant file",
                  (code, actions(payload),
                   "occupied by twin.md" in payload["results"][0]["detail"],
                   read(wiki("Twin.md")), read(wiki("twin.md"))),
                  (1, ["refused"], True, b"twin\n", b"other twin\n"))
        else:
            check("distinct case-variant files skipped on a case-insensitive "
                  "filesystem", True, True)

        os.makedirs(os.path.join(vault, "Other"))
        os.symlink("Other", os.path.join(vault, "Reviews"))
        owned = os.path.join(scratch, "owned-snapshots.json")
        payload, code = cmd_snapshot(vault, ["Reviews/log.md"], owned,
                                     owned_dirs=["Reviews"])
        check("--owned-dir refuses a symlinked directory and stores nothing",
              (code, payload["snapshots"][0]["state"],
               "symlink" in payload["snapshots"][0]["error"],
               load_snapshots(owned, _vault(vault))),
              (1, "refused", True, {}))
        cmd_snapshot(vault, ["Reviews/log.md"], owned)
        owned_manifest = manifest("owned-manifest.json", [
            ("Reviews/log.md", draft("log.md", b"log\n"))])
        payload, code = cmd_publish(vault, owned, owned_manifest,
                                    owned_dirs=["Reviews"])
        verified = cmd_verify(vault, owned, owned_dirs=["Reviews"])
        check("publish and verify refuse a path under a symlinked owned "
              "directory",
              (code, actions(payload), verified[1],
               verified[0]["results"][0]["status"],
               os.listdir(os.path.join(vault, "Other"))),
              (1, ["refused"], 1, "unsafe", []))

        os.unlink(os.path.join(vault, "Reviews"))
        os.makedirs(os.path.join(vault, "reviews"))
        cmd_snapshot(vault, ["Reviews/log.md"], owned, replace=True)
        twin_runs = [cmd_publish(vault, owned, owned_manifest,
                                 create_dir="Reviews", owned_dirs=extra)
                     for extra in ([], ["Reviews"])]
        check("--create-dir never adds a case variant of an existing folder",
              ([(code, actions(payload)) for payload, code in twin_runs],
               "case or Unicode variant"
               in twin_runs[0][0]["results"][0]["detail"],
               "differently spelled" in twin_runs[1][0]["results"][0]["detail"],
               sorted(n for n in os.listdir(vault)
                      if portable_identity(n) == "reviews"),
               os.listdir(os.path.join(vault, "reviews"))),
              ([(1, ["refused"])] * 2, True, True, ["reviews"], []))

        os.rmdir(os.path.join(vault, "reviews"))
        payload, code = cmd_publish(vault, owned, owned_manifest,
                                    create_dir="Reviews",
                                    owned_dirs=["Reviews"])
        refreshed = cmd_snapshot(vault, ["Reviews/log.md"], owned,
                                 replace=True, owned_dirs=["Reviews"])
        check("a real owned directory is created and used normally",
              (code, actions(payload),
               read(os.path.join(vault, "Reviews", "log.md")), refreshed[1],
               cmd_verify(vault, owned, owned_dirs=["Reviews"])[1]),
              (0, ["created"], b"log\n", 0, 0))

        dups = os.path.join(scratch, "dups.json")
        dup_paths = ["Wiki/Dup.md", "Wiki/dup.md",
                     "Wiki/Caf\u00e9.md", "Wiki/Cafe\u0301.md"]
        cmd_snapshot(vault, dup_paths, dups)
        dup_manifest = manifest("dups-manifest.json", [
            (path, draft("dup%d.md" % index, b"dup\n"))
            for index, path in enumerate(dup_paths)])
        dry_payload, dry_code = cmd_publish(vault, dups, dup_manifest,
                                            dry_run=True)
        payload, code = cmd_publish(vault, dups, dup_manifest)
        dup_keys = {portable_identity(os.path.basename(p)) for p in dup_paths}
        check("paths equal up to case or normalization are all refused",
              (dry_code, actions(dry_payload), code, actions(payload),
               "up to case" in payload["results"][0].get("detail", ""),
               [n for n in os.listdir(os.path.join(vault, "Wiki"))
                if portable_identity(n) in dup_keys], stage_parents()),
              (1, ["refused"] * 4, 1, ["refused"] * 4, True, [], []))

        put(wiki("Case.md"), b"case\n")
        if os.path.lexists(wiki("cASE.md")):
            alias_snap = os.path.join(scratch, "alias.json")
            payload, code = cmd_snapshot(vault, ["Wiki/cASE.md"], alias_snap)
            alias_record = payload["snapshots"][0]
            check("a case alias of an existing file is unsafe and not stored",
                  (code, alias_record["state"],
                   "on disk as Case.md" in alias_record.get("error", ""),
                   load_snapshots(alias_snap, _vault(vault))),
                  (1, "unsafe", True, {}))
            cmd_snapshot(vault, ["Wiki/Case.md"], alias_snap)
            with open(alias_snap, encoding="utf-8") as fh:
                forged = json.load(fh)
            forged["snapshots"][0]["path"] = "Wiki/cASE.md"
            with open(alias_snap, "w", encoding="utf-8") as fh:
                json.dump(forged, fh)
            payload, code = cmd_publish(vault, alias_snap, manifest(
                "alias-manifest.json",
                [("Wiki/cASE.md", draft("alias.md", b"ours\n"))]))
            verify_status = cmd_verify(vault, alias_snap)[0]["results"][0]
            check("publishing through a case alias is refused, not a rename",
                  (code, actions(payload), verify_status["status"],
                   "Case.md" in os.listdir(os.path.join(vault, "Wiki")),
                   "cASE.md" in os.listdir(os.path.join(vault, "Wiki")),
                   read(wiki("Case.md"))),
                  (1, ["refused"], "unsafe", True, False, b"case\n"))
        else:
            check("case-alias regressions skipped on a case-sensitive "
                  "filesystem", True, True)
            check("case-alias publication skipped on a case-sensitive "
                  "filesystem", True, True)

        put(wiki("Caf\u00e9 note.md"), b"nfc\n")
        if os.path.lexists(wiki("Cafe\u0301 note.md")):
            put(wiki("Nai\u0308ve note.md"), b"nfd\n")

            def notes():
                return sorted(n for n in os.listdir(os.path.join(vault, "Wiki"))
                              if n.endswith(" note.md"))

            stored_names = notes()
            nfd_snap = os.path.join(scratch, "nfd.json")
            payload, code = cmd_snapshot(
                vault, ["Wiki/Cafe\u0301 note.md", "Wiki/Na\u00efve note.md"],
                nfd_snap)
            published, pub_code = cmd_publish(vault, nfd_snap, manifest(
                "nfd-manifest.json",
                [("Wiki/Cafe\u0301 note.md", draft("nfd.md", b"cafe new\n")),
                 ("Wiki/Na\u00efve note.md", draft("nfc.md", b"naive new\n"))]))
            check("a normalization spelling of an existing file is that file "
                  "and is replaced under its on-disk spelling",
                  (code, [r["state"] for r in payload["snapshots"]], pub_code,
                   actions(published), notes() == stored_names,
                   read(wiki("Caf\u00e9 note.md")),
                   read(wiki("Na\u00efve note.md"))),
                  (0, ["file", "file"], 0, ["replaced", "replaced"], True,
                   b"cafe new\n", b"naive new\n"))
        else:
            check("normalization-alias regression skipped on a "
                  "normalization-sensitive filesystem", True, True)

        check("the listed spelling prefers an exact name to a normalization "
              "variant",
              [_listed_spelling(name, names) for name, names in (
                  ("Cafe\u0301.md", ["Caf\u00e9.md", "Cafe\u0301.md"]),
                  ("Cafe\u0301.md", ["a.md", "Caf\u00e9.md"]),
                  ("Caf\u00e9.md", ["Cafe\u0301.md"]),
                  ("cafe.md", ["Cafe.md"]))],
              ["Cafe\u0301.md", "Caf\u00e9.md", "Cafe\u0301.md", None])

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
    for command in (snapshot, verify, publish):
        command.add_argument(
            "--owned-dir", action="append", default=[], metavar="DIR",
            help="direct child of the vault that must be one readable real "
                 "directory (repeatable)")
    remove = sub.add_parser("remove", help="remove snapshotted files")
    remove.add_argument("--vault", required=True)
    remove.add_argument("--snapshots", required=True, metavar="SNAP.json")
    remove.add_argument("paths", nargs="+", metavar="PATH")
    move = sub.add_parser(
        "move", help="move a snapshotted file to a free path, or respell "
        "its name in case or Unicode normalization")
    move.add_argument("--vault", required=True)
    move.add_argument("--snapshots", required=True, metavar="SNAP.json")
    move.add_argument("source", metavar="SRC")
    move.add_argument("destination", metavar="DST")
    return parser


def main(argv=None):
    _configure_utf8_stdio()
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.test:
        return run_self_test()
    if args.command == "snapshot":
        payload, code = cmd_snapshot(args.vault, args.paths, args.output,
                                     args.replace, args.owned_dir)
    elif args.command == "verify":
        payload, code = cmd_verify(args.vault, args.snapshots, args.owned_dir)
    elif args.command == "publish":
        payload, code = cmd_publish(args.vault, args.snapshots, args.manifest,
                                    args.create_dir, args.dry_run,
                                    args.owned_dir)
    elif args.command == "remove":
        payload, code = cmd_remove(args.vault, args.snapshots, args.paths)
    elif args.command == "move":
        payload, code = cmd_move(args.vault, args.snapshots, args.source,
                                 args.destination)
    else:
        parser.print_help()
        return 2
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
