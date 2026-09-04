"""Strict, standard-library readers for the figure extractor's sidecars.

The batch extractor, explicit-coordinate cropper and source renamer share these
formats. Malformed or conflicting records are errors, never an empty ownership
map. Writers carry the exact version they parsed into guarded publication, so
concurrent manifest/review updates are conflicts rather than lost updates.
Run ``python3 figure_state.py --test`` for the format/rename regressions.
"""
import argparse
import hashlib
import errno
import os
import re
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

import atomic_move


MANIFEST_FILE = ".figure-manifest.tsv"
REVIEW_FILE = ".figure-review.txt"


class SidecarConflict(FileExistsError):
    """A sidecar no longer matches the version a caller read and edited."""

    def __init__(self, *args, recovery_path=None, keep_stage=False):
        super().__init__(*args)
        self.recovery_path = recovery_path
        self.keep_stage = keep_stage


_ABSENT_SNAPSHOT = (False, None, None, None, None)


def figure_identity(name):
    """Portable identity without changing a sidecar's original spelling."""
    return unicodedata.normalize("NFC", name).casefold()


def manifest_key(manifest, filename):
    """Find an existing record's original key; ambiguous ownership is an error."""
    identity = figure_identity(filename)
    keys = [key for key in manifest if figure_identity(key) == identity]
    if len(keys) > 1:
        raise ValueError("duplicate/ambiguous ownership for %r" % filename)
    return keys[0] if keys else None


