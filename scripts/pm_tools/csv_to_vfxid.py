#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CSV → VFX ID — charge un .csv (VFX ID + timecode record) et renomme les clips
de la timeline active dont le point d'entrée correspond au timecode record.
Module interne de la PM Suite (voir PM-Suite.py).

Colonnes reconnues (insensible à la casse, , ou ; comme délimiteur) :
  • VFX ID   : "VFX ID", "VFX_ID", "VFXID", "ID", "Name", "Nom", "Shot"
  • Record TC: "Record In", "Rec In", "Record TC", "Rec TC", "Record Start",
               "Start", "TC In", "Timecode"

MATCHING
─────────
Le TC record du CSV est converti en frames (DF/NDF et cadence lus sur la
timeline) puis comparé à TimelineItem.GetStart(). Un clip dont le début tombe
exactement sur le TC est prioritaire ; à défaut, on accepte (avec avertissement)
un clip qui *contient* le TC — cas d'un TC pris au milieu d'un plan.

NOTE
─────
Comme pour csv_to_tc, la valeur de retour de SetName() n'est pas jugée fiable :
le nom est relu après écriture. Les anciens noms sont consignés dans un log
horodaté (~/Logs/PM-Suite/) pour pouvoir revenir en arrière.
"""

import os
import sys
import csv
import io
import re
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

TOOL_NAME = "PM-Resolve_CSV-to-VFXid"

ID_HEADERS = ("vfx id", "vfx_id", "vfxid", "vfx-id", "id", "name", "nom", "shot")
TC_HEADERS = ("rec tc in", "record tc in", "record in", "rec in", "record_in", "rec_in", "record tc", "rec tc",
              "record start", "rec start", "start", "tc in", "tc_in", "timecode", "tc")

TC_RE = re.compile(r"^\s*(\d{1,2})[:;.](\d{2})[:;.](\d{2})[:;.](\d{2})\s*$")


# ── Logique pure (testable hors Resolve) ───────────────────────────────────────
def tc_to_frames(tc, fps, drop_frame=False):
    """'HH:MM:SS:FF' → numéro de frame absolu. Lève ValueError si le format est invalide."""
    m = TC_RE.match(tc or "")
    if not m:
        raise ValueError(f"Timecode invalide : '{tc}'")
    h, mi, s, f = (int(x) for x in m.groups())
    nominal = int(round(float(fps)))
    total = (h * 3600 + mi * 60 + s) * nominal + f
    if drop_frame:
        drop = 2 if nominal <= 30 else 4
        total_minutes = h * 60 + mi
        total -= drop * (total_minutes - total_minutes // 10)
    return total


def _norm(header):
    """Normalise un en-tête : minuscules, retours ligne/espaces multiples réduits à un espace."""
    return " ".join((header or "").split()).lower()


def find_column(fieldnames, candidates):
    """Retourne l'index de colonne du 1er candidat trouvé, sinon None."""
    norm = [_norm(fn) for fn in fieldnames]
    for cand in candidates:
        if cand in norm:
            return norm.index(cand)
    return None


def read_text(path):
    """Lit le fichier en UTF-8, sinon en MacRoman (export Excel Mac) puis cp1252 (Excel Windows)."""
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "mac_roman", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def read_csv_rows(path):
    """
    Retourne une liste de tuples (vfx_id, record_tc). L'en-tête est cherché dans
    les 15 premières lignes (les exports de breakdown ont souvent une ligne de
    titre au-dessus). Lève ValueError si les deux colonnes sont introuvables.
    """
    text = read_text(path)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text, newline=""), dialect=dialect))

    for i, header in enumerate(rows[:15]):
        id_col = find_column(header, ID_HEADERS)
        tc_col = find_column(header, TC_HEADERS)
        if id_col is not None and tc_col is not None:
            break
    else:
        first = rows[1] if len(rows) > 1 else (rows[0] if rows else [])
        raise ValueError(
            f"Colonnes introuvables (ligne d'en-tête testée : {first}).\n"
            f"Attendu : un VFX ID ({', '.join(ID_HEADERS[:4])}…) "
            f"et un TC record ({', '.join(TC_HEADERS[:4])}…)."
        )

    out = []
    for row in rows[i + 1:]:
        vfx_id = row[id_col].strip() if id_col < len(row) else ""
        tc = row[tc_col].strip() if tc_col < len(row) else ""
        if vfx_id or tc:
            out.append((vfx_id, tc))
    return out


