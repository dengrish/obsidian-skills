"""No-clobber moves and verified file publication shared by vault workflows.

``move_noreplace(src, dst)`` either moves one filesystem entry while ``dst``
is still unoccupied, or raises without replacing it. Regular files retain the
authorized inode and conditionally displace the source before publication;
directories use a host exclusive-rename primitive or fail closed.

``publish_new``, ``replace_expected`` and ``remove_expected`` implement the
shared staged-publication protocol for regular files, including readback and
conditional rollback of only the snapshot the caller authorized.
``regular_file_snapshot`` supplies their default identity/content callback.

The guarantees are about concurrent directory-entry changes while the process
is running. They do not claim power-loss durability; callers needing that must
also flush file data and the affected directories according to the host
filesystem's durability contract before reporting a durable commit.
On a host that lacks an exclusive rename primitive, process termination during
the regular-file fallback can leave the source under a sibling
``.atomic-move-*`` directory. Preserve such a directory and inspect its
``.removed``/``.observed`` entries; it is recovery state, not disposable cache.

This module is a programmatic import library, not a publication CLI. Its
command line intentionally exposes only ``--test`` for the adversarial cases.
"""

import argparse
import ctypes
import errno
import hashlib
import os
import shutil
import stat
import sys
import tempfile
from collections import namedtuple


RegularFileSnapshot = namedtuple(
    "RegularFileSnapshot", ("identity", "digest", "mode", "size"))


def set_private_mode(file_or_fd, path, mode):
    """Set mode on a staged private file on POSIX and native Windows.

    ``os.fchmod`` is absent on native Windows. The pathname fallback is safe
    only because callers create ``path`` exclusively inside their private
    staging directory and have not exposed it at a public vault name yet.
    """
    descriptor = (file_or_fd if isinstance(file_or_fd, int)
                  else file_or_fd.fileno())
    fchmod = getattr(os, "fchmod", None)
    if callable(fchmod):
        fchmod(descriptor, mode)
    else:
        os.chmod(path, mode)


class MoveIncomplete(OSError):
    """A move reached a state that cannot be reported as fully recovered.

    Surviving names are deliberately retained. Removing either as cleanup
    could delete a competing writer that changed a directory entry during the
    operation.
    """

    def __init__(self, src, dst, cause, recovery_path=None,
                 recovery_paths=None):
        paths = tuple(recovery_paths or (
            (recovery_path,) if recovery_path is not None else ()))
        super().__init__(
            getattr(cause, "errno", None) or errno.EIO,
            "move %r -> %r is incomplete; inspect and preserve every existing "
            "entry at both paths%s (%s)" % (
                src, dst,
                " and the recovery path(s) %s" % ", ".join(
                    repr(path) for path in paths) if paths else "", cause), src)
        self.src = src
        self.dst = dst
        self.recovery_paths = paths
        self.recovery_path = paths[0] if paths else None


class SourceChanged(OSError):
    """The source no longer has the identity authorized by the caller."""


class LinkUnavailable(OSError):
    """The hard link needed for safe publication is unsupported or denied."""

    def __init__(self, source, target, cause):
        OSError.__init__(
            self, getattr(cause, "errno", None) or errno.ENOTSUP,
            "safe publication requires hard links on one filesystem; cannot "
            "link %r to %r (%s). Move the staging area onto the target "
            "filesystem and verify that its permissions and filesystem permit "
            "hard links" %
            (source, target, cause), target)
        self.source = source
        self.target = target
        self.cause = cause
        self.recovery_path = None
        self.staging_path = None
        self.keep_stage = False


def _retain_link_unavailable(exc, detail, recovery_path=None,
                             staging_path=None):
    """Add recoverable publication state without erasing the error category."""
    if detail:
        exc.strerror = "%s; %s" % (exc.strerror, detail)
        # OSError stores the display message both as ``strerror`` and in
        # ``args``. Keep them aligned for callers that serialize either form.
        exc.args = (exc.errno, exc.strerror)
    exc.recovery_path = recovery_path
    exc.staging_path = staging_path
    exc.keep_stage = True
    return exc


class PublicationConflict(OSError):
    """Expected-file replacement/removal met a newer filesystem occupant."""

    def __init__(self, message, recovery_path=None, keep_stage=False):
        OSError.__init__(self, errno.EEXIST, message, recovery_path)
        self.recovery_path = recovery_path
        self.keep_stage = keep_stage


class RecoveryFailed(OSError):
    """A displaced file remains in private staging and must be retained."""

    def __init__(self, path, cause):
        OSError.__init__(
            self, getattr(cause, "errno", None) or errno.EIO,
            "could not restore or move the displaced file; it is preserved "
            "at %s (%s)" % (path, cause), path)
        self.path = path


def _validate_stage_dir(stage_dir, reserved_names):
    """Refuse missing, unsafe, or previously used private publication state."""
    try:
        stage_stat = os.lstat(stage_dir)
    except OSError as exc:
        raise PublicationConflict(
            "private staging directory %s is missing or unreadable (%s: %s); "
            "refusing publication before changing the target" %
            (stage_dir, type(exc).__name__, exc),
            recovery_path=stage_dir, keep_stage=True) from exc
    if not stat.S_ISDIR(stage_stat.st_mode) or stat.S_ISLNK(stage_stat.st_mode):
        raise PublicationConflict(
            "private staging path %s is not a real directory; refusing "
            "publication before changing the target" % stage_dir,
            recovery_path=stage_dir, keep_stage=True)
    for name in reserved_names:
        path = os.path.join(stage_dir, name)
        if os.path.lexists(path):
            raise PublicationConflict(
                "private staging directory contains prior publication state "
                "at %s; preserve and inspect it, then use a fresh unique "
                "stage directory" % path,
                recovery_path=path, keep_stage=True)


def file_identity(path):
    """Stable directory-entry identity without following a symlink."""
    item = os.lstat(path)
    return item.st_dev, item.st_ino, stat.S_IFMT(item.st_mode)


def regular_file_snapshot(path):
    """Return a stable identity/content token for guarded publication.

    The file is read through one no-follow descriptor and its identity and
    change-sensitive metadata are compared before, during, and after that
    read. The returned equality token deliberately omits ctime and link count:
    ``publish_new`` and ``replace_expected`` create private hard links, which
    change those fields without changing the authorized file or its bytes.

    ``RegularFileSnapshot.mode`` is the permission mode to copy to a staged
    replacement. The other fields make the object suitable as both the
    ``expected`` value and the ``snapshot`` callback result used by this
    module's regular-file publication primitives.
    """
    path = os.fspath(path)
    before = os.lstat(path)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = getattr(before, "st_file_attributes", 0)
    if (not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or bool(reparse and attributes & reparse)):
        raise OSError(
            errno.EINVAL, "snapshot target is a symlink, reparse point, or "
            "non-regular file", path)

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    source = None
    digest = hashlib.sha256()
    try:
        source = os.fdopen(descriptor, "rb")
        descriptor = None
        with source:
            opened_before = os.fstat(source.fileno())
            if (not stat.S_ISREG(opened_before.st_mode)
                    or file_identity(path) != (
                        opened_before.st_dev,
                        opened_before.st_ino,
                        stat.S_IFMT(opened_before.st_mode))):
                raise OSError(
                    errno.EBUSY, "file changed while it was opened", path)
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
            opened_after = os.fstat(source.fileno())
    finally:
        if descriptor is not None:
            os.close(descriptor)

    after = os.lstat(path)

    def stable(item):
        return (
            item.st_dev,
            item.st_ino,
            stat.S_IFMT(item.st_mode),
            stat.S_IMODE(item.st_mode),
            item.st_size,
            getattr(item, "st_mtime_ns", int(item.st_mtime * 1e9)),
            getattr(item, "st_ctime_ns", int(item.st_ctime * 1e9)),
        )

    if not (stable(before) == stable(opened_before)
            == stable(opened_after) == stable(after)):
        raise OSError(errno.EBUSY, "file changed while it was read", path)
    return RegularFileSnapshot(
        identity=(after.st_dev, after.st_ino, stat.S_IFMT(after.st_mode)),
        digest=digest.hexdigest(),
        mode=stat.S_IMODE(after.st_mode),
        size=after.st_size,
    )


