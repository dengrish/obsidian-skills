#!/usr/bin/env python3
"""Read explicitly selected private JSON credentials without exporting secrets.

This sibling library has no network or storage side effects. Use market_data.py
with --credentials-file for retrieval; --test here runs offline file checks.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parent))
from market_http import CREDENTIAL_NAMES, DataError


MAX_CREDENTIAL_BYTES = 32768


def credential_environment(env, loaded):
    """A selected file is authoritative, including missing provider settings."""
    return {**{key: value for key, value in env.items() if key not in CREDENTIAL_NAMES}, **loaded}


def _fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _private_file(info):
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) not in (0o600, 0o400)):
        raise DataError('unsafe_credentials_file',
                        'Credentials require a user-owned private regular file with one link (mode 600 or 400).')
    if not 0 < info.st_size <= MAX_CREDENTIAL_BYTES:
        raise DataError('invalid_credentials_file', 'Credentials file is empty or exceeds the 32 KiB limit.')


def load_credentials(path):
    """Read one bounded, stable descriptor; never print a path, payload, or OS error."""
    directory = descriptor = None
    try:
        if (not all(hasattr(os, name) for name in ('O_NOFOLLOW', 'O_DIRECTORY', 'getuid'))
                or os.open not in os.supports_dir_fd or os.stat not in os.supports_dir_fd):
            raise DataError('unsafe_credentials_file', 'This platform cannot safely open private credentials files.')
        # Walk directories without following links; do not resolve a linked path into an allowed one.
        raw_path = os.fspath(path)
        if not isinstance(raw_path, str) or not raw_path or '\x00' in raw_path:
            raise DataError('invalid_credentials_file', 'Select a credentials file using a valid filesystem path.')
        if '..' in raw_path.split(os.sep):
            raise DataError('unsafe_credentials_file', 'Credentials file paths must not contain parent-directory traversal.')
        parts = Path(os.path.abspath(raw_path)).parts
        flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0)
        directory = os.open(parts[0], flags | os.O_DIRECTORY)
        for part in parts[1:-1]:
            child = os.open(part, flags | os.O_DIRECTORY, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(parts[-1], flags | getattr(os, 'O_NONBLOCK', 0), dir_fd=directory)
        before = os.fstat(descriptor)
        _private_file(before)
        chunks, size = [], 0
        while True:
            chunk = os.read(descriptor, min(8192, MAX_CREDENTIAL_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_CREDENTIAL_BYTES:
                raise DataError('invalid_credentials_file', 'Credentials file exceeds the 32 KiB limit.')
        after = os.fstat(descriptor)
        named = os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)
        if _fingerprint(before) != _fingerprint(after) or _fingerprint(after) != _fingerprint(named) or size != after.st_size:
            raise DataError('changed_credentials_file', 'Credentials file changed during reading; retry after saving it.')
        payload = b''.join(chunks).decode('utf-8')

        def object_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key not in CREDENTIAL_NAMES or key in result:
                    raise DataError('invalid_credentials_file', 'Credentials JSON contains an unknown or duplicate setting.')
                if (not isinstance(value, str) or not value.strip()
                        or any(unicodedata.category(ch) == 'Cc' for ch in value)):
                    raise DataError('invalid_credentials_file', 'Credential values must be nonempty strings without control characters.')
                value.encode('utf-8')  # Reject lone surrogate escapes before any provider uses a value.
                result[key] = value
            return result

        loaded = json.loads(payload, object_pairs_hook=object_pairs)
        if not isinstance(loaded, dict):
            raise DataError('invalid_credentials_file', 'Credentials JSON must be one flat object of named strings.')
        return loaded
    except DataError:
        raise
    except (OSError, ValueError, TypeError, RecursionError):
        raise DataError('invalid_credentials_file',
                        'Cannot read valid private credentials JSON; check its path, permissions and contents.') from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if directory is not None:
            os.close(directory)


def run_self_test():
    import tempfile
    import unittest
    from unittest.mock import patch

    class CredentialTests(unittest.TestCase):
        def setUp(self):
            self.temp = tempfile.TemporaryDirectory()
            self.addCleanup(self.temp.cleanup)
            # macOS's default temporary directory has a linked /var prefix.
            self.root = Path(self.temp.name).resolve()
            self.path = self.root / 'credentials.json'

        def write(self, payload=b'{"FRED_API_KEY":"fixture-private-value"}'):
            self.path.write_bytes(payload)
            self.path.chmod(0o600)
            return self.path

        def rejected(self, path=None):
            with self.assertRaises(DataError) as error:
                load_credentials(path or self.path)
            self.assertNotIn('fixture-private-value', str(error.exception))
            self.assertNotIn(str(self.root), str(error.exception))
            return error.exception

        def test_private_partial_configuration(self):
            self.write()
            self.assertEqual(load_credentials(self.path), {'FRED_API_KEY': 'fixture-private-value'})
            self.path.chmod(0o400)
            self.assertEqual(load_credentials(self.path)['FRED_API_KEY'], 'fixture-private-value')

        def test_authoritative_file_removes_missing_environment_keys(self):
            source = {'FRED_API_KEY': 'old-key', 'ALPACA_API_KEY': 'old-id', 'OTHER_SETTING': 'kept'}
            original = dict(source)
            self.assertEqual(credential_environment(source, {'FRED_API_KEY': 'new-key'}),
                             {'FRED_API_KEY': 'new-key', 'OTHER_SETTING': 'kept'})
            self.assertEqual(source, original)

        def test_empty_object_configures_no_provider(self):
            self.write(b'{}')
            self.assertEqual(load_credentials(self.path), {})

        def test_malformed_unknown_duplicate_and_nonstring_json(self):
            for payload in (b'{bad fixture-private-value', b'{"OTHER":"fixture-private-value"}',
                            b'{"FRED_API_KEY":"fixture-private-value","FRED_API_KEY":"other"}',
                            b'{"FRED_API_KEY":42}', b'{"FRED_API_KEY":null}',
                            b'{"FRED_API_KEY":{"FRED_API_KEY":"fixture-private-value"}}',
                            b'["fixture-private-value"]', b'NaN', b'null'):
                with self.subTest(payload=payload):
                    self.write(payload)
                    self.rejected()

        def test_invalid_encoding_empty_values_and_controls(self):
            for payload in (b'\xff', b'\xef\xbb\xbf{}', b'{"FRED_API_KEY":""}', b'{"FRED_API_KEY":" "}',
                            b'{"FRED_API_KEY":"fixture-private-value\\n"}',
                            b'{"FRED_API_KEY":"\\ud800"}', b'{"FRED_API_KEY":"\\u007f"}',
                            b'{"FRED_API_KEY":"fixture-private-value\\u0085"}'):
                with self.subTest(payload=payload):
                    self.write(payload)
                    self.rejected()

        def test_size_bounds_and_missing_file(self):
            self.rejected()
            for payload in (b'', b' ' * (MAX_CREDENTIAL_BYTES + 1)):
                self.write(payload)
                self.rejected()

        def test_shared_permissions_and_special_bits(self):
            self.write()
            for mode in (0o644, 0o640, 0o604, 0o660, 0o700):
                with self.subTest(mode=mode):
                    self.path.chmod(mode)
                    self.assertEqual(self.rejected().code, 'unsafe_credentials_file')
            # Some filesystems silently remove setuid bits on chmod; validate that policy directly.
            metadata = list(self.path.stat())
            metadata[0] = stat.S_IFREG | 0o4600
            with self.assertRaises(DataError):
                _private_file(os.stat_result(metadata))

        def test_foreign_owner(self):
            self.write()
            with patch(__name__ + '.os.getuid', return_value=os.getuid() + 1):
                self.assertEqual(self.rejected().code, 'unsafe_credentials_file')

        def test_symlink_leaf_and_parent(self):
            self.write()
            leaf = self.root / 'leaf.json'
            leaf.symlink_to(self.path)
            self.rejected(leaf)
            parent = self.root / 'linked-directory'
            parent.symlink_to(self.root, target_is_directory=True)
            self.rejected(parent / self.path.name)

        def test_hardlink_directory_and_fifo(self):
            self.write()
            os.link(self.path, self.root / 'hardlink.json')
            self.assertEqual(self.rejected().code, 'unsafe_credentials_file')
            self.rejected(self.root)
            fifo = self.root / 'fifo'
            os.mkfifo(fifo, 0o600)
            self.assertEqual(self.rejected(fifo).code, 'unsafe_credentials_file')

        def test_path_traversal_and_invalid_path(self):
            self.write()
            self.rejected(self.root / '..' / self.root.name / self.path.name)
            for value in ('', '\x00', b'bytes-path'):
                with self.assertRaises(DataError):
                    load_credentials(value)

        def test_file_changes_during_read(self):
            self.write()
            original_read = os.read
            changed = False
            def changing_read(descriptor, count):
                nonlocal changed
                result = original_read(descriptor, count)
                if not changed:
                    changed = True
                    with self.path.open('ab') as handle:
                        handle.write(b' ')
                return result
            with patch(__name__ + '.os.read', side_effect=changing_read):
                self.assertEqual(self.rejected().code, 'changed_credentials_file')

        def test_file_replaced_during_read(self):
            self.write()
            original_read = os.read
            changed = False
            def replacing_read(descriptor, count):
                nonlocal changed
                result = original_read(descriptor, count)
                if not changed:
                    changed = True
                    self.path.unlink()
                    self.write()
                return result
            with patch(__name__ + '.os.read', side_effect=replacing_read):
                self.assertEqual(self.rejected().code, 'changed_credentials_file')

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CredentialTests)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    print('%d/%d self-tests passed' % (result.testsRun - len(result.failures) - len(result.errors), result.testsRun))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', action='store_true', help='run offline credential-file tests')
    args = parser.parse_args()
    if args.test:
        raise SystemExit(run_self_test())
    parser.print_help()
