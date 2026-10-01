#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests du parseur SnapDrive et de la règle de match. Lancer : python3 -m unittest discover -s tests"""

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

from pm_tools import snapdrive as sd  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "sample_snapdrive.html")
CLIP = "A_0010C001_260318_120504_p1DBN"


class MatchRuleTests(unittest.TestCase):
    def test_stem_removes_last_extension_only(self):
        self.assertEqual(sd.stem("A_0010C001.mxf"), "A_0010C001")
        self.assertEqual(sd.stem("a.b.mov"), "a.b")

    def test_stem_without_extension_or_hidden(self):
        self.assertEqual(sd.stem("noext"), "noext")
        self.assertEqual(sd.stem(".hidden"), ".hidden")

    def test_match_key_case_and_whitespace(self):
        self.assertEqual(sd.match_key("  A_001.MXF "), sd.normalize("a_001"))
        self.assertEqual(sd.normalize("  ClIp "), "clip")

    def test_exact_not_partial(self):
        idx = sd.SnapDriveIndex()
        idx.add(sd.parse_snapdrive_file(FIXTURE))
        self.assertEqual(idx.lookup(CLIP[:-3]), [])       # préfixe : pas de match
        self.assertEqual(idx.lookup(CLIP + "x"), [])


class ParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.drive = sd.parse_snapdrive_file(FIXTURE)

    def test_disk_name_from_volumes_path(self):
        self.assertEqual(self.drive.disk, "IMT_TRNS_02")

    def test_title_read(self):
        self.assertEqual(self.drive.title, "IMT_TRNS_02")

    def test_indented_first_line_parsed(self):
        # la 1re ligne D.p est indentée : ses dossiers doivent être lus (aucun fichier ici)
        self.assertEqual(self.drive.bad_blocks, 0)

    def test_file_count_and_folders_excluded(self):
        self.assertEqual(len(self.drive), 5)               # 2 mxf + weird.txt + mov + exr

    def test_entry_fields(self):
        e = next(x for x in self.drive.entries if x.name.startswith(CLIP))
        self.assertEqual(e.name, CLIP + ".mxf")
        self.assertEqual(e.size, 189718665376)
        self.assertEqual(e.mtime, 1773836097)
        self.assertEqual(e.type, "Fichier MXF")
        self.assertIsNone(e.info)
        self.assertEqual(e.path, "/Volumes/IMT_TRNS_02/IMPORT/003_20260318/A_0010_1DBN/" + CLIP + ".mxf")

    def test_name_containing_asterisk(self):
        e = next(x for x in self.drive.entries if x.name.endswith("weird.txt"))
        self.assertEqual(e.name, "notes*weird.txt")
        self.assertEqual(e.size, 12)

    def test_image_sequence_info(self):
        e = next(x for x in self.drive.entries if x.type == "sequence")
        self.assertEqual(e.info, "240")

    def test_total_size(self):
        self.assertEqual(self.drive.total_size(), 189718665376 + 1000 + 12 + 5000 + 900)

    def test_invalid_block_ignored_and_counted(self):
        text = 'D.p(["/Volumes/X/a*0*1","f.mxf*1*2*T*null",1,""]);\nD.p([oops]);\n'
        d = sd.parse_snapdrive_text(text)
        self.assertEqual(len(d), 1)
        self.assertEqual(d.bad_blocks, 1)

    def test_filename_with_closing_sequence(self):
        text = 'D.p(["/Volumes/X/a*0*1","we]);ird.mxf*1*2*T*null",1,""]);\n'
        self.assertEqual(sd.parse_snapdrive_text(text).entries[0].name, "we]);ird.mxf")

    def test_disk_fallback_title_then_filename(self):
        no_vol = 'D.p(["/mnt/z/a*0*1","f.mxf*1*2*T*null",1,""]);'
        d = sd.parse_snapdrive_text("<title>MY_DISK</title>" + no_vol, source="x.html")
        self.assertEqual((d.disk, d.entries[0].disk), ("MY_DISK", "MY_DISK"))
        d = sd.parse_snapdrive_text(no_vol, source="/a/OTHER.html")
        self.assertEqual(d.disk, "OTHER")


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.idx = sd.SnapDriveIndex()
        self.idx.add(sd.parse_snapdrive_file(FIXTURE))

    def test_lookup_case_insensitive_trim(self):
        hits = self.idx.lookup("  " + CLIP.lower() + " ")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].disk, "IMT_TRNS_02")

    def test_lookup_unknown(self):
        self.assertEqual(self.idx.lookup("NOPE"), [])

    def test_same_clip_on_two_disks(self):
        other = sd.parse_snapdrive_text(
            f'D.p(["/Volumes/SHTL_01/x*0*1","{CLIP}.mxf*5*6*Fichier MXF*null",5,""]);')
        self.idx.add(other)
        self.assertEqual(sorted(e.disk for e in self.idx.lookup(CLIP)), ["IMT_TRNS_02", "SHTL_01"])

    def test_readding_same_disk_replaces(self):
        self.idx.add(sd.parse_snapdrive_file(FIXTURE))
        self.assertEqual(len(self.idx.lookup(CLIP)), 1)
        self.assertEqual(len(self.idx), 5)


class LoadFolderTests(unittest.TestCase):
    def test_load_folder_skips_bad_files(self):
        with tempfile.TemporaryDirectory() as d:
            with open(FIXTURE, encoding="utf-8") as src, open(os.path.join(d, "a.html"), "w") as dst:
                dst.write(src.read())
            with open(os.path.join(d, "broken.html"), "w") as f:
                f.write("<html>rien</html>")
            with open(os.path.join(d, "readme.txt"), "w") as f:
                f.write("ignoré")
            index, errors = sd.load_folder(d)
        self.assertEqual(list(index.drives), ["IMT_TRNS_02"])
        self.assertEqual(len(errors), 1)
        self.assertIn("broken.html", errors[0])

    def test_missing_folder_raises(self):
        with self.assertRaises(sd.SnapDriveError):
            sd.load_folder("/nonexistent/folder")

    def test_is_mounted(self):
        with tempfile.TemporaryDirectory() as root:
            os.mkdir(os.path.join(root, "DISK_A"))
            self.assertTrue(sd.is_mounted("DISK_A", root))
            self.assertFalse(sd.is_mounted("DISK_B", root))


if __name__ == "__main__":
    unittest.main()
