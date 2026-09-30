#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Markers → Stills — exporte un still (image) à chaque marker de la timeline active
et nomme le fichier d'après le nom du marker.
Module interne de la PM Suite (voir PM-Suite.py).

FONCTIONNEMENT
───────────────
Les markers de timeline (timeline.GetMarkers()) sont indexés par frame *relative*
au début de la timeline : on y ajoute le Start TC de la timeline pour obtenir le
timecode absolu, on déplace le playhead dessus (SetCurrentTimecode) puis on appelle
project.ExportCurrentFrameAsStill(). Le format est déterminé par l'extension.

Le nom du fichier est le champ *Name* du marker (à défaut : Notes, puis le TC).
Les caractères interdits sont remplacés par « _ » ; en cas de doublon (dans le lot
ou déjà sur le disque) un suffixe _2, _3… est ajouté : rien n'est jamais écrasé.
Le still reflète le grade actuel de la timeline.
"""

import os
import sys
import re
import time
import tkinter as tk
from tkinter import ttk, messagebox

# Resolve exécute les scripts de Scripts/Utility sans définir __file__ : on retombe
# alors sur les dossiers Modules connus, où pm_common.py est installé.
_MODULE_DIRS = [
    "/Users/" + (os.environ.get("USER") or os.environ.get("LOGNAME") or "unknown") +
    "/Library/Containers/com.blackmagic-design.DaVinciResolveAppStore/Data/Library/Application Support/Developer/Scripting/Modules",
    "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules",
]
try:
    _MODULE_DIRS.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
except NameError:
    pass
for _d in _MODULE_DIRS:
    if os.path.isdir(_d) and _d not in sys.path:
        sys.path.insert(0, _d)
import pm_common
from pm_common import PMWindow, Theme
from pm_tools.csv_to_vfxid import tc_to_frames

TOOL_NAME = "PM-Resolve_Markers-to-Stills"

ALL_COLORS = "Toutes les couleurs"
FORMATS = ["png", "jpg", "tif", "dpx"]
BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


# ── Logique pure (testable hors Resolve) ───────────────────────────────────────
def frames_to_tc(frame, fps, drop_frame=False):
    """Numéro de frame absolu → 'HH:MM:SS:FF' (ou 'HH:MM:SS;FF' en drop frame)."""
    nominal = int(round(float(fps)))
    frame = int(frame)
    if drop_frame:
        drop = 2 if nominal <= 30 else 4
        per_10min = nominal * 600 - drop * 9
        per_min = nominal * 60 - drop
        d, m = divmod(frame, per_10min)
        if m > drop:
            frame += drop * 9 * d + drop * ((m - drop) // per_min)
        else:
            frame += drop * 9 * d
    ff = frame % nominal
    ss = (frame // nominal) % 60
    mm = (frame // (nominal * 60)) % 60
    hh = frame // (nominal * 3600)
    sep = ";" if drop_frame else ":"
    return f"{hh:02d}:{mm:02d}:{ss:02d}{sep}{ff:02d}"


def sanitize(name):
    """Nom de fichier sûr : caractères interdits → '_', espaces/points de bord retirés."""
    clean = BAD_CHARS.sub("_", name or "").strip().strip(".")
    return clean[:150]


def build_plan(markers, start_frame, fps, drop_frame, color, folder, ext, exists=os.path.exists):
    """
    markers : dict {offset: {color, name, note, ...}} tel que rendu par GetMarkers().
    Retourne une liste triée de dicts {tc, color, label, path, status}. `exists`
    est injectable pour les tests.
    """
    plan, used = [], set()
    for offset in sorted(markers):
        m = markers[offset]
        if color != ALL_COLORS and m.get("color") != color:
            continue
        tc = frames_to_tc(start_frame + int(offset), fps, drop_frame)
        label = sanitize(m.get("name")) or sanitize(m.get("note"))
        fallback = not label
        if fallback:
            label = "Marker_" + tc.replace(":", "-").replace(";", "-")
        base, n = label, 1
        while True:
            fname = f"{base}.{ext}" if n == 1 else f"{base}_{n}.{ext}"
            path = os.path.join(folder, fname)
            if fname.lower() not in used and not exists(path):
                break
            n += 1
        used.add(fname.lower())
        status = "Prêt" if n == 1 and not fallback else (
            "Prêt (nom sans marker)" if fallback else f"Prêt (doublon → _{n})")
        plan.append({"tc": tc, "color": m.get("color", ""), "label": label,
                     "path": path, "status": status})
    return plan


class MarkersToStillsWindow(PMWindow):
    def __init__(self, master):
        self.markers = {}
        self.plan = []
        self.timeline = None
        super().__init__(master, "Markers → Stills",
                          f"DaVinci Resolve  ·  {pm_common.RESOLVE_VARIANT}")
        self._init_resolve()

    def _build_content(self, main):
        top = tk.Frame(main, bg=Theme.DARK_BG)
        top.pack(fill="x")
        tk.Label(top, text="Dossier :", bg=Theme.DARK_BG, fg=Theme.FG).pack(side="left")
        self.folder_var = tk.StringVar()
        entry = tk.Entry(top, textvariable=self.folder_var, bg=Theme.PANEL_BG, fg=Theme.FG,
                          insertbackground=Theme.FG, relief="flat", width=50)
        entry.pack(side="left", padx=6, ipady=3)
        entry.bind("<Return>", lambda e: self._rebuild_plan())
        self.button(top, "Parcourir…", Theme.PANEL_BG, self.on_browse, side="left")
        self.btn_export = self.button(top, "Exporter", Theme.SUCCESS, self.on_export, side="right")
        self.btn_export.config(state="disabled")

        opts = tk.Frame(main, bg=Theme.DARK_BG)
        opts.pack(fill="x", pady=(8, 0))
        tk.Label(opts, text="Couleur :", bg=Theme.DARK_BG, fg=Theme.FG).pack(side="left")
        self.color_var = tk.StringVar(value=ALL_COLORS)
        self.cmb_color = ttk.Combobox(opts, textvariable=self.color_var, width=22,
                                       state="readonly", values=[ALL_COLORS])
        self.cmb_color.pack(side="left", padx=6)
        self.cmb_color.bind("<<ComboboxSelected>>", lambda e: self._rebuild_plan())
        tk.Label(opts, text="Format :", bg=Theme.DARK_BG, fg=Theme.FG).pack(side="left", padx=(16, 0))
        self.fmt_var = tk.StringVar(value="png")
        cmb_fmt = ttk.Combobox(opts, textvariable=self.fmt_var, width=6, state="readonly",
                                values=FORMATS)
        cmb_fmt.pack(side="left", padx=6)
        cmb_fmt.bind("<<ComboboxSelected>>", lambda e: self._rebuild_plan())
        self.button(opts, "Relire les markers", Theme.PANEL_BG, self._reload, side="right")

        self.lbl_info = tk.Label(main, text="", bg=Theme.DARK_BG, fg=Theme.FG)
        self.lbl_info.pack(anchor="w", pady=(6, 0))

        columns = ("tc", "color", "file", "status")
        self.tree = ttk.Treeview(main, columns=columns, show="headings", height=14)
        for col, title, w in (("tc", "TC", 110), ("color", "Couleur", 90),
                              ("file", "Fichier", 340), ("status", "Statut", 240)):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, pady=(10, 8))
        self.tree.tag_configure("ok", background=Theme.PANEL_BG)
        self.tree.tag_configure("warn", background="#4a3a1a")
        self.tree.tag_configure("bad", background="#4a1a1a")

        self.progress = ttk.Progressbar(main, mode="determinate")
        self.progress.pack(fill="x")
        self.log = self.build_log(main, height=8)

    # ---------------------------------------------------------- Resolve init
    def _init_resolve(self):
        try:
            self.resolve, self.project, _ = pm_common.get_resolve_objects()
        except Exception as e:
            messagebox.showerror("Erreur de connexion", str(e))
            self.resolve = self.project = None
            return
        self.log_write(self.log, f"Connecté à Resolve (variante : {pm_common.RESOLVE_VARIANT}).\n", "dim")
        self._reload()

    def _reload(self):
        """Relit la timeline active, ses markers et les couleurs présentes."""
        self.timeline = self.project.GetCurrentTimeline() if self.project else None
        if not self.timeline:
            self.log_write(self.log, "[ERREUR] Aucune timeline active.\n", "err")
            return
        try:
            self.fps = float(self.timeline.GetSetting("timelineFrameRate") or 24)
        except (TypeError, ValueError):
            self.fps = 24.0
        self.drop_frame = str(self.timeline.GetSetting("timelineDropFrameTimecode")) == "1"
        self.start_frame = tc_to_frames(self.timeline.GetStartTimecode() or "01:00:00:00",
                                        self.fps, self.drop_frame)
        self.markers = self.timeline.GetMarkers() or {}
        colors = sorted({m.get("color", "") for m in self.markers.values() if m.get("color")})
        self.cmb_color.config(values=[ALL_COLORS] + colors)
        if self.color_var.get() not in self.cmb_color["values"]:
            self.color_var.set(ALL_COLORS)
        self.lbl_info.config(text=f"{self.timeline.GetName()}  ·  {self.fps:g} fps"
                              f"{' DF' if self.drop_frame else ''}  ·  {len(self.markers)} marker(s)")
        self.log_write(self.log, f"Timeline : {self.timeline.GetName()}  ·  {len(self.markers)} marker(s)"
                        f"  ·  couleurs : {', '.join(colors) or 'aucune'}\n", "dim")
        self._rebuild_plan()

    # ---------------------------------------------------------------- Plan
    def on_browse(self):
        folder = pm_common.pick_folder("Dossier de destination des stills", parent=self)
        if folder:
            self.folder_var.set(folder)
            self._rebuild_plan()

    def _folder(self):
        return os.path.expanduser(self.folder_var.get().strip().strip('"').strip("'").replace("\\ ", " "))

    def _rebuild_plan(self):
        self.tree.delete(*self.tree.get_children())
        self.plan = []
        self.btn_export.config(state="disabled")
        if not self.timeline:
            return
        folder = self._folder()
        self.plan = build_plan(self.markers, self.start_frame, self.fps, self.drop_frame,
                               self.color_var.get(), folder or ".", self.fmt_var.get())
        for p in self.plan:
            tag = "ok" if p["status"] == "Prêt" else "warn"
            self.tree.insert("", "end", iid=p["tc"] + p["label"],
                             values=(p["tc"], p["color"], os.path.basename(p["path"]), p["status"]),
                             tags=(tag,))
        if not self.plan:
            self.log_write(self.log, "Aucun marker pour ce filtre.\n", "warn")
        elif folder and os.path.isdir(folder):
            self.btn_export.config(state="normal")
        else:
            self.log_write(self.log, f"{len(self.plan)} marker(s) — choisis un dossier de destination.\n", "dim")

    # -------------------------------------------------------------- Export
    def _goto(self, tc):
        """Place le playhead sur `tc` et attend que Resolve l'ait pris en compte."""
        for _ in range(10):
            self.timeline.SetCurrentTimecode(tc)
            time.sleep(0.15)
            self.update()
            if (self.timeline.GetCurrentTimecode() or "").replace(";", ":") == tc.replace(";", ":"):
                return True
        return False

    def _export_one(self, p):
        if not self._goto(p["tc"]):
            return False, "playhead non positionné"
        for _ in range(3):
            ok = self.project.ExportCurrentFrameAsStill(p["path"])
            for _ in range(10):         # l'écriture peut finir après le retour de l'API
                if os.path.isfile(p["path"]):
                    return True, ""
                time.sleep(0.1)
            time.sleep(0.3)
        return False, "export refusé par Resolve" if not ok else "fichier non créé"

    def on_export(self):
        folder = self._folder()
        if not self.plan or not os.path.isdir(folder):
            messagebox.showerror("Dossier introuvable", f"Choisis un dossier existant :\n{folder}")
            return
        if not messagebox.askyesno("Confirmer", f"Exporter {len(self.plan)} still(s) vers\n{folder} ?"):
            return
        self._rebuild_plan()            # nouveaux noms si des fichiers sont apparus entre-temps
        self.btn_export.config(state="disabled")
        self.progress.config(maximum=len(self.plan), value=0)
        self.log_write(self.log, "\n── Export ──\n", "accent")

        original_tc = self.timeline.GetCurrentTimecode()
        n_ok, journal = 0, [f"Timeline : {self.timeline.GetName()}", f"Dossier : {folder}"]
        for i, p in enumerate(self.plan, 1):
            try:
                ok, why = self._export_one(p)
            except Exception as e:
                ok, why = False, f"exception : {e}"
            iid = p["tc"] + p["label"]
            if ok:
                n_ok += 1
                self.log_write(self.log, f"[OK] {p['tc']}  → {os.path.basename(p['path'])}\n", "ok")
                self.tree.item(iid, tags=("ok",))
                self.tree.set(iid, "status", "Exporté")
            else:
                self.log_write(self.log, f"[ÉCHEC] {p['tc']}  {os.path.basename(p['path'])} — {why}\n", "err")
                self.tree.item(iid, tags=("bad",))
                self.tree.set(iid, "status", f"Échec ({why})")
            journal.append(f"{p['tc']}\t{p['color']}\t{p['path']}\t{'OK' if ok else 'ECHEC : ' + why}")
            self.progress.config(value=i)
            self.update()

        if original_tc:
            self.timeline.SetCurrentTimecode(original_tc)
        try:
            log_path = pm_common.write_log(TOOL_NAME, journal)
            self.log_write(self.log, f"\nJournal : {log_path}\n", "dim")
        except OSError as e:
            self.log_write(self.log, f"\n[INFO] Journal non écrit ({e}).\n", "dim")
        n_fail = len(self.plan) - n_ok
        self.log_write(self.log, f"Terminé : {n_ok} succès, {n_fail} échec(s).\n", "accent")
        messagebox.showinfo("Terminé", f"{n_ok} still(s) exporté(s).\n{n_fail} échec(s) — voir le log.")
        self.btn_export.config(state="normal")


def open_window(master):
    return MarkersToStillsWindow(master)


def main():
    """Lancement autonome (Workspace > Scripts) : racine Tk cachée + fenêtre de l'outil."""
    root = tk.Tk()
    root.withdraw()
    try:
        win = MarkersToStillsWindow(root)
        win.protocol("WM_DELETE_WINDOW", root.destroy)
        pm_common.run_app(root)
    except Exception as e:
        pm_common.write_error_log(TOOL_NAME, e)
        raise


if __name__ == "__main__":
    main()
