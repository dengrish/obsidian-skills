# Publishing vault files without clobbering later edits

Read this before a workflow creates, replaces, or removes a vault artifact.
The user's permission to edit a file applies to the version the workflow
inspected. It does not extend to a different file or a newer editor save that
arrives after planning.

## Snapshot the version being edited

For an existing regular file, read its complete bytes and filesystem identity
from the same open descriptor. Keep both as the expected snapshot. Reject
symlinks, directories, unreadable files, and any identity or byte change before
publication. A pathname-only check, modification time alone, or a second
`exists()` call does not establish that the occupant is still the inspected
file.

For generated sidecars and multi-file operations, take the snapshot when the
content used to derive the replacement is read. Taking a fresh snapshot only
at publication would silently adopt and overwrite an intervening edit instead
of detecting a stale plan.

## Stage complete bytes off the public path

A working draft may live in any approved scratch location. Before publication,
copy its complete reviewed bytes into a unique private temporary directory on
the **target filesystem**. Keep that final stage outside flat or recursively
scanned output folders, so an interrupted draft cannot be mistaken for a note,
image, or sidecar. Preserve the existing file's permissions when replacing it.

Resolve the destination directory before choosing that private stage parent.
If `Wiki/`, `Articles/`, or `Sources/Images/` is a directory symlink, a sibling
of its logical path may be on another filesystem; stage beside the resolved
real directory instead. Continue publishing to the requested logical pathname
so the vault layout remains unchanged. If a same-filesystem private stage
cannot be established, retain the draft and stop rather than falling back to a
cross-device copy into the public name.

Publish a new pathname with an exclusive primitive such as a hard link from
the staged regular file. Any occupant, including a dangling symlink or a file
that appeared after preflight, makes publication fail unchanged. Never turn
`path does not exist` followed by `os.replace`, ordinary `mv`, or a write to the
final pathname into a creation protocol.

## Replace only the snapshotted occupant

An `unchanged` check immediately followed by `os.replace` still has a race
between the two operations. Use this guarded displacement sequence instead:

1. Hard-link the current public regular file into private staging and verify
   that link against the expected identity and bytes.
2. Move the current public directory entry to another unused private staging
   name. This move has no occupied destination and therefore overwrites
   nothing.
3. Verify that the displaced entry is the same expected inode and bytes as the
   observed link. If another occupant won the gap, restore it to the public
   name with exclusive creation.
4. Link the completed replacement into the now-empty public name with exclusive
   creation. A new occupant in this gap makes the link fail; restore the
   displaced file exclusively.
5. Remove the displaced expected version only after the new file is published
   and read back successfully.

If exclusive restoration is blocked because another writer has already taken
the public name, preserve the displaced file in a named recovery directory on
the same filesystem and report both paths. Never overwrite the new occupant to
make rollback look complete. If the filesystem cannot provide the required
link or move semantics, leave the staged draft and stop.

Repository Python helpers use `shared/scripts/atomic_move.py` for exclusive
moves, new-file publication, expected-file replacement, and conditional
removal. Its `set_private_mode` helper preserves staged permissions on hosts
with or without `os.fchmod`. Reuse those primitives instead of maintaining a
workflow-local copy.

## Remove or move an old pathname conditionally

Do not check an old path and then call `remove` or `unlink`: a later occupant
can arrive in the gap. Displace the entry into private staging, verify the
displaced identity and bytes against the expected snapshot, and delete only
the verified version. Restore or preserve any mismatch by the same rule above.

Exclusive destination moves must also verify the moved source identity. A
hard-link-then-unlink fallback can leave both names when unlinking the source
fails; callers must record and recover that partial state rather than claiming
that no move occurred.

## Multi-file operations

Per-file guards prevent data loss; they do not make a group of writes a single
transaction. Record every completed publication and roll it back only while
its published snapshot remains unchanged. If a rollback encounters a newer
edit, retain it, name the mixed state, and stop. For a hierarchy closure or
another derived group, re-read the current files and re-derive the complete
authorized group before retrying.
