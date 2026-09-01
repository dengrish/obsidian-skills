#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""find_collisions.py -- run wiki-builder's collision probes over candidates.

Runs the collision workflow described in references/merge.md. Every probe
compares candidates with existing slugs and aliases, and with other candidates
in the same source run. A match is evidence for a decision, not blanket
permission to merge notes.

PROBES:
  a  slug-equality        candidate slug compared as-is
  b  mu-variant           both U+00B5 / U+03BC spellings probed
  c  singular-plural      plural and singular forms probed
  d  hyphenation-collapse hyphens stripped from both sides
  e  word-order           slug tokenised on "-", tokens sorted, compared
  f  stem-morphology      light per-token suffix normalization
  g  token-superset       one stemmed token set extends the other by at most two

VERDICTS
  create      no probe fired
  merge       probe (a) or (b) fired -- same entity under a different
              spelling of the same slug, with one existing owner;
              multiple existing owners require adjudication
  adjudicate  near-duplicate signals, multiple owners or peer collisions
              require a source-based identity decision. Probes (c)–(g)
              never establish identity by themselves; related techniques
              and process/tool/unit terms may need separate qualified titles.

Candidate-to-candidate matches carry ``matched_via: "candidate"`` and also
appear in ``candidate_collisions``. Review them before writing either entry.
Probes (f) and (g) are enabled by default and can be disabled independently.
The token-superset probe is deliberately absent from wiki-linter's whole-vault
sweep, where qualified terms alongside broader concepts are often intentional.

Module use:
    from find_collisions import check_candidates, load_index
    idx = load_index("index.json")
    report = check_candidates(["Masked language modeling"], idx)

CLI:
    find_collisions.py --index index.json --title "Foo" [--title ...]
    find_collisions.py --index index.json --titles titles.json
        titles.json is either ["Foo", "Bar"] or [{"title": "Foo"}, ...]
    find_collisions.py --wiki '<vault>/Wiki' --title "Foo"   (indexes on the fly)
      [--no-stem]      probe (f) off
      [--no-superset]  probe (g), the token-superset extension, off
      [--no-peers]     skip the candidate-vs-candidate pass
      [--compact]      compact JSON

Output: per candidate {candidate, slug, matches:[{probe, matched_slug,
matched_via, alias?, entry_slug, implies}], verdict}, plus the top-level
``candidate_collisions[]`` and ``summary``.

Gotcha: a title that begins with "-" must use the "=" form, or argparse eats
it as a flag -- find_collisions.py --title=--- (not --title "---").

Exit codes: 0 ok, 2 bad usage / unreadable input.
"""

from __future__ import annotations

import argparse
import json
import os
import unicodedata
import sys

# --- obsidian shared-layer bootstrap (canonical; see shared/CONVENTIONS.md) ---
import os as _os, sys as _sys
_here = _os.path.dirname(_os.path.abspath(__file__))
_env = _os.environ.get("OBSIDIAN_VAULT_SHARED")
if _env:                                   # explicit override: authoritative, no fallback
    _tried = [_os.path.abspath(_os.path.expanduser(_env))]
else:                                      # plugin-relative walk-up, at most 5 levels
    _tried, _d = [], _here
    for _ in range(5):
        _tried.append(_os.path.join(_d, "shared", "scripts"))
        _d = _os.path.dirname(_d)
_shared = next((_p for _p in _tried if _os.path.isdir(_p)), None)
if _shared is None:
    raise SystemExit("""obsidian: cannot find the plugin's shared/scripts/ folder, which holds
the one canonical copy of the conventions this script depends on.
Looked for:
  %s
