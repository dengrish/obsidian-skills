"""Strict, standard-library readers for the figure extractor's sidecars.

The batch extractor, manual cropper and source renamer share these formats.
Malformed or conflicting records are errors, never an empty ownership map.
Run ``python3 figure_state.py --test`` for the format/rename regressions.
"""
import argparse
import hashlib
import os
import re
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


def write_manifest(path, manifest, header=""):
    """Atomically write valid ownership records, never replacing a symlink."""
    body = header + "".join("%s\t%s\n" % (key, manifest[key]) for key in sorted(manifest))
    parse_manifest(body)
    if os.path.islink(path):
        raise ValueError("%s is a sidecar symlink; refusing to replace it" % path)
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                         prefix=".figure-manifest-", delete=False) as fh:
            temporary = fh.name
            fh.write(body)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def self_test():
    import io
    import unittest

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
                path = os.path.join(directory, MANIFEST_FILE)
                write_manifest(path, {"A_fig_1.png": "a" * 64})
                before = open(path, "rb").read()
                with self.assertRaises(ValueError):
                    write_manifest(path, {"A_fig_1.png": "bad"})
                self.assertEqual(open(path, "rb").read(), before)
                self.assertEqual(read_manifest(path), {"A_fig_1.png": "a" * 64})
                self.assertEqual(read_manifest(os.path.join(directory, "absent")), {})

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
