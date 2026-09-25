#!/usr/bin/env python3
"""Check the installed PDF and image parsers against their security floors.

PDF reading and splitting use pypdf; figure extraction and page rendering use
PyMuPDF and Pillow. They parse untrusted PDFs and images, and an import-only
check can accept an old vulnerable release. Run this with the interpreter a
PDF or image workflow will use, after creating its environment:

    python3 shared/scripts/check_parsers.py          # check this interpreter
    python3 shared/scripts/check_parsers.py --test   # inline self-tests

``MINIMUMS`` are the floors in ``requirements.txt`` (pypdf) and
``skills/figure-extract/scripts/requirements.txt`` (PyMuPDF, Pillow); keep
them synchronized. Releases compare numerically, with missing components read
as zero, so ``13`` and ``7.0`` are later releases. A prerelease or development
build of a floor release, such as ``12.3.0rc1``, ``12.3rc1`` or
``6.16.1.dev0``, precedes that release and fails.

The check itself needs only the standard library and Python 3.10+. The parsers
are imported inside ``main()``, after their versions pass.
Exit codes: 0 every floor met and every parser imports, 1 otherwise.
"""

import argparse
import importlib
import re
import sys
from importlib.metadata import PackageNotFoundError, version

__all__ = [
    "MINIMUMS",
    "MIN_PYTHON",
    "IMPORTS",
    "find_problems",
    "failure_message",
    "installed_versions",
    "main",
    "run_self_test",
]

#: Distribution name -> lowest accepted release.
MINIMUMS = {
    "pypdf": (6, 16, 1),
    "PyMuPDF": (1, 28, 0),
    "Pillow": (12, 3, 0),
}

#: The plugin runtime floor, which the parser floors also require.
MIN_PYTHON = (3, 10)

#: Distribution name -> module that must import once its version passes.
#: PyMuPDF imports as ``pymupdf``; its legacy ``fitz`` alias is not used.
IMPORTS = {
    "pypdf": "pypdf",
    "PyMuPDF": "pymupdf",
    "Pillow": "PIL.Image",
}

_RELEASE = re.compile(r"^\d+(?:\.\d+)*")
_PRERELEASE = ("a", "b", "rc", ".dev", "dev")


def _dotted(parts):
    return ".".join(str(part) for part in parts)


def find_problems(python_version, installed, minimums=None):
    """Return one message per unmet floor; an empty list means all are met.

    ``python_version`` is a ``sys.version_info``-like tuple. ``installed``
    maps each distribution name to its installed version string, or to
    ``None`` when the distribution is not installed.
    """
    minimums = MINIMUMS if minimums is None else minimums
    problems = []
    if tuple(python_version[:2]) < MIN_PYTHON:
        problems.append("Python %s or newer is required (found %s)"
                        % (_dotted(MIN_PYTHON), _dotted(python_version[:3])))
    for package, minimum in minimums.items():
        found = installed.get(package)
        if found is None:
            problems.append("%s is not installed" % package)
            continue
        match = _RELEASE.match(found)
        release = (tuple(int(part) for part in match.group().split("."))
                   if match else ())
        suffix = found[match.end():].lower() if match else ""
        # Pad both sides to one width: `13` is 13.0.0, and `12.3.0.0rc1` is
        # still a prerelease of the 12.3.0 floor.
        width = max(len(release), len(minimum)) if release else 0
        release += (0,) * (width - len(release))
        floor = tuple(minimum) + (0,) * (width - len(minimum))
        prerelease_at_floor = (release == floor
                               and suffix.startswith(_PRERELEASE))
        if release < floor or prerelease_at_floor:
            problems.append("%s %s is below %s"
                            % (package, found, _dotted(minimum)))
    return problems


def failure_message(problems):
    """The one-line report for a failed check."""
    return "dependency check failed: " + "; ".join(problems)


def installed_versions(names=None):
    """Installed version of each distribution, or ``None`` when absent."""
    found = {}
    for name in (MINIMUMS if names is None else names):
        try:
            found[name] = version(name)
        except PackageNotFoundError:
            found[name] = None
    return found


def _import_problems():
    """Import each parser; report any that fails to load."""
    problems = []
    for package, module in IMPORTS.items():
        try:
            importlib.import_module(module)
        except Exception as exc:  # a broken build can raise more than ImportError
            problems.append("%s does not import as %s (%s: %s)"
                            % (package, module, type(exc).__name__, exc))
    return problems


