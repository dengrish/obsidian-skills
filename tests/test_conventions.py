#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_conventions.py -- fail loudly when a skill drifts from shared/CONVENTIONS.md.

    python3 tests/test_conventions.py                 # human-readable report
    python3 tests/test_conventions.py -v              # also list every passing check
    python3 tests/test_conventions.py --json          # machine-readable
    python3 tests/test_conventions.py --allow-pending # PENDING exits 0

Exit codes: 0 all checks passed, 1 at least one FAIL **or PENDING**, 2 the
harness itself could not run (missing CONVENTIONS.md, unparseable canonical
block).

Strict is the DEFAULT: a registered pending defect exits non-zero like a FAIL,
so an unattended CI gate that only reads the exit code cannot be greened by
registering the regression.  `--allow-pending` is the explicit opt-out for a
pass that is deliberately working around a parked defect; `--strict` is
accepted and ignored (it names what is now the default).  It used to be the
reverse -- strict was opt-in -- and CONVENTIONS.md §10 records why that
changed.

WHY THIS FILE EXISTS
--------------------
`shared/CONVENTIONS.md` states each cross-skill convention once.  Nothing stops
a future edit from restating one inside a skill and letting the two drift --
which is exactly how every serious bug in this plugin's review history was
produced.  This test is what makes the shared layer real rather than
aspirational: it re-derives each convention from CONVENTIONS.md and checks the
skills against it mechanically.

Everything canonical is READ FROM CONVENTIONS.md, never hardcoded here.  If a
convention changes, it changes in one place and this test follows.  The only
values written into this file are the *adversarial slug inputs*, which are test
data rather than convention.

THREE RESULT CLASSES
--------------------
  PASS     the check held.
  FAIL     drift.  Exit code 1.  Reported with file and line.
  PENDING  a known, registered defect that a skill edit (not a shared-layer
           edit) must fix, listed in CONVENTIONS.md §10 / §10a / §10b.  Loud,
           itemised, and NOT a pass -- but not a hard failure either, because
           the tree cannot be made green from inside `shared/` and `tests/`.
           Anything of the same shape that is *not* registered is a FAIL, so
           the registry can only ever shrink.  Deleting a registry line
           strictly strengthens this test.  A registry line that stops
           matching anything is itself a FAIL: an allowlist that outlives its
           defect is a standing licence to reintroduce it.

VACUITY IS A FAILURE, NOT A PASS
--------------------------------
The most dangerous result this file can produce is a check that passes because
its discovery step found nothing to look at.  Three mechanisms stop that:

  * every discovery step reports its population through `Report.saw`, and an
    empty population is a FAIL naming the step (`VACUOUS: ...`);
  * a check that emits no results at all is a FAIL -- previously such a check
    simply did not appear in the summary, and the run still said PASS;
  * a check that raises is a FAIL naming the exception and its line.  It
    proved nothing about the tree, so it cannot be counted as a pass.

Populations that a healthy tree legitimately leaves empty (violation
detectors) register the *corpus* they scanned instead of their hit count --
otherwise the check would be demanding its own violation.

THIS TEST EXECUTES THE TREE'S OWN CODE
--------------------------------------
Two checks have to.  `scripts-run` asserts every bundled script still imports;
`slug-single-impl` asserts no second slug implementation disagrees with the
canonical one, and the copy most likely to disagree is a terse wrong one that
no syntactic scan can see (see the note on SLUG_FINGERPRINTS).

So running this file is NOT a read-only operation on the tree, and you should
not treat it as one.  Two fences bound what that means:

  * every module under `skills/` and `shared/` is checked STATICALLY first,
    and one whose import does anything beyond defining names is refused and
    FAILED rather than imported (`module_scope_effects`);
  * what survives is imported in a SEPARATE, time-limited process whose
    output is captured and whose answer is read from a file, never off stdout
    (`probe_module`).

Neither is a sandbox and this file does not claim to be one: a module that
passes the static gate runs arbitrary Python inside the child.  What the pair
guarantees is narrower and checkable -- the harness itself cannot be hung,
silenced, path-poisoned or crashed by the tree it is judging, and the ordinary
way for code to end up running at import is refused with a file and a line.
Run this on a tree you would run the skills from; that is the same trust
decision, and no smaller.

The harness uses stdlib, Python 3.9+; the script self-tests also need the runtime
dependencies in requirements-dev.txt. The walk is done once and
cached, the enum extractors skip any file that cannot possibly hold the list,
and the out-of-process module probes and bundled self-test suites account for
most of the runtime.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import inspect
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap

# The slug checks import skill scripts to compare their output.  Without this,
# running the test litters `__pycache__/` into skill directories it has no
# business writing to -- and into the plugin tree a user just installed.
sys.dont_write_bytecode = True

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS_DIR = os.path.join(ROOT, "skills")
SHARED_DIR = os.path.join(ROOT, "shared")
CONVENTIONS = os.path.join(SHARED_DIR, "CONVENTIONS.md")
SLUGIFY = os.path.join(SHARED_DIR, "scripts", "slugify.py")
PLUGIN_PATHS = os.path.join(SHARED_DIR, "scripts", "plugin_paths.py")
NAMING = os.path.join(SHARED_DIR, "scripts", "naming.py")
FETCH_IMAGES = os.path.join(
    SKILLS_DIR, "clipping-processor", "scripts", "fetch_images.py")
SCAN_VAULT = os.path.join(
    SKILLS_DIR, "wiki-linter", "scripts", "scan_vault.py")

TEXT_EXT = (".md", ".py")


# ===========================================================================
# harness
# ===========================================================================

class Report:
    """Collects results; prints the summary; owns the exit code."""

    def __init__(self):
        self.results = []          # (check, status, where, message)
        self.checks = []           # ordered check names
        self.examined = {}         # check -> {what: count}, the vacuity ledger

    def _add(self, check, status, where, message):
        if check not in self.checks:
            self.checks.append(check)
        self.results.append((check, status, where, message))

    def ok(self, check, message, where=""):
        self._add(check, "PASS", where, message)

    def fail(self, check, message, where=""):
        self._add(check, "FAIL", where, message)

    def pending(self, check, message, where=""):
        self._add(check, "PENDING", where, message)

    def saw(self, check, what, n):
        """Record that a sub-check examined ``n`` candidate sites.

        A check that finds nothing to look at is the most dangerous result
        shape in this file: it passes, it costs nothing, and it means the
        opposite of what the summary line says.  Every discovery step reports
        its population here, and :meth:`vacuity` turns an empty one into a
        FAIL naming the sub-check -- so a glob that stops matching is a
        failure, not a silence.
        """
        self.examined.setdefault(check, {}).setdefault(what, 0)
        self.examined[check][what] += n

    def vacuity(self):
        for check in sorted(self.examined):
            for what, n in sorted(self.examined[check].items()):
                if n == 0:
                    self.fail(check,
                              "VACUOUS: the `%s` step examined 0 candidates. It "
                              "did not pass -- it found nothing to check. Either "
                              "the convention is no longer stated anywhere (a "
                              "drift in itself) or this step's discovery is "
                              "broken." % what)

    def counts(self):
        c = {"PASS": 0, "FAIL": 0, "PENDING": 0}
        for _, s, _, _ in self.results:
            c[s] += 1
        return c

    def by_status(self, status):
        return [r for r in self.results if r[1] == status]

    def render(self, verbose=False, allow_pending=False):
        out = []
        w = max((len(c) for c in self.checks), default=10)
        out.append("=" * 78)
        out.append("obsidian :: shared-convention conformance")
        out.append("  canonical source : %s" % rel(CONVENTIONS))
        out.append("  tree under test  : %s" % rel(SKILLS_DIR))
        out.append("=" * 78)

        for check in self.checks:
            rs = [r for r in self.results if r[0] == check]
            n_fail = sum(1 for r in rs if r[1] == "FAIL")
            n_pend = sum(1 for r in rs if r[1] == "PENDING")
            n_pass = sum(1 for r in rs if r[1] == "PASS")
            if n_fail:
                mark, tail = "FAIL", "%d failed" % n_fail
            elif n_pend:
                mark, tail = "PEND", "%d pending" % n_pend
            else:
                mark, tail = " ok ", "%d checked" % n_pass
            out.append("[%s] %-*s  %s" % (mark, w, check, tail))
            for c, s, where, msg in rs:
                if s == "PASS" and not verbose:
                    continue
                prefix = {"PASS": "       .", "FAIL": "       x",
                          "PENDING": "       ~"}[s]
                out.append("%s %s" % (prefix, msg))
                if where:
                    out.append("         at %s" % where)

        cnt = self.counts()
        out.append("-" * 78)
        if cnt["FAIL"]:
            out.append("RESULT: FAIL  (%d failed, %d pending, %d passed)"
                       % (cnt["FAIL"], cnt["PENDING"], cnt["PASS"]))
            out.append("")
            out.append("Failures, in order:")
            for i, (c, _, where, msg) in enumerate(self.by_status("FAIL"), 1):
                out.append("  %2d. [%s] %s" % (i, c, msg))
                if where:
                    out.append("      %s" % where)
        elif cnt["PENDING"]:
            # Not "PASS".  A pending defect is a real defect, and calling the
            # run a pass is how the registry turns into a place to hide one.
            out.append("RESULT: PASS-WITH-PENDING  (%d checks, %d pending "
                       "defect(s) below -- %s)"
                       % (cnt["PASS"], cnt["PENDING"],
                          "exit 0 because --allow-pending was passed"
                          if allow_pending else
                          "this run exits NON-ZERO; `--allow-pending` is the "
                          "opt-out"))
        else:
            out.append("RESULT: PASS  (%d checks, 0 pending)" % cnt["PASS"])

        if cnt["PENDING"]:
            out.append("")
            out.append("PENDING -- registered in %s, awaiting an edit inside skills/:"
                       % rel(CONVENTIONS))
            for i, (c, _, where, msg) in enumerate(self.by_status("PENDING"), 1):
                out.append("  %2d. [%s] %s" % (i, c, msg))
                if where:
                    out.append("      %s" % where)
            out.append("")
            out.append("  These are NOT passes. Each is a real defect with a named fix;")
            out.append("  deleting its line from CONVENTIONS.md §10 turns it into a FAIL,")
            out.append("  and registering one does not make this run exit 0.")
        out.append("=" * 78)
        return "\n".join(out)

    def exit_code(self, allow_pending=False):
        """1 unless the tree is actually clean.

        A PENDING is a real defect with a line in CONVENTIONS.md, and the
        strict exit code used to be opt-in: adding one fictional name to
        `canonical:external-skills` turned a FAIL into `PASS-WITH-PENDING` and
        exit **0**, so an unattended gate reading only the exit code was
        greened by an edit to a markdown file.  Refusing by default puts the
        opt-out where it belongs: on whoever wants to ignore the defect, in the
        command line, where it is visible in CI config rather than in prose.
        """
        c = self.counts()
        if c["FAIL"]:
            return 1
        return 0 if allow_pending else (1 if c["PENDING"] else 0)


class HarnessError(Exception):
    """The test itself cannot run (as opposed to a check failing)."""


class Registry:
    """A pending-defect allowlist read from a CONVENTIONS.md canonical block.

    Registries exist so the test can be *green-when-correct* while a defect it
    cannot fix from inside `shared/` and `tests/` is still outstanding.  Three
    properties keep that from becoming a rug to sweep things under:

    * a registered defect is reported as PENDING -- itemised, with file and
      line, in its own section of the summary -- never as a pass;
    * anything of the same shape that is NOT registered is a hard FAIL, so the
      registry can only ever shrink;
    * a registry line that stops matching anything is reported as stale, with
      an instruction to delete it -- so the allowlist cannot outlive the defect
      and quietly keep a real regression hidden.
    """

    def __init__(self, rep, check, conv_text, block, label):
        self.rep, self.check, self.label = rep, check, label
        self.block = block
        self.keys = list(canonical_block(conv_text, block, required=False))
        self.used = set()

    def claims(self, key):
        return key in self.keys

    def hit(self, key, message, where=""):
        self.used.add(key)
        self.rep.pending(self.check,
                         "%s  [registered in CONVENTIONS.md as `%s`]"
                         % (message, self.block), where)

    def finish(self):
        for key in self.keys:
            if key not in self.used:
                # A FAIL, not a note.  An allowlist line that outlived its
                # defect is a standing licence to reintroduce it, and a PASS
                # is invisible without -v -- which is exactly how an allowlist
                # quietly keeps a real regression hidden.
                self.rep.fail(self.check,
                              "registry line `%s` under `%s` no longer matches "
                              "anything (%s is fixed) -- DELETE that line from "
                              "CONVENTIONS.md so the check hardens. Until it is "
                              "deleted it is a standing exemption for a defect "
                              "that is no longer there."
                              % (key, self.block, self.label),
                              rel(CONVENTIONS))


def rel(path):
    try:
        return os.path.relpath(path, ROOT)
    except ValueError:
        return path


_READ_CACHE = {}
#: Files the walkers could not decode.  Silently skipping one drops it out of
#: *every* check at once -- a single stray byte would exempt a whole file from
#: the harness -- so they are collected and reported instead.
UNREADABLE = []


def read(path):
    if path not in _READ_CACHE:
        with open(path, encoding="utf-8") as fh:
            _READ_CACHE[path] = fh.read()
    return _READ_CACHE[path]


def line_of(text, offset):
    return text.count("\n", 0, offset) + 1


def at(path, offset_or_line, text=None):
    line = line_of(text, offset_or_line) if text is not None else offset_or_line
    return "%s:%d" % (rel(path), line)


_SKILL_FILES = None


def walk_skill_files():
    """Yield (skill, path, text) for every .md/.py under skills/.

    Walked once and cached: nine checks iterate this, and re-statting the tree
    per check is the difference between a test that gets run and one that does
    not.  A file that cannot be decoded is *not* skipped -- it is recorded in
    :data:`UNREADABLE` and reported, because a skipped file is exempt from
    every check at once.
    """
    global _SKILL_FILES
    if _SKILL_FILES is None:
        out = []
        for skill in sorted(os.listdir(SKILLS_DIR)):
            sdir = os.path.join(SKILLS_DIR, skill)
            if not os.path.isdir(sdir) or skill.startswith("."):
                continue
            for base, dirs, names in os.walk(sdir):
                dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                for name in sorted(names):
                    if not name.endswith(TEXT_EXT) or name.startswith("."):
                        continue
                    path = os.path.join(base, name)
                    try:
                        out.append((skill, path, read(path)))
                    except (UnicodeDecodeError, OSError) as exc:
                        UNREADABLE.append((path, "%s: %s"
                                           % (type(exc).__name__, exc)))
        _SKILL_FILES = out
    return iter(_SKILL_FILES)


def skill_names():
    return sorted(d for d in os.listdir(SKILLS_DIR)
                  if os.path.isdir(os.path.join(SKILLS_DIR, d))
                  and not d.startswith("."))


# ===========================================================================
# canonical blocks
# ===========================================================================

BLOCK_RE_TMPL = (r"<!--\s*canonical:%s\s*-->\s*```[a-z]*\n(.*?)```\s*<!--\s*/canonical\s*-->")


ANY_BLOCK_RE = re.compile(BLOCK_RE_TMPL % r"[a-z0-9:_-]+", re.S)


def canonical_block_lines(text):
    """Line numbers inside any ``<!-- canonical:… -->`` block.

    The contents of a canonical block are *keys*, not prose: a registry line
    naming a path that is deliberately not shipped is the record of that
    decision, not another statement of it.  A check that reads the block as
    documentation reports the registry for registering the thing.
    """
    out = set()
    for m in ANY_BLOCK_RE.finditer(text):
        first = text.count("\n", 0, m.start()) + 1
        last = text.count("\n", 0, m.end()) + 1
        out.update(range(first, last + 1))
    return out


def canonical_block(conv_text, name, required=True):
    """Return the lines of the ``<!-- canonical:NAME -->`` fenced block."""
    m = re.search(BLOCK_RE_TMPL % re.escape(name), conv_text, re.S)
    if not m:
        if required:
            raise HarnessError(
                "CONVENTIONS.md has no `<!-- canonical:%s -->` block. The test "
                "reads every canonical value from that file rather than "
                "hardcoding it; without the block there is nothing to check "
                "against." % name)
        return []
    return [ln.strip() for ln in m.group(1).splitlines() if ln.strip()]


def canonical_csv_block(conv_text, name):
    """A canonical block written as one comma-separated line."""
    lines = canonical_block(conv_text, name)
    vals = []
    for ln in lines:
        vals.extend(v.strip() for v in ln.split(",") if v.strip())
    return vals


# ===========================================================================
# generic run-extraction (used by the enum and schema checks)
# ===========================================================================

TOKEN_RE = re.compile(r"[a-z_][a-z_0-9-]*")
#: Characters allowed *between* two members of a list without breaking it.
#: Deliberately excludes `(`, `)`, `:`, `.` and `;` -- those end a sentence or
#: a clause, and treating them as separators glues a prose mention onto the
#: list that follows it.
RUN_SEP = set(" \t\n\r`\",'#[]{}·")
#: A gap containing either of these is a hard break, whatever else is in it: a
#: blank line ends a paragraph, and a ``` fence ends a code block.  Without
#: this, a `tags:` YAML example immediately followed by the enum glues its
#: `machine-learning` onto the front of the list and reports a 26-value enum.
RUN_HARD_BREAK = re.compile(r"\n[ \t]*\n|```")


#: Separators that additionally hold a *list* together but not a prose run:
#: a markdown table pipe.
RUN_SEP_LIST = RUN_SEP | {"|"}
#: A newline followed by a bullet or an ordinal.  Without this, a convention
#: restated as a markdown bullet list is invisible to the run extractor -- the
#: `-` is not a separator, so every item is its own run of length one, and the
#: whole list slips past every membership and order check.
BULLET_GAP = re.compile(r"\n[ \t]*(?:[-*+]|\d+[.)])[ \t]*")
#: Characters that wrap a list member: backticks in prose, quotes in code.
WRAPPERS = "`\"'"


def _is_list_gap(gap):
    # Fast path: the overwhelming majority of gaps are one or two ordinary
    # separator characters.  This function is called once per adjacent token
    # pair per file per enum, so it dominates the runtime; the regexes below
    # only need to run for gaps that could actually hold a break.
    if len(gap) <= 2 and "\n" not in gap:
        return all(c in RUN_SEP_LIST for c in gap)
    if RUN_HARD_BREAK.search(gap):
        return False
    if "|" in gap and "\n" in gap:
        return False        # a table *row* boundary: the next cell is a new fact
    return all(c in RUN_SEP_LIST for c in BULLET_GAP.sub("\n", gap))


def _wrap_of(text, a, b):
    """The quoting character wrapping ``text[a:b]``, or ``""`` if bare."""
    before = text[a - 1] if a > 0 else ""
    after = text[b] if b < len(text) else ""
    return before if (before == after and before in WRAPPERS) else ""


#: Tokens that join the members of a *prose* enumeration without being one.
#: Only used where the list is written bare, in English ("place, work, or
#: quote"); a wrapped list needs no such tolerance.
ENUM_GLUE = frozenset(("or", "and", "a", "an", "the"))

#: Counting words, for the two checks that read a stated count back: the skill
#: roster ("all five skills") and a declared subset of an enum ("the remaining
#: ten"). Digits count too -- "all 6 skills" is exactly as stale as "all six
#: skills", and a check that reads only the spelled-out form is one a rewrite
#: walks straight through.
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
                "fifteen": 15}
_COUNT_ALT = "|".join(list(NUMBER_WORDS) + [r"\d{1,2}"])


def enum_statements(text, members, min_len, token_re=None, glue=frozenset()):
    """Statements of a closed enum, with the values that do not belong to it.

    ``maximal_runs`` below *breaks* a run on the first token that is not a
    member, which means a 28th value written at either end of the list -- the
    cheapest way to widen a closed enum -- leaves an intact 27-value run and
    reports as canonical.  This extractor instead keeps a non-member token
    inside the run when it is decorated exactly like its neighbours (same
    backtick or quote wrapper), and returns it as an *extra*.

    Returns ``[(members_in_order, extras, start_offset)]``.
    """
    # A file that does not even contain ``min_len`` of the members as plain
    # substrings cannot state the enum.  Tokenising every file three times to
    # discover that is what made this the slowest thing in the harness.
    if sum(1 for v in members if v in text) < min_len:
        return []
    rx = token_re or TOKEN_RE
    toks = [(m.group(0), m.start(), m.end()) for m in rx.finditer(text)]
    if not toks:
        return []
    # gap_ok[i]: the text between toks[i-1] and toks[i] is only list punctuation
    gap_ok = [False] * len(toks)
    for i in range(1, len(toks)):
        gap_ok[i] = _is_list_gap(text[toks[i - 1][2]:toks[i][1]])

    anchors, i = [], 0
    while i < len(toks):
        if toks[i][0] not in members:
            i += 1
            continue
        j = i + 1
        while j < len(toks) and gap_ok[j] and (toks[j][0] in members
                                               or toks[j][0] in glue):
            j += 1
        while j - 1 > i and toks[j - 1][0] not in members:
            j -= 1                       # never end a run on glue
        if len([1 for t, _, _ in toks[i:j] if t in members]) >= min_len:
            anchors.append((i, j))
        i = j

    out = []
    for i, j in anchors:
        wraps = [_wrap_of(text, a, b) for _, a, b in toks[i:j]]
        dom = max(set(wraps), key=wraps.count)
        if wraps.count(dom) * 2 < len(wraps):
            dom = None

        def belongs(k, prev_gap_index):
            # A token outside the member run belongs to the same list only if
            # it is decorated the way the members are.  A trailing code
            # comment (`# the 27-discipline enum`) is not a 28th value; a
            # backticked `artificial-intelligence` sitting against the end of
            # a backticked list is.
            if not gap_ok[prev_gap_index]:
                return False
            if dom is None:
                return False
            if dom == "":
                return (_wrap_of(text, toks[k][1], toks[k][2]) == ""
                        and re.search(r"[,·|]", text[toks[k - 1][2]:toks[k][1]]
                                      if k else ""))
            return _wrap_of(text, toks[k][1], toks[k][2]) == dom

        lo, hi = i, j
        while hi < len(toks) and belongs(hi, hi):
            hi += 1
        while lo > 0 and belongs(lo - 1, lo):
            lo -= 1
        span = [t for t, _, _ in toks[lo:hi]]
        out.append(([t for t in span if t in members],
                    [t for t in span if t not in members and t not in glue],
                    toks[lo][1]))
    return out


_AST_CACHE = {}


def _parsed(text):
    """The AST for ``text``, parsed once (three checks want it)."""
    key = id(text)
    if key not in _AST_CACHE:
        try:
            _AST_CACHE[key] = ast.parse(text)
        except SyntaxError:
            _AST_CACHE[key] = None
    return _AST_CACHE[key]


def python_literal_lists(text):
    """``(elements, lineno)`` for every list/set/tuple of string constants.

    A script constant is the copy of an enum that matters most -- it is the
    one that actually decides behaviour -- and it is also the one a prose
    extractor reads least reliably.  Parsing the AST reads it exactly.
    """
    tree = _parsed(text)
    if tree is None:
        return []
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.List, ast.Set, ast.Tuple)):
            continue
        vals = []
        for el in node.elts:
            if isinstance(el, ast.Constant) and isinstance(el.value, str):
                vals.append(el.value)
            else:
                vals = None
                break
        if vals:
            out.append((vals, node.lineno))
    return out


def maximal_runs(text, members, min_len):
    """Maximal runs of ``members`` separated only by :data:`RUN_SEP`.

    Returns ``[(values, start_offset)]``.  This is how a list is recognised
    without caring whether it was written with commas, middots, backticks,
    Python quotes or newlines -- all six statements of the tag enum in this
    tree use a different punctuation, and all six must be checkable.
    """
    toks = [(m.group(0), m.start(), m.end()) for m in TOKEN_RE.finditer(text)]
    runs, cur = [], []
    for tok, a, b in toks:
        gap = text[cur[-1][2]:a] if cur else ""
        contiguous = bool(cur) and all(c in RUN_SEP for c in gap) \
            and not RUN_HARD_BREAK.search(gap)
        if tok in members and contiguous:
            cur.append((tok, a, b))
            continue
        if len(cur) >= min_len:
            runs.append(([t for t, _, _ in cur], cur[0][1]))
        cur = [(tok, a, b)] if tok in members else []
    if len(cur) >= min_len:
        runs.append(([t for t, _, _ in cur], cur[0][1]))
    return runs


# ===========================================================================
# check 1 -- the discipline-tag enum
# ===========================================================================

def _order_divergence(values, canonical):
    """``(position, got, want)`` of the first difference, or ``None``.

    Written defensively: the caller used to build this message with two
    ``next()`` calls over ``zip``, which raised ``StopIteration`` -- crashing
    the whole check -- whenever the two lists held the same values in the same
    positions but differed in length, e.g. a duplicated member.
    """
    for i, (a, b) in enumerate(zip(values, canonical)):
        if a != b:
            return i + 1, a, b
    if len(values) != len(canonical):
        return min(len(values), len(canonical)) + 1, \
            (values[len(canonical):] or ["<end>"])[0], \
            (canonical[len(values):] or ["<end>"])[0]
    return None


def _check_enum_statement(rep, check, values, extras, canonical, where, what,
                          label):
    """One statement of a closed enum, checked for membership *and* order."""
    canon_set = set(canonical)
    missing = [v for v in canonical if v not in values]
    extra = sorted(set(extras) | {v for v in values if v not in canon_set})
    dupes = sorted({v for v in values if values.count(v) > 1})
    if missing or extra or dupes:
        bits = []
        if missing:
            bits.append("missing %s" % ", ".join(missing))
        if extra:
            bits.append("extra %s" % ", ".join(extra))
        if dupes:
            bits.append("duplicated %s" % ", ".join(dupes))
        rep.fail(check,
                 "%s states a %d-value %s: %s. The enum is closed: %d values, "
                 "no synonyms, no invented members."
                 % (what, len(values) + len(extras), label, "; ".join(bits),
                    len(canonical)), where)
        return False
    div = _order_divergence(values, canonical)
    if div:
        rep.fail(check,
                 "%s states all %d %s values but in a different order than "
                 "CONVENTIONS.md (first divergence at position %d: %r vs "
                 "canonical %r). Order is part of the fact: a reader "
                 "diffing two copies cannot tell a reordering from a "
                 "substitution."
                 % (what, len(canonical), label, div[0], div[1], div[2]), where)
        return False
    rep.ok(check, "%s states the canonical %d-value %s"
           % (what, len(canonical), label), where)
    return True


def check_tag_enum(rep, conv):
    """Every skill that states the enum states exactly the canonical 27."""
    check = "tag-enum"
    canonical = canonical_block(conv, "tag-enum")
    if len(canonical) != 27:
        raise HarnessError("canonical:tag-enum has %d values, expected 27"
                           % len(canonical))
    canon_set = set(canonical)
    n_prose = n_const = 0

    for skill, path, text in walk_skill_files():
        # A file "mentions discipline tags" if it names enough of them to be
        # restating the enum.  A single `#machine-learning` in prose is a use,
        # not a restatement, and is not the thing that drifts.
        distinct = {v for v in canon_set if re.search(r"(?<![a-z-])%s(?![a-z-])"
                                                      % re.escape(v), text)}
        runs = enum_statements(text, canon_set, min_len=8)

        if len(distinct) >= 15 and not runs:
            rep.fail(check,
                     "%s names %d of the 27 discipline tags but states no "
                     "recognisable enum list -- the enum has probably been "
                     "split by a non-enum value spliced into it, or restated "
                     "in a layout this extractor cannot read. Either way the "
                     "27 values are no longer checkable here."
                     % (rel(path), len(distinct)), at(path, 1))
            continue

        for values, extras, off in runs:
            n_prose += 1
            _check_enum_statement(rep, check, values, extras, canonical,
                                  at(path, off, text), rel(path),
                                  "discipline-tag enum")

        # A Python constant is the copy that decides behaviour.  Read it from
        # the AST rather than from punctuation: `VALID_TAGS = {...}` with a
        # 28th member appended is invisible to any prose extractor that stops
        # at the first non-member token.
        if path.endswith(".py"):
            for vals, lineno in python_literal_lists(text):
                if len(set(vals) & canon_set) < 8:
                    continue
                n_const += 1
                _check_enum_statement(
                    rep, check, [v for v in vals if v in canon_set],
                    [v for v in vals if v not in canon_set], canonical,
                    at(path, lineno), "%s constant at line %d" % (rel(path), lineno),
                    "discipline-tag enum")

    rep.saw(check, "prose statements of the tag enum", n_prose)
    rep.saw(check, "script constants holding the tag enum", n_const)


# ===========================================================================
# check 2 -- the slug algorithm has exactly one implementation
# ===========================================================================

#: Fingerprints of the slug algorithm.  A file matching several of these is
#: implementing the algorithm, not merely mentioning it.
#:
#: DEMOTED, DELIBERATELY.  This scan used to *be* the check, at a threshold of
#: four.  Its sensitivity is upside-down: a faithful re-vendoring trips all
#: seven and is loudly caught, while the copy that actually matters -- a short,
#: WRONG reimplementation -- trips one and sails through.  Five lines are
#: enough to shadow the canonical module and slug `C++` to `c`:
#:
#:     import re
#:     class SlugError(ValueError): pass
#:     slug_stem = lambda t: re.sub(r'[^a-z0-9]+', '-', str(t).lower()).strip('-')
#:     slugify = lambda t: slug_stem(t) + '.md'
#:     base_term = has_parenthetical = mu_variants = lambda t: t
#:
#: That file scored 1/7, defined nothing an AST `FunctionDef` scan can see
#: (every entry point is a lambda BINDING), and the whole suite reported PASS
#: while `C++` slugged to `c`.  So the fingerprints are now one of three
#: discovery channels, at a threshold of two, and none of them is what
#: actually decides: `_slug_producers` IMPORTS each module and runs its
#: callables against the canonical corpus.  Behaviour is the fact; a
#: fingerprint is a guess about the spelling of the fact.
SLUG_FINGERPRINTS = [
    ("nfkd", re.compile(r"normalize\(\s*[\"']NFKD[\"']")),
    ("greek", re.compile(r"[\"']alpha[-\"']")),
    ("symbol-words", re.compile(r"[\"']-?sharp[\"']|[\"']-?star[\"']")),
    ("charges", re.compile(r"[\"']-?plus[\"']|[\"']-?minus[\"']")),
    ("non-slug-re", re.compile(r"\[\^a-z0-9[^\]\n]{0,6}\]")),
    ("hyphen-run", re.compile(r"-\{2,\}|--\+")),
    ("ascii-fold", re.compile(r"encode\(\s*[\"']ascii[\"']|unicodedata")),
]

#: The public names CONVENTIONS.md §4a publishes for the canonical module,
#: plus the thin wrapper name §4a blesses (`slug`).  A module under `skills/`
#: or `shared/` that *defines* one of these without delegating to the shared
#: module is a second home for the fact, however it happens to be spelled --
#: which is what the fingerprint scan alone cannot see.
CANONICAL_SLUG_API = {"slugify", "slug_stem", "base_term", "mu_variants",
                      "has_parenthetical", "preprocess", "slug"}

#: Names no module under `skills/` may define or export, whatever it does with
#: them.  §4a publishes these for ONE module and it is not in a skill: a skill
#: that owns the name owns the import path `import slugify` resolves to, and
#: whether its answer happens to agree today is beside the point.  `slug` is
#: absent on purpose -- wiki-linter's `slug()` is the §4a-blessed delegating
#: wrapper, and it is held to agreement by the behavioural check below.
FORBIDDEN_SLUG_NAMES = {"slugify", "slug_stem"}

#: How few fingerprints still count as "this file may be implementing it".
#: Two, not four -- see the note on SLUG_FINGERPRINTS.  A low threshold is
#: affordable now because a hit only widens what gets EXECUTED; it never
#: decides anything on its own, so a file that merely *discusses* the
#: algorithm in a comment cannot be failed by it.
SLUG_FINGERPRINT_MIN = 2

#: ...whereas a file scoring this many, with nothing runnable in it, is
#: claimed to be an implementation that the behavioural check could not
#: verify -- which is a FAIL, because it proved nothing either way.
SLUG_FINGERPRINT_UNVERIFIABLE = 4

#: A callable whose NAME suggests it might turn a title into a slug.  Used
#: only to decide what is worth executing; the decision itself is behavioural.
SLUGGY_NAME_RE = re.compile(r"slug|kebab|normali[sz]e|filename|to_?name", re.I)

#: The shape of a canonical stem: lowercase kebab, no leading/trailing hyphen.
SLUG_SHAPE_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

#: Titles used to ask a callable, by running it, "do you produce slugs?".
#: Three ordinary multi-word titles with no special characters at all: every
#: implementation of the algorithm agrees on these, so a callable that answers
#: with a slug-shaped string for two of the three is producing slugs, and one
#: that does not is not -- without either of us having to guess from its name.
SLUG_DUCK_PROBES = ("ROC curve", "k-fold cross-validation", "F1 score")

#: Attribute/function names whose presence anywhere inside a candidate marks
#: it as touching the world.  The behavioural check EXECUTES code out of the
#: tree under test; it may only execute things that look pure.  This is a
#: safety screen, not a detector -- a slug function has no business calling
#: any of these, so screening one out costs the check nothing.
#:
#: It is a screen on what gets CALLED.  It is not, and cannot be, what makes
#: executing the tree safe: by the time a callable can be screened its module
#: has already been imported.  Containment is :func:`probe_module` -- a static
#: import-time gate plus a separate, time-limited process.  See that function.
IMPURE_NAMES = frozenset((
    "open", "remove", "unlink", "rename", "replace", "rmtree", "move",
    "copy", "copy2", "mkdir", "makedirs", "system", "popen", "Popen", "run",
    "call", "check_output", "urlopen", "urlretrieve", "request", "connect",
    "socket", "input", "write", "writelines", "exit", "eval", "exec",
    "compile", "__import__", "chmod", "chown", "truncate",
    # command-line entry points.  A function that parses argv is a `main`,
    # not a slug function, and calling one makes argparse `sys.exit(2)` --
    # which is how a first cut at this check killed the whole harness.
    "parse_args", "parse_known_args", "ArgumentParser", "print_usage",
    "print_help", "argv", "stdin",
    # Reflection and the modules that reach the world.  `getattr(os, "sys" +
    # "tem")` spells none of the names above, and a slug function has no use
    # for any of these, so naming the modules costs the check nothing and
    # closes the whole build-the-name-at-runtime family at once.
    "getattr", "setattr", "delattr", "globals", "locals", "vars",
    "os", "sys", "subprocess", "shutil", "socket", "urllib", "requests",
    "pathlib", "importlib", "ctypes", "signal", "threading",
    "multiprocessing", "tempfile", "atexit", "builtins", "__builtins__",
))


