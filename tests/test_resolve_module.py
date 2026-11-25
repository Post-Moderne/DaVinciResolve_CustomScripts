#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Repli sur le DaVinciResolveScript.py embarqué dans l'application Resolve."""

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import pm_common  # noqa: E402


class BundledModuleTests(unittest.TestCase):
    def setUp(self):
        self.apps = tempfile.mkdtemp()
        self.saved = (pm_common.APP_PATTERNS, list(sys.path), dict(os.environ))
        pm_common.APP_PATTERNS = [os.path.join(self.apps, "DaVinci Resolve*.app")]
        sys.path[:] = [p for p in sys.path
                       if not os.path.isfile(os.path.join(p, "DaVinciResolveScript.py"))]
        os.environ.pop("RESOLVE_SCRIPT_LIB", None)
        sys.modules.pop("DaVinciResolveScript", None)

    def tearDown(self):
        pm_common.APP_PATTERNS, sys.path[:], env = self.saved
        os.environ.clear()
        os.environ.update(env)
        sys.modules.pop("DaVinciResolveScript", None)

    def make_app(self, name, code):
        app = os.path.join(self.apps, name)
        for sub, filename, text in (("Resources/Developer/Scripting/Modules", "DaVinciResolveScript.py", code),
                                    ("Libraries/Fusion", "fusionscript.so", "")):
            d = os.path.join(app, "Contents", sub)
            os.makedirs(d)
            with open(os.path.join(d, filename), "w") as f:
                f.write(text)

    def test_newest_app_used_with_its_library(self):
        for n in ("20", "21"):
            self.make_app(f"DaVinci Resolve Studio {n}.app",
                          f"import os\nVERSION = '{n}'\nLIB = os.environ.get('RESOLVE_SCRIPT_LIB')\n")
        dvr = pm_common.import_resolve_script()
        self.assertEqual(dvr.VERSION, "21")
        self.assertIn("Studio 21.app/Contents/Libraries/Fusion/fusionscript.so", dvr.LIB)

    def test_error_shows_real_cause(self):
        self.make_app("DaVinci Resolve.app", "raise ImportError('Could not locate module dependencies')\n")
        with self.assertRaises(RuntimeError) as cm:
            pm_common.import_resolve_script()
        self.assertIn("Could not locate module dependencies", str(cm.exception))
        self.assertNotIn("RESOLVE_SCRIPT_LIB", os.environ)

    def test_no_app(self):
        with self.assertRaises(RuntimeError):
            pm_common.import_resolve_script()


if __name__ == "__main__":
    unittest.main()
