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
from pm_tools import i18n
from pm_tools.i18n import tr

TOOLS = [
    ("Find & Replace", "Recherche/remplacement dans les métadonnées (Media Pool) ou les noms de clips (Timeline)", "pm_tools.find_replace"),
    ("CSV → Start TC", "Met à jour le Start TC des clips depuis un fichier CSV", "pm_tools.csv_to_tc"),
    ("CSV → VFX ID", "Renomme les clips de la timeline avec les VFX ID d'un CSV (TC record)", "pm_tools.csv_to_vfxid"),
    ("Markers → Stills", "Exporte un still à chaque marker, nommé d'après le marker", "pm_tools.markers_to_stills"),
    ("Timecode Extractor", "Extrait le Start TC depuis le nom de fichier (DJI, etc.)", "pm_tools.dji_tc"),
    ("BinBuilder", "Crée des bins/sous-bins en masse dans le Media Pool", "pm_tools.bin_builder"),
    ("SnapDrive Loader", "Analyse les timelines et importe leurs sources depuis les SnapDrive", "pm_tools.snapdrive_loader"),
]

# Outils en test, visibles sur toutes les stations dans la section repliable « BETA ».
# Pousser en beta = ajouter l'outil ici + incrémenter scripts/VERSION + push.
# Passer en production = déplacer la ligne de BETA_TOOLS vers TOOLS.
BETA_TOOLS = [
]


class Launcher(tk.Tk):
    def __init__(self):
        super().__init__()
        i18n.load()
        self._beta_open = False
        self.title("PM Suite")
        self.resizable(False, False)
        self.configure(bg=Theme.DARK_BG)
        style_ttk(self)
        self._build()
        self._center()

    def _set_language(self, code):
        """Applique la langue au lanceur ; les outils déjà ouverts la prennent à leur réouverture."""
        if code == i18n.language():
            return
        saved = i18n.set_language(code)
        for widget in self._frames:       # pas winfo_children() : les fenêtres d'outils en font partie
            widget.destroy()
        self._build()
        self.update_idletasks()
        self.geometry("")
        if not saved:
            messagebox.showwarning("PM Suite", tr("La langue n'a pas pu être mémorisée : elle sera "
                                                  "de nouveau à choisir au prochain lancement."))

    def _center(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

    def _build(self):
        hdr = tk.Frame(self, bg="#111116", pady=16)
        hdr.pack(fill="x")
        self._frames = [hdr]
        tk.Label(hdr, text="⬡  PM SUITE", font=(Theme.FONT_UI[0], 15, "bold"),
                 bg="#111116", fg=Theme.ACCENT).pack(side="left", padx=20)
        tk.Label(hdr, text=f"v{pm_common.get_version()}  ·  {pm_common.RESOLVE_VARIANT}",
                 font=Theme.FONT_SM, bg="#111116", fg=Theme.FG_DIM).pack(side="right", padx=20)

        main = tk.Frame(self, bg=Theme.DARK_BG, padx=20, pady=20)
        main.pack(fill="both", expand=True)
        self._frames.append(main)

        top = tk.Frame(main, bg=Theme.DARK_BG)
        top.pack(fill="x", pady=(0, 10))
        self._language_switch(top)
        tk.Label(top, text=tr("Choisis un outil :"), font=(Theme.FONT_UI[0], 10, "bold"),
                 bg=Theme.DARK_BG, fg=Theme.FG_DIM).pack(side="left")

        for label, desc, module_name in TOOLS:
            self._tool_row(main, label, tr(desc), module_name)

        if BETA_TOOLS:
            self._build_beta(main)

        line = tk.Frame(self, bg=Theme.BORDER, height=1)
        line.pack(fill="x")
        footer = tk.Frame(self, bg=Theme.DARK_BG, pady=10)
        footer.pack(fill="x")
        self._frames += [line, footer]
        tk.Button(footer, text=tr("Mises à jour…"), font=Theme.FONT_SM, bg=Theme.FG_DIM, fg=Theme.DARK_BG,
                  relief="flat", bd=0, padx=14, pady=6, cursor="hand2",
                  command=self._open_updater).pack(side="left", padx=20)
        tk.Button(footer, text=tr("Quitter"), font=Theme.FONT_SM, bg=Theme.FG_DIM, fg=Theme.DARK_BG,
                  relief="flat", bd=0, padx=14, pady=6, cursor="hand2",
                  command=self.destroy).pack(side="right", padx=20)

    def _language_switch(self, parent):
        """Sélecteur Français / English. Des Labels cliquables : sous macOS un tk.Button ignore bg."""
        box = tk.Frame(parent, bg=Theme.BORDER, padx=1, pady=1)
        box.pack(side="right", padx=(20, 0))
        for code, name in i18n.LANGUAGES.items():
            active = code == i18n.language()
            lbl = tk.Label(box, text=name, font=Theme.FONT_SM, padx=10, pady=3, cursor="hand2",
                           bg=Theme.ACCENT if active else Theme.PANEL_BG,
                           fg="#0a0a10" if active else Theme.FG)
            lbl.pack(side="left")
            lbl.bind("<Button-1>", lambda _e, c=code: self._set_language(c))

    def _build_beta(self, parent):
        """Section « BETA » repliable (fermée par défaut) : les outils en test, clairement identifiés."""
        self._beta_btn = tk.Label(parent, font=(Theme.FONT_UI[0], 10, "bold"), bg=Theme.DARK_BG,
                                  fg=Theme.WARNING, anchor="w", cursor="hand2")
        self._beta_btn.bind("<Button-1>", lambda _e: self._toggle_beta())
        self._beta_btn.pack(fill="x", pady=(12, 0))
        self._beta_frame = tk.Frame(parent, bg=Theme.DARK_BG)
        for label, desc, module_name in BETA_TOOLS:
            self._tool_row(self._beta_frame, f"[BETA] {label}", tr(desc), module_name)
        self._refresh_beta()

    def _refresh_beta(self):
        arrow = "▾" if self._beta_open else "▸"
        self._beta_btn.config(text=tr("{0}  BETA  ({1})  —  outils en test", arrow, len(BETA_TOOLS)))
        if self._beta_open:
            self._beta_frame.pack(fill="x", after=self._beta_btn)
        else:
            self._beta_frame.pack_forget()

    def _toggle_beta(self):
        self._beta_open = not self._beta_open
        self._refresh_beta()
        self.update_idletasks()
        self.geometry("")           # la fenêtre épouse son contenu

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
            messagebox.showerror("PM Suite", tr("Impossible d'ouvrir cet outil :\n{0}\n\nLog : {1}",
                                                e, log_path))


def main():
    app = Launcher()
    run_app(app)


if __name__ == "__main__":
    main()
