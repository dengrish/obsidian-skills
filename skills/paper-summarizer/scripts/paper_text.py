#!/usr/bin/env python3
"""Read a PDF document's text by page, and check a claim against it.

Four modes, all over one page-indexed extraction:

  ``--pages``     the text, one labelled block per page.  The page numbers are
                  physical (1-indexed positions in the file), which is what a
                  `#page=N` anchor means (`CONVENTIONS.md` §7).
  ``--find STR``  which pages contain STR.  **Repeatable, and it exits 1 when
                  any needle is unfound** — that exit code is the whole point:
                  it turns "verify every number against the source" from an
                  intention into a command with a result.
  ``--cites``     how often each figure number appears anywhere in the text,
                  its own caption included.  A non-arbitrary tiebreak when
                  choosing which figures a summary carries.  The labels match
                  `paper_scan.py`'s on-disk ones, so pass the same
                  ``--ed-prefix`` the extraction run used or Extended Data
                  figures will be counted under a label no file carries.
  ``--sections``  where the standard sections start.  Finds the pages holding
                  the abstract, methods, results, limitations and
                  data-availability statements, and also the funding,
                  conflict-of-interest and registration ones -- which
                  paper-summarizer never reports (references/note-format.md) and
                  reads only to see what a reporting guideline asks for and
                  the paper does not say.  A heading is a short line that is
                  *only* a heading; prose that merely opens with a section
                  word is not one.

Matching is deliberately forgiving, because a PDF's text layer is not the
page: Unicode is NFKC-folded, the six dash characters and the curly quotes are
mapped to ASCII, whitespace is collapsed, and case is ignored unless
``--exact``.  A needle that still misses is retried with every space and
hyphen removed, which is what recovers a word the PDF broke across a line —
and a hit found only that way is reported as ``loose``, never as a clean one.

    python3 '<skill>/scripts/paper_text.py' '<vault>/Sources/PDFs/Doe_Foo_2025.pdf' --sections
    python3 '<skill>/scripts/paper_text.py' '<document>.pdf' --find '13.2 months' --find 'hazard ratio 0.62'

The paths are the user's and the needles come from the document, so both are
single-quoted (`CONVENTIONS.md` §1b).

PyMuPDF is used when present (pdf-figure-extractor already depends on it) and
pypdf otherwise; neither is imported until a PDF is actually opened.
"""

import argparse
import json
import os
import re
import sys
import unicodedata


class _Encrypted(RuntimeError):
    """A user-password PDF: readable only after decryption, not a corrupt file."""


class _NoBackend(RuntimeError):
    """Neither PDF library is installed -- a different failure from a bad file."""

#: Characters a PDF's text layer uses that a typed needle will not.
_TRANSLATE = {
    0x00AD: None,        # soft hyphen
    0x2010: "-", 0x2011: "-", 0x2012: "-", 0x2013: "-", 0x2014: "-",
    0x2212: "-",         # minus sign, the classic false negative in a p-value
    0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"',
    0x00A0: " ", 0x2007: " ", 0x2009: " ", 0x202F: " ",
}

#: A reference to a figure in body text or in a caption.  Panel letters are
#: tolerated and dropped (`Fig. 3b` counts toward figure 3), and the label is
#: normalised to the
#: on-disk form: dots become dashes, and a marker word *before* the keyword
#: folds into the namespace prefix the extractor writes — §8b, whose default
#: is that `Supplementary`, `Suppl.`, `Supp.` and `Extended Data` all land in
#: `S`.  Without the marker group `Supplementary Figure 1` counted toward
#: figure 1, which is a different figure.
_FIG_REF = re.compile(
    r"(?:\b(?P<marker>supplementary|supplemental|suppl\.|supp\.|extended\s+data)\s+)?"
    r"\bfig(?:ure)?(?P<plural>s)?\.?\s*"
    # A hierarchical label is `1.2` or `1-2`; a *range* is `1-3` after a plural.
    # Reading "Figures 1-3" as one label `1-3` scores a figure no run can write
    # and costs figures 1, 2 and 3 a citation each -- and the en dash papers
    # actually use folds to `-` before this ever runs, so it is the common case.
    r"(?P<label>(?:si|ed|s)?\d+(?:\.\d+)*"
    r"(?P<tail>-(?:si|ed|s)?\d+(?:\.\d+)*)?)"
    r"[a-z]?\b(?!\s*%)", re.I)

