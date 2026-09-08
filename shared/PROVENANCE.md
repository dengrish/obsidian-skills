# Note provenance

Record the producing skill when creating a Markdown note, including Wiki
entries, article summaries and polished clippings, MOCs, investment research,
and suggestion logs. This is publication metadata, not an extra section of
the note. Do not stamp original sources, extracted text, PDFs, images, helper
sidecars, queues, or temporary reports merely because a workflow handles them.

Use the active installed plugin's bundled `provenance.json` and helper. Never
infer a release from the latest GitHub commit, a development checkout, a cache
directory name, another plugin, or the date of a note. The helper verifies the
installed distribution before producing a record; missing or inconsistent
provenance blocks stamping and publication of the affected note. It does not
authorize modifying a cache, fetching code, or installing an update.

For `feed-collect` account notes only, keep this same verified producer record
in the private collection state alongside the note's publication digest. These
notes contain properties and posts, with no provenance footer or metadata
section. The collector preserves a known creator when migrating its existing
footer to state and records the current updater on substantive changes. This
exception does not apply to stock-research reports or suggestion logs.

## Stamp the reviewed draft

After the note's content is settled, use the same Python environment as the
active skill. `<skill-name>` is its loaded frontmatter `name`, without a plugin
prefix; `<plugin>` is the installed plugin directory resolved in runtime setup.

```bash
python3 '<plugin>/shared/scripts/note_provenance.py' inspect \
    --plugin '<plugin>' --skill '<skill-name>'
python3 '<plugin>/shared/scripts/note_provenance.py' stamp \
    --plugin '<plugin>' --skill '<skill-name>' \
    --draft '<scratch>/note.md' --output '<scratch>/note-stamped.md'
```

For an authorized edit to an existing note, also pass
`--previous '<scratch>/original-note.md'`, using the complete bytes retained
when that note was read. Keep that original snapshot as the publication
precondition; rereading the live path to stamp a draft must not replace it.
The output path must be a new scratch path, never a vault destination or the
input draft. Validate the stamped result, publish those exact bytes through
the active workflow's guarded write, and verify the public bytes afterward.
The stamping command itself does not publish a note or expand edit authority.

Stamp only a note this skill actually creates or changes. Preserve known
`generated_by` on edits and record the current skill as `updated_by`. For a
historical note without provenance, creation remains `generated_by: null`;
only the verified update is attributed. Do not guess its original producer or
bulk-edit unchanged notes just to fill missing metadata. An unchanged body is
a no-op: retain the complete original bytes, even when a newer skill ran.
For a new suggestion log, record the skill that actually initialized it, not
the skill named by the log's filename. A sibling workflow invoked for its own
output records its own skill; a consumer merely following shared writing rules
records itself, for example `knowledge:wiki-add`, not `knowledge:wiki-build`.
Pure file moves and mechanical reference repairs by a helper preserve the
existing attribution; they do not claim to regenerate the note's content.

## Stored identity and history

The helper writes one final line, separated from the note by a blank line:

```text
<!-- skill-provenance: {JSON record supplied by the helper} -->
```

The schema-1 record contains `generated_by` and, after an authorized change,
`updated_by`. Each known producer records its qualified skill name,
`plugin_version`, full `source_commit`, `source_url`, `source_status`, and
`runtime_sha256`. The commit links to the canonical GitHub source snapshot;
the SHA-256 fingerprint identifies the verified installed runtime bytes even
if version numbers are later reused. A plugin release versions all its skills;
there is no independent per-skill number to invent. Keep full hashes in the
note rather than shortening them.

`source_status: committed` means the bundled source snapshot is tied to that
commit. Development builds with uncommitted inputs use `uncommitted`, and
builds without sufficient Git history use `unavailable`; both leave the commit
and URL null rather than falsely labeling changed code with an earlier commit.
The runtime fingerprint still identifies their content. This metadata records
distributed code identity, not the model, Python environment or bytecode caches,
external data versions, or proof that every
instruction was followed. Keep research sources and evidence in the note's
ordinary source fields or visible research record.

The footer is the sole metadata exception to MOCs' outline-only format and
investment notes' prohibition on hidden content. It contains no reasoning,
financial state, links for navigation, or source evidence. Leave all existing
frontmatter schemas unchanged. Place it after all prose, lists, and flashcards,
with a blank line so it cannot become card scheduling metadata. An otherwise
empty generated MOC may contain only the footer. Preserve it when consuming a
note; malformed, duplicate, or misplaced records need diagnosis, not silent
removal or invented replacement. An active skill may fix metadata only when
the correct attribution is established and the note is already within scope.
