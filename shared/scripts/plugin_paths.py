#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""plugin_paths.py -- locate the obsidian plugin's ``shared/scripts/``.

WHY THIS EXISTS
---------------
Several skills need the same helper (today: ``slugify.py``).  The plugin
installs as one tree, so a skill script can reach ``shared/scripts/`` by
walking up from its own ``__file__``.  But a skill can also be *extracted
alone* -- copied out of the plugin, vendored into another package, run from a
tarball of one skill directory -- and then there is no ``shared/`` above it.

The two failure modes we are avoiding:

  1. **Vendoring a second copy of the algorithm** into each skill.  That is the
     duplication that produced the data-loss bug this shared layer exists to
     prevent: ``C++`` slugged to ``c-plus-plus`` in one copy and ``c`` in the
     other, so the linter proposed renaming correctly-named entries, and an
     approved rename rewrites links vault-wide.
  2. **Dying with ``ModuleNotFoundError: No module named 'slugify'``**, which
     tells the user nothing about what is wrong or how to fix it.

So: resolve the plugin-relative path first, fall back to a co-located copy,
and otherwise fail with an error that names the searched locations and the
one-line fix.

THE BOOTSTRAP
-------------
A skill script cannot ``import plugin_paths`` before it knows where
``shared/scripts/`` is -- so the search itself has to be inlined.  The
canonical snippet is :data:`BOOTSTRAP` below.  It is pure path arithmetic --
it restates no convention, so a copy of it cannot drift in any way that
matters -- and ``tests/test_conventions.py`` asserts every copy in the tree is
byte-identical to :data:`BOOTSTRAP`.  Paste it verbatim, then ``import
slugify`` (and, if you want the richer helpers, ``import plugin_paths``)
normally.

Three properties of the snippet are load-bearing, and each one is a bug that
was actually shipped:

  * ``$OBSIDIAN_VAULT_SHARED`` is consulted FIRST, by the snippet itself.  The
    override used to be readable only through this module, i.e. only *after*
    the bootstrap had already succeeded -- so it could never rescue the case
    it exists for.
  * The script's own directory is **appended**, never inserted at the front,
    and ``shared/scripts/`` is inserted at position 0.  The snippet used to
    re-insert the script's directory at 0 *after* the shared path, giving the
    skill's own ``scripts/`` precedence: a ``slugify.py`` dropped in there
    shadowed this tree's canonical module silently, and ``C++`` slugged to
    ``c``.  Co-located modules (``vault_index``) still import, because the
    directory is still on ``sys.path`` -- just last.
  * Failing to resolve is a :class:`SystemExit` carrying the searched
    locations and the fix, not a fall-through to ``ModuleNotFoundError: No
    module named 'slugify'``.

That last one is why the snippet is deliberately STRICTER than
:func:`find_shared_scripts`: it has no step-3 co-located fallback.  It cannot
have one, because it does not know which module the script is about to import
-- and "a slug module sitting next to the script wins when ``shared/`` is
absent" is one typo in a walk-up away from being the shadowing bug again.  A
skill genuinely extracted alone points ``$OBSIDIAN_VAULT_SHARED`` at the
directory holding the copy; the error message says so.  The richer,
fallback-bearing search below is still available to anything that has already
imported this module.

SEARCH ORDER (:func:`find_shared_scripts`)
------------------------------------------
  1. ``$OBSIDIAN_VAULT_SHARED`` if set -- the explicit escape hatch for an
     unusual install; must be a directory, and (when the caller names the
     module it is about to import) must actually hold that module, or it is
     an error, never a silent skip.  An override that resolves to a directory
     without the modules in it is failure mode 2 wearing a hat: the caller
     puts it on ``sys.path`` and the next line dies with the bare
     ``ModuleNotFoundError``.
  2. Plugin-relative: walk up from the starting path (default: the caller's
     directory) at most :data:`MAX_WALK_UP` levels, taking the first
     ancestor that contains ``shared/scripts/``.  From
     ``skills/<skill>/scripts/x.py`` the plugin root is three levels up, so
     the default bound of 5 has slack for a deeper layout without wandering
     into ``$HOME``.
  3. Co-located fallback: the starting directory itself, if it holds the
     module being looked for.  This is the "skill extracted alone, someone
     dropped a copy next to it" case -- supported so the skill still runs,
     and reported by :func:`describe` so the copy is visible rather than
     silently authoritative.