#: Further labels after a plural reference: ``Figures 1, 2 and 3``. The
#: figure keyword establishes the namespace once; later labels inherit its
#: Supplementary / Extended Data marker.
_FIG_MORE = re.compile(
    r"\s*(?:,\s*(?:and\s+)?|and\s+|&\s*)"
    r"(?P<label>(?:si|ed|s)?\d+(?:\.\d+)*"
    r"(?:-(?:si|ed|s)?\d+(?:\.\d+)*)?)"
    r"[a-z]?\b", re.I)

_MAX_FIG_RANGE = 20

#: The marker set is exactly `pdf-figure-extractor`'s, and deliberately so:
#: a marker this counts but the extractor cannot match scores a figure under a
#: label no run can ever write, so the tiebreak recommends carrying a file that
#: does not exist.  `Supporting Information` used to be here and is not a
#: marker word anywhere in the extractor -- only the `SI` *number* prefix of
#: `Figure SI1` is, and that arrives through the label group, not this one.
#:
#: `Extended Data` is the one marker that moves: §8b folds it into `S` by
#: default and `--ed-prefix ED` gives it its own namespace, so the mapping has
#: to be told which extraction run it is being compared against.
_ED_MARKER = "extended data"

#: Section headings worth locating, and the words that start them.  Written as
#: prefixes of a normalised line so `Conflicts of Interest Statement` and
#: `Conflict of interest:` both land in one bucket.
_SECTIONS = [
    ("abstract", ("abstract", "summary")),
    ("introduction", ("introduction", "background")),
    ("methods", ("methods", "materials and methods", "method",
                 "experimental procedures", "study design")),
    ("results", ("results", "findings")),
    ("discussion", ("discussion",)),
    ("limitations", ("limitations", "limitation", "study limitations")),
    ("conclusion", ("conclusion", "conclusions")),
    ("funding", ("funding", "financial support", "grant support",
                 "role of the funding source")),
    ("conflicts", ("conflict of interest", "conflicts of interest",
                   "competing interests", "declaration of interests",
                   "disclosure", "disclosures")),
    ("data", ("data availability", "data and code availability",
              "code availability", "availability of data")),
    ("ethics", ("ethics", "ethical approval", "institutional review")),
    ("registration", ("trial registration", "registration", "preregistration",
                      "pre-registration")),
    ("references", ("references", "bibliography", "literature cited")),
]


def normalize(text, fold_case=True):
    """The comparable form of a chunk of text."""
    text = unicodedata.normalize("NFKC", text).translate(_TRANSLATE)
    text = re.sub(r"\s+", " ", text).strip()
    return text.casefold() if fold_case else text


def squash(text):
    """`normalize` with the spacing and hyphenation thrown away too."""
    return re.sub(r"[\s-]+", "", text)


