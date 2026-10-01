#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests de l'analyse et du rapport SnapDrive. Lancer : python3 -m unittest discover -s tests"""

import csv
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

from pm_tools import snapdrive as sd  # noqa: E402
from pm_tools import snapdrive_analysis as an  # noqa: E402
from pm_tools.snapdrive_analysis import RawItem  # noqa: E402


def drive(disk, *files):
    items = ",".join(f'"{n}*{s}*1*Fichier MXF*null"' for n, s in files)
    return sd.parse_snapdrive_text(f'D.p(["/Volumes/{disk}/f*0*1",{items},0,""]);')


def raw(name, tl="TL1", kind="source", usage=None, track=1, detail=""):
    return RawItem(tl, track, name, "Orange", kind, usage, detail)


class FakeMount:
    def __init__(self, *disks):
        self.disks = set(disks)

    def __call__(self, disk):
        return disk in self.disks


def make_index(*drives):
    idx = sd.SnapDriveIndex()
    for d in drives:
        idx.add(d)
    return idx


class ClassifyTests(unittest.TestCase):
    def test_offline_clip_without_media_pool_item_is_source(self):
        self.assertEqual(an.classify(False, "", "A_0058C035_260406_150018_p1DBN.mov"), "source")
        self.assertEqual(an.classify(False), "source")

    def test_generic_names_without_media_pool_item_are_generators(self):
        self.assertEqual(an.classify(False, "", "Adjustment Clip"), "generator")
        self.assertEqual(an.classify(False, "", "Solid Color"), "generator")
        self.assertEqual(an.classify(False, "", "Text+"), "generator")

    def test_compound_and_timeline(self):
        self.assertEqual(an.classify(True, "Compound Clip"), "compound")
        self.assertEqual(an.classify(True, "Timeline"), "compound")

    def test_normal_clip(self):
        self.assertEqual(an.classify(True, "Video"), "source")
        self.assertEqual(an.classify(True, ""), "source")


class ClipNameTests(unittest.TestCase):
    def test_clip_stem(self):
        self.assertEqual(an.clip_stem("A_001.mov"), "A_001")
        self.assertEqual(an.clip_stem(" A_001.MXF "), "A_001")
        self.assertEqual(an.clip_stem("A_001"), "A_001")
        self.assertEqual(an.clip_stem("A_001.5"), "A_001.5")      # pas une extension média

    def test_timeline_name_with_extension_matches_other_extension(self):
        idx = make_index(drive("D1", ("A_0058C035_260406_150018_p1DBN.mxf", 10)))
        r = an.analyze([raw("A_0058C035_260406_150018_p1DBN.mov", kind="source")], idx, mounted=FakeMount("D1"))
        self.assertEqual(len(r.found), 1)
        self.assertEqual(r.found[0].name, "A_0058C035_260406_150018_p1DBN")

    def test_with_and_without_extension_are_one_source(self):
        idx = make_index(drive("D1", ("A_001.mxf", 10)))
        r = an.analyze([raw("A_001.mov"), raw("a_001"), raw("A_001.mxf")], idx, mounted=FakeMount("D1"))
        self.assertEqual((len(r.sources), r.sources[0].uses), (1, 3))

    def test_missing_with_extension_shown_without(self):
        r = an.analyze([raw("ZZZ.mov"), raw("zzz")], make_index(drive("D1", ("A.mxf", 1))), mounted=FakeMount())
        self.assertEqual([(s.name, s.uses) for s in r.missing], [("ZZZ", 2)])


class PriorityTests(unittest.TestCase):
    def setUp(self):
        self.hits = [drive("IMT_SHTL_01", ("A.mxf", 1)).entries[0], drive("IMT_TRNS_02", ("A.mxf", 1)).entries[0]]

    def test_mounted_beats_priority(self):
        e = an.choose_entry(self.hits, ["IMT_TRNS_*"], FakeMount("IMT_SHTL_01"))
        self.assertEqual(e.disk, "IMT_SHTL_01")

    def test_priority_among_mounted(self):
        e = an.choose_entry(self.hits, ["imt_trns_*", "IMT_SHTL_*"], FakeMount("IMT_SHTL_01", "IMT_TRNS_02"))
        self.assertEqual(e.disk, "IMT_TRNS_02")

    def test_priority_when_none_mounted(self):
        e = an.choose_entry(self.hits, ["IMT_TRNS_*"], FakeMount())
        self.assertEqual(e.disk, "IMT_TRNS_02")

    def test_default_alphabetical_and_empty(self):
        self.assertEqual(an.choose_entry(self.hits, (), FakeMount()).disk, "IMT_SHTL_01")
        self.assertIsNone(an.choose_entry([], (), FakeMount()))


