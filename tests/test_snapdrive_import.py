#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests du plan et de l'import SnapDrive (faux media pool). Lancer : python3 -m unittest discover -s tests"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

from pm_tools import snapdrive as sd  # noqa: E402
from pm_tools import snapdrive_analysis as an  # noqa: E402
from pm_tools import snapdrive_import as si  # noqa: E402


# ── faux media pool ────────────────────────────────────────────────────────────
class FakeClip:
    def __init__(self, path):
        self.path = path

    def GetClipProperty(self, key):
        return self.path if key == "File Path" else None


class FakeFolder:
    def __init__(self, name):
        self.name, self.clips, self.subs = name, [], []

    def GetName(self):
        return self.name

    def GetClipList(self):
        return list(self.clips)

    def GetSubFolderList(self):
        return list(self.subs)


class FakePool:
    def __init__(self, refuse=()):
        self.root = FakeFolder("Master")
        self.current = self.root
        self.refuse = set(refuse)
        self.imports = []

    def GetRootFolder(self):
        return self.root

    def GetCurrentFolder(self):
        return self.current

    def SetCurrentFolder(self, f):
        self.current = f
        return True

    def AddSubFolder(self, parent, name):
        f = FakeFolder(name)
        parent.subs.append(f)
        return f

    def ImportMedia(self, paths):
        out = []
        for p in paths:
            if p in self.refuse:
                continue
            clip = FakeClip(p)
            self.current.clips.append(clip)
            self.imports.append((self.current.name, p))
            out.append(clip)
        return out


# ── données ────────────────────────────────────────────────────────────────────
def drive(disk, *files):
    items = ",".join(f'"{n}*{s}*1*{t}*null"' for n, s, t in files)
    return sd.parse_snapdrive_text(f'D.p(["/Volumes/{disk}/f*0*1",{items},0,""]);')


def raw(name):
    return an.RawItem("TL", 1, name, "", "source", None, "")


class Mount:
    def __init__(self, *d):
        self.d = set(d)

    def __call__(self, disk):
        return disk in self.d


def report_for(names, *drives, priority=(), mounted=Mount()):
    idx = sd.SnapDriveIndex()
    for d in drives:
        idx.add(d)
    return an.analyze([raw(n) for n in names], idx, priority=priority, mounted=mounted)


MXF = "Fichier MXF"


class PlanTests(unittest.TestCase):
    def test_only_mounted_disks(self):
        r = report_for(["A", "B", "ZZZ"], drive("D1", ("A.mxf", 1, MXF)), drive("D2", ("B.mxf", 1, MXF)))
        plan = si.plan_import(r, (), Mount("D1"))
        self.assertEqual(list(plan.by_disk), ["D1"])
        self.assertEqual([s.name for s in plan.waiting], ["B"])         # introuvable (ZZZ) n'est nulle part

    def test_duplicate_goes_to_one_disk_by_priority(self):
        r = report_for(["A"], drive("SHTL_01", ("A.mxf", 1, MXF)), drive("TRNS_02", ("A.mxf", 1, MXF)))
        both = Mount("SHTL_01", "TRNS_02")
        plan = si.plan_import(r, ["TRNS_*"], both)
        self.assertEqual(list(plan.by_disk), ["TRNS_02"])
        self.assertEqual(list(si.plan_import(r, ["SHTL_*"], both).by_disk), ["SHTL_01"])

    def test_plan_follows_current_mount_state_not_analysis_time(self):
        r = report_for(["A"], drive("D1", ("A.mxf", 1, MXF)))          # analysé disque débranché
        self.assertEqual(list(si.plan_import(r, (), Mount()).by_disk), [])
        self.assertEqual(list(si.plan_import(r, (), Mount("D1")).by_disk), ["D1"])


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.r = report_for(["A", "B", "C"], drive("D1", ("A.mxf", 1, MXF), ("B.mxf", 1, MXF), ("C.mxf", 1, MXF)))
        self.plan = si.plan_import(self.r, (), Mount("D1"))
        self.pool = FakePool()
        self.A = "/Volumes/D1/f/A.mxf"

    def run_it(self, **kw):
        kw.setdefault("file_exists", lambda p: True)
        return si.run_import(self.pool, self.plan, **kw)

    def test_imports_into_snapdrive_disk_bin(self):
        res = self.run_it()
        self.assertEqual([r.status for r in res], ["imported"] * 3)
        top = self.pool.root.subs[0]
        self.assertEqual(top.name, "_SnapDrive")
        self.assertEqual([s.name for s in top.subs], ["D1"])
        self.assertEqual(len(top.subs[0].clips), 3)

    def test_rerun_is_safe_nothing_reimported(self):
        self.run_it()
        n = len(self.pool.imports)
        res = self.run_it()
        self.assertEqual([r.status for r in res], ["present"] * 3)
        self.assertEqual(len(self.pool.imports), n)
        self.assertEqual(len(self.pool.root.subs), 1)                  # pas de bin en double

    def test_already_present_anywhere_in_project(self):
        other = FakeFolder("Rushes")
        other.clips.append(FakeClip(self.A))
        self.pool.root.subs.append(other)
        res = self.run_it()
        self.assertEqual([r.status for r in res], ["present", "imported", "imported"])

    def test_present_comparison_case_insensitive(self):
        self.pool.root.clips.append(FakeClip(self.A.upper()))
        self.assertEqual(self.run_it()[0].status, "present")

    def test_missing_on_disk_flagged_and_no_bin_if_nothing_imported(self):
        res = self.run_it(file_exists=lambda p: False)
        self.assertEqual({r.status for r in res}, {"absent"})
        self.assertIn("absent du disque", res[0].detail)
        self.assertEqual(self.pool.root.subs, [])

    def test_refused_import_is_error_and_others_continue(self):
        self.pool.refuse = {self.A}
        res = self.run_it()
        self.assertEqual([r.status for r in res], ["error", "imported", "imported"])

    def test_exception_is_caught(self):
        def boom(paths):
            raise RuntimeError("boum")
        self.pool.ImportMedia = boom
        res = self.run_it()
        self.assertTrue(all(r.status == "error" and "boum" in r.detail for r in res))

    def test_current_folder_restored(self):
        keep = FakeFolder("Mon bin")
        self.pool.root.subs.append(keep)
        self.pool.current = keep
        self.run_it()
        self.assertIs(self.pool.current, keep)

    def test_image_sequence_skipped(self):
        r = report_for(["SEQ"], drive("D1", ("SEQ.exr", 1, "sequence")))
        res = si.run_import(self.pool, si.plan_import(r, (), Mount("D1")), file_exists=lambda p: True)
        self.assertEqual(res[0].status, "skipped")

    def test_progress_callback_and_summary(self):
        calls = []
        res = self.run_it(progress=lambda i, n, r: calls.append((i, n)))
        self.assertEqual(calls, [(1, 3), (2, 3), (3, 3)])
        counts, text = si.summarize(res)
        self.assertEqual(counts["imported"], 3)
        self.assertEqual(text, "3 importé(s), 0 déjà présent(s), 0 en erreur")

    def test_collect_existing_walks_subfolders(self):
        a = FakeFolder("a")
        b = FakeFolder("b")
        a.subs.append(b)
        b.clips.append(FakeClip("/X/y.mxf"))
        self.pool.root.subs.append(a)
        self.assertEqual(si.collect_existing_paths(self.pool.root), {si.norm_path("/X/y.mxf")})


if __name__ == "__main__":
    unittest.main()