def file_digest(path):
    """Hash a crop without loading the whole rendered image into memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fragment(value):
    return bool(value and value.strip() == value and not any(
        c in value for c in ("/", "\\", "\x00", "\r", "\n", "\t")))


def _records(text, kind):
    """Yield (line index, key, value, replacement span) without losing prose."""
    if kind not in ("manifest", "review"):
        raise ValueError("unknown figure sidecar kind: %s" % kind)
    seen = {}
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        raw = line.rstrip("\r\n")
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if kind == "manifest":
            fields = raw.split("\t")
            if len(fields) != 2:
                raise ValueError("manifest line %d: expected filename<TAB>sha256" % number)
            key, value = fields
            if not _fragment(key) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
                raise ValueError("manifest line %d: invalid filename or SHA-256" % number)
            identity = figure_identity(key)
            if identity in seen:
                raise ValueError("manifest line %d: duplicate/ambiguous filename %r" % (number, key))
            seen[identity] = key
            yield number - 1, key, value.lower(), (0, len(key))
        else:
            # Native rows have an optional third note column. Also preserve
            # the documented hand-written STEM:FIG spelling and comments.
            if "\t" in raw:
                fields = raw.split("\t", 2)
                key, value = fields[:2]
            else:
                key, sep, value = raw.rpartition(":")
                if not sep:
                    raise ValueError("review line %d: expected stem<TAB>label or STEM:FIG" % number)
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
            if not _fragment(key) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", value):
                raise ValueError("review line %d: invalid stem or figure label" % number)
            yield number - 1, key, value, (0, len(key))


def parse_manifest(text):
    return {key: digest for _i, key, digest, _span in _records(text, "manifest")}


def parse_reviewed(text):
    return {(key, label) for _i, key, label, _span in _records(text, "review")}


def _snapshot_identity(item):
    return item.st_dev, item.st_ino


def _stable_sidecar_bytes(path):
    """Return exact bytes plus identity/mode, rejecting a moving read target."""
    try:
        before = os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        if os.path.lexists(path):
            raise ValueError("%s is a dangling sidecar symlink" % path)
        return b"", _ABSENT_SNAPSHOT
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("%s is not a regular sidecar file" % path)
    with open(path, "rb") as fh:
        opened_before = os.fstat(fh.fileno())
        body = fh.read()
        opened_after = os.fstat(fh.fileno())
    try:
        after = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise SidecarConflict(
            errno.EEXIST, "%s changed while it was read" % path, path) from exc
    stable = lambda item: (
        item.st_dev, item.st_ino, item.st_size,
        getattr(item, "st_mtime_ns", int(item.st_mtime * 1e9)),
        getattr(item, "st_ctime_ns", int(item.st_ctime * 1e9)),
    )
    identity = lambda item: (
        item.st_dev, item.st_ino, stat.S_IFMT(item.st_mode))
    # Native Windows can project stable permission and timestamp metadata
    # differently through path stat and handle stat. Compare each API with
    # itself across the read, then bind the two views by portable identity.
    if not (stable(before) == stable(after)
            and stable(opened_before) == stable(opened_after)
            and identity(before) == identity(opened_before)
            and identity(after) == identity(opened_after)):
        raise SidecarConflict(
            errno.EEXIST, "%s changed while it was read" % path, path)
    snapshot = (
        True,
        _snapshot_identity(after),
        hashlib.sha256(body).hexdigest(),
        stat.S_IMODE(after.st_mode),
        len(body),
    )
    return body, snapshot


def read_sidecar(path):
    """Return exact UTF-8 text and a snapshot suitable for conditional write."""
    body, snapshot = _stable_sidecar_bytes(path)
    return body.decode("utf-8"), snapshot


def read_manifest_snapshot(path):
    """Read strict ownership records and return the exact version consumed."""
    text, snapshot = read_sidecar(path)
    return parse_manifest(text), snapshot


def read_manifest(path):
    """Read a manifest strictly; only a missing file means no prior record."""
    return read_manifest_snapshot(path)[0]


def rewrite_sidecar(text, replacements, kind):
    """Rename first-column identities while retaining comments and line endings.

    Destination records belonging to a different original identity are a
    collision even if their digests match: identical bytes are not ownership.
    """
    rows = list(_records(text, kind))
    mapping = {}
    for old, new in replacements.items():
        folded = figure_identity(old)
        if folded in mapping and mapping[folded] != new:
            raise ValueError("ambiguous sidecar rename for %r" % old)
        mapping[folded] = new
    lines = text.splitlines(keepends=True)
    destinations = {}
    for i, key, value, (start, end) in rows:
        new = mapping.get(figure_identity(key), key)
        dest = (figure_identity(new), value) if kind == "review" else figure_identity(new)
        owner = figure_identity(key)
        if dest in destinations and destinations[dest] != owner:
            raise ValueError("%s rename collides at %r" % (kind, new))
        destinations[dest] = owner
        lines[i] = lines[i][:start] + new + lines[i][end:]
    result = "".join(lines)
    list(_records(result, kind))       # validate the names being written too
    return result


def check_manifest_writable(path):
    """Preflight a sidecar; atomic replacement must respect a read-only file."""
    if os.path.islink(path):
        raise ValueError("%s is a sidecar symlink; refusing to replace it" % path)
    if os.path.exists(path):
        mode = os.stat(path).st_mode
        if not stat.S_ISREG(mode):
            raise ValueError("%s is not a regular sidecar file" % path)
        if not mode & 0o222 or not os.access(path, os.W_OK):
            raise ValueError("%s is a read-only sidecar; refusing to replace it" % path)


def _publication_snapshot(path):
    """Adapt sidecar validation failures to the shared publisher's contract."""
    try:
        return _stable_sidecar_bytes(path)[1]
    except ValueError as exc:
        raise OSError(errno.EINVAL, str(exc), path) from exc


def _publish_sidecar(staged, path, expected):
    """Publish with the shared exact-snapshot and recovery protocol."""
    stage_dir = os.path.dirname(staged)
    stage_parent = os.path.dirname(stage_dir)
    try:
        if expected[0]:
            return atomic_move.replace_expected(
                staged, path, expected, _publication_snapshot,
                stage_dir, stage_parent=stage_parent,
                recovery_prefix=".figure-state-recovery-",
            )
        return atomic_move.publish_new(
            staged, path, _publication_snapshot,
            stage_parent, recovery_prefix=".figure-state-recovery-",
        )
    except atomic_move.LinkUnavailable:
        # This is a filesystem capability failure, not a stale sidecar or a
        # competing writer. Let callers report the distinct diagnosis; the
        # outer writer attaches and retains the complete sidecar stage.
        raise
    except OSError as exc:
        recovery_path = getattr(exc, "recovery_path", None)
        keep_stage = bool(getattr(exc, "keep_stage", False))
        detail = getattr(exc, "strerror", None) or str(exc)
        raise SidecarConflict(
            errno.EEXIST, detail, path,
            recovery_path=recovery_path,
            keep_stage=keep_stage,
        ) from exc


