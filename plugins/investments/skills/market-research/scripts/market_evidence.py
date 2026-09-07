#!/usr/bin/env python3
"""Pinned, content-addressed JSON evidence for the investments plugin.

Only Comparisons and ProviderStatus snapshot folders are supported. Files are
create-only; exact retries verify existing bytes. This writer briefly pins the
working directory: invoke it from a single-threaded CLI, never parallel threads.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile

_OBSIDIAN_SHARED_MODULES = ('atomic_move', 'portable_names')

# --- obsidian shared-layer bootstrap (canonical; see shared/RUNTIME.md) ---
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
from portable_names import portable_identity

MAX_BYTES = 32 * 1024 * 1024
FOLDERS = {('Investments', 'Snapshots', 'Comparisons'), ('Investments', 'Snapshots', 'ProviderStatus')}


class PublicationError(RuntimeError):
    """The exact named private stage must be preserved for recovery."""


def fail(message):
    raise ValueError(message)


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
                       allow_nan=False) + '\n').encode('utf-8')


def directory_owner(descriptor, name):
    owners = [entry for entry in os.listdir(descriptor)
              if portable_identity(entry) == portable_identity(name)]
    if owners and owners != [name]:
        fail('portable-equivalent immutable evidence owner collision')
    return bool(owners)


def pinned_directory(vault, folder, create=False):
    """Create the directory context only when evidence is accessed."""
    return contextmanager(_pinned_directory)(vault, folder, create)


def _pinned_directory(vault, folder, create=False):
    """Pin every vault-relative directory; a symlink or replacement never redirects I/O."""
    if tuple(folder) not in FOLDERS:
        fail('unsupported immutable evidence folder')
    if vault is None:
        fail('linked immutable evidence requires the selected vault')
    requested = Path(vault).expanduser().absolute()
    if requested.is_symlink() or '..' in requested.parts:
        fail('immutable evidence vault must be an explicit real directory')
    root = requested.resolve(strict=True)  # Resolve platform aliases above the selected vault.
    flags = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    descriptors, chain = [], []
    try:
        descriptors.append(os.open(root, flags))
        if create:
            import fcntl
            try:
                fcntl.flock(descriptors[0], fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                fail('another market publication is in progress; retry after it finishes')
        root_stat = os.fstat(descriptors[0])
        for name in folder:
            parent = descriptors[-1]
            present = directory_owner(parent, name)
            if not present and create:
                os.mkdir(name, dir_fd=parent)  # Exclusive: never adopt a concurrent owner.
            child = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISDIR(child.st_mode):
                fail('immutable evidence folders must be real directories, never symlinks')
            descriptor = os.open(name, flags, dir_fd=parent)
            descriptors.append(descriptor)
            opened = os.fstat(descriptor)
            identity = (child.st_dev, child.st_ino)
            if identity != (opened.st_dev, opened.st_ino):
                fail('immutable evidence directory changed while opening')
            chain.append((parent, name, identity))

        def check():
            current_root = root.lstat()
            if (not stat.S_ISDIR(current_root.st_mode)
                    or (current_root.st_dev, current_root.st_ino) != (root_stat.st_dev, root_stat.st_ino)):
                fail('immutable evidence vault changed during access')
            for parent, name, identity in chain:
                if not directory_owner(parent, name):
                    fail('immutable evidence directory disappeared during access')
                current = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != identity:
                    fail('immutable evidence directory changed during access')

        check()
        yield root, descriptors[-1], check
        check()
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def read_bytes(descriptor, name, max_bytes=MAX_BYTES):
    if not directory_owner(descriptor, name):
        fail('immutable evidence attachment is missing')
    before = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
        fail('immutable evidence must be a bounded regular non-symlink file')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    with os.fdopen(os.open(name, flags, dir_fd=descriptor), 'rb') as handle:
        opened = os.fstat(handle.fileno())
        if not stat.S_ISREG(opened.st_mode):
            fail('immutable evidence changed to a non-regular file')
        raw = handle.read(max_bytes + 1)
        after_open = os.fstat(handle.fileno())
    after = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
    def token(item):
        return (item.st_dev, item.st_ino, item.st_mode, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
    if len(raw) > max_bytes or not token(before) == token(opened) == token(after_open) == token(after):
        fail('immutable evidence changed while reading or exceeded its byte limit')
    return raw


def write(value, vault, folder, max_bytes=MAX_BYTES):
    """Publish canonical bytes exclusively; callers validate their own record schema."""
    raw = canonical(value)
    if len(raw) > max_bytes:
        fail('immutable evidence exceeds its attachment byte budget')
    sha256 = hashlib.sha256(raw).hexdigest()
    name = sha256 + '.json'
    with pinned_directory(vault, folder, create=True) as (root, descriptor, check):
        path = root.joinpath(*folder, name)
        if directory_owner(descriptor, name):
            if read_bytes(descriptor, name, max_bytes) != raw:
                fail('immutable evidence filename is occupied by different bytes; preserve it')
            status = 'unchanged'
        else:
            stage = Path(tempfile.mkdtemp(prefix='.market-evidence-stage-', dir=root))
            staged, previous = stage / name, None
            try:
                with staged.open('xb') as handle:
                    atomic_move.set_private_mode(handle, 0o600)
                    handle.write(raw); handle.flush(); os.fsync(handle.fileno())
                check()
                previous = os.open('.', os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
                os.fchdir(descriptor)
                atomic_move.publish_new(staged, Path(name), atomic_move.regular_file_snapshot, root)
                check()
                if read_bytes(descriptor, name, max_bytes) != raw:
                    fail('immutable evidence readback differs from its reviewed bytes')
            except Exception as exc:
                raise PublicationError('immutable evidence publication failed; preserve recovery stage %s: %s' % (stage, exc)) from exc
            finally:
                if previous is not None:
                    os.fchdir(previous); os.close(previous)
            shutil.rmtree(stage)
            status = 'created'
        check()
    return {'status': status, 'path': str(path), 'sha256': sha256,
            'link': '[[%s/%s]]' % ('/'.join(folder), name)}


def run_self_test():
    import unittest

    class EvidenceTests(unittest.TestCase):
        def setUp(self):
            self.temp = tempfile.TemporaryDirectory(prefix='.immutable-evidence-test-')
            self.addCleanup(self.temp.cleanup)
            self.vault = Path(self.temp.name).resolve()
            self.folder = ('Investments', 'Snapshots', 'ProviderStatus')

        def test_create_only_retry_and_bounded_readback(self):
            result = write({'fixture': 1}, self.vault, self.folder)
            path = Path(result['path']); original = path.read_bytes()
            self.assertEqual(result['sha256'], hashlib.sha256(original).hexdigest())
            self.assertEqual(write({'fixture': 1}, self.vault, self.folder)['status'], 'unchanged')
            with pinned_directory(self.vault, self.folder) as (_, descriptor, _):
                self.assertEqual(read_bytes(descriptor, path.name), original)
                with self.assertRaises(ValueError):
                    read_bytes(descriptor, path.name, 1)

        def test_unowned_path_symlink_and_different_bytes_are_preserved(self):
            with self.assertRaises(ValueError):
                write({'fixture': 1}, self.vault, ('Investments', '..', 'elsewhere'))
            result = write({'fixture': 1}, self.vault, self.folder)
            path = Path(result['path']); path.write_bytes(b'changed')
            with self.assertRaises(ValueError):
                write({'fixture': 1}, self.vault, self.folder)
            self.assertEqual(path.read_bytes(), b'changed')
            path.unlink(); path.symlink_to(self.vault / 'absent')
            with self.assertRaises(ValueError):
                write({'fixture': 1}, self.vault, self.folder)
            self.assertTrue(path.is_symlink())

        def test_no_stage_remains_after_success(self):
            write({'fixture': 1}, self.vault, self.folder)
            self.assertEqual(list(self.vault.glob('.market-evidence-*')), [])

    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(EvidenceTests))
    print('%d/%d self-tests passed' % (result.testsRun - len(result.failures) - len(result.errors), result.testsRun))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', action='store_true', help='run bounded offline publication fixtures')
    args = parser.parse_args()
    if args.test:
        raise SystemExit(run_self_test())
    parser.print_help()