def _slug_api_definitions(text):
    """``[(name, lineno, delegates)]`` for slug-API functions defined here."""
    tree = _parsed(text)
    if tree is None:
        return []
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "") == "slugify":
            imported.update(a.asname or a.name for a in node.names)
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "slugify":
                    imported.add(a.asname or a.name)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.lstrip("_") not in CANONICAL_SLUG_API:
            continue
        used = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        used |= {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
        out.append((node.name, node.lineno, bool(used & imported)))
    return out


def walk_python_sources():
    """Every .py under skills/ and shared/, except the canonical module."""
    for skill, path, text in walk_skill_files():
        if path.endswith(".py"):
            yield path, text
    for base, dirs, names in os.walk(SHARED_DIR):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(names):
            path = os.path.join(base, name)
            if not name.endswith(".py") or os.path.abspath(path) == SLUGIFY:
                continue
            try:
                yield path, read(path)
            except (UnicodeDecodeError, OSError) as exc:
                UNREADABLE.append((path, "%s: %s" % (type(exc).__name__, exc)))

#: Adversarial inputs on top of slugify.py's own self-test cases.  These are
#: test data, not convention, so they live here.  Each one is a shape that a
#: divergent copy has actually got wrong, or would.
#:
#: This list used to run ONLY when a second implementation was found in the
#: tree -- so on a healthy tree (no duplicate, which is the whole goal) it
#: never executed at all.  It was 44 inert string literals.  It is now run
#: against the canonical module unconditionally, by
#: `_check_adversarial_canonical`, as well as against every slug producer the
#: behavioural scan finds.
ADVERSARIAL = [
    "C", "C++", "C#", "C*", "A*",                    # symbol-word mapping
    "Ca2+", "Ca²⁺", "Cl-", "Cl⁻",     # ASCII vs typeset charge
    "Na+", "[Mg2+]", "Mg2-",
    "Α-helix", "Β-sheet", "Γδ T cell",   # Greek CAPITALS
    "ΔG", "Ω notation", "Σ-algebra", "ς final",
    "µm", "μm",                            # micro sign vs Greek mu
    "機械学習",                      # CJK -> unsluggable
    "トランスフォーマー",
    "---", "", "   ", "***", "+++",                  # empty-slug family
    "X-ray", "T-cell receptor", "mRNA-seq", "RNA-",  # anion negative controls
    "Cross-validation", "Smith–Waterman", "DALL·E",
    "5'-UTR", "Schrödinger equation", "Straße", "Søren Kierkegaard",
    "Feature (machine learning)", "Information entropy",
    "Ångström", "gRPC++", "F1 score", "k-fold cross-validation",
]


def _load_module(path, name, screen=False):
    """Import ``path`` as ``name``, leaving this process's ``sys.path`` as found.

    Two changes landed together and did not see each other: the slug check
    started *importing and executing* the skill scripts, and the CONVENTIONS
    §5 bootstrap those scripts carry started rewriting ``sys.path`` in place
    (``_sys.path[:] = ...``, then insert ``shared/scripts`` at 0 and append
    the script's own directory).  In the script's own process that is exactly
    right.  Inside the harness it escapes: importing the twelve modules under
    ``skills/`` left four directories permanently on the harness's path --
    ``shared/scripts`` at position 0, plus three skill ``scripts/`` dirs --
    so every later bare ``import`` in this file resolved against the tree
    under test before the standard library.  Nothing collides today
    (``slugify``, ``vault_index``, ``slug``, ``scan_vault`` are not stdlib
    names), which is precisely why it would be found the hard way.

    The module still executes with the bootstrap's path in effect, so its own
    ``from slugify import ...`` and ``import vault_index`` bind normally; only
    the harness's view is restored afterwards.
    """
    # With ``screen=True`` the static-effects screen runs HERE, before exec,
    # not merely in the checks that happen to have run earlier: this function
    # executes tree code IN-PROCESS, and whether `scripts-run`'s screen had
    # already looked at a *consumer* script depended on check ordering -- a
    # module-level hang or write in one would have wedged or dirtied the
    # harness despite its containment claims.  A refused module raises
    # HarnessError; the consumer-probing call sites catch it and degrade to an
    # ordinary FAIL naming the file.  The screen stays OFF for the canonical
    # shared instruments (slugify builds its GREEK table with a module-level
    # loop the screen would refuse; those imports are this harness's own
    # instruments, vetted by their self-tests, not probed strangers).
    if screen:
        effects = module_scope_effects(read(path))
        if effects:
            raise HarnessError(
                "%s does something at import time (%s), so the harness "
                "refuses to import it in-process" % (
                    rel(path),
                    "; ".join("line %d: %s" % (ln, what)
                              for ln, what in effects[:3])))
    saved = list(sys.path)
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path[:] = saved


# ===========================================================================
# executing code out of the tree under test, safely
# ===========================================================================
#
# Two checks below need to RUN the tree's own modules: `scripts-run` asserts
# every bundled script still imports, and `slug-single-impl` asserts no second
# slug implementation disagrees with the canonical one.  Behaviour is the only
# thing that answers either question -- see the note on SLUG_FINGERPRINTS for
# why a syntactic scan does not.
#
# But `python3 tests/test_conventions.py` reads as a static conformance check,
# it is what a reviewer runs to decide whether to trust this tree, and it is
# what CI runs unattended.  An earlier cut of this file imported every .py
# under skills/ and shared/ directly into the harness process, with the purity
# screen applied only afterwards, to callables.  A module with a module-level
# `subprocess.run(...)` therefore ran it -- before anything had screened
# anything -- and a module-level `print` landed above the report header.
#
# So execution is fenced twice, and the two fences do different jobs:
#
#   1. `module_scope_effects` is a PRECONDITION, checked statically, before
#      anything is executed.  A module whose import does more than define
#      things is refused and FAILED, never imported.  This is what catches the
#      realistic accident -- a script that grew a module-level write or a
#      stray `main()` call -- and it is enforceable without running anything.
#   2. `probe_module` runs the import and the slug probes in a SEPARATE,
#      time-limited process, and reads the answer back out of a file rather
#      than off stdout.  This is what contains everything the first fence
#      cannot decide: a hang, an `os._exit` (which no `except BaseException`
#      can catch), a segfault in a C extension, an import-time `print`, and
#      the §5 bootstrap's `sys.path` rewrite.
#
# Neither fence is a sandbox, and this file does not pretend to be one: a
# module that passes the static gate still runs arbitrary Python inside the
# child.  What the pair buys is that the harness itself cannot be corrupted,
# hung or silenced by the tree it is judging, and that the most common way for
# code to run at import is refused with a message naming the file and line.

#: Seconds a single module's probe may take before it is killed and FAILED.
#: Generous -- the whole point is that a hang becomes a report, not a wedge.
PROBE_TIMEOUT = 60

#: Calls whose value is a constant table for our purposes.  Deliberately tiny:
#: everything here builds a regex, a container or a number, and nothing here
#: can write, spawn or connect.  A module-scope call to anything else is an
#: import-time effect as far as the gate is concerned.
PURE_CALL_NAMES = frozenset((
    "frozenset", "set", "dict", "list", "tuple", "sorted", "reversed",
    "len", "range", "int", "str", "float", "bool", "bytes", "enumerate",
    "zip", "max", "min", "sum", "abs", "chr", "ord", "round", "repr",
    "next", "iter", "type", "object", "property", "staticmethod",
    "classmethod", "namedtuple", "re.compile", "re.escape",
    "collections.namedtuple", "collections.OrderedDict", "textwrap.dedent",
    "os.path.join", "os.path.dirname", "os.path.abspath", "os.path.basename",
    "os.path.splitext", "os.path.expanduser", "os.path.normpath",
    "Path", "pathlib.Path", "datetime.timedelta",
))

#: Method names that only read or reshape a value already in hand.  Needed
#: because a constant table is often built as `X.items()` / `Path(f).resolve()`
#: / `s.split(",")`.  As above: nothing here reaches the world.
PURE_METHOD_NAMES = frozenset((
    "compile", "escape", "items", "keys", "values", "copy", "get",
    "split", "rsplit", "splitlines", "strip", "lstrip", "rstrip", "join",
    "lower", "upper", "title", "format", "replace", "encode", "decode",
    "startswith", "endswith", "resolve", "union", "difference",
    "intersection", "isdigit", "isalpha", "count", "index", "setdefault",
))

#: The names a module-scope *statement* may bind to.  A plain name is a
#: constant; `sys.modules[x] = ...` is not, and that is one of the two ways an
#: import-time effect gets spelled.  (`sys.path` is the other, and is allowed
#: on its own terms -- see :data:`_PATH_SETUP`.)
_SIMPLE_TARGETS = (ast.Name, ast.Tuple, ast.List)

#: `sys.path` manipulation, allowed at module scope by name.
#:
#: Not an oversight and not a hole.  CONVENTIONS.md §5 *requires* it: the
#: bootstrap every skill script carries puts `shared/scripts/` on the path
#: before importing the canonical module, and `batch_extract.py` does the same
#: for its sibling modules.  There is no way to express "reach the shared
#: layer" without it.  It is also the one import-time effect that is fully
#: neutralised by the second fence rather than merely bounded by it: the probe
#: runs in its own process, so a rewritten `sys.path` dies with that process
#: and cannot reach the harness.  It cannot write, spawn or connect.
#: Everything else that mutates existing state is still refused.
_PATH_SETUP = frozenset(("sys.path", "_sys.path"))


def _dotted(node):
    """``"re.compile"`` for a Name/Attribute chain, else ``None``."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


#: Module-scope calls that only stop the module from loading.  A script that
#: refuses to import without PyMuPDF is doing the right thing, and refusing to
#: start is not an effect on the world -- nothing is written, spawned or
#: connected.  If one of these actually fires, the probe reports it as an
#: import error and `scripts-run` FAILs the file, so nothing is hidden by
#: letting it past the static gate.
_REFUSAL_CALLS = frozenset(("sys.exit", "exit", "SystemExit", "_sys.exit"))


def _expr_nodes(node):
    """Every node of ``node`` that is actually EVALUATED at import.

    ``ast.walk`` is wrong here, and wrongly in the direction that matters: it
    descends into ``lambda`` bodies, which do not run when the module is
    imported any more than a ``def``'s body does.  Walking them made the gate
    refuse ``slug_stem = lambda t: re.sub(...)`` -- the exact five-line wrong
    copy the behavioural check exists to catch -- so the file was rejected for
    the wrong reason and never reached the probe that would have shown it
    disagreeing with the canonical module.  A lambda's DEFAULTS do evaluate at
    import, so those are still walked.
    """
    stack, out = [node], []
    while stack:
        cur = stack.pop()
        out.append(cur)
        if isinstance(cur, ast.Lambda):
            stack.extend(d for d in cur.args.defaults if d is not None)
            stack.extend(d for d in cur.args.kw_defaults if d is not None)
            continue
        stack.extend(ast.iter_child_nodes(cur))
    return out


def _impure_expr(node):
    """The first import-time effect inside an expression, or ``None``."""
    for sub in _expr_nodes(node):
        if not isinstance(sub, ast.Call):
            continue
        name = _dotted(sub.func)
        if name is not None:
            if name in PURE_CALL_NAMES or name in _REFUSAL_CALLS:
                continue
            if name.rsplit(".", 1)[0] in _PATH_SETUP:
                continue                     # sys.path.insert/append -- see above
            # `os.environ.get(...)` and friends: judged on the method name.
            if isinstance(sub.func, ast.Attribute) \
                    and sub.func.attr in PURE_METHOD_NAMES:
                continue
            return "calls %s()" % name
        if isinstance(sub.func, ast.Attribute):
            if sub.func.attr in PURE_METHOD_NAMES:
                continue
            return "calls .%s()" % sub.func.attr
        return "calls a computed expression"
    return None


def _is_main_guard(test):
    """True for ``__name__ == "__main__"`` (either operand order)."""
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return False
    if not isinstance(test.ops[0], ast.Eq):
        return False
    sides = [test.left, test.comparators[0]]
    names = {n.id for n in sides if isinstance(n, ast.Name)}
    consts = {n.value for n in sides if isinstance(n, ast.Constant)}
    return "__name__" in names and "__main__" in consts


def _scope_effects(body, out):
    for node in body:
        line = getattr(node, "lineno", 1)
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Pass)):
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            # A decorator runs at import; the bases of a class are evaluated
            # at import.  Everything else in here is just definition.
            for dec in list(node.decorator_list) + list(
                    getattr(node, "bases", [])):
                bad = _impure_expr(dec)
                if bad:
                    out.append((line, "the decorator/base of `%s` %s"
                                % (node.name, bad)))
            continue
        if isinstance(node, ast.Expr):
            if isinstance(node.value, ast.Constant):
                continue                     # a docstring or a string comment
            bad = _impure_expr(node.value)
            if bad:
                out.append((line, "evaluates an expression for its effect "
                                  "(it %s)" % bad))
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) \
                else [node.target]
            for tgt in targets:
                if isinstance(tgt, _SIMPLE_TARGETS):
                    continue
                inner = tgt.value if isinstance(tgt, (ast.Subscript,
                                                      ast.Attribute)) else tgt
                if _dotted(inner) in _PATH_SETUP:
                    continue                 # `sys.path[:] = ...` -- see above
                out.append((line, "assigns through `%s`, which mutates an "
                                  "object that already exists"
                            % (_dotted(tgt) or ast.dump(tgt)[:40])))
            if node.value is not None:
                bad = _impure_expr(node.value)
                if bad:
                    out.append((line, "computes a module-level value that %s"
                                % bad))
            continue
        if isinstance(node, ast.If):
            if _is_main_guard(node.test):
                # `if __name__ == "__main__":` -- the body is exactly the code
                # that does NOT run on import.  Refusing it would be refusing
                # the fix this gate asks for.
                _scope_effects(node.orelse, out)
                continue
            bad = _impure_expr(node.test)
            if bad:
                out.append((line, "a module-level `if` whose test %s" % bad))
            _scope_effects(node.body, out)
            _scope_effects(node.orelse, out)
            continue
        if isinstance(node, ast.For):
            bad = _impure_expr(node.iter)
            if bad:
                out.append((line, "a module-level `for` whose iterable %s" % bad))
            _scope_effects(node.body, out)
            _scope_effects(node.orelse, out)
            continue
        if isinstance(node, ast.Try):
            _scope_effects(node.body, out)
            for h in node.handlers:
                _scope_effects(h.body, out)
            _scope_effects(node.orelse, out)
            _scope_effects(node.finalbody, out)
            continue
        if isinstance(node, ast.Raise):
            # `raise SystemExit(...)` is how the §5 bootstrap reports a missing
            # shared layer.  Refusing to *start* is not an effect on the world,
            # and if it actually fires the probe reports it as an import error.
            continue
        out.append((line, "a module-level `%s` statement"
                    % type(node).__name__.lower()))
    return out


_BOOTSTRAP_TEXT = []


def _bootstrap_text():
    """The canonical §5 bootstrap snippet, from ``shared/scripts``.

    Exempted from the import-time gate on purpose, and only when it matches
    byte-for-byte: it rewrites ``sys.path`` (which the gate otherwise refuses,
    correctly), it is the one snippet in the tree that has to, and
    ``check_bootstrap`` already asserts every copy is identical to this
    string.  A copy that has been edited is not exempt -- it fails the gate
    *and* the bootstrap check.
    """
    if not _BOOTSTRAP_TEXT:
        try:
            pp = _load_module(PLUGIN_PATHS, "_shared_plugin_paths")
            _BOOTSTRAP_TEXT.append(pp.BOOTSTRAP)
        except Exception:
            _BOOTSTRAP_TEXT.append("")
    return _BOOTSTRAP_TEXT[0]


def module_scope_effects(text):
    """``[(line, what)]`` for everything this module DOES when imported.

    Empty means importing the module only defines names.  Anything else is a
    thing that happens the moment the harness imports it, and the harness
    refuses to import a module with a non-empty result -- see the section
    header above.  This is a precondition on the tree, not a sandbox: it is
    what makes "the test only reads the tree" true for the ordinary case, and
    what turns the extraordinary one into a FAIL naming the file and line.
    """
    boot = _bootstrap_text()
    if boot and boot in text:
        # Blank it rather than deleting it, so line numbers still point at the
        # file the reader has open.
        text = text.replace(boot, "\n" * boot.count("\n"))
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [(exc.lineno or 1, "does not parse: %s" % exc.msg)]
    return _scope_effects(tree.body, [])


_PROBED = {}


def probe_module(path):
    """Import ``path`` and probe it for slug producers, out of process.

    Returns a dict:  ``refused`` (import-time effects, so nothing was run),
    ``timeout``, ``import_error``, ``crash``, ``noise`` (anything the module
    wrote to stdout/stderr), ``exports``, ``defines``, ``producers``.
    Exactly one of ``refused`` / ``timeout`` / ``import_error`` / ``crash``
    being set means the module was not cleared -- a module the harness could
    not run is not a module it has approved.
    """
    key = os.path.abspath(path)
    if key in _PROBED:
        return _PROBED[key]
    blank = {"refused": None, "timeout": False, "import_error": None,
             "crash": None, "noise": "", "exports": [], "defines": {},
             "producers": [], "screened": []}

    effects = module_scope_effects(read(path))
    if effects:
        blank["refused"] = effects
        _PROBED[key] = blank
        return blank

    fd, out_path = tempfile.mkstemp(prefix="conv_probe.", suffix=".json")
    os.close(fd)
    try:
        proc = subprocess.run(
            [sys.executable, os.path.abspath(__file__),
             "--probe-module", os.path.abspath(path), "--probe-out", out_path],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=PROBE_TIMEOUT,
            cwd=ROOT, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        noise, rc = proc.stdout.decode("utf-8", "replace").strip(), proc.returncode
        try:
            with open(out_path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = None
        if data is None:
            blank["crash"] = ("the probe process exited %s without reporting; "
                              "output was %r" % (rc, noise[:400]))
        else:
            blank.update(data)
        blank["noise"] = noise
    except subprocess.TimeoutExpired:
        blank["timeout"] = True
    finally:
        try:
            os.remove(out_path)
        except OSError:
            pass
    _PROBED[key] = blank
    return blank


def _probe_child(path, out_path):
    """The child half of :func:`probe_module`.  Runs inside its own process."""
    result = {"import_error": None, "crash": None, "exports": [],
              "defines": {}, "producers": [], "screened": []}
    try:
        canon = _load_module(SLUGIFY, "_shared_slugify")
        corpus = [t for t, _, _ in canon.TEST_CASES] + ADVERSARIAL
        text = read(path)
        fingerprinted = sum(
            1 for _, rx in SLUG_FINGERPRINTS if rx.search(text)
        ) >= SLUG_FINGERPRINT_MIN
        try:
            mod = _load_module(path, "_probe_" + re.sub(r"\W", "_", rel(path)))
        except BaseException as exc:                   # SystemExit included
            result["import_error"] = "%s: %s" % (type(exc).__name__, exc)
            mod = None
        if mod is not None:
            result["exports"] = [str(n) for n in
                                 (getattr(mod, "__all__", []) or [])]
            for name in sorted(FORBIDDEN_SLUG_NAMES):
                result["defines"][name] = _defined_here(mod, name)
            imported = _shared_imported_names(text)
            producers, result["screened"] = _slug_producers(mod, fingerprinted)
            for name, fn in producers:
                result["producers"].append({
                    "name": name,
                    "delegates": _delegates(fn, imported),
                    "diffs": [list(d) for d in
                              _diff_against_canonical(canon, fn, corpus)],
                })
    except BaseException as exc:
        result["crash"] = "%s: %s" % (type(exc).__name__, exc)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh)
    return 0


def probe_failure(res, r):
    """The one-line reason ``r`` was not cleared, or ``None``."""
    if res["refused"]:
        return ("does things at import time, so the harness refused to "
                "execute it: %s. Move them inside `main()` (or behind "
                "`if __name__ == \"__main__\":`) -- importing a bundled "
                "script must only define names, because `python3 "
                "tests/test_conventions.py` imports every one of them"
                % "; ".join("line %d %s" % e for e in res["refused"][:4]))
    if res["timeout"]:
        return ("did not finish importing within %ds and was killed, so it "
                "could not be checked" % PROBE_TIMEOUT)
    if res["import_error"]:
        return "fails at import: %s" % res["import_error"]
    if res["crash"]:
        return "could not be probed: %s" % res["crash"]
    return None


def _call_quietly(fn, arg):
    """``(value, exception)`` from ``fn(arg)``, with stdout/stderr muted.

    Two hazards this closes, both hit while writing the behavioural check:
    a probed callable that prints corrupts the report it is printing into,
    and a probed callable that is really a CLI entry point raises
    ``SystemExit`` from inside argparse -- a ``BaseException``, which sails
    straight through ``except Exception`` and takes the harness with it.
    """
    sink = io.StringIO()
    saved = (sys.stdout, sys.stderr)
    sys.stdout = sys.stderr = sink
    try:
        return fn(arg), None
    except KeyboardInterrupt:
        raise
    except BaseException as exc:                   # SystemExit included
        return None, exc
    finally:
        sys.stdout, sys.stderr = saved


def _stem_of(fn, title):
    """Normalise one slug entry point to ``stem-or-None``.

    The canonical module raises ``SlugError`` on an unsluggable title; a
    vendored copy may instead return ``""``.  Both mean the same thing, and
    conflating them would hide a real difference, so both map to ``None``.
    Any *other* exception is a real difference and is reported as one.
    """
    out, exc = _call_quietly(fn, title)
    if exc is not None:
        if isinstance(exc, ValueError) or type(exc).__name__ == "SlugError":
            return None
        return "<raised %s: %s>" % (type(exc).__name__, exc)
    if out is None or out == "" or out == ".md":
        return None
    if not isinstance(out, str):
        return "<returned %s, not a string>" % type(out).__name__
    return out[:-3] if out.endswith(".md") else out


def _stem_via(mod, title):
    """``_stem_of`` over whichever entry point a module happens to publish."""
    for fname in ("slug_stem", "slug", "slugify"):
        fn = getattr(mod, fname, None)
        if callable(fn):
            return _stem_of(fn, title)
    raise HarnessError("%s exposes no slug entry point" % mod.__name__)


def _defined_here(mod, name):
    """True when ``mod.name`` is a callable DEFINED in ``mod``.

    ``__module__`` is what separates a definition from a re-export: a
    `from slugify import slug_stem` binds the canonical function, whose
    ``__module__`` stays `slugify`, while a `def` -- or a `lambda`, which no
    AST FunctionDef scan sees -- carries the importing module's own name.
    """
    obj = getattr(mod, name, None)
    return callable(obj) and getattr(obj, "__module__", None) == mod.__name__


def _takes_one_title(fn):
    """True when ``fn(title)`` binds -- checked without calling anything."""
    try:
        inspect.signature(fn).bind("probe")
    except (TypeError, ValueError):
        return False
    return True


def _looks_pure(fn, mod=None, _seen=None):
    """True when nothing ``fn`` reaches touches the world.

    A syntactic screen, and deliberately a blunt one: this decides which
    callables the probe is willing to CALL.  A slug function calls none of
    :data:`IMPURE_NAMES`, so a false negative here costs a candidate that was
    never a slug function anyway.

    **It follows calls.**  Reading only ``fn``'s own source made the screen
    one level deep and therefore not a screen: ::

        def slug_stem(title):        # no IMPURE_NAME appears here
            return _helper(title)

        def _helper(title):
            open("/tmp/x", "a").write(title)      # ... but it does here
            return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")

    passed, and was then called once per corpus entry.  Any name ``fn`` uses
    that resolves to a function defined in the same module is screened too,
    transitively, with a visited set for mutual recursion.  A callable whose
    source cannot be read at all (a C function, a ``functools.partial``, an
    instance with ``__call__``) is refused rather than guessed at.
    """
    if _seen is None:
        _seen = set()
    if id(fn) in _seen:
        return True                      # already being screened; not a hole
    _seen.add(id(fn))
    try:
        src = textwrap.dedent(inspect.getsource(fn))
        tree = ast.parse(src)
    except (OSError, TypeError, SyntaxError, IndentationError):
        return False
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if node.id in IMPURE_NAMES:
                return False
            used.add(node.id)
        if isinstance(node, ast.Attribute) and node.attr in IMPURE_NAMES:
            return False
    if mod is None:
        return True
    for name in sorted(used):
        obj = getattr(mod, name, None)
        if (callable(obj) and not inspect.isclass(obj)
                and getattr(obj, "__module__", None) == mod.__name__):
            if not _looks_pure(obj, mod, _seen):
                return False
    return True


def _produces_slugs(fn):
    """Ask a callable, by running it, whether it turns titles into slugs.

    This is the whole point of the strengthened check.  The five-line stub
    that shadowed the canonical module defined no function an AST scan could
    see and matched one fingerprint out of seven -- but handed
    ``"ROC curve"`` back as ``"roc-curve"``, because that is what a slug
    function does.  Behaviour is not evadable by writing the algorithm in a
    different idiom, under a different name, or in six lines.
    """
    hits = 0
    for probe in SLUG_DUCK_PROBES:
        out, exc = _call_quietly(fn, probe)
        if exc is not None:
            continue                    # refused this input; try the next
        if isinstance(out, str):
            stem = out[:-3] if out.endswith(".md") else out
            if SLUG_SHAPE_RE.match(stem):
                hits += 1
    return hits >= 2


def _slug_producers(mod, fingerprinted):
    """``([(name, fn)], [screened_name])``: callables in ``mod`` producing slugs.

    Candidates are gated on name (or on the module having tripped the
    fingerprint scan) purely to bound what gets executed; membership is then
    decided by running the thing.  Aliases of one function are collapsed, so
    a module exposing `slugify = slug_stem` is one producer, not two.

    The second list is candidates :func:`_looks_pure` refused to run.  They
    are returned rather than dropped: a slug-API-named callable that the
    harness declines to execute has not agreed with the canonical module, it
    has gone unchecked, and silence there is the shape this whole file exists
    to prevent.  Only candidates that *claim* to be an implementation (a
    §4a-published name) are listed -- a screened
    `normalize_fig_num` is not a slug function and reporting it would be
    noise.
    """
    out, screened, seen = [], [], set()
    for name, obj in sorted(vars(mod).items()):
        if not callable(obj) or inspect.isclass(obj):
            continue
        if getattr(obj, "__module__", None) != mod.__name__:
            continue                    # imported from elsewhere: delegation
        if not (SLUGGY_NAME_RE.search(name)
                or name.lstrip("_") in CANONICAL_SLUG_API
                or fingerprinted):
            continue
        if id(obj) in seen or not _takes_one_title(obj):
            continue
        if not _looks_pure(obj, mod):
            # A weak module fingerprint widens discovery, but cannot make an
            # unrelated CLI/linter claim to be a slug implementation. Unicode
            # filename comparison plus a Markdown table separator already
            # supplies two fingerprints. Strong module-level evidence remains
            # checked separately against SLUG_FINGERPRINT_UNVERIFIABLE.
            if name.lstrip("_") in CANONICAL_SLUG_API:
                screened.append(name)
            continue
        if _produces_slugs(obj):
            seen.add(id(obj))
            out.append((name, obj))
    return out, screened


#: `Title` -> `slug`, in prose or in a two-column table row.  This is the
#: shape §4a forbids ("Do not restate the table") -- but a restatement that
#: *agrees* is only a maintenance hazard, while one that disagrees is the
#: C++/c bug in documentation form, so the check is agreement, not absence.
#: (A) the §4a command-line examples, which claim an exact output of the
#: canonical script; (B) a restated slug *table* -- the shape §4a forbids; and
#: (C) a prose consequence written as `Some Title` -> `some-title.md`.
#: The tree is full of unrelated `x` -> `y` mappings (`image/jpeg` -> `jpg`,
#: `#machine-learning` -> `machine-learning-moc.md`, `2024` -> `2024-01-01`),
#: so each trigger is deliberately narrow: reading one of those as a slug
#: claim would report the harness's own confusion as drift.
SLUG_CLI_RE = re.compile(
    r"slugify\.py\s+\"([^\"\n]{1,60})\"[^\n]*?#\s*->\s*(?:\{[^\n]*?\"slug\"\s*:\s*\")?"
    r"([a-z0-9][a-z0-9-]*)")
SLUG_TABLE_ROW_RE = re.compile(
    r"^\|\s*`?([^`|\n]{1,60}?)`?\s*\|\s*`?([a-z0-9][a-z0-9-]*(?:\.md)?)`?\s*\|", re.M)
SLUG_PROSE_RE = re.compile(
    r"`([^`\n]{1,60})`\s*(?:→|->|—>)\s*`([a-z0-9][a-z0-9-]*\.md)`")
SLUG_CONTEXT = re.compile(r"slug", re.I)
#: A paragraph that is exhibiting a *wrong* pairing on purpose.  This tree
#: teaches by counter-example ("title in full form but slug in acronym
#: (`\"Data-Efficient Image Transformer\"` -> `deit.md`)"), and reading a
#: counter-example as a claim reports the documentation of a bug as the bug.
COUNTEREXAMPLE_CUE = re.compile(
    r"incoheren|mismatch|wrong|violat|never leave|must not|instead of|"
    r"failure|stale|drifted|disagree", re.I)


def _check_slug_claims(rep, check, canon):
    """Every stated `Title` -> `slug` pair agrees with the canonical module.

    CONVENTIONS.md §4a says the algorithm is the script and the table must not
    be restated -- but nothing checked that the *consequences* it does state
    ("`Feature (machine learning)` -> `feature-machine-learning.md`") are
    still true, nor that a skill restating a pair got it right.  A prose table
    that disagrees with the script is the same bug as a vendored copy that
    disagrees with it: the reader follows the prose.
    """
    n = 0
    for path, text in walk_plugin_files():
        if not path.endswith(".md"):
            continue
        claims = [(m.group(1), m.group(2), m.start())
                  for m in SLUG_CLI_RE.finditer(text)]
        for block, boff in _tables(text):
            head = block.splitlines()[0].lower()
            if not re.search(r"\|\s*\**slug\**\s*\|", head):
                continue
            claims += [(m.group(1), m.group(2), boff + m.start())
                       for m in SLUG_TABLE_ROW_RE.finditer(block)]
        for m in SLUG_PROSE_RE.finditer(text):
            a = text.rfind("\n\n", 0, m.start()) + 1
            b = text.find("\n\n", m.end())
            para = text[a:b if b != -1 else len(text)]
            # A title-shaped left side only: `#machine-learning` ->
            # `machine-learning-moc.md` is §3's MOC derivation, not a slug.
            if (SLUG_CONTEXT.search(para) and re.search(r"[A-Z ]", m.group(1))
                    and not COUNTEREXAMPLE_CUE.search(para)):
                claims.append((m.group(1), m.group(2), m.start()))

        for title, claimed, off in claims:
            if claimed.endswith(".md"):
                claimed = claimed[:-3]
            try:
                got = canon.slug_stem(title)
            except Exception:
                got = None
            if got is None:
                continue        # unsluggable titles are §4a's own case
            n += 1
            if got != claimed:
                rep.fail(check,
                         "%s states `%s` -> `%s`, but "
                         "shared/scripts/slugify.py computes `%s`. A "
                         "restated slug that disagrees with the one "
                         "implementation is the C++/c bug in prose form: "
                         "a reader follows the text, the linter follows "
                         "the script, and a correctly-named entry becomes "
                         "a rename candidate."
                         % (rel(path), title, claimed, got),
                         at(path, off, text))
    rep.saw(check, "stated title-to-slug pairs", n)
    if n:
        rep.ok(check, "%d stated `Title` -> `slug` pair(s) agree with "
                      "shared/scripts/slugify.py" % n)


#: The self-test may only ever GROW.  A floor, not an equality: the old
#: `result["total"] == 40` made every added case a failing build, so the
#: cheapest way to keep the suite green was to leave the gaps alone -- and
#: CONVENTIONS.md §4a named three real ones (Greek capitals, final sigma, CJK)
#: that stayed open for exactly that reason.  A shrink is still a failure.
SLUG_SELFTEST_MIN = 61          # the 2026-08-31 tally; shrink = FAIL


def _check_slug_exports(rep, check, canon):
    """`slugify.py`'s `__all__` matches the surface its docstring publishes.

    The docstring's `from slugify import ...` line is the module's advertised
    API; `__all__` is what a star-import and every reader's mental model
    actually get.  A name in one and not the other is a promise the module
    does not keep -- and the fix for that is one line, so nothing should be
    holding it open.
    """
    doc = canon.__doc__ or ""
    m = re.search(r"from slugify import ([A-Za-z_0-9, ]+)", doc)
    documented = set(re.findall(r"[A-Za-z_][A-Za-z_0-9]*", m.group(1))) if m else set()
    exported = list(getattr(canon, "__all__", []) or [])
    rep.saw(check, "public names slugify.py's docstring documents", len(documented))
    rep.saw(check, "names in slugify.py's __all__", len(exported))

    undeclared = sorted(n for n in documented if n not in exported)
    if undeclared:
        rep.fail(check,
                 "shared/scripts/slugify.py's docstring documents %s but "
                 "__all__ does not export %s. The docstring is the API a "
                 "caller reads; __all__ is the API they get."
                 % (", ".join(sorted(documented)), ", ".join(undeclared)),
                 rel(SLUGIFY))
    dangling = sorted(n for n in exported if not hasattr(canon, n))
    if dangling:
        rep.fail(check,
                 "shared/scripts/slugify.py's __all__ exports %s, which the "
                 "module does not define -- `from slugify import *` raises "
                 "AttributeError." % ", ".join(dangling), rel(SLUGIFY))
    if not undeclared and not dangling:
        rep.ok(check, "slugify.py's __all__ (%d names) exports everything its "
                      "docstring documents (%s) and nothing it lacks"
               % (len(exported), ", ".join(sorted(documented))), rel(SLUGIFY))


def _check_adversarial_canonical(rep, check, canon):
    """Run :data:`ADVERSARIAL` against the CANONICAL module, unconditionally.

    Previously this corpus was only ever handed to a *duplicate*
    implementation, so on the tree it is meant to protect -- one
    implementation, no duplicate -- it never ran.  Nothing was checking that
    the canonical module itself still handles the shapes the list was built
    from.

    Three properties, because "it did not crash" is not a check:
      * every input either yields a well-formed stem or refuses with
        SlugError -- any other exception is a crash in a linter's hot path;
      * `C`, `C++`, `C#`, `C*`, `A*` yield five DISTINCT stems, which is the
        entire reason FIX-B exists (without it all five are `c`);
      * the pairs §4a says must agree do agree, and the pair it says must
        differ differs.
    """
    n, bad = 0, []
    for title in ADVERSARIAL:
        n += 1
        try:
            stem = _stem_of(canon.slug_stem, title)
        except Exception as exc:
            bad.append("%r raised %s: %s (only SlugError is a legal refusal)"
                       % (title, type(exc).__name__, exc))
            continue
        if stem is not None and not SLUG_SHAPE_RE.match(stem):
            bad.append("%r -> %r, which is not a well-formed slug stem"
                       % (title, stem))
    rep.saw(check, "adversarial titles run against the canonical module", n)
    if bad:
        rep.fail(check, "shared/scripts/slugify.py mishandles %d adversarial "
                        "title(s): %s" % (len(bad), "; ".join(bad[:6])),
                 rel(SLUGIFY))
    else:
        rep.ok(check, "all %d adversarial titles either slug cleanly or refuse "
                      "with SlugError" % n, rel(SLUGIFY))

    family = ["C", "C++", "C#", "C*", "A*"]
    got = {t: _stem_of(canon.slug_stem, t) for t in family}
    if len(set(got.values())) != len(family):
        rep.fail(check,
                 "the symbol-word family collapses: %s. Without FIX-B all five "
                 "titles slug to `c`, so four correctly-named entries become "
                 "rename candidates onto one destination and each rename "
                 "clobbers the last." % got, rel(SLUGIFY))
    else:
        rep.ok(check, "`C`/`C++`/`C#`/`C*`/`A*` slug to five distinct stems "
                      "(%s)" % ", ".join(got[t] for t in family), rel(SLUGIFY))

    # (title_a, title_b, must_be_equal, why)
    pairs = [("Ca2+", "Ca²⁺", True, "ASCII and typeset cation (FIX-A)"),
             ("Cl-", "Cl⁻", True, "ASCII and typeset anion (FIX-A)"),
             ("µm", "μm", False, "micro sign U+00B5 vs Greek mu U+03BC")]
    for a, b, same, why in pairs:
        sa, sb = _stem_of(canon.slug_stem, a), _stem_of(canon.slug_stem, b)
        if (sa == sb) != same:
            rep.fail(check,
                     "%r -> %r and %r -> %r, but §4a requires them to %s: %s"
                     % (a, sa, b, sb, "agree" if same else "differ", why),
                     rel(SLUGIFY))
        else:
            rep.ok(check, "%r and %r %s (%s)"
                   % (a, b, "agree on %r" % sa if same else
                      "differ (%r vs %r)" % (sa, sb), why), rel(SLUGIFY))


def _shared_imported_names(text):
    """Local names this module bound from the canonical ``slugify`` module."""
    tree = _parsed(text)
    if tree is None:
        return set()
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "") == "slugify":
            out.update(a.asname or a.name for a in node.names)
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "slugify":
                    out.add(a.asname or a.name)
    return out


def _delegates(fn, imported):
    """True when ``fn``'s own source uses a name imported from ``slugify``.

    This is what separates wiki-linter's blessed `slug()` wrapper -- which
    calls `slugify.slug_stem` and merely swallows `SlugError` -- from a
    second implementation.  Delegation is the whole test: a producer that
    agrees today without delegating is a copy, and copies are what diverge.
    """
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    except (OSError, TypeError, SyntaxError, IndentationError):
        return False
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    used |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    return bool(used & imported)


def _diff_against_canonical(canon, fn, corpus):
    """``[(title, canonical, got)]`` for every case ``fn`` gets differently."""
    diffs = []
    for title in corpus:
        want = _stem_of(canon.slug_stem, title)
        got = _stem_of(fn, title)
        if want != got:
            diffs.append((title, want, got))
    return diffs


def check_slug_single_implementation(rep, conv):
    check = "slug-single-impl"

    if not os.path.isfile(SLUGIFY):
        rep.fail(check, "canonical shared/scripts/slugify.py is missing")
        return
    canon = _load_module(SLUGIFY, "_shared_slugify")

    # (a) the canonical implementation still passes its own suite, from its
    #     new home.  The count is reported and floored, never pinned.
    result = canon.run_self_test()
    if not result["ok"]:
        rep.fail(check, "shared/scripts/slugify.py self-test %d/%d failed: %s"
                 % (result["passed"], result["total"],
                    json.dumps(result["failures"], ensure_ascii=False)),
                 rel(SLUGIFY))
    elif result["total"] < SLUG_SELFTEST_MIN:
        rep.fail(check,
                 "shared/scripts/slugify.py's self-test has shrunk to %d cases "
                 "(floor: %d). Coverage may grow; it may not be deleted."
                 % (result["total"], SLUG_SELFTEST_MIN), rel(SLUGIFY))
    else:
        rep.ok(check, "shared/scripts/slugify.py self-test %d/%d"
               % (result["passed"], result["total"]), rel(SLUGIFY))

    # (a2) the module's advertised surface and its actual surface agree.
    _check_slug_exports(rep, check, canon)

    # (a3) the adversarial corpus, run against the canonical module itself.
    _check_adversarial_canonical(rep, check, canon)

    corpus = [t for t, _, _ in canon.TEST_CASES] + ADVERSARIAL

    # (b) THE STRUCTURAL RULE.  There is one implementation and it is not in a
    #     skill, so under skills/ the name `slugify.py` and the exported names
    #     `slugify`/`slug_stem` are violations on sight -- no agreement test,
    #     no registry, no reprieve.  Whether such a file's answers happen to
    #     match today is beside the point: it owns what `import slugify`
    #     resolves to for every script beneath it.
    #
    # (c) THE BEHAVIOURAL RULE.  Every module under skills/ is imported and
    #     its callables are RUN against the canonical corpus.  This is what
    #     replaces the fingerprint scan as the load-bearing check: the copy
    #     most likely to disagree is the terse wrong one, and terse wrong
    #     copies are exactly what a syntactic scan cannot see.
    pending = Registry(rep, check, conv, "slug-duplicates",
                       "the vendored slug copy")
    n_scanned = n_producers = n_skill_modules = 0

    for path, text in walk_python_sources():
        n_scanned += 1
        r = rel(path)
        under_skills = os.path.abspath(path).startswith(SKILLS_DIR + os.sep)
        if under_skills:
            n_skill_modules += 1
        hits = [name for name, rx in SLUG_FINGERPRINTS if rx.search(text)]
        fingerprinted = len(hits) >= SLUG_FINGERPRINT_MIN

        res = probe_module(path)
        why = probe_failure(res, r)
        if why:
            rep.fail(check,
                     "%s %s, so it could not be checked for a second slug "
                     "implementation. A module the harness cannot run is not "
                     "a module it has cleared." % (r, why), r)
            continue

        # (b) structural violations
        hard = []
        if under_skills and os.path.basename(path) == "slugify.py":
            hard.append("is named `slugify.py`, so `import slugify` in every "
                        "script in this directory resolves here")
        declared = set(res["exports"])
        for name in sorted(FORBIDDEN_SLUG_NAMES):
            if not under_skills:
                continue
            if res["defines"].get(name):
                hard.append("defines `%s`" % name)
            elif name in declared:
                hard.append("re-exports `%s` in __all__" % name)
        if hard:
            rep.fail(check,
                     "%s %s. CONVENTIONS.md §4a publishes those names for ONE "
                     "module and it is shared/scripts/slugify.py -- there is no "
                     "correct copy of the slug algorithm under skills/, only "
                     "copies that have not diverged yet. Delete it and reach "
                     "the canonical module through the §5 bootstrap."
                     % (r, " and ".join(hard)), r)

        # (b2) the syntactic channel, kept as a hint only: a non-delegating
        #      slug-API `def` that the behavioural pass finds nothing runnable
        #      behind.  It never fails a file by itself -- see (d).
        stale = ["defines `%s()` at line %d without delegating to "
                 "shared/scripts/slugify.py" % (name, lineno)
                 for name, lineno, delegates in _slug_api_definitions(text)
                 if not delegates]

        # (c) behaviour decides.  Every producer is run against the corpus --
        #     in the probe subprocess, not here -- and a producer that does not
        #     DELEGATE to the canonical module is a second implementation
        #     whether or not it agrees today.
        producers = res["producers"]
        agreed, disagreed, vendored = [], [], []
        for p in producers:
            n_producers += 1
            if not p["delegates"]:
                vendored.append(p["name"])
            diffs = [tuple(d) for d in p["diffs"]]
            (disagreed if diffs else agreed).append((p["name"], diffs))

        def _where(name):
            m = re.search(r"(?m)^\s*(?:async\s+)?(?:def\s+)?%s\s*[=(]"
                          % re.escape(name), text)
            return "%s:%d" % (r, line_of(text, m.start()) if m else 1)

        if disagreed:
            name, diffs = disagreed[0]
            shown = "; ".join("%r -> canonical %r, this %r" % d
                              for d in diffs[:5])
            rep.fail(check,
                     "%s DISAGREES with shared/scripts/slugify.py: `%s()` gets "
                     "%d of %d cases differently%s. %s%s -- this is the C++/c "
                     "class of bug: the linter recomputes a slug, gets a "
                     "different answer than the one that named the file, and "
                     "proposes renaming a correctly-named entry. An approved "
                     "rename rewrites links vault-wide."
                     % (r, name, len(diffs), len(corpus),
                        "" if len(disagreed) == 1 else
                        " (so do %s)" % ", ".join("`%s()`" % n
                                                  for n, _ in disagreed[1:]),
                        shown,
                        "" if len(diffs) <= 5 else
                        " (+%d more)" % (len(diffs) - 5)),
                     _where(name))
        elif agreed:
            rep.ok(check, "%s: %s agree with the canonical slug on all %d cases"
                   % (r, ", ".join("`%s()`" % n for n, _ in agreed), len(corpus)),
                   _where(agreed[0][0]))

        if vendored and not hard:
            # A second home for the fact, agreeing or not.  Agreement today is
            # not the property that matters: the next edit to either copy is.
            note = "; ".join(["produces slugs from %s without delegating to "
                              "shared/scripts/slugify.py"
                              % ", ".join("`%s()`" % n for n in vendored)]
                             + (["fingerprints: %s" % ", ".join(hits)]
                                if fingerprinted else []))
            msg = "%s ships a second copy of the slug algorithm (%s)" % (r, note)
            if pending.claims(r):
                pending.hit(r, msg + (
                    " -- and it DISAGREES with the canonical module (the hard "
                    "failure above); registration parks the duplication, never "
                    "a divergence" if disagreed else
                    " -- verified above to agree with shared/scripts/slugify.py "
                    "on every case, but it is still a second home for the fact, "
                    "and the next edit to either copy is what re-opens the bug"
                ), _where(vendored[0]))
            else:
                rep.fail(check, msg + " and is NOT registered in "
                         "CONVENTIONS.md §10. Import it from shared/scripts/ "
                         "via the §5 bootstrap instead -- divergent copies are "
                         "the bug the shared layer exists to prevent.",
                         _where(vendored[0]))

        # (d) claimed to be an implementation, but nothing in it would run.
        if not producers and not hard:
            claims = list(stale)
            claims += ["defines `%s()`, which the harness declined to execute "
                       "because its source reaches the world (a slug function "
                       "does not)" % n for n in res["screened"]]
            if len(hits) >= SLUG_FINGERPRINT_UNVERIFIABLE:
                claims.append("fingerprints: %s" % ", ".join(hits))
            if claims:
                rep.fail(check,
                         "%s looks like a second slug implementation (%s) but "
                         "exposes no one-argument callable the harness could "
                         "run against the canonical corpus, so its agreement "
                         "is UNVERIFIED -- it did not pass, it was not "
                         "checked. Give it a callable entry point or delete "
                         "the copy." % (r, "; ".join(claims)), r)

    rep.saw(check, "python sources scanned for a second slug implementation",
            n_scanned)
    rep.saw(check, "modules under skills/ imported and probed for slug output",
            n_skill_modules)
    # NOT a violation count: the tree is healthy when the only slug producers
    # under skills/ are the blessed delegating wrappers.  It must still be
    # non-zero, or the behavioural check is executing nothing and this whole
    # section is decoration.
    rep.saw(check, "slug-producing callables executed against the corpus",
            n_producers)

    _check_slug_claims(rep, check, canon)
    pending.finish()


# ===========================================================================
# check 3 -- the figure-naming pattern
# ===========================================================================

#: A statement of how to *find* figures: a stem placeholder, `_fig`, then a
#: glob star or a separator.
FIG_GLOB_RE = re.compile(
    r"(?:\[[a-z_]*stem\]|<[a-z_]*stem>|\[source_stem\]|\[pdf_stem\]|<slug>|<stem>)"
    r"_fig(_?)(\*|<N>|<numbers>|N\b|[0-9])")

#: The literal bad glob: matching `_fig_*` misses every `_fig<N>` producer.
FIG_BAD_GLOB_RE = re.compile(r"_fig_\*")

#: The stem placeholder a §8 pattern opens with -- `[source_stem]_fig*`,
#: `<note_stem>_fig_<N>.<ext>`.  Both halves of §8 are matched with it, so the
#: consumer glob and the producer table can be held to the same stem.
FIG_GLOB_STEM_RE = re.compile(r"[\[<]([a-z_]+)[\]>]_fig")

#: The number-or-placeholder that follows the `_fig` token in a figure name.
#: Factored out of :data:`FIG_NAME_RE` so the near-miss pattern below can
#: require the *same* tail: `_figure_1.png` is a figure name spelt wrong,
#: `_figures/` is a folder and none of this check's business.
FIG_TAIL = (r"(?:\*|<[A-Za-z_][A-Za-z_ -]*>|\{[a-z_]+[^}]*\}|%[0-9]*[sd]|"
            r"S?[0-9]|[NS]\b|ED[0-9]|SI[0-9])")

#: Any *concrete* figure filename or format string, with no stem placeholder
#: required.  `FIG_GLOB_RE` above only sees a name introduced by a bracketed
#: stem, so a worked example (`Teslo_Pancreatic_Cancer_2026_fig3.webp`) or an
#: f-string in a producer script (`f"{pdf_stem}_fig{n}.png"`) -- the two forms
#: a human actually copies -- were both invisible to it.
FIG_NAME_RE = re.compile(r"_fig(_?)(%s)" % FIG_TAIL)

#: A figure name whose token is ALMOST `_fig`.  :data:`FIG_NAME_RE` verifies
#: the separator *inside* an already-recognised `_fig` token, so a file that
#: abandons the token entirely contributes no results at all rather than a
#: failure: `sed -i 's/_fig_/_figure_/g'` over two reference files took 16
#: checks out of the run, left a PASS, and tripped no vacuity guard -- the
#: population is plugin-wide, so two files emptying is invisible in the total.
#: Anything in this shape is either the convention spelt wrong or a second
#: convention, and §8 has room for neither.
#: The same tail, written to consume a whole *filename* number rather than one
#: digit, and never a year: `doe_figs_2025.pdf` is a PDF stem, not a figure.
FIG_NEAR_TAIL = (r"(?:\*|<[A-Za-z_][A-Za-z_ -]*>|\{[a-z_]+[^}]*\}|%[0-9]*[sd]|"
                 r"(?:S|ED|SI)?[0-9]{1,3}(?![0-9])(?:[-.][0-9]{1,3})*)")
FIG_NEAR_MISS_RE = re.compile(
    r"_(?:figure|figures|figs|fgs?|imgs?|images?|plates?|panels?)[_\-.]?"
    r"%s(?:\.[a-z]{2,4}\b|\*)"
    r"|_fig[-.]%s(?:\.[a-z]{2,4}\b|\*)" % (FIG_NEAR_TAIL, FIG_NEAR_TAIL))

#: §8a: "accept any extension".  A consumer that pins one is the strict-glob
#: failure in a different spelling -- clippings can produce nine formats.
FIG_EXT_PINNED_RE = re.compile(r"_fig\*\.[a-z]{2,4}")

#: §8a: "Match on `[source_stem]_fig`, never on `[source_stem]_fig_`".  Prose
#: telling a consumer to match the strict prefix has the same effect as the
#: strict glob and none of its literal characters.
FIG_STRICT_TOKEN_RE = re.compile(r"`\[?[a-z_]*stem\]?_fig_`")
FIG_STRICT_CUE = re.compile(
    r"(?:begin|start|prefix|whose name|match(?:ing|es)?|only|list)[^.\n]{0,60}$",
    re.I)
#: §8a states the rule *by negation* ("Match on `[stem]_fig`, never on
#: `[stem]_fig_`"), and every correct restatement does the same.  Without this
#: guard the check reports the canonical wording as the violation.
FIG_STRICT_NEGATED = re.compile(
    r"\b(?:not|never|rather than|instead of|avoid|don't|do not|no)\b[^.\n]{0,30}$",
    re.I)

#: The same escape, for a *filename* rather than a glob.  §8c is explicit that
#: pre-convergence and hand-named files are still on disk, so a file has to be
#: able to write one down -- to say what a consumer will meet, or to build a
#: fixture out of one.  Without this it could not: the only way past the check
#: was to obscure the name (`"_fig" + "3.png"`), which hides it from every
#: reader too.  Wider than :data:`FIG_STRICT_NEGATED` because these names are
#: written in *code*, where the sentence that explains them is the comment on
#: the line above -- but bounded, and quoted back into the report so an
#: excused name is visible rather than silent.
FIG_NAME_NEGATED = re.compile(
    r"\b(?:not|never|rather than|instead of|avoid|don't|do not|no longer|"
    r"used to|predat\w+|older|legacy|pre-convergence|hand-?named|"
    r"before the (?:naming )?convergence|already (?:sitting|on disk))\b", re.I)
#: How far back the cue above may sit.  Two or three lines: the comment that
#: introduces a fixture, not the paragraph before last.
FIG_NAME_NEGATED_REACH = 240


def _fig_name_excused(text, start):
    """The cue excusing a non-canonical figure name at ``start``, or ``""``."""
    m = FIG_NAME_NEGATED.search(text[max(0, start - FIG_NAME_NEGATED_REACH):start])
    return m.group(0) if m else ""

#: A *concrete* figure filename -- literal stem, literal number, literal
#: extension.  Placeholders (`[source_stem]`, `<slug>`) are excluded by the
#: leading character class.
FIG_CONCRETE_STEM_RE = re.compile(
    r"(?<![\w./<>\[-])([A-Za-z0-9][A-Za-z0-9._-]*)_fig_[A-Za-z0-9-]+\.[a-z]{2,4}\b")

#: An image embed on a line of its own. Wiki and summary writers supply an
#: italic caption immediately below; clipping captions depend on the source.
FIG_EMBED_RE = re.compile(r"^!\[\[([^\]\n]+)\]\][ \t]*$", re.M)


#: Floor, not a pin -- exactly like SLUG_SELFTEST_MIN.  Coverage may grow
#: freely; only a shrink fails, which is what stops a case being quietly
#: deleted to make a regression go away.
NAMING_SELFTEST_MIN = 161       # the 2026-08-31 tally; shrink = FAIL

#: Corpus floor for figure-naming (c), separately from behavioral case counts.
#: Rebased after the 2026-08-31 documentation consolidation: 352 occurrences
#: became 292 by removing repeated instructions/examples. All label families
#: remain covered; the only removed unique token, _fig_SI1, has SI3 examples
#: and extractor tests. Rebase only after auditing intended content moves;
#: near-miss tokens and every remaining filename are still checked below.
FIG_NAME_MIN = 292

#: The three consumers of the source-filename rule (§1a names them all), and
#: the surface each one must be getting from the shared module rather than
#: defining for itself.  paper_scan.py was the one importer this map did not
#: watch -- a local rebind of its skip logic would have gone unseen.
NAMING_CONSUMERS = {
    os.path.join("pdf-organizer", "scripts", "organize.py"):
        ("looks_canonical", "CANONICAL"),
    os.path.join("pdf-figure-extractor", "scripts", "batch_extract.py"):
        ("chapter_book_stem", "core_stem"),
    os.path.join("paper-summarizer", "scripts", "paper_scan.py"):
        ("chapter_book_stem", "core_stem", "looks_canonical"),
}

#: Names that may only come from `naming.py`.  A module under skills/ that
#: BINDS one of these itself owns what its own callers resolve, whatever its
#: answers happen to be today -- which is the whole failure mode.
NAMING_RESERVED = ("CANONICAL", "CHAPTER_STEM_RE", "SAFE_NAME",
                   "looks_canonical", "chapter_parts", "chapter_book_stem",
                   "core_stem", "split_tail")


def _bound_names(tree):
    """Every name a module BINDS, at any nesting level, with its line.

    The old test was `(?m)^(?:%s\\s*=|def\\s+%s\\b)` -- column-0 assignment or
    column-0 `def`.  Four spellings of the same second implementation walked
    straight through it: `class Names: CANONICAL = …` (indented),
    `CANONICAL: "re.Pattern" = …` (annotated), `CANONICAL, OTHER = …` (tuple),
    and a `def looks_canonical` nested inside any block.  A binding is a
    binding wherever it sits, so ask the parser, not the left margin.

    Imports are deliberately NOT bindings here: `from naming import CANONICAL`
    binds the name to the canonical object, which is the whole point.
    """
    out = {}

    def note(name, node):
        if isinstance(name, str):
            out.setdefault(name, node.lineno)

    def target(node):
        if isinstance(node, ast.Name):
            note(node.id, node)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for elt in node.elts:
                target(elt)
        elif isinstance(node, ast.Starred):
            target(node.value)

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                target(t)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            target(node.target)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
            note(node.name, node)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            target(node.target)
        elif isinstance(node, ast.NamedExpr):        # 3.8+ walrus
            target(node.target)
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            target(node.optional_vars)
    return out


#: Every literal regex a module compiles, so the rule can be caught under a
#: name nobody thought to reserve.  A blocklist only ever catches the spelling
#: that already burned someone: `CHAPTER_STEM_RE` is on it because that copy
#: existed, and the identical rule reintroduced as `SRC_NAME_RE` beside a
#: `def is_organized(name)` is invisible to it.  Shape, not name.
_RE_CALLS = ("compile", "match", "search", "fullmatch", "findall", "finditer",
             "sub", "subn", "split")


def _compiled_patterns(tree):
    """Yield (pattern_source, lineno) for every literal regex in `tree`."""
    literals = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            literals[node.targets[0].id] = node.value.value
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else \
            (fn.id if isinstance(fn, ast.Name) else "")
        if name not in _RE_CALLS:
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            yield arg.value, node.lineno
        elif isinstance(arg, ast.Name) and arg.id in literals:
            yield literals[arg.id], node.lineno
        elif isinstance(arg, ast.JoinedStr) or isinstance(arg, ast.BinOp):
            parts = [n.value for n in ast.walk(arg)
                     if isinstance(n, ast.Constant) and isinstance(n.value, str)]
            if parts:
                yield "".join(parts), node.lineno


#: The `<Year>` segment of §1a's shape: a four-digit atom right after an `_`,
#: however a regex spells it and through whatever group or alternation opener
#: sits between -- `_(?:\d{4}|nd)`, `_(\d{4})`, `_[0-9]{4}`.
_RX_YEAR_SEG = re.compile(r"_[^_]{0,14}?(?:\\d|\[0-9\]|\[\\d\])\{4\}")
#: A `_NN_` chapter segment: two digits fenced by underscores.  §1a: "`NN` is a
#: zero-padded two-digit chapter number", and it is the token that tells a
#: chapter from its book.
_RX_CHAPTER_SEG = re.compile(r"_(?:\\d|\[0-9\]|\[\\d\])\{2\}_")
#: An underscore-separated author/title run: a repeated character class or
#: `\w` immediately followed by the `_` that separates §1a's segments.
_RX_NAME_RUN = re.compile(r"(?:\[[^\]]+\]|\\w|\.)[*+](?:\?)?_")


def _restates_naming_shape(pattern):
    """Does `pattern` re-implement §1a's filename shape, whatever it is called?

    Two independently sufficient shapes, because the two consumers key off
    different halves: the `<Author>_<AbbrevTitle>_<Year>` run, and the `_NN_`
    chapter segment that tells a chapter from its book.  `naming.py` lives in
    shared/, not skills/, so the canonical copy is out of scope by
    construction and this needs no name-based exemption.
    """
    if _RX_CHAPTER_SEG.search(pattern):
        return "a `_NN_` chapter segment"
    if _RX_YEAR_SEG.search(pattern) and _RX_NAME_RUN.search(pattern):
        return "an author/title run followed by a four-digit year"
    return ""


#: A backticked stem carrying BOTH a chapter segment and a `_src` / `_2` tail
#: -- the only shape whose *order* §1a pins down, and therefore the only one
#: worth asking the module about.  `Prince_UDL_2026_src.pdf` (tail, no
#: chapter) and `<book core stem>_NN_Name` (chapter, no tail) state nothing
#: about the ordering and are not claims.
NAMING_STEM_CLAIM_RE = re.compile(r"`([A-Za-z0-9<>'’ ._-]*_[A-Za-z0-9<>'’ ._-]*)`")
_HAS_CHAPTER_SEG = re.compile(r"_(?:\d{2}|NN|<NN>)_")
_HAS_TAIL_SEG = re.compile(r"_(?:src|<?\d>?)(?:_|\b)")

#: A sentence relates the tail to the chapter segment when it names both.
#: The unit is the sentence, not a `tail…chapter` span: a lazy span matches
#: "chapter carries a disambiguator, the tail" and stops one word short of the
#: "sits before" that is the whole claim -- and finditer then resumes past it,
#: so the wrong statement is never classified at all.
NAMING_TAIL_MENTION = re.compile(r"\btails?\b", re.I)
NAMING_CHAPTER_MENTION = re.compile(r"\bchapters?\b", re.I)
NAMING_TAIL_LAST_CUE = re.compile(
    r"after the chapter|at the (?:very )?end|comes? last|goes? last|sits? last|"
    r"last, after|end, after", re.I)
NAMING_TAIL_FIRST_CUE = re.compile(
    r"before the chapter|precedes? the chapter|ahead of the chapter|"
    r"sits? before|comes? before|goes? before|first, before", re.I)

#: Prose marking a stated form as the WRONG one.  §1a states the ordering by
#: negation ("`…_02_SupLearn_src`, never `…_src_02_SupLearn`") and names the
#: legacy mis-spelling on purpose, so without this the file that states the
#: convention is the file that fails it -- the same guard COUNTER_EXAMPLE
#: gives §1b and FIG_STRICT_NEGATED gives §8a.
NAMING_CLAIM_NEGATED = re.compile(
    r"\b(?:never|not|no|rather than|instead of|avoid|wrong|legacy|used to|"
    r"refuses?|rejects?|re-?renames?|mis-?spell\w*|disagree\w*|don't|do not|"
    r"invalid|illegal|broken)\b", re.I)


def _concrete_stem(token):
    """Turn a stated stem into one `naming.py` can be asked about."""
    stem = token.strip()
    stem = re.sub(r"\.(?:pdf|md|epub|docx|txt|rtf|html)$", "", stem, flags=re.I)
    # `<book>`, `<book core stem>`, `<another PDF's core stem>` all stand for a
    # whole canonical book stem, not for one segment.
    stem = re.sub(r"<[^>]*>", "Author_AbbrevTitle_2026", stem)
    stem = re.sub(r"(?<=_)NN(?=_)", "01", stem)
    if stem.startswith("_"):                 # a bare `_src_NN_Chapter` fragment
        stem = "Author_AbbrevTitle_2026" + stem
    return stem if re.match(r"\A[A-Za-z0-9][A-Za-z0-9_-]*\Z", stem) else None


def _check_naming_claims(rep, check, canon):
    """Prose that states §1a's tail order agrees with `naming.py`.

    The ordering was pinned in code and nowhere else: a SKILL.md restating it
    as "`_src_NN_Chapter` -- the tail sits before the chapter segment" passed
    green, and that is the whole §1a failure re-entering through the door the
    check does not watch.  A reader follows the prose, `looks_canonical()`
    follows the module, and the rename splits in two directions again.

    Two probes, because a restatement can be a form or a sentence: every
    stated stem carrying both a chapter segment and a tail is instantiated and
    handed to the module, and every sentence relating the tail to the chapter
    segment is classified and compared with what the module actually does.
    `shared/scripts/naming.py` is out of scope by construction -- it is the
    implementation, and its self-test has to contain the wrong form.
    """
    good, bad = ("Author_AbbrevTitle_2026_02_SupLearn_src",
                 "Author_AbbrevTitle_2026_src_02_SupLearn")
    tail_last = canon.looks_canonical(good) and not canon.looks_canonical(bad)
    n_forms, n_sentences = 0, 0

    for path, text in walk_plugin_files():
        if path.endswith(".py") and not path.startswith(SKILLS_DIR + os.sep):
            continue
        for m in NAMING_STEM_CLAIM_RE.finditer(text):
            token = m.group(1)
            if not (_HAS_CHAPTER_SEG.search(token) and _HAS_TAIL_SEG.search(token)):
                continue
            stem = _concrete_stem(token)
            if stem is None:
                continue
            n_forms += 1
            if canon.looks_canonical(stem):
                continue
            # The sentence the form sits in, NOT the line: §1a is hard-wrapped
            # and its `never` lands at the end of the line above the form it
            # negates, so a line-bounded window sees an empty string and
            # reports the canonical wording as the violation.
            window = text[max(0, m.start() - 200):m.start()]
            cut = max((b.end() for b in re.finditer(r"[.!?;]\s|\n[ \t]*\n",
                                                    window)), default=0)
            if NAMING_CLAIM_NEGATED.search(window[cut:]):
                continue                     # a labelled wrong-form example
            rep.fail(check,
                     "%s states `%s` as a source filename, but naming.py "
                     "rejects %r. §1a's tail order is pinned in code and "
                     "restated here; a restatement that disagrees is the "
                     "two-homes bug in prose form -- the reader follows the "
                     "text and looks_canonical() follows the module. Mark it "
                     "as the wrong form if that is what it is."
                     % (rel(path), token, stem), at(path, m.start(), text))

        if not path.endswith(".md"):
            continue
        for off, sentence in _soft_sentences(text):
            if not (NAMING_TAIL_MENTION.search(sentence)
                    and NAMING_CHAPTER_MENTION.search(sentence)):
                continue
            says_last = bool(NAMING_TAIL_LAST_CUE.search(sentence))
            says_first = bool(NAMING_TAIL_FIRST_CUE.search(sentence))
            if says_last == says_first:
                continue                     # states no direction, or both
            n_sentences += 1
            if says_last != tail_last:
                rep.fail(check,
                         "%s states that the tail comes %s the chapter "
                         "segment, but naming.py accepts %r and rejects %r. "
                         "§1a: the tail always comes LAST. That disagreement "
                         "had two homes once and cost either every chapter's "
                         "figures or a doubled set of them."
                         % (rel(path), "before" if says_first else "after",
                            good if tail_last else bad,
                            bad if tail_last else good),
                         at(path, off, text))
    rep.saw(check, "stated source stems carrying a chapter segment and a tail",
            n_forms)
    rep.saw(check, "prose statements of the tail order", n_sentences)
    if n_forms or n_sentences:
        rep.ok(check, "%d stated stem(s) and %d prose statement(s) of the tail "
                      "order agree with shared/scripts/naming.py"
               % (n_forms, n_sentences), rel(NAMING))


def check_source_filename(rep, conv):
    """One implementation of the source-filename rule, and both skills use it.

    pdf-organizer writes these names and pdf-figure-extractor reads them to
    tell a book's chapters from the book.  The rule had two homes and they
    disagreed about where a `_src` tail sits -- in both directions at once, so
    no chapter name satisfied both consumers.  One choice re-renamed every
    chapter on the next batch run and orphaned its figures; the other wrote
    every figure twice under two stems that never collide.  Neither raises,
    and nothing downstream can report either.  CONVENTIONS.md §1a.
    """
    check = "source-filename"

    if not os.path.isfile(NAMING):
        rep.fail(check, "canonical shared/scripts/naming.py is missing")
        return
    canon = _load_module(NAMING, "_shared_naming")

    # (a) the canonical implementation passes its own suite; count floored.
    result = canon.run_self_test()
    if not result["ok"]:
        rep.fail(check, "shared/scripts/naming.py self-test %d/%d failed: %s"
                 % (result["passed"], result["total"],
                    json.dumps(result["failures"], ensure_ascii=False)),
                 rel(NAMING))
    elif result["total"] < NAMING_SELFTEST_MIN:
        rep.fail(check,
                 "shared/scripts/naming.py's self-test has shrunk to %d cases "
                 "(floor: %d). Coverage may grow; it may not be deleted."
                 % (result["total"], NAMING_SELFTEST_MIN), rel(NAMING))
    else:
        rep.ok(check, "shared/scripts/naming.py self-test %d/%d"
               % (result["passed"], result["total"]), rel(NAMING))

    # (b) CONVENTIONS.md shows the two forms, and the module agrees with what
    #     it shows.  A block that drifts from the code is worse than no block:
    #     it is the thing a reader trusts instead of reading the script.
    forms = canonical_block(conv, "source-filename")
    if not forms:
        # A HarnessError, exactly like an emptied canonical:figure-glob, and
        # for the same reason: emptying this block used to delete two checks
        # in silence -- the suite went 248 -> 246 and still said PASS.  A
        # canonical block with nothing in it is not a tree that conforms, it
        # is a harness with nothing to check against.
        raise HarnessError(
            "canonical:source-filename is empty. §1a's two forms are what this "
            "check instantiates and hands to naming.py; with none of them the "
            "form and tail-order checks silently stop running.")
    rep.saw(check, "canonical:source-filename forms", len(forms))
    for form in forms:
        # Turn the documented template into a concrete name and ask the
        # module.  `<Author>_<AbbrevTitle>_<Year>` -> `Author_AbbrevTitle_2026`.
        concrete = (form.replace("<Author>", "Author")
                        .replace("<AbbrevTitle>", "AbbrevTitle")
                        .replace("<Year>", "2026")
                        .replace("<NN>", "01")
                        .replace("<ChapterName>", "ChapterName"))
        if "<" in concrete:
            rep.fail(check, "canonical:source-filename form %r has a "
                            "placeholder this check cannot instantiate -- add "
                            "it to the substitution list" % form,
                     rel(CONVENTIONS))
        elif not canon.looks_canonical(concrete):
            rep.fail(check,
                     "CONVENTIONS.md documents the form %r, but naming.py "
                     "rejects %r. Readers follow the block; the code is what "
                     "runs." % (form, concrete), rel(CONVENTIONS))
        else:
            rep.ok(check, "canonical:source-filename %r accepted by naming.py"
                   % form, rel(CONVENTIONS))

    # (b2) the tail order, which is the fact the two copies disagreed about.
    #      Documented in §1a's prose; asserted here so prose and code cannot
    #      drift apart again.
    for good, bad in (("Author_AbbrevTitle_2026_02_SupLearn_src",
                       "Author_AbbrevTitle_2026_src_02_SupLearn"),
                      ("Author_AbbrevTitle_2026_02_SupLearn_src_2",
                       "Author_AbbrevTitle_2026_02_SupLearn_2_src")):
        if canon.looks_canonical(good) and not canon.looks_canonical(bad):
            rep.ok(check, "tail order pinned: %s canonical, %s not"
                   % (good, bad), rel(NAMING))
        else:
            rep.fail(check,
                     "the tail must come LAST (§1a): expected %r canonical and "
                     "%r not, got %r / %r"
                     % (good, bad, canon.looks_canonical(good),
                        canon.looks_canonical(bad)), rel(NAMING))

    # (b3) and the prose that restates the tail order agrees with the module.
    #      §1a's ordering was pinned in code and nowhere else, so a SKILL.md
    #      saying "`_src_NN_Chapter` -- the tail sits before the chapter
    #      segment" passed green.  That is the C++/c bug in prose form: the
    #      reader follows the text, the code follows naming.py, and the two
    #      halves of the rename disagree again.  Modelled on _check_slug_claims.
    _check_naming_claims(rep, check, canon)

    # (c) THE STRUCTURAL RULE.  No module under skills/ defines any of the
    #     reserved names, and no module under skills/ compiles §1a's shape
    #     under a name of its own.  Importing is the point; binding is the
    #     bug, whether or not this week's copy happens to agree.
    n_modules, n_patterns = 0, 0
    for _skill, path, src in walk_skill_files():
        if not path.endswith(".py"):
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError as exc:
            rep.fail(check, "%s does not parse (%s), so it cannot be checked "
                            "for a second copy of the source-filename rule"
                     % (rel(path), exc), rel(path))
            continue
        n_modules += 1
        bound = _bound_names(tree)
        for name in NAMING_RESERVED:
            if name in bound:
                rep.fail(check,
                         "%s defines `%s` itself. The source-filename rule has "
                         "one home, shared/scripts/naming.py -- import it. A "
                         "second copy owns what its own callers resolve, and "
                         "the last one cost either every chapter's figures or "
                         "a doubled set of them (§1a)." % (rel(path), name),
                         at(path, bound[name]))
        # The name-blocklist above only ever catches a spelling that already
        # burned someone.  This catches the rule by its SHAPE, so the same
        # regex reintroduced as `SRC_NAME_RE` beside a `def is_organized` --
        # which is literally what `CHAPTER_STEM_RE` was -- is caught on its
        # first appearance rather than its second.
        for pattern, lineno in _compiled_patterns(tree):
            n_patterns += 1
            shape = _restates_naming_shape(pattern)
            if shape:
                rep.fail(check,
                         "%s compiles %r, which restates §1a's source-filename "
                         "shape (%s) whatever it is called. The rule has one "
                         "home, shared/scripts/naming.py -- import "
                         "looks_canonical()/chapter_parts()/core_stem() "
                         "instead. A second copy that agrees today is still a "
                         "second home, and the last one cost either every "
                         "chapter's figures or a doubled set of them."
                         % (rel(path), pattern, shape), at(path, lineno))
    rep.saw(check, "skill modules parsed for a second copy of the rule",
            n_modules)
    rep.saw(check, "literal patterns compiled or matched under skills/",
            n_patterns)

    # (d) both named consumers actually import it, and get the surface they
    #     are documented to use.  A skill that quietly stops importing is how
    #     a shared layer becomes decorative.
    for relpath, surface in sorted(NAMING_CONSUMERS.items()):
        path = os.path.join(SKILLS_DIR, relpath)
        if not os.path.isfile(path):
            rep.fail(check, "%s is missing; CONVENTIONS.md §1a names it as a "
                            "consumer of the source-filename rule" % relpath)
            continue
        try:
            mod = _load_module(
                path, "_naming_consumer_" + re.sub(r"\W", "_", relpath),
                screen=True)
        except BaseException as exc:            # SystemExit included: a missing
            rep.fail(check,                     # third-party dep exits, not raises
                     "%s fails at import (%s: %s), so it cannot be checked for "
                     "a second copy of the source-filename rule"
                     % (relpath, type(exc).__name__, exc), rel(path))
            continue
        missing = [n for n in surface if not hasattr(mod, n)]
        if missing:
            rep.fail(check,
                     "%s does not expose %s -- CONVENTIONS.md §1a says it "
                     "imports the rule from shared/scripts/naming.py"
                     % (relpath, ", ".join(missing)), rel(path))
            continue
        # And each object must have been DEFINED in naming.py, not merely
        # agree with it today.  Identity (`is`) is the wrong test here: the
        # harness loads naming.py under its own private module name while the
        # consumer's §5 bootstrap loads it as `naming`, so the two hold
        # distinct-but-equivalent objects and every consumer would fail.
        # What actually matters is the defining file.
        wrong = []
        for name in surface:
            obj, want = getattr(mod, name), getattr(canon, name, None)
            if callable(obj) and not isinstance(obj, re.Pattern):
                try:
                    src = os.path.abspath(inspect.getsourcefile(obj) or "")
                except TypeError:
                    src = ""
                if src != os.path.abspath(NAMING):
                    wrong.append("%s (defined in %s)"
                                 % (name, rel(src) if src else "<unknown>"))
            elif isinstance(obj, re.Pattern):
                if want is None or obj.pattern != want.pattern:
                    wrong.append("%s (pattern differs from naming.py's)" % name)
            elif obj != want:
                wrong.append("%s (value differs from naming.py's)" % name)
        if wrong:
            rep.fail(check,
                     "%s does not get %s from shared/scripts/naming.py -- a "
                     "re-implementation that agrees today is still a second "
                     "home for the rule, and the last one cost either every "
                     "chapter's figures or a doubled set of them"
                     % (relpath, ", ".join(wrong)), rel(path))
        else:
            rep.ok(check, "%s imports %s from shared/scripts/naming.py"
                   % (relpath, ", ".join(surface)), rel(path))


#: A `<placeholder>` inside a shell command.  §1b rule 3 is about exactly this
#: token: "Every `<placeholder>` standing for a filename, a path or a URL in
#: these files is written inside `'…'`."
SHELL_PLACEHOLDER = re.compile(r"<[A-Za-z][A-Za-z0-9 _.\-/]*>")

#: A fence line, opening or closing, with whatever info string it carries.
#: Matched per line rather than as a `(.*?)` span because the old span regex
#: could not see an indented fence and could not tell an unterminated one from
#: a terminated one.
MD_FENCE_LINE_RE = re.compile(r"^[ \t]{0,3}(?:`{3,}|~{3,})[ \t]*([A-Za-z0-9_+.#-]*)")

#: Fence tags that DECLARE shell.  Reported as its own population: §1b
#: describes this guard as walking "every ```bash fence", so a tree with none
#: left means the guard's own anchor is gone.  Relabelling every fence in the
#: tree to ```zsh used to empty the corpus and still print `1 checked` -- the
#: check counted violations and never its population.  A ```zsh fence is not
#: silently readmitted here either: it falls through to the content sniff
#: below, so coverage does not depend on this vocabulary being complete.
SHELL_FENCE_TAGS = frozenset(("bash", "sh", "shell", "console"))

#: Fence tags with quoting rules of their own.  A ```python or ```yaml fence
#: is not what §1b rule 3 is about, and `"<slug>"` is correct Python.
NON_SHELL_FENCE_TAGS = frozenset((
    "python", "py", "python3", "yaml", "yml", "json", "jsonl", "markdown",
    "md", "html", "xml", "css", "js", "javascript", "ts", "typescript",
    "latex", "tex", "diff", "patch", "toml", "ini", "sql", "r", "csv", "tsv",
    "make", "makefile", "dockerfile", "regex"))

#: Command words that open a shell command line.  §1b rule 3 reaches any
#: *command line* in these files, not only the ones that happen to sit in a
#: tagged fence -- an untagged fence, a ```text fence, an inline `code` span
#: and a four-space block all teach the model the same template.  So outside a
#: declared shell fence the corpus is found by content, and this vocabulary is
#: what "content" means.  Deliberately excludes `for`, `while`, `if`, `test`
#: and `open`: those are Python keywords and builtins, and the corpus now
#: includes .py docstrings and comments.
SHELL_COMMANDS = (
    "awk", "basename", "bash", "cat", "cd", "chmod", "convert", "cp", "curl",
    "cut", "diff", "dirname", "du", "egrep", "export", "ffmpeg", "fgrep",
    "file", "find", "git", "grep", "head", "jq", "ln", "ls", "magick",
    "mkdir", "mv", "node", "npx", "ocrmypdf", "pdfimages", "pdftotext", "pip",
    "pip3", "printf", "python", "python3", "qpdf", "readlink", "realpath",
    "rg", "rm", "rmdir", "rsync", "sed", "sh", "sort", "stat", "tail", "tee",
    "touch", "tr", "uniq", "wc", "wget", "which", "xargs", "zsh")
_CMD_ALT = "(?:%s)" % "|".join(sorted(SHELL_COMMANDS, key=len, reverse=True))
#: A command at the start of the fragment (after an optional `$ ` prompt,
#: `sudo`, and any leading `VAR=value` assignments) ...
SHELL_LINE_START = re.compile(
    r"^[ \t>]*(?:[-*+]|\d+[.)])?[ \t]*(?:\$ +)?(?:sudo +)?"
    r"(?:[A-Za-z_][A-Za-z_0-9]*=\S*[ \t]+)*" + _CMD_ALT + r"\b")
#: ... or after a pipe, a `&&`, a `;`, a `$(` or a backtick.  `grep x | awk
#: '…' <file>` is one command line and the placeholder is on the second half.
SHELL_LINE_PIPED = re.compile(r"(?:\||&&|;|\$\(|`|\bxargs +)[ \t]*" + _CMD_ALT + r"\b")


#: A command *fragment* quoted on its own -- `--old-slug <X> --new-slug <Y>`,
#: `--src <vault>/Sources` -- with no command name in front of it.  These teach
#: the same template as a full line and were invisible to the two patterns
#: above, which both anchor on a recognised command name.  Requiring a flag AND
#: a value keeps ordinary prose out: a sentence does not start with `--`.
FLAG_FRAGMENT = re.compile(r"\A\s*--[A-Za-z][A-Za-z0-9-]*[= ]\S")


#: A command line recognised by its SHAPE rather than by its command name: a
#: bare lowercase word followed by a flag, a quoted argument, a `<placeholder>`
#: or a path-ish token.  `SHELL_COMMANDS` is a 60-word vocabulary, and a
#: vocabulary is a list of the commands someone thought of: `pandoc --from html
#: --to markdown <path/to/page.html>` in an untagged fence and `pdfseparate
#: <input.pdf> out-%d.pdf` inline both sailed past it, while the same `pandoc`
#: line inside a ```bash fence failed.  The only difference between those two
#: is a word this file happens not to know.
#: The argument shapes are deliberately narrow.  A bare `word <placeholder>`
#: would match English -- `missing <key>: key` is a scanner's finding message,
#: not a command -- so the placeholder arm requires the placeholder to look
#: like a file or a path (`<input.pdf>`, `<path/to/page.html>`), which is also
#: the only kind §1b rule 3 is about.
#: One optional bare SUBCOMMAND word may sit between the command and its first
#: argument shape: `fetch_images.py rename --attachments '<vault>/…'` and
#: `organize.py split '<pdf>'` are the plugin's own template shapes, and a
#: pattern requiring the flag/quoted/path token immediately after the command
#: word read right past them -- §1b's "every command line" claim was false for
#: exactly the templates that take attacker-adjacent paths.
GENERIC_COMMAND = re.compile(
    r"^[ \t>]*(?:[-*+]|\d+[.)])?[ \t]*(?:\$ +)?(?:sudo +)?"
    r"(?:[A-Za-z_][A-Za-z_0-9]*=\S*[ \t]+)*"
    r"[a-z][a-z0-9._+-]*(?:[ \t]+[a-z][a-z0-9-]{1,15}(?=[ \t]))?"
    r"(?:[ \t]+--?[A-Za-z][\w-]*|[ \t]+'[^']*'"
    r"|[ \t]+<[a-z][^>\n]*[./][^>\n]*>|[ \t]+[^ \t\n]*/[^ \t\n]*)")


def _looks_like_shell(fragment):
    """True when `fragment` reads as a shell command line.

    A sniff, not a parser: it only decides whether §1b rule 3 looks at the
    fragment at all, and every fragment it looks at must still contain a
    `<placeholder>` before anything is reported.  Being wrong here costs a
    missed template or a noisy one, never a wrong verdict about quoting.
    """
    return bool(SHELL_LINE_START.search(fragment)
                or SHELL_LINE_PIPED.search(fragment)
                or FLAG_FRAGMENT.match(fragment))


def _looks_like_command(fragment):
    """The same question, asked where the text is already claimed to be code.

    A fence, an indented block and a backticked span are all a claim that what
    is inside is typed rather than read, so *shape* is enough there and the
    command vocabulary is not needed.  In prose -- a .py docstring's paragraph,
    a comment -- it still is: "writing Wiki/<tgt>.md opens the existing
    case-variant file" is an English sentence with a path in it, and the shape
    test alone reads it as a command line.
    """
    return _looks_like_shell(fragment) or bool(GENERIC_COMMAND.match(fragment))


def _fence_holds_commands(lines):
    """Is this fence a block of command lines, whatever its tag says?

    Decided once for the whole fence and then applied to every line in it.
    Per-line sniffing is what let a wrapped or continued command line
    (`  --slug '<x>' \\`) sit unread next to one that was read, and deciding
    per fence is also how an unknown command word stops mattering: one
    recognisable line makes the block a command block.
    """
    return any(_looks_like_command(ln) for ln in lines)


#: A backticked span, including the ``double`` form RST-style docstrings use.
#: An inline span is where most of this plugin's command templates actually
#: live -- `grep -rl <vault>/Wiki` in a sentence teaches exactly what the same
#: line in a fence teaches, and the fence-only scan never saw one.
INLINE_CODE_RE = re.compile(r"(?<!`)(`+)(?!`)([^\n]+?)(?<!`)\1(?!`)")
INLINE_KIND = "an inline `code` span"

#: A markdown list marker -- the reason an indented line is usually NOT a code
#: block.  Every deep-indent line in body-cleaning.md is a nested list item,
#: and treating those as code would scan prose as if it were a command line.
LIST_MARKER_RE = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]")
#: A four-space (or tab) indented code block line.
INDENTED_CODE_RE = re.compile(r"^(?: {4}|\t)[ \t]*\S")

#: Placeholders that do not stand for a filename, path or URL, so §1b rule 3
#: does not reach them.  Kept deliberately tiny: every addition is a hole.
QUOTING_EXEMPT = {"<N>", "<number>", "<count>", "<n>"}

#: HTML element names that could not be standing in for a path.  These skills
#: grep fetched pages for markup and build HTML in heredocs, so `<script>` and
#: `<table>` appear inside shell fences as literal tags -- quoting those would
#: be nonsense.  Names that are ALSO plausible placeholders are NOT here; see
#: :data:`HTML_ELEMENTS_AMBIGUOUS`.
HTML_ELEMENTS_UNAMBIGUOUS = frozenset((
    "body", "br", "canvas", "div", "figcaption", "h1", "h2", "h3", "h4", "h5",
    "h6", "head", "hr", "html", "iframe", "img", "li", "noscript", "ol", "p",
    "picture", "script", "span", "sub", "sup", "svg", "table", "tbody", "td",
    "textarea", "tfoot", "th", "thead", "tr", "ul", "video"))

#: Element names that are also the likeliest REAL placeholders in this plugin,
#: so a bare name list exempts the very tokens the rule is for: `source:` is a
#: §2b frontmatter field and the thing every clipping fetch is keyed to, and
#: §1b names a clipping's *title* as attacker-controlled ("A clipping's title,
#: author and image URLs come from a page fetched off the open web").  A real
#: `grep -oiE '(…)' <source>` hid behind this list.  These are exempt only in
#: markup context -- see :func:`_markup_context`.
HTML_ELEMENTS_AMBIGUOUS = frozenset((
    "a", "article", "aside", "base", "caption", "cite", "code", "col", "data",
    "details", "dialog", "figure", "footer", "form", "header", "input",
    "label", "link", "main", "map", "menu", "meta", "nav", "object", "option",
    "output", "param", "section", "select", "slot", "source", "style",
    "summary", "template", "time", "title", "track"))

#: What makes a `<name>` markup rather than a placeholder: a closing tag, a
#: tag carrying an attribute, a doctype, or an unambiguous element tag beside
#: it on the same line.  `<style>html,body{…}</style>` in lottie-recovery's
#: heredoc has all three shapes; `grep -oiE '(…)' <source>` has none.
_MARKUP_CONTEXT = re.compile(
    r"</[A-Za-z][A-Za-z0-9]*\s*>"                     # </style>
    r"|<[A-Za-z][A-Za-z0-9]*\s+[A-Za-z-]+\s*="        # <img src=…
    r"|<!doctype|<!--"                                # <!doctype html>
    r"|<(?:%s)\b[^>]*>" % "|".join(sorted(HTML_ELEMENTS_UNAMBIGUOUS)),
    re.I)


def _markup_context(fragment):
    return bool(_MARKUP_CONTEXT.search(fragment))


#: A fragment ENDING in `# NO` is a deliberate counter-example -- §1b teaches
#: the rule by showing the wrong form once, labelled.  Anchored hard: the old
#: `#\s*NO\b[^\n]*$` matched the marker anywhere with anything after it, so
#: `mv <old>.pdf <new>.pdf   # NO-op when names match` exempted a whole line
#: and hid two real placeholders behind an English word.  §1b already
#: documents the marker as "a line ending in `# NO`"; this is the code
#: catching up with the prose, not a new rule.
COUNTER_EXAMPLE = re.compile(r"#[ \t]*NO[ \t]*$")

#: Where a `'` may OPEN a quoted run: start of fragment, whitespace, or a
#: shell metacharacter that ends the previous word.  Quote state is tracked
#: per line, so with a bare toggle an apostrophe in prose -- `echo don't && rm
#: <target>.pdf`, or any of the "don't"/"it's"/"user's" that fill these files
#: -- silently marked the whole rest of the line as quoted and every
#: placeholder after it as compliant.  A word-internal `'` is an apostrophe,
#: not a quote.  `\` is in the set for the `'\''` idiom §1b rule 2 teaches,
#: and `$` for `$'…'`; both are how a quote legitimately opens mid-word.
QUOTE_OPENERS = set(" \t=$(){}[],:;|&<>!\\")


def _unquoted_placeholders(fragment):
    """Placeholders in `fragment` that are NOT inside single quotes.

    Tracks quote state rather than testing adjacency, because the common
    correct form wraps a whole path — `'<vault>/Clippings/Cleaned'` — so the
    placeholder's own neighbours are `/` and `<`, not quotes.  A closing quote
    is any matching quote character; an OPENING one has to sit where a shell
    word can start (:data:`QUOTE_OPENERS`).
    """
    if COUNTER_EXAMPLE.search(fragment):
        return []                      # a labelled wrong-form example
    out, in_single, in_double, i = [], False, False, 0
    while i < len(fragment):
        ch = fragment[i]
        prev = fragment[i - 1] if i else " "
        if ch == "'" and not in_double:
            if in_single:
                in_single = False
            elif prev in QUOTE_OPENERS:
                in_single = True
        elif ch == '"' and not in_single:
            if in_double:
                in_double = False
            elif prev in QUOTE_OPENERS:
                in_double = True
        elif ch == "<" and not in_single:
            m = SHELL_PLACEHOLDER.match(fragment, i)
            if m and m.group(0) not in QUOTING_EXEMPT and not _is_html_tag(
                    m.group(0), fragment):
                # A double-quoted placeholder is rule 2's violation rather than
                # rule 3's, and it is the more dangerous of the two: `$(…)`,
                # backticks and `${…}` all still expand inside `"…"`.
                out.append((m.group(0), "double-quoted" if in_double else "bare"))
            if m:
                i = m.end()
                continue
        i += 1
    return out


def _is_html_tag(token, fragment):
    """Is `<token>` a literal HTML tag rather than a placeholder?"""
    name = token[1:-1].split()[0].lower()
    if name in HTML_ELEMENTS_UNAMBIGUOUS:
        return True
    return name in HTML_ELEMENTS_AMBIGUOUS and _markup_context(fragment)


def _md_shell_fragments(text):
    """Yield (lineno, fragment, kind) for the parts of a .md §1b rule 3 reaches.

    Four kinds, because the rule is about what a *template* teaches and all
    four teach identically.  Only the first was scanned before, and each of
    the other three was a verified false negative: an untagged or ```text
    fence, an inline `grep -rl <vault>/Wiki` span, and a four-space block.
    """
    # Fences are read whole: what a fence *is* is decided once, from all of its
    # lines, and then every line in it is scanned.  Line-by-line sniffing meant
    # a command line's own continuation could be outside the corpus, and that
    # an unknown command word (`pandoc`, `pdfseparate`) put the whole line
    # outside it -- in an untagged fence, where the reader copies it just as
    # readily as out of a ```bash one.
    fences, cur, start, tag = [], None, 0, ""
    for i, line in enumerate(text.split("\n"), 1):
        m = MD_FENCE_LINE_RE.match(line)
        if m and cur is None:
            cur, start, tag = [], i, m.group(1).lower()
        elif m:
            fences.append((start, tag, cur))
            cur = None
        elif cur is not None:
            cur.append(line)
    if cur is not None:
        fences.append((start, tag, cur))          # unterminated: read it anyway
    fenced_lines = set()
    for start, tag, lines in fences:
        fenced_lines.update(range(start, start + len(lines) + 2))
        if tag in SHELL_FENCE_TAGS:
            kind = "a shell fence"
        elif tag in NON_SHELL_FENCE_TAGS or not _fence_holds_commands(lines):
            continue
        else:
            kind = ("an untagged fence" if not tag else "a ```%s fence" % tag)
        for j, line in enumerate(lines):
            yield start + 1 + j, line, kind

    in_fence, tag = False, ""
    in_list = False
    for i, line in enumerate(text.split("\n"), 1):
        m = MD_FENCE_LINE_RE.match(line)
        if m:
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.strip():
            # A deep-indented line under a list marker is a continuation
            # paragraph, not a code block.
            if LIST_MARKER_RE.match(line):
                in_list = True
            elif not line[:1].isspace():
                in_list = False
            if (not in_list and INDENTED_CODE_RE.match(line)
                    and _looks_like_command(line)):
                yield i, line, "an indented code block"
        for span in INLINE_CODE_RE.finditer(line):
            if _looks_like_command(span.group(2)):
                yield i, span.group(2), INLINE_KIND


def _py_shell_fragments(path, text):
    """Yield (lineno, fragment, kind) for a .py file's docstrings and comments.

    §1b rule 3 is about "these files", not about markdown: rule 1 is "prefer
    the bundled script over the shell", and every one of those scripts
    documents its CLI in a docstring usage block.  The check skipped every
    non-.md file, so a `python3 fetch_images.py --attachments <vault>/…` usage
    line -- the exact template a reader copies -- was outside the corpus.
    """
    prose = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        tree = None                    # scripts-run reports it; not this check
    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef,
                                 ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc and node.body:
                    prose.append((node.body[0].lineno, doc, "a .py docstring"))
    for line_no, line in enumerate(text.split("\n"), 1):
        hash_at = line.find("#")
        if hash_at != -1 and line[:hash_at].count("'") % 2 == 0 \
                and line[:hash_at].count('"') % 2 == 0:
            prose.append((line_no, line[hash_at:], "a .py comment"))
    for start, chunk, kind in prose:
        for j, line in enumerate(chunk.split("\n")):
            if _looks_like_shell(line):
                yield start + j, line, kind
            for span in INLINE_CODE_RE.finditer(line):
                if _looks_like_command(span.group(2)):
                    yield start + j, span.group(2), kind


def check_shell_quoting(rep, conv):
    """§1b rule 3: a path/filename/URL placeholder is written inside `'…'`.

    This is the one §1b rule with no mechanical guard, and it drifted in all
    five skills -- including pdf-organizer, which §1b itself names as "the
    model for it".  The rule exists because the model copies the template it
    is shown: a documented `awk '…' <cleaned-note>.md` teaches the unquoted
    form, and the values that reach these command lines are filenames off the
    user's disk and titles and image URLs off a fetched web page.  Inside
    `"…"` the shell still expands `$(…)`, backticks and `${…}`.

    The corpus is every command line in every skill file and in CONVENTIONS.md
    -- fenced or not, tagged or not, .md or .py.  Scanning only ```bash fences
    in .md made six shapes of the same violation invisible while the summary
    line said the rule held.
    """
    check = "shell-quoting"
    violations = 0
    n_tagged, n_sniffed, n_inline, n_py = 0, 0, 0, 0

    # Every file that states plugin contract, not just skills/: §1b says "in
    # these files", the old check already held CONVENTIONS.md to its own rule,
    # and a shared/scripts/ usage block teaches a reader exactly what a skill's
    # does.  walk_plugin_files() excludes tests/, which is the checker.
    corpus = list(walk_plugin_files())

    # `n_tagged` is counted here rather than inside the fragment walker: it is
    # the population §1b's own description of this guard refers to, and it has
    # to fail on its own when the tree stops declaring its shell fences.
    for path, text in corpus:
        if not path.endswith(".md"):
            continue
        in_fence = False
        for line in text.split("\n"):
            m = MD_FENCE_LINE_RE.match(line)
            if not m:
                continue
            if in_fence:
                in_fence = False
            else:
                in_fence = True
                n_tagged += m.group(1).lower() in SHELL_FENCE_TAGS

    seen = set()
    for path, text in corpus:
        if path.endswith(".md"):
            fragments = _md_shell_fragments(text)
        elif path.endswith(".py"):
            fragments = _py_shell_fragments(path, text)
        else:
            continue
        for lineno, fragment, kind in fragments:
            n_sniffed += 1
            n_inline += kind == INLINE_KIND
            n_py += kind.startswith("a .py")
            for token, how in _unquoted_placeholders(fragment):
                # The same placeholder can arrive twice -- once as a docstring
                # line, once as the ``code`` span inside it.  One site, one
                # report.
                if (path, lineno, token) in seen:
                    continue
                seen.add((path, lineno, token))
                violations += 1
                rep.fail(check,
                         "%s: %s placeholder %s in %s. §1b rule 3: "
                         "write it inside '…' -- the model copies the template "
                         "it is shown, and these values are filenames off the "
                         "user's disk and URLs off a fetched page.%s%s"
                         % (rel(path), how, token, kind,
                            "" if how == "bare" else
                            " Double quotes do not stop $(…), backticks or ${…}.",
                            "" if path != CONVENTIONS else
                            " CONVENTIONS.md states this rule and then shows it broken."),
                         at(path, lineno))

    rep.saw(check, "```bash/sh/shell/console fences (the corpus §1b names)",
            n_tagged)
    rep.saw(check, "command lines scanned for <placeholder>s", n_sniffed)
    rep.saw(check, "inline `code` spans holding a command line", n_inline)
    rep.saw(check, "shell commands in .py docstrings and comments", n_py)
    if violations == 0:
        rep.ok(check, "every <placeholder> in a command line is single-quoted "
                      "(§1b rule 3; %d fragments across %d files)"
               % (n_sniffed, len(corpus)), rel(SKILLS_DIR))


def check_figure_naming(rep, conv):
    check = "figure-naming"
    glob_lines = canonical_block(conv, "figure-glob")
    if len(glob_lines) != 1:
        raise HarnessError("canonical:figure-glob must hold exactly one pattern")
    canonical_glob = glob_lines[0]                       # [source_stem]_fig*
    if not canonical_glob.endswith("_fig*"):
        raise HarnessError(
            "canonical:figure-glob is `%s`, which does not end in the `_fig*` "
            "token the whole of §8 is built on -- so this check cannot run, "
            "and nothing about figure naming was checked.\n"
            "  This is what a tree-wide rename of the `_fig` token looks like "
            "from here. If the rename is intended it is a change to §8a, §8b, "
            "§8c and every skill at once: make it in one commit and update "
            "FIG_TAIL, FIG_NAME_RE and FIG_NEAR_MISS_RE in "
            "tests/test_conventions.py with it.\n"
            "  If instead CONVENTIONS.md was edited to match a tree that had "
            "already drifted, the edit is the defect: restore this block and "
            "the figure-naming check will name the files."
            % canonical_glob)

    clipping_exts = set(canonical_csv_block(
        conv, "clipping-image-extensions"))
    if not clipping_exts:
        raise HarnessError(
            "canonical:clipping-image-extensions is empty, so producer and "
            "consumer format support cannot be compared")
    try:
        fetch = _load_module(FETCH_IMAGES, "_fetch_image_extensions", screen=True)
        scanner = _load_module(SCAN_VAULT, "_scan_image_extensions", screen=True)
    except Exception as exc:
        rep.fail(check, "could not load the image producer/consumer to compare "
                 "CONVENTIONS.md §8a's extension set: %s" % exc)
    else:
        produced = set(getattr(fetch, "OUTPUT_EXTENSIONS", ()))
        if produced != clipping_exts:
            rep.fail(check, "fetch_images.py OUTPUT_EXTENSIONS is %s, but "
                     "CONVENTIONS.md §8a publishes %s"
                     % (sorted(produced), sorted(clipping_exts)))
        else:
            rep.ok(check, "clipping-processor's %d output extensions match "
                   "CONVENTIONS.md §8a" % len(clipping_exts))
        missed = [ext for ext in sorted(clipping_exts)
                  if not scanner.EMB.fullmatch("![[X_fig_1.%s]]" % ext)
                  or not scanner.IMG_EMBED.search("![[X_fig_1.%s]]" % ext)]
        if missed:
            rep.fail(check, "wiki-linter does not recognize clipping-processor "
                     "output extension(s) as local image embeds: %s"
                     % ", ".join(missed))
        else:
            rep.ok(check, "wiki-linter recognizes all %d clipping-processor "
                   "output extensions" % len(clipping_exts))

    producers = _parse_producer_table(conv)
    if not producers:
        rows = _producer_table_rows(conv)
        raise HarnessError(
            "no row of CONVENTIONS.md §8b's producer table states a "
            "`_fig`-shaped pattern, so this check has no separator to hold the "
            "tree to and did not run.\n"
            "  The table parsed to %d row(s): %s\n"
            "  If the `_fig` token was renamed across the tree, see the note "
            "under canonical:figure-glob above -- that is a §8-wide change, not "
            "a table edit. If the table itself was reformatted, the row shape "
            "this reads is `| `<skill>` | `<pattern>` |`."
            % (len(rows), "; ".join("%s -> `%s`" % r for r in rows) or "none"))

    # (a0) the two halves of §8 agree about what a figure name STARTS with.
    #      The stem half of `canonical:figure-glob` bound nothing: the block was
    #      read only for an `endswith("_fig*")` guard and for message text, so
    #      changing `[source_stem]_fig*` to `[wiki_entry_slug]_fig*` -- §4a's
    #      naming rule, the one a figure filed under it is invisible to --
    #      passed with an unchanged count.
    section = _section_text(conv, "8")
    stem_m = FIG_GLOB_STEM_RE.match(canonical_glob)
    if not stem_m:
        rep.fail(check,
                 "canonical:figure-glob is `%s`, which does not start with a "
                 "`[placeholder]` for the stem. §8 opens by saying every figure "
                 "filename begins with the source stem; the block is where that "
                 "is stated mechanically." % canonical_glob, rel(CONVENTIONS))
    else:
        glob_stem = stem_m.group(1)
        spelled = glob_stem.replace("_", " ")
        if not glob_stem.endswith("stem"):
            rep.fail(check,
                     "canonical:figure-glob globs `[%s]_fig*`, but §8 keys every "
                     "figure to the source *stem*. `%s` is a different naming "
                     "rule (§4a's entry slug is the one that bites: a figure "
                     "filed under a slug is invisible to wiki-builder's glob, "
                     "and the unused-figure diagnostic walks the same pattern)."
                     % (glob_stem, glob_stem), rel(CONVENTIONS))
        elif spelled not in section:
            rep.fail(check,
                     "canonical:figure-glob globs `[%s]_fig*`, but §8's prose "
                     "never uses the words \"%s\" -- the block and the section "
                     "it belongs to are naming different things."
                     % (glob_stem, spelled), rel(CONVENTIONS))
        else:
            rep.ok(check, "canonical:figure-glob globs `[%s]_fig*`, and §8 "
                          "states that same stem in prose" % glob_stem,
                   rel(CONVENTIONS))
        for skill, (pattern, _sep) in sorted(producers.items()):
            pm = FIG_GLOB_STEM_RE.match(pattern)
            if not pm:
                rep.fail(check,
                         "§8b's `%s` row writes `%s`, which does not begin with "
                         "a `[placeholder]` for the stem -- so §8a's "
                         "`[%s]_fig*` and this producer no longer agree about "
                         "what a figure name starts with, and nothing else "
                         "compares them." % (skill, pattern, glob_stem),
                         rel(CONVENTIONS))
            elif not pm.group(1).endswith("stem"):
                rep.fail(check,
                         "§8b's `%s` row writes `[%s]_fig…` while §8a globs "
                         "`[%s]_fig*`. A producer keyed to anything but the "
                         "source stem writes files the consumer glob cannot "
                         "find: total, silent loss."
                         % (skill, pm.group(1), glob_stem), rel(CONVENTIONS))
            else:
                rep.ok(check, "§8b's `%s` row keys its figures to `[%s]`, the "
                              "same kind of stem §8a globs for"
                       % (skill, pm.group(1)), rel(CONVENTIONS))
    declared_seps = {p[1] for p in producers.values()}
    if len(declared_seps) != 1:
        raise HarnessError("CONVENTIONS.md §8b declares more than one figure "
                           "separator (%r); §8a's loose glob is then the only "
                           "thing holding consumers together and this check "
                           "needs rewriting" % sorted(declared_seps))
    canonical_sep = declared_seps.pop()

    pending = Registry(rep, check, conv, "pending-figure-text",
                       "stale figure-naming text")

    # (a) nobody may state the over-strict consumer glob -- except a producer
    #     globbing its OWN output, where `_fig_*` is exactly right.
    for skill, path, text in walk_skill_files():
        if skill in producers:
            continue
        for m in FIG_BAD_GLOB_RE.finditer(text):
            rep.fail(check,
                     "%s globs figures as `_fig_*`, but %s is a consumer, not a "
                     "producer. Vaults predating the naming convergence hold "
                     "`_fig<N>` files too, so the strict form silently matches "
                     "nothing for those -- entries end up with no images and "
                     "the unused-figure diagnostic stays silent, because it "
                     "walks the same wrong pattern. The canonical glob is `%s` "
                     "(CONVENTIONS.md §8a)."
                     % (rel(path), skill, canonical_glob), at(path, m.start(), text))

    # (a2) the same failure written without the literal `_fig_*`: pinning an
    #      extension, or telling the reader to match the strict prefix.
    for skill, path, text in walk_skill_files():
        if skill in producers:
            continue
        for m in FIG_EXT_PINNED_RE.finditer(text):
            rep.fail(check,
                     "%s pins an extension onto the consumer glob (`%s`). "
                     "CONVENTIONS.md §8a: match `%s` and accept ANY extension "
                     "-- PDFs give .png, and clipping-processor can emit "
                     ".png/.jpg/.gif/.webp/.svg/.avif/.bmp/.tiff/.ico, "
                     "and a pinned extension drops every one of the others "
                     "silently."
                     % (rel(path), text[m.start():m.end()], canonical_glob),
                     at(path, m.start(), text))
        for m in FIG_STRICT_TOKEN_RE.finditer(text):
            pre = text[max(0, m.start() - 90):m.start()]
            if FIG_STRICT_NEGATED.search(pre) or not FIG_STRICT_CUE.search(pre):
                continue
            rep.fail(check,
                     "%s tells a consumer to match the strict `_fig%s` prefix "
                     "in prose (\"%s\"). That is the over-strict glob of §8a "
                     "with none of its literal characters: vaults predating "
                     "the naming convergence hold `_fig<N>` files, and those "
                     "become invisible -- including to the unused-figure "
                     "diagnostic, which walks the same pattern."
                     % (rel(path), canonical_sep,
                        " ".join(text[max(0, m.start() - 60):m.end()].split())),
                     at(path, m.start(), text))

    # (b) the canonical consumer glob must actually be stated somewhere --
    #     counted with FIG_GLOB_RE, which requires the STEM PLACEHOLDER in
    #     front of the star.  The bare-substring test this replaces counted
    #     any `_fig*`, so a statement that lost its stem key (the half that
    #     tells a consumer WHICH files) still counted as a statement.
    consumer_ok = 0
    for skill, path, text in walk_skill_files():
        stated = [m for m in FIG_GLOB_RE.finditer(text) if m.group(2) == "*"]
        if stated:
            consumer_ok += 1
            rep.ok(check, "%s states the canonical consumer glob `%s`"
                   % (rel(path), canonical_glob),
                   at(path, stated[0].start(), text))
    rep.saw(check, "statements of the canonical consumer glob", consumer_ok)
    if not consumer_ok:
        rep.fail(check, "no skill states the canonical consumer glob `%s` -- "
                        "CONVENTIONS.md §8a is unenforced" % canonical_glob)

    # (c0) a token that is almost `_fig`.  (c) below can only judge a name it
    #      already recognises, so a file that renames the token drops out of
    #      the population instead of failing -- and takes its checks with it.
    n_near_files = 0
    for skill, path, text in walk_skill_files():
        n_near_files += 1
        for m in FIG_NEAR_MISS_RE.finditer(text):
            snippet = m.group(0)
            r = rel(path)
            excuse = _fig_name_excused(text, m.start())
            if excuse:
                rep.ok(check, "%s writes `%s`, a name §8b does not produce, "
                              "while saying so (\"%s\")" % (r, snippet, excuse),
                       at(path, m.start(), text))
                continue
            msg = ("%s names a figure file `%s`, which is not the `_fig%s<N>` "
                   "token CONVENTIONS.md §8b declares for every producer -- and "
                   "not the loose `_fig` prefix §8a's consumers glob for "
                   "either. A second spelling is a second set of files: they "
                   "never collide, never deduplicate, and every consumer sees "
                   "half of them. This is also how the check goes quiet: a "
                   "renamed token is invisible to the separator test below, so "
                   "the drift costs checks rather than failing one."
                   % (r, snippet, canonical_sep))
            where = at(path, m.start(), text)
            if pending.claims(r):
                pending.hit(r, msg, where)
            else:
                rep.fail(check, msg, where)
    # The corpus, not the hit count: a healthy tree has zero near-miss tokens,
    # and demanding a non-empty hit list would make the check require its own
    # violation.
    rep.saw(check, "files scanned for a near-miss figure token", n_near_files)

    # (c) every stated figure filename uses the one declared separator.
    n_names = 0
    for skill, path, text in walk_skill_files():
        for m in FIG_NAME_RE.finditer(text):
            if m.group(2) == "*":
                continue                           # that's a consumer glob
            n_names += 1
            sep = m.group(1)
            where = at(path, m.start(), text)
            snippet = text[m.start():m.end()]
            if sep == canonical_sep:
                rep.ok(check, "%s states `%s`" % (rel(path), snippet), where)
            elif _fig_name_excused(text, m.start()):
                # §8c: the pre-convergence names are still on disk, so a file
                # is allowed to write one down while saying that is what it is.
                rep.ok(check, "%s writes `%s` while saying it is not the "
                              "current spelling (\"%s\")"
                       % (rel(path), snippet,
                          _fig_name_excused(text, m.start())), where)
            elif pending.claims(rel(path)):
                pending.hit(rel(path),
                            "%s still spells a figure filename `%s`; every "
                            "producer in CONVENTIONS.md §8b now writes `_fig%s<N>`"
                            % (rel(path), snippet, canonical_sep), where)
            else:
                rep.fail(check,
                         "%s spells a figure filename `%s`, but CONVENTIONS.md "
                         "§8b declares one separator for every producer: "
                         "`_fig%s<N>`. Two spellings of the same figure are two "
                         "files that never collide and never deduplicate, and "
                         "half of them are flagged unused forever."
                         % (rel(path), snippet, canonical_sep), where)
    rep.saw(check, "stated figure filenames", n_names)
    if n_names < FIG_NAME_MIN:
        rep.fail(check,
                 "only %d figure filenames are stated across skills/; the floor "
                 "is %d. The vacuity guard only fires at zero, so a rename that "
                 "took two files' worth of examples out of the corpus left this "
                 "check reporting a clean sweep of what was left. Coverage may "
                 "grow; a drop means the examples moved, were deleted, or are "
                 "spelt in a way this check no longer recognises."
                 % (n_names, FIG_NAME_MIN))

    # (c1) §8b + §4c: the stem of a figure filename is the SOURCE stem -- the
    #      PDF's on-disk stem or the cleaned note's, which §4c makes
    #      Title_Case_Underscored.  A kebab-lowercase stem is a *wiki-entry*
    #      slug (§4a), the other naming rule entirely, and a figure filed
    #      under it is invisible to wiki-builder's glob: total, silent loss.
    n_stems = 0
    for skill, path, text in walk_skill_files():
        for m in FIG_CONCRETE_STEM_RE.finditer(text):
            stem = m.group(1)
            n_stems += 1
            if "-" in stem and stem == stem.lower():
                rep.fail(check,
                         "%s names a figure `%s`, whose stem `%s` is a "
                         "kebab-lowercase wiki-entry slug (§4a), not a source "
                         "stem. §8b keys every figure to the SOURCE stem and "
                         "§4c makes that Title_Case_Underscored -- "
                         "wiki-builder globs the source stem, so a figure "
                         "filed under a slug is invisible to it, and the "
                         "unused-figure diagnostic walks the same pattern."
                         % (rel(path), text[m.start():m.end()], stem),
                         at(path, m.start(), text))
    rep.saw(check, "concrete figure filenames with a literal stem", n_stems)

    # (c2) §8b: authored wiki/summary image captions sit immediately below.
    #      Clippings preserve source captions only; a missing caption is valid
    #      and prose alone cannot distinguish the next paragraph from one.
    #      PDF embeds are exempt (§6's legacy PDF-path notes).
    n_embeds = 0
    for skill, path, text in walk_skill_files():
        if not path.endswith(".md") or skill == "clipping-processor":
            continue
        lines = text.splitlines()
        for m in FIG_EMBED_RE.finditer(text):
            if m.group(1).lower().endswith(".pdf"):
                continue
            n_embeds += 1
            i = text.count("\n", 0, m.start())
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if not (nxt.strip().startswith("*") and nxt.strip().endswith("*")):
                rep.fail(check,
                         "%s embeds `%s` with no italic caption on the line "
                         "immediately below (found %r). CONVENTIONS.md §8b: "
                         "wiki/summary embeds carry a caption there, italic, with no "
                         "blank line between."
                         % (rel(path), m.group(1), nxt.strip()[:40]),
                         at(path, m.start(), text))
    rep.saw(check, "figure embeds in examples", n_embeds)
    if n_embeds:
        rep.ok(check, "%d figure embed(s) carry an italic caption on the next "
                      "line (§8b)" % n_embeds)

    # (d) a registered file that also *describes* the old split in prose.
    stale_prose = re.compile(
        r"no underscore before the number|_fig<numbers>|_fig[0-9]+_[0-9]")
    for skill, path, text in walk_skill_files():
        for m in stale_prose.finditer(text):
            r = rel(path)
            msg = ("%s describes the old `_fig<numbers>` naming as current; "
                   "every producer now writes `_fig%s<N>` (CONVENTIONS.md §8b)"
                   % (r, canonical_sep))
            where = at(path, m.start(), text)
            if pending.claims(r):
                pending.hit(r, msg, where)
            else:
                rep.fail(check, msg, where)

    pending.finish()


PRODUCER_ROW_RE = re.compile(r"^\|\s*`([a-z-]+)`\s*\|\s*`([^`|]+)`\s*\|", re.M)


def _producer_table_rows(conv):
    """Every ``(skill, pattern)`` row of the §8b table, `_fig`-shaped or not."""
    return [(m.group(1), m.group(2)) for m in PRODUCER_ROW_RE.finditer(conv)]


def _parse_producer_table(conv):
    """{skill: (pattern, separator)} from the §8b markdown table."""
    out = {}
    for skill, pattern in _producer_table_rows(conv):
        fm = re.search(r"_fig(_?)[<\[]", pattern)
        if fm:
            out[skill] = (pattern, fm.group(1))
    return out


def _section_text(conv, number):
    """The body of ``## <number>.`` … up to the next top-level section."""
    m = re.search(r"^##[ \t]+%s\.[^\n]*$" % re.escape(number), conv, re.M)
    if not m:
        return ""
    nxt = re.compile(r"^##[ \t]+\d", re.M).search(conv, m.end())
    return conv[m.start():nxt.start() if nxt else len(conv)]


# ===========================================================================
# check 4 -- frontmatter field lists and order
# ===========================================================================

SCHEMA_BLOCKS = {
    "wiki-entry": "frontmatter:wiki-entry",
    "source-note": "frontmatter:cleaned-note",
    "retired-topics": "frontmatter:retired-topics",
}

#: Schemas CONVENTIONS.md documents only in order to retire them.  A statement
#: matching one of these is a leftover, not a convention: PENDING when the file
#: is registered, FAIL otherwise.
RETIRED_SCHEMAS = {"retired-topics"}

#: The key list of a note actually written under the retired `topics:` schema.
#: A *fixture*, deliberately, and the one place in this file where a canonical
#: block is pinned rather than merely read: nothing in the tree states this
#: schema (that is what "retired" means), so `canonical:frontmatter:retired-
#: topics` had no consumer and bound nothing -- renaming a field inside it, or
#: renaming all eight of the others, left the suite green with an identical
#: count.  §2c's whole job is that the harness can RECOGNISE this shape if it
#: reappears in a skill and report it as retired rather than as unknown, and
#: that is only testable against a note in the shape.  It is a historical
#: record, so it does not drift: if this fixture and §2c ever disagree, one of
#: them is wrong about what the old notes looked like.
RETIRED_TOPICS_FIXTURE = ("title", "type", "source", "url", "author",
                          "published", "created", "description", "topics")

#: Keys tolerated inside a wiki-entry schema statement even though they are not
#: in the canonical order: `importance` is retired-but-preserved and must sit in
#: its historical slot between `tags` and `parents` (CONVENTIONS.md §2a).
LEGACY_SLOT = {"wiki-entry": ("importance", "tags", "parents")}

FENCE_RE = re.compile(r"```[a-z]*\n(.*?)```", re.S)
YAML_KEY_RE = re.compile(r"^([a-z_][a-z_0-9]*):", re.M)

#: A key its own §2 subsection marks as omittable: "**`aliases` is the only
#: omittable key**", "`url` is the schema's **one optional key**".  Read out of
#: CONVENTIONS.md rather than hardcoded, for the reason every other canonical
#: value here is: two copies of "which key may be left out" drift, and the copy
#: in the test is the one nobody reads.  Scoped to the subsection that states
#: the schema, so §2b's sentence about `url` cannot excuse a missing `url` in a
#: wiki-entry statement.
SCHEMA_OPTIONAL_RE = re.compile(
    r"`([a-z_][a-z_0-9]*)`[^\n`]{0,60}?\b(?:optional|omittable)\b")
#: Any markdown heading -- the subsection boundary the rule above is scoped to.
HEADING_RE = re.compile(r"^#{1,6}[ \t]", re.M)


def _schema_optional_keys(conv, schemas):
    """{schema: {keys CONVENTIONS.md's own section calls optional}}.

    Everything else in the canonical order is *mandatory*, and that is what
    :func:`_check_sequence` demands a restatement contain.  Without this,
    deleting a field from a stated schema was invisible: the order test is a
    subsequence test, and every proper subset of the canonical order is a
    subsequence of it.
    """
    out = {}
    for name, block in SCHEMA_BLOCKS.items():
        m = re.search(BLOCK_RE_TMPL % re.escape(block), conv, re.S)
        if not m:
            raise HarnessError("canonical:%s block not found" % block)
        heads = [h.start() for h in HEADING_RE.finditer(conv)]
        lo = max([h for h in heads if h < m.start()] or [0])
        hi = min([h for h in heads if h > m.start()] or [len(conv)])
        keys = {k for k in SCHEMA_OPTIONAL_RE.findall(conv[lo:hi])
                if k in schemas[name]}
        if len(keys) > 2:
            raise HarnessError(
                "CONVENTIONS.md's %s section marks %d of its own keys optional "
                "(%s). Each one is a key a skill may silently stop stating; "
                "if that is really intended, this guard needs rewriting rather "
                "than widening." % (name, len(keys), ", ".join(sorted(keys))))
        out[name] = keys
    return out


def _list_slice_of(text, off, keys, members):
    """The foreign token this run of ``keys`` is butted up against, or ``""``.

    ``maximal_runs`` returns a *maximal run of members*, so a longer list that
    merely contains the schema's field names -- `vault_index.py`'s per-entry
    index record, `slug, path, relpath, title, type, …, parents, is_stub, …` --
    arrives here looking exactly like a nine-field schema statement with `read`
    dropped.  It is not one, and demanding completeness of it reports the wrong
    file.  The test is the one :func:`enum_statements` already uses for the
    other direction: a neighbouring token belongs to the same list when it is
    decorated the way the members are (same backtick/quote wrapper, or bare
    with a comma between).
    """
    toks = [(m.group(0), m.start(), m.end()) for m in TOKEN_RE.finditer(text)]
    start = next((i for i, t in enumerate(toks) if t[1] == off), None)
    if start is None:
        return ""
    end, seen = start, 0
    while end < len(toks) and seen < len(keys):
        if toks[end][0] in members:
            seen += 1
        end += 1
    wraps = [_wrap_of(text, a, b) for t, a, b in toks[start:end] if t in members]
    dom = wraps[0] if wraps else ""
    for k, other in ((start - 1, start), (end, end - 1)):
        if not (0 <= k < len(toks)):
            continue
        a, b = (toks[k][2], toks[other][1]) if k < other \
            else (toks[other][2], toks[k][1])
        gap = text[a:b]
        if toks[k][0] in members or not _is_list_gap(gap):
            continue
        if _wrap_of(text, toks[k][1], toks[k][2]) != dom:
            continue
        if dom == "" and not re.search(r"[,·|]", gap):
            continue
        return toks[k][0]
    return ""


def _canonical_schemas(conv):
    out = {}
    for name, block in SCHEMA_BLOCKS.items():
        out[name] = canonical_csv_block(conv, block)
        if len(out[name]) < 5:
            raise HarnessError("canonical:%s parsed to %r" % (block, out[name]))
    return out


def _classify(keys, schemas):
    """Best-matching schema for a key list, or None."""
    best, best_overlap = None, 0
    for name, fields in schemas.items():
        ov = len(set(keys) & set(fields))
        if ov > best_overlap:
            best, best_overlap = name, ov
    if best is None or best_overlap < 4:
        return None
    if best_overlap / max(1, len(set(keys))) < 0.6:
        return None
    return best


def _check_sequence(rep, check, keys, schema_name, schemas, where, what,
                    optional=None, order_only=""):
    """Assert ``keys`` is the schema: same order, and nothing left out.

    Two assertions, and the second is the one that was missing.  The order test
    is a *subsequence* test, which every proper subset of the canonical order
    passes -- so deleting `read` from a stated field order left the check
    reporting the mutilated list as "matches the canonical order", with the
    same number of checks as before.  A restatement must therefore also be
    complete: every key CONVENTIONS.md's own section does not call optional has
    to be in it, and any that are missing are named.
    """
    canon = list(schemas[schema_name])
    legacy = LEGACY_SLOT.get(schema_name)
    if legacy and legacy[0] in keys:
        anchor = canon.index(legacy[2])
        canon = canon[:anchor] + [legacy[0]] + canon[anchor:]

    unknown = [k for k in keys if k not in canon]
    if unknown:
        rep.fail(check, "%s lists frontmatter key(s) %s that are not in the "
                        "canonical %s schema (%s)"
                 % (what, ", ".join(repr(k) for k in unknown), schema_name,
                    ", ".join(canon)), where)
        return

    it = iter(canon)
    if not all(k in it for k in keys):
        rep.fail(check,
                 "%s states the %s schema out of order: %s\n"
                 "         canonical order is: %s"
                 % (what, schema_name, ", ".join(keys), ", ".join(canon)), where)
        return

    opt = set(optional or ())
    missing = [k for k in schemas[schema_name] if k not in keys and k not in opt]
    if missing and order_only:
        rep.ok(check, "%s lists %d schema key(s) in canonical order; %s, so it "
                      "is read for order only"
               % (what, len(keys), order_only), where)
    elif missing:
        rep.fail(check,
                 "%s states the %s schema but leaves out %s. Every key in "
                 "CONVENTIONS.md §2's order is mandatory except %s; a "
                 "restatement missing one teaches the omission, and the order "
                 "test alone cannot see it -- a shortened list is still a "
                 "subsequence.\n         stated:    %s\n         canonical: %s"
                 % (what, schema_name, ", ".join("`%s`" % k for k in missing),
                    ", ".join("`%s`" % k for k in sorted(opt)) or "none",
                    ", ".join(keys), ", ".join(canon)), where)
    else:
        rep.ok(check, "%s matches the canonical %s order, in full"
               % (what, schema_name), where)


def _check_retired_schema(rep, check, schemas):
    """§2c is still the shape it says it is, and still distinguishable.

    Two assertions against :data:`RETIRED_TOPICS_FIXTURE`, because the block
    has no other consumer:

    * the block *is* that shape -- otherwise §2c is a record of something that
      never existed, and the recognition it promises is recognition of the
      wrong thing;
    * a note in that shape classifies as `retired-topics` and not as the live
      source-note schema it shares seven keys with -- which is the behaviour
      §2c exists for, and which `_classify`'s thresholds could break without
      anything else in this file noticing.
    """
    got = list(schemas["retired-topics"])
    want = list(RETIRED_TOPICS_FIXTURE)
    if got != want:
        rep.fail(check,
                 "CONVENTIONS.md §2c's retired `topics:` schema is now %s, but "
                 "the notes it describes were written %s. §2c is a historical "
                 "record kept so this harness can RECOGNISE the old shape if it "
                 "reappears in a skill; edited to a shape no note ever had, it "
                 "recognises nothing and reports the reappearance as an unknown "
                 "schema instead of a retired one. Fix the block, or -- if the "
                 "old notes really were written this way -- fix "
                 "RETIRED_TOPICS_FIXTURE in tests/test_conventions.py and say "
                 "why in the same commit."
                 % (", ".join(got), ", ".join(want)), rel(CONVENTIONS))
        return
    name = _classify(list(RETIRED_TOPICS_FIXTURE), schemas)
    if name != "retired-topics":
        rep.fail(check,
                 "a note in the retired `topics:` shape (%s) classifies as %r, "
                 "not as `retired-topics`. §2c promises the opposite: that the "
                 "old shape is recognised as retired rather than mistaken for "
                 "the live source-note schema it shares seven keys with."
                 % (", ".join(want), name), rel(CONVENTIONS))
    else:
        rep.ok(check, "a note in §2c's retired `topics:` shape still "
                      "classifies as `retired-topics`, not as the live "
                      "source-note schema", rel(CONVENTIONS))


def check_frontmatter(rep, conv):
    check = "frontmatter-schema"
    schemas = _canonical_schemas(conv)
    optional = _schema_optional_keys(conv, schemas)
    all_fields = set().union(*[set(v) for v in schemas.values()]) | {"importance"}
    seen_any = {name: False for name in schemas}
    n_statements = [0]
    pending = Registry(rep, check, conv, "pending-frontmatter",
                       "the retired `topics:` schema")
    rep.ok(check, "the only key CONVENTIONS.md §2 lets a schema statement leave "
                  "out: %s" % "; ".join(
                      "%s -> %s" % (n, ", ".join(sorted(k)) or "none")
                      for n, k in sorted(optional.items())), rel(CONVENTIONS))
    _check_retired_schema(rep, check, schemas)

    def handle(keys, name, where, what, order_only=""):
        seen_any[name] = True
        n_statements[0] += 1
        if name in RETIRED_SCHEMAS:
            msg = ("%s still states the retired `%s` frontmatter schema (%s). "
                   "CONVENTIONS.md §2c retires it in favour of the source-note "
                   "schema; the same skill's own skeleton already emits the new "
                   "one, so the skill currently contradicts itself"
                   % (what, name, ", ".join(keys)))
            r = where.split(":")[0]
            if pending.claims(r):
                pending.hit(r, msg, where)
            else:
                rep.fail(check, msg, where)
            return
        _check_sequence(rep, check, keys, name, schemas, where, what,
                        optional.get(name), order_only)

    for skill, path, text in walk_skill_files():
        # (a) YAML examples in markdown.  Order only: an *instance* of a note
        #     may legitimately be a fragment (`SKILL.md` shows the five keys a
        #     raw Web Clipper capture arrives with), and the completeness of a
        #     real frontmatter block is `check_yaml_examples`' job -- it reads
        #     the `---` fences, knows which fence is this plugin's own output,
        #     and already names every required key a block omits.
        if path.endswith(".md"):
            for m in FENCE_RE.finditer(text):
                keys = YAML_KEY_RE.findall(m.group(1))
                if len(keys) < 4:
                    continue
                name = _classify(keys, schemas)
                if not name:
                    continue
                # The raw Web Clipper capture (title, source, author, ... --
                # no `format:`, no `type:`, no `topics:`) is an EXTERNAL input
                # format several files legitimately show, not a statement of
                # any schema of ours.  Since the source-note rename (scalar
                # `source` -> list `sources`) its keys subsequence into
                # `retired-topics` rather than into the live schema, so it
                # needs the exemption `yaml-example` already gives it.
                if ("source" in keys and "format" not in keys
                        and "type" not in keys and "topics" not in keys):
                    continue
                handle(keys, name, at(path, m.start(), text),
                       "%s YAML example" % rel(path),
                       order_only="a YAML example is an instance, and "
                                  "`yaml-example` checks its required keys")

        # (b) prose / constant lists of field names, in any punctuation.
        for values, off in maximal_runs(text, all_fields, min_len=5):
            name = _classify(values, schemas)
            if not name:
                continue
            slice_of = _list_slice_of(text, off, values, all_fields)
            handle(values, name, at(path, off, text), "%s field list" % rel(path),
                   order_only=("`%s` sits in the same list, so this is a slice "
                               "of a longer list of its own" % slice_of)
                   if slice_of else "")

        # (c) numbered/bulleted field lists, which the run extractor cannot see
        #     because prose text sits between the members.
        for keys, off in _enumerated_field_lists(text, all_fields):
            name = _classify(keys, schemas)
            if not name:
                continue
            handle(keys, name, at(path, off, text),
                   "%s numbered field list" % rel(path))

    rep.saw(check, "frontmatter schema statements", n_statements[0])
    for name, seen in seen_any.items():
        if not seen and name not in RETIRED_SCHEMAS:
            rep.fail(check, "no skill states the %s frontmatter schema -- "
                            "CONVENTIONS.md §2 documents a schema nothing "
                            "implements, or the extractor is broken" % name)
    pending.finish()


NUMBERED_FIELD = re.compile(r"^[ \t]*(\d+)\.[ \t]+`([a-z_][a-z_0-9]*)`", re.M)


def _enumerated_field_lists(text, members):
    """Field lists written as an **ordinal** list, one field per line.

    A skill stating its canonical order this way (``1. `title` `` …) is
    invisible to the separator-run extractor, because each item carries prose
    between it and the next.  One did, which is why this exists.

    Only *numbered* lists count, and only when the numbers run 1, 2, 3, ….  A
    bulleted list of per-field rules (``- `description` is <= 110 characters``)
    is a checklist, not a statement of order -- treating one as a schema
    reports every checklist that happens to discuss fields in a useful order as
    drift.
    """
    hits = [(int(m.group(1)), m.group(2), m.start())
            for m in NUMBERED_FIELD.finditer(text)]
    out, cur = [], []

    def flush():
        if len(cur) >= 5:
            out.append(([n for _, n, _ in cur], cur[0][2]))
        cur.clear()

    for num, name, off in hits:
        expected = cur[-1][0] + 1 if cur else 1
        if name not in members or num != expected:
            flush()
            if name in members and num == 1:
                cur.append((num, name, off))
            continue
        cur.append((num, name, off))
    flush()
    return out


# ===========================================================================
# check 4b -- what the YAML examples actually say
# ===========================================================================
#
# The schema check above compares *field orders*.  That is only half of §2:
# the other half is what goes in the fields, and it is the half with the
# silent failure modes.  An unquoted `- #machine-learning` is a YAML comment,
# so the discipline vanishes with no error anywhere (§2a, §3); a `sources:`
# item without a page anchor breaks the one thing §7 guarantees; a
# `description` over the cap is invisible until a reader hits it.
#
# Every rule here is read from CONVENTIONS.md -- the field orders and the tag
# enum from canonical blocks, the fifteen `type` values and the 110-character
# cap from the prose of §2a, which is where they are stated.

#: `type` is one of fifteen: `Concept` `Person` ... -- §2a.
TYPE_ENUM_RE = re.compile(
    r"`type`\s+is\s+one\s+of\s+([a-z]+)\s*:\s*((?:\s*`[^`\n]+`)+)", re.S)
#: `description` is <= 110 characters -- §2a and §2b state the same cap.
DESC_MAX_RE = re.compile(r"`description`\s+is\s*(?:\\u2264|≤|<=)\s*(\d+)\s*characters")

_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                 "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                 "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
                 "fifteen": 15, "sixteen": 16, "twenty": 20, "twenty-five": 25}


