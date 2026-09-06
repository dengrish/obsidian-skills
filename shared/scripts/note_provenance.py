#!/usr/bin/env python3
"""Verify a shipped plugin and stamp Markdown drafts with its exact identity.

Stdlib only. No Git, network, host registry, repository fallback, or vault writes.
The CLI writes only a newly named draft; publish it using the active workflow's
safe-write protocol. The fingerprint identifies code, not research correctness.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys


MARKER = '<!-- skill-provenance'
FOOTER = re.compile(r'^<!-- skill-provenance: (\{[^\r\n]*\}) -->\r?\n?\Z', re.M)
HEX256 = re.compile(r'[0-9a-f]{64}\Z')
COMMIT = re.compile(r'(?:[0-9a-f]{40}|[0-9a-f]{64})\Z')
SKILL = re.compile(r'(knowledge|investments):[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z')
RECORD_FIELDS = {'skill', 'plugin_version', 'source_commit', 'source_url',
                 'source_status', 'runtime_sha256'}
MANIFEST_FIELDS = {'schema', 'plugin', 'plugin_version', 'repository',
                   'source_commit', 'source_url', 'source_status',
                   'runtime_sha256', 'files'}
MAX_FILE_BYTES = 64 * 1024 * 1024


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate provenance JSON key: ' + key)
        result[key] = value
    return result


def _json(text):
    return json.loads(text, object_pairs_hook=_unique_object)


def _snapshot(item):
    return (item.st_dev, item.st_ino, item.st_mode, item.st_size,
            item.st_mtime_ns, item.st_ctime_ns)


def _read(path):
    """Read one stable regular file; never follow a leaf symlink."""
    path = Path(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_BYTES:
        raise ValueError('expected a bounded regular file: ' + str(path))
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as handle:
        opened = os.fstat(handle.fileno())
        if not stat.S_ISREG(opened.st_mode) or _snapshot(opened) != _snapshot(before):
            raise ValueError('file changed before provenance read: ' + str(path))
        data = handle.read(MAX_FILE_BYTES + 1)
        after = os.fstat(handle.fileno())
    if (len(data) > MAX_FILE_BYTES or _snapshot(before) != _snapshot(after)
            or _snapshot(after) != _snapshot(path.lstat())):
        raise ValueError('file changed during provenance read: ' + str(path))
    return data


def validate_record(record):
    """Validate attribution syntax, without claiming to reverify old releases."""
    if not isinstance(record, dict) or set(record) != RECORD_FIELDS:
        raise ValueError('invalid skill provenance record fields')
    if not isinstance(record['skill'], str) or not SKILL.fullmatch(record['skill']):
        raise ValueError('invalid qualified producing skill')
    version = record['plugin_version']
    if not isinstance(version, str) or not re.fullmatch(r'[0-9][A-Za-z0-9.+_-]{0,99}', version):
        raise ValueError('invalid provenance plugin version')
    digest = record['runtime_sha256']
    if not isinstance(digest, str) or not HEX256.fullmatch(digest):
        raise ValueError('invalid runtime SHA-256')
    status = record['source_status']
    commit, url = record['source_commit'], record['source_url']
    if status == 'committed':
        if not isinstance(commit, str) or not COMMIT.fullmatch(commit):
            raise ValueError('committed provenance needs a full Git commit')
        if (not isinstance(url, str)
                or not re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/commit/' + commit, url)):
            raise ValueError('source URL must link to the full GitHub commit')
    elif status in {'uncommitted', 'unavailable'}:
        if commit is not None or url is not None:
            raise ValueError('unverified source must not claim a Git commit')
    else:
        raise ValueError('invalid provenance source status')
    return record


def split_provenance(text):
    """Remove only one valid final footer, rejecting malformed or hidden copies."""
    if MARKER not in text:
        return text, None
    if text.count(MARKER) != 1:
        raise ValueError('duplicate skill provenance footer')
    match = FOOTER.search(text)
    if match is None or match.start() != text.index(MARKER):
        raise ValueError('skill provenance must be a single final metadata line')
    prefix = text[:match.start()]
    if not prefix.endswith(('\n\n', '\r\n\r\n')):
        raise ValueError('separate skill provenance from note content with a blank line')
    payload = _json(match[1])
    if (not isinstance(payload, dict) or type(payload.get('schema')) is not int
            or payload['schema'] != 1
            or not {'schema', 'generated_by'} <= set(payload)
            or set(payload) - {'schema', 'generated_by', 'updated_by'}):
        raise ValueError('invalid note provenance metadata')
    if payload['generated_by'] is not None:
        validate_record(payload['generated_by'])
    elif 'updated_by' not in payload:
        raise ValueError('unknown creator requires an identified later editor')
    if 'updated_by' in payload:
        validate_record(payload['updated_by'])
    # A canonical separator does not become part of the note's prose or cards.
    return prefix.rstrip('\r\n') + '\n', payload


def _runtime_inventory(root):
    """Reject unlisted executable/runtime material, links and special files."""
    result = {}
    for folder, dirs, names in os.walk(root, followlinks=False):
        parent = Path(folder)
        for name in list(dirs):
            path = parent / name
            if path.is_symlink():
                raise ValueError('plugin contains a symlink: ' + str(path))
            if name == '__pycache__' or (parent == root and name == '.git'):
                dirs.remove(name)
        for name in names:
            path = parent / name
            if path.is_symlink():
                raise ValueError('plugin contains a symlink: ' + str(path))
            if name == '.DS_Store' or path.suffix in {'.pyc', '.pyo'}:
                continue
            relative = path.relative_to(root).as_posix()
            if relative != 'provenance.json':
                result[relative] = hashlib.sha256(_read(path)).hexdigest()
    return result


def verified_record(plugin_root, skill):
    """Verify the exact distributed bytes and return one producing-skill record.

    This is independent of the importing host. The CLI and publishing callers
    additionally bind their actual executing paths to this verified root.
    """
    original = Path(plugin_root).absolute()
    if original.is_symlink() or not original.is_dir():
        raise ValueError('plugin root must be an ordinary directory')
    root = original.resolve()
    override = os.environ.get('OBSIDIAN_VAULT_SHARED')
    if override and Path(override).expanduser().resolve() != root / 'shared/scripts':
        raise ValueError('shared-helper override belongs to a different plugin')
    manifest_bytes = _read(root / 'provenance.json')
    manifest = _json(manifest_bytes)
    if (not isinstance(manifest, dict) or set(manifest) != MANIFEST_FIELDS
            or type(manifest['schema']) is not int or manifest['schema'] != 1
            or manifest['plugin'] not in {'knowledge', 'investments'}):
        raise ValueError('invalid bundled provenance manifest')
    qualified = str(manifest['plugin']) + ':' + skill
    record = {key: manifest[key] for key in RECORD_FIELDS - {'skill'}}
    record['skill'] = qualified
    validate_record(record)
    repository = manifest['repository']
    if (not isinstance(repository, str)
            or not re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository)
            or (record['source_commit'] is not None
                and record['source_url'] != repository + '/commit/' + record['source_commit'])):
        raise ValueError('provenance repository disagrees with source commit URL')
    files = manifest['files']
    if not isinstance(files, dict) or not files:
        raise ValueError('empty or invalid runtime file inventory')
    for relative, digest in files.items():
        if not isinstance(relative, str):
            raise ValueError('invalid runtime inventory path')
        path = PurePosixPath(relative)
        if (not relative or path.is_absolute() or '..' in path.parts
                or path.as_posix() != relative or '\\' in relative
                or relative == 'provenance.json'
                or not isinstance(digest, str) or not HEX256.fullmatch(digest)):
            raise ValueError('invalid runtime inventory entry')
    if 'skills/' + skill + '/SKILL.md' not in files:
        raise ValueError('producing skill is absent from this plugin')
    inventory_bytes = json.dumps(files, sort_keys=True, separators=(',', ':')).encode('utf-8')
    if hashlib.sha256(inventory_bytes).hexdigest() != manifest['runtime_sha256']:
        raise ValueError('runtime fingerprint does not match the file inventory')
    actual = _runtime_inventory(root)
    if actual != files:
        changed = sorted(key for key in set(actual) | set(files) if actual.get(key) != files.get(key))
        raise ValueError('installed runtime differs from its provenance: ' + ', '.join(changed[:8]))
    authored = _json(_read(root / '.claude-plugin/plugin.json'))
    codex = _json(_read(root / '.codex-plugin/plugin.json'))
    for host_manifest in (authored, codex):
        if not isinstance(host_manifest, dict):
            raise ValueError('plugin manifest must be a JSON object')
        host_repository = str(host_manifest.get('repository', '')).rstrip('/')
        if host_repository.endswith('.git'):
            host_repository = host_repository[:-4]
        if (host_manifest.get('name') != manifest['plugin']
                or host_manifest.get('version') != manifest['plugin_version']
                or host_repository != repository):
            raise ValueError('plugin manifest disagrees with bundled provenance')
    if _read(root / 'provenance.json') != manifest_bytes:
        raise ValueError('bundled provenance changed during verification')
    return record


def stamp_text(text, record, previous=None):
    """Stamp a new draft or retain creator attribution during a substantive edit."""
    validate_record(record)
    body, current = split_provenance(text)
    if previous is not None:
        old_body, old = split_provenance(previous)
        if body.rstrip('\r\n') == old_body.rstrip('\r\n'):
            return previous
        # Metadata in the source note is authoritative, not a replacement draft.
        payload = {'schema': 1, 'generated_by': old['generated_by'] if old else None,
                   'updated_by': record}
    elif current is not None:
        # Repeating the stamping step must not turn a new creation into an edit.
        if current.get('updated_by', current['generated_by']) == record:
            return text
        raise ValueError('draft carries another producer; use --previous for an existing-note edit, '
                         'never copy provenance into a new note')
    else:
        payload = {'schema': 1, 'generated_by': record}
    if not body.strip():
        # An empty generated misc MOC still needs a separated metadata line.
        body = ''
    return (body.rstrip('\r\n') + '\n\n<!-- skill-provenance: '
            + json.dumps(payload, sort_keys=True, separators=(',', ':')) + ' -->\n')


def run_self_test():
    """Portable attribution tests; cross-format/publication tests live in tests/."""
    import unittest

    class ProvenanceTests(unittest.TestCase):
        def setUp(self):
            self.record = {'skill': 'knowledge:wiki-build', 'plugin_version': '1.0.2',
                           'source_commit': 'a' * 40,
                           'source_url': 'https://github.com/dengrish/obsidian-skills/commit/' + 'a' * 40,
                           'source_status': 'committed', 'runtime_sha256': 'b' * 64}

        def test_create_and_retry(self):
            original = '# A concept\n\nA useful definition.\n'
            stamped = stamp_text(original, self.record)
            body, metadata = split_provenance(stamped)
            self.assertEqual(body, original)
            self.assertEqual(metadata, {'schema': 1, 'generated_by': self.record})
            self.assertEqual(stamp_text(stamped, self.record), stamped)

        def test_preserve_known_creator_during_edit(self):
            previous = stamp_text('Definition.\n', self.record)
            editor = dict(self.record, skill='knowledge:wiki-lint', runtime_sha256='c' * 64)
            _, metadata = split_provenance(stamp_text('Improved definition.\n', editor, previous))
            self.assertEqual(metadata['generated_by'], self.record)
            self.assertEqual(metadata['updated_by'], editor)

        def test_unknown_historical_creator_remains_unknown(self):
            _, metadata = split_provenance(stamp_text('New wording.\n', self.record, 'Old wording.\n'))
            self.assertIsNone(metadata['generated_by'])
            self.assertEqual(metadata['updated_by'], self.record)

        def test_noop_returns_exact_original_even_without_provenance(self):
            for previous in ('Old wording.\r\n\r\n', stamp_text('Old wording.\n', self.record)):
                editor = dict(self.record, plugin_version='2.0.0')
                self.assertEqual(stamp_text('Old wording.\n', editor, previous), previous)

        def test_another_creator_cannot_be_adopted_without_original(self):
            copied = stamp_text('A copied template.\n', self.record)
            with self.assertRaisesRegex(ValueError, 'another producer'):
                stamp_text(copied, dict(self.record, skill='knowledge:wiki-add'))

        def test_false_or_abbreviated_commit_is_rejected(self):
            for change in ({'source_commit': 'a' * 7}, {'source_url': 'https://example.org'},
                           {'source_status': 'uncommitted'}, {'runtime_sha256': 'short'}):
                with self.subTest(change=change), self.assertRaises(ValueError):
                    validate_record(dict(self.record, **change))
            for status in ('uncommitted', 'unavailable'):
                validate_record(dict(self.record, source_status=status, source_commit=None, source_url=None))

        def test_sha256_git_history_and_reused_version_remain_distinguishable(self):
            later = dict(self.record, source_commit='d' * 64,
                         source_url='https://github.com/dengrish/obsidian-skills/commit/' + 'd' * 64,
                         runtime_sha256='e' * 64)
            first = stamp_text('Definition.\n', self.record)
            second = stamp_text('Definition.\n', later)
            self.assertNotEqual(first, second)
            self.assertEqual(split_provenance(second)[1]['generated_by']['plugin_version'], '1.0.2')

        def test_malformed_misplaced_duplicate_footer_is_never_silently_removed(self):
            good = stamp_text('Definition.\n', self.record)
            footer = good[good.index(MARKER):]
            for malformed in (good + 'More prose.\n', good + footer,
                              good.replace('\n\n<!--', '\n<!--'),
                              good.replace('"schema":1', '"schema":true'),
                              good.replace('"schema":1', '"schema":1,"schema":1'),
                              good.replace('"schema":1', '"schema":1,"hidden_state":true')):
                with self.subTest(malformed=malformed), self.assertRaises(ValueError):
                    split_provenance(malformed)
            with self.assertRaises(ValueError):
                stamp_text('New definition.\n', self.record, good + 'More prose.\n')

        def test_empty_outline_has_separate_metadata(self):
            body, metadata = split_provenance(stamp_text('', self.record))
            self.assertFalse(body.strip())
            self.assertEqual(metadata['generated_by'], self.record)

    result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(ProvenanceTests))
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print('%d/%d self-test cases pass' % (passed, total))
    return 0 if result.wasSuccessful() else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', action='store_true', help='run offline self-tests')
    commands = parser.add_subparsers(dest='command')
    for command in ('inspect', 'stamp'):
        sub = commands.add_parser(command)
        sub.add_argument('--plugin', type=Path, required=True)
        sub.add_argument('--skill', required=True, help='unqualified skill directory name')
        if command == 'stamp':
            sub.add_argument('--draft', type=Path, required=True)
            sub.add_argument('--previous', type=Path)
            sub.add_argument('--output', type=Path, required=True, help='new scratch draft only')
    args = parser.parse_args(argv)
    if args.test:
        return run_self_test()
    if args.command is None:
        parser.error('choose inspect or stamp')
    try:
        root = args.plugin.resolve()
        if Path(__file__).resolve() != root / 'shared/scripts/note_provenance.py':
            raise ValueError('invoke the selected plugin\'s own provenance helper')
        record = verified_record(args.plugin, args.skill)
        if args.command == 'inspect':
            print(json.dumps(record, indent=2, sort_keys=True))
        else:
            raw = _read(args.draft)
            old = _read(args.previous) if args.previous is not None else None
            content = stamp_text(raw.decode('utf-8'), record,
                                 old.decode('utf-8') if old is not None else None)
            if _read(args.draft) != raw or (old is not None and _read(args.previous) != old):
                raise ValueError('draft or previous note changed during stamping')
            # This is an intermediate draft writer, never a replacement tool.
            fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as output:
                output.write(content.encode('utf-8'))
                output.flush()
                os.fsync(output.fileno())
            print(json.dumps({'status': 'created', 'path': str(args.output.absolute()),
                              'provenance': record}, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError) as exc:
        print('provenance error: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