def match_item(frame, items):
    """
    items : liste de (item, start, end) avec end exclusif.
    Retourne (liste d'items, mode) où mode ∈ {"exact", "inside", "none"}.
    """
    exact = [it for it, s, e in items if s == frame]
    if exact:
        return exact, "exact"
    inside = [it for it, s, e in items if s <= frame < e]
    if inside:
        return inside, "inside"
    return [], "none"


class CsvToVfxIdWindow(PMWindow):
    ROW_OK = Theme.PANEL_BG
    ROW_WARN = "#4a3a1a"
    ROW_BAD = "#4a1a1a"

    def __init__(self, master):
        self.csv_rows = []
        self.plan = []
        self.timeline = None
        super().__init__(master, "CSV → VFX ID",
                          f"DaVinci Resolve  ·  {pm_common.RESOLVE_VARIANT}")
        self._init_resolve()

    def _build_content(self, main):
        top = tk.Frame(main, bg=Theme.DARK_BG)
        top.pack(fill="x")
        tk.Label(top, text="Chemin CSV :", bg=Theme.DARK_BG, fg=Theme.FG).pack(side="left")
        self.path_var = tk.StringVar()
        entry = tk.Entry(top, textvariable=self.path_var, bg=Theme.PANEL_BG, fg=Theme.FG,
                          insertbackground=Theme.FG, relief="flat", width=50)
        entry.pack(side="left", padx=6, ipady=3)
        entry.bind("<Return>", lambda e: self.on_load_csv())
        self.button(top, "Parcourir…", Theme.PANEL_BG, self.on_browse, side="left")
        self.button(top, "Charger", Theme.PANEL_BG, self.on_load_csv, side="left", padx_l=6)
        self.btn_apply = self.button(top, "Appliquer", Theme.SUCCESS, self.on_apply, side="right")
        self.btn_apply.config(state="disabled")

        opts = tk.Frame(main, bg=Theme.DARK_BG)
        opts.pack(fill="x", pady=(8, 0))
        tk.Label(opts, text="Piste vidéo :", bg=Theme.DARK_BG, fg=Theme.FG).pack(side="left")
        self.track_var = tk.StringVar(value="V1")
        self.cmb_track = ttk.Combobox(opts, textvariable=self.track_var, width=8, state="readonly",
                                       values=["V1"])
        self.cmb_track.pack(side="left", padx=6)
        self.cmb_track.bind("<<ComboboxSelected>>", lambda e: self._rebuild_plan())
        self.inside_var = tk.BooleanVar(value=True)
        tk.Checkbutton(opts, text="Accepter un TC à l'intérieur d'un clip",
                        variable=self.inside_var, command=self._rebuild_plan,
                        bg=Theme.DARK_BG, fg=Theme.FG, activebackground=Theme.DARK_BG,
                        activeforeground=Theme.FG, selectcolor=Theme.PANEL_BG,
                        font=Theme.FONT_SM, bd=0).pack(side="left", padx=(16, 0))

        self.lbl_csv = tk.Label(main, text="Aucun CSV chargé", bg=Theme.DARK_BG, fg=Theme.FG)
        self.lbl_csv.pack(anchor="w", pady=(6, 0))

        columns = ("vfx_id", "tc", "clip", "status")
        self.tree = ttk.Treeview(main, columns=columns, show="headings", height=14)
        for col, title, w in (("vfx_id", "VFX ID", 200), ("tc", "TC record", 120),
                              ("clip", "Clip actuel", 280), ("status", "Statut", 260)):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, pady=(10, 8))
        self.tree.tag_configure("ok", background=self.ROW_OK)
        self.tree.tag_configure("warn", background=self.ROW_WARN)
        self.tree.tag_configure("bad", background=self.ROW_BAD)

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
        self._refresh_timeline()

    def _refresh_timeline(self):
        """Relit la timeline active, sa cadence/DF et la liste des pistes vidéo."""
        self.timeline = self.project.GetCurrentTimeline() if self.project else None
        if not self.timeline:
            self.log_write(self.log, "[ERREUR] Aucune timeline active.\n", "err")
            return False
        try:
            self.fps = float(self.timeline.GetSetting("timelineFrameRate") or 24)
        except (TypeError, ValueError):
            self.fps = 24.0
        self.drop_frame = str(self.timeline.GetSetting("timelineDropFrameTimecode")) == "1"
        n = int(self.timeline.GetTrackCount("video") or 1)
        self.cmb_track.config(values=["Toutes"] + [f"V{i}" for i in range(1, n + 1)])
        if self.track_var.get() not in self.cmb_track["values"]:
            self.track_var.set("V1")
        self.log_write(self.log, f"Timeline : {self.timeline.GetName()}  ·  {self.fps:g} fps"
                        f"{' DF' if self.drop_frame else ''}  ·  {n} piste(s) vidéo\n", "dim")
        return True

    def _track_items(self):
        """Retourne [(item, start, end), ...] pour la/les piste(s) choisie(s)."""
        sel = self.track_var.get()
        n = int(self.timeline.GetTrackCount("video") or 1)
        tracks = range(1, n + 1) if sel == "Toutes" else [int(sel[1:])]
        out = []
        for t in tracks:
            for it in (self.timeline.GetItemListInTrack("video", t) or []):
                out.append((it, int(it.GetStart()), int(it.GetEnd())))
        return out

    # ---------------------------------------------------------------- CSV
    def on_browse(self):
        path = pm_common.pick_file("Choisir le fichier CSV", ["csv"], parent=self)
        if path:
            self.path_var.set(path)
            self.on_load_csv()
        else:
            self.log_write(self.log, "[INFO] Aucun fichier choisi (ou sélecteur indisponible). "
                            "Colle le chemin du CSV dans le champ.\n", "dim")

    def on_load_csv(self):
        if self.project is None:
            messagebox.showerror("Erreur", "Pas de connexion active à Resolve.")
            return
        path = os.path.expanduser(self.path_var.get().strip().strip('"').strip("'").replace("\\ ", " "))
        if not os.path.isfile(path):
            messagebox.showerror("Fichier introuvable", f"Aucun fichier à ce chemin :\n{path}")
            return
        try:
            self.csv_rows = read_csv_rows(path)
        except Exception as e:
            messagebox.showerror("Erreur de lecture CSV", str(e))
            return
        if not self._refresh_timeline():
            messagebox.showerror("Erreur", "Ouvre d'abord une timeline dans Resolve.")
            return
        self.lbl_csv.config(text=os.path.basename(path))
        self.log_write(self.log, f"\nCSV chargé : {path} ({len(self.csv_rows)} lignes)\n", "dim")
        self._rebuild_plan()

    # ---------------------------------------------------------------- Plan
    def _rebuild_plan(self):
        if not self.csv_rows or not self.timeline:
            return
        self.tree.delete(*self.tree.get_children())
        self.plan = []
        items = self._track_items()
        used = {}   # id(item) -> vfx_id déjà assigné, pour détecter deux lignes sur un même clip
        n_ok = n_warn = n_bad = 0

        for vfx_id, tc in self.csv_rows:
            def bad(status):
                nonlocal n_bad
                self.tree.insert("", "end", values=(vfx_id, tc, "-", status), tags=("bad",))
                self.log_write(self.log, f"[IGNORÉ] '{vfx_id}' @ {tc} — {status}\n", "warn")
                n_bad += 1

            if not vfx_id:
                bad("VFX ID vide")
                continue
            try:
                frame = tc_to_frames(tc, self.fps, self.drop_frame)
            except ValueError as e:
                bad(str(e))
                continue

            matches, mode = match_item(frame, items)
            if mode == "inside" and not self.inside_var.get():
                matches, mode = [], "none"
            if mode == "none":
                bad("Aucun clip à ce TC")
                continue
            if len(matches) > 1:
                bad(f"{len(matches)} clips à ce TC — choisis une piste précise")
                continue

            item = matches[0]
            if id(item) in used:
                bad(f"Clip déjà ciblé par '{used[id(item)]}'")
                continue
            used[id(item)] = vfx_id

            old = item.GetName() or ""
            if mode == "exact":
                tag, status = "ok", "Prêt"
                n_ok += 1
            else:
                tag, status = "warn", "Prêt (TC à l'intérieur du clip)"
                n_warn += 1
            self.tree.insert("", "end", values=(vfx_id, tc, old, status), tags=(tag,))
            self.plan.append({"item": item, "vfx_id": vfx_id, "tc": tc, "old": old})

        self.log_write(self.log, f"Preview : {n_ok} exact(s), {n_warn} à l'intérieur, "
                        f"{n_bad} ignoré(s).\n", "accent")
        self.btn_apply.config(state="normal" if self.plan else "disabled")

    # ---------------------------------------------------------------- Apply
    def on_apply(self):
        if not self.plan:
            return
        if not messagebox.askyesno(
            "Confirmer",
            f"Renommer {len(self.plan)} clip(s) de la timeline avec leur VFX ID ?\n"
            "Les anciens noms seront consignés dans un log."
        ):
            return

        n_ok = n_fail = 0
        journal = []
        self.log_write(self.log, "\n── Application ──\n", "accent")
        for p in self.plan:
            item, vfx_id = p["item"], p["vfx_id"]
            try:
                item.SetName(vfx_id)
                confirmed = item.GetName() or ""
            except Exception as e:
                confirmed = f"<exception : {e}>"
            if confirmed == vfx_id:
                n_ok += 1
                self.log_write(self.log, f"[OK] {p['tc']}  '{p['old']}' → '{vfx_id}'\n", "ok")
                self._mark_row(p, "ok", "Appliqué")
            else:
                n_fail += 1
                self.log_write(self.log, f"[ÉCHEC] {p['tc']} — lu '{confirmed}', attendu '{vfx_id}'\n", "err")
                self._mark_row(p, "bad", f"Non appliqué (lu : {confirmed or 'vide'})")
            journal.append(f"{p['tc']}\t'{p['old']}' -> '{vfx_id}'\t{'OK' if confirmed == vfx_id else 'ECHEC'}")

        try:
            log_path = pm_common.write_log(TOOL_NAME, [f"Timeline : {self.timeline.GetName()}"] + journal)
            self.log_write(self.log, f"\nJournal : {log_path}\n", "dim")
        except OSError as e:
            self.log_write(self.log, f"\n[INFO] Journal non écrit ({e}).\n", "dim")
        self.log_write(self.log, f"Terminé : {n_ok} succès, {n_fail} échec(s).\n", "accent")
        messagebox.showinfo("Terminé", f"{n_ok} clip(s) renommé(s).\n{n_fail} échec(s) — voir le log.")

    def _mark_row(self, plan_item, tag, status):
        for iid in self.tree.get_children():
            v = self.tree.item(iid, "values")
            if v[0] == plan_item["vfx_id"] and v[1] == plan_item["tc"]:
                self.tree.item(iid, values=(v[0], v[1], v[2], status), tags=(tag,))
                break


def open_window(master):
    return CsvToVfxIdWindow(master)


def main():
    """Lancement autonome (Workspace > Scripts) : racine Tk cachée + fenêtre de l'outil."""
    root = tk.Tk()
    root.withdraw()
    try:
        win = CsvToVfxIdWindow(root)
        win.protocol("WM_DELETE_WINDOW", root.destroy)
        pm_common.run_app(root)
    except Exception as e:
        pm_common.write_error_log(TOOL_NAME, e)
        raise


if __name__ == "__main__":
    main()