def _write_sidecar(path, body, expected=None):
    """Conditionally publish one validated sidecar, preserving its mode.

    Stage beside the destination directory, not inside the flat image folder.
    Missing files are created exclusively. Existing files are displaced and
    revalidated against the exact snapshot their caller parsed; no operation
    blindly replaces the public pathname. A killed process cannot leave
    unfinished metadata among the files consumers list.
    """
    check_manifest_writable(path)
    if expected is None:
        _current, expected = read_sidecar(path)
    mode = expected[3] if expected[0] else None
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    # Resolve the directory for staging only. A symlinked Images folder can
    # point at another filesystem, where its logical parent would make the
    # final replace cross-device and therefore non-atomic.
    directory = os.path.realpath(directory)
    stage_parent = os.path.dirname(directory)
    stage_dir = tempfile.mkdtemp(prefix=".figure-state-stage-",
                                 dir=stage_parent)
    keep_stage = False
    try:
        temporary = os.path.join(stage_dir, os.path.basename(path))
        with open(temporary, "w", encoding="utf-8", newline="") as fh:
            fh.write(body)
            if mode is not None:
                atomic_move.set_private_mode(fh, temporary, mode)
        try:
            return _publish_sidecar(temporary, path, expected)
        except BaseException as exc:
            # Every exception after the complete sidecar exists retains that
            # recoverable draft. A more specific recovery_path may name a
            # displaced predecessor, so expose the draft as staging_path too.
            keep_stage = True
            try:
                exc.keep_stage = True
                exc.staging_path = stage_dir
                if not getattr(exc, "recovery_path", None):
                    exc.recovery_path = stage_dir
            except (AttributeError, TypeError):
                pass
            raise
    finally:
        if not keep_stage:
            shutil.rmtree(stage_dir, ignore_errors=True)


def write_manifest(path, manifest, header="", expected=None):
    """Atomically write valid ownership records, preserving existing modes."""
    body = header + "".join("%s\t%s\n" % (key, manifest[key]) for key in sorted(manifest))
    parse_manifest(body)
    return _write_sidecar(path, body, expected=expected)


def write_review(path, body, expected=None):
    """Atomically write a complete, valid review ledger."""
    parse_reviewed(body)
    return _write_sidecar(path, body, expected=expected)