def _derive(rep, check, what, value, where):
    """Report a derivation that stopped matching CONVENTIONS.md.

    A canonical value this test can no longer find must never degrade into an
    empty list that everything vacuously satisfies.  It is a FAIL naming the
    statement and the file to edit -- loud, and it does not abort the other
    checks the way a HarnessError would.
    """
    if value:
        return value
    rep.fail(check,
             "the harness can no longer locate %s in %s, so the rule it "
             "derives is UNCHECKED. CONVENTIONS.md was reworded (or the rule "
             "removed); update the extractor in tests/test_conventions.py to "
             "match -- do not leave this unguarded." % (what, where))
    return None


def derive_type_enum(rep, check, conv):
    m = TYPE_ENUM_RE.search(conv)
    if not m:
        return _derive(rep, check, "§2a's `type` enum", None, rel(CONVENTIONS))
    vals = re.findall(r"`([^`\n]+)`", m.group(2))
    want = _NUMBER_WORDS.get(m.group(1).lower())
    if want is not None and want != len(vals):
        rep.fail(check,
                 "CONVENTIONS.md §2a says `type` is one of %s but lists %d "
                 "values (%s) -- the authority contradicts itself"
                 % (m.group(1), len(vals), ", ".join(vals)), rel(CONVENTIONS))
        return None
    return _derive(rep, check, "§2a's `type` enum", vals, rel(CONVENTIONS))