def read_pages(path):
    """[page text], 0-indexed in the list, 1-indexed to the reader.

    Raises RuntimeError with an actionable message when neither backend is
    installed — silently returning nothing would read as "the document says
    nothing", which is the worst possible answer for a verification tool.
    """
    # `pymupdf` first: it is the module name PyMuPDF has moved to, and the
    # legacy `fitz` alias prints a deprecation warning on every import, which
    # lands in the middle of a verification report and reads like a failure.
    doc_mod = None
    for name in ("pymupdf", "fitz"):
        try:
            doc_mod = __import__(name)
            break
        except ImportError:
            continue
    if doc_mod is not None:
        with doc_mod.open(path) as doc:
            # PyMuPDF deliberately opens several document formats. An HTML
            # error page merely named `.pdf` therefore used to pass `--find`
            # and falsely verify any claim whose text appeared in that page.
            if not getattr(doc, "is_pdf", False):
                fmt = (getattr(doc, "metadata", None) or {}).get("format")
                raise ValueError(
                    "%s is not a PDF (PyMuPDF opened it as %s)" %
                    (path, fmt or "another document format"))
            # A user-password PDF OPENS fine and then raises on the first
            # get_text(), landing in the generic could-not-be-opened handler —
            # whose advice ("the file needs replacing") is wrong here:
            # re-downloading yields the same encrypted file; decrypting fixes
            # it.  batch_extract and organize special-case this the same way.
            if getattr(doc, "needs_pass", False):
                raise _Encrypted(
                    "%s is encrypted and password-protected, so no text can "
                    "be read from it. This is not corruption and not a scan; "
                    "re-downloading it changes nothing. Decrypt it first "
                    "(`qpdf --decrypt --password='<pw>' 'in.pdf' 'out.pdf'`) "
                    "and run this script on the result." % path)
            if len(doc) == 0:
                return []
            return [page.get_text() or "" for page in doc]
    try:
        import pypdf
    except ImportError:
        raise _NoBackend(
            "neither PyMuPDF nor pypdf is installed, so this script cannot "
            "read a PDF at all. Use a virtual environment with the plugin "
            "dependencies; see shared/RUNTIME.md.\n"
            "Do not fall back to reading the document by eye and reporting the "
            "verification as done.")
    reader = pypdf.PdfReader(path)
    if getattr(reader, "is_encrypted", False):
        # An owner-password-only PDF opens with the empty user password; a
        # user-password one does not, and is _Encrypted, not corrupt.
        try:
            _ok = reader.decrypt("")
        except Exception:
            _ok = 0
        if not _ok:
            raise _Encrypted(
                "%s is encrypted and password-protected, so no text can be "
                "read from it. This is not corruption and not a scan; "
                "re-downloading it changes nothing. Decrypt it first "
                "(`qpdf --decrypt --password='<pw>' 'in.pdf' 'out.pdf'`) "
                "and run this script on the result." % path)
    return [(p.extract_text() or "") for p in reader.pages]


def find(pages, needle, fold_case=True):
    """{'needle', 'pages', 'loose_pages'} — where a string occurs.

    `pages` are clean hits; `loose_pages` matched only after spacing and
    hyphens were removed, and are reported separately because that relaxation
    can join two words that the paper kept apart.
    """
    want = normalize(needle, fold_case)
    want_sq = squash(want)
    hits, loose = [], []
    for i, raw in enumerate(pages, start=1):
        norm = normalize(raw, fold_case)
        if want and want in norm:
            hits.append(i)
        elif want_sq and want_sq in squash(norm):
            loose.append(i)
    return {"needle": needle, "pages": hits, "loose_pages": loose}


def _range_labels(label, plural):
    """Expand an unambiguous plural range, otherwise return ``[label]``.

    ``Figures 1-3`` and ``Figures 1.2-1.4`` are ranges. A singular
    ``Figure 1-3`` remains one chapter-style label, and a descending or very
    wide span remains literal because books use the same spelling.
    """
    if not plural or label.count("-") != 1:
        return [label]
    low, high = label.split("-", 1)
    endpoint = re.compile(
        r"(?P<prefix>si|ed|s)?(?P<number>\d+(?:\.\d+)*)\Z", re.I)
    lo_match, hi_match = endpoint.fullmatch(low), endpoint.fullmatch(high)
    if not lo_match or not hi_match:
        return [label]
    lo_prefix = (lo_match.group("prefix") or "").upper()
    hi_prefix = (hi_match.group("prefix") or "").upper()
    # The namespace may be written once (S1-3) or at both endpoints
    # (S1-S3). A prefix that appears only on the upper endpoint, or two
    # different prefixes, does not unambiguously describe one range.
    if (hi_prefix and not lo_prefix) or (hi_prefix and hi_prefix != lo_prefix):
        return [label]
    lo_parts = lo_match.group("number").split(".")
    hi_parts = hi_match.group("number").split(".")
    if (len(lo_parts) != len(hi_parts)
            or lo_parts[:-1] != hi_parts[:-1]
            or not lo_parts[-1].isdigit() or not hi_parts[-1].isdigit()):
        return [label]
    lo, hi = int(lo_parts[-1]), int(hi_parts[-1])
    if not 0 < hi - lo <= _MAX_FIG_RANGE:
        return [label]
    hierarchy = ".".join(lo_parts[:-1])
    return [lo_prefix + (hierarchy + "." if hierarchy else "") + str(n)
            for n in range(lo, hi + 1)]


