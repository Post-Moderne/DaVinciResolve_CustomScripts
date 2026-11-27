#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests CSV → VFX ID : lecture de la colonne Notes et frame des markers."""

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "pm_tools"))

import csv_to_vfxid as v  # noqa: E402


def write(text):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "t.csv")
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return p


class NotesTests(unittest.TestCase):
    def test_notes_variants(self):
        for header in ("Notes", "Commentaires", "Comments", "Remarques", "À faire"):
            rows = v.read_csv_rows(write(f"VFX ID,Record In,{header}\nVFX_010,01:00:05:00,Retirer le fil\n"))
            self.assertEqual(rows, [("VFX_010", "01:00:05:00", "Retirer le fil")], header)

    def test_no_notes(self):
        rows = v.read_csv_rows(write("VFX ID;Record In\nVFX_010;01:00:05:00\n"))
        self.assertEqual(rows, [("VFX_010", "01:00:05:00", "")])

    def test_title_line_above_header(self):
        rows = v.read_csv_rows(write("Breakdown\nVFX ID,Rec In,Notes\nA,01:00:00:00,x\n"))
        self.assertEqual(rows, [("A", "01:00:00:00", "x")])


class ErrorAndSampleTests(unittest.TestCase):
    def test_error_message_is_explicit(self):
        with self.assertRaises(v.ColumnsNotFound) as cm:
            v.read_csv_rows(write("Plan,Foo\nA,B\n"))
        msg = str(cm.exception)
        self.assertIn("VFX ID", msg)
        self.assertIn("Plan, Foo", msg)          # montre ce qui a été lu
        self.assertIn("Record In", msg)

    def test_error_names_only_missing_column(self):
        with self.assertRaises(v.ColumnsNotFound) as cm:
            v.read_csv_rows(write("VFX ID,Foo\nA,B\n"))
        self.assertIn("TC record", str(cm.exception).split("\n")[0])
        self.assertNotIn("colonne VFX ID", str(cm.exception).split("\n")[0])

    def test_sample_roundtrip_no_overwrite(self):
        d = tempfile.mkdtemp()
        p1, p2 = v.write_sample_csv(d), v.write_sample_csv(d)
        self.assertNotEqual(p1, p2)
        rows = v.read_csv_rows(p1)
        self.assertEqual(len(rows), 3)
        self.assertTrue(rows[0][2])
        self.assertEqual(v.tc_to_frames(rows[0][1], 24), (3600 + 5) * 24)


class ManualColumnsTests(unittest.TestCase):
    CSV = "Breakdown,,\nPlan,Entrée,Détail\nA,01:00:00:00,x\n,,\nB,01:00:01:00,\n"

    def test_error_carries_headers_for_the_dialog(self):
        with self.assertRaises(v.ColumnsNotFound) as cm:
            v.read_csv_rows(write(self.CSV))
        self.assertEqual((cm.exception.header_row, cm.exception.headers), (1, ["Plan", "Entrée", "Détail"]))
        self.assertEqual(cm.exception.guess, (None, None, None))

    def test_partial_guess(self):
        with self.assertRaises(v.ColumnsNotFound) as cm:
            v.read_csv_rows(write("Titre\nFoo,TC IN,Notes\nA,01:00:00:00,x\n"))
        self.assertEqual((cm.exception.header_row, cm.exception.guess), (1, (None, 1, 2)))

    def test_read_with_chosen_columns(self):
        path = write(self.CSV)
        self.assertEqual(v.read_csv_rows(path, columns=(1, 0, 1, 2)),
                         [("A", "01:00:00:00", "x"), ("B", "01:00:01:00", "")])
        self.assertEqual(v.read_csv_rows(path, columns=(1, 0, 1, None))[0], ("A", "01:00:00:00", ""))

    def test_empty_file(self):
        with self.assertRaises(v.ColumnsNotFound) as cm:
            v.read_csv_rows(write(""))
        self.assertEqual(cm.exception.headers, [])


class MarkerFrameTests(unittest.TestCase):
    def test_relative_to_timeline_start(self):
        tl_start = 86400                        # 01:00:00:00 à 24 fps
        self.assertEqual(v.marker_frame(tl_start + 100, tl_start + 200, tl_start), 150)

    def test_first_clip_odd_length(self):
        self.assertEqual(v.marker_frame(86400, 86400 + 25, 86400), 12)

    def test_positions(self):
        self.assertEqual(v.marker_frame(86500, 86600, 86400, "Début"), 100)
        self.assertEqual(v.marker_frame(86500, 86600, 86400, "Milieu"), 150)
        self.assertEqual(v.marker_frame(86500, 86600, 86400, "Fin"), 199)   # end exclusif

    def test_end_of_one_frame_clip(self):
        self.assertEqual(v.marker_frame(86500, 86501, 86400, "Fin"), 100)

    def test_colors_include_defaults(self):
        self.assertIn("Blue", v.MARKER_COLORS)


class MarkerOnlyTests(unittest.TestCase):
    def test_marker_at_tc(self):
        self.assertEqual(v.marker_only_frame(86400 + 120, 86400, {}), 120)
        self.assertEqual(v.marker_only_frame(86400, 86400, {}), 0)

    def test_before_timeline_start(self):
        with self.assertRaises(ValueError):
            v.marker_only_frame(86399, 86400, {})

    def test_duplicate_tc(self):
        with self.assertRaises(ValueError) as cm:
            v.marker_only_frame(86410, 86400, {10: "VFX_010"})
        self.assertIn("VFX_010", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
