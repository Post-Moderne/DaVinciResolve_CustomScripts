#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests de pm_common.Trace (diagnostic de gel)."""

import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import pm_common  # noqa: E402


class TraceTests(unittest.TestCase):
    def setUp(self):
        self._root = pm_common.LOG_ROOT
        pm_common.LOG_ROOT = tempfile.mkdtemp()

    def tearDown(self):
        pm_common.LOG_ROOT = self._root

    def test_removed_on_normal_close(self):
        t = pm_common.Trace("T")
        t.step("a")
        path = t.path
        self.assertTrue(os.path.exists(path))
        t.close()
        self.assertFalse(os.path.exists(path))

    def test_kept_when_requested_and_steps_written(self):
        t = pm_common.Trace("T")
        t.step("étape un")
        path = t.path
        t.close(keep=True)
        txt = open(path, encoding="utf-8").read()
        self.assertIn("étape un", txt)
        self.assertIn("PM Suite v", txt)

    def test_watchdog_dumps_stack_when_stuck(self):
        t = pm_common.Trace("T", watchdog_s=0.3)
        t.step("avant le gel")
        time.sleep(0.8)                      # simule un appel bloquant
        path = t.path
        t.close(keep=True)
        txt = open(path, encoding="utf-8").read()
        self.assertIn("avant le gel", txt)
        self.assertIn("most recent call first", txt)
        self.assertIn("test_watchdog_dumps_stack_when_stuck", txt)

    def test_inactive_trace_is_noop(self):
        t = pm_common.Trace.__new__(pm_common.Trace)
        t._f = None
        t.step("x")
        t.close()


if __name__ == "__main__":
    unittest.main()
