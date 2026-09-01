"""Strict, standard-library readers for the figure extractor's sidecars.

The batch extractor, manual cropper and source renamer share these formats.
Malformed or conflicting records are errors, never an empty ownership map.
Run ``python3 figure_state.py --test`` for the format/rename regressions.
"""
import argparse
import hashlib
import os
import re
import stat
import tempfile
import unicodedata


MANIFEST_FILE = ".figure-manifest.tsv"
REVIEW_FILE = ".figure-review.txt"


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


def read_manifest(path):
    """Read a manifest strictly; only a missing file means no prior record."""
    try:
        with open(path, encoding="utf-8") as fh:
            return parse_manifest(fh.read())
    except FileNotFoundError:
        if os.path.lexists(path):
            raise ValueError("%s is a dangling sidecar symlink" % path)
        return {}


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


def _write_sidecar(path, body):
    """Atomically replace one validated sidecar, preserving its mode.

    Stage beside the destination directory, not inside the flat image folder.
    The final ``os.replace`` remains same-filesystem atomic, while a killed
    process cannot leave unfinished metadata among the files consumers list.
    """
    check_manifest_writable(path)
    mode = stat.S_IMODE(os.stat(path).st_mode) if os.path.exists(path) else None
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    # Resolve the directory for staging only. A symlinked Images folder can
    # point at another filesystem, where its logical parent would make the
    # final replace cross-device and therefore non-atomic.
    directory = os.path.realpath(directory)
    stage_parent = os.path.dirname(directory)
    with tempfile.TemporaryDirectory(prefix=".figure-state-stage-",
                                     dir=stage_parent) as stage_dir:
        temporary = os.path.join(stage_dir, os.path.basename(path))
        with open(temporary, "w", encoding="utf-8", newline="") as fh:
            fh.write(body)
            if mode is not None:
                os.fchmod(fh.fileno(), mode)
        os.replace(temporary, path)


def write_manifest(path, manifest, header=""):
    """Atomically write valid ownership records, preserving existing modes."""
    body = header + "".join("%s\t%s\n" % (key, manifest[key]) for key in sorted(manifest))
    parse_manifest(body)
    _write_sidecar(path, body)


def write_review(path, body):
    """Atomically write a complete, valid review ledger."""
    parse_reviewed(body)
    _write_sidecar(path, body)


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
                with mock.patch.object(os, "replace",
                                       side_effect=OSError("interrupted")):
                    with self.assertRaises(OSError):
                        write_review(path, text + "New\t4\n")
                self.assertEqual(open(path, "rb").read(), before)
                self.assertFalse(any(name.startswith(".figure-state-stage-")
                                     for name in os.listdir(directory)))

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

        def test_atomic_write_and_bad_input(self):
            with tempfile.TemporaryDirectory() as directory:
                real_root = os.path.join(directory, "real")
                real_images = os.path.join(real_root, "Images")
                os.makedirs(real_images)
                path = os.path.join(real_images, MANIFEST_FILE)
                stage_parents = []
                real_tempdir = tempfile.TemporaryDirectory

                def tracked_tempdir(*args, **kwargs):
                    stage_parents.append(kwargs.get("dir"))
                    return real_tempdir(*args, **kwargs)

                with mock.patch.object(tempfile, "TemporaryDirectory",
                                       side_effect=tracked_tempdir):
                    write_manifest(path, {"A_fig_1.png": "a" * 64})
                self.assertEqual(stage_parents, [os.path.realpath(real_root)])
                self.assertFalse(any(name.startswith(".figure-state-stage-")
                                     for name in os.listdir(real_root)))
                self.assertTrue(os.path.isfile(os.path.join(real_images,
                                                            MANIFEST_FILE)))
                before = open(path, "rb").read()
                with mock.patch.object(os, "replace",
                                       side_effect=OSError("blocked publication")):
                    with self.assertRaises(OSError):
                        write_manifest(path, {"B_fig_1.png": "b" * 64})
                self.assertEqual(open(path, "rb").read(), before)
                self.assertFalse(any(name.startswith(".figure-state-stage-")
                                     for name in os.listdir(real_root)))
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
                    with mock.patch.object(tempfile, "TemporaryDirectory",
                                           side_effect=tracked_tempdir):
                        write_manifest(linked_path, {"A_fig_1.png": "a" * 64})
                    self.assertEqual(stage_parents, [os.path.realpath(real_root)])
                    self.assertTrue(os.path.isfile(os.path.join(
                        real_images, MANIFEST_FILE)))

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