Stdlib only, Python 3.8+.  Usable as a module and as a CLI:

    python3 shared/scripts/plugin_paths.py            # human-readable report
    python3 shared/scripts/plugin_paths.py --json     # same, machine-readable
    python3 shared/scripts/plugin_paths.py --bootstrap  # print the snippet
    python3 shared/scripts/plugin_paths.py --test     # inline self-test
Exit codes: 0 resolved, 1 not found.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sys
import tempfile

__all__ = [
    "SharedLayerNotFound",
    "BOOTSTRAP",
    "MAX_WALK_UP",
    "SHARED_REL",
    "find_shared_scripts",
    "ensure_shared_on_path",
    "plugin_root",
    "describe",
    "run_self_test",
]

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

#: ``shared/scripts`` relative to the plugin root, as path components.
SHARED_REL = ("shared", "scripts")

#: How many ancestors to try.  ``skills/<skill>/scripts`` needs 3; 5 leaves
#: slack for a deeper layout while still stopping well short of ``$HOME``.
MAX_WALK_UP = 5

#: Environment override, for an install whose layout we cannot guess.
ENV_VAR = "OBSIDIAN_VAULT_SHARED"

#: The module every entry point probes an override with, so that all of them
#: accept and refuse the same directories.  :func:`plugin_root` and
#: :func:`ensure_shared_on_path` used to pass none while :func:`describe`
#: passed ``"slugify"``, which is the contradiction :func:`_root_of` was
#: written to remove, re-entering one layer up: a hollow override was a hard
#: refusal for one of the three and a resolved answer for the other two.
PROBE_MODULE = "slugify"

#: The canonical bootstrap snippet.  Copy it VERBATIM into any skill script
#: that needs a module from ``shared/scripts/``.  ``tests/test_conventions.py``
#: asserts every copy in the tree matches this string exactly.
BOOTSTRAP = '''\
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
copy is the bug the shared layer exists to prevent.""" % "\\n  ".join(_tried))
_sys.path[:] = [_p for _p in _sys.path if _p not in (_shared, _here)]
_sys.path.insert(0, _shared)               # shared/scripts/ FIRST
_sys.path.append(_here)                    # own dir LAST: a local copy cannot shadow it
# --- end bootstrap ---
'''


class SharedLayerNotFound(ImportError):
    """Raised when ``shared/scripts/`` cannot be located.

    Subclasses :class:`ImportError` so a caller that only wants to degrade
    gracefully can catch the import error it already catches.
    """


# ---------------------------------------------------------------------------
# resolution
# ---------------------------------------------------------------------------

def _caller_dir(start):
    if start:
        return os.path.dirname(os.path.abspath(start)) if os.path.isfile(start) \
            else os.path.abspath(start)
    return os.path.dirname(os.path.abspath(__file__))