def self_test():
    import io
    import unittest
    from unittest import mock

    class StateTests(unittest.TestCase):
        def test_roundtrip_and_preservation(self):
            text = "# keep this\r\nOld_fig_1.png\t" + "a" * 64 + "\r\nOther_fig_2.png\t" + "b" * 64 + "\r\n"
            updated = rewrite_sidecar(text, {"Old_fig_1.png": "New_fig_1.png"}, "manifest")
            self.assertEqual(updated, text.replace("Old_fig_1.png", "New_fig_1.png"))
            self.assertEqual(parse_manifest(updated)["Other_fig_2.png"], "b" * 64)

        def test_review_formats(self):
            text = "# manual marks\nOld\t1\tchecked yesterday\nOld:2 # retained\nOther\t3\n"
            updated = rewrite_sidecar(text, {"Old": "New"}, "review")
            self.assertEqual(updated, text.replace("Old", "New"))
            self.assertEqual(parse_reviewed(updated), {("New", "1"), ("New", "2"), ("Other", "3")})
            with tempfile.TemporaryDirectory() as directory:
                images = os.path.join(directory, "Images")
                path = os.path.join(images, REVIEW_FILE)
                write_review(path, text)
                before = open(path, "rb").read()
                interrupted = None
                with mock.patch.dict(globals(), {
                        "_publish_sidecar": mock.Mock(
                            side_effect=OSError("interrupted"))}):
                    with self.assertRaises(OSError) as caught:
                        write_review(path, text + "New\t4\n")
                    interrupted = caught.exception
                self.assertEqual(open(path, "rb").read(), before)
                self.assertTrue(os.path.isfile(os.path.join(
                    interrupted.staging_path, REVIEW_FILE)))
                shutil.rmtree(interrupted.staging_path)

        def test_conflicts_and_malformed_rows(self):
            for text in ("broken", "A.png\tbad\n", "A.png\t" + "a" * 64 + "\na.png\t" + "b" * 64):
                with self.assertRaises(ValueError):
                    parse_manifest(text)
            text = "A.png\t" + "a" * 64 + "\nB.png\t" + "b" * 64 + "\n"
            with self.assertRaises(ValueError):
                rewrite_sidecar(text, {"A.png": "B.png"}, "manifest")
            with self.assertRaises(ValueError):
                rewrite_sidecar("A\t1\nB\t1\n", {"A": "B"}, "review")

        def test_equivalent_identity_preserves_original_key(self):
            original = unicodedata.normalize("NFD", "García_Study_2025_fig_1.png")
            manifest = {original: "a" * 64, "Other_fig_2.png": "b" * 64}
            key = manifest_key(manifest, "GARCÍA_STUDY_2025_FIG_1.PNG")
            self.assertEqual(key, original)
            manifest[key] = "c" * 64
            self.assertEqual(set(manifest), {original, "Other_fig_2.png"})
            self.assertEqual(manifest["Other_fig_2.png"], "b" * 64)
            self.assertIsNone(manifest_key(manifest, "Missing_fig_1.png"))
            with self.assertRaises(ValueError):
                manifest_key({"Straße.png": "a" * 64, "STRASSE.png": "b" * 64}, "strasse.png")
            with self.assertRaises(ValueError):
                parse_manifest("Straße.png\t" + "a" * 64 + "\nSTRASSE.png\t" + "b" * 64)

        def test_stable_read_tolerates_path_handle_metadata_projection(self):
            with tempfile.TemporaryDirectory() as directory:
                path = os.path.join(directory, MANIFEST_FILE)
                content = b"A_fig_1.png\t" + b"a" * 64 + b"\n"
                with open(path, "wb") as fh:
                    fh.write(content)
                real_fstat = os.fstat

                class HandleStat:
                    def __init__(self, item, ctime_delta=100, ino_delta=0):
                        self.item = item
                        self.ctime_delta = ctime_delta
                        self.ino_delta = ino_delta

                    def __getattr__(self, name):
                        if name == "st_ctime_ns":
                            return getattr(self.item, name) + self.ctime_delta
                        if name == "st_mode":
                            return stat.S_IFMT(self.item.st_mode) | 0o444
                        if name == "st_ino":
                            return self.item.st_ino + self.ino_delta
                        return getattr(self.item, name)

                def projected_fstat(descriptor):
                    return HandleStat(real_fstat(descriptor))

                with mock.patch.object(os, "fstat",
                                       side_effect=projected_fstat):
                    body, snapshot = _stable_sidecar_bytes(path)
                self.assertEqual(body, content)
                self.assertEqual(snapshot[2], hashlib.sha256(content).hexdigest())

                calls = {"count": 0}

                def changing_fstat(descriptor):
                    calls["count"] += 1
                    return HandleStat(real_fstat(descriptor),
                                      ctime_delta=calls["count"] * 100)

                with mock.patch.object(os, "fstat",
                                       side_effect=changing_fstat):
                    with self.assertRaisesRegex(
                            SidecarConflict, "changed while it was read"):
                        _stable_sidecar_bytes(path)

                def mismatched_fstat(descriptor):
                    return HandleStat(real_fstat(descriptor), ino_delta=1)

                with mock.patch.object(os, "fstat",
                                       side_effect=mismatched_fstat):
                    with self.assertRaisesRegex(
                            SidecarConflict, "changed while it was read"):
                        _stable_sidecar_bytes(path)

        def test_atomic_write_and_bad_input(self):
            with tempfile.TemporaryDirectory() as directory:
                real_root = os.path.join(directory, "real")
                real_images = os.path.join(real_root, "Images")
                os.makedirs(real_images)
                path = os.path.join(real_images, MANIFEST_FILE)
                stage_parents = []
                real_mkdtemp = tempfile.mkdtemp

                def tracked_mkdtemp(*args, **kwargs):
                    if kwargs.get("prefix") == ".figure-state-stage-":
                        stage_parents.append(kwargs.get("dir"))
                    return real_mkdtemp(*args, **kwargs)

                with mock.patch.object(tempfile, "mkdtemp",
                                       side_effect=tracked_mkdtemp):
                    write_manifest(path, {"A_fig_1.png": "a" * 64})
                self.assertEqual(stage_parents, [os.path.realpath(real_root)])
                self.assertFalse(any(name.startswith(".figure-state-stage-")
                                     for name in os.listdir(real_root)))
                self.assertTrue(os.path.isfile(os.path.join(real_images,
                                                            MANIFEST_FILE)))
                before = open(path, "rb").read()
                with mock.patch.dict(globals(), {
                        "_publish_sidecar": mock.Mock(
                            side_effect=OSError("blocked publication"))}):
                    with self.assertRaises(OSError) as caught:
                        write_manifest(path, {"B_fig_1.png": "b" * 64})
                self.assertEqual(open(path, "rb").read(), before)
                self.assertTrue(os.path.isfile(os.path.join(
                    caught.exception.staging_path, MANIFEST_FILE)))
                shutil.rmtree(caught.exception.staging_path)

                no_link = os.path.join(real_images, "no-link.tsv")

                def refuse_link(source, target, *args, **kwargs):
                    raise atomic_move.LinkUnavailable(
                        source, target,
                        OSError(errno.ENOTSUP,
                                "injected filesystem has no hard links"))

                with mock.patch.object(atomic_move, "publish_new",
                                       side_effect=refuse_link):
                    with self.assertRaises(atomic_move.LinkUnavailable) as caught:
                        write_manifest(no_link, {"C_fig_1.png": "c" * 64})
                self.assertEqual(caught.exception.recovery_path,
                                 caught.exception.staging_path)
                self.assertTrue(os.path.isfile(os.path.join(
                    caught.exception.staging_path,
                    os.path.basename(no_link))))
                shutil.rmtree(caught.exception.staging_path)
                with self.assertRaises(ValueError):
                    write_manifest(path, {"A_fig_1.png": "bad"})
                self.assertEqual(open(path, "rb").read(), before)
                self.assertEqual(read_manifest(path), {"A_fig_1.png": "a" * 64})
                self.assertEqual(read_manifest(os.path.join(real_images, "absent")), {})

                # A directory symlink can point to another volume. If this
                # platform permits creating one, prove staging follows the
                # resolved destination rather than its logical parent. Windows
                # without developer mode commonly denies this operation; the
                # ordinary-path assertions above still cover outside-folder
                # staging and cleanup there.
                logical_root = os.path.join(directory, "logical")
                logical_images = os.path.join(logical_root, "Images")
                os.makedirs(logical_root)
                try:
                    os.symlink(real_images, logical_images)
                except (OSError, NotImplementedError):
                    logical_images = None
                if logical_images is not None:
                    stage_parents[:] = []
                    linked_path = os.path.join(logical_images, MANIFEST_FILE)
                    with mock.patch.object(tempfile, "mkdtemp",
                                           side_effect=tracked_mkdtemp):
                        write_manifest(linked_path, {"A_fig_1.png": "a" * 64})
                    self.assertEqual(stage_parents, [os.path.realpath(real_root)])
                    self.assertTrue(os.path.isfile(os.path.join(
                        real_images, MANIFEST_FILE)))

        def test_stale_snapshot_and_late_new_occupant_are_preserved(self):
            with tempfile.TemporaryDirectory() as directory:
                path = os.path.join(directory, MANIFEST_FILE)
                write_manifest(path, {"A_fig_1.png": "a" * 64})
                _manifest, expected = read_manifest_snapshot(path)
                late = b"B_fig_1.png\t" + b"b" * 64 + b"\n"
                with open(path, "wb") as fh:
                    fh.write(late)
                with self.assertRaises(SidecarConflict):
                    write_manifest(path, {"C_fig_1.png": "c" * 64},
                                   expected=expected)
                self.assertEqual(open(path, "rb").read(), late)

                new_path = os.path.join(directory, "new.tsv")
                _empty, absent = read_sidecar(new_path)
                with open(new_path, "wb") as fh:
                    fh.write(late)
                with self.assertRaises(SidecarConflict):
                    write_manifest(new_path, {"C_fig_1.png": "c" * 64},
                                   expected=absent)
                self.assertEqual(open(new_path, "rb").read(), late)

        def test_publish_races_restore_or_recover_every_occupant(self):
            with tempfile.TemporaryDirectory() as directory:
                images = os.path.join(directory, "Images")
                os.makedirs(images)
                path = os.path.join(images, MANIFEST_FILE)
                write_manifest(path, {"A_fig_1.png": "a" * 64})
                _manifest, expected = read_manifest_snapshot(path)
                foreign = b"B_fig_1.png\t" + b"b" * 64 + b"\n"
                real_move = atomic_move.move_noreplace
                injected = []

                def replace_before_displacement(src, dst, expected=None,
                                                **kwargs):
                    if src == path and not injected:
                        intruder = path + ".intruder"
                        with open(intruder, "wb") as fh:
                            fh.write(foreign)
                        os.replace(intruder, path)
                        injected.append(True)
                    return real_move(src, dst, expected=expected, **kwargs)

                with mock.patch.object(atomic_move, "move_noreplace",
                                       side_effect=replace_before_displacement):
                    with self.assertRaisesRegex(
                            SidecarConflict, "different occupant"):
                        write_manifest(path, {"C_fig_1.png": "c" * 64},
                                       expected=expected)
                self.assertEqual(open(path, "rb").read(), foreign)

                # A writer arriving after the verified predecessor was moved
                # keeps the public name. The predecessor is retained outside
                # Images and its recovery path is named by the exception.
                _manifest, expected = read_manifest_snapshot(path)
                competing = b"D_fig_1.png\t" + b"d" * 64 + b"\n"
                real_link = os.link
                injected[:] = []

                def occupy_before_publish(src, dst, *args, **kwargs):
                    if (dst == path and os.path.basename(src) == MANIFEST_FILE
                            and not injected):
                        with open(path, "wb") as fh:
                            fh.write(competing)
                        injected.append(True)
                    return real_link(src, dst, *args, **kwargs)

                with mock.patch.object(os, "link",
                                       side_effect=occupy_before_publish):
                    with self.assertRaisesRegex(
                            SidecarConflict, "preserved at") as caught:
                        write_manifest(path, {"E_fig_1.png": "e" * 64},
                                       expected=expected)
                self.assertEqual(open(path, "rb").read(), competing)
                recovery_path = caught.exception.recovery_path
                self.assertEqual(open(recovery_path, "rb").read(), foreign)

                post_path = os.path.join(images, "post-publication.tsv")
                write_manifest(post_path, {"Old_fig_1.png": "a" * 64})
                original = open(post_path, "rb").read()
                _manifest, post_expected = read_manifest_snapshot(post_path)
                after = b"Late_fig_1.png\t" + b"f" * 64 + b"\n"
                injected[:] = []

                def replace_after_publish(src, dst, *args, **kwargs):
                    answer = real_link(src, dst, *args, **kwargs)
                    if (dst == post_path
                            and os.path.basename(src) == os.path.basename(post_path)
                            and not injected):
                        intruder = post_path + ".intruder"
                        with open(intruder, "wb") as fh:
                            fh.write(after)
                        os.replace(intruder, post_path)
                        injected.append(True)
                    return answer

                with mock.patch.object(os, "link",
                                       side_effect=replace_after_publish):
                    with self.assertRaisesRegex(
                            SidecarConflict, "differs from the staged snapshot") as caught:
                        write_manifest(post_path,
                                       {"New_fig_1.png": "e" * 64},
                                       expected=post_expected)
                self.assertEqual(open(post_path, "rb").read(), after)
                recovery_path = caught.exception.recovery_path
                self.assertEqual(open(recovery_path, "rb").read(), original)

                # A new sidecar has no predecessor to restore. If its public
                # hard link is changed before readback, withdraw only the
                # version staged here and retain the later bytes.
                new_path = os.path.join(images, "post-new.tsv")
                _text, absent = read_sidecar(new_path)
                late_new = b"LateNew_fig_1.png\t" + b"9" * 64 + b"\n"
                injected[:] = []
                real_link_noreplace = atomic_move.link_noreplace

                def mutate_new_after_link(src, dst):
                    answer = real_link_noreplace(src, dst)
                    if dst == new_path and not injected:
                        with open(dst, "wb") as fh:
                            fh.write(late_new)
                        injected.append(True)
                    return answer

                with mock.patch.object(
                        atomic_move, "link_noreplace",
                        side_effect=mutate_new_after_link):
                    with self.assertRaisesRegex(
                            SidecarConflict, "differs from its staged snapshot"):
                        write_manifest(new_path,
                                       {"New_fig_1.png": "e" * 64},
                                       expected=absent)
                self.assertEqual(open(new_path, "rb").read(), late_new)

                link_path = os.path.join(images, "post-new-link.tsv")
                link_target = os.path.join(directory, "late-link-target.tsv")
                with open(link_target, "wb") as fh:
                    fh.write(late_new)
                _text, absent = read_sidecar(link_path)
                injected[:] = []

                def replace_new_with_symlink(src, dst):
                    answer = real_link_noreplace(src, dst)
                    if dst == link_path and not injected:
                        os.unlink(dst)
                        os.symlink(link_target, dst)
                        injected.append(True)
                    return answer

                with mock.patch.object(
                        atomic_move, "link_noreplace",
                        side_effect=replace_new_with_symlink):
                    with self.assertRaisesRegex(
                            SidecarConflict, "could not be read back"):
                        write_manifest(link_path,
                                       {"New_fig_1.png": "e" * 64},
                                       expected=absent)
                self.assertTrue(os.path.islink(link_path))
                self.assertEqual(open(link_path, "rb").read(), late_new)

        def test_read_only_and_linked_sidecars_remain_untouched(self):
            with tempfile.TemporaryDirectory() as directory:
                path = os.path.join(directory, MANIFEST_FILE)
                write_manifest(path, {"A_fig_1.png": "a" * 64})
                before = open(path, "rb").read()
                os.chmod(path, 0o444)
                try:
                    with self.assertRaises(ValueError):
                        write_manifest(path, {"B_fig_1.png": "b" * 64})
                    self.assertEqual(open(path, "rb").read(), before)
                    self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o444)
                finally:
                    os.chmod(path, 0o640)
                with mock.patch.object(os, "fchmod", None):
                    write_manifest(path, {"B_fig_1.png": "b" * 64})
                self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o640)
                link = os.path.join(directory, "linked.tsv")
                os.symlink(path, link)
                before = open(path, "rb").read()
                with self.assertRaises(ValueError):
                    write_manifest(link, {"C_fig_1.png": "c" * 64})
                self.assertTrue(os.path.islink(link))
                self.assertEqual(open(path, "rb").read(), before)

    output = io.StringIO()
    result = unittest.TextTestRunner(stream=output).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(StateTests))
    failed = len(result.failures) + len(result.errors)
    if failed:
        print(output.getvalue())
    print("%d/%d self-test cases pass" % (result.testsRun - failed, result.testsRun))
    return 0 if result.wasSuccessful() else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true", help="run sidecar regression tests")
    args = parser.parse_args(argv)
    if args.test:
        return self_test()
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