#: `format` is `Article` | `Post` | `Video` for a web clipping, and `Paper` |
#: `Book` | `Report` for a note built from a local PDF -- §2b.
FORMAT_ENUM_RE = re.compile(r"`format`\s+is\s+(.*?)(?:\n[ \t]*\n|Unquoted)", re.S)


def derive_format_enum(rep, check, conv):
    m = FORMAT_ENUM_RE.search(conv)
    vals = set(re.findall(r"`([A-Z][A-Za-z]*)`", m.group(1))) if m else set()
    return _derive(rep, check, "§2b's `format` enum", vals or None,
                   rel(CONVENTIONS))


def derive_description_max(rep, check, conv):
    m = DESC_MAX_RE.search(conv)
    return _derive(rep, check, "§2a's `description` length cap",
                   int(m.group(1)) if m else None, rel(CONVENTIONS))


FM_FENCE_RE = re.compile(r"```[a-z]*\n(---\n.*?\n---)\s*?\n", re.S)
FM_KEY_RE = re.compile(r"^([a-z_][a-z_0-9]*):[ \t]*(.*)$")
FM_ITEM_RE = re.compile(r"^[ \t]+-[ \t]*(.*)$")
#: A `**Related:**` footer line and everything on it.
RELATED_LINE_RE = re.compile(r"^\*\*Related:\*\*[ \t]*(.*)$", re.M)