def cites(pages, ed_prefix="S"):
    """{normalised figure label: times referred to}, over the whole document."""
    if ed_prefix not in ("S", "ED"):
        raise ValueError("ed_prefix must be 'S' or 'ED'")
    counts = {}
    for raw in pages:
        text = normalize(raw, fold_case=False)
        for m in _FIG_REF.finditer(text):
            marker = m.group("marker")
            labels = _range_labels(m.group("label"), bool(m.group("plural")))
            pos = m.end()
            if m.group("plural"):
                while True:
                    more = _FIG_MORE.match(text, pos)
                    if not more:
                        break
                    labels.extend(_range_labels(more.group("label"), True))
                    pos = more.end()
            for label in labels:
                label = label.replace(".", "-")
                label = re.sub(r"\A(si|ed|s)", lambda x: x.group(1).upper(),
                               label, flags=re.I)
                if marker and not label[0].isalpha():
                    clean_marker = re.sub(r"\s+", " ", marker).lower().rstrip(".")
                    label = (ed_prefix if clean_marker == _ED_MARKER else "S") + label
                counts[label] = counts.get(label, 0) + 1
    return counts


def sections(pages):
    """{section: [pages where a heading for it starts]}.

    A heading is a *short line that is only the heading*.  Matching a line's
    first word was the old rule and it fired on ordinary prose -- "Results were
    consistent across all three cohorts.", "Limitations of this approach are
    discussed below." -- which is worse than finding nothing, because the
    results-page reading pass uses that range to decide which numbers to inspect.
    It also *missed* the common real forms: "5. Empirical Results" (the section
    word is not first) and "7. Discussion, Limitations, Conclusion" (three
    sections on one line).

    So: strip any leading numbering, reject anything punctuated like a sentence,
    split the rest on the separators a compound heading uses, and require each
    part to be a handful of words ending in a section name.
    """
    out = {}
    for i, raw in enumerate(pages, start=1):
        for line in raw.splitlines():
            norm = normalize(line).strip()
            norm = re.sub(r"\A[\s#*]*(?:[0-9]+(?:\.[0-9]+)*|[IVXLC]+)[.)]?\s+",
                          "", norm)
            # "Funding: supported by Acme Pharma." is a heading with its
            # content on the same line, which is how most journals set the
            # statements this looks for.  Take what precedes the first colon
            # before applying heading length limits: the statement itself
            # can be much longer than a heading.
            cands = [norm.casefold()]
            if ":" in norm:
                cands.append(norm.split(":", 1)[0].casefold())
            for cand in cands:
                cand = cand.strip(" :\u2014\u2013-*#")
                if not cand or len(cand) > 60 or len(cand.split()) > 8:
                    continue
                if cand.endswith((".", ";")) or cand[-1:].isdigit():
                    continue                  # a sentence, or a wrapped line
                for part in re.split(r"[,/&]| and (?=\w)", cand):
                    part = part.strip(" .:-")
                    if not part or len(part.split()) > 4:
                        continue
                    for name, starts in _SECTIONS:
                        if any(part == s or part.endswith(" " + s) for s in starts):
                            out.setdefault(name, [])
                            if i not in out[name]:
                                out[name].append(i)
                            break
    return out


def _render_find(results):
    lines, missing = [], 0
    for r in results:
        if r["pages"]:
            lines.append("FOUND   %-40r page(s) %s"
                         % (r["needle"],
                            ", ".join(str(p) for p in r["pages"])))
        elif r["loose_pages"]:
            lines.append("loose   %-40r page(s) %s  (matched only with "
                         "spacing and hyphens removed -- read the page before "
                         "citing it)"
                         % (r["needle"],
                            ", ".join(str(p) for p in r["loose_pages"])))
        else:
            missing += 1
            lines.append("MISSING %-40r not on any page. Cut the claim or "
                         "fix it; do not soften it." % (r["needle"],))
    loose = sum(1 for r in results if not r["pages"] and r["loose_pages"])
    exact = len(results) - missing - loose
    lines.append("")
    lines.append("%d of %d needle(s) found exactly; %d loose; %d missing"
                 % (exact, len(results), loose, missing))
    if loose:
        lines.append("A loose match is NOT a verification. Squashing spaces and "
                     "hyphens is what recovers a word the PDF broke across a "
                     "line -- and it is also what joins two things the document "
                     "kept apart ('...to 2015. 3 patients...' matches '2015.3'). "
                     "Open each loose page and read it before citing.")
    return "\n".join(lines), missing