class AnalyzeTests(unittest.TestCase):
    def setUp(self):
        self.idx = make_index(drive("D1", ("A_001.mxf", 100), ("B_002.mxf", 200)),
                              drive("D2", ("C_003.mxf", 300), ("A_001.mxf", 100)))
        self.m = FakeMount("D1")

    def test_single_listing_with_use_count(self):
        r = an.analyze([raw("A_001"), raw("a_001 ", tl="TL2"), raw("A_001")], self.idx, mounted=self.m)
        self.assertEqual(len(r.sources), 1)
        s = r.sources[0]
        self.assertEqual((s.uses, s.timelines), (3, {"TL1", "TL2"}))

    def test_found_missing_duplicates(self):
        r = an.analyze([raw("A_001"), raw("B_002"), raw("ZZZ")], self.idx, mounted=self.m)
        self.assertEqual([s.name for s in r.found], ["A_001", "B_002"])
        self.assertEqual([s.name for s in r.missing], ["ZZZ"])
        self.assertEqual([s.name for s in r.duplicates], ["A_001"])
        self.assertEqual(r.duplicates[0].disks, ["D1", "D2"])

    def test_ignored_items_listed_not_matched(self):
        r = an.analyze([raw("Titre", kind="generator"), raw("Comp 1", kind="compound"),
                        raw("  ", kind="source"), raw("A_001")], self.idx, mounted=self.m)
        self.assertEqual(len(r.sources), 1)
        self.assertEqual([i.kind for i in r.ignored], ["generator", "compound", "noname"])
        self.assertEqual(dict(r.ignored_summary()), {"generator": 1, "compound": 1, "noname": 1})

    def test_pull_list_totals_per_disk(self):
        r = an.analyze([raw("A_001"), raw("A_001"), raw("B_002"), raw("C_003")], self.idx, mounted=self.m)
        pl = r.pull_list(self.m)
        self.assertEqual(list(pl), ["D1", "D2"])
        self.assertEqual(pl["D1"], {"sources": 2, "uses": 3, "size": 300, "mounted": True})
        self.assertEqual(pl["D2"], {"sources": 1, "uses": 1, "size": 300, "mounted": False})

    def test_usage_property_kept(self):
        r = an.analyze([raw("A_001", usage="2")], self.idx, mounted=self.m)
        self.assertEqual(r.sources[0].usage, "2")

    def test_no_double_extension_collision(self):
        idx = make_index(drive("D1", ("A.mxf", 1), ("A.mov", 2)))
        r = an.analyze([raw("A")], idx, mounted=self.m)
        self.assertTrue(r.sources[0].duplicate)


class CsvTests(unittest.TestCase):
    def test_csv_export(self):
        idx = make_index(drive("D1", ("A_001.mxf", 100)), drive("D2", ("A_001.mxf", 100)))
        r = an.analyze([raw("A_001"), raw("ZZZ"), raw("Titre", kind="generator")], idx,
                       mounted=FakeMount("D1"))
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "r.csv")
            an.write_csv(r, p, FakeMount("D1"))
            with open(p, encoding="utf-8-sig", newline="") as f:
                rows = list(csv.reader(f))
        self.assertEqual(rows[0], an.CSV_HEADER)
        statuses = [x[0] for x in rows[1:]]
        self.assertEqual(statuses, ["TROUVÉ (doublon)", "DOUBLON (alternative)", "INTROUVABLE", "IGNORÉ"])
        self.assertEqual(rows[1][1], "D1")

    def test_human_size(self):
        self.assertEqual(an.human_size(0), "0 o")
        self.assertEqual(an.human_size(1536), "1.5 Ko")


if __name__ == "__main__":
    unittest.main()