def link_noreplace(source, target):
    """Expose one regular inode atomically only at an unoccupied name."""
    try:
        try:
            os.link(source, target, follow_symlinks=False)
        except (TypeError, NotImplementedError):
            os.link(source, target)
    except NotImplementedError as exc:
        cause = OSError(errno.ENOSYS, "hard links are not implemented")
        raise LinkUnavailable(source, target, cause) from exc
    except OSError as exc:
        # POSIX specifies EPERM when a filesystem does not support hard links;
        # network filesystems also commonly translate that refusal to EACCES.
        # Either way the capability this operation needs is unavailable, and
        # presenting it as a content race sends callers toward the wrong fix.
        unavailable = {errno.EXDEV, errno.ENOSYS, errno.EPERM, errno.EACCES}
        for name in ("ENOTSUP", "EOPNOTSUPP"):
            number = getattr(errno, name, None)
            if number is not None:
                unavailable.add(number)
        # Native Windows reports an unsupported hard-link operation through
        # winerror even when errno is the generic EINVAL/EACCES translation.
        if (exc.errno in unavailable
                or getattr(exc, "winerror", None) in {1, 50}):
            raise LinkUnavailable(source, target, exc) from exc
        raise


def _restore_or_recover(displaced, target, stage_parent, recovery_prefix):
    """Restore a displaced file exclusively, or retain it at a named path."""
    try:
        link_noreplace(displaced, target)
        return "the displaced file was restored to its original path", None
    except OSError as restore_exc:
        recovery_dir = tempfile.mkdtemp(prefix=recovery_prefix,
                                        dir=stage_parent)
        recovery = os.path.join(recovery_dir, os.path.basename(target))
        try:
            move_noreplace(displaced, recovery,
                           expected=file_identity(displaced))
        except MoveIncomplete as move_exc:
            if os.path.lexists(recovery):
                if isinstance(restore_exc, LinkUnavailable):
                    return (("the displaced file could not be restored because "
                             "hard links are unavailable; it is preserved at %s"
                             % recovery), recovery)
                return (("the public path was reoccupied (%s); the displaced "
                         "file is preserved at %s" % (restore_exc, recovery)),
                        recovery)
            raise RecoveryFailed(displaced, move_exc) from move_exc
        except OSError as move_exc:
            try:
                os.rmdir(recovery_dir)
            except OSError:
                pass
            raise RecoveryFailed(displaced, move_exc) from move_exc
        if isinstance(restore_exc, LinkUnavailable):
            return (("the displaced file could not be restored because hard "
                     "links are unavailable; it is preserved at %s" % recovery),
                    recovery)
        return (("the public path was reoccupied (%s); the displaced file is "
                 "preserved at %s" % (restore_exc, recovery)), recovery)


def _displace_expected(target, expected, snapshot, stage_dir, stage_parent,
                       recovery_prefix):
    """Move the current expected occupant into staging without losing a race."""
    observed = os.path.join(stage_dir, ".atomic-observed")
    displaced = os.path.join(stage_dir, ".atomic-displaced")
    try:
        link_noreplace(target, observed)
        if not stat.S_ISREG(os.lstat(observed).st_mode):
            raise PublicationConflict(
                "%s is no longer a regular file; refusing publication" % target)
        if snapshot(observed) != expected:
            raise PublicationConflict(
                "%s changed after planning; refusing publication" % target)
    except (PublicationConflict, LinkUnavailable):
        raise
    except (OSError, UnicodeError) as exc:
        raise PublicationConflict(
            "%s changed or became unreadable after planning (%s: %s); "
            "refusing publication" %
            (target, type(exc).__name__, exc)) from exc

    try:
        # The private destination is unique. Moving the current public entry
        # captures a writer that won after observation instead of overwriting
        # it; the second snapshot below decides which inode was captured.
        move_noreplace(target, displaced, stage_parent=stage_parent)
    except LinkUnavailable:
        raise
    except OSError as exc:
        if isinstance(exc, MoveIncomplete) and os.path.lexists(displaced):
            try:
                disposition, recovery = _restore_or_recover(
                    displaced, target, stage_parent, recovery_prefix)
            except RecoveryFailed as recovery_exc:
                raise PublicationConflict(
                    str(recovery_exc), recovery_path=recovery_exc.path,
                    keep_stage=True) from recovery_exc
            raise PublicationConflict(
                "%s changed during displacement (%s); %s" %
                (target, exc, disposition), recovery_path=recovery) from exc
        raise PublicationConflict(
            "%s changed before it could be displaced; refusing publication "
            "(%s)" % (target, exc)) from exc

    try:
        displaced_snapshot = snapshot(displaced)
    except (OSError, UnicodeError) as exc:
        try:
            disposition, recovery = _restore_or_recover(
                displaced, target, stage_parent, recovery_prefix)
        except RecoveryFailed as recovery_exc:
            raise PublicationConflict(
                str(recovery_exc), recovery_path=recovery_exc.path,
                keep_stage=True) from recovery_exc
        raise PublicationConflict(
            "%s could not be revalidated after displacement (%s); %s" %
            (target, exc, disposition), recovery_path=recovery) from exc
    if displaced_snapshot != expected:
        try:
            disposition, recovery = _restore_or_recover(
                displaced, target, stage_parent, recovery_prefix)
        except RecoveryFailed as recovery_exc:
            raise PublicationConflict(
                str(recovery_exc), recovery_path=recovery_exc.path,
                keep_stage=True) from recovery_exc
        raise PublicationConflict(
            "%s acquired a different occupant during publication; %s" %
            (target, disposition), recovery_path=recovery)
    return displaced