def _build_parser():
    p = argparse.ArgumentParser(
        description="Read a PDF document by page, and check claims against it.")
    p.add_argument("pdf", nargs="?", help="the PDF to read")
    p.add_argument("--pages", action="store_true",
                   help="print the text, one labelled block per page")
    p.add_argument("--find", action="append", default=[], metavar="STR",
                   help="report which pages contain STR (repeatable)")
    p.add_argument("--exact", action="store_true",
                   help="make --find case-sensitive")
    p.add_argument("--cites", action="store_true",
                   help="how often each figure number is referred to")
    p.add_argument("--ed-prefix", choices=("S", "ED"), default="S",
                   help="namespace for `Extended Data Figure N` in --cites; "
                        "must match the --ed-prefix the extraction run used "
                        "(default: S, which is that run's default too)")
    p.add_argument("--sections", action="store_true",
                   help="where the standard sections start")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--test", action="store_true", help="run the self-test")
    return p


# ---------------------------------------------------------------------------
# self-test -- no PDF needed: everything above read_pages is pure text
# ---------------------------------------------------------------------------

_PAGES = [
    "Introduction\nWe studied 412 adults.",
    "Results\nMedian overall survival was 13.2 months (95% CI 11.1–15.4),\n"
    "a hazard ratio of 0.62 versus chemo­therapy alone (Fig. 2a).\n"
    "Progression-\nfree survival improved by 4.2 months.",
    "Figure 2. Survival curves. See also Figure 2 and Supplementary Figure 1.\n"
    "Funding: supported by Acme Pharma.\nConflict of interest: none declared.",
]


