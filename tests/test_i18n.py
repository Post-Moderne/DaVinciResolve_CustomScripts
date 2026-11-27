#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests de la langue d'interface : complétude des traductions et valeurs internes."""

import ast
import glob
import os
import string
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCRIPTS)

from pm_tools import i18n  # noqa: E402
from pm_tools import csv_to_tc, csv_to_vfxid, dji_tc, find_replace  # noqa: E402
from pm_tools import markers_to_stills as mts, snapdrive_analysis as an  # noqa: E402
from pm_tools.i18n_en import EN  # noqa: E402


def literal_tr_keys():
    """Tous les textes écrits en clair dans un appel tr("…")."""
    for path in glob.glob(os.path.join(SCRIPTS, "**", "*.py"), recursive=True):
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and getattr(n.func, "id", "") == "tr" and n.args
                    and isinstance(n.args[0], ast.Constant)):
                yield os.path.basename(path), n.args[0].value, len(n.args) - 1


def fields(text):
    return sorted((name, spec, conv or "") for _, name, spec, conv in string.Formatter().parse(text)
                  if name is not None)


# Textes identiques dans les deux langues : pas besoin d'entrée dans EN.
SAME = {"Source", "Timelines", "SnapDrive", "Import", "Date", "TC", "0 s", "1 s", "2 s", "3 s"}


class CompletenessTests(unittest.TestCase):
    def test_every_literal_has_a_translation(self):
        missing = sorted({(f, k) for f, k, _ in literal_tr_keys() if k not in EN and k not in SAME})
        self.assertEqual(missing, [])

    def test_constants_translated_at_display_have_a_translation(self):
        values = [
            *csv_to_vfxid.MARKER_POSITIONS, csv_to_vfxid.ALL_TRACKS, csv_to_vfxid.SAMPLE_FILENAME,
            csv_to_tc.SAMPLE_FILENAME, *(r[2] for r in csv_to_vfxid.SAMPLE_ROWS[1:] if r[2]),
            find_replace.PLACEHOLDER_FIND, find_replace.PLACEHOLDER_REPLACE,
            find_replace.TRACK_ALL, find_replace.TRACK_VIDEO, find_replace.TRACK_AUDIO,
            find_replace.MetadataTab.CONFIRM_TEXT, find_replace.TimelineTab.CONFIRM_TEXT,
            mts.ALL_COLORS, *mts.BRICKS.values(), *mts.SEPARATORS, *mts.DATE_FORMATS, "0,5 s",
            an.ALL_COLORS, *an.IGNORED_LABELS.values(), *an.CSV_HEADER,
        ]
        with open(os.path.join(SCRIPTS, "PM-Suite.py"), encoding="utf-8") as f:
            for node in ast.parse(f.read()).body:
                if isinstance(node, ast.Assign) and node.targets[0].id == "TOOLS":
                    values += [t[1] for t in ast.literal_eval(node.value)]
        self.assertEqual([v for v in values if v not in EN and v not in SAME], [])

    def test_placeholders_match(self):
        for fr, en in EN.items():
            if "(?P<" in fr:
                continue
            self.assertEqual(fields(fr), fields(en), fr)

    def test_argument_count_matches_placeholders(self):
        for f, key, nargs in literal_tr_keys():
            if nargs:
                self.assertEqual(len({n for n, _, _ in fields(key)}), nargs, (f, key))


class LanguageTests(unittest.TestCase):
    def setUp(self):
        self.saved = (i18n.CONFIG_PATH, i18n._current)
        i18n.CONFIG_PATH = os.path.join(tempfile.mkdtemp(), "config", "language.json")
        i18n._current = "fr"

    def tearDown(self):
        i18n.CONFIG_PATH, i18n._current = self.saved

    def test_french_by_default_and_with_unreadable_config(self):
        self.assertEqual(i18n.load(), "fr")
        os.makedirs(os.path.dirname(i18n.CONFIG_PATH))
        for bad in ("pas du json", "[]", '{"language": "xx"}'):
            with open(i18n.CONFIG_PATH, "w") as f:
                f.write(bad)
            self.assertEqual(i18n.load(), "fr", bad)

    def test_choice_is_remembered(self):
        self.assertTrue(i18n.set_language("en"))
        i18n._current = "fr"
        self.assertEqual(i18n.load(), "en")
        self.assertEqual(i18n.tr("Parcourir…"), "Browse…")
        self.assertEqual(i18n.tr("Dossier : {0}", "/x"), "Folder: /x")

    def test_unknown_text_falls_back_to_french(self):
        i18n._current = "en"
        self.assertEqual(i18n.tr("Texte {0} non traduit", 1), "Texte 1 non traduit")

    def test_labels_map_back_to_internal_values(self):
        for code in i18n.LANGUAGES:
            i18n._current = code
            for values in (csv_to_vfxid.MARKER_POSITIONS, list(mts.SEPARATORS), list(mts.DATE_FORMATS),
                           list(mts.RENDER_DELAYS), list(mts.BRICKS.values()),
                           [find_replace.TRACK_ALL, find_replace.TRACK_VIDEO, "V1"]):
                labels = i18n.choices(values)
                self.assertEqual(len(set(labels)), len(values), (code, labels))
                self.assertEqual([i18n.source(x, values) for x in labels], values, code)

    def test_labels_from_the_other_language_are_still_recognized(self):
        for shown, current in (("fr", "en"), ("en", "fr")):
            i18n._current = shown
            labels = i18n.choices(csv_to_vfxid.MARKER_POSITIONS)
            i18n._current = current
            self.assertEqual([i18n.source(x, csv_to_vfxid.MARKER_POSITIONS) for x in labels],
                             csv_to_vfxid.MARKER_POSITIONS)

    def test_english_pure_logic(self):
        i18n._current = "en"
        self.assertEqual(an.human_size(10), "10 B")
        self.assertEqual(an.human_size(2048), "2.0 KB")
        self.assertEqual(csv_to_tc.normalize_tc("")[2], "empty TC")
        with self.assertRaises(ValueError) as cm:
            dji_tc.generate_strict_pattern("A_123456", "")
        self.assertIn("empty", str(cm.exception))
        plan = mts.build_plan({0: {"color": "Blue", "name": ""}}, 0, 24, False, mts.ALL_COLORS,
                              "/x", "png", exists=lambda p: False)
        self.assertEqual(plan[0]["status"], "Ready (empty name → TC)")

    def test_french_sizes_unchanged(self):
        self.assertEqual(an.human_size(10), "10 o")
        self.assertEqual(an.human_size(2048), "2.0 Ko")
        self.assertEqual(an.human_size(1024 ** 5), "1.0 Po")


if __name__ == "__main__":
    unittest.main()
