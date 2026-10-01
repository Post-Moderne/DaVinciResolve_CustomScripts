#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests de la détection de variante Resolve. Lancer : python3 -m unittest discover -s tests"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import pm_common  # noqa: E402

P = pm_common.PATHS


class VariantTests(unittest.TestCase):
    def test_module_in_dmg_modules(self):
        self.assertEqual(pm_common.resolve_variant(P["dmg"]["modules"] + "/pm_common.py"), "dmg")

    def test_module_in_appstore_modules(self):
        self.assertEqual(pm_common.resolve_variant(P["appstore"]["modules"] + "/pm_common.py"), "appstore")

    def test_module_in_dmg_utility_scripts(self):
        self.assertEqual(pm_common.resolve_variant(P["dmg"]["scripts"] + "/Utility/PM-Suite.py"), "dmg")

    def test_dmg_wins_even_if_appstore_container_exists(self):
        # Poste où l'app App Store a été supprimée mais son conteneur reste :
        # le module installé côté DMG doit rester « dmg ».
        orig = os.path.isdir
        os.path.isdir = lambda p: True
        try:
            self.assertEqual(pm_common.resolve_variant(P["dmg"]["modules"] + "/pm_common.py"), "dmg")
        finally:
            os.path.isdir = orig

    def test_prefix_lookalike_is_not_matched(self):
        self.assertNotIn(pm_common.resolve_variant("/tmp/x" + P["dmg"]["modules"] + "/pm_common.py"), ("dmg",))


if __name__ == "__main__":
    unittest.main()