def run_self_test():
    bad = 0
    n = 0

    def case(label, got, want):
        nonlocal bad, n
        n += 1
        if got != want:
            bad += 1
            print("FAIL %s -> %r, expected %r" % (label, got, want))

    # The en-dash in the CI and the soft hyphen in "chemotherapy" are exactly
    # the two characters a typed needle will not carry.
    case("dash-folded CI",
         find(_PAGES, "95% CI 11.1-15.4")["pages"], [2])
    case("soft-hyphen word",
         find(_PAGES, "versus chemotherapy alone")["pages"], [2])
    case("plain number", find(_PAGES, "13.2 months")["pages"], [2])
    case("case folded", find(_PAGES, "MEDIAN OVERALL SURVIVAL")["pages"], [2])
    case("case exact",
         find(_PAGES, "MEDIAN OVERALL SURVIVAL", fold_case=False)["pages"], [])
    # A claim that is not in the paper must come back empty in BOTH buckets:
    # a loose fallback that matches anything would make the exit code useless.
    absent = find(_PAGES, "14.9 months")
    case("absent needle, clean", absent["pages"], [])
    case("absent needle, loose", absent["loose_pages"], [])
    # A phrase the PDF broke *between words* is a clean hit: collapsing the
    # newline to a space is faithful, not a relaxation.
    case("phrase across a line break",
         find(_PAGES, "months (95% CI 11.1-15.4), a hazard ratio")["pages"], [2])
    # A word the PDF broke *inside* is not: only the squashed retry finds it,
    # so it reports as loose and the reader is sent to the page.
    hyph = find(_PAGES, "progression-free survival")
    case("word broken at a hyphen, clean", hyph["pages"], [])
    case("word broken at a hyphen, loose", hyph["loose_pages"], [2])

    c = cites(_PAGES)
    case("panel letter folds to its figure", c.get("2"), 3)
    case("supplementary marker kept", c.get("S1"), 1)
    case("no phantom figures", sorted(c), ["2", "S1"])
    case("plural prose percentages are not figure citations",
         cites(["The headline figures 45% and 8% both held."]), {})
    # The marker set must be the extractor's, no wider: a marker counted here
    # that `auto_fig_bbox.py`'s caption regex cannot match scores a figure
    # under a label no run can write to disk, and the tiebreak then
    # recommends carrying a file that does not exist.
    case("no marker the extractor cannot produce",
         sorted(cites(["Supporting Information Figure 1 shows the traces."])),
         ["1"])
    # `Extended Data Figure 1` must land wherever the extraction run put it.
    ed = ["Extended Data Figure 1 shows the raw traces."]
    case("extended data folds to S by default", sorted(cites(ed)), ["S1"])
    case("extended data honours --ed-prefix ED",
         sorted(cites(ed, "ED")), ["ED1"])

    # Prose that merely begins with a section word is not a heading: the old
    # rule fired on every one of these, and step 10 uses the results page range
    # to decide which numbers to look at hardest.
    for prose in ("Results were consistent across all three cohorts.",
                  "We discuss the results.",
                  "Methods for the assay are described in the appendix.",
                  "Limitations of this approach are discussed below.",
                  "Background rates of infection were low.",
                  "Summary statistics appear in the next table.",
                  "Registration of the trial lapsed in 2019."):
        case("prose is not a heading: %s" % prose[:28], sections([prose]), {})
    # ...and the real forms it used to miss.
    case("numbered heading", sections(["5. Empirical Results"]).get("results"), [1])
    case("compound heading",
         sorted(sections(["7. Discussion, Limitations, Conclusion"])),
         ["conclusion", "discussion", "limitations"])
    case("roman-numbered heading", sections(["IV. Results"]).get("results"), [1])
    case("multi-word section name",
         sections(["Materials and Methods"]).get("methods"), [1])
    case("inline statements do not hide their short heading",
         sections(["Funding: This research was supported by the Example Research "
                   "Council through its investigator grant programme."]),
         {"funding": [1]})
    # A range after a plural is a range, not a hierarchical label. Every
    # implied member and every label in a compact list contributes to the
    # tiebreak; otherwise a figure mentioned only in a list reads as uncited.
    case("figure range counts every member, not a phantom label",
         cites(["See Figures 1-3 for the traces."]),
         {"1": 1, "2": 1, "3": 1})
    case("en-dash figure range likewise",
         cites(["See Figures 1\u20133 for the traces."]),
         {"1": 1, "2": 1, "3": 1})
    case("hierarchical range counts each peer",
         cites(["See Figures 1.2-1.4 for the traces."]),
         {"1-2": 1, "1-3": 1, "1-4": 1})
    case("a plural comma-and list counts every label",
         cites(["See Figs. 1, 2, and 4 for the traces."]),
         {"1": 1, "2": 1, "4": 1})
    case("a prefixed plural range repeats its namespace",
         cites(["See Figures S1\u2013S3 for the traces."]),
         {"S1": 1, "S2": 1, "S3": 1})
    case("an ED plural range repeats its namespace",
         cites(["See Figures ED1\u2013ED3 for the traces."], "ED"),
         {"ED1": 1, "ED2": 1, "ED3": 1})
    case("a prefixed plural list counts every label",
         cites(["See Figures S1, S2, and S4 for the traces."]),
         {"S1": 1, "S2": 1, "S4": 1})
    case("a singular prefixed dashed label remains hierarchical",
         cites(["Figure S1-3 shows the loss curve."]), {"S1-3": 1})
    case("a singular dashed label remains hierarchical",
         cites(["Figure 4-6 shows the loss curve."]), {"4-6": 1})
    case("a hierarchical label survives",
         cites(["As shown in Figure 1.2, the loss falls."]), {"1-2": 1})
    # A loose match is reported as loose and is not counted as found.
    _txt, _missing = _render_find([{"needle": "2015.3", "pages": [],
                                    "loose_pages": [1]}])
    case("loose is not counted as found", "0 of 1 needle(s) found exactly" in _txt,
         True)
    case("loose does not set the exit code", _missing, 0)
    case("loose is called out", "NOT a verification" in _txt, True)

    s = sections(_PAGES)
    case("results located", s.get("results"), [2])
    case("funding located", s.get("funding"), [3])
    case("conflicts located", s.get("conflicts"), [3])
    case("no phantom limitations section", s.get("limitations"), None)

    # A user-password PDF is _Encrypted (decrypt it), never the generic
    # "corrupt, replace the file" — re-downloading yields the same bytes.
    try:
        import pymupdf as _pm
    except ImportError:
        try:
            import fitz as _pm  # noqa: F401
        except ImportError:
            _pm = None
    if _pm is not None:
        import tempfile
        with tempfile.TemporaryDirectory() as _td:
            _enc = os.path.join(_td, "enc.pdf")
            _doc = _pm.open()
            _pg = _doc.new_page()
            _pg.insert_text((72, 72), "secret text")
            _doc.save(_enc, encryption=_pm.PDF_ENCRYPT_AES_256,
                      user_pw="pw", owner_pw="pw")
            _doc.close()
            try:
                read_pages(_enc)
                _got = "no error"
            except _Encrypted as exc:
                _got = "encrypted" if "Decrypt it first" in str(exc) else "wrong msg"
            except Exception as exc:
                _got = "generic %s" % type(exc).__name__
            case("a password-protected PDF raises _Encrypted with the "
                 "decrypt advice, not the corrupt-file advice", _got, "encrypted")

            _html = os.path.join(_td, "error-page.pdf")
            with open(_html, "w", encoding="utf-8") as _fh:
                _fh.write("<html><body>hazard ratio 0.62</body></html>")
            try:
                read_pages(_html)
                _got = "accepted"
            except Exception:
                _got = True
            case("HTML named .pdf cannot verify a claim", _got, True)

            _empty = os.path.join(_td, "zero-pages.pdf")
            import pypdf as _pypdf
            with open(_empty, "wb") as _fh:
                _pypdf.PdfWriter().write(_fh)
            case("a zero-page PDF returns no pages for the caller's distinct verdict",
                 read_pages(_empty), [])

    print("%d/%d self-test cases pass" % (n - bad, n))
    return 1 if bad else 0