def _strip_comment(v):
    """Drop a trailing ` # ...` comment that is not inside quotes."""
    out, quote = [], None
    for i, ch in enumerate(v):
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            out.append(ch)
            continue
        if ch == "#" and i and v[i - 1] in " \t":
            break
        out.append(ch)
    return "".join(out).strip()


def parse_frontmatter(block):
    """``[(key, inline_value, [items], line_offset)]`` for a `---`-fenced block.

    Deliberately not a YAML parser: it reads what a *reader* sees -- the key
    order, the raw inline value, and the raw list items with their quoting
    intact.  A real parser would throw away exactly the quoting this check
    exists to police.
    """
    lines = block.splitlines()
    fields, cur = [], None
    for n, ln in enumerate(lines):
        if ln.strip() == "---":
            if fields and n > 1:
                break
            continue
        m = FM_KEY_RE.match(ln)
        if m:
            cur = [m.group(1), _strip_comment(m.group(2)), [], n]
            fields.append(cur)
            continue
        m = FM_ITEM_RE.match(ln)
        if m and cur is not None:
            cur[2].append(_strip_comment(m.group(1)))
    return fields


def _is_placeholder(v):
    return "<" in v and ">" in v


def _dq(v):
    return len(v) >= 2 and v[0] == '"' and v[-1] == '"'


def check_yaml_examples(rep, conv):
    """Complete frontmatter examples obey §2a/§2b, not just the field order."""
    check = "yaml-example"
    schemas = _canonical_schemas(conv)
    optional = _schema_optional_keys(conv, schemas)
    tag_enum = set(canonical_block(conv, "tag-enum"))
    types = derive_type_enum(rep, check, conv)
    desc_max = derive_description_max(rep, check, conv)
    formats = derive_format_enum(rep, check, conv)
    if types is None or desc_max is None or formats is None:
        return
    slugger = _load_module(SLUGIFY, "_shared_slugify") \
        if os.path.isfile(SLUGIFY) else None

    n_entry = n_note = 0
    for skill, path, text in walk_skill_files():
        if not path.endswith(".md"):
            continue
        for m in FM_FENCE_RE.finditer(text):
            fields = parse_frontmatter(m.group(1))
            keys = [f[0] for f in fields]
            if len(keys) < 4:
                continue
            name = _classify(keys, schemas)
            if name not in ("wiki-entry", "source-note"):
                continue
            # A source-note example without `format:` is the *raw* Web Clipper
            # capture, which several files legitimately show as input.  The
            # `format:` key is precisely what clipping-processor adds, so its
            # presence is what marks a fence as this plugin's own output.
            if name == "source-note" and "format" not in keys:
                continue
            base = line_of(text, m.start())
            where = at(path, base)

            def bad(msg, f=None):
                rep.fail(check, "%s: %s" % (rel(path), msg),
                         at(path, base + (f[3] if f else 0) + 1))

            by = {f[0]: f for f in fields}
            # `required` is the canonical order less whatever CONVENTIONS.md's
            # own §2 subsection calls omittable -- the same derivation
            # `frontmatter-schema` uses, so the two checks cannot disagree
            # about which key may be left out.
            required = [k for k in schemas[name] if k not in optional[name]]
            if name == "wiki-entry":
                n_entry += 1
                quoted_lists = ("aliases", "sources", "tags", "parents")
                # `read` is here because §2a/§2d name it with the never-quote
                # three: a quoted `read: "false"` is a STRING, and Obsidian's
                # checkbox renders it permanently ticked -- the one value drift
                # in an example that teaches a silently wrong vault state.
                never_quoted = ("type", "created", "updated", "read")
                always_quoted = ("title", "description")
            else:
                n_note += 1
                quoted_lists = ("tags", "sources")
                never_quoted = ("format", "read")
                always_quoted = ()

            missing = [k for k in required if k not in by]
            if missing:
                bad("frontmatter example omits required %s key(s) %s. "
                    "CONVENTIONS.md §2 makes every key mandatory (a blank "
                    "value is fine where allowed, an absent key is not); an "
                    "example that omits one teaches the omission."
                    % (name, ", ".join(missing)))

            for k in always_quoted:
                f = by.get(k)
                if f and f[1] and not _dq(f[1]):
                    bad("`%s:` is not double-quoted in a %s example -- §2a "
                        "requires double quotes on it" % (k, name), f)
            for k in never_quoted:
                f = by.get(k)
                if f and f[1] and (_dq(f[1]) or f[1].startswith("'")):
                    bad("`%s:` is quoted in a %s example -- §2 says it is "
                        "never quoted" % (k, name), f)
            for k in quoted_lists:
                f = by.get(k)
                if not f:
                    continue
                for item in f[2]:
                    if not _dq(item):
                        bad("`%s:` item %s is not double-quoted. §2a/§3: the "
                            "quotes are load-bearing -- an unquoted "
                            "`- #machine-learning` is a YAML comment and the "
                            "value is silently lost." % (k, item), f)
            if name == "source-note":
                f = by.get("author")
                if f and f[1] and f[1] != "[]":
                    bad("populated `author:` is inline (%s). §2b requires a "
                        "block-form list; the only inline form is the exact "
                        "authorless exception `author: []`" % f[1], f)
                if f and not f[1] and not f[2]:
                    bad("bare `author:` is YAML null. §2b requires populated "
                        "block-list items or the exact authorless exception "
                        "`author: []`", f)
                for item in (f[2] if f and not f[1] else []):
                    if _dq(item) or item.startswith("[["):
                        bad("`author:` item %s keeps quotes or a `[[…]]` "
                            "wrapper; §2b says author items are unquoted with "
                            "the wikilink wrapper stripped" % item, f)
                fmt = (by.get("format") or [None, ""])[1]
                sf = by.get("sources")
                if fmt.strip() == "Book" and sf and \
                        len([i for i in sf[2] if i.strip()]) > 1:
                    bad("a `sources:` URL item is present on a `format: Book` "
                        "example -- §2b says a book chapter never carries "
                        "one", sf)

            # tags: values are enum members, `#`-prefixed
            f = by.get("tags")
            for item in (f[2] if f else []):
                inner = item.strip('"').strip()
                if _is_placeholder(inner):
                    continue
                if not inner.startswith("#"):
                    bad("`tags:` item %s is not `#`-prefixed (§3)" % item, f)
                elif inner[1:] not in tag_enum:
                    bad("`tags:` item %s is not one of the %d discipline "
                        "values in CONVENTIONS.md §3"
                        % (item, len(tag_enum)), f)

            f = by.get("type")
            if name == "wiki-entry" and f and f[1] and not _is_placeholder(f[1]):
                if f[1].strip('"') not in types:
                    bad("`type: %s` is not one of the %d values in "
                        "CONVENTIONS.md §2a (%s)"
                        % (f[1], len(types), ", ".join(types)), f)

            f = by.get("sources")
            for item in (f[2] if f and name == "wiki-entry" else []):
                inner = item.strip('"').strip()
                if _is_placeholder(inner) or inner == "stub":
                    continue
                mm = re.match(r"^\[\[([^\]]+)\]\]$", inner)
                if not mm:
                    bad("`sources:` item %s is not a quoted wikilink, and is "
                        "not the literal \"stub\" (§7)" % item, f)
                    continue
                target = mm.group(1)
                if target.endswith(".md"):
                    pass
                elif re.match(r"^.+\.pdf#page=\d+$", target):
                    pass
                elif target.endswith(".pdf"):
                    bad("`sources:` item %s names a PDF with no `#page=N` "
                        "anchor -- §7 requires the anchor on every PDF source"
                        % item, f)
                elif ".md#" in target:
                    bad("`sources:` item %s anchors a markdown source -- §7 "
                        "says a markdown source never carries an anchor" % item, f)
                else:
                    bad("`sources:` item %s carries no file extension; §7 "
                        "requires the literal on-disk filename, extension "
                        "included" % item, f)

            if name == "source-note" and f:
                # §2b: the list opens with the document's origin -- a URL item
                # on a clipping, the bare PDF wikilink (no anchor) on a note
                # about a local document -- and may carry one printed-origin
                # URL as item 2.  §7's page anchors are a wiki-entry rule and
                # do not apply here.
                items = [i for i in f[2] if i.strip()]
                for pos, item in enumerate(items, 1):
                    inner = item.strip('"').strip()
                    if _is_placeholder(inner):
                        continue
                    is_url = inner.startswith(("https://", "http://"))
                    mm = re.match(r"^\[\[([^\]]+)\]\]$", inner)
                    if pos == 1:
                        if is_url:
                            continue
                        if not (mm and mm.group(1).endswith(".pdf")):
                            bad("`sources:` item 1 %s is neither a URL (a "
                                "clipping's capture URL) nor a bare "
                                "`[[….pdf]]` wikilink (§2b)" % item, f)
                        elif "#" in mm.group(1):
                            bad("`sources:` item 1 %s anchors the PDF -- "
                                "§2b's pairing wikilink is the bare basename, "
                                "no `#page=N`" % item, f)
                    elif not is_url:
                        bad("`sources:` item %d %s is not a URL -- §2b: later "
                            "items are the document's printed origin"
                            % (pos, item), f)
                if len(items) > 2:
                    bad("`sources:` holds %d items -- §2b caps a source note "
                        "at two (the PDF, then its printed URL)"
                        % len(items), f)
                # §2b: a CLIPPING holds exactly one item, its capture URL.
                # Item 1 being a URL is what makes the example a clipping, so
                # a second item on it teaches the two-URL list no producer
                # writes.
                if len(items) > 1 and items[0].strip().strip('"').startswith(
                        ("https://", "http://")):
                    bad("`sources:` item 1 is a URL (a clipping) but the list "
                        "holds %d items -- §2b: a cleaned clipping carries "
                        "exactly one item, its capture URL" % len(items), f)

            # §4b: every alias is slug-form, because aliases *are* alternative
            # slugs -- a future candidate that slugs to one resolves here.  An
            # alias that is not itself a slug can never be hit.
            f = by.get("aliases")
            for item in (f[2] if f else []):
                inner = item.strip('"').strip()
                if _is_placeholder(inner) or slugger is None:
                    continue
                try:
                    want = slugger.slug_stem(inner)
                except Exception:
                    continue
                if want != inner:
                    bad("`aliases:` item %s is not slug-form -- it slugs to "
                        "`%s`. §4b: aliases ARE alternative slugs; one that is "
                        "not itself a slug is never matched by anything."
                        % (item, want), f)

            # §2b: `format` is one of six values.
            f = by.get("format")
            if f and f[1] and formats and not _is_placeholder(f[1]):
                if f[1].strip() not in formats:
                    bad("`format: %s` is not one of the %d values in "
                        "CONVENTIONS.md §2b (%s)"
                        % (f[1], len(formats), ", ".join(sorted(formats))), f)

            f = by.get("description")
            if f and f[1] and not _is_placeholder(f[1]):
                val = f[1].strip('"')
                if len(val) > desc_max:
                    bad("`description:` in this example is %d characters; "
                        "CONVENTIONS.md §2 caps it at %d"
                        % (len(val), desc_max), f)

    rep.saw(check, "wiki-entry frontmatter examples", n_entry)
    rep.saw(check, "source-note frontmatter examples", n_note)
    if n_entry or n_note:
        rep.ok(check, "%d wiki-entry and %d source-note frontmatter example(s) "
                      "conform to CONVENTIONS.md §2/§3/§7" % (n_entry, n_note))

    # Every *fragment* of a block-form list field, not just the complete
    # frontmatter blocks.  A skill teaching `tags:` in a three-line snippet is
    # teaching it just as effectively, and the unquoted form is the failure
    # §2a and §3 both single out: `- #machine-learning` is a YAML comment, the
    # discipline is dropped, and nothing anywhere reports it.
    n_items = 0
    for path, text in walk_plugin_files():
        if not path.endswith(".md"):
            continue
        for fm in FENCE_RE.finditer(text):
            body = fm.group(1)
            for km in re.finditer(r"^(aliases|sources|tags|parents):[ \t]*$",
                                  body, re.M):
                rest = body[km.end():].splitlines()
                for ln in rest:
                    if not ln.strip():
                        continue
                    im = FM_ITEM_RE.match(ln)
                    if not im:
                        break
                    n_items += 1
                    item = _strip_comment(im.group(1))
                    off = fm.start(1) + km.start()
                    if not _dq(item):
                        rep.fail(check,
                                 "%s shows `%s:` with the unquoted item `%s`. "
                                 "CONVENTIONS.md §2a/§3: every item under "
                                 "aliases/sources/tags/parents is "
                                 "double-quoted, and an unquoted "
                                 "`- #machine-learning` parses as a YAML "
                                 "comment -- the value is silently lost, with "
                                 "no error anywhere."
                                 % (rel(path), km.group(1), item),
                                 at(path, off, text))
    rep.saw(check, "block-form list items in examples", n_items)
    if n_items:
        rep.ok(check, "%d block-form list item(s) in examples are "
                      "double-quoted (§2a/§3)" % n_items)

    # §6: EVERY `**Related:**` footer link is piped, even when slug-equal.
    # An unpiped example teaches the bare form, and wiki-linter then "fixes"
    # what wiki-builder wrote, run after run.
    n_rel = 0
    for path, text in walk_plugin_files():
        if not path.endswith(".md"):
            continue
        for m in RELATED_LINE_RE.finditer(text):
            for lm in re.finditer(r"\[\[([^\]\n]+)\]\]", m.group(1)):
                target = lm.group(1)
                if "…" in target or "..." in target or "<" in target:
                    continue          # an elided placeholder, not a link
                n_rel += 1
                if "|" not in target:
                    rep.fail(check,
                             "%s shows an unpiped `**Related:**` link "
                             "`[[%s]]`. CONVENTIONS.md §6: every Related "
                             "footer link is piped -- `[[slug|Canonical "
                             "Title]]` -- even when the label equals the slug."
                             % (rel(path), target),
                             at(path, m.start(1) + lm.start(), text))
    rep.saw(check, "Related-footer links in examples", n_rel)
    if n_rel:
        rep.ok(check, "%d `**Related:**` footer link(s) in examples are piped "
                      "(§6)" % n_rel)


