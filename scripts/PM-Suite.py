#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PM Suite — Post-Moderne
=========================
Point d'entrée unique de la suite d'outils PM pour DaVinci Resolve.
Lance depuis : Workspace > Scripts > Utility > PM-Suite

Compatibilité : DaVinci Resolve 18+

DÉPLOIEMENT
─────────────
Ce fichier est le SEUL à placer dans Scripts/Utility (c'est lui qui doit
apparaître comme entrée de menu — Resolve liste tout .py trouvé
directement dans ce dossier). pm_common.py, VERSION et le dossier
pm_tools/ doivent être copiés dans le dossier "Modules" de la variante
Resolve active (voir pm_common.PATHS) : ils restent ainsi importables
sans ajouter d'entrées de menu supplémentaires.
"""

import os
import sys
import tkinter as tk
from tkinter import messagebox

# Resolve exécute ce script sans définir __file__ : on cherche pm_common.py
# dans les dossiers Modules connus (voir DÉPLOIEMENT plus haut). HOME est remappé
# par le sandbox App Store : on reconstruit le vrai home à partir de USER.
_MODULE_DIRS = [
    "/Users/" + (os.environ.get("USER") or os.environ.get("LOGNAME") or "unknown") +
    "/Library/Containers/com.blackmagic-design.DaVinciResolveAppStore/Data/Library/Application Support/Developer/Scripting/Modules",
    "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules",
]
try:
    _MODULE_DIRS.insert(0, os.path.dirname(os.path.abspath(__file__)))
except NameError:
    pass
for _d in _MODULE_DIRS:
    if os.path.isdir(_d) and _d not in sys.path:
        sys.path.insert(0, _d)
import pm_common
from pm_common import Theme, style_ttk, run_app

TOOLS = [
    ("Metadata Find & Replace", "Recherche/remplacement dans les métadonnées des clips", "pm_tools.find_replace"),
    ("CSV → Start TC", "Met à jour le Start TC des clips depuis un fichier CSV", "pm_tools.csv_to_tc"),
    ("CSV → VFX ID", "Renomme les clips de la timeline avec les VFX ID d'un CSV (TC record)", "pm_tools.csv_to_vfxid"),
    ("Timecode Extractor", "Extrait le Start TC depuis le nom de fichier (DJI, etc.)", "pm_tools.dji_tc"),
    ("BinBuilder", "Crée des bins/sous-bins en masse dans le Media Pool", "pm_tools.bin_builder"),
]


class Launcher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PM Suite")
        self.resizable(False, False)
        self.configure(bg=Theme.DARK_BG)
        style_ttk(self)
        self._build()
        self._center()

    def _center(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

    def _build(self):
        hdr = tk.Frame(self, bg="#111116", pady=16)
        hdr.pack(fill="x")
        tk.Label(hdr, text="⬡  PM SUITE", font=(Theme.FONT_UI[0], 15, "bold"),
                 bg="#111116", fg=Theme.ACCENT).pack(side="left", padx=20)
        tk.Label(hdr, text=f"v{pm_common.get_version()}  ·  {pm_common.RESOLVE_VARIANT}",
                 font=Theme.FONT_SM, bg="#111116", fg=Theme.FG_DIM).pack(side="right", padx=20)

        main = tk.Frame(self, bg=Theme.DARK_BG, padx=20, pady=20)
        main.pack(fill="both", expand=True)

        tk.Label(main, text="Choisis un outil :", font=(Theme.FONT_UI[0], 10, "bold"),
                 bg=Theme.DARK_BG, fg=Theme.FG_DIM).pack(anchor="w", pady=(0, 10))

        for label, desc, module_name in TOOLS:
            self._tool_row(main, label, desc, module_name)

        tk.Frame(self, bg=Theme.BORDER, height=1).pack(fill="x")
        footer = tk.Frame(self, bg=Theme.DARK_BG, pady=10)
        footer.pack(fill="x")
        tk.Button(footer, text="Mises à jour…", font=Theme.FONT_SM, bg=Theme.FG_DIM, fg=Theme.DARK_BG,
                  relief="flat", bd=0, padx=14, pady=6, cursor="hand2",
                  command=self._open_updater).pack(side="left", padx=20)
        tk.Button(footer, text="Quitter", font=Theme.FONT_SM, bg=Theme.FG_DIM, fg=Theme.DARK_BG,
                  relief="flat", bd=0, padx=14, pady=6, cursor="hand2",
                  command=self.destroy).pack(side="right", padx=20)

    def _tool_row(self, parent, label, desc, module_name):
        row = tk.Frame(parent, bg=Theme.PANEL_BG, highlightbackground=Theme.BORDER,
                        highlightthickness=1, cursor="hand2")
        row.pack(fill="x", pady=4)

        inner = tk.Frame(row, bg=Theme.PANEL_BG, padx=14, pady=10)
        inner.pack(fill="x")
        tk.Label(inner, text=label, font=(Theme.FONT_UI[0], 11, "bold"),
                 bg=Theme.PANEL_BG, fg=Theme.FG, anchor="w").pack(fill="x")
        tk.Label(inner, text=desc, font=Theme.FONT_SM,
                 bg=Theme.PANEL_BG, fg=Theme.FG_DIM, anchor="w").pack(fill="x")

        def _open(event=None, m=module_name):
            self._launch_tool(m)

        for widget in (row, inner, *inner.winfo_children()):
            widget.bind("<Button-1>", _open)

    def _open_updater(self):
        self._launch_tool("pm_update")

    def _launch_tool(self, module_name):
        try:
            module = __import__(module_name, fromlist=["open_window"])
            module.open_window(self)
        except Exception as e:
            log_path = pm_common.write_error_log(module_name, e)
            messagebox.showerror("PM Suite", f"Impossible d'ouvrir cet outil :\n{e}\n\nLog : {log_path}")


def main():
    app = Launcher()
    run_app(app)


if __name__ == "__main__":
    main()