def _configure_stdio():
    """Keep extracted paper text writable through narrow host pipes."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (AttributeError, OSError, ValueError):
                pass


def main(argv=None):
    _configure_stdio()
    args = _build_parser().parse_args(argv)
    if args.test:
        return run_self_test()
    if not args.pdf:
        print("give a PDF path (or --test)", file=sys.stderr)
        return 2
    if not (args.pages or args.find or args.cites or args.sections):
        print("pick a mode: --pages, --find, --cites or --sections",
              file=sys.stderr)
        return 2
    if not os.path.isfile(args.pdf):
        # Distinguished from every other failure below, because the advice
        # differs completely and a wrong path is the likeliest of the three.
        print("no such file: %s. Check the path; nothing was read."
              % args.pdf, file=sys.stderr)
        return 2
    try:
        pages = read_pages(args.pdf)
    except _NoBackend as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except _Encrypted as exc:
        print(str(exc), file=sys.stderr)
        return 6
    except Exception as exc:
        print("%s could not be opened as a PDF (%s: %s). A truncated "
              "download, an HTML error page saved with a .pdf extension, or a "
              "corrupt file. This is not a missing-backend problem and not a "
              "scan; the file needs replacing."
              % (args.pdf, type(exc).__name__, exc), file=sys.stderr)
        return 5
    if not pages:
        print("%s is a structurally valid PDF with zero pages. It is not a "
              "scan and OCR will not help; the file needs replacing."
              % args.pdf, file=sys.stderr)
        return 5
    if not any(p.strip() for p in pages):
        print("%s has %d page(s) and no extractable text at all -- it is a "
              "scan. OCR it first (`ocrmypdf`) or read it with the pdf skill; "
              "nothing below can verify a claim against it."
              % (args.pdf, len(pages)), file=sys.stderr)
        return 4

    out, status = {}, 0
    if args.pages:
        out["pages"] = pages
        if not args.json:
            for i, text in enumerate(pages, start=1):
                print("=== page %d ===" % i)
                print(text)
    if args.find:
        if any(not s.strip() for s in args.find):
            print("an empty --find needle matches nothing and means nothing; "
                  "drop it rather than reading it as a missing claim",
                  file=sys.stderr)
            return 2
        results = [find(pages, s, not args.exact) for s in args.find]
        out["find"] = results
        rendered, missing = _render_find(results)
        if not args.json:
            print(rendered)
        status = 1 if missing else status
    if args.cites:
        counts = cites(pages, args.ed_prefix)
        out["cites"] = counts
        if not args.json:
            print("figure references in the body text (label: times cited)")
            for label in sorted(counts, key=lambda x: (-counts[x], x)):
                print("  %-8s %d" % (label, counts[label]))
            if not counts:
                print("  none -- the text names no figure by number")
    if args.sections:
        found = sections(pages)
        out["sections"] = found
        if not args.json:
            print("sections (page numbers are physical, as `#page=N` means)")
            for name, _starts in _SECTIONS:
                where = found.get(name)
                print("  %-13s %s" % (name,
                                      ", ".join(str(p) for p in where)
                                      if where else "not found"))
    if args.json:
        print(json.dumps(out, indent=2))
    return status


if __name__ == "__main__":
    sys.exit(main())