# ===========================================================================
# check 4c -- the `type` enum, wherever it is restated
# ===========================================================================

#: `type` values are capitalised and one of them carries a slash
#: (`Gene/Protein`), so the lowercase token regex above cannot see them.
TYPE_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9/-]*")
LOWER_TYPE_TOKEN_RE = re.compile(r"[a-z][a-z0-9/-]*")

#: A list that *says* it is only part of the enum.  Deliberate subsets exist
#: ("the remaining ten (…)", "**All other types** (…)"), and they are legitimate
#: -- but only when the file announces them.  Without this cue, "shorter than
#: the enum" was itself the licence: dropping a value from a full restatement
#: made it a 14-value run, which the check then re-classified as a deliberate
#: subset and *reported as a pass*.
TYPE_SUBSET_CUE = re.compile(
    r"\b(?:all other|the other|other than|remaining|rest of|except|excluding|"
    r"besides|apart from|less the|minus|only the|just the)\b[^.\n]{0,80}$", re.I)
#: A count inside that cue -- "the remaining **ten** (`Device`, …)".  When the
#: cue counts, the count is checked, so a value deleted from a declared subset
#: is drift there too.
TYPE_SUBSET_COUNT = re.compile(r"\b(%s)\b[^.\n]{0,60}$" % _COUNT_ALT, re.I)

#: How many canonical `type` values in a row make a run a restatement of the
#: enum rather than a coincidence.  See the note in :func:`check_type_enum`.
TYPE_ENUM_RUN_MIN = 6


def _check_type_subset(rep, check, path, text, values, types, off, where):
    """A restatement shorter than the enum: legitimate only if declared.

    Three ways a shorter list can be honest, and nothing else is:

    * the cue counts the subset ("the remaining **ten**") -- then the count has
      to be right, so a value deleted from a declared subset is drift too;
    * the cue names the complement instead ("**All other types**", after a
      bullet about `Software`) -- then every value left out has to be named as
      a type in the run-up, or the reader cannot tell what "other" excludes;
    * there is no cue at all -- which is not honest, and is the shape a
      deletion from a full restatement leaves behind.
    """
    missing = [t for t in types if t not in values]
    pre = text[max(0, off - 200):off]
    # A wider scope for "is the complement on the page?" than for the cue
    # itself: the cue has to be right in front of the list, but the bullet it
    # is the counterpart of ("**`Software` entries:** …") can be a paragraph
    # long.  Still bounded -- "somewhere in the file" would exempt everything.
    run_up = text[max(0, off - 1000):off]
    cue = TYPE_SUBSET_CUE.search(pre)
    if not cue:
        rep.fail(check,
                 "%s restates %d of the %d canonical `type` values, leaving out "
                 "%s, and nothing in the sentence says it is only part of the "
                 "list. A value dropped from a restatement is drift -- the "
                 "loader-visible description and the §2a field table are what "
                 "route work to this skill. Write the whole enum, or say which "
                 "part of it this is (\"the remaining ten\", \"all other "
                 "types\")."
                 % (rel(path), len(values), len(types),
                    ", ".join("`%s`" % t for t in missing)), where)
        return
    said = TYPE_SUBSET_COUNT.search(pre[:cue.end()])
    if said:
        word = said.group(1).lower()
        want = NUMBER_WORDS.get(word, int(word) if word.isdigit() else None)
        if want is not None and want != len(values):
            rep.fail(check,
                     "%s announces %s of the %d `type` values (\"%s\") and then "
                     "lists %d: %s. A counted subset whose count is wrong is "
                     "the same drift as a wrong enum, one indirection out."
                     % (rel(path), word, len(types),
                        " ".join(pre[cue.start():].split())[:60], len(values),
                        ", ".join(values)), where)
            return
        rep.ok(check, "%s lists the declared subset of %d `type` value(s), all "
                      "canonical, and the count it announces matches"
               % (rel(path), len(values)), where)
        return
    unnamed = [t for t in missing if t not in run_up]
    if unnamed:
        rep.fail(check,
                 "%s lists %d `type` values as \"%s\" but never says what the "
                 "other %d are: %s appear(s) neither in the list nor in the "
                 "run-up to it. An uncounted subset is readable only when its "
                 "complement is on the page -- otherwise a deleted value looks "
                 "exactly like an excluded one."
                 % (rel(path), len(values),
                    " ".join(pre[cue.start():].split())[:40], len(missing),
                    ", ".join("`%s`" % t for t in unnamed)), where)
        return
    rep.ok(check, "%s lists a declared %d-value subset of the `type` enum; the "
                  "%d value(s) it leaves out are named beside it"
           % (rel(path), len(values), len(missing)), where)


def check_type_enum(rep, conv):
    """§2a's fifteen `type` values, checked like the tag enum."""
    check = "type-enum"
    types = derive_type_enum(rep, check, conv)
    if types is None:
        return
    type_set = set(types)
    lower_map = {t.lower(): t for t in types}
    # The floor is "this run of canonical values cannot be a coincidence", NOT
    # "this run is nearly the whole enum".  At `len(types) - 5` a deletion
    # could drop a statement out of the population entirely -- one value less
    # than the floor and the run is not extracted, so the drift costs a check
    # rather than failing one.  Six is well below every real statement in the
    # tree and discovers nothing new (verified against the clean tree).
    min_len = max(4, min(TYPE_ENUM_RUN_MIN, len(types)))
    n_prose = n_const = 0

    for skill, path, text in walk_skill_files():
        # A full restatement is what must agree.  Deliberate subsets exist and
        # are legitimate (`references/rare-types.md` defines ten of them, and
        # `api-surface.md` speaks about "all other types") -- but the file has
        # to SAY so.  Length alone cannot be the licence: a value deleted from
        # a full restatement produces a shorter run, and reading that as a
        # deliberate subset reported the drift as a pass, with an unchanged
        # check count.  `tag-enum` never had this branch and caught the same
        # deletion; only this check did.
        #
        # Two passes: the enum as written (`Concept`), and the lowercase prose
        # form a SKILL.md description uses ("a concept, person, ... or quote").
        # The description is what the loader shows and what routes work, so a
        # value dropped from it is drift too.
        found = list(enum_statements(text, type_set, min_len, TYPE_TOKEN_RE))
        found += [([lower_map[v] for v in vals], extras, off)
                  for vals, extras, off in
                  enum_statements(text, set(lower_map), min_len,
                                  LOWER_TYPE_TOKEN_RE, ENUM_GLUE)]
        for values, extras, off in found:
            n_prose += 1
            where = at(path, off, text)
            if extras:
                rep.fail(check,
                         "%s lists %s alongside %d of the %d canonical `type` "
                         "values. §2a closes the list: a sixteenth type has no "
                         "definition, no lint rule and no reader."
                         % (rel(path), ", ".join(sorted(set(extras))),
                            len(values), len(types)), where)
            elif len(values) >= len(types):
                _check_enum_statement(rep, check, values, [], types, where,
                                      rel(path), "`type` enum")
            else:
                _check_type_subset(rep, check, path, text, values, types, off,
                                   where)

        if path.endswith(".py"):
            for vals, lineno in python_literal_lists(text):
                if len(set(vals) & type_set) < min_len:
                    continue
                n_const += 1
                _check_enum_statement(
                    rep, check, [v for v in vals if v in type_set],
                    [v for v in vals if v not in type_set], types,
                    at(path, lineno),
                    "%s constant at line %d" % (rel(path), lineno), "`type` enum")

    rep.saw(check, "prose statements of the type enum", n_prose)
    rep.saw(check, "script constants holding the type enum", n_const)


# ===========================================================================
# check 5 -- names used as contracts resolve to something that exists
# ===========================================================================
#
# The check below is called `contract-name-resolution`, and that is all it
# does.  It reads three populations of *name*:
#
#   * a backticked kebab token used as a skill -> a directory under skills/;
#   * a vault path attributed to another skill -> that skill's own text, or
#     CONVENTIONS.md;
#   * a `field:` attributed to another skill  -> the same.
#
# It was called `contract-fiction`, which promised something much larger than
# it delivers: a paragraph attributing SHA-256 checksum verification, XMP
# refusal, emailed receipts and atomic batch rollback to `scripts/organize.py`
# passed it without a murmur, because none of those are names.  Nothing here
# reads behaviour, and the name now says so.  `script-surface` below is the
# narrow, honest piece of the behavioural claim that CAN be checked: a
# documented script and a documented flag either exist or they do not.

SENT_SPLIT = re.compile(r"(?<=[.:;!?])\s+|\n")
BACKTICK_NAME = re.compile(r"`([a-z][a-z0-9]*(?:-[a-z0-9]+)+)`")
#: A backticked kebab name is being used as the name of a *skill* when its
#: sentence talks about skills, or when it sits in one of these frames.  The
#: sentence test alone misses "named in the `pdf-organizer` convention"; the
#: frames alone would miss a lot.  Both together are approximate but cheap, and
#: a miss costs a check, not a false alarm.
SKILL_FRAME = re.compile(
    r"`%s`\s*(?:convention|naming|pipeline|skill)"
    r"|(?:by|run|runs|invoke|via|through|hand(?:ed|s)? (?:it |them )?(?:off )?to)\s+`%s`")
#: A vault-path-shaped token: at least one `Capitalised/` or `<placeholder>/`
#: segment.  This is the shape of the original bug (`Clippings/Extracted/`).
VAULT_PATH = re.compile(
    r"`[^`\n]{0,40}?((?:[A-Z][A-Za-z0-9_.-]*|<[a-z-]+>)/(?:[A-Za-z0-9_.<>-]+/?)*)[^`\n]{0,40}?`")
FIELD_CLAIM = re.compile(r"`([a-z_]+):\s*[^`\n]{0,40}`")
PLUGIN_INTERNAL = re.compile(r"^(references|scripts|shared|skills|tests)/"
                             r"|/(references|scripts)/")
#: A trailing path segment that names an *instance* rather than a contract
#: (`Sources/Geron_HandsOnML_2025/` vs `Clippings/Extracted/`).
INSTANCE_SEG = re.compile(r"_|\d{4}")


def _sentences(text):
    i = 0
    for m in SENT_SPLIT.finditer(text):
        chunk = text[i:m.start()]
        if chunk.strip():
            yield i, chunk
        i = m.end()
    if text[i:].strip():
        yield i, text[i:]


def _path_prefixes(token):
    """`Sources/Geron_HandsOnML_2025/` -> that, then `Sources/`.

    Only *instance-shaped* trailing segments are stripped, so a contract-shaped
    leaf (`Clippings/Extracted/`) is never softened into its parent.

    A leading `<placeholder>/` segment is also dropped, because `<vault>/Foo/`
    and `Foo/` are the same folder and CONVENTIONS.md only ever writes the
    bare form.  Without this, spelling a documented path with its vault prefix
    reported it as fiction -- which says nothing about the claim and
    everything about which of two spellings the sentence happened to use.
    """
    yield token
    segs = [s for s in token.split("/") if s]
    if len(segs) > 1 and segs[0].startswith("<") and segs[0].endswith(">"):
        segs = segs[1:]
        yield "/".join(segs) + ("/" if token.endswith("/") else "")
    while segs and INSTANCE_SEG.search(segs[-1]):
        segs.pop()
        if segs:
            yield "/".join(segs) + "/"


def check_contract_fictions(rep, conv):
    check = "contract-name-resolution"
    skills = skill_names()
    external = Registry(rep, check, conv, "external-skills",
                        "the reference to a skill that does not ship here")
    tag_values = set(canonical_block(conv, "tag-enum"))

    texts = {}
    for skill, path, text in walk_skill_files():
        texts.setdefault(skill, {})[path] = text
    blobs = {s: "\n".join(texts.get(s, {}).values()).lower() for s in skills}
    conv_low = conv.lower()

    # (a) a name used as a skill must be a skill (or a registered external).
    for skill in skills:
        for path, text in sorted(texts.get(skill, {}).items()):
            for off, sent in _sentences(text):
                sentence_is_about_skills = bool(re.search(r"\bskill", sent, re.I))
                loose_ok = _loose_frame_applies(sent, set(skills))
                for m in BACKTICK_NAME.finditer(sent):
                    name = m.group(1)
                    if (name in skills or "." in name or "/" in name
                            or name in tag_values):
                        continue
                    esc = re.escape(name)
                    if not sentence_is_about_skills and not re.search(
                            SKILL_FRAME.pattern % (esc, esc), sent, re.I) \
                            and not (loose_ok
                                     and re.search(LOOSE_AGENT_FRAME % esc, sent)):
                        continue
                    where = at(path, off + m.start(), text)
                    if external.claims(name):
                        external.hit(name,
                                     "%s refers to `%s` as a skill; nothing in "
                                     "this plugin implements it, so the "
                                     "contract it names is never enforced and "
                                     "never fails -- it just quietly does not "
                                     "happen" % (rel(path), name), where)
                    else:
                        rep.fail(check,
                                 "%s refers to `%s` as a skill, but there is no "
                                 "skills/%s/ and it is not registered in "
                                 "CONVENTIONS.md §10b. A contract with a skill "
                                 "that does not exist is never enforced and "
                                 "never fails -- it just quietly does not "
                                 "happen." % (rel(path), name, name), where)

    # (b) a vault artifact attributed to another skill must be grounded --
    #     in that skill's own text, or in CONVENTIONS.md (which is now the
    #     canonical home for every cross-skill contract).
    grounded = 0
    kinds = {"path": 0, "field": 0}
    for skill in skills:
        for path, text in sorted(texts.get(skill, {}).items()):
            for off, sent in _sentences(text):
                others = [o for o in skills if o != skill and o in sent]
                if not others:
                    continue
                claims = []
                for m in VAULT_PATH.finditer(sent):
                    tok = m.group(1)
                    if PLUGIN_INTERNAL.search(tok) or tok.startswith(("http", "/tmp")):
                        continue
                    claims.append(("path", tok, m.start()))
                for m in FIELD_CLAIM.finditer(sent):
                    claims.append(("field", m.group(1) + ":", m.start()))
                for kind, tok, moff in claims:
                    kinds[kind] += 1
                    variants = list(_path_prefixes(tok)) if kind == "path" else [tok]
                    for other in others:
                        if any(v.lower() in blobs.get(other, "")
                               or v.lower() in conv_low
                               for v in variants):
                            grounded += 1
                            continue
                        rep.fail(check,
                                 "%s attributes `%s` to %s, but %s's own text "
                                 "never mentions it and CONVENTIONS.md does not "
                                 "document it. Either %s implements it (say so "
                                 "there), or the claim is fiction."
                                 % (rel(path), tok, other, other, other),
                                 at(path, off + moff, text))
    # Per-pattern, not per-check: with one ledger entry, breaking the path
    # extractor still left the field extractor's count non-zero and the
    # vacuity guard saw nothing wrong.
    for kind, n_kind in sorted(kinds.items()):
        rep.saw(check, "cross-skill %s claims" % kind, n_kind)
    if grounded:
        rep.ok(check, "%d cross-skill artifact claim(s) grounded in the named "
                      "skill or in CONVENTIONS.md" % grounded)

    # (c) a name routed work to in an explicit dispatch frame, with no
    #     decoration at all.  Both (a) above and the roster check read only
    #     backticked or bolded names, so "hand the file to pdf-to-md and use
    #     its output" -- an ordinary way to write it -- named a skill that
    #     does not exist and neither check could see it.
    n_routes, n_route_files = 0, 0
    for path, text in walk_plugin_files():
        n_route_files += 1
        for m in ROUTE_FRAME.finditer(text):
            name = m.group(1)
            if name in tag_values or FILENAME_TAIL.match(text[m.end(1):m.end(1) + 8]):
                continue
            n_routes += 1
            if name in skills:
                continue
            where = at(path, m.start(1), text)
            if external.claims(name):
                external.hit(name, "%s routes work to `%s` (\"%s\"); nothing in "
                                   "this plugin implements it"
                             % (rel(path), name,
                                " ".join(m.group(0).split())), where)
            else:
                rep.fail(check,
                         "%s routes work to `%s` (\"%s\"), but there is no "
                         "skills/%s/. A contract with a skill that does not "
                         "exist is never enforced and never fails -- the work "
                         "just quietly does not happen."
                         % (rel(path), name, " ".join(m.group(0).split()), name),
                         where)
    # The population guarded here is the corpus, not the hit count: a healthy
    # tree has zero routing frames pointing outside the roster, and demanding
    # a non-empty hit list would make the check demand its own violation.
    rep.saw(check, "files scanned for routing frames", n_route_files)
    rep.ok(check, "%d explicit routing frame(s) across %d file(s), all naming "
                  "a skill that ships here" % (n_routes, n_route_files))

    _check_ownership_split(rep, check, conv, skills, texts)
    external.finish()


#: A dispatch frame: work being handed to a named agent.  Deliberately narrow
#: -- these verbs are only used this way about a skill.
ROUTE_FRAME = re.compile(
    r"(?:hand(?:s|ed|ing)?|route[sd]?|delegate[sd]?|pass(?:es|ed)?|defer[sr]?ed?)"
    r"\s+(?:it|them|the\s+\w+|work|requests?)?\s*(?:off\s+)?to\s+"
    r"\**`?([a-z][a-z0-9]*(?:-[a-z0-9]+)+)`?\**")

#: §9's two headings.  The ownership rules below are anchored to them: if the
#: section is reorganised the anchors stop matching and the check says so
#: rather than quietly checking nothing.
OWNERSHIP_ANCHOR = re.compile(
    r"^###\s+([a-z-]+)\s+—\s+(inside the entries it writes|everything vault-wide)",
    re.M)
#: A sentence crediting the per-document skill with the whole-vault mandate.
WHOLE_VAULT_SCOPE = re.compile(
    r"vault-wide|retroactive|across every|every existing entry|whole vault|"
    r"entire vault|anywhere in the vault", re.I)
LINK_VERB = re.compile(r"link|backfill|prune|cross-link", re.I)
#: Deliberately excludes a bare "no": "so no bare mention is left unlinked" is
#: the *consequence* of the false claim, not a disclaimer of it, and treating
#: it as one let the whole rule through.
OWNERSHIP_NEGATION = re.compile(
    r"\bnot\b|\bnever\b|\bstops?\b|out of bounds|does not|doesn't|\bonly\b|"
    r"scoped|belongs to|\bis\b.{0,20}\bjob\b|cannot|\bstale\b", re.I)
#: How far back from the claim a disclaimer may sit and still be read as
#: disclaiming it.  Matched anywhere in the sentence, these twelve words
#: disarmed the rule from any distance: "This skill backfills links vault-wide
#: across every existing entry as it writes, and it is the only pass that does
#: so" passed on the `only` in its second clause, while the same sentence
#: without that clause failed.  A disclaimer governs what follows it, so the
#: window sits *before* the claim, and it is one clause long.
OWNERSHIP_NEGATION_REACH = 60


def _check_ownership_split(rep, check, conv, skills, texts):
    """§9: the linking bar has exactly one home, and it is not wiki-builder's.

    §9 says in as many words: "If wiki-builder's files still say anything
    about vault-wide or retroactive linking, that text is stale."  Nothing
    checked it, and a claim like "wiki-builder backfills links vault-wide" is
    a contract fiction that no path or field pattern can see -- it names no
    artifact, only a behaviour.
    """
    anchors = dict((m.group(2), m.group(1)) for m in OWNERSHIP_ANCHOR.finditer(conv))
    scoped = anchors.get("inside the entries it writes")
    vaultwide = anchors.get("everything vault-wide")
    if not scoped or not vaultwide:
        rep.fail(check,
                 "the harness can no longer find §9's two ownership headings "
                 "in %s (got %r), so the linking-ownership rule is UNCHECKED. "
                 "Update the anchor in tests/test_conventions.py."
                 % (rel(CONVENTIONS), sorted(anchors)))
        return
    n, n_files = 0, 0
    for skill in skills:
        for path, text in sorted(texts.get(skill, {}).items()):
            n_files += 1
            for off, sent in _soft_sentences(text):
                # "this skill" means *this* skill.  Read in every skill's
                # files, it made pdf-organizer's "A PDF basename this skill
                # produces is unique across the whole vault" a wiki-builder
                # ownership claim, and the check then leaned on an unrelated
                # "not" three clauses later to let it through.
                if scoped not in sent and not (
                        skill == scoped and "this skill" in sent.lower()):
                    continue
                if vaultwide in sent:
                    continue                # the disclaiming form names the owner
                cue = WHOLE_VAULT_SCOPE.search(sent)
                verb = LINK_VERB.search(sent)
                if not (cue and verb):
                    continue
                n += 1
                # The disclaimer has to govern the claim: it sits in the run-up
                # to whichever of the two halves comes first, not merely
                # somewhere in the same sentence.
                anchor = min(cue.start(), verb.start())
                if OWNERSHIP_NEGATION.search(
                        sent[max(0, anchor - OWNERSHIP_NEGATION_REACH):anchor]):
                    continue
                rep.fail(check,
                         "%s credits `%s` with %s linking (\"%s\"), and nothing "
                         "in the %d characters before it disclaims that. "
                         "CONVENTIONS.md §9 gives the whole retroactive and "
                         "cross-entry surface to `%s` alone: two skills "
                         "linking under separately-stated bars is what "
                         "produced the add-then-prune churn the split exists "
                         "to end. A disclaimer in a later clause does not "
                         "un-say it."
                         % (rel(path), scoped, "vault-wide/retroactive",
                            " ".join(sent.split())[:110],
                            OWNERSHIP_NEGATION_REACH, vaultwide),
                         at(path, off, text))
    rep.saw(check, "files scanned for §9 ownership claims", n_files)
    rep.ok(check, "%d whole-vault linking sentence(s) in `%s`'s files; each "
                  "disclaims the mandate §9 gives `%s` before making the claim, "
                  "rather than somewhere later in the sentence"
           % (n, scoped, vaultwide))


# ===========================================================================
# check 6 -- the skill roster, read from skills/ and checked plugin-wide
# ===========================================================================
#
# The roster has now gone stale three times, in both directions:
#
#   * a note-writing collaborator that two skills routed work to and that had
#     never existed at all;
#   * a file-organizing skill leaned on for a load-bearing uniqueness
#     guarantee before it was part of the plugin;
#   * a single-PDF conversion skill removed while five files still routed
#     requests to it, one reference file still justified a glob by its naming,
#     and three scripts still called themselves copies kept in sync with it.
#
# Every one of those is the same failure: a contract with a skill that is not
# installed is never enforced and never fails.  It just quietly does not
# happen, and the user gets silence where they expected work.  The names are
# deliberately not written down here -- a checker that hardcodes the roster,
# even in a comment, is the thing it is supposed to be preventing.
#
# `check_contract_fictions` already catches the *backticked, skill-sentenced*
# form inside `skills/`.  This check exists because that is not where the
# roster is mostly written down.  It is written down in README.md's pipeline
# diagram and skill table, in CONVENTIONS.md's ownership tables and
# "Depended on by" footers, and in routing tables whose skill names sit in the
# second column where the sentence heuristic cannot see them -- none of which
# the older check reads at all.  So this one is plugin-wide and structural.
#
# The roster is READ FROM `skills/`.  Adding or removing a skill needs no edit
# here; the check follows the directory.

#: A token shaped like a skill directory name: lowercase kebab-case, at least
#: two segments.  Deliberately the shape of the directory, not a list of them.
SKILL_SHAPED = re.compile(r"(?<![\w./-])([a-z][a-z0-9]*(?:-[a-z0-9]+)+)(?![\w-])")

#: The same shape, wrapped in the two decorations this tree uses for a skill
#: name: backticks in prose, bold in tables.  Bold is NOT accepted in prose --
#: `**report-only**` is emphasis, and treating emphasis as a skill name reports
#: every bolded compound in a sentence that mentions skills.
DECORATED_SKILL = re.compile(
    r"`([a-z][a-z0-9]*(?:-[a-z0-9]+)+)`"
    r"|\*\*([a-z][a-z0-9]*(?:-[a-z0-9]+)+)\*\*")
BACKTICKED_SKILL = re.compile(r"`([a-z][a-z0-9]*(?:-[a-z0-9]+)+)`")

#: A trailing extension makes the token a filename, not a skill name
#: (`wiki-builder-suggestions.md`, `machine-learning-moc.md`).
FILENAME_TAIL = re.compile(r"\.[a-z0-9]{1,5}\b")

#: A backticked name used as an *agent*: it owns something ("`pdf-organizer`'s
#: output"), or it acts ("`pdf-organizer` renames every file it processes").
#: Only a skill is written about that way, and this is the exact shape of the
#: two references that named an absent skill without ever saying "skill" --
#: which is why the sentence heuristic missed them both.
#: The verb list is deliberately narrow: only things a *skill* does to a vault.
#: A copula would not do -- `k-means` is a wiki entry, `rlottie-python` is a pip
#: package, and both get written about as "`x` is ...".
#: The possessive needs a skill-owned noun after it, for the same reason:
#: `k-means`'s parent is a wiki entry's field, not a skill's artifact.
AGENT_FRAME = re.compile(
    r"`%s`\s*(?:'s|’s)\s+(?:output|job|contract|guarantee|convention|naming|"
    r"input|batch|run|pipeline|scripts?|frontmatter|schema|workflow|copies|"
    r"copy|glob|defaults|own\b|SKILL)"
    r"|`%s`\s+(?:renames?|writes?|reads?|produces?|extracts?|creates?|globs?|"
    r"handles?|processes?|guarantees?|owns?|splits?|converts?|emits?|walks?|"
    r"sweeps?|lints?|embeds?|downloads?|prunes?|backfills?)\b")

#: The same frame with the verb list opened up: any present-tense verb, not the
#: twenty-one above.  "Afterwards `ocr-preprocess` cleans the scan and returns a
#: searchable PDF" named a skill that does not exist and passed both checks;
#: changing `cleans` to `processes` failed them.  The difference was a word this
#: file happens not to know, which is not a difference worth having.
#:
#: Copulas and auxiliaries stay out for the reason the narrow list has them out:
#: `k-means` *is* a wiki entry and `rlottie-python` *has* a text-layer bug, and
#: neither is a skill doing something.
LOOSE_AGENT_FRAME = (
    r"`%s`\s+(?:also |then |now |only |always |never |already |still |quietly |"
    r"simply )?(?!(?:is|was|were|has|have|had|does|did|means|seems|exists|"
    r"remains|stays|becomes)\b)[a-z]{3,}s\b")

#: The guard that makes the loose frame safe: it speaks only when its token is
#: the ONLY backticked thing in the sentence.  A token sitting among other
#: backticked tokens with no real skill among them is a member of some list of
#: that file's own -- the scanner's `plural` / `word-order-singular` probe
#: names, the `rlottie-python` / `python-lottie` renderers it rejected -- and
#: those get written about with verbs exactly like a skill's.  The narrow
#: AGENT_FRAME above is not subject to this: its verb list is its own evidence.
ANY_BACKTICKED = re.compile(r"`([^`\n]+)`")


def _loose_frame_applies(sent, roster):
    """Is the loose agent frame trustworthy in this sentence?"""
    spans = [m.group(1) for m in ANY_BACKTICKED.finditer(sent)]
    return len(spans) <= 1 or any(s in roster for s in spans)

#: Lines that route work with an arrow -- README's "figure images ->
#: pdf-figure-extractor" and the pipeline diagram.
ARROW_ROUTE = re.compile(r"(?:->|→|▶)\s*\**`?([a-z][a-z0-9]*(?:-[a-z0-9]+)+)")

#: A markdown table: a contiguous run of lines starting with `|`.
TABLE_LINE = re.compile(r"^[ \t]*\|.*$", re.M)

#: Text between two pipes on one line.
TABLE_CELL = re.compile(r"(?<=\|)([^|\n]*)(?=\|)")

#: A prose enumeration of skills.  Everything from the marker to the end of
#: the paragraph is one scope.
ENUM_SCOPE = re.compile(
    r"(?:Depended on by|Written by|Read by|Produced by|Consumed by)"
    r".*?(?=\n[ \t]*\n|\Z)", re.S)

#: How many skills a document claims the plugin has.  Only roster framings
#: count -- "all five skills", "Five skills cover ..." -- never a subset count
#: like "four skills fire on a PDF".
ROSTER_COUNT = re.compile(
    r"\b(?:all|these)\s+(%s)\s+skills\b"
    r"|\b(%s)\s+skills\s+cover\b"
    r"|\bplugin(?:'s)?\s+(%s)\s+skills\b"
    % (_COUNT_ALT, _COUNT_ALT, _COUNT_ALT), re.I)


_PLUGIN_FILES = None


def walk_plugin_files():
    """Yield (path, text) for every .md/.py that states plugin contract.

    `tests/` is excluded on purpose: it is the checker, not the contract.  A
    test that discusses a removed skill by name in a comment -- as this one
    does, right above -- is documenting history, not routing work to it.
    """
    global _PLUGIN_FILES
    if _PLUGIN_FILES is None:
        out = []
        for base, dirs, names in os.walk(ROOT):
            dirs[:] = sorted(d for d in dirs
                             if not d.startswith(".")
                             and d not in ("tests", "__pycache__"))
            for name in sorted(names):
                if not name.endswith(TEXT_EXT) or name.startswith("."):
                    continue
                path = os.path.join(base, name)
                try:
                    out.append((path, read(path)))
                except (UnicodeDecodeError, OSError) as exc:
                    UNREADABLE.append((path, "%s: %s" % (type(exc).__name__, exc)))
        _PLUGIN_FILES = out
    return iter(_PLUGIN_FILES)


#: Like SENT_SPLIT, but a bare newline does NOT end a sentence -- only a
#: sentence-ender or a blank line does.  Hard-wrapped prose (every script
#: docstring in this tree) puts the subject and the skill name it names on
#: different lines, and splitting per line hides the connection between them.
SOFT_SENT_SPLIT = re.compile(r"(?<=[.:;!?])\s+|\n[ \t]*\n")


def _soft_sentences(text):
    i = 0
    for m in SOFT_SENT_SPLIT.finditer(text):
        chunk = text[i:m.start()]
        if chunk.strip():
            yield i, chunk
        i = m.end()
    if text[i:].strip():
        yield i, text[i:]


def _is_skill_name_token(name, text, end, roster, tag_values):
    if name in roster or name in tag_values:
        return name in roster          # roster names are valid; tags are not
    # `<something>.md` is a file, not a skill -- including when the closing
    # backtick sits between the name and its extension (`feature-ml`.md`).
    if FILENAME_TAIL.match(text[end:end + 10].lstrip("`'\"")):
        return False
    return True


def _decorated(text, rx=DECORATED_SKILL):
    for m in rx.finditer(text):
        yield (m.group(1) or m.group(len(m.groups()))), m.start()


def _tables(text):
    """(block_text, block_offset) for each contiguous markdown table."""
    rows = [(m.start(), m.end()) for m in TABLE_LINE.finditer(text)]
    if not rows:
        return
    start, prev_end = rows[0][0], rows[0][1]
    for a, b in rows[1:]:
        if text[prev_end:a].strip():        # a blank/other line broke the run
            yield text[start:prev_end], start
            start = a
        prev_end = b
    yield text[start:prev_end], start


def _list_elements(scope):
    """Bare comma/`and`-separated elements of an enumeration.

    Parentheticals are stripped first ("wiki-builder (consumes -- ... and
    ...)"), so a qualifier cannot split its own element or contribute one.
    Only elements that are *exactly* a skill-shaped token are returned; a
    phrase is prose, not a list of skills.
    """
    flat = re.sub(r"\([^)]*\)", " ", scope)
    for part in re.split(r"[,;]|\band\b|\n", flat):
        tok = part.strip().strip("*`_ .").strip()
        if re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)+", tok):
            yield tok