def run_self_test(verbose=False):
    """Check the floor logic on fixed inputs; no parser needs to be installed."""
    floors = {"pypdf": "6.16.1", "PyMuPDF": "1.28.0", "Pillow": "12.3.0"}

    def with_versions(**changes):
        versions = dict(floors)
        versions.update(changes)
        return versions

    current = (3, 12, 4)
    cases = [
        ("passing versions exactly at the floors", current, floors, []),
        ("later releases pass", (3, 10, 0),
         {"pypdf": "6.17.0", "PyMuPDF": "1.28.1", "Pillow": "13.0.0"}, []),
        ("releases compare numerically, not as text", current,
         with_versions(pypdf="10.0.0"), []),
        ("a below-floor patch release fails", current,
         with_versions(pypdf="6.16.0"), ["pypdf 6.16.0 is below 6.16.1"]),
        ("a below-floor minor release fails", current,
         with_versions(Pillow="12.2.9"), ["Pillow 12.2.9 is below 12.3.0"]),
        ("a textually larger but older minor release fails", current,
         with_versions(pypdf="6.9.0"), ["pypdf 6.9.0 is below 6.16.1"]),
        ("a release candidate of the floor fails", current,
         with_versions(Pillow="12.3.0rc1"),
         ["Pillow 12.3.0rc1 is below 12.3.0"]),
        ("a beta of the floor fails", current,
         with_versions(PyMuPDF="1.28.0b2"),
         ["PyMuPDF 1.28.0b2 is below 1.28.0"]),
        ("a development build of the floor fails", current,
         with_versions(pypdf="6.16.1.dev0"),
         ["pypdf 6.16.1.dev0 is below 6.16.1"]),
        ("a post-release of the floor passes", current,
         with_versions(pypdf="6.16.1.post1"), []),
        ("a local build of the floor passes", current,
         with_versions(Pillow="12.3.0+local"), []),
        ("a prerelease of a later release passes", current,
         with_versions(PyMuPDF="1.29.0rc1"), []),
        ("a two-component later release passes", current,
         with_versions(pypdf="7.0"), []),
        ("a one-component later release passes", current,
         with_versions(Pillow="13"), []),
        ("a two-component older release fails", current,
         with_versions(Pillow="12.2"), ["Pillow 12.2 is below 12.3.0"]),
        ("a two-component prerelease of the floor fails", current,
         with_versions(Pillow="12.3rc1"), ["Pillow 12.3rc1 is below 12.3.0"]),
        ("a four-component prerelease of the floor fails", current,
         with_versions(Pillow="12.3.0.0rc1"),
         ["Pillow 12.3.0.0rc1 is below 12.3.0"]),
        ("a four-component later release passes", current,
         with_versions(pypdf="6.16.1.1"), []),
        ("an unreadable version fails", current,
         with_versions(Pillow="unknown"), ["Pillow unknown is below 12.3.0"]),
        ("a missing package fails", current,
         with_versions(PyMuPDF=None), ["PyMuPDF is not installed"]),
        ("an absent entry counts as missing", current,
         {"pypdf": "6.16.1", "Pillow": "12.3.0"},
         ["PyMuPDF is not installed"]),
        ("Python below 3.10 fails", (3, 9, 18), floors,
         ["Python 3.10 or newer is required (found 3.9.18)"]),
        ("every problem is reported together", (3, 9, 0),
         {"pypdf": None, "PyMuPDF": "1.27.4", "Pillow": "12.3.0a1"},
         ["Python 3.10 or newer is required (found 3.9.0)",
          "pypdf is not installed",
          "PyMuPDF 1.27.4 is below 1.28.0",
          "Pillow 12.3.0a1 is below 12.3.0"]),
    ]
    passed = failed = 0

    def record(name, got, expected):
        nonlocal passed, failed
        ok = got == expected
        if verbose or not ok:
            print("%s: %s" % ("PASS" if ok else "FAIL", name))
        if ok:
            passed += 1
        else:
            failed += 1
            print("  expected %r\n  got      %r" % (expected, got))

    for name, python_version, installed, expected in cases:
        record(name, find_problems(python_version, installed), expected)
    record("the failure message joins every problem",
           failure_message(["pypdf is not installed",
                            "Pillow 12.2.0 is below 12.3.0"]),
           "dependency check failed: pypdf is not installed; "
           "Pillow 12.2.0 is below 12.3.0")
    absent = "obsidian-skills-no-such-distribution"
    record("an absent distribution is reported as not installed",
           installed_versions([absent]), {absent: None})
    record("every floor has a module to import",
           sorted(IMPORTS), sorted(MINIMUMS))
    print("%d/%d self-test cases pass" % (passed, passed + failed))
    return failed == 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Check the installed PDF and image parsers against their "
                    "security floors.")
    parser.add_argument("--test", action="store_true",
                        help="run the self-tests")
    parser.add_argument("--verbose", action="store_true",
                        help="with --test, list every case")
    args = parser.parse_args(argv)
    if args.test:
        return 0 if run_self_test(args.verbose) else 1
    installed = installed_versions()
    problems = find_problems(sys.version_info, installed)
    if not problems:
        problems = _import_problems()
    if problems:
        sys.stderr.write(failure_message(problems) + "\n")
        return 1
    print("parser check passed: Python %s; %s"
          % (_dotted(sys.version_info[:3]),
             "; ".join("%s %s" % (name, installed[name]) for name in MINIMUMS)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
