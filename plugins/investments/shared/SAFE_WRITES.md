# Publishing vault files without clobbering later edits

Read this before a workflow creates, replaces, or removes a vault artifact.
The user's permission to edit a file applies to the version the workflow
inspected. It does not extend to a different file or a newer editor save that
arrives after planning. A workflow that publishes, removes or moves regular
files with `publish_files.py` needs only that command's documented steps; the
rest of this guide governs writes it does not perform, such as a case
respelling or a new file that keeps another file's permissions, which use a
private driver.

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

A working draft belongs in the current run's owned `<scratch>` directory. Before publication,
copy its complete reviewed bytes into a unique private temporary directory on
the **target filesystem**. Keep that final stage outside flat or recursively
scanned output folders, so an interrupted draft cannot be mistaken for a note,
image, or sidecar. Preserve the existing file's permissions when replacing it.
Ordinary scratch follows [RUNTIME.md](RUNTIME.md#one-owned-scratch-directory-per-run);
this hidden same-filesystem final stage is a separate publication requirement
and may sit inside the vault outside scanned folders. Keep existing helper
staging/recovery names and guards; do not relocate them, or this final stage,
into `<scratch>`.

Resolve the destination directory before choosing that private stage parent.
Follow the active workflow's directory-ownership rules first: this protocol
does not permit a symlink where that workflow rejects one. For a permitted
directory symlink, a sibling of its logical path may be on another filesystem;
stage beside the resolved real directory instead. Continue publishing to the
requested logical pathname so the vault layout remains unchanged. If a same-filesystem private stage
cannot be established, retain the draft and stop rather than falling back to a
cross-device copy into the public name.

Publish a new pathname with an exclusive primitive such as a hard link from
the staged regular file. Any occupant, including a dangling symlink or a file
that appeared after preflight, makes publication fail unchanged. Never turn
`path does not exist` followed by `os.replace`, ordinary `mv`, or a write to the
final pathname into a creation protocol.

These regular-file primitives require hard-link support and a staging file on
the destination filesystem. FAT/exFAT and some network mounts cannot provide
that guarantee. The helper reports this capability limit as `LinkUnavailable`,
separately from a concurrent-edit conflict; retain the staged bytes and name
the filesystem limitation. Do not retry through `copy`, `os.replace`, or a
cross-device move, because each would remove the no-clobber guarantee.

## Replace only the snapshotted occupant

An `unchanged` check immediately followed by `os.replace` still has a race
between the two operations. Use this guarded displacement sequence instead;
Python writers get it from `replace_expected` and `remove_expected`
([the shared API](#call-the-shared-python-api)) and do not reimplement it:

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
link or move semantics, leave the staged draft and stop with the distinct
capability error above.

Repository Python helpers use `shared/scripts/atomic_move.py` for exclusive
moves, new-file publication, expected-file replacement, and conditional
removal. Its `set_private_mode` helper preserves staged permissions through the
open file descriptor. Reuse those primitives instead of maintaining a
workflow-local copy.

### Call the shared Python API

`atomic_move.py` is a Python import library, not a publication command. Its
command line intentionally exposes only `--test`. Do not invent positional
arguments or interpolate a vault path or note bytes into `python -c`, a shell
heredoc, or command text. When a workflow-specific writer exists, use it.
For publishing reviewed regular files, `shared/scripts/publish_files.py`
provides this recipe as a CLI (`snapshot`, `verify`, `publish`); its `remove`
and `move` commands perform the conditional removal and no-replace move below
for snapshotted paths, and a moved destination is re-snapshotted with
`snapshot --replace` before anything is published to it. Use it instead of a
private driver unless the operation needs a primitive the CLI does not offer.
Otherwise, put the publication logic in a private Python driver, pass paths as
ordinary `sys.argv` values, and import `atomic_move` after putting the trusted
plugin `shared/scripts/` directory first on `sys.path`, using the actual plugin
path resolved under [runtime setup](RUNTIME.md#resolve-the-paths-before-acting).
Shipped skill scripts carry their own helper-discovery bootstrap.

Use one snapshot function throughout the operation. The shared
`regular_file_snapshot(path)` rejects leaf symlinks and non-regular files,
reads identity and content from one stable descriptor, and returns an
equality-comparable token whose `.mode` can be copied to a replacement stage.
Capture the expected token **when the public bytes used to make the decision
are read**, and retain that exact token through review; taking it only when
publication begins would adopt an intervening edit:

```python
snapshot = atomic_move.regular_file_snapshot
expected = snapshot(target) if os.path.lexists(target) else None
# Read/derive/review the complete replacement while retaining `expected`.
```

Once the reviewed bytes have been copied to `staged` in a unique private
`stage_dir` on the target filesystem, flushed, and given `expected.mode` for a
replacement, publish with the matching programmatic call:

```python
if expected is None:
    published = atomic_move.publish_new(
        staged, target, snapshot, stage_parent)
else:
    published = atomic_move.replace_expected(
        staged, target, expected, snapshot, stage_dir,
        stage_parent=stage_parent)
```

Here `stage_parent` is outside the resolved public output directory and
`stage_dir` is a fresh unique private child for this one operation. Never reuse
it for another replacement or removal, including rollback: the helper keeps
observation/recovery entries there even after success. `published` is the exact public
snapshot returned after readback. Keep `stage_dir` and report its path on **any**
exception, including `LinkUnavailable`; clean it only after success.

For an authorized old-path cleanup, create another fresh `stage_dir` first,
for example with `tempfile.mkdtemp(prefix=".atomic-remove-", dir=stage_parent)`
(the helper refuses a missing directory). Then pass the original token and the
same callback to `remove_expected(target, expected, snapshot, stage_dir,
stage_parent=stage_parent)`.

For a move, `move_noreplace(src, dst, expected=identity,
stage_parent=stage_parent)` takes only the source identity captured at
planning, a retained token's `.identity` or `atomic_move.file_identity(src)`,
never the whole token. It checks identity, not bytes: when the bytes decided
the move, first confirm that `snapshot(src)` still equals the retained token.
Never replace any expected value with a fresh snapshot at commit time.

## Remove or move an old pathname conditionally

Do not check an old path and then call `remove` or `unlink`: a later occupant
can arrive in the gap. Displace the entry into private staging, verify the
displaced identity and bytes against the expected snapshot, and delete only
the verified version; `remove_expected` performs the displacement and check.
Restore or preserve any mismatch by the same rule above.

Exclusive destination moves must also verify the moved source identity, as
`move_noreplace` does. Its `MoveIncomplete` error means partial state:
preserve and report both public paths and its `recovery_paths` rather than
claiming that no move occurred. A leftover `.atomic-move-*` directory is
recovery state, not disposable cache.

## Multi-file operations

Per-file guards prevent data loss; they do not make a group of writes a single
transaction. Give each replacement/removal its own fresh `stage_dir`; a shared
`stage_parent` is fine. Use another fresh child for each rollback operation,
preserving any failed stage for recovery. Record every completed publication and roll it back only while
its published snapshot remains unchanged. If a rollback encounters a newer
edit, retain it, name the mixed state, and stop. For a hierarchy closure or
another derived group, re-read the current files and re-derive the complete
authorized group before retrying.