def _roster_candidates(text, roster, tag_values):
    """(name, offset, why) for every token this file uses as a skill name."""
    out = []

    def keep(name, off, why, end=None):
        if not _is_skill_name_token(name, text, end if end is not None
                                    else off + len(name), roster, tag_values):
            return
        out.append((name, off, why))

    # (a) backticked, in a sentence about skills, in a routing frame, or
    #     beside a backticked real skill.  That last one is what catches the
    #     shape the sentence heuristic alone misses -- "the interface
    #     `wiki-builder` globs for, and the name `<gone>` writes" -- which is
    #     how three script docstrings kept naming a removed skill.
    #     The two signals get different scopes on purpose.  "This sentence is
    #     about skills" is weak evidence, so it is read per line -- widened, it
    #     swallows the sentence next door and reports every backticked slug
    #     (`c-plus-plus`) that happens to share a paragraph with the word.
    #     "This name sits beside a real skill name, both backticked" is strong
    #     evidence, so it may cross a hard wrap.
    for off, sent in _sentences(text):
        about = bool(re.search(r"\bskill", sent, re.I))
        loose_ok = _loose_frame_applies(sent, roster)
        for name, moff in _decorated(sent, BACKTICKED_SKILL):
            esc = re.escape(name)
            if (about
                    or re.search(SKILL_FRAME.pattern % (esc, esc), sent, re.I)
                    or re.search(AGENT_FRAME.pattern % (esc, esc), sent)
                    or (loose_ok
                        and re.search(LOOSE_AGENT_FRAME % esc, sent))):
                keep(name, off + moff + 1, "named as a skill in prose",
                     off + moff + 1 + len(name))

    for off, sent in _soft_sentences(text):
        names = list(_decorated(sent, BACKTICKED_SKILL))
        if not any(n in roster for n, _ in names):
            continue
        for name, moff in names:
            keep(name, off + moff + 1, "named beside a real skill",
                 off + moff + 1 + len(name))

    # (b) a table that names two or more real skills is a table of skills --
    #     including in its second column, where (a) cannot see it.
    for block, boff in _tables(text):
        decorated = list(_decorated(block))
        if sum(1 for n, _ in decorated if n in roster) < 2:
            continue
        for name, moff in decorated:
            keep(name, boff + moff + 1, "listed in a table of skills",
                 boff + moff + 1 + len(name))

    # (c) a fenced block with arrows and two or more real skills is a flow
    #     diagram, and every node in it is a stage.  The arrow requirement is
    #     what separates it from the vault-layout tree, whose comment text is
    #     prose ("read-only, kept forever") and full of hyphenated compounds.
    #     Parentheticals are blanked for the same reason: inside a diagram they
    #     are captions, not nodes ("(a book is split into per-chapter PDFs)").
    for m in FENCE_RE.finditer(text):
        block = m.group(1)
        if sum(1 for r in roster if r in block) < 2:
            continue
        if not any(a in block for a in ("->", "→", "▶")):
            continue
        nodes = re.sub(r"\([^)\n]*\)", lambda g: " " * len(g.group(0)), block)
        for sm in SKILL_SHAPED.finditer(nodes):
            keep(sm.group(1), m.start(1) + sm.start(),
                 "drawn into a pipeline diagram", m.start(1) + sm.end())

    # (d) a delimited list one of whose elements is a real skill.  This is the
    #     "Written by | Read by" column and the "Depended on by:" footer: every
    #     other element of such a list is a skill too, or it is fiction.
    scopes = [(c, coff) for block, boff in _tables(text)
              for c, coff in ((m.group(1), boff + m.start())
                              for m in TABLE_CELL.finditer(block))]
    scopes += [(m.group(0), m.start()) for m in ENUM_SCOPE.finditer(text)]
    for scope, soff in scopes:
        elements = list(_list_elements(scope))
        if not any(e in roster for e in elements):
            continue
        for name in elements:
            keep(name, soff + scope.index(name), "listed alongside real skills",
                 soff + scope.index(name) + len(name))

    # (e) an arrow routing work to a name -- "figure images -> some-skill".
    #     An arrow alone is not enough, and neither is a backticked
    #     destination: this tree writes slugs that way too (`Feature (machine
    #     learning)` -> `feature-machine-learning`), and prose uses an arrow
    #     for "becomes" ("no real ancestor -> self-parent").  The line has to
    #     be routing *between skills* -- two real ones on it, or one plus the
    #     word "skill" -- before its arrows mean dispatch.
    for m in re.finditer(r"^.*$", text, re.M):
        line = m.group(0)
        n_roster = sum(1 for r in roster if r in line)
        if n_roster < (1 if re.search(r"\bskill", line, re.I) else 2):
            continue
        for am in ARROW_ROUTE.finditer(line):
            keep(am.group(1), m.start() + am.start(1),
                 "routed to by an arrow", m.start() + am.end(1))

    return out


def check_skill_roster(rep, conv):
    check = "skill-roster"
    roster = set(skill_names())
    tag_values = set(canonical_block(conv, "tag-enum"))

    if not roster:
        rep.fail(check, "skills/ contains no skill directories -- the roster "
                        "this check reads is empty, which would make every "
                        "name below vacuously wrong")
        return
    rep.ok(check, "roster read from skills/: %s" % ", ".join(sorted(roster)),
           rel(SKILLS_DIR))

    external = Registry(rep, check, conv, "external-skills",
                        "the reference to a skill that does not ship here")

    # (a) no file names a skill that is not a directory under skills/.
    seen, checked = set(), 0
    for path, text in walk_plugin_files():
        r = rel(path)
        for name, off, why in _roster_candidates(text, roster, tag_values):
            checked += 1
            if name in roster or (r, name) in seen:
                continue
            seen.add((r, name))
            where = at(path, off, text)
            if external.claims(name):
                external.hit(name,
                             "%s uses `%s` as a skill (%s); nothing in this "
                             "plugin implements it" % (r, name, why), where)
            else:
                rep.fail(check,
                         "%s uses `%s` as a skill (%s), but skills/ holds only "
                         "%s. A name with no directory behind it routes work "
                         "nowhere: the contract is never enforced, never "
                         "fails, and the user gets silence. Either ship "
                         "skills/%s/, route to a skill that exists, or delete "
                         "the reference."
                         % (r, name, why, ", ".join(sorted(roster)), name),
                         where)
    rep.saw(check, "skill-name uses across the plugin", checked)
    if checked:
        rep.ok(check, "%d skill-name use(s) across the plugin, all resolving to "
                      "a directory under skills/" % checked)
    else:
        rep.fail(check, "no file in the plugin names a skill at all -- the "
                        "extractor is broken, which would make this check "
                        "silently vacuous")

    # (b) a document that counts the roster must count it correctly.
    #     Read plugin-wide, not just from README and CONVENTIONS: a SKILL.md
    #     that says "all five skills" goes stale in exactly the same way.
    counted = 0
    for path, text in walk_plugin_files():
        for m in ROSTER_COUNT.finditer(text):
            word = next(g for g in m.groups() if g).lower()
            counted += 1
            n = NUMBER_WORDS.get(word, int(word) if word.isdigit() else None)
            if n != len(roster):
                rep.fail(check,
                         "%s says the plugin has %s skills, but skills/ holds "
                         "%d (%s). A stale count is the readable half of a "
                         "stale roster."
                         % (rel(path), word, len(roster),
                            ", ".join(sorted(roster))), at(path, m.start(), text))
    rep.saw(check, "stated roster counts", counted)
    if counted:
        rep.ok(check, "%d stated roster count(s) agree with skills/ (%d skills)"
               % (counted, len(roster)))

    external.finish()


# ===========================================================================
# check 7 -- bundled paths resolve, and every reference is reachable
# ===========================================================================

PATH_REF = re.compile(r"`?((?:[a-z0-9-]+/)?(?:references|scripts)/[a-z0-9_.-]+\.(?:md|py))`?")

#: Everything else a file can point at inside the plugin: `skills/…`,
#: `shared/…`, `<skill>/SKILL.md`, and any bundled file whose name is not
#: lowercase.  `PATH_REF` alone only sees a `references/` or `scripts/`
#: component made of lowercase characters, so `skills/wiki-linter/RULEBOOK.md`
#: -- a pointer at a file that does not exist -- was simply not a path to it.
PLUGIN_PATH_REF = re.compile(
    r"`((?:skills|shared|tests)/[A-Za-z0-9_./-]+\.(?:md|py)|"
    r"[a-z0-9-]+/[A-Za-z][A-Za-z0-9_.-]*\.(?:md|py))`")

#: Boundaries of the sentence a token sits in.
SENT_BOUND = re.compile(r"[.!?;]\s|\n\s*\n")


def _enclosing_sentence(text, start, end):
    # Bounded on both sides: scanning back to offset 0 for every token made
    # this quadratic in file size, and a "sentence" 2000 characters long is
    # not a scope anyone reading the file would recognise anyway.
    a = max(0, start - 600)
    for m in SENT_BOUND.finditer(text, a, start):
        a = m.end()
    m = SENT_BOUND.search(text, end)
    return text[a:m.start() if m else min(len(text), end + 200)]


def _absent_paths(conv):
    """``{(file, token)}`` registered in `canonical:absent-paths` (§10c).

    A pointer at a file that does not ship is sometimes right --
    `lottie-recovery.md` explains why its Lottie converter is
    written to a temp file at runtime instead of shipping as `scripts/…`, and
    reporting that as a broken pointer would report the fix as the bug.

    It used to be enough for the *sentence* to sound like that explanation:
    any of `no longer`, `used to ship`, `does not exist` and six more phrases,
    anywhere in the sentence, turned a broken pointer into two passes.  That is
    an exemption anyone can write by accident, it is invisible without `-v`,
    and it grows.  The exemption now has to be written down in CONVENTIONS.md,
    one line per (file, token) pair, where it is countable and reviewable --
    and a line that stops matching is reported as stale, so the list can only
    shrink.  The prose explanation is still required of the file; it is just no
    longer what the harness takes as authority.
    """
    out = set()
    for line in canonical_block(conv, "absent-paths", required=False):
        if "::" in line:
            f, tok = (p.strip() for p in line.split("::", 1))
            out.add((f, tok))
    return out


def _resolve_ref(skill, token, nearby_skills=()):
    """Candidate on-disk locations for a `references/…` or `scripts/…` token."""
    cands = [os.path.join(SKILLS_DIR, skill, token)]
    segs = token.split("/")
    if len(segs) == 3 or (len(segs) >= 2 and segs[0] in skill_names()):
        cands.append(os.path.join(SKILLS_DIR, token))   # <skill>/SKILL.md
    cands.append(os.path.join(ROOT, token))   # shared/scripts/x.py
    # A bare `references/x.md` naming its owning skill in the same breath --
    # "`references/pdf-path.md` in that skill", "wiki-builder references/media.md"
    # -- resolves against that skill.  Only skills named nearby are tried, so
    # this does not degrade into "exists anywhere".
    for other in nearby_skills:
        cands.append(os.path.join(SKILLS_DIR, other, token))
    return cands


def check_reference_paths(rep, conv):
    check = "reference-paths"
    pending = Registry(rep, check, conv, "pending-skill-edits",
                       "the stale slugify.py path")
    absent, absent_used = _absent_paths(conv), set()
    claimed = {}
    for line in pending.keys:
        if "::" in line:
            f, tok = (p.strip() for p in line.split("::", 1))
            claimed[(f, tok)] = line
    all_skills = skill_names()

    # (a) every referenced path exists.
    n_tokens, n_borrowed = 0, [0]
    for skill, path, text in walk_skill_files():
        tokens = [(m.group(1), m.start(), m.end()) for m in PATH_REF.finditer(text)]
        tokens += [(m.group(1), m.start(1), m.end(1))
                   for m in PLUGIN_PATH_REF.finditer(text)]
        for token, tstart, tend in sorted(set(tokens)):
            if "<" in token or ">" in token:
                continue                      # a shape, not a pointer
            n_tokens += 1
            # Both the "deliberately absent" cue and the "resolve against the
            # skill named beside it" rescue are scoped to the token's own
            # sentence.  At the +/-220 characters they used, either could be
            # supplied by the sentence next door: any broken pointer within
            # 220 characters of the words "no longer" was reported as a PASS,
            # and any bare `references/x.md` within 220 characters of another
            # skill's name resolved into that skill's directory.
            sent = _enclosing_sentence(text, tstart, tend)
            nearby = [s for s in all_skills if s in sent and s != skill]
            hit = next((c for c in _resolve_ref(skill, token, nearby)
                        if os.path.isfile(c)), None)
            if hit:
                owner = os.path.dirname(os.path.relpath(hit, SKILLS_DIR)).split("/")[0]
                if (token.count("/") == 1 and nearby and owner in nearby
                        and owner != skill):
                    # A bare `references/x.md` that only resolves because
                    # another skill was named beside it.  Legitimate here, but
                    # never silent: an unqualified cross-skill pointer is a
                    # judgement call, and the report has to show it was made.
                    n_borrowed[0] += 1
                    rep.ok(check,
                           "%s points at the bare `%s`, which exists only "
                           "under `%s` -- resolved through that name in the "
                           "same sentence. Qualify it (`%s/%s`) if it is meant "
                           "to be that skill's file."
                           % (rel(path), token, owner, owner, token),
                           at(path, tstart, text))
                continue
            where = at(path, tstart, text)
            r = rel(path)
            if (r, token) in absent:
                absent_used.add((r, token))
                rep.ok(check, "%s names `%s`, which CONVENTIONS.md §10c "
                              "registers as deliberately not shipped"
                       % (r, token), where)
                continue
            key = claimed.get((r, token))
            if key:
                pending.hit(key,
                            "%s points at `%s`, which no longer exists -- the "
                            "file moved to shared/scripts/ and this reference "
                            "was not updated with it" % (r, token), where)
            else:
                rep.fail(check,
                         "%s points at `%s`, which does not exist under "
                         "skills/%s/, under a skill named in the same "
                         "sentence, or at the plugin root. A pointer at a "
                         "missing file is read as an instruction to consult "
                         "rules that are not there. If the file is deliberately "
                         "not shipped, say so in the text AND register the pair "
                         "`%s :: %s` in CONVENTIONS.md §10c -- prose alone no "
                         "longer exempts a pointer."
                         % (r, token, skill, r, token), where)
    for f, tok in sorted(absent - absent_used):
        rep.fail(check,
                 "CONVENTIONS.md §10c registers `%s :: %s` as deliberately "
                 "absent, but %s no longer names that path. DELETE the line: an "
                 "exemption that matches nothing is a standing licence for the "
                 "next broken pointer at that name." % (f, tok, f),
                 rel(CONVENTIONS))
    # No `saw` for the §10c population: an empty registry is the intended
    # steady state, and `vacuity()` turns an empty population into a FAIL.
    rep.saw(check, "path references resolved", n_tokens)
    if n_tokens:
        rep.ok(check, "%d bundled-path reference(s) resolve on disk" % n_tokens)

    # (b) every reference file is reachable from its own SKILL.md.
    for skill in skill_names():
        refdir = os.path.join(SKILLS_DIR, skill, "references")
        skillmd = os.path.join(SKILLS_DIR, skill, "SKILL.md")
        if not os.path.isdir(refdir):
            continue
        if not os.path.isfile(skillmd):
            rep.fail(check, "skills/%s/ has references/ but no SKILL.md" % skill)
            continue
        text = read(skillmd)
        for name in sorted(os.listdir(refdir)):
            if not name.endswith(".md"):
                continue
            if ("references/" + name) in text:
                rep.ok(check, "skills/%s/references/%s is reachable from SKILL.md"
                       % (skill, name))
            else:
                rep.fail(check,
                         "skills/%s/references/%s is never named in SKILL.md. A "
                         "reference file with no trigger condition is never "
                         "read, so its rules are done from memory instead."
                         % (skill, name), rel(skillmd))

    # (c) the shared layer's own files exist.
    for p in (CONVENTIONS, SLUGIFY, PLUGIN_PATHS):
        if os.path.isfile(p):
            rep.ok(check, "%s present" % rel(p))
        else:
            rep.fail(check, "%s is missing" % rel(p))

    pending.finish()


# ===========================================================================
# check 7 -- the shared-layer bootstrap is copied verbatim
# ===========================================================================

def check_scripts_run(rep, conv):
    """Every bundled script parses and imports.

    CONVENTIONS.md §10a records the exact regression this catches: two
    wiki-builder scripts did `sys.path.insert(...)` then
    `from slugify import …`, and after the module moved to `shared/scripts/`
    **both scripts failed at import**.  Every text-level check in this file
    passed the whole time -- the files said all the right things; they just
    could not run.  A skill whose bundled script dies on import degrades to
    the model doing the work from memory, which is the failure the scripts
    exist to prevent.
    """
    check = "scripts-run"
    n = n_clean = 0
    for path, text in walk_python_sources():
        n += 1
        r = rel(path)
        try:
            compile(text, path, "exec")
        except SyntaxError as exc:
            rep.fail(check, "%s does not parse: %s (line %s). A bundled script "
                            "that cannot be compiled cannot be run."
                     % (r, exc.msg, exc.lineno), "%s:%s" % (r, exc.lineno or 1))
            continue
        # Imported in a separate, time-limited process (see `probe_module`),
        # and only after the static import-time gate has cleared it.  Running
        # it in a fresh interpreter is also the more faithful test: a fresh
        # interpreter is what the skill actually gets.
        res = probe_module(path)
        if res["refused"]:
            rep.fail(check,
                     "%s %s" % (r, probe_failure(res, r)),
                     "%s:%d" % (r, res["refused"][0][0]))
        elif res["timeout"] or res["import_error"] or res["crash"]:
            rep.fail(check,
                     "%s %s. The skill that bundles it will fall back to doing "
                     "the work from memory, silently -- CONVENTIONS.md §10a "
                     "records two scripts that broke exactly this way when a "
                     "module moved." % (r, probe_failure(res, r)), r)
        else:
            n_clean += 1
            rep.ok(check, "%s compiles, imports with no import-time effects, "
                          "and was probed in a separate process" % r, r)
    rep.saw(check, "bundled python scripts", n)
    # A gate that clears nothing is a gate that proves nothing: if every module
    # were refused, every `scripts-run` result would be a FAIL and the
    # import-time-effects gate would never have been exercised on a real
    # import.  Non-zero here is what says the two fences still let the healthy
    # tree through.
    rep.saw(check, "scripts cleared by the import-time gate and imported",
            n_clean)


# ===========================================================================
# check 6b -- documented script surface: the script exists, the flag exists
# ===========================================================================
#
# `contract-name-resolution` reads names and nothing else.  This is the one
# behavioural claim in the tree that can be checked exactly rather than
# approximately: a file that writes `scripts/foo.py --bar` is documenting a
# capability, and both halves of it are decidable -- the script is bundled or
# it is not, and `--bar` is in that script's parser or it is not.  A flag that
# is not is the same failure as a skill that does not exist: the model copies
# the template it is shown, the run dies with `unrecognized arguments`, and the
# skill falls back to doing the work from memory.
#
# Deliberately NOT a claim about what the flag does.  Nothing here reads
# behaviour; a check that pretended to would be the thing this file just
# finished renaming.

#: A script named in prose or in a command line: `scripts/foo.py`, with or
#: without a skill directory or `<skill>/` placeholder in front of it.
SCRIPT_MENTION = re.compile(r"((?:[A-Za-z0-9_<>.-]+/)*scripts/([a-z0-9_]+\.py))")
#: A leading `<vault>/`, `<skill>/` placeholder segment -- the ordinary way
#: this tree writes a command line, and not a sign that the path is a shape.
LEADING_PLACEHOLDER = re.compile(r"^<[^>]*>/")
#: A long flag as it is written on a command line or in prose.  Short flags are
#: not read: `-o` is also a bullet, a minus sign and half of `-o-`.
LONG_FLAG = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]*)")
#: Flags that belong to the *interpreter* or to another program on the same
#: line, not to the bundled script.
NOT_SCRIPT_FLAGS = frozenset(("--help", "--version"))