def replace_expected(staged, target, expected, snapshot, stage_dir,
                     stage_parent=None, recovery_prefix=".atomic-recovery-"):
    """Replace exactly ``expected`` through displacement and exclusive link.

    ``snapshot(path)`` returns any equality-comparable identity+content value.
    The caller owns ``stage_dir`` and must retain it when a raised
    :class:`PublicationConflict` or :class:`LinkUnavailable` has ``keep_stage``
    true. A named recovery path is exposed on the exception whenever the
    displaced predecessor could not reclaim the public name.
    """
    stage_parent = stage_parent or os.path.dirname(stage_dir)
    _validate_stage_dir(
        stage_dir,
        (".atomic-observed", ".atomic-displaced",
         ".atomic-publication-rollback"))
    try:
        staged_stat = os.lstat(staged)
        if not stat.S_ISREG(staged_stat.st_mode):
            raise OSError(errno.EINVAL, "staged publication is not a regular file",
                          staged)
        replacement = snapshot(staged)
    except (OSError, UnicodeError) as exc:
        raise PublicationConflict(
            "%s could not be verified before publication (%s: %s)" %
            (staged, type(exc).__name__, exc)) from exc
    # Once the predecessor has been displaced, rollback itself needs a hard
    # link. Refuse a cross-device replacement before touching the public name
    # instead of discovering EXDEV only at staged -> target publication time.
    try:
        target_parent_stat = os.stat(os.path.dirname(target) or os.curdir)
    except OSError as exc:
        raise PublicationConflict(
            "%s parent could not be verified before publication (%s: %s)" %
            (target, type(exc).__name__, exc)) from exc
    if (getattr(staged_stat, "st_dev", None) is not None
            and staged_stat.st_dev != target_parent_stat.st_dev):
        cause = OSError(errno.EXDEV, "staged file and target are on different "
                        "filesystems", target)
        raise _retain_link_unavailable(
            LinkUnavailable(staged, target, cause),
            "the staged replacement is preserved at %s" % staged,
            recovery_path=staged, staging_path=stage_dir)
    try:
        displaced = _displace_expected(
            target, expected, snapshot, stage_dir, stage_parent, recovery_prefix)
    except LinkUnavailable as exc:
        raise _retain_link_unavailable(
            exc, "the public predecessor remains unchanged and the staged "
            "replacement is preserved at %s" % staged,
            recovery_path=staged, staging_path=stage_dir)
    try:
        link_noreplace(staged, target)
    except LinkUnavailable as exc:
        try:
            disposition, recovery = _restore_or_recover(
                displaced, target, stage_parent, recovery_prefix)
        except RecoveryFailed as recovery_exc:
            raise _retain_link_unavailable(
                exc, "publication failed and the predecessor could not be "
                "restored; inspect %s. The staged replacement remains at %s"
                % (recovery_exc.path, staged),
                recovery_path=recovery_exc.path,
                staging_path=stage_dir) from recovery_exc
        raise _retain_link_unavailable(
            exc, "%s; the staged replacement is preserved at %s"
            % (disposition, staged),
            recovery_path=(recovery or staged), staging_path=stage_dir)
    except OSError as exc:
        try:
            disposition, recovery = _restore_or_recover(
                displaced, target, stage_parent, recovery_prefix)
        except RecoveryFailed as recovery_exc:
            raise PublicationConflict(
                str(recovery_exc), recovery_path=recovery_exc.path,
                keep_stage=True) from recovery_exc
        raise PublicationConflict(
            "%s was reoccupied before exclusive publication (%s); %s" %
            (target, exc, disposition), recovery_path=recovery) from exc

    verification = None
    try:
        if snapshot(target) != replacement:
            verification = "the published file differs from the staged snapshot"
    except (OSError, UnicodeError) as exc:
        verification = "the published file could not be read back (%s: %s)" % (
            type(exc).__name__, exc)
    if verification is None:
        try:
            if snapshot(displaced) != expected:
                verification = ("the displaced predecessor changed after "
                                "publication")
        except (OSError, UnicodeError) as exc:
            verification = (
                "the displaced predecessor could not be revalidated after "
                "publication (%s: %s)" % (type(exc).__name__, exc))
    if verification is None:
        return replacement

    # Publication is not complete until readback succeeds. Retract only the
    # exact staged snapshot; a writer that changed or replaced it owns the
    # public name and must remain there. The predecessor is restored
    # exclusively, or moved to a named recovery path if that name is occupied.
    rollback_dir = os.path.join(stage_dir, ".atomic-publication-rollback")
    retract_error = None
    try:
        os.mkdir(rollback_dir)
        remove_expected(
            target, replacement, snapshot, rollback_dir,
            stage_parent=stage_parent, recovery_prefix=recovery_prefix)
    except PublicationConflict as exc:
        retract_error = exc
    except OSError as exc:
        retract_error = PublicationConflict(
            "%s could not be conditionally withdrawn (%s: %s)" %
            (target, type(exc).__name__, exc), keep_stage=True)

    try:
        disposition, recovery = _restore_or_recover(
            displaced, target, stage_parent, recovery_prefix)
    except RecoveryFailed as recovery_exc:
        detail = ("; conditional withdrawal also failed: %s" % retract_error
                  if retract_error else "")
        raise PublicationConflict(
            "%s for %s%s; %s" %
            (verification, target, detail, recovery_exc),
            recovery_path=recovery_exc.path, keep_stage=True) from recovery_exc

    detail = ("; conditional withdrawal retained a newer occupant: %s" %
              retract_error if retract_error else
              "; the unverified publication was withdrawn")
    raise PublicationConflict(
        "%s for %s%s; %s" %
        (verification, target, detail, disposition),
        recovery_path=(recovery or
                       (retract_error.recovery_path if retract_error else None)),
        keep_stage=bool(retract_error and retract_error.keep_stage))


def remove_expected(target, expected, snapshot, stage_dir, stage_parent=None,
                    recovery_prefix=".atomic-recovery-"):
    """Displace only ``expected``; caller cleanup then removes that version."""
    if not os.path.lexists(target):
        return False
    stage_parent = stage_parent or os.path.dirname(stage_dir)
    _validate_stage_dir(stage_dir, (".atomic-observed", ".atomic-displaced"))
    _displace_expected(
        target, expected, snapshot, stage_dir, stage_parent, recovery_prefix)
    return True


def publish_new(staged, target, snapshot, stage_parent,
                recovery_prefix=".atomic-recovery-"):
    """Publish a new regular file exclusively and verify its public snapshot.

    A failed readback conditionally withdraws only the exact staged snapshot.
    A newer occupant remains public. Any private residue that cannot be safely
    restored or named is retained and exposed through ``PublicationConflict``.
    """
    try:
        if not stat.S_ISREG(os.lstat(staged).st_mode):
            raise OSError(errno.EINVAL, "staged publication is not a regular file",
                          staged)
        expected = snapshot(staged)
    except (OSError, UnicodeError) as exc:
        raise PublicationConflict(
            "%s could not be verified before publication (%s: %s)" %
            (staged, type(exc).__name__, exc)) from exc

    rollback = tempfile.mkdtemp(prefix=".atomic-new-rollback-",
                                dir=stage_parent)
    keep_stage = False
    try:
        try:
            link_noreplace(staged, target)
        except LinkUnavailable as exc:
            raise _retain_link_unavailable(
                exc, "the staged file is preserved at %s" % staged,
                recovery_path=staged,
                staging_path=os.path.dirname(os.path.abspath(staged)))
        verification = None
        try:
            if snapshot(target) != expected:
                verification = (
                    "the new public file differs from its staged snapshot")
        except (OSError, UnicodeError) as exc:
            verification = (
                "the new public file could not be read back (%s: %s)" %
                (type(exc).__name__, exc))
        if verification is None:
            return expected

        try:
            removed = remove_expected(
                target, expected, snapshot, rollback,
                stage_parent=stage_parent, recovery_prefix=recovery_prefix)
        except PublicationConflict as exc:
            keep_stage = exc.keep_stage
            raise PublicationConflict(
                "%s for %s; conditional cleanup retained a newer occupant: %s"
                % (verification, target, exc),
                recovery_path=exc.recovery_path,
                keep_stage=exc.keep_stage) from exc
        disposition = ("the exact unverified publication was withdrawn"
                       if removed else "the public name was already absent")
        raise PublicationConflict(
            "%s for %s; %s" % (verification, target, disposition))
    finally:
        if not keep_stage:
            shutil.rmtree(rollback, ignore_errors=True)


