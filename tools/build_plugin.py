#!/usr/bin/env python3
"""Generate the Codex manifest and a reproducible, complete plugin archive."""

import argparse
import io
import json
from pathlib import Path
import zipfile


def codex_manifest(root):
    """Keep common metadata authored once; add only Codex presentation fields."""
    manifest = json.loads((root / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    manifest["skills"] = "./skills/"
    manifest["interface"] = {
        "displayName": "Obsidian",
        "shortDescription": "Turn papers and clippings into a maintained Obsidian vault",
        "longDescription": manifest["description"],
        "developerName": manifest["author"]["name"],
        "category": "Productivity",
        "capabilities": ["Read", "Write"],
        "defaultPrompt": [
            "Organize the PDFs and process the web clippings in my Obsidian inbox.",
            "Summarize a research paper with its key figures in my Obsidian vault.",
            "Audit the wiki entries and rebuild my maps of content.",
        ],
    }
    return (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def package_files(root):
    """An allowlist keeps local environments, vault data and Git state out."""
    files = {}
    for name in ("AGENTS.md", "CLAUDE.md", "README.md", "requirements.txt", "requirements-dev.txt"):
        files[name] = (root / name).read_bytes()
    for name in (".claude-plugin", "skills", "shared", "tests", "tools"):
        for path in sorted((root / name).rglob("*")):
            if path.is_file() and path.suffix in (".md", ".py", ".json", ".txt"):
                if "__pycache__" not in path.parts:
                    files[path.relative_to(root).as_posix()] = path.read_bytes()
    files[".codex-plugin/plugin.json"] = codex_manifest(root)
    return files


def archive_bytes(files):
    """Stable order, timestamps and modes make rebuilds byte-for-byte identical."""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
    return output.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if generated files are stale; write nothing")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    outputs = {
        root / ".codex-plugin/plugin.json": codex_manifest(root),
        root / "obsidian.plugin": archive_bytes(package_files(root)),
    }
    stale = [path for path, content in outputs.items()
             if not path.is_file() or path.read_bytes() != content]
    if args.check:
        for path in stale:
            print("Stale or missing: " + str(path.relative_to(root)))
        if stale:
            print("Run python3 tools/build_plugin.py")
        else:
            print("Codex manifest and obsidian.plugin match the source tree.")
        return int(bool(stale))
    for path in stale:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(outputs[path])
        print("Built " + str(path.relative_to(root)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
