"""No-clobber moves and verified file publication shared by vault workflows.

``move_noreplace(src, dst)`` either moves one filesystem entry while ``dst``
is still unoccupied, or raises without replacing it. Regular files retain the
authorized inode and conditionally displace the source before publication;
directories use a host exclusive-rename primitive or fail closed.

``publish_new``, ``replace_expected`` and ``remove_expected`` implement the
shared staged-publication protocol for regular files, including readback and
conditional rollback of only the snapshot the caller authorized.

Run ``python3 atomic_move.py --test`` for the adversarial cases.
"""

import argparse
import ctypes
import errno
import os
import shutil
import stat
import sys
import tempfile


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


def file_identity(path):
    """Stable directory-entry identity without following a symlink."""
    item = os.lstat(path)
    return item.st_dev, item.st_ino, stat.S_IFMT(item.st_mode)


def link_noreplace(source, target):
    """Expose one regular inode atomically only at an unoccupied name."""
    try:
        os.link(source, target, follow_symlinks=False)
    except (TypeError, NotImplementedError):
        os.link(source, target)


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
    except PublicationConflict:
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
    :class:`PublicationConflict` has ``keep_stage`` true. A named recovery path
    is exposed on the exception whenever the displaced predecessor could not
    reclaim the public name.
    """
    stage_parent = stage_parent or os.path.dirname(stage_dir)
    try:
        if not stat.S_ISREG(os.lstat(staged).st_mode):
            raise OSError(errno.EINVAL, "staged publication is not a regular file",
                          staged)
        replacement = snapshot(staged)
    except (OSError, UnicodeError) as exc:
        raise PublicationConflict(
            "%s could not be verified before publication (%s: %s)" %
            (staged, type(exc).__name__, exc)) from exc
    displaced = _displace_expected(
        target, expected, snapshot, stage_dir, stage_parent, recovery_prefix)
    try:
        link_noreplace(staged, target)
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
        link_noreplace(staged, target)
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

        def byte_snapshot(path):
            with open(path, "rb") as fh:
                return file_identity(path), fh.read()

        target = put(folder, "replace-target", b"old text")
        expected = byte_snapshot(target)
        with tempfile.TemporaryDirectory(
                prefix=".replace-stage-", dir=folder) as stage:
            staged = put(stage, "replacement", b"new text")
            published = replace_expected(
                staged, target, expected, byte_snapshot, stage,
                stage_parent=folder)
            check("expected replacement is published and read back",
                  (published, byte_snapshot(target)[1]),
                  (byte_snapshot(target), b"new text"))

        with tempfile.TemporaryDirectory(
                prefix=".new-stage-", dir=folder) as stage:
            staged = put(stage, "new-file", b"new file")
            target = os.path.join(folder, "new-target")
            published = publish_new(
                staged, target, byte_snapshot, stage_parent=folder)
            check("a new file is published exclusively and read back",
                  (published, byte_snapshot(target)[1]),
                  (byte_snapshot(target), b"new file"))

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