def _raise_errno(number, path):
    """Raise the specific OSError subclass for ``number`` and ``path``."""
    raise OSError(number, os.strerror(number), path)


def _native_noreplace(src, dst):
    """Use a host exclusive-rename syscall; return False when unavailable."""
    if os.name == "nt":
        # Python documents os.rename as no-replace on Windows.
        os.rename(src, dst)
        return True

    try:
        libc = ctypes.CDLL(None, use_errno=True)
    except (OSError, AttributeError):
        return False

    source = os.fsencode(src)
    target = os.fsencode(dst)
    if sys.platform.startswith("linux"):
        fn = getattr(libc, "renameat2", None)
        if fn is None:
            return False
        fn.argtypes = (ctypes.c_int, ctypes.c_char_p,
                       ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
        fn.restype = ctypes.c_int
        # Linux fcntl.h: AT_FDCWD=-100; linux/fs.h: RENAME_NOREPLACE=1.
        result = fn(-100, source, -100, target, 1)
    elif sys.platform == "darwin":
        fn = getattr(libc, "renamex_np", None)
        if fn is None:
            return False
        fn.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        fn.restype = ctypes.c_int
        # Darwin sys/stdio.h: RENAME_EXCL=0x00000004.
        result = fn(source, target, 0x00000004)
    else:
        return False

    if result == 0:
        return True
    number = ctypes.get_errno()
    unsupported = {errno.ENOSYS, errno.EINVAL}
    for name in ("ENOTSUP", "EOPNOTSUPP"):
        value = getattr(errno, name, None)
        if value is not None:
            unsupported.add(value)
    if number in unsupported:
        return False
    _raise_errno(number, dst)


def _move_regular_via_links(src, dst, expected, stage_parent=None):
    """Move a regular file without ever unlinking an unchecked public name."""
    parent = (os.path.realpath(stage_parent) if stage_parent is not None else
              (os.path.dirname(os.path.abspath(src)) or "."))
    stage = tempfile.mkdtemp(prefix=".atomic-move-", dir=parent)
    observed = os.path.join(stage, ".observed")
    removed = os.path.join(stage, ".removed")
    keep_stage = False

    def retained_private_paths():
        return tuple(path for path in (observed, removed)
                     if os.path.lexists(path))

    try:
        # First retain the authorized inode. Then move the current public
        # directory entry into private staging and verify what was removed.
        # A source replacement in that gap is preserved at ``removed`` rather
        # than being unlinked as the old link/unlink fallback did.
        link_noreplace(src, observed)
        if file_identity(observed) != expected:
            raise SourceChanged(
                errno.ESTALE if hasattr(errno, "ESTALE") else errno.EBUSY,
                "source identity changed while it was retained", src)
        try:
            os.rename(src, removed)
        except OSError as exc:
            # A plain rename failure can leave the public source wholly
            # untouched (permissions, read-only media, transient I/O). In
            # that state this operation has nothing to recover: remove the
            # private observation link and preserve the original exception.
            try:
                source_unchanged = (not os.path.lexists(removed)
                                    and file_identity(src) == expected)
            except OSError:
                source_unchanged = False
            if source_unchanged:
                raise
            keep_stage = True
            raise MoveIncomplete(src, dst, exc,
                                 recovery_paths=retained_private_paths()) from exc

        try:
            removed_identity = file_identity(removed)
        except OSError as exc:
            keep_stage = True
            raise MoveIncomplete(src, dst, exc,
                                 recovery_paths=retained_private_paths()) from exc
        if removed_identity != expected:
            disposition = "the replacement remains in private staging"
            restored = False
            try:
                # Retain the private name while restoring a late regular file,
                # so another source-path race cannot consume its only copy.
                # Non-regular late occupants cannot be hard-linked and remain
                # named in staging rather than taking a risky native move.
                if stat.S_ISREG(os.lstat(removed).st_mode):
                    link_noreplace(removed, src)
                    restored = file_identity(src) == removed_identity
                if restored:
                    disposition = "the replacement was restored to its source path"
            except OSError as restore_exc:
                disposition = "the replacement remains in private staging (%s)" % restore_exc
            keep_stage = True
            raise MoveIncomplete(
                src, dst,
                SourceChanged(
                    errno.EBUSY,
                    "source changed during conditional removal; %s" % disposition,
                    src),
                recovery_paths=retained_private_paths())

        try:
            link_noreplace(observed, dst)
        except OSError as exc:
            # Restore only through exclusive creation. If a writer reclaimed
            # the old name, both private links remain as explicit recovery.
            try:
                link_noreplace(observed, src)
                if file_identity(src) != expected:
                    raise SourceChanged(
                        errno.EBUSY, "a different entry appeared at the source",
                        src)
            except OSError as restore_exc:
                keep_stage = True
                raise MoveIncomplete(
                    src, dst,
                    OSError(getattr(restore_exc, "errno", None) or errno.EIO,
                            "publication failed (%s) and exclusive source "
                            "restoration failed (%s)" % (exc, restore_exc)),
                    recovery_paths=retained_private_paths()) from exc
            raise
        try:
            landed = file_identity(dst)
        except OSError as exc:
            keep_stage = True
            raise MoveIncomplete(src, dst, exc,
                                 recovery_paths=retained_private_paths()) from exc
        if landed != expected:
            keep_stage = True
            raise MoveIncomplete(
                src, dst,
                SourceChanged(
                    errno.EBUSY,
                    "destination identity changed before move verification", dst),
                recovery_paths=retained_private_paths())

        # Both private names are known links to the inode now verified at the
        # destination. They are the only names this fallback ever unlinks.
        try:
            os.unlink(observed)
            os.unlink(removed)
        except OSError as exc:
            keep_stage = True
            raise MoveIncomplete(src, dst, exc,
                                 recovery_paths=retained_private_paths()) from exc
    finally:
        if not keep_stage:
            for private in (observed, removed):
                try:
                    os.unlink(private)
                except FileNotFoundError:
                    pass
                except OSError as cleanup_exc:
                    # A private cleanup failure is residue, not a reason to
                    # risk either public pathname during exception handling.
                    keep_stage = True
                    raise MoveIncomplete(
                        src, dst, cleanup_exc,
                        recovery_paths=retained_private_paths())
        if not keep_stage:
            try:
                os.rmdir(stage)
            except OSError:
                pass


def _move_directory_via_private(src, dst, expected):
    """Move a directory through verified private space before publication."""
    parent = os.path.dirname(os.path.abspath(src)) or "."
    stage = tempfile.mkdtemp(prefix=".atomic-move-", dir=parent)
    held = os.path.join(stage, ".held")
    keep_stage = False
    try:
        # If the filesystem lacks exclusive directory rename, this returns
        # False before moving the source. There is no overwrite-capable
        # directory fallback.
        if not _native_noreplace(src, held):
            raise OSError(
                errno.ENOTSUP,
                "this host/filesystem has no exclusive directory rename; "
                "refusing an overwrite-capable fallback", src)
        try:
            held_identity = file_identity(held)
        except OSError as exc:
            keep_stage = True
            raise MoveIncomplete(src, dst, exc,
                                 recovery_path=held) from exc
        if held_identity != expected:
            keep_stage = True
            raise MoveIncomplete(
                src, dst,
                SourceChanged(errno.EBUSY,
                              "directory identity changed during staging", src),
                recovery_path=held)
        try:
            published = _native_noreplace(held, dst)
            if not published:
                raise OSError(
                    errno.ENOTSUP,
                    "exclusive directory rename became unavailable", dst)
        except OSError as exc:
            if os.path.lexists(held):
                try:
                    restored = _native_noreplace(held, src)
                except OSError as restore_exc:
                    restored = False
                    exc = OSError(
                        getattr(restore_exc, "errno", None) or errno.EIO,
                        "publication failed and source restoration failed: %s"
                        % restore_exc)
                if not restored:
                    keep_stage = True
                    raise MoveIncomplete(src, dst, exc,
                                         recovery_path=held) from exc
                try:
                    restored_identity = file_identity(src)
                except OSError as restore_exc:
                    raise MoveIncomplete(src, dst, restore_exc) from restore_exc
                if restored_identity != expected:
                    raise MoveIncomplete(
                        src, dst,
                        SourceChanged(
                            errno.EBUSY,
                            "source identity changed during restoration", src))
            raise
        try:
            landed = file_identity(dst)
        except OSError as exc:
            raise MoveIncomplete(src, dst, exc) from exc
        if landed != expected:
            raise MoveIncomplete(
                src, dst,
                SourceChanged(
                    errno.EBUSY,
                    "destination identity changed before move verification", dst))
    finally:
        if not keep_stage:
            try:
                os.rmdir(stage)
            except OSError:
                pass


def move_noreplace(src, dst, expected=None, stage_parent=None):
    """Move ``src`` without replacing either a late source or destination.

    Common hosts use atomic exclusive rename. A regular-file fallback retains
    the expected inode, conditionally displaces the public source into private
    staging, and exclusively publishes the retained link. Case/normalization
    aliases take the same two-step route, so the spelling change never relies
    on overwrite-capable ``os.rename(src, dst)``. Directories require the host
    exclusive-rename primitive and otherwise fail before mutation. Callers
    that must keep private staging out of a consumer directory may pass a
    same-filesystem ``stage_parent`` for regular files.
    """
    src = os.fspath(src)
    dst = os.fspath(dst)
    source_stat = os.lstat(src)
    observed = (source_stat.st_dev, source_stat.st_ino,
                stat.S_IFMT(source_stat.st_mode))
    if expected is not None and observed != expected:
        raise SourceChanged(
            errno.ESTALE if hasattr(errno, "ESTALE") else errno.EBUSY,
            "source identity changed after planning; refusing to move it", src)
    if os.path.abspath(src) == os.path.abspath(dst):
        return
    if not (stat.S_ISREG(source_stat.st_mode)
            or stat.S_ISDIR(source_stat.st_mode)):
        raise OSError(
            errno.ENOTSUP,
            "exclusive moves support regular files and directories only",
            src)
    if stat.S_ISREG(source_stat.st_mode):
        return _move_regular_via_links(
            src, dst, observed, stage_parent=stage_parent)
    return _move_directory_via_private(src, dst, observed)


def run_self_test():
    """Exercise exclusive publication, aliases, and the portable fallback."""
    cases = []

    def check(label, got, want):
        cases.append((label, got == want, got, want))

    def put(folder, name, body=b"source"):
        path = os.path.join(folder, name)
        with open(path, "wb") as fh:
            fh.write(body)
        return path

    with tempfile.TemporaryDirectory(prefix="atomic-move-test.") as folder:
        mode_path = put(folder, "private-mode", b"mode")
        with open(mode_path, "r+b") as mode_file:
            saved_fchmod = getattr(os, "fchmod", None)
            try:
                os.fchmod = None
                set_private_mode(mode_file, mode_path, 0o640)
            finally:
                if saved_fchmod is None:
                    delattr(os, "fchmod")
                else:
                    os.fchmod = saved_fchmod
        actual_mode = stat.S_IMODE(os.stat(mode_path).st_mode)
        if os.name == "nt":
            # Native Windows exposes only its read-only/writeable projection
            # through chmod rather than preserving every POSIX group bit.
            check("private staged permissions have a native-Windows fallback",
                  bool(actual_mode & stat.S_IWUSR), True)
        else:
            check("private staged permissions have a native-Windows fallback",
                  actual_mode, 0o640)

        src = put(folder, "source")
        dst = os.path.join(folder, "target")
        move_noreplace(src, dst)
        check("an unoccupied regular-file destination is published",
              (os.path.lexists(src), open(dst, "rb").read()),
              (False, b"source"))

        src = put(folder, "source2", b"ours")
        dst = put(folder, "target2", b"late")
        try:
            move_noreplace(src, dst)
            refused = False
        except FileExistsError:
            refused = True
        check("an occupied destination is refused without clobbering",
              (refused, open(src, "rb").read(), open(dst, "rb").read()),
              (True, b"ours", b"late"))

        same = put(folder, "same", b"same")
        move_noreplace(same, same)
        check("moving a path to itself is a no-op", open(same, "rb").read(),
              b"same")

        src = put(folder, "identity-source", b"first")
        expected = file_identity(src)
        os.unlink(src)
        put(folder, "identity-source", b"replacement")
        if file_identity(src) == expected:
            # Some filesystems can immediately reuse an inode. The test is for
            # an expected-identity mismatch, so make that mismatch deterministic.
            expected = (expected[0], -1, expected[2])
        dst = os.path.join(folder, "identity-target")
        try:
            move_noreplace(src, dst, expected=expected)
            changed_refused = False
        except SourceChanged:
            changed_refused = True
        check("a source replaced after planning is not silently moved",
              (changed_refused, open(src, "rb").read(), os.path.lexists(dst)),
              (True, b"replacement", False))

        first = put(folder, "first-link", b"linked")
        second = os.path.join(folder, "second-link")
        try:
            os.link(first, second)
        except (OSError, AttributeError, NotImplementedError):
            check("hard-link alias case is unavailable cleanly", True, True)
        else:
            try:
                move_noreplace(first, second)
                refused = False
            except FileExistsError:
                refused = True
            check("a distinct hard link is occupied, not a case-only alias",
                  (refused, os.path.lexists(first), os.path.lexists(second)),
                  (True, True, True))

        real_native = globals()["_native_noreplace"]
        globals()["_native_noreplace"] = lambda _src, _dst: False
        try:
            src = put(folder, "fallback-source", b"fallback")
            dst = os.path.join(folder, "fallback-target")
            move_noreplace(src, dst)
            check("the regular-file fallback moves through an exclusive link",
                  (os.path.lexists(src), open(dst, "rb").read()),
                  (False, b"fallback"))

            src = put(folder, "fallback-source2", b"ours")
            dst = put(folder, "fallback-target2", b"late")
            try:
                move_noreplace(src, dst)
                refused = False
            except FileExistsError:
                refused = True
            check("the fallback also preserves an occupied destination",
                  (refused, open(src, "rb").read(), open(dst, "rb").read()),
                  (True, b"ours", b"late"))

            real_os_link = os.link
            capability_results = []
            for number in (errno.EXDEV, errno.EPERM, errno.EACCES):
                src = put(folder, "unsupported-link-source-%d" % number,
                          b"still public")
                dst = os.path.join(folder, "unsupported-link-target-%d" % number)

                def refuse_hard_links(*_args, **_kwargs):
                    raise OSError(number, "injected unavailable hard link")

                os.link = refuse_hard_links
                try:
                    try:
                        move_noreplace(src, dst)
                        unavailable = False
                        unavailable_message = ""
                    except LinkUnavailable as exc:
                        unavailable = True
                        unavailable_message = str(exc)
                finally:
                    os.link = real_os_link
                capability_results.append((
                    unavailable, "requires hard links" in unavailable_message,
                    os.path.lexists(src), os.path.lexists(dst)))
            check("an unavailable hard link has a distinct actionable error",
                  (capability_results,
                   any(name.startswith(".atomic-move-")
                       for name in os.listdir(folder))),
                  ([(True, True, True, False)] * 3, False))

            src = put(folder, "rename-refusal-source", b"untouched")
            dst = os.path.join(folder, "rename-refusal-target")
            real_rename = os.rename

            def refuse_source_rename(source, target):
                if source == src and os.path.basename(target) == ".removed":
                    raise PermissionError(
                        errno.EACCES, "injected source rename refusal", source)
                return real_rename(source, target)

            os.rename = refuse_source_rename
            try:
                try:
                    move_noreplace(src, dst)
                    original_error_preserved = False
                except PermissionError:
                    original_error_preserved = True
            finally:
                os.rename = real_rename
            check("an untouched source rename failure needs no recovery",
                  (original_error_preserved, open(src, "rb").read(),
                   os.path.lexists(dst),
                   any(name.startswith(".atomic-move-")
                       for name in os.listdir(folder))),
                  (True, b"untouched", False, False))

            src = put(folder, "finally-source", b"finally ours")
            dst = put(folder, "finally-target", b"finally late")
            real_unlink = os.unlink

            def refuse_exception_cleanup(path):
                if os.path.basename(path) == ".observed":
                    raise PermissionError(
                        errno.EACCES, "injected exception cleanup failure", path)
                return real_unlink(path)

            os.unlink = refuse_exception_cleanup
            try:
                try:
                    move_noreplace(src, dst)
                    finally_incomplete = False
                    recoveries = ()
                    incomplete_message = ""
                except MoveIncomplete as exc:
                    finally_incomplete = True
                    recoveries = exc.recovery_paths
                    incomplete_message = str(exc)
            finally:
                os.unlink = real_unlink
            check("cleanup after a refused publication reports every residue",
                  (finally_incomplete, open(src, "rb").read(),
                   open(dst, "rb").read(), len(recoveries),
                   all(path in incomplete_message for path in recoveries)),
                  (True, b"finally ours", b"finally late", 2, True))

            src = put(folder, "unlink-source", b"linked bytes")
            dst = os.path.join(folder, "unlink-target")
            expected = file_identity(src)
            real_unlink = os.unlink

            def refuse_private_cleanup(path):
                if os.path.basename(path) == ".removed":
                    raise PermissionError(errno.EACCES,
                                          "injected private cleanup failure", path)
                return real_unlink(path)

            os.unlink = refuse_private_cleanup
            try:
                try:
                    move_noreplace(src, dst, expected=expected)
                    incomplete = False
                    recovery = None
                except MoveIncomplete as exc:
                    incomplete = True
                    recovery = exc.recovery_path
            finally:
                os.unlink = real_unlink
            check("a fallback cleanup failure reports the landed destination "
                  "and retained private link",
                  (incomplete, os.path.lexists(src), open(dst, "rb").read(),
                   open(recovery, "rb").read() if recovery else None),
                  (True, False, b"linked bytes", b"linked bytes"))

            # Exercise the alias branch on every host. A late destination is
            # injected after the source was moved into private staging. The
            # ordinary case-only os.rename that this replaced would clobber
            # it; exclusive publication preserves it and restores our source.
            src = put(folder, "case-source", b"case bytes")
            dst = os.path.join(folder, "Case-Source")
            real_link = globals()["link_noreplace"]
            injected = {"done": False}

            def occupy_case_destination(source, target):
                if (target == dst and not injected["done"]
                        and os.path.basename(source) == ".observed"):
                    injected["done"] = True
                    put(folder, "Case-Source", b"late case occupant")
                return real_link(source, target)

            globals()["link_noreplace"] = occupy_case_destination
            try:
                try:
                    move_noreplace(src, dst)
                    case_refused = False
                    recovery = None
                except FileExistsError:
                    case_refused = True
                    recovery = None
                except MoveIncomplete as exc:
                    case_refused = True
                    recovery = exc.recovery_path
            finally:
                globals()["link_noreplace"] = real_link
            check("a late case-only destination is never overwritten",
                  (case_refused, open(dst, "rb").read(),
                   (open(src, "rb").read() == b"case bytes"
                    or (recovery is not None
                        and open(recovery, "rb").read() == b"case bytes"))),
                  (True, b"late case occupant", True))

            # Replace the source in the observe/displace gap. The late source
            # returns to its public name and the authorized predecessor is
            # reported at a private recovery path, never unlinked.
            src = put(folder, "source-gap", b"planned source")
            dst = os.path.join(folder, "source-gap-target")
            expected = file_identity(src)
            replacement = put(folder, "source-gap-replacement", b"late source")
            real_rename = os.rename
            injected = {"done": False}

            def swap_before_displacement(source, target):
                if source == src and not injected["done"]:
                    injected["done"] = True
                    os.replace(replacement, source)
                return real_rename(source, target)

            os.rename = swap_before_displacement
            recoveries = ()
            try:
                try:
                    move_noreplace(src, dst, expected=expected)
                    source_gap_incomplete = False
                    recovery = None
                except MoveIncomplete as exc:
                    source_gap_incomplete = True
                    recovery = exc.recovery_path
                    recoveries = exc.recovery_paths
            finally:
                os.rename = real_rename
            check("a source swapped during fallback displacement is preserved",
                  (source_gap_incomplete, open(src, "rb").read(),
                   open(recovery, "rb").read() if recovery else None,
                   sorted(open(path, "rb").read() for path in recoveries),
                   os.path.lexists(dst)),
                  (True, b"late source", b"planned source",
                   [b"late source", b"planned source"], False))

            source_dir = os.path.join(folder, "source-dir")
            target_dir = os.path.join(folder, "target-dir")
            os.mkdir(source_dir)
            try:
                move_noreplace(source_dir, target_dir)
                directory_refused = False
            except OSError as exc:
                directory_refused = exc.errno == errno.ENOTSUP
            check("a directory has no overwrite-capable fallback",
                  (directory_refused, os.path.isdir(source_dir),
                   os.path.lexists(target_dir)), (True, True, False))
        finally:
            globals()["_native_noreplace"] = real_native

        # Repeat the observe/displace source race with normal host primitives
        # enabled. Regular files deliberately do not take the tempting direct
        # renameat2/renamex path, because those syscalls exclude a destination
        # race but would still relocate a source swapped after lstat.
        src = put(folder, "native-source-gap", b"native planned source")
        dst = os.path.join(folder, "native-source-gap-target")
        expected = file_identity(src)
        replacement = put(folder, "native-source-gap-replacement",
                          b"native late source")
        real_rename = os.rename
        injected = {"done": False}

        def swap_default_source_before_displacement(source, target):
            if source == src and not injected["done"]:
                injected["done"] = True
                os.replace(replacement, source)
            return real_rename(source, target)

        os.rename = swap_default_source_before_displacement
        try:
            try:
                move_noreplace(src, dst, expected=expected)
                default_gap_incomplete = False
                recovery = None
            except MoveIncomplete as exc:
                default_gap_incomplete = True
                recovery = exc.recovery_path
        finally:
            os.rename = real_rename
        check("the normal host path also preserves a source swapped after lstat",
              (default_gap_incomplete, open(src, "rb").read(),
               open(recovery, "rb").read() if recovery else None,
               os.path.lexists(dst)),
              (True, b"native late source", b"native planned source", False))

        source_dir = os.path.join(folder, "directory-gap-source")
        os.mkdir(source_dir)
        put(source_dir, "planned.txt", b"planned directory")
        expected = file_identity(source_dir)
        original_dir = os.path.join(folder, "directory-gap-original")
        target_dir = os.path.join(folder, "directory-gap-target")
        real_native = globals()["_native_noreplace"]
        injected = {"done": False}

        def swap_directory_before_private_move(source, target):
            if source == source_dir and not injected["done"]:
                injected["done"] = True
                os.rename(source_dir, original_dir)
                os.mkdir(source_dir)
                put(source_dir, "late.txt", b"late directory")
                os.rename(source_dir, target)
                return True
            return real_native(source, target)

        globals()["_native_noreplace"] = swap_directory_before_private_move
        try:
            try:
                move_noreplace(source_dir, target_dir, expected=expected)
                directory_gap_incomplete = False
                recovery = None
            except MoveIncomplete as exc:
                directory_gap_incomplete = True
                recovery = exc.recovery_path
        finally:
            globals()["_native_noreplace"] = real_native
        check("a distinct directory swapped after lstat stays in recovery",
              (directory_gap_incomplete,
               open(os.path.join(original_dir, "planned.txt"), "rb").read(),
               open(os.path.join(recovery, "late.txt"), "rb").read()
               if recovery else None,
               os.path.lexists(source_dir), os.path.lexists(target_dir)),
              (True, b"planned directory", b"late directory", False, False))

        snapshot_target = put(folder, "public-snapshot", b"snapshot bytes")
        snapshot = regular_file_snapshot(snapshot_target)
        check("the public snapshot carries identity, digest, mode, and size",
              (snapshot.identity == file_identity(snapshot_target),
               snapshot.digest == hashlib.sha256(b"snapshot bytes").hexdigest(),
               snapshot.size),
              (True, True, len(b"snapshot bytes")))

        snapshot_alias = os.path.join(folder, "public-snapshot-alias")
        os.link(snapshot_target, snapshot_alias)
        check("a publication hard link does not invalidate the snapshot token",
              regular_file_snapshot(snapshot_alias), snapshot)

        snapshot_link = os.path.join(folder, "public-snapshot-symlink")
        try:
            os.symlink(snapshot_target, snapshot_link)
        except (OSError, NotImplementedError):
            symlink_refused = True       # host cannot create the adversary
        else:
            try:
                regular_file_snapshot(snapshot_link)
                symlink_refused = False
            except OSError:
                symlink_refused = True
        check("the public snapshot refuses a leaf symlink", symlink_refused,
              True)

        snapshot_race = put(folder, "public-snapshot-race", b"before")
        real_lstat = os.lstat
        lstat_calls = {"target": 0}

        def mutate_before_final_snapshot(path, *args, **kwargs):
            if os.path.abspath(os.fspath(path)) == os.path.abspath(snapshot_race):
                lstat_calls["target"] += 1
                if lstat_calls["target"] == 3:
                    with open(snapshot_race, "wb") as fh:
                        fh.write(b"changed during snapshot")
            return real_lstat(path, *args, **kwargs)

        os.lstat = mutate_before_final_snapshot
        try:
            try:
                regular_file_snapshot(snapshot_race)
                snapshot_race_refused = False
            except OSError:
                snapshot_race_refused = True
        finally:
            os.lstat = real_lstat
        check("the public snapshot refuses a pathname changed during read",
              (snapshot_race_refused, open(snapshot_race, "rb").read()),
              (True, b"changed during snapshot"))

        def byte_snapshot(path):
            with open(path, "rb") as fh:
                return file_identity(path), fh.read()

        cross_target = put(folder, "cross-device-target", b"old")
        cross_expected = byte_snapshot(cross_target)
        with tempfile.TemporaryDirectory(
                prefix=".cross-device-stage-", dir=folder) as cross_stage:
            cross_staged = put(cross_stage, "replacement", b"new")
            real_stat = os.stat

            class OtherDevice:
                st_dev = os.lstat(cross_staged).st_dev + 1

            def different_target_device(path, *args, **kwargs):
                if os.path.abspath(os.fspath(path)) == os.path.abspath(folder):
                    return OtherDevice()
                return real_stat(path, *args, **kwargs)

            os.stat = different_target_device
            try:
                try:
                    replace_expected(cross_staged, cross_target,
                                     cross_expected, byte_snapshot,
                                     cross_stage, stage_parent=folder)
                    cross_refused = False
                except LinkUnavailable:
                    cross_refused = True
            finally:
                os.stat = real_stat
            check("cross-device replacement is refused before displacement",
                  (cross_refused, open(cross_target, "rb").read(),
                   os.path.lexists(os.path.join(
                       cross_stage, ".atomic-displaced"))),
                  (True, b"old", False))

        target = put(folder, "replace-target", b"old text")
        expected = regular_file_snapshot(target)
        with tempfile.TemporaryDirectory(
                prefix=".replace-stage-", dir=folder) as stage:
            staged = put(stage, "replacement", b"new text")
            published = replace_expected(
                staged, target, expected, regular_file_snapshot, stage,
                stage_parent=folder)
            check("expected replacement is published and read back",
                  published, regular_file_snapshot(target))

        target = put(folder, "unavailable-displacement-target", b"old text")
        expected = regular_file_snapshot(target)
        with tempfile.TemporaryDirectory(
                prefix=".unavailable-displacement-stage-", dir=folder) as stage:
            staged = put(stage, "replacement", b"new text")
            real_move = globals()["move_noreplace"]

            def refuse_displacement(source, destination, **kwargs):
                if source == target and destination.endswith(".atomic-displaced"):
                    cause = OSError(errno.ENOTSUP,
                                    "injected displacement capability failure")
                    raise LinkUnavailable(source, destination, cause)
                return real_move(source, destination, **kwargs)

            globals()["move_noreplace"] = refuse_displacement
            try:
                try:
                    replace_expected(
                        staged, target, expected, regular_file_snapshot, stage,
                        stage_parent=folder)
                    displacement_error = None
                except LinkUnavailable as exc:
                    displacement_error = exc
            finally:
                globals()["move_noreplace"] = real_move
            check("a displacement capability error keeps its type and draft",
                  (isinstance(displacement_error, LinkUnavailable),
                   bool(displacement_error and displacement_error.keep_stage),
                   getattr(displacement_error, "staging_path", None),
                   open(target, "rb").read(), open(staged, "rb").read()),
                  (True, True, stage, b"old text", b"new text"))

        target = put(folder, "unavailable-publication-target", b"old text")
        expected = regular_file_snapshot(target)
        with tempfile.TemporaryDirectory(
                prefix=".unavailable-publication-stage-", dir=folder) as stage:
            staged = put(stage, "replacement", b"new text")
            real_link = globals()["link_noreplace"]

            def refuse_replacement_link(source, destination):
                if source == staged and destination == target:
                    cause = OSError(errno.ENOTSUP,
                                    "injected publication capability failure")
                    raise LinkUnavailable(source, destination, cause)
                return real_link(source, destination)

            globals()["link_noreplace"] = refuse_replacement_link
            try:
                try:
                    replace_expected(
                        staged, target, expected, regular_file_snapshot, stage,
                        stage_parent=folder)
                    publication_error = None
                except LinkUnavailable as exc:
                    publication_error = exc
            finally:
                globals()["link_noreplace"] = real_link
            check("a late link failure restores the predecessor and keeps the draft",
                  (isinstance(publication_error, LinkUnavailable),
                   bool(publication_error and publication_error.keep_stage),
                   getattr(publication_error, "staging_path", None),
                   "restored to its original path" in str(publication_error),
                   open(target, "rb").read(), open(staged, "rb").read()),
                  (True, True, stage, True, b"old text", b"new text"))

        target = put(folder, "reused-stage-target", b"old text")
        expected = regular_file_snapshot(target)
        with tempfile.TemporaryDirectory(
                prefix=".reused-stage-", dir=folder) as stage:
            staged = put(stage, "replacement", b"new text")
            residue = put(stage, ".atomic-observed", b"prior state")
            try:
                replace_expected(
                    staged, target, expected, regular_file_snapshot, stage,
                    stage_parent=folder)
                reused_refused = False
                message = ""
                recovery = None
            except PublicationConflict as exc:
                reused_refused = True
                message = str(exc)
                recovery = exc.recovery_path
            check("a reused stage reports its residue without blaming the target",
                  (reused_refused, "prior publication state" in message,
                   "target changed" in message, recovery,
                   open(target, "rb").read(),
                   os.path.lexists(os.path.join(stage, ".atomic-displaced"))),
                  (True, True, False, residue, b"old text", False))

        with tempfile.TemporaryDirectory(
                prefix=".new-stage-", dir=folder) as stage:
            staged = put(stage, "new-file", b"new file")
            target = os.path.join(folder, "new-target")
            published = publish_new(
                staged, target, regular_file_snapshot, stage_parent=folder)
            check("a new file is published exclusively and read back",
                  published, regular_file_snapshot(target))

        with tempfile.TemporaryDirectory(
                prefix=".edited-new-stage-", dir=folder) as stage:
            staged = put(stage, "new-file", b"new draft")
            target = os.path.join(folder, "edited-new-target")
            real_link = globals()["link_noreplace"]
            state = {"edited": False}

            def edit_new_file_after_link(source, destination):
                real_link(source, destination)
                if (source == staged and destination == target
                        and not state["edited"]):
                    state["edited"] = True
                    with open(destination, "wb") as fh:
                        fh.write(b"late new-file edit")

            globals()["link_noreplace"] = edit_new_file_after_link
            try:
                try:
                    publish_new(
                        staged, target, byte_snapshot, stage_parent=folder)
                    new_edit_refused = False
                except PublicationConflict:
                    new_edit_refused = True
            finally:
                globals()["link_noreplace"] = real_link
            check("new-file readback preserves a post-link editor save",
                  (new_edit_refused, open(target, "rb").read()),
                  (True, b"late new-file edit"))

        target = put(folder, "readback-target", b"old readback")
        expected = byte_snapshot(target)
        with tempfile.TemporaryDirectory(
                prefix=".readback-stage-", dir=folder) as stage:
            staged = put(stage, "replacement", b"new readback")
            real_link = globals()["link_noreplace"]
            state = {"published": False, "failed": False}

            def mark_publication(source, destination):
                real_link(source, destination)
                if source == staged and destination == target:
                    state["published"] = True

            def fail_one_readback(path):
                if (path == target and state["published"]
                        and not state["failed"]):
                    state["failed"] = True
                    raise OSError(errno.EIO, "injected readback failure", path)
                return byte_snapshot(path)

            globals()["link_noreplace"] = mark_publication
            try:
                try:
                    replace_expected(
                        staged, target, expected, fail_one_readback, stage,
                        stage_parent=folder)
                    readback_refused = False
                except PublicationConflict:
                    readback_refused = True
            finally:
                globals()["link_noreplace"] = real_link
            check("a failed readback conditionally restores the predecessor",
                  (readback_refused, open(target, "rb").read()),
                  (True, b"old readback"))

        target = put(folder, "edited-readback-target", b"old predecessor")
        expected = byte_snapshot(target)
        with tempfile.TemporaryDirectory(
                prefix=".edited-readback-stage-", dir=folder) as stage:
            staged = put(stage, "replacement", b"new draft")
            real_link = globals()["link_noreplace"]
            state = {"edited": False}

            def edit_after_publication(source, destination):
                real_link(source, destination)
                if (source == staged and destination == target
                        and not state["edited"]):
                    state["edited"] = True
                    with open(destination, "wb") as fh:
                        fh.write(b"late editor save")

            globals()["link_noreplace"] = edit_after_publication
            try:
                try:
                    replace_expected(
                        staged, target, expected, byte_snapshot, stage,
                        stage_parent=folder)
                    edited_refused = False
                    recovery = None
                except PublicationConflict as exc:
                    edited_refused = True
                    recovery = exc.recovery_path
            finally:
                globals()["link_noreplace"] = real_link
            check("readback rollback never removes a newer editor save",
                  (edited_refused, open(target, "rb").read(),
                   open(recovery, "rb").read() if recovery else None),
                  (True, b"late editor save", b"old predecessor"))

        target = put(folder, "edited-predecessor-target", b"old predecessor")
        expected = byte_snapshot(target)
        with tempfile.TemporaryDirectory(
                prefix=".edited-predecessor-stage-", dir=folder) as stage:
            staged = put(stage, "replacement", b"new replacement")
            state = {"edited": False}

            def edit_predecessor_after_readback(path):
                result = byte_snapshot(path)
                if (path == target and result[1] == b"new replacement"
                        and not state["edited"]):
                    state["edited"] = True
                    with open(os.path.join(stage, ".atomic-displaced"),
                              "wb") as fh:
                        fh.write(b"late predecessor edit")
                return result

            try:
                replace_expected(
                    staged, target, expected,
                    edit_predecessor_after_readback, stage,
                    stage_parent=folder)
                predecessor_refused = False
            except PublicationConflict:
                predecessor_refused = True
            check("a predecessor edited after publication is restored",
                  (predecessor_refused, open(target, "rb").read()),
                  (True, b"late predecessor edit"))

    failed = [case for case in cases if not case[1]]
    for label, ok, got, want in cases:
        if not ok:
            print("FAIL  %s\n        got  %r\n        want %r"
                  % (label, got, want))
    print("%d/%d self-test cases pass" %
          (len(cases) - len(failed), len(cases)))
    return 1 if failed else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true",
                        help="run the built-in adversarial cases")
    args = parser.parse_args(argv)
    if args.test:
        return run_self_test()
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
