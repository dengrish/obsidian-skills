"""Portable filename identity shared by independent vault workflows."""

import argparse
import os
import unicodedata


def portable_identity(value):
    """NFC + Unicode case-fold identity, without changing stored spelling."""
    return unicodedata.normalize("NFC", os.fspath(value)).casefold()


def run_self_test():
    """Exercise filesystem spelling equivalence without touching a vault."""
    from pathlib import Path
    import unittest

    class Tests(unittest.TestCase):
        def test_canonically_equivalent_spellings(self):
            self.assertEqual(portable_identity("Müller.md"),
                             portable_identity("Mu\u0308ller.md"))

        def test_unicode_casefold_expansion(self):
            self.assertEqual(portable_identity("Straße.md"),
                             portable_identity("STRASSE.MD"))

        def test_pathlike_input(self):
            self.assertEqual(portable_identity(Path("Investments")),
                             "investments")

        def test_whitespace_remains_significant(self):
            self.assertNotEqual(portable_identity(" report.md "),
                                portable_identity("report.md"))

        def test_compatibility_characters_remain_distinct(self):
            self.assertNotEqual(portable_identity("Ａ.md"),
                                portable_identity("A.md"))

    result = unittest.TextTestRunner().run(
        unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    failed = len(result.failures) + len(result.errors)
    print("%d/%d self-test cases pass" %
          (result.testsRun - failed, result.testsRun))
    return result.wasSuccessful()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args(argv)
    if args.test:
        return 0 if run_self_test() else 1
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
