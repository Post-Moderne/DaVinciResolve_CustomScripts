#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests du parsing CSV → Start TC. Lancer : python3 -m unittest discover -s tests"""

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "pm_tools"))

import csv_to_tc as c  # noqa: E402


def write(tmp, text, enc="utf-8"):
    p = os.path.join(tmp, "t.csv")
    with open(p, "w", encoding=enc, newline="") as f:
        f.write(text)
    return p


class NormalizeTcTests(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(c.normalize_tc("01:00:00:00"), ("01:00:00:00", "ok", ""))
        self.assertEqual(c.normalize_tc("01:00:00;12")[1], "ok")          # drop-frame

    def test_fixed(self):
        self.assertEqual(c.normalize_tc("1:0:0:0")[:2], ("01:00:00:00", "fixed"))
        self.assertEqual(c.normalize_tc("01.00.05.10")[:2], ("01:00:05:10", "fixed"))
        self.assertEqual(c.normalize_tc("01:00:05")[:2], ("01:00:05:00", "fixed"))
        self.assertEqual(c.normalize_tc("01000510")[:2], ("01:00:05:10", "fixed"))
        self.assertEqual(c.normalize_tc("1:00:00;05")[:2], ("01:00:00;05", "fixed"))

    def test_invalid(self):
        for bad in ("", "abc", "99:00:00:00", "01:75:00:00", "1:2", "01:00:00:00:00"):
            self.assertEqual(c.normalize_tc(bad)[1], "invalid", bad)


class ColumnsTests(unittest.TestCase):
    def test_exact(self):
        self.assertEqual(c.detect_columns(["Name", "Start"]), ("Name", "Start"))

    def test_aliases(self):
        self.assertEqual(c.detect_columns(["Reel", "Clip Name", "Timecode"]), ("Clip Name", "Timecode"))
        self.assertEqual(c.detect_columns(["Nom", "Début"]), ("Nom", "Début"))

    def test_read_with_alias_and_semicolon(self):
        with tempfile.TemporaryDirectory() as d:
            info = {}
            rows = c.read_csv_rows(write(d, "File Name;TC\na.mov;01:00:00:00\nb.mov;02:00:00:00\n"), info=info)
            self.assertEqual(rows, [("a.mov", "01:00:00:00"), ("b.mov", "02:00:00:00")])
            self.assertTrue(info["auto"])

    def test_not_found_then_override(self):
        with tempfile.TemporaryDirectory() as d:
            p = write(d, "Foo,Bar\na.mov,01:00:00:00\n")
            with self.assertRaises(c.ColumnsNotFound) as cm:
                c.read_csv_rows(p)
            self.assertEqual(cm.exception.fieldnames, ["Foo", "Bar"])
            self.assertEqual(c.read_csv_rows(p, columns=("Foo", "Bar")), [("a.mov", "01:00:00:00")])

    def test_sample_roundtrip_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            p1, p2 = c.write_sample_csv(d), c.write_sample_csv(d)
            self.assertNotEqual(p1, p2)
            rows = c.read_csv_rows(p1)
            self.assertEqual(len(rows), 3)
            self.assertTrue(all(c.normalize_tc(tc)[1] == "ok" for _, tc in rows))


if __name__ == "__main__":
    unittest.main()