def find_shared_scripts(start=None, module=None, _trace=None):
    """Return the absolute path of ``shared/scripts/``.

    ``start`` is a file or directory to search up from (default: this file's
    directory).  ``module`` is an optional bare module name (``"slugify"``)
    used by the co-located fallback: without it, step 3 cannot tell a stray
    directory from a usable one, so it is skipped.

    Raises :class:`SharedLayerNotFound` with a message naming every location
    tried and the fix.
    """
    trace = _trace if _trace is not None else []
    base = _caller_dir(start)

    # 1. explicit override
    env = os.environ.get(ENV_VAR)
    if env:
        cand = os.path.abspath(os.path.expanduser(env))
        trace.append(("env", cand, os.path.isdir(cand)))
        if not os.path.isdir(cand):
            raise SharedLayerNotFound(
                "%s is set to %r, which is not a directory. Unset it, or point it "
                "at the plugin's shared/scripts/ folder." % (ENV_VAR, env)
            )
        # An override that IS a directory but does not hold the module is the
        # one override failure that used to slip through: this function
        # returned it, the caller put it on sys.path, and the next line died
        # with "ModuleNotFoundError: No module named 'slugify'" -- the bare
        # error this module exists to replace (failure mode 2 above).  The
        # override is authoritative, so there is nothing to fall back to; the
        # only useful thing left is to say exactly what is wrong.
        if module and not os.path.isfile(os.path.join(cand, module + ".py")):
            try:
                present = sorted(n for n in os.listdir(cand) if n.endswith(".py"))
            except OSError as exc:
                present = ["(cannot list the directory: %s)" % exc]
            raise SharedLayerNotFound(
                "%s is set to %r, which is a directory but does not contain "
                "%s.py.\n"
                "The override is authoritative -- nothing falls back to the "
                "plugin-relative walk-up -- so importing %s from it would fail "
                "with a bare \"ModuleNotFoundError: No module named '%s'\", "
                "which says nothing about what is wrong.\n"
                "Python modules found there: %s\n"
                "Fix: point %s at the plugin's shared/scripts/ folder (the one "
                "holding %s.py), or unset it to use the plugin-relative "
                "walk-up." % (ENV_VAR, env, module, module, module,
                              ", ".join(present) or "(none)", ENV_VAR, module)
            )
        return cand

    # 2. plugin-relative walk-up (the normal path)
    d = base
    for _ in range(MAX_WALK_UP):
        cand = os.path.join(d, *SHARED_REL)
        hit = os.path.isdir(cand)
        trace.append(("walk-up", cand, hit))
        if hit:
            return cand
        parent = os.path.dirname(d)
        if parent == d:                      # filesystem root
            break
        d = parent

    # 3. co-located fallback (skill extracted alone)
    if module:
        cand = os.path.join(base, module + ".py")
        hit = os.path.isfile(cand)
        trace.append(("co-located", cand, hit))
        if hit:
            return base

    tried = "\n".join("  %-11s %s%s" % (kind, path, "" if ok else "  (absent)")
                      for kind, path, ok in trace) or "  (nothing tried)"
    raise SharedLayerNotFound(
        "obsidian: could not find the plugin's shared/scripts/ folder.\n"
        "Tried, in order:\n%s\n"
        "The shared layer holds the single canonical copy of conventions more "
        "than one skill depends on (see shared/CONVENTIONS.md). Either install "
        "the whole plugin tree, or set %s to the shared/scripts/ path.\n"
        "Do NOT work around this by pasting a second copy of the algorithm "
        "into the skill -- divergent copies are the bug the shared layer "
        "exists to prevent." % (tried, ENV_VAR)
    )


def ensure_shared_on_path(start=None, module=PROBE_MODULE):
    """Put ``shared/scripts/`` on ``sys.path`` (idempotent); return its path.

    ``module`` defaults to :data:`PROBE_MODULE` rather than to ``None``: this
    function's whole job is to make the caller's next line -- ``import
    slugify`` -- work, and with no module to probe for, a hollow override went
    onto ``sys.path[0]`` and that next line died with the bare
    ``ModuleNotFoundError`` this module exists to replace.  Pass ``None``
    explicitly to put a directory on the path without vetting it.
    """
    path = find_shared_scripts(start=start, module=module)
    if path not in sys.path:
        sys.path.insert(0, path)
    return path


def _root_of(shared):
    """The plugin root implied by ``shared``, or ``None`` if it implies none.

    ONE rule, used by :func:`plugin_root` and :func:`describe` alike.  They
    used to compute this separately and only :func:`plugin_root` applied the
    ``isdir(root/shared/scripts)`` guard, so :func:`describe` reported a
    ``plugin_root`` that :func:`plugin_root` itself refused -- point the
    override at a vendored ``lib/`` and ``describe()`` named its grandparent
    as the plugin root while ``plugin_root()`` returned ``None``.  A
    diagnostic that contradicts the function it is diagnosing is worse than no
    diagnostic: it is the thing the reader trusts.
    """
    root = os.path.dirname(os.path.dirname(shared))
    return root if os.path.isdir(os.path.join(root, *SHARED_REL)) else None


