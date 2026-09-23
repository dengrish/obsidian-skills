# Plugin build identity

Markdown notes do not carry skill-provenance footers. The bundled
`provenance.json` identifies the plugin release, source commit and runtime
fingerprint. Feed collection and stock dossier helpers may retain verified
producer records in their private operational state; those records are not
note content or research evidence.

`shared/scripts/note_provenance.py inspect --plugin '<plugin>' --skill '<skill-name>'`
verifies the installed bundle and reports its identity without writing files.
Use the helper shipped by that plugin. The helper has no note-stamping command.

Legacy readers still recognize a valid final footer so existing archives,
flashcards and source notes remain readable. They do not infer missing creators
or add or refresh footers. Malformed legacy metadata remains a diagnostic,
not permission to discard unrelated note content.

A committed build names its exact source revision. Development builds with
uncommitted inputs use `uncommitted`; builds without sufficient Git history
use `unavailable`. Both leave the commit and URL null. The runtime fingerprint
identifies distributed bytes, not the model, Python environment, external data
versions, research correctness or proof that instructions were followed.