def _parser_surface(text):
    """``(long flags, subcommands)`` a script's argparse actually defines."""
    flags, subs = set(), set()
    tree = _parsed(text)
    if tree is None:
        return flags, subs
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = (_dotted(node.func) or "").split(".")[-1]
        args = [a.value for a in node.args
                if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        if name == "add_argument":
            flags |= {a for a in args if a.startswith("--")}
        elif name == "add_parser":
            subs |= set(args[:1])
        # `dest=`/`metavar=` are not surface; only what a user types is.
    return flags, subs


_BARE_SCRIPT_CACHE = {}


def _bare_script_re(scripts):
    """A compiled alternation over the bundled script BASENAMES.

    The lookbehind keeps a path mention (`scripts/foo.py`, already matched by
    SCRIPT_MENTION) and a dotted or templated token from matching twice or
    half-matching; the caller dedupes the union anyway.
    """
    key = tuple(sorted(scripts))
    if key not in _BARE_SCRIPT_CACHE:
        _BARE_SCRIPT_CACHE[key] = re.compile(
            r"(?<![A-Za-z0-9_/<.-])(%s)" % "|".join(re.escape(b) for b in key))
    return _BARE_SCRIPT_CACHE[key]


def check_script_surface(rep, conv):
    """Every documented `scripts/x.py --flag` exists and parses.

    Two populations, both plugin-wide: the scripts named in prose, and the
    long flags written against them.  A name that resolves to no bundled script
    is a pointer at nothing (`reference-paths` says so too, for the paths it can
    see); a flag that the script's own parser does not define is a command line
    that dies on first use, and it is written in exactly the place a reader
    copies from.
    """
    check = "script-surface"
    scripts = {os.path.basename(p): p for p in bundled_scripts()}
    absent = _absent_paths(conv)
    surface = {}
    for base, path in scripts.items():
        try:
            surface[base] = _parser_surface(read(path))
        except (UnicodeDecodeError, OSError):
            surface[base] = (set(), set())

    n_mentions = n_flags = 0
    seen = set()
    for path, text in walk_plugin_files():
        in_block = canonical_block_lines(text)
        for i, line in enumerate(text.split("\n"), 1):
            if i in in_block:
                continue
            named = []
            for m in SCRIPT_MENTION.finditer(line):
                token = LEADING_PLACEHOLDER.sub("", m.group(1))
                if "<" in token or ">" in token:
                    continue      # `skills/<skill>/scripts/x.py` is a shape
                if (rel(path), "scripts/" + m.group(2)) in absent:
                    continue      # registered in CONVENTIONS.md §10c
                named.append(m.group(2))
            # Bare-basename mentions -- `vault_index.py --compact`,
            # `paper_scan.py --test` -- the ordinary way running text names a
            # script it has already introduced.  Restricted to the bundled
            # basenames (an unknown bare `x.py` is prose, not a pointer), and
            # fed through the same flag check below: a wrong flag beside a
            # bare name dies exactly as dead as beside a full path.
            # vault_index.py's own usage line documented `--pretty`, which its
            # parser never defined, and the path-anchored corpus above could
            # not see it -- the suite was green while the documented command
            # exited 2.
            for m in _bare_script_re(scripts).finditer(line):
                if (rel(path), "scripts/" + m.group(1)) not in absent:
                    named.append(m.group(1))
            named = list(dict.fromkeys(named))
            if not named:
                continue
            n_mentions += len(named)
            for base in [b for b in named if b not in scripts]:
                if (rel(path), base) in seen:
                    continue
                seen.add((rel(path), base))
                rep.fail(check,
                         "%s documents `scripts/%s`, which is not a bundled "
                         "script (skills/*/scripts/ and shared/scripts/ hold "
                         "%d others). A documented command line naming a file "
                         "that is not there is read as an instruction to run "
                         "it, and the run dies. If it is deliberately not "
                         "shipped, register it in CONVENTIONS.md §10c."
                         % (rel(path), base, len(scripts)), at(path, i))
            known = [b for b in named if b in scripts]
            if not known:
                continue
            allowed = set().union(*[surface[b][0] for b in known])
            for m in LONG_FLAG.finditer(line):
                flag = m.group(1)
                if flag in NOT_SCRIPT_FLAGS or flag in allowed:
                    n_flags += 1
                    continue
                # A flag written *before* the script name on the line belongs
                # to whatever runs it (`python3 -X faulthandler …`).
                if m.start() < min(line.index(b) for b in known):
                    continue
                n_flags += 1
                rep.fail(check,
                         "%s documents `%s` for %s, whose parser defines no "
                         "such flag (it defines %s). The model copies the "
                         "template it is shown: this line produces "
                         "`unrecognized arguments: %s` on first use, and the "
                         "skill falls back to doing the work from memory."
                         % (rel(path), flag, " / ".join(sorted(known)),
                            ", ".join(sorted(allowed)) or "none", flag),
                         at(path, i))
    rep.saw(check, "bundled scripts named in documentation", n_mentions)
    rep.saw(check, "long flags documented against a bundled script", n_flags)
    rep.ok(check, "%d documented script mention(s) and %d flag(s) resolve to a "
                  "bundled script and its own parser"
           % (n_mentions, n_flags), rel(SKILLS_DIR))


#: Seconds one bundled script's self-test may take before it is killed and
#: FAILED.  Four times `PROBE_TIMEOUT`: a probe only imports, whereas these
#: suites build temporary vaults, render pages and shell out.  A suite killed
#: for being slow is indistinguishable in the report from a suite that fails,
#: so the number has to sit well clear of the slowest one in the tree.
SELFTEST_TIMEOUT = 240

#: The self-test function itself: `run_self_test`, `_selftest`, `run_selftest`.
SELFTEST_FUNC = re.compile(r"^def\s+(_?(?:run_)?self_?tests?\w*)\s*\(", re.M)

#: The two entry points in use: a `--test` flag (eighteen scripts) and a
#: `selftest` subcommand (`organize.py`, `fetch_images.py`, whose CLIs are
#: subcommand-shaped already).  Both are accepted; having none is the failure.
SELFTEST_FLAG = re.compile(r"""add_argument\(\s*["']--test["']""")
SELFTEST_SUB = re.compile(r"""add_parser\(\s*["']selftest["']""")

#: The tally a suite prints: `69/69 self-test cases pass`, `109/109 self-tests
#: passed`, `128/128`.  Anchored at both ends of a line so a stray `1/2` inside
#: a sentence of prose cannot be mistaken for a result.
SELFTEST_TALLY = re.compile(
    r"^[^\S\n]*(\d+)[^\S\n]*/[^\S\n]*(\d+)(?![\d/])[^\n]*$", re.M)

#: Per-script case-count FLOORS -- exactly like :data:`SLUG_SELFTEST_MIN` and
#: :data:`NAMING_SELFTEST_MIN`, and for the same reason, extended to every
#: bundled suite.  `passed == total` is satisfied just as well by a suite whose
#: cases were deleted alongside the bug they caught, and nothing else in this
#: file looks at the size of a suite.  Coverage may grow freely: only a shrink
#: fails.  Lowering a number here is a deliberate, reviewable statement that
#: cases went away; a script with no line is checked for a clean tally only.
SELFTEST_MIN_CASES = {
    # Re-tuned to the exact tallies of 2026-08-31. Raising after growth is the
    # mirror duty of the "lowering is a deliberate, reviewable statement" rule
    # below: new regression cases must not disappear with the harness green.
    "shared/scripts/figure_state.py": 6,
    "shared/scripts/naming.py": 191,
    "shared/scripts/plugin_paths.py": 95,
    "shared/scripts/plurals.py": 200,
    "shared/scripts/slugify.py": 61,
    "shared/scripts/yaml_scalars.py": 8,
    "skills/clipping-processor/scripts/dedup_index.py": 113,
    "skills/clipping-processor/scripts/fetch_images.py": 293,
    "skills/clipping-processor/scripts/slug.py": 120,
    "skills/paper-summarizer/scripts/note_lint.py": 190,
    "skills/paper-summarizer/scripts/paper_scan.py": 118,
    "skills/paper-summarizer/scripts/paper_text.py": 39,
    "skills/pdf-figure-extractor/scripts/auto_fig_bbox.py": 296,
    "skills/pdf-figure-extractor/scripts/batch_extract.py": 235,
    "skills/pdf-figure-extractor/scripts/extract_figures.py": 108,
    "skills/pdf-figure-extractor/scripts/render_page.py": 38,
    "skills/pdf-organizer/scripts/organize.py": 212,
    "skills/wiki-builder/scripts/find_collisions.py": 62,
    "skills/wiki-builder/scripts/lint_entry.py": 164,
    "skills/wiki-builder/scripts/vault_index.py": 63,
    "skills/wiki-linter/scripts/scan_vault.py": 202,
}


def bundled_scripts():
    """Every .py the plugin ships under `skills/*/scripts/` and `shared/scripts/`.

    Deliberately not `walk_python_sources`: that one skips `slugify.py` -- the
    canonical module the slug checks import by hand -- and reaches every .py
    anywhere under `skills/`.  This rule is about the executable surface the
    skills actually invoke, and `slugify.py` is emphatically part of it.
    """
    roots = [os.path.join(SKILLS_DIR, s, "scripts") for s in skill_names()]
    roots.append(os.path.join(SHARED_DIR, "scripts"))
    out = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for base, dirs, names in os.walk(root):
            dirs[:] = sorted(d for d in dirs
                             if not d.startswith(".") and d != "__pycache__")
            out += [os.path.join(base, n) for n in sorted(names)
                    if n.endswith(".py") and not n.startswith(".")]
    return sorted(out)


def _selftest_tallies(out):
    """Every ``N/M`` line the run printed: ``[(passed, total, line)]``."""
    return [(int(m.group(1)), int(m.group(2)), " ".join(m.group(0).split()))
            for m in SELFTEST_TALLY.finditer(out)]


def _tally_is_last_line(out):
    """Is the final ``N/M`` line also the last thing the run printed?

    A suite that reports its tally and then keeps going has not reported its
    result: whatever follows the tally is outside the count.  Every suite in
    the tree ends on its tally today (`slugify.py`'s JSON aside), so this costs
    nothing and closes the "tally, then the real failures" shape.
    """
    tallies = _selftest_tallies(out)
    if not tallies:
        return True
    lines = [ln for ln in out.splitlines() if ln.strip()]
    return bool(lines) and " ".join(lines[-1].split()) == tallies[-1][2]


def _selftest_tally(out):
    """``(passed, total)`` as the suite reported it, or ``None`` if it did not.

    Two shapes exist in the tree and both are accepted, because what has to be
    proved is that the suite ran every case it has and none failed -- not how
    it spells that.  Most scripts end on a tally line; `slugify.py --test`
    prints the `run_self_test()` dict as JSON instead, which carries the same
    two numbers.  A run that reports NEITHER is a failure even at exit 0: an
    exit code alone cannot tell "63 cases passed" from "the suite returned
    before running anything".

    The tally returned is the **worst** ``N/M`` line the run printed, not the
    last one.  Reading the last one meant a suite could fail every case it has,
    exit 0, print `0/3 self-test cases pass` and then print `3/3 fixtures
    cleaned up` -- and this check reported "ran 3/3 cases, all passing".  A
    trailing tally is not allowed to overwrite a failing one.
    """
    tallies = _selftest_tallies(out)
    if tallies:
        return min(((p, t) for p, t, _ in tallies),
                   key=lambda pt: (pt[0] - pt[1], pt[1] and pt[0] / pt[1], -pt[1]))
    body = out.strip()
    if body.startswith("{") and body.endswith("}"):
        try:
            data = json.loads(body)
        except ValueError:
            return None
        if isinstance(data, dict) and "passed" in data and "total" in data:
            try:
                return int(data["passed"]), int(data["total"])
            except (TypeError, ValueError):
                return None
    return None


def _run_selftest(path, argv):
    """Run one suite in a process of its own.  ``(rc, output, timed_out)``."""
    try:
        proc = subprocess.run(
            [sys.executable, os.path.abspath(path)] + argv,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=SELFTEST_TIMEOUT, cwd=ROOT,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    except subprocess.TimeoutExpired as exc:
        return None, (exc.output or b"").decode("utf-8", "replace"), True
    return proc.returncode, proc.stdout.decode("utf-8", "replace"), False


def _quote_output(out, n=12):
    """The tail of a suite's own output, indented into the report.

    Its own words, not a paraphrase: the suite already knows which case broke
    and says so, and a report that swallows that leaves the reader to re-run
    the thing by hand to find out what this check actually saw.
    """
    lines = [ln.rstrip() for ln in out.splitlines() if ln.strip()]
    if not lines:
        return "         | (the script printed nothing at all)"
    shown = lines[-n:]
    head = ("         | ... %d earlier line(s) omitted\n" % (len(lines) - len(shown))
            if len(shown) < len(lines) else "")
    return head + "\n".join("         | " + ln for ln in shown)


def check_self_test(rep, conv):
    """Every bundled script carries a self-test, and it passes RIGHT NOW.

    Two regressions, and the second is the one that bites.

    The first is a gap: `shared/scripts/plugin_paths.py` shipped as the only
    module in `shared/scripts/` with no self-test, next to three siblings that
    had one.  Two real bugs sat in it the whole time -- `describe()` reported a
    `plugin_root` that `plugin_root()` itself refused, and an
    `$OBSIDIAN_VAULT_SHARED` pointing at a directory without the modules in it
    resolved happily and then died with the bare `ModuleNotFoundError` that
    module's own docstring exists to prevent.  Nothing in this file noticed,
    because nothing in this file asked whether a script HAD a suite.

    The second is worse, and is why this check runs the suites instead of
    grepping for them: a suite that exists and fails is worse than no suite,
    because the tree now looks tested.  `slug-single-impl` and
    `source-filename` call `run_self_test()` on exactly two modules,
    in-process; every other suite in the tree was dead text as far as this
    harness was concerned.  A suite can rot -- its module changes underneath
    it and it starts failing -- and until something runs it on every commit,
    the failure is a file nobody opens.

    So: the entry point is found statically, then invoked out of process, and
    the run has to end at exit 0 having reported a complete, all-passing tally
    of at least :data:`SELFTEST_MIN_CASES` cases.

    The four pdf-figure-extractor suites REQUIRE PyMuPDF: without it they exit
    non-zero before running a case, and this check FAILs them for it. That is
    the honest report -- they are not testing anything in that environment --
    but it does mean this harness needs the imaging libraries installed, and
    that the floors below were taken in an environment that had them.
    """
    check = "self-test"
    n = n_ran = 0
    floors_used = set()
    for path in bundled_scripts():
        n += 1
        r = rel(path)
        try:
            text = read(path)
        except (UnicodeDecodeError, OSError) as exc:
            rep.fail(check, "%s cannot be read (%s), so its self-test cannot "
                            "be found or run" % (r, exc), r)
            continue

        fn = SELFTEST_FUNC.search(text)
        flag, sub = SELFTEST_FLAG.search(text), SELFTEST_SUB.search(text)
        if not fn:
            rep.fail(check,
                     "%s defines no self-test function. Every other bundled "
                     "script has a `run_self_test()` holding its worked "
                     "examples; a script without one is a script whose "
                     "behaviour is asserted nowhere, and the model falls back "
                     "to doing the work from memory the day it drifts." % r, r)
        if not (flag or sub):
            rep.fail(check,
                     "%s exposes no self-test entry point: no `--test` flag and "
                     "no `selftest` subcommand. Whatever cases it holds cannot "
                     "be run by anyone -- not by this harness, not by a user "
                     "checking an install -- so they cannot fail, which is the "
                     "same as not having them." % r, r)
            continue
        if not fn:
            continue

        argv = ["--test"] if flag else ["selftest"]
        rc, out, timed_out = _run_selftest(path, argv)
        spelled = " ".join([os.path.basename(path)] + argv)
        if timed_out:
            rep.fail(check,
                     "%s: `%s` did not finish within %ds and was killed, so the "
                     "suite proves nothing. A self-test that cannot be run on "
                     "every commit is a self-test nobody runs.\n%s"
                     % (r, spelled, SELFTEST_TIMEOUT, _quote_output(out)), r)
            continue

        tally = _selftest_tally(out)
        if rc != 0:
            rep.fail(check,
                     "%s: `%s` exited %s -- its own self-test FAILS. This is "
                     "worse than having none: the tree reads as tested. Its "
                     "output:\n%s" % (r, spelled, rc, _quote_output(out)), r)
        elif tally is None:
            rep.fail(check,
                     "%s: `%s` exited 0 but reported no tally, so nothing here "
                     "distinguishes a suite that ran every case from one that "
                     "returned before running any. End it with a `N/M "
                     "self-test cases pass` line (or the `run_self_test()` "
                     "dict as JSON). Its output:\n%s"
                     % (r, spelled, _quote_output(out)), r)
        elif tally[1] == 0:
            rep.fail(check,
                     "%s: `%s` reported 0/0 -- an empty suite passing "
                     "vacuously. It has an entry point and no cases behind it."
                     % (r, spelled), r)
        elif tally[0] != tally[1]:
            rep.fail(check,
                     "%s: `%s` reported %d/%d -- %d case(s) FAILED while the "
                     "process still exited 0, which is the one shape that hides "
                     "from a CI job. Its output:\n%s"
                     % (r, spelled, tally[0], tally[1], tally[1] - tally[0],
                        _quote_output(out)), r)
        elif not _tally_is_last_line(out):
            rep.fail(check,
                     "%s: `%s` printed its %d/%d tally and then kept going, so "
                     "the tally does not cover the whole run. End the suite on "
                     "its tally: a result line with output after it is a result "
                     "line that can be contradicted by what follows. Its "
                     "output:\n%s"
                     % (r, spelled, tally[0], tally[1], _quote_output(out)), r)
        elif tally[1] < SELFTEST_MIN_CASES.get(r, 0):
            floors_used |= {r} & set(SELFTEST_MIN_CASES)
            rep.fail(check,
                     "%s: `%s` ran %d cases; the floor in tests/"
                     "test_conventions.py is %d. Coverage may grow, it may not "
                     "shrink: a suite that still reports every case passing "
                     "after its cases were deleted is the same green as one "
                     "that never had them. If the cases really are gone on "
                     "purpose, lower SELFTEST_MIN_CASES[%r] in the same commit."
                     % (r, spelled, tally[1], SELFTEST_MIN_CASES[r], r), r)
        else:
            n_ran += 1
            floors_used |= {r} & set(SELFTEST_MIN_CASES)
            rep.ok(check, "%s: `%s` ran %d/%d cases, all passing (floor %s)"
                   % (r, spelled, tally[0], tally[1],
                      SELFTEST_MIN_CASES.get(r, "-")), r)

    # A floor naming a script that never reported a tally in this run is an
    # exemption nobody is watching: it stops guarding the moment the path
    # changes, and reads as coverage until someone opens this file.
    for r in sorted(set(SELFTEST_MIN_CASES) - floors_used):
        rep.fail(check,
                 "SELFTEST_MIN_CASES names %s, which is not a bundled script "
                 "that reported a tally in this run. Either the script moved "
                 "(fix the key), or it is gone (delete the line), or its suite "
                 "is failing above -- a floor over nothing guards nothing." % r)

    # Both populations, for the same reason `scripts-run` reports two: the
    # first says the glob still matches the tree, the second says the suites
    # were really executed.  If a rename moved every script out from under
    # `skills/*/scripts/`, the first goes to zero and `vacuity()` FAILS the
    # check instead of reporting a clean sweep of nothing.
    rep.saw(check, "bundled scripts required to carry a self-test", n)
    rep.saw(check, "self-test suites run out of process and passing", n_ran)
    rep.saw(check, "self-test suites held to a case-count floor",
            len(floors_used))


def _first_diff_line(a, b):
    """The first line of ``a`` that ``b`` does not have in the same place."""
    la, lb = a.splitlines(), b.splitlines()
    for i, ln in enumerate(la):
        if i >= len(lb) or lb[i] != ln:
            return ln
    return "<%d extra line(s) in the other>" % (len(lb) - len(la))


def check_bootstrap(rep, conv):
    check = "shared-bootstrap"
    if not os.path.isfile(PLUGIN_PATHS):
        rep.fail(check, "shared/scripts/plugin_paths.py is missing")
        return
    pp = _load_module(PLUGIN_PATHS, "_shared_plugin_paths")
    canonical = pp.BOOTSTRAP
    marker = "obsidian shared-layer bootstrap"

    # It must also be what CONVENTIONS.md §5 shows the reader -- byte for
    # byte.  Asserting that two landmark strings are *present somewhere* in an
    # nine-hundred-line file is not that: the walk-up depth could go from 5 to 2, or
    # the two sys.path inserts could swap order, and both landmarks would
    # still be there.  §5's whole claim is that the snippet is safe to paste.
    fences = [m.group(1) for m in re.finditer(r"```python\n(.*?)```", conv, re.S)
              if marker in m.group(1)]
    if not fences:
        rep.fail(check, "CONVENTIONS.md §5 no longer shows a python block "
                        "containing the bootstrap -- readers have nothing to "
                        "paste, and this check has nothing to compare",
                 rel(CONVENTIONS))
    for fence in fences:
        if fence == canonical:
            rep.ok(check, "CONVENTIONS.md §5 shows plugin_paths.BOOTSTRAP "
                          "byte-for-byte", rel(CONVENTIONS))
        else:
            rep.fail(check,
                     "CONVENTIONS.md §5's snippet is NOT byte-identical to "
                     "plugin_paths.BOOTSTRAP; readers paste the stale one and "
                     "the test then demands the other. First difference:\n"
                     "         §5 %r\n         BOOTSTRAP %r"
                     % (_first_diff_line(fence, canonical),
                        _first_diff_line(canonical, fence)), rel(CONVENTIONS))

    # Any copy in a skill must be byte-identical.
    found = 0
    for skill, path, text in walk_skill_files():
        if marker not in text:
            continue
        found += 1
        start = text.index("# --- " + marker)
        end = text.find("# --- end bootstrap ---", start)
        if end == -1:
            rep.fail(check, "%s opens a shared-layer bootstrap but never closes "
                            "it with `# --- end bootstrap ---`" % rel(path),
                     at(path, start, text))
            continue
        block = text[start:end + len("# --- end bootstrap ---\n")]
        if block == canonical:
            rep.ok(check, "%s carries the canonical bootstrap verbatim" % rel(path),
                   at(path, start, text))
        else:
            rep.fail(check,
                     "%s carries a MODIFIED shared-layer bootstrap. It must be "
                     "byte-identical to plugin_paths.BOOTSTRAP "
                     "(`python3 shared/scripts/plugin_paths.py --bootstrap`); a "
                     "hand-tuned copy is how the walk-up depth or the sys.path "
                     "order silently diverges between skills."
                     % rel(path), at(path, start, text))
    rep.saw(check, "skill scripts carrying the bootstrap", found)

    # Which scripts *must* carry it is derived, not listed: any skill script
    # that imports a module living in shared/scripts/ depends on the snippet
    # having put that directory on sys.path.  Without this the check was
    # vacuous in the worst way -- delete the two marker comments from all
    # three scripts and it reported "no skill script has adopted the
    # bootstrap yet" and passed, while CONVENTIONS.md §10a records that these
    # exact scripts once died at import for exactly this reason.
    shared_modules = {os.path.basename(n)[:-3]
                      for n in os.listdir(os.path.join(SHARED_DIR, "scripts"))
                      if n.endswith(".py")}
    n_importers = 0
    for path, text in walk_python_sources():
        if not path.startswith(SKILLS_DIR):
            continue
        needs = sorted(m for m in shared_modules
                       if re.search(r"^\s*(?:import %s\b|from %s import)"
                                    % (re.escape(m), re.escape(m)), text, re.M))
        if not needs:
            continue
        n_importers += 1
        if marker in text:
            rep.ok(check, "%s imports %s from shared/scripts/ and carries the "
                          "bootstrap" % (rel(path), ", ".join(needs)), rel(path))
        else:
            rep.fail(check,
                     "%s does `import %s` -- a module that lives in "
                     "shared/scripts/ -- but carries no §5 bootstrap. Nothing "
                     "puts shared/scripts/ on sys.path, so this script dies at "
                     "import with ModuleNotFoundError. CONVENTIONS.md §10a "
                     "records two scripts that failed exactly this way."
                     % (rel(path), needs[0]), rel(path))
    rep.saw(check, "skill scripts importing a shared module", n_importers)

    # And the resolver itself must work from a skill-script vantage point.
    probe = os.path.join(SKILLS_DIR, "wiki-linter", "scripts", "scan_vault.py")
    if os.path.isfile(probe):
        info = pp.describe(start=probe)
        if info["ok"] and not info["co_located_fallback"]:
            rep.ok(check, "shared/scripts/ resolves from a skill script via %s"
                   % info["via"], rel(probe))
        else:
            rep.fail(check, "shared/scripts/ does not resolve plugin-relative "
                            "from %s: %s" % (rel(probe), info["error"]))


# ===========================================================================
# main
# ===========================================================================

#: Loader limits.  Like the XML-tag rule above these come from outside the
#: plugin, so they are written here rather than read from CONVENTIONS.md --
#: the skills did not agree them and cannot change them.  The tree's longest
#: description currently sits 5 characters under the cap.
SKILL_DESCRIPTION_MAX = 1024
SKILL_NAME_MAX = 64


def _frontmatter_scalar(fm, key):
    """The unescaped value of a top-level scalar key, or None."""
    m = re.search(r"^%s:[ \t]*(.*?)(?=^[A-Za-z0-9_-]+:|\Z)" % re.escape(key),
                  fm, re.S | re.M)
    if not m:
        return None
    raw = m.group(1).strip()
    if raw[:1] in (">", "|"):
        return " ".join(ln.strip() for ln in raw.splitlines()[1:] if ln.strip())
    if raw.startswith('"') and raw.endswith('"') and len(raw) > 1:
        try:
            return json.loads(raw)
        except ValueError:
            return raw[1:-1]
    if raw.startswith("'") and raw.endswith("'") and len(raw) > 1:
        return raw[1:-1].replace("''", "'")
    return raw


def _yaml_frontmatter_problems(fm):
    """Cheap structural validation, stdlib only (no PyYAML in this harness)."""
    problems = []
    if "\t" in fm:
        problems.append("contains a literal tab, which YAML forbids for indentation")
    depth = {"[": 0, "{": 0}
    quote = esc = None
    for ch in fm:
        if quote:
            if esc:
                esc = False
                continue
            if ch == "\\" and quote == '"':
                esc = True                 # YAML escapes only inside "..."
                continue
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "[{":
            depth["[" if ch == "[" else "{"] += 1
        elif ch in "]}":
            depth["[" if ch == "]" else "{"] -= 1
    if quote:
        problems.append("has an unterminated %s quote" % quote)
    if depth["["] or depth["{"]:
        problems.append("has unbalanced brackets/braces (%d [ , %d {)"
                        % (depth["["], depth["{"]))
    for ln in fm.splitlines():
        if not ln.strip() or ln[:1] in (" ", "\t", "#", "-"):
            continue
        if not re.match(r"^[A-Za-z0-9_-]+:(\s|$)", ln):
            problems.append("line %r is neither a `key:` nor a continuation"
                            % ln[:48])
            break
    return problems


def check_manifest_validity(rep, conv):
    """Guard the rules the plugin loader enforces at install time.

    These are not conventions the skills agreed among themselves -- they are
    hard constraints from outside, and violating one makes the whole plugin
    fail to install rather than merely drift.  A real install was rejected for
    an ``<N>`` placeholder in a description, which the loader read as an XML
    tag; the angle brackets had arrived legitimately, from the figure-naming
    convention.  So the pattern is easy to reintroduce and worth pinning.
    """
    check = "manifest-validity"
    xmlish = re.compile(r"<[^>\s][^>]*>")

    # The plugin manifest itself.  Nothing checked it at all: a trailing comma
    # makes it unparseable and the whole plugin fails to load, which no
    # convention check would ever notice.
    manifest = os.path.join(ROOT, ".claude-plugin", "plugin.json")
    if not os.path.isfile(manifest):
        rep.fail(check, ".claude-plugin/plugin.json is missing -- the plugin "
                        "has no manifest and will not install", rel(manifest))
    else:
        try:
            data = json.loads(read(manifest))
        except ValueError as exc:
            rep.fail(check, ".claude-plugin/plugin.json is not valid JSON: %s. "
                            "The loader reads this first; nothing else in the "
                            "plugin runs." % exc, rel(manifest))
            data = None
        if isinstance(data, dict):
            pname = data.get("name")
            if not isinstance(pname, str) or not re.fullmatch(r"[a-z0-9-]+", pname or ""):
                rep.fail(check,
                         ".claude-plugin/plugin.json name is %r; it must be a "
                         "non-empty lowercase kebab-case string" % (pname,),
                         rel(manifest))
            else:
                # The plugin's identity has two homes -- the manifest and
                # README's title -- so it is exactly the kind of fact that
                # drifts.  Compared here rather than against the checkout
                # directory name, which is whatever the user cloned into.
                readme = os.path.join(ROOT, "README.md")
                h1 = None
                if os.path.isfile(readme):
                    hm = re.match(r"#\s+(\S+)", read(readme))
                    h1 = hm.group(1) if hm else None
                if h1 and h1 != pname:
                    rep.fail(check,
                             "plugin.json calls the plugin %r but README.md's "
                             "title says %r -- one of the two is stale, and a "
                             "reader cannot tell which" % (pname, h1),
                             rel(manifest))
                else:
                    rep.ok(check, "plugin.json name %r agrees with README.md's "
                                  "title" % pname, rel(manifest))
            if str(data.get("description", "")).strip():
                rep.ok(check, "plugin.json has a description", rel(manifest))
            else:
                rep.fail(check, "plugin.json has no description", rel(manifest))

    rep.saw(check, "skill manifests", len(skill_names()))
    for name in skill_names():
        path = os.path.join(SKILLS_DIR, name, "SKILL.md")
        if not os.path.isfile(path):
            rep.fail(check, "%s has no SKILL.md" % name, rel(path))
            continue
        text = open(path, encoding="utf-8").read()
        m = re.match(r"---\n(.*?)\n---\n", text, re.S)
        if not m:
            rep.fail(check, "%s: SKILL.md has no YAML frontmatter" % name, rel(path))
            continue
        fm = m.group(1)

        # 1. No XML-like tags anywhere in frontmatter. Placeholders belong in
        #    the body, where the loader never looks.
        found = xmlish.findall(fm)
        if found:
            rep.fail(check,
                     "%s: frontmatter contains XML-like tag(s) %s -- the plugin "
                     "loader rejects these; write the placeholder without angle "
                     "brackets (N, not <N>) and keep <N> for the body"
                     % (name, ", ".join(sorted(set(found)))), rel(path))
        else:
            rep.ok(check, "%s: frontmatter has no XML-like tags" % name)

        # 2. name and description present, and name matches the directory --
        #    a mismatch installs the skill under a name nothing points at.
        got = re.search(r"^name:\s*(\S+)\s*$", fm, re.M)
        if not got:
            rep.fail(check, "%s: frontmatter has no name: field" % name, rel(path))
        elif got.group(1).strip('"\'') != name:
            rep.fail(check,
                     "%s: frontmatter name is %r but the directory is %r -- "
                     "these must match" % (name, got.group(1), name), rel(path))
        else:
            rep.ok(check, "%s: name matches its directory" % name)

        # 3. The frontmatter must be parseable at all.  An unbalanced quote or
        #    bracket in a hand-edited description is the same class of
        #    install-time rejection as the `<N>` incident, and just as easy to
        #    reintroduce -- these descriptions are ~1000 characters of prose
        #    full of quotes and brackets.
        problems = _yaml_frontmatter_problems(fm)
        if problems:
            rep.fail(check, "%s: frontmatter does not parse as YAML -- %s. The "
                            "loader reads this before anything else; the skill "
                            "does not install." % (name, "; ".join(problems)),
                     rel(path))
        else:
            rep.ok(check, "%s: frontmatter parses" % name)

        desc = _frontmatter_scalar(fm, "description")
        if desc is None or not desc.strip():
            rep.fail(check, "%s: frontmatter has no description: field" % name,
                     rel(path))
        elif len(desc) > SKILL_DESCRIPTION_MAX:
            rep.fail(check,
                     "%s: description is %d characters, over the loader's "
                     "%d-character limit -- the skill is rejected at install "
                     "time, exactly like the `<N>` placeholder was"
                     % (name, len(desc), SKILL_DESCRIPTION_MAX), rel(path))
        else:
            rep.ok(check, "%s: description is %d characters (limit %d)"
                   % (name, len(desc), SKILL_DESCRIPTION_MAX))
        if len(name) > SKILL_NAME_MAX:
            rep.fail(check, "%s: skill name is %d characters, over the loader's "
                            "%d-character limit"
                     % (name, len(name), SKILL_NAME_MAX), rel(path))


def check_readability(rep, conv):
    """Every file the walkers touched actually decoded.

    ``walk_skill_files`` used to swallow a ``UnicodeDecodeError`` and move on,
    which meant one stray byte anywhere in a file exempted that file from all
    nine checks at once, silently, while the summary still said PASS.
    """
    check = "file-readability"
    walk_skill_files()
    walk_plugin_files()
    rep.saw(check, "files walked", len(_SKILL_FILES or []) + len(_PLUGIN_FILES or []))
    for path, why in UNREADABLE:
        rep.fail(check,
                 "%s could not be read as UTF-8 (%s), so every check silently "
                 "skipped it. Fix the encoding: an unreadable file is exempt "
                 "from the whole harness." % (rel(path), why), rel(path))
    if not UNREADABLE:
        rep.ok(check, "all %d walked file(s) decoded as UTF-8"
               % (len(_SKILL_FILES or []) + len(_PLUGIN_FILES or [])))


def mod_generic(path):
    """The module's namespace, for reading a frozenset constant out of it.

    `ast.literal_eval` cannot build a `frozenset({...})` call, so this one
    constant is read by executing the module -- with `module_scope_effects`
    applied HERE, first, not assumed from check ordering: "check_scripts_run
    has already refused it" was true only when that check happened to run
    earlier, and an import-time hang in this in-process exec would have wedged
    the harness.  Returns None if it is refused or will not import.
    """
    try:
        return _load_module(path, "_ns_probe", screen=True)
    except Exception:
        return None


def check_note_headings(rep, conv):
    """Keep the summary format's ordered roles and examples aligned with lint.

    The prose contract lives in references/note-format.md, linked from the
    drafting step. Its canonical block and example table must both agree
    with note_lint.py's ROLES and generic-heading rejection set.
    """
    check = "note-headings"
    skill = os.path.join(SKILLS_DIR, "paper-summarizer", "SKILL.md")
    format_doc = os.path.join(SKILLS_DIR, "paper-summarizer", "references",
                              "note-format.md")
    lint = os.path.join(SKILLS_DIR, "paper-summarizer", "scripts", "note_lint.py")
    if not os.path.isfile(skill):
        rep.ok(check, "paper-summarizer is not installed; nothing to check")
        rep.saw(check, "section roles stated in both places", 0)
        return
    if not os.path.isfile(lint):
        rep.fail(check, "paper-summarizer/SKILL.md is here but "
                        "scripts/note_lint.py is not, so the six section roles "
                        "are stated once and enforced by nothing", rel(skill))
        return
    if not os.path.isfile(format_doc):
        rep.fail(check, "paper-summarizer is installed but its note-format.md "
                        "contract is missing; the section roles are unchecked",
                 rel(format_doc))
        return
    stated = canonical_block(read(format_doc), "summary-note:roles", required=False)
    stated = [l.strip() for l in stated if l.strip()]
    if not stated:
        rep.fail(check, "paper-summarizer/references/note-format.md has no "
                        "`canonical:summary-note:roles` block, so the section roles "
                        "note_lint.py enforces are stated in only one place",
                 rel(format_doc))
        return
    got = None
    try:
        tree = ast.parse(read(lint))
    except SyntaxError as exc:
        rep.fail(check, "note_lint.py does not parse (%s), so its ROLES "
                        "constant could not be compared with note-format.md's block"
                 % exc.msg, rel(lint))
        return
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "ROLES" not in names:
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, SyntaxError):
            got = None
            continue
        if not isinstance(value, (list, tuple)):
            rep.fail(check, "note_lint.py's ROLES is %r, not a sequence of "
                            "section names" % (value,), rel(lint))
            return
        got = [str(v) for v in value]
    if got is None:
        rep.fail(check, "note_lint.py has no module-level ROLES literal, so the "
                        "section roles it enforces cannot be compared with the "
                        "ones note-format.md documents", rel(lint))
        return
    if got != stated:
        rep.fail(check, "note_lint.py ROLES is %s but note-format.md's canonical block "
                        "says %s -- the linter and the instructions disagree "
                        "about what sections a note has"
                 % (" | ".join(got) or "(empty)", " | ".join(stated)), rel(lint))
        return
    # The examples are instructions too: check their order and uniqueness,
    # not merely membership in the canonical list.
    format_text = read(format_doc)
    table = [m.group(1).strip() for m in
             re.finditer(r"(?m)^\|\s*([A-Za-z][A-Za-z ]*?)\s*\|\s*`## ",
                         format_text)]
    if table != stated:
        rep.fail(check, "note-format.md's role table is %s but its canonical "
                        "block says %s; the example roles must match in order"
                 % (" | ".join(table) or "(empty)", " | ".join(stated)),
                 rel(format_doc))
        return
    generic = getattr(mod_generic(lint), "GENERIC_HEADINGS", None)
    if not isinstance(generic, (set, frozenset, list, tuple)):
        rep.fail(check, "note_lint.py's GENERIC_HEADINGS could not be read as "
                        "a collection; its agreement with the section roles "
                        "was not checked", rel(lint))
        return
    loose = [r for r in stated if r.casefold() not in generic]
    if loose:
        rep.fail(check, "note_lint.py's GENERIC_HEADINGS does not contain %s, "
                        "so a note headed with that role name would pass"
                 % ", ".join(loose), rel(lint))
        return
    rep.saw(check, "section roles stated in both places", len(stated))
    rep.saw(check, "role-table rows cross-checked", len(table))
    rep.ok(check, "note-format.md's canonical block, its example table and "
                  "note_lint.py's ROLES and GENERIC_HEADINGS all agree",
           rel(format_doc))


# ===========================================================================
# four seams the 2026-08-24 review found unwatched
# ===========================================================================
#
# Each of these pins a policy whose restatements had already drifted once (or
# were one edit away from it) and which no earlier check read: the equation
# policy's three homes, the MOC location, §6's footer-pipe rule, and §7's
# physical-page rule.  Same shape throughout: the POSITIVE pins double as
# vacuity guards (an extraction that finds nothing is a FAIL naming the home,
# never a silent pass), and the NEGATIVE pins name the exact resurrection
# shape that bit before.


def check_equation_policy(rep, conv):
    """The v1.31 equation policy, held to agree across its three homes.

    wiki-builder/references/equations.md owns the policy; CONVENTIONS §2d
    records it; wiki-linter's qc-items item 12 restates it.  The one live
    contradiction the 2026-08-20 review found was exactly here (the linter's
    restatement dropped the read-reset split), and until now nothing watched
    the seam.
    """
    check = "equation-policy"
    eq_path = os.path.join(SKILLS_DIR, "wiki-builder", "references",
                           "equations.md")
    qc_path = os.path.join(SKILLS_DIR, "wiki-linter", "references",
                           "qc-items.md")
    try:
        eq, qc = read(eq_path), read(qc_path)
    except OSError as exc:
        rep.fail(check, "cannot read a policy home: %s" % exc)
        return

    pins = [
        (CONVENTIONS, conv, r"wiki-builder/references/equations\.md",
         "CONVENTIONS.md no longer names `wiki-builder/references/"
         "equations.md` as the equation policy's home -- the pointer that "
         "makes the policy findable from the canonical layer"),
        (CONVENTIONS, conv,
         r"reports the insertion under \*Notes for the user\*",
         "CONVENTIONS.md §2d no longer records that a linter-inserted "
         "equation is reported under *Notes for the user* (the linter writes "
         "neither `read:` nor `updated:`)"),
        (CONVENTIONS, conv, r"resets `read: false`",
         "CONVENTIONS.md §2d no longer records the builder half of the "
         "split: a merge that adds an equation resets `read: false`"),
        (eq_path, eq, r"resets `read: false`",
         "equations.md no longer states that a new equation added on a merge "
         "is body content and resets `read: false` -- the builder half of "
         "the split"),
        (eq_path, eq, r"writes neither `read:` nor `updated:`",
         "equations.md no longer states the linter half of the split: a "
         "retroactive item-12 insertion writes neither `read:` nor "
         "`updated:`"),
        (eq_path, eq, r"\*Notes for the user\*",
         "equations.md no longer routes the linter's insertion notice to "
         "*Notes for the user*"),
        (qc_path, qc, r"owned by `wiki-builder/references/equations\.md`",
         "qc-items.md item 12 no longer credits equations.md as the owner "
         "of the equation clauses -- the restatement has detached from its "
         "rule of record"),
        (qc_path, qc,
         r"insertion into an entry whose `read:` is `true`[^.]{0,220}"
         r"\*Notes for the user\*",
         "qc-items.md item 12 no longer states that an insertion into a "
         "`read: true` entry is named under *Notes for the user* -- the "
         "silent-unread-math gap the 2026-08-20 review closed"),
    ]
    n = 0
    for path, text, pat, msg in pins:
        if re.search(pat, text, re.S):
            n += 1
        else:
            rep.fail(check, msg, rel(path))
    # The direction must never invert: nothing may say the LINTER resets or
    # writes `read:` on an insertion (its Dates policy is the opposite).
    for path, text in ((eq_path, eq), (qc_path, qc)):
        for m in re.finditer(r"(?:wiki-)?linter[^.\n]{0,120}"
                             r"(?:resets|writes) `read:(?! `? ?nor)", text):
            frag = " ".join(text[m.start():m.end()].split())
            if "neither" in frag:
                continue
            rep.fail(check,
                     "%s says the linter writes/resets `read:` (\"%s…\") -- "
                     "the linter never writes the field; that is the exact "
                     "inversion the policy split exists to prevent"
                     % (rel(path), frag[:90]), rel(path))
    rep.saw(check, "equation-policy pins held", n)
    rep.ok(check, "%d/%d equation-policy statements agree across the three "
                  "homes" % (n, len(pins)), rel(CONVENTIONS))


def check_moc_placement(rep, conv):
    """§3's MOC location and naming, restated only in agreeing forms.

    §3: the MOC file is `<discipline-slug>-moc.md` in the VAULT ROOT.  A
    restatement that files it under `Wiki/` sends Task 3's writes into the
    entry folder, where the scanner reads each MOC as a malformed entry on
    every later run.
    """
    check = "moc-placement"
    if not re.search(r"-moc\.md", conv) \
            or not re.search(r"-moc(?:\.md|\]\])?`?[^.\n]{0,120}vault root|"
                             r"vault root[^.\n]{0,160}-moc", conv):
        rep.fail(check, "CONVENTIONS.md §3 no longer states the MOC file "
                        "shape (`<discipline>-moc.md`) in the vault root -- "
                        "the location every restatement is held to",
                 rel(CONVENTIONS))
    else:
        rep.ok(check, "§3 states `<discipline>-moc.md`, vault root",
               rel(CONVENTIONS))
    stated = 0
    for skill, path, text in walk_skill_files():
        if re.search(r"-moc(?:\.md|\]\])", text):
            stated += 1
        for m in re.finditer(r"Wiki/[^\s`\]]*-moc", text):
            rep.fail(check,
                     "%s places a MOC under `Wiki/` (\"%s\") -- §3 puts MOC "
                     "files in the vault ROOT; a MOC written into Wiki/ is "
                     "scanned as a malformed entry on every later run"
                     % (rel(path), m.group(0)), at(path, m.start(), text))
    rep.saw(check, "skill files naming the -moc shape", stated)
    if not stated:
        rep.fail(check, "no skill file states the `-moc` naming at all -- "
                        "the shape §3 defines has no consumer statement left")


def check_link_rules(rep, conv):
    """§6's footer-pipe rule and its known resurrection shape.

    §6: EVERY Related-footer link is piped, even when slug-equal.  writing.md
    carried a slug-equal exception that contradicted §6, builder item 11 and
    the SKILL body at once (fixed 2026-08-24); this pins the rule's statement
    and fails the exception's return.
    """
    check = "link-rules"
    if not re.search(r"always piped, even when slug-equal", conv):
        rep.fail(check, "CONVENTIONS.md §6's footer row no longer says "
                        "\"always piped, even when slug-equal\" -- the rule "
                        "of record this check holds restatements to",
                 rel(CONVENTIONS))
    wb = os.path.join(SKILLS_DIR, "wiki-builder", "references", "writing.md")
    try:
        wtext = read(wb)
    except OSError:
        wtext = ""
    if not re.search(r"bare form `\[\[slug\]\]` is wrong in the footer",
                     wtext):
        rep.fail(check, "writing.md's Related-footer section no longer "
                        "states that the bare form is wrong in the footer "
                        "(§6's rule)", rel(wb))
    else:
        rep.ok(check, "writing.md states §6's footer-pipe rule", rel(wb))
    n_files = 0
    for skill, path, text in walk_skill_files():
        n_files += 1
        for m in re.finditer(r"[^.\n]*exception[^.\n]*", text):
            frag = m.group(0)
            if ("slug-equal" not in frag and "all-lowercase" not in frag) \
                    or "footer" not in frag.lower():
                continue
            if re.search(r"\bno\b[^.\n]{0,40}exception", frag) \
                    or "There is no" in frag:
                continue
            rep.fail(check,
                     "%s re-grants a slug-equal footer exception (\"%s…\") -- "
                     "§6's footer rule has no exception, and this exact "
                     "sentence shape contradicted three statements of the "
                     "rule at once before it was removed"
                     % (rel(path), " ".join(frag.split())[:90]),
                     at(path, m.start(), text))
    rep.saw(check, "skill files scanned for the footer-exception shape",
            n_files)


def check_physical_page(rep, conv):
    """§7's physical-page rule: every `#page=` explanation stays physical.

    §7: `#page=N` is the 1-indexed position in the FILE, never the printed
    folio.  The drift shape is a restatement quietly explaining `N` as the
    printed page number -- every citation checked against it then points a
    page early or late for any front-matter offset.
    """
    check = "physical-page"
    if not re.search(r"`N` is the physical page", conv):
        rep.fail(check, "CONVENTIONS.md §7 no longer states \"`N` is the "
                        "physical page\" -- the rule of record",
                 rel(CONVENTIONS))
    stated = 0
    for skill, path, text in walk_skill_files():
        low = text
        if re.search(r"physical[^.\n]{0,120}page|page[^.\n]{0,40}physical",
                     low) and "#page=" in low:
            stated += 1
        # Sentence-wise: an explanation tying #page= to "printed" must carry
        # the physical contrast in the same sentence, or it IS the drift.
        for m in re.finditer(r"[^.\n]*#page=[^.\n]*printed[^.\n]*|"
                             r"[^.\n]*printed[^.\n]*#page=[^.\n]*", low):
            frag = m.group(0)
            if "physical" in frag or "not the printed" in frag \
                    or "whatever folio" in frag or "not the folio" in frag:
                continue
            rep.fail(check,
                     "%s explains `#page=` by the PRINTED page (\"%s…\") "
                     "with no physical-position contrast in the sentence -- "
                     "§7's anchor is the 1-indexed position in the file"
                     % (rel(path), " ".join(frag.split())[:90]),
                     at(path, m.start(), text))
    rep.saw(check, "skill files stating the physical-page rule", stated)
    if stated < 2:
        rep.fail(check, "fewer than two skill files state the physical-page "
                        "rule -- the restatements this check exists to hold "
                        "have gone missing")
    else:
        rep.ok(check, "%d skill file(s) state §7's physical-page rule"
               % stated, rel(SKILLS_DIR))


CHECKS = [
    check_readability,
    check_note_headings,
    check_tag_enum,
    check_slug_single_implementation,
    check_source_filename,
    check_shell_quoting,
    check_figure_naming,
    check_frontmatter,
    check_yaml_examples,
    check_type_enum,
    check_contract_fictions,
    check_script_surface,
    check_skill_roster,
    check_reference_paths,
    check_scripts_run,
    check_self_test,
    check_bootstrap,
    check_manifest_validity,
    check_equation_policy,
    check_moc_placement,
    check_link_rules,
    check_physical_page,
]


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="test_conventions.py",
        description="Check the skills against shared/CONVENTIONS.md.")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="list passing checks individually, not just failures")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--allow-pending", action="store_true",
                    help="exit 0 when the only defects are ones CONVENTIONS.md "
                         "§10 registers as pending (they are still reported)")
    ap.add_argument("--strict", action="store_true",
                    help="accepted and ignored: strict is now the default, and "
                         "`--allow-pending` is the way to relax it")
    # Not for humans: this is how the harness re-enters itself as the child
    # half of `probe_module`.  Importing a module under test happens HERE, in
    # a process of its own, with a clock on it -- never in the process that
    # owns the report.  See "executing code out of the tree under test".
    ap.add_argument("--probe-module", metavar="PATH", help=argparse.SUPPRESS)
    ap.add_argument("--probe-out", metavar="PATH", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if args.probe_module:
        if not args.probe_out:
            print("--probe-module requires --probe-out", file=sys.stderr)
            return 2
        return _probe_child(args.probe_module, args.probe_out)

    if not os.path.isfile(CONVENTIONS):
        print("harness error: %s not found" % rel(CONVENTIONS), file=sys.stderr)
        return 2
    if not os.path.isdir(SKILLS_DIR):
        print("harness error: %s not found" % rel(SKILLS_DIR), file=sys.stderr)
        return 2

    conv = read(CONVENTIONS)
    rep = Report()
    for fn in CHECKS:
        before = len(rep.results)
        try:
            fn(rep, conv)
        except HarnessError as exc:
            print("harness error in %s: %s" % (fn.__name__, exc), file=sys.stderr)
            return 2
        except Exception as exc:                       # a broken check is a bug
            tb = sys.exc_info()[2]
            last = tb
            while last.tb_next is not None:
                last = last.tb_next
            rep.fail(fn.__name__,
                     "check CRASHED and therefore checked nothing: %s: %s "
                     "(at %s:%d). A crashed check is a failed check -- it "
                     "proves nothing about the tree."
                     % (type(exc).__name__, exc,
                        os.path.basename(last.tb_frame.f_code.co_filename),
                        last.tb_lineno))
        if len(rep.results) == before:
            # A check that emitted nothing at all does not appear in the
            # summary, so the run looks complete while one whole check is
            # missing.  That is the vacuous pass in its purest form.
            rep.fail(fn.__name__,
                     "check produced NO results at all -- it neither passed "
                     "nor failed anything, so its convention is currently "
                     "unguarded. Its discovery step is broken, or the "
                     "convention is no longer stated anywhere.")
    rep.vacuity()

    if args.json:
        print(json.dumps({
            "ok": rep.exit_code(args.allow_pending) == 0,
            "counts": rep.counts(),
            "examined": rep.examined,
            "results": [{"check": c, "status": s, "where": w, "message": m}
                        for c, s, w, m in rep.results],
        }, indent=2, ensure_ascii=False))
    else:
        print(rep.render(verbose=args.verbose,
                         allow_pending=args.allow_pending))
    return rep.exit_code(args.allow_pending)


if __name__ == "__main__":
    sys.exit(main())