def plugin_root(start=None, module=PROBE_MODULE):
    """Return the plugin root (the parent of ``shared/``), or ``None``.

    ``None`` when the co-located fallback resolved -- there is no plugin root
    in that case, which is exactly the signal a caller wants.

    Probes with :data:`PROBE_MODULE`, as :func:`describe` does, so that the
    two answer for the same set of overrides.  Passing none was the same
    contradiction :func:`_root_of` removes, one layer up and pointing the
    other way: set ``$OBSIDIAN_VAULT_SHARED`` to a hollow ``lib/`` sitting
    inside a REAL plugin and the ``if module`` guard in
    :func:`find_shared_scripts` was skipped here, so this function named that
    plugin as the root while :func:`describe` raised and reported ``None``.
    A diagnostic and the function it diagnoses that disagree is the bug; which
    of the two is right does not enter into it.
    """
    try:
        shared = find_shared_scripts(start=start, module=module)
    except SharedLayerNotFound:
        return None
    return _root_of(shared)


def describe(start=None, module=PROBE_MODULE):
    """Diagnostic dict: how resolution went, and via which step."""
    trace = []
    try:
        shared = find_shared_scripts(start=start, module=module, _trace=trace)
        via = trace[-1][0] if trace else "unknown"
        root = _root_of(shared)
        return {
            "ok": True,
            "shared_scripts": shared,
            "via": via,
            "plugin_root": root if via != "co-located" else None,
            "co_located_fallback": via == "co-located",
            "tried": [{"step": k, "path": p, "found": ok} for k, p, ok in trace],
            "error": None,
        }
    except SharedLayerNotFound as exc:
        return {
            "ok": False,
            "shared_scripts": None,
            "via": None,
            "plugin_root": None,
            "co_located_fallback": False,
            "tried": [{"step": k, "path": p, "found": ok} for k, p, ok in trace],
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------

def _touch(path, body="# plugin_paths self-test stub\n"):
    """Create ``path`` (and its parents) inside the self-test's temp tree."""
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    return path


def _capture(fn, *args):
    """``fn``'s stdout as a string (it writes; we are asserting on what)."""
    saved, sink = sys.stdout, io.StringIO()
    sys.stdout = sink
    try:
        fn(*args)
    finally:
        sys.stdout = saved
    return sink.getvalue()


def _run_bootstrap(script_path):
    """Execute :data:`BOOTSTRAP` as the script at ``script_path`` would.

    Returns ``(sys.path after, None)``, or ``(None, message)`` when the
    snippet raised its :class:`SystemExit`.  ``sys.path`` is restored before
    returning: rewriting it in place is right in the script's own process and
    unacceptable inside this one.
    """
    saved = list(sys.path)
    namespace = {"__file__": script_path}
    try:
        exec(compile(BOOTSTRAP, "<BOOTSTRAP>", "exec"), namespace)  # noqa: S102
        return list(sys.path), None
    except SystemExit as exc:
        return None, str(exc)
    finally:
        sys.path[:] = saved


def run_self_test():
    """Run the inline scenarios; return the result dict (no printing).

    Same shape as ``slugify.run_self_test()``, ``naming.run_self_test()`` and
    ``plurals.run_self_test()``, so ``tests/test_conventions.py`` can read all
    four the same way.

    Every scenario is a real directory tree built under a temporary directory
    and removed again, because the thing under test is filesystem arithmetic
    and a mocked ``isdir`` would only assert that the mock agrees with itself.
    ``$OBSIDIAN_VAULT_SHARED`` and ``sys.path`` are saved and restored: half of
    what is exercised here is code whose whole job is to change them.
    """
    cases = []                       # (name, ok, detail)

    def eq(name, got, expected):
        cases.append((name, got == expected,
                      "expected %r, got %r" % (expected, got)))

    def yes(name, cond, detail="expected a true value"):
        cases.append((name, bool(cond), detail))

    def says(name, message, needle):
        cases.append((name, needle in (message or ""),
                      "%r is not in the message: %r" % (needle, message)))

    def refuses(name, fn, *args, **kwargs):
        """Assert ``fn`` raises SharedLayerNotFound; return its message."""
        try:
            got = fn(*args, **kwargs)
        except SharedLayerNotFound as exc:
            cases.append((name, True, ""))
            return str(exc)
        except Exception as exc:                     # a bare ImportError here
            cases.append((name, False,               # is exactly the bug
                          "raised %s: %s -- not SharedLayerNotFound"
                          % (type(exc).__name__, exc)))
            return ""
        cases.append((name, False, "did not raise; returned %r" % (got,)))
        return ""

    def agree(name, start):
        """describe() must report the plugin_root that plugin_root() returns."""
        said, returned = describe(start=start)["plugin_root"], plugin_root(start=start)
        cases.append((name, said == returned,
                      "describe() reports %r, plugin_root() returns %r"
                      % (said, returned)))

    def set_env(value):
        if value is None:
            os.environ.pop(ENV_VAR, None)
        else:
            os.environ[ENV_VAR] = value

    tmp = tempfile.mkdtemp(prefix="plugin_paths-selftest-")
    saved_env = os.environ.get(ENV_VAR)
    saved_path = list(sys.path)
    try:
        set_env(None)

        # -- a script inside a full plugin ------------------------------
        plug = os.path.join(tmp, "plugin")
        shared = os.path.join(plug, *SHARED_REL)
        _touch(os.path.join(shared, "slugify.py"))
        script = _touch(os.path.join(plug, "skills", "demo", "scripts", "thing.py"))
        here = os.path.dirname(script)

        eq("full plugin: resolves from a skill script",
           find_shared_scripts(start=script), shared)
        eq("full plugin: resolves from a directory as well as a file",
           find_shared_scripts(start=here), shared)
        info = describe(start=script)
        yes("full plugin: describe reports success", info["ok"], info["error"] or "")
        eq("full plugin: resolved via the walk-up", info["via"], "walk-up")
        eq("full plugin: not the co-located fallback", info["co_located_fallback"], False)
        eq("full plugin: plugin_root is the plugin", plugin_root(start=script), plug)
        agree("full plugin: describe and plugin_root agree", script)

        sys.path[:] = list(saved_path)
        eq("ensure_shared_on_path returns the directory",
           ensure_shared_on_path(start=script, module="slugify"), shared)
        eq("ensure_shared_on_path puts shared/scripts/ first", sys.path[0], shared)
        ensure_shared_on_path(start=script, module="slugify")
        eq("ensure_shared_on_path is idempotent", sys.path.count(shared), 1)
        sys.path[:] = list(saved_path)

        # -- the plugin nested inside another folder --------------------
        # The outer tree ALSO has shared/scripts/: the NEAREST ancestor has to
        # win, or a plugin vendored into a host tree silently runs the host's
        # copy of the conventions -- the divergent-copy bug by another route.
        outer = os.path.join(tmp, "outer")
        _touch(os.path.join(outer, *(SHARED_REL + ("slugify.py",))))
        nested = os.path.join(outer, "vendor", "obsidian")
        nested_shared = os.path.join(nested, *SHARED_REL)
        _touch(os.path.join(nested_shared, "slugify.py"))
        nested_script = _touch(os.path.join(nested, "skills", "demo",
                                            "scripts", "thing.py"))

        eq("nested plugin: resolves to the nested shared/scripts/",
           find_shared_scripts(start=nested_script), nested_shared)
        eq("nested plugin: plugin_root is the nested root",
           plugin_root(start=nested_script), nested)
        agree("nested plugin: describe and plugin_root agree", nested_script)

        # -- a skill extracted alone, with no shared/ above it ----------
        lone_script = _touch(os.path.join(tmp, "lone", "scripts", "thing.py"))
        msg = refuses("extracted alone: refuses to resolve",
                      find_shared_scripts, start=lone_script)
        says("extracted alone: the error names the override", msg, ENV_VAR)
        says("extracted alone: the error lists a location it searched",
             msg, os.path.join(os.path.dirname(lone_script), *SHARED_REL))
        says("extracted alone: the error forbids a second copy", msg, "Do NOT")
        yes("SharedLayerNotFound is an ImportError, so `except ImportError` "
            "still catches it", issubclass(SharedLayerNotFound, ImportError))
        eq("extracted alone: plugin_root is None", plugin_root(start=lone_script), None)
        info = describe(start=lone_script)
        eq("extracted alone: describe reports failure", info["ok"], False)
        eq("extracted alone: describe has no plugin_root", info["plugin_root"], None)
        yes("extracted alone: describe lists what it tried",
            len(info["tried"]) >= MAX_WALK_UP,
            "listed %d locations" % len(info["tried"]))
        agree("extracted alone: describe and plugin_root agree", lone_script)

        # -- extracted alone, with a copy dropped next to the script ----
        copy_script = _touch(os.path.join(tmp, "lone-copy", "scripts", "thing.py"))
        copy_dir = os.path.dirname(copy_script)
        _touch(os.path.join(copy_dir, "slugify.py"))
        eq("co-located copy: resolves to the script's own directory",
           find_shared_scripts(start=copy_script, module="slugify"), copy_dir)
        refuses("co-located copy: only when the module is named",
                find_shared_scripts, start=copy_script)
        info = describe(start=copy_script)
        eq("co-located copy: resolved via the fallback", info["via"], "co-located")
        eq("co-located copy: reported as a fallback, not silently authoritative",
           info["co_located_fallback"], True)
        eq("co-located copy: there is no plugin root", info["plugin_root"], None)
        agree("co-located copy: describe and plugin_root agree", copy_script)

        # -- deeper than the walk-up limit ------------------------------
        # MAX_WALK_UP candidates are tried: the starting directory and
        # MAX_WALK_UP - 1 ancestors.  Both sides of that boundary are checked,
        # so raising or lowering the constant cannot go unnoticed.
        deep = os.path.join(tmp, "deep")
        deep_shared = os.path.join(deep, *SHARED_REL)
        _touch(os.path.join(deep_shared, "slugify.py"))
        rungs = ["d%d" % i for i in range(MAX_WALK_UP)]
        inside = _touch(os.path.join(deep, *(rungs[:-1] + ["thing.py"])))
        outside = _touch(os.path.join(deep, *(rungs + ["thing.py"])))
        eq("walk-up limit: the last reachable ancestor still resolves",
           find_shared_scripts(start=inside), deep_shared)
        msg = refuses("walk-up limit: one level deeper does not",
                      find_shared_scripts, start=outside)
        says("walk-up limit: the error lists the locations it searched", msg, deep)
        eq("walk-up limit: plugin_root is None beyond it",
           plugin_root(start=outside), None)
        agree("walk-up limit: describe and plugin_root agree", outside)
        trace = []
        try:
            find_shared_scripts(start=outside, _trace=trace)
        except SharedLayerNotFound:
            pass
        eq("walk-up limit: exactly MAX_WALK_UP ancestors are tried",
           len([t for t in trace if t[0] == "walk-up"]), MAX_WALK_UP)

        # -- $OBSIDIAN_VAULT_SHARED, set correctly ----------------------
        set_env(shared)
        eq("env override: rescues a skill that has no shared/ above it",
           find_shared_scripts(start=lone_script), shared)
        info = describe(start=lone_script)
        eq("env override: resolved via the environment", info["via"], "env")
        eq("env override: plugin_root is the overridden plugin",
           plugin_root(start=lone_script), plug)
        agree("env override: describe and plugin_root agree", lone_script)
        eq("env override: authoritative even where the walk-up would succeed",
           find_shared_scripts(start=nested_script), shared)

        # -- $OBSIDIAN_VAULT_SHARED set to a FILE -----------------------
        afile = _touch(os.path.join(tmp, "not-a-directory.py"))
        set_env(afile)
        msg = refuses("env override is a file: refuses",
                      find_shared_scripts, start=script, module="slugify")
        says("env override is a file: the error names the variable", msg, ENV_VAR)
        says("env override is a file: the error names the offending path", msg, afile)
        says("env override is a file: the error says what is wrong",
             msg, "not a directory")
        says("env override is a file: the error names the fix", msg, "Unset it")
        info = describe(start=script)
        eq("env override is a file: describe reports failure", info["ok"], False)
        eq("env override is a file: describe has no plugin_root",
           info["plugin_root"], None)
        agree("env override is a file: describe and plugin_root agree", script)

        # -- $OBSIDIAN_VAULT_SHARED set to a directory without the modules --
        # The regression: this used to RESOLVE.  An empty directory went onto
        # sys.path, describe() announced a nonsense plugin root two levels
        # above it, and the caller's next line died with the bare
        # ModuleNotFoundError this module's docstring exists to prevent.
        hollow = os.path.join(tmp, "hollow", "lib", "py")
        os.makedirs(hollow)
        set_env(hollow)
        msg = refuses("env override without the modules: refuses",
                      find_shared_scripts, start=script, module="slugify")
        says("env override without the modules: the error names the variable",
             msg, ENV_VAR)
        says("env override without the modules: the error names the directory",
             msg, hollow)
        says("env override without the modules: the error names the module file",
             msg, "slugify.py")
        says("env override without the modules: the error names the fix",
             msg, "shared/scripts/")
        says("env override without the modules: the error is not the bare one",
             msg, "says nothing about what is wrong")
        refuses("env override without the modules: ensure_shared_on_path refuses "
                "too, so the caller never reaches its import",
                ensure_shared_on_path, start=script, module="slugify")
        info = describe(start=script)
        eq("env override without the modules: describe reports failure",
           info["ok"], False)
        eq("env override without the modules: describe invents no plugin root",
           info["plugin_root"], None)
        agree("env override without the modules: describe and plugin_root agree",
              script)
        # Negative control: the same override with the module in it must work,
        # or the new guard has simply broken the escape hatch.
        _touch(os.path.join(hollow, "slugify.py"))
        eq("env override holding the module: resolves",
           find_shared_scripts(start=script, module="slugify"), hollow)
        eq("env override holding the module: no plugin root above it",
           plugin_root(start=script), None)
        agree("env override holding the module: describe and plugin_root agree",
              script)

        # -- a hollow override sitting INSIDE a real plugin ---------------
        # The fixture above cannot tell this one: `tmp/hollow/lib/py` has no
        # `shared/scripts` two levels up, so `_root_of` answers None on both
        # sides and `agree` passes by construction, whatever the two functions
        # did to get there.  Put the same empty directory inside a plugin that
        # IS installed and `_root_of` resolves -- and then the `if module`
        # guard in `find_shared_scripts`, which only `describe` used to arm,
        # decided the answer: `describe()` raised and reported no root while
        # `plugin_root()` named the plugin, and `ensure_shared_on_path()` put
        # the empty directory at `sys.path[0]` for the caller's next line to
        # die on.  That is `_root_of`'s own bug one layer up, and the module
        # under test is the one thing in the tree three skills trust to say
        # where the shared layer is.
        inner = os.path.join(tmp, "host-plugin")
        _touch(os.path.join(inner, *(SHARED_REL + ("slugify.py",))))
        inner_hollow = os.path.join(inner, "lib", "py")
        os.makedirs(inner_hollow)
        set_env(inner_hollow)
        eq("hollow override inside a real plugin: plugin_root invents no root",
           plugin_root(start=script), None)
        agree("hollow override inside a real plugin: describe and plugin_root "
              "agree", script)
        refuses("hollow override inside a real plugin: ensure_shared_on_path "
                "refuses rather than putting it on sys.path",
                ensure_shared_on_path, start=script)
        # Negative control again: with the module present the override is the
        # escape hatch it is meant to be, and now there IS a root to report.
        _touch(os.path.join(inner_hollow, "slugify.py"))
        eq("override inside a real plugin, holding the module: plugin_root is "
           "that plugin", plugin_root(start=script), inner)
        agree("override inside a real plugin, holding the module: describe and "
              "plugin_root agree", script)
        set_env(None)

        # -- the BOOTSTRAP snippet --------------------------------------
        # tests/test_conventions.py asserts every copy in the tree is
        # byte-identical to BOOTSTRAP.  Nothing asserted that BOOTSTRAP itself
        # still does what this module does -- and a dozen byte-identical
        # copies of the wrong thing is still the wrong thing.
        eq("--bootstrap prints BOOTSTRAP verbatim",
           _capture(main, ["--bootstrap"]), BOOTSTRAP)
        try:
            compile(BOOTSTRAP, "<BOOTSTRAP>", "exec")
            compiles, why = True, ""
        except SyntaxError as exc:
            compiles, why = False, str(exc)
        yes("BOOTSTRAP compiles", compiles, why)
        says("BOOTSTRAP reads the documented variable", BOOTSTRAP, '"%s"' % ENV_VAR)
        says("BOOTSTRAP inlines MAX_WALK_UP", BOOTSTRAP, "range(%d)" % MAX_WALK_UP)
        says("BOOTSTRAP inlines SHARED_REL", BOOTSTRAP,
             ", ".join('"%s"' % part for part in SHARED_REL))

        for label, start in [("inside a full plugin", script),
                             ("inside a nested plugin", nested_script),
                             ("at the walk-up limit", inside),
                             ("beyond the walk-up limit", outside),
                             ("extracted alone", lone_script)]:
            try:
                want = find_shared_scripts(start=start)
            except SharedLayerNotFound:
                want = None
            path, err = _run_bootstrap(start)
            eq("BOOTSTRAP resolves as find_shared_scripts does, %s" % label,
               path[0] if path else None, want)
            if want is None:
                says("BOOTSTRAP %s: names the locations it searched" % label,
                     err, "Looked for")
                says("BOOTSTRAP %s: names the override" % label, err, ENV_VAR)
                says("BOOTSTRAP %s: forbids a second copy" % label,
                     err, "Do NOT paste a second copy")
            else:
                eq("BOOTSTRAP %s: the script's own directory goes last" % label,
                   path[-1], os.path.dirname(os.path.abspath(start)))

        # The snippet is deliberately STRICTER than find_shared_scripts: it
        # has no co-located step, because it cannot know which module the
        # script is about to import.  That asymmetry is documented, so it is
        # asserted rather than left to be "fixed" by a future reader.
        path, err = _run_bootstrap(copy_script)
        eq("BOOTSTRAP has no co-located fallback", path, None)
        eq("...where find_shared_scripts does have one",
           find_shared_scripts(start=copy_script, module="slugify"), copy_dir)

        # A copy dropped beside the script must not shadow the shared one.
        _touch(os.path.join(here, "slugify.py"))
        path, _ = _run_bootstrap(script)
        eq("BOOTSTRAP: shared/scripts/ is first even with a local copy present",
           path[0] if path else None, shared)
        eq("BOOTSTRAP: the script's own directory is last",
           path[-1] if path else None, here)
        yes("BOOTSTRAP: shared/scripts/ outranks the local copy",
            path is not None and path.index(shared) < path.index(here))

        set_env(nested_shared)
        path, _ = _run_bootstrap(script)
        eq("BOOTSTRAP: the override is consulted first, by the snippet itself",
           path[0] if path else None, nested_shared)
        set_env(afile)
        path, err = _run_bootstrap(script)
        eq("BOOTSTRAP: an override that is not a directory does not resolve",
           path, None)
        says("BOOTSTRAP: and the SystemExit says where it looked", err, afile)
        set_env(None)
    finally:
        os.environ.pop(ENV_VAR, None)
        if saved_env is not None:
            os.environ[ENV_VAR] = saved_env
        sys.path[:] = saved_path
        shutil.rmtree(tmp, ignore_errors=True)

    failures = ["%s: %s" % (name, detail) for name, ok, detail in cases if not ok]
    return {
        "total": len(cases),
        "passed": len(cases) - len(failures),
        "failed": len(failures),
        "failures": failures,
        "ok": not failures,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(
        prog="plugin_paths.py",
        description="Locate the obsidian plugin's shared/scripts/ folder.",
    )
    p.add_argument("--from", dest="start", metavar="PATH",
                   help="resolve as if called from this file or directory")
    p.add_argument("--module", default="slugify", metavar="NAME",
                   help="module the co-located fallback looks for (default: slugify)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--bootstrap", action="store_true",
                   help="print the canonical bootstrap snippet and exit")
    p.add_argument("--test", action="store_true",
                   help="run the inline self-test and exit")
    args = p.parse_args(argv)

    if args.test:
        result = run_self_test()
        for failure in result["failures"]:
            print("FAIL: " + failure, file=sys.stderr)
        print("%d/%d self-test cases pass" % (result["passed"], result["total"]))
        return 0 if result["ok"] else 1

    if args.bootstrap:
        sys.stdout.write(BOOTSTRAP)
        return 0

    info = describe(start=args.start, module=args.module)
    if args.json:
        print(json.dumps(info, indent=2))
        return 0 if info["ok"] else 1

    if info["ok"]:
        print("shared/scripts : %s" % info["shared_scripts"])
        print("resolved via   : %s" % info["via"])
        print("plugin root    : %s" % (info["plugin_root"] or "(none -- skill extracted alone)"))
        if info["co_located_fallback"]:
            print("WARNING: resolved to a co-located copy, not the plugin's shared layer.\n"
                  "         That copy can drift from shared/scripts/. Reinstall the full\n"
                  "         plugin tree when you can.")
        return 0

    print(info["error"], file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