Fix: install the whole plugin tree, or set OBSIDIAN_VAULT_SHARED to the
shared/scripts/ directory (unset it to use the plugin-relative walk-up).
Do NOT paste a second copy of the algorithm into this skill -- a divergent
copy is the bug the shared layer exists to prevent.""" % "\n  ".join(_tried))
_sys.path[:] = [_p for _p in _sys.path if _p not in (_shared, _here)]
_sys.path.insert(0, _shared)               # shared/scripts/ FIRST
_sys.path.append(_here)                    # own dir LAST: a local copy cannot shadow it
# --- end bootstrap ---

from slugify import SlugError, mu_variants, slug_stem  # noqa: E402
# NO SINGULARISER LIVES HERE.  Probes (c) and (e) both turn on which two word
# forms are the same word, and wiki-linter's whole-vault sweep turns on the
# same fact -- CONVENTIONS.md §9 gives that sweep to wiki-linter alone, so a
# near-duplicate pair already sitting in the vault is seen by nothing else.
# The tables below used to live in this file and wiki-linter carried a
# three-rule stripper of its own, which answered "hypotheses" with "hypothes":
# `hypothesis-testing` / `testing-hypotheses` fired here and nowhere else, and
# a pair that got into the vault was reported by nobody.  One implementation,
# in shared/scripts/plurals.py; `python3 shared/scripts/plurals.py --test` is
# the conformance suite.  Do NOT paste a copy back.
from plurals import (  # noqa: E402
    AMBIGUOUS_IRREGULAR_PLURALS, IRREGULAR_PLURALS, IRREGULAR_SINGULARS,
    VES_IRREGULARS, plural_key, pluralize, real_permutation, singular_forms,
    singular_key, singular_keys, singularize, stem_key, stem_tokens,
    wordorder_key_singular,
)
import vault_index as _vault_index  # noqa: E402

__all__ = [
    "check_candidates", "check_candidate", "load_index", "build_targets",
    "pluralize", "singularize", "singular_forms", "singular_key",
    "singular_keys", "hyphen_key", "wordorder_key", "stem_key", "stem_tokens",
    "PROBES",
]

PROBES = {
    "a-slug-equality": "merge",
    "b-mu-variant": "merge",
    "c-singular-plural": "adjudicate",
    "d-hyphenation-collapse": "adjudicate",
    "e-word-order-permutation": "adjudicate",
    "f-stem-morphology": "adjudicate",   # extension, not one of the five
    "g-token-superset": "adjudicate",    # extension, not one of the five
}

VERDICT_RANK = {"create": 0, "adjudicate": 1, "merge": 2}

STEM_PROBE = "f-stem-morphology"
SUPERSET_PROBE = "g-token-superset"

#: Probe (g) fires only when the two stemmed token sets differ by at most
#: this many tokens: "k-means" ~ "k-means-clustering" is a near-duplicate
#: signal, "model" ~ "deep-convolutional-neural-network-model" is not.
SUPERSET_MAX_EXTRA = 2


def _implies(probe):
    """The verdict a probe implies.

    Probes (f) and (g) are extensions, not among the skill's five, and both
    deliberately fire on pairs the schema may want kept SEPARATE -- (f) on
    process / tool / unit triples (tokenization / tokenizer / token), (g) on
    a qualified title beside its base term.  They can therefore only ever
    ``adjudicate``; a merge verdict from either would silently fuse distinct
    entries.  Hard-coded here rather than only in ``PROBES`` so the invariant
    survives an edit to that table.
    """
    if probe in (STEM_PROBE, SUPERSET_PROBE):
        return "adjudicate"
    return PROBES[probe]

# --------------------------------------------------------------------------
# morphology helpers -- the plural ones are imported from shared/scripts/
# plurals.py (see the note beside that import); only the probe keys with no
# morphology in them are defined here.
# --------------------------------------------------------------------------

def hyphen_key(slug):
    """Probe (d) key: all hyphens stripped."""
    return slug.replace("-", "")


def wordorder_key(slug):
    """Probe (e) key: tokens sorted alphabetically."""
    return "-".join(sorted(t for t in slug.split("-") if t))


# --------------------------------------------------------------------------
# index handling
# --------------------------------------------------------------------------

def load_index(path):
    """Load an index written by ``vault_index.py``.

    Accepts the full index object, a bare list of entry records, or a plain
    ``{slug: {...}}`` mapping.  Returns the normalised full-object form.
    """
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, list):
        data = {"wiki_folder": None, "entries": data}
    elif isinstance(data, dict) and "entries" in data:
        pass
    elif isinstance(data, dict):
        entries = []
        for slug, rec in data.items():
            if rec is not None and not isinstance(rec, dict):
                raise ValueError("index record %r must be an object" % slug)
            rec = dict(rec or {})
            rec.setdefault("slug", slug)
            entries.append(rec)
        data = {"wiki_folder": None, "entries": entries}
    else:
        raise ValueError("unrecognised index shape in %s" % path)
    _validate_index(data)
    return data


def _validate_index(index):
    """Reject malformed lookup data rather than treating it as an empty vault."""
    if not isinstance(index, dict) or not isinstance(index.get("entries"), list):
        raise ValueError("index must contain an entries list")
    if not isinstance(index.get("problems", []), list):
        raise ValueError("index problems must be a list")
    for i, rec in enumerate(index["entries"], 1):
        if not isinstance(rec, dict) or not isinstance(rec.get("slug"), str) or not rec["slug"].strip():
            raise ValueError("index entry %d must be an object with a nonempty slug" % i)
        aliases = rec.get("aliases", [])
        if aliases is None:
            aliases = []
        if not isinstance(aliases, list) or any(not isinstance(a, str) for a in aliases):
            raise ValueError("index entry %d aliases must be a list of strings" % i)
        if not isinstance(rec.get("errors", []), list):
            raise ValueError("index entry %d errors must be a list" % i)


def _index_problems(index):
    """Keep index omissions visible even when a caller supplied a bare list."""
    problems = [str(p) for p in index.get("problems", [])]
    for rec in index["entries"]:
        for error in rec.get("errors", []):
            message = "%s: %s" % (rec.get("relpath") or rec["slug"], error)
            if message not in problems:
                problems.append(message)
    return problems


def build_targets(index):
    """Flatten an index into probe targets.

    Returns a list of dicts:
    ``{slug, via, alias, entry_slug, path}`` -- one for each filename stem
    and one for each alias on each entry.
    """
    _validate_index(index)
    targets = []
    for rec in index.get("entries", []):
        slug = (rec.get("slug") or "").strip()
        if slug:
            targets.append({
                "slug": slug, "via": "filename", "alias": None,
                "entry_slug": slug, "path": rec.get("relpath") or rec.get("path"),
                "is_stub": bool(rec.get("is_stub")),
            })
        for alias in rec.get("aliases") or []:
            alias = (alias or "").strip()
            if not alias:
                continue
            # the aliases field rule requires every alias to already BE a slug, but
            # nothing enforced it, and an alias stored as prose ("receiver
            # operating characteristic") matched no probe key at all -- the
            # entry it should have caught got written a second time.  Slug it
            # here so a malformed alias is still probed; the original string is
            # kept for reporting.  lint_entry.py's 18-alias-form warns about it.
            try:
                alias_slug = slug_stem(alias)
            except SlugError:
                continue
            targets.append({
                "slug": alias_slug, "via": "alias", "alias": alias,
                "entry_slug": slug,
                "path": rec.get("relpath") or rec.get("path"),
                "is_stub": bool(rec.get("is_stub")),
            })
    return targets


# --------------------------------------------------------------------------
# probing
# --------------------------------------------------------------------------

def _candidate_slugs(title, use_stem=True, use_superset=True):
    """All probe keys for one candidate title.  Returns ``(slug, keys, err)``."""
    if not isinstance(title, str) or not title.strip():
        return None, None, "candidate title must be a nonempty string"
    try:
        slug = slug_stem(title)
    except SlugError as exc:
        return None, None, str(exc)

    mu_slugs = set()
    for variant in mu_variants(title):
        try:
            mu_slugs.add(slug_stem(variant))
        except SlugError:
            pass
    mu_slugs.discard(slug)

    keys = {
        "slug": slug,
        "mu": mu_slugs,
        "plural_forms": {singular_key(slug), plural_key(slug)} - {slug},
        "singular": singular_key(slug),
        "singular_set": singular_keys(slug),
        "hyphen": hyphen_key(slug),
        "wordorder": wordorder_key(slug),
        "wordorder_singular": wordorder_key_singular(slug),
        "stem": stem_key(slug) if use_stem else None,
        "superset": stem_tokens(slug) if use_superset else None,
    }
    return slug, keys, None


def _fold(s):
    """Case- and Unicode-folded slug, matching scan_vault.fold_name."""
    return unicodedata.normalize("NFC", (s or "").strip()).casefold()


def _probe_pair(keys, other_slug, use_stem=True, use_superset=True):
    """Which probes fire between a prepared candidate and ``other_slug``?"""
    fired = []
    slug = keys["slug"]

    # Case- and normalization-folded, not raw. The documented vault sits on a
    # case-insensitive volume, so `roc-curve` and `ROC-curve` are ONE file: a
    # raw comparison made the existing entry invisible, returned `create`, and
    # step 4 then wrote `Wiki/roc-curve.md` -- which opens `ROC-curve.md` and
    # replaces a full entry. `scan_vault` and `vault_index` both fold for this
    # reason; the probe that decides whether to create a file did not.
    if slug == other_slug or _fold(slug) == _fold(other_slug):
        fired.append("a-slug-equality")
        return fired                       # identity: no point reporting more

    # Every probe below compares slug STRINGS, and on the documented
    # case-insensitive volume a case variant is the same file -- so a probe
    # that misses it hands back `create` for a name that will overwrite an
    # existing entry. Fold once, here, rather than at nine call sites.
    other_slug = _fold(other_slug)

    if other_slug in keys["mu"]:
        fired.append("b-mu-variant")

    # Probe (c) is symmetric: intersect the two sets of plausible singulars
    # rather than compare two single best guesses.  Comparing best guesses only
    # worked when the CANDIDATE was the plural and the guess happened to be the
    # right one -- "ROC curves" vs roc-curve.md fired nothing.
    if (other_slug in keys["plural_forms"]
            or singular_keys(other_slug) & keys["singular_set"]):
        fired.append("c-singular-plural")

    if hyphen_key(other_slug) == keys["hyphen"]:
        fired.append("d-hyphenation-collapse")

    if wordorder_key(other_slug) == keys["wordorder"]:
        fired.append("e-word-order-permutation")
    elif (wordorder_key_singular(other_slug) == keys["wordorder_singular"]
            and real_permutation(other_slug, slug)):
        # Only a genuine permutation -- if the singularised token SEQUENCES are
        # identical this is a pure plural pair that probe (c) already caught.
        # The guard is `plurals.real_permutation` because wiki-linter's sweep
        # has to draw the same line: a pair the two skills classify differently
        # is one worklist item under two names.
        fired.append("e-word-order-permutation")

    if use_stem and keys["stem"] and stem_key(other_slug) == keys["stem"]:
        # Only when nothing else fired.  Probe (f)'s stemmer collapses plurals
        # too, so before probe (c) was symmetric a plain plural pair
        # (roc-curve / roc-curves) came back labelled "f-stem-morphology" --
        # naming an extension as the cause of a finding that is really a
        # probe-(c) hit, and misdirecting whoever read the report.
        if not fired:
            fired.append("f-stem-morphology")

    if use_superset and keys["superset"] and not fired:
        # Probe (g): one side's stemmed token set properly contains the
        # other's, by at most SUPERSET_MAX_EXTRA tokens.  Every probe above
        # compares whole token multisets, so "K-means clustering" against
        # k-means.md fired nothing and came back `create` -- a duplicate
        # entry.  Proper subset only (equal sets are probe (f)'s hit), and
        # only when nothing else fired, for the reason (f) gives.
        other_toks = stem_tokens(other_slug)
        cand_toks = keys["superset"]
        if ((cand_toks < other_toks or other_toks < cand_toks)
                and abs(len(cand_toks) - len(other_toks)) <= SUPERSET_MAX_EXTRA):
            fired.append("g-token-superset")

    return fired


def check_candidate(title, index, use_stem=True, use_superset=True, peers=None,
                    targets=None, index_problems=None):
    """Probe one candidate title against the vault index (and optional peers).

    ``peers`` is a list of ``(title, slug)`` for the other candidates in the
    same run.  ``targets`` is a prebuilt ``build_targets(index)`` — pass it
    when probing many candidates: rebuilding it per candidate re-slugs every
    alias in the vault each time, which turns a run over a large vault into
    candidates × aliases slug computations for no new information.  Returns
    the per-candidate result dict.
    """
    slug, keys, err = _candidate_slugs(title, use_stem=use_stem,
                                       use_superset=use_superset)
    result = {"candidate": title, "slug": slug, "matches": [], "verdict": "create"}
    if err:
        result["error"] = err
        result["verdict"] = "adjudicate"
        return result

    for target in (build_targets(index) if targets is None else targets):
        other = target["slug"]
        for probe in _probe_pair(keys, other, use_stem=use_stem,
                                 use_superset=use_superset):
            match = {
                "probe": probe,
                "matched_slug": other,
                "matched_via": target["via"],
                "entry_slug": target["entry_slug"],
                "entry_path": target["path"],
                "is_stub": target["is_stub"],
                "implies": _implies(probe),
            }
            if target["via"] == "alias":
                match["alias"] = target["alias"]
            result["matches"].append(match)

    for peer_title, peer_slug in (peers or []):
        if peer_title == title:
            continue
        for probe in _probe_pair(keys, peer_slug, use_stem=use_stem,
                                 use_superset=use_superset):
            result["matches"].append({
                "probe": probe,
                "matched_slug": peer_slug,
                "matched_via": "candidate",
                "matched_candidate": peer_title,
                "implies": _implies(probe),
            })

    # A decisive spelling match does not choose between several existing
    # owners. Keep paths in the identity: two subfolders can contain distinct
    # files with the very same slug. Multiple aliases of ONE entry are safe.
    merge_owners = {(m["entry_slug"], m["entry_path"])
                    for m in result["matches"]
                    if m["matched_via"] != "candidate" and m["implies"] == "merge"}
    if len(merge_owners) > 1:
        result["verdict"] = "adjudicate"
        result["error"] = ("exact spelling matches have %d existing owners; "
                           "resolve the destination before merging; never "
                           "choose an owner by index order" % len(merge_owners))
        for match in result["matches"]:
            if match["implies"] == "merge":
                match["implies"] = "adjudicate"
        return result

    verdict = "create"
    for match in result["matches"]:
        if VERDICT_RANK[match["implies"]] > VERDICT_RANK[verdict]:
            verdict = match["implies"]
    result["verdict"] = verdict
    problems = _index_problems(index) if index_problems is None else index_problems
    if problems and verdict == "create":
        result["verdict"] = "adjudicate"
        result["error"] = ("the index reports %d problem(s); unreadable or malformed "
                           "entries may hide aliases, so creation is not established"
                           % len(problems))
    return result


def check_candidates(titles, index, use_stem=True, use_superset=True,
                     include_peers=True):
    """Probe every candidate title; returns the full report dict."""
    if not isinstance(titles, (list, tuple)) or any(not isinstance(t, str) or not t.strip() for t in titles):
        raise ValueError("candidate titles must be a list of nonempty strings")
    prepared = []
    for title in titles:
        try:
            prepared.append((title, slug_stem(title)))
        except SlugError:
            prepared.append((title, None))

    peers = [(t, s) for t, s in prepared if s] if include_peers else []

    targets = build_targets(index)          # once, not once per candidate
    index_problems = _index_problems(index)
    results = [check_candidate(t, index, use_stem=use_stem,
                               use_superset=use_superset, peers=peers,
                               targets=targets, index_problems=index_problems)
               for t in titles]

    seen_pairs, pairwise = set(), []
    for res in results:
        for match in res["matches"]:
            if match["matched_via"] != "candidate":
                continue
            pair = tuple(sorted([res["candidate"], match["matched_candidate"]]))
            token = pair + (match["probe"],)
            if token in seen_pairs:
                continue
            seen_pairs.add(token)
            pairwise.append({
                "candidates": list(pair),
                "probe": match["probe"],
                "implies": match["implies"],
            })

    return {
        "wiki_folder": index.get("wiki_folder"),
        "indexed_entries": len(index.get("entries", [])),
        "index_problems": index_problems,
        "stem_probe_enabled": use_stem,
        "superset_probe_enabled": use_superset,
        "candidate_count": len(results),
        "results": results,
        "candidate_collisions": pairwise,
        "summary": {
            "create": sum(1 for r in results if r["verdict"] == "create"),
            "merge": sum(1 for r in results if r["verdict"] == "merge"),
            "adjudicate": sum(1 for r in results if r["verdict"] == "adjudicate"),
        },
    }


# --------------------------------------------------------------------------
# self-test
# --------------------------------------------------------------------------
#
# What this pins is the answer to "may step 4 write this file?".  A probe that
# does not fire returns ``create``, and step 4 then writes
# ``Wiki/<slug>.md`` -- which, on the documented case-insensitive volume,
# opens and replaces whatever entry already answers to that name.  So every
# probe gets a firing case AND a not-firing case, and the case-fold half gets
# its own, because that is the miss that ends in a truncated entry.
#
#     python3 find_collisions.py --test

def _st_entry_text(title, aliases=(), stub=False):
    lines = ["---", 'title: "%s"' % title, "type: Concept"]
    if aliases:
        lines.append("aliases:")
        lines.extend('  - "%s"' % a for a in aliases)
    lines.append("sources:")
    lines.append('  - "stub"' if stub else '  - "[[Doe_X_2025.pdf#page=2]]"')
    lines += ["created: 2026-01-01", "updated: 2026-01-02",
              'description: "A worked example used by the self-test."',
              "tags:", '  - "#statistics"', "parents: []", "read: false", "---",
              "**%s** is a worked example." % title, ""]
    return "\n".join(lines)


def _st_fired(result, matched_slug):
    """Which probes fired against one target, sorted."""
    return sorted({m["probe"] for m in result["matches"]
                   if m["matched_slug"] == matched_slug})


def run_self_test():
    import io
    import contextlib
    import shutil
    import tempfile
    cases = []

    def check(label, got, want):
        cases.append((label, got == want, got, want))

    tmp = tempfile.mkdtemp(prefix="find_collisions-selftest-")
    try:
        wiki = os.path.join(tmp, "Wiki")
        os.makedirs(wiki)

        def put(name, text):
            with open(os.path.join(wiki, name), "w", encoding="utf-8") as fh:
                fh.write(text)

        # `ROC-curve.md` is spelled with capitals ON PURPOSE: the probes compare
        # slug strings, and the documented vault sits on a case-insensitive
        # volume where `roc-curve.md` IS this file.
        put("ROC-curve.md", _st_entry_text("ROC curve", aliases=["roc"]))
        put("mu-m.md", _st_entry_text("μm"))
        put("cross-validation.md", _st_entry_text("Cross-validation"))
        put("weight-tying.md", _st_entry_text("Weight tying"))
        put("masked-language-model.md", _st_entry_text("Masked language model"))
        put("random-forest.md", _st_entry_text("Random forest"))
        put("f1-score.md", _st_entry_text(
            "F1 score", aliases=["receiver operating characteristic"]))
        put("k-means.md", _st_entry_text("k-means"))
        put("stochastic-gradient-descent.md",
            _st_entry_text("Stochastic gradient descent"))
        put("deep-convolutional-neural-network.md",
            _st_entry_text("Deep convolutional neural network"))

        index = _vault_index.build_index(wiki)
        check("the fixture vault indexed", index["entry_count"], 10)

        # -- index shapes: all three must flatten to the same target set ----
        path = os.path.join(tmp, "index.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(index, fh)
        as_list = os.path.join(tmp, "list.json")
        with open(as_list, "w", encoding="utf-8") as fh:
            json.dump(index["entries"], fh)
        as_map = os.path.join(tmp, "map.json")
        with open(as_map, "w", encoding="utf-8") as fh:
            json.dump({r["slug"]: r for r in index["entries"]}, fh)
        want_targets = sorted((t["slug"], t["via"]) for t in build_targets(index))
        for label, p in (("full object", path), ("bare list", as_list),
                         ("{slug: rec} map", as_map)):
            check("load_index accepts a %s" % label,
                  sorted((t["slug"], t["via"])
                         for t in build_targets(load_index(p))), want_targets)
        check("build_targets probes filenames AND aliases",
              sorted(t["slug"] for t in build_targets(index) if t["via"] == "alias"),
              ["receiver-operating-characteristic", "roc"])
        check("...slugging a prose alias so it is probed at all",
              [t["alias"] for t in build_targets(index)
               if t["slug"] == "receiver-operating-characteristic"],
              ["receiver operating characteristic"])

        for incomplete in (
                {"entries": [], "problems": ["unreadable wiki directory: private"]},
                {"entries": [{"slug": "existing", "aliases": [],
                              "errors": ["unparseable YAML scalar"]}]}):
            rep = check_candidates(["A new unmatched term"], incomplete)
            check("incomplete index cannot authorize an unmatched create",
                  (rep["results"][0]["verdict"], bool(rep["index_problems"])),
                  ("adjudicate", True))
        malformed_index = os.path.join(tmp, "malformed-index.json")
        for payload in ({"entries": ["bad"]}, {"entries": [{"slug": "x", "aliases": 0}]}):
            with open(malformed_index, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["--index", malformed_index, "--title", "A new term"])
            check("malformed index records are structured CLI errors, never tracebacks",
                  (rc, json.loads(buf.getvalue())["ok"]), (2, False))

        # -- every probe, firing --------------------------------------------
        def probe(title, **kw):
            return check_candidate(title, index, targets=build_targets(index), **kw)

        r = probe("ROC curve")
        check("(a) slug equality fires", _st_fired(r, "ROC-curve"), ["a-slug-equality"])
        check("...and implies merge", r["verdict"], "merge")
        check("...identity short-circuits the other probes",
              len([m for m in r["matches"] if m["matched_slug"] == "ROC-curve"]), 1)

        r = probe("roc curve")
        check("(a) fires case-folded on a lowercase candidate too",
              (_st_fired(r, "ROC-curve"), r["verdict"]),
              (["a-slug-equality"], "merge"))

        r = probe("ROC curves")
        check("(c) singular/plural fires against the CAPITALISED file",
              _st_fired(r, "ROC-curve"), ["c-singular-plural"])
        check("...and implies adjudicate, never merge", r["verdict"], "adjudicate")

        r = probe("ROC")
        check("(a) fires through an ALIAS, not just a filename",
              [(m["probe"], m["matched_via"], m["entry_slug"]) for m in r["matches"]
               if m["matched_via"] == "alias"],
              [("a-slug-equality", "alias", "ROC-curve")])
        check("...and the alias is named in the match",
              [m.get("alias") for m in r["matches"]
               if m["matched_via"] == "alias"], ["roc"])
        check("...while (g) reports the same entry's FILENAME as a superset",
              _st_fired(r, "ROC-curve"), ["g-token-superset"])

        r = probe("µm")
        check("(b) mu-variant fires across the two mu code points",
              _st_fired(r, "mu-m"), ["b-mu-variant"])
        check("...and implies merge", r["verdict"], "merge")

        r = probe("Crossvalidation")
        check("(d) hyphenation-collapse fires",
              _st_fired(r, "cross-validation"), ["d-hyphenation-collapse"])

        r = probe("Tying weights")
        check("(e) word-order fires on the skill's own worked example",
              _st_fired(r, "weight-tying"), ["e-word-order-permutation"])

        r = probe("Model language masked")
        check("(e) fires on a pure token permutation as well",
              _st_fired(r, "masked-language-model"), ["e-word-order-permutation"])

        r = probe("Masked language modeling")
        check("(f) stem-morphology fires where (c), (d) and (e) cannot",
              _st_fired(r, "masked-language-model"), ["f-stem-morphology"])
        check("...and can only ever adjudicate", r["verdict"], "adjudicate")
        r = probe("Masked language modeling", use_stem=False)
        check("--no-stem turns probe (f) off entirely",
              (r["matches"], r["verdict"]), ([], "create"))

        r = probe("K-means clustering")
        check("(g) token-superset fires where every whole-multiset probe misses",
              _st_fired(r, "k-means"), ["g-token-superset"])
        check("...and can only ever adjudicate", r["verdict"], "adjudicate")
        r = probe("Gradient descent")
        check("(g) fires in the other direction too (candidate is the subset)",
              _st_fired(r, "stochastic-gradient-descent"), ["g-token-superset"])
        r = probe("Network")
        check("(g) does NOT fire at a token-set difference of 3",
              _st_fired(r, "deep-convolutional-neural-network"), [])
        r = probe("K-means clustering", use_superset=False)
        check("--no-superset turns probe (g) off entirely",
              (_st_fired(r, "k-means"), r["verdict"]), ([], "create"))

        # -- every probe, NOT firing ----------------------------------------
        r = probe("Gradient boosting")
        check("an unrelated candidate fires nothing and is `create`",
              (r["matches"], r["verdict"]), ([], "create"))
        for title, other in (("ROC curve", "random-forest"),
                             ("ROC curves", "cross-validation"),
                             ("Crossvalidation", "weight-tying"),
                             ("Tying weights", "masked-language-model"),
                             ("µm", "f1-score")):
            check("no probe fires between %r and %s" % (title, other),
                  _st_fired(probe(title), other), [])
        check("probe (f) is suppressed when another probe already fired "
              "(a stem hit must not be reported as the cause of a plural pair)",
              _st_fired(probe("ROC curves"), "ROC-curve"), ["c-singular-plural"])

        # -- verdict arithmetic ---------------------------------------------
        check("a merge match outranks an adjudicate match on the same candidate",
              probe("ROC curve")["verdict"], "merge")
        check("an unsluggable title is an error, and adjudicate not create",
              [probe("機械学習")[k] for k in ("slug", "verdict")]
              + ["error" in probe("機械学習")],
              [None, "adjudicate", True])
        saved = PROBES[STEM_PROBE]
        try:
            PROBES[STEM_PROBE] = "merge"
            check("probe (f) can never imply merge, even if PROBES is edited",
                  _implies(STEM_PROBE), "adjudicate")
        finally:
            PROBES[STEM_PROBE] = saved

        # -- peers: the candidate-vs-candidate pass the skill never specifies -
        empty = {"wiki_folder": None, "entries": []}
        rep = check_candidates(["Masked language model", "Masked language modeling"],
                               empty)
        check("two candidates in ONE run are probed against each other",
              [(c["probe"], c["implies"]) for c in rep["candidate_collisions"]],
              [("f-stem-morphology", "adjudicate")])
        check("...naming both candidates",
              sorted(rep["candidate_collisions"][0]["candidates"]),
              ["Masked language model", "Masked language modeling"])
        check("...and marked matched_via candidate",
              sorted({m["matched_via"] for r in rep["results"] for m in r["matches"]}),
              ["candidate"])
        rep = check_candidates(["Masked language model", "Masked language modeling"],
                               empty, include_peers=False)
        check("--no-peers turns the peer pass off",
              (rep["candidate_collisions"], rep["summary"]["create"]), ([], 2))
        rep = check_candidates(["ROC curve", "ROC curves", "Gradient boosting"], index)
        check("the summary counts each verdict once",
              rep["summary"], {"create": 1, "merge": 1, "adjudicate": 1})
        check("a candidate never collides with itself",
              [c for c in rep["candidate_collisions"]
               if c["candidates"][0] == c["candidates"][1]], [])

        # Distinct physical destinations cannot be reduced to one decisive
        # merge merely because they claim the same filename or alias.
        for label, records in (
                ("duplicate basenames", [("first/shared.md", "Shared", []),
                                         ("second/shared.md", "Shared", [])]),
                ("shared aliases", [("first.md", "First", ["shared"]),
                                    ("second.md", "Second", ["shared"])]),
                ("filename and alias", [("first.md", "First", ["shared"]),
                                        ("shared.md", "Shared", [])])):
            collision_wiki = os.path.join(tmp, label.replace(" ", "-"))
            for rel, title, aliases in records:
                dest = os.path.join(collision_wiki, rel)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "w", encoding="utf-8") as fh:
                    fh.write(_st_entry_text(title, aliases=aliases))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["--wiki", collision_wiki, "--title", "Shared"])
            rep = json.loads(buf.getvalue())
            result = rep["results"][0]
            check("%s require destination adjudication in the public CLI" % label,
                  (rc, result["verdict"], rep["summary"]["merge"],
                   all(m["implies"] == "adjudicate" for m in result["matches"]),
                   "existing owners" in result.get("error", "")),
                  (0, "adjudicate", 0, True, True))
        unique = {"entries": [{"slug": "shared", "aliases": ["shared", "Shared"],
                               "relpath": "shared.md"}]}
        check("several exact spellings on one owner remain a merge",
              check_candidate("Shared", unique)["verdict"], "merge")

        # -- --titles, in each shape a caller actually writes ---------------
        for label, payload, want in (
                ("a bare list of strings", ["Foo", "Bar"], ["Foo", "Bar"]),
                ("a list of {\"title\": ...} objects",
                 [{"title": "Foo"}, {"candidate": "Bar"}, {"name": "Baz"}],
                 ["Foo", "Bar", "Baz"]),
                ("an object with a titles: key", {"titles": ["Foo"]}, ["Foo"]),
                ("an empty list", [], [])):
            tf = os.path.join(tmp, "titles.json")
            with open(tf, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
            check("--titles accepts %s" % label, _load_titles(tf), want)

        for payload in ({"titles": [{"title": 12}]}, {"titles": "not a list"}, [None]):
            with open(tf, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["--index", path, "--titles", tf])
            check("malformed title JSON is a structured CLI error",
                  (rc, json.loads(buf.getvalue())["ok"]), (2, False))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["--index", path, "--title", "   "])
        check("a blank --title is a structured CLI error too",
              (rc, json.loads(buf.getvalue())["ok"]), (2, False))

        # -- the CLI still refuses a real run that is missing an argument ----
        for argv, needle in (([], "--index"), (["--wiki", wiki], "--title")):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = main(argv)
            check("a run missing %s exits 2 and names it" % needle,
                  (rc, needle in buf.getvalue()), (2, True))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [c for c in cases if not c[1]]
    for label, ok, got, want in cases:
        if not ok:
            print("FAIL  %s\n        got  %r\n        want %r" % (label, got, want))
    print("%d/%d self-test cases pass" % (len(cases) - len(failed), len(cases)))
    return 1 if failed else 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _load_titles(path):
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        if "titles" in data:
            data = data["titles"]
        elif "candidates" in data:
            data = data["candidates"]
        else:
            raise ValueError("title object must contain titles or candidates")
    if not isinstance(data, list):
        raise ValueError("candidate titles must be a list")
    titles = []
    for item in data:
        if isinstance(item, str):
            val = item
        elif isinstance(item, dict):
            val = item.get("title") or item.get("candidate") or item.get("name")
        else:
            raise ValueError("every candidate must be a title string or object")
        if not isinstance(val, str) or not val.strip():
            raise ValueError("every candidate title must be a nonempty string")
        titles.append(val)
    return titles


def _build_parser():
    p = argparse.ArgumentParser(
        prog="find_collisions.py",
        description="Run wiki-builder's collision probes for candidate titles "
                    "against a vault index (stdlib only).",
        epilog='example: find_collisions.py --index /tmp/index.json '
               '--title "Masked language modeling"',
    )
    # Neither group is `required=True`: that made `--test` unreachable, since
    # argparse refuses the command line before main() ever runs.  A real run
    # missing either half is refused below instead, by name and with exit 2.
    src = p.add_mutually_exclusive_group()
    src.add_argument("--index", help="JSON index from vault_index.py")
    src.add_argument("--wiki", help="wiki folder to index on the fly instead")
    cand = p.add_mutually_exclusive_group()
    cand.add_argument("--title", action="append",
                      help="a candidate title (repeatable)")
    cand.add_argument("--titles", help="JSON file: a list of titles, or of "
                                       '{"title": ...} objects')
    p.add_argument("--test", action="store_true",
                   help="run the built-in self-test and exit")
    p.add_argument("--no-stem", action="store_true",
                   help="disable probe (f), the non-skill stem-morphology "
                        "extension, for strict five-probe behaviour")
    p.add_argument("--no-superset", action="store_true",
                   help="disable probe (g), the non-skill token-superset "
                        "extension (a candidate extending an existing slug "
                        "by <=2 stemmed tokens, adjudicate only)")
    p.add_argument("--no-peers", action="store_true",
                   help="disable candidate-vs-candidate probing")
    p.add_argument("--compact", action="store_true", help="compact JSON output")
    return p


def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.test:
        return run_self_test()
    if not (args.index or args.wiki):
        print(json.dumps({"ok": False,
                          "error": "missing required argument: --index or --wiki"},
                         indent=2))
        return 2
    if not (args.title or args.titles):
        print(json.dumps({"ok": False,
                          "error": "missing required argument: --title or --titles"},
                         indent=2))
        return 2

    try:
        if args.index:
            index = load_index(args.index)
        else:
            index = _vault_index.build_index(args.wiki)
            if not os.path.isdir(args.wiki):
                print(json.dumps({"ok": False,
                                  "error": "wiki folder not found: %s" % args.wiki},
                                 indent=2))
                return 2
    except Exception as exc:
        print(json.dumps({"ok": False,
                          "error": "could not load index: %s: %s"
                                   % (type(exc).__name__, exc)}, indent=2))
        return 2

    try:
        titles = args.title if args.title else _load_titles(args.titles)
    except Exception as exc:
        print(json.dumps({"ok": False,
                          "error": "could not read titles: %s: %s"
                                   % (type(exc).__name__, exc)}, indent=2))
        return 2

    if not titles:
        print(json.dumps({"ok": False, "error": "no candidate titles supplied"},
                         indent=2))
        return 2

    try:
        report = check_candidates(titles, index, use_stem=not args.no_stem,
                                  use_superset=not args.no_superset,
                                  include_peers=not args.no_peers)
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2
    print(json.dumps(report, ensure_ascii=False,
                     **({} if args.compact else {"indent": 2})))
    return 0


if __name__ == "__main__":
    sys.exit(main())
