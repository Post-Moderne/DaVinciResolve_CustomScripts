#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CSV → Start TC — charge un .csv (colonnes "Name"/"Start") et met à jour
le Start TC des clips du Media Pool dont "Clip Name" correspond à "Name".
Module interne de la PM Suite (voir PM-Suite.py).

NOTE IMPORTANTE
─────────────────
L'API Resolve accepte parfois SetClipProperty("Start TC", ...) sans erreur
même quand le changement n'est pas réellement appliqué (cas fréquent avec
du média caméra à timecode embarqué). Ce script relit systématiquement la
valeur après écriture pour confirmer le succès réel, plutôt que de se fier
à la valeur de retour de l'API.
"""

import os
import sys
import csv
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pm_common
from pm_common import PMWindow, Theme

TOOL_NAME = "PM-CSV-2-StartTC"


# ── Parcours récursif du Media Pool ────────────────────────────────────────────
def collect_all_clips(folder, out_list):
    """Ajoute récursivement tous les MediaPoolItem de folder (et sous-bins) dans out_list."""
    clips = folder.GetClipList() or []
    out_list.extend(clips)
    for sub in (folder.GetSubFolderList() or []):
        collect_all_clips(sub, out_list)


def build_name_index(all_clips):
    """Retourne dict: nom_clip -> liste de MediaPoolItem (pour repérer les doublons)."""
    index = {}
    for clip in all_clips:
        try:
            name = clip.GetClipProperty("Clip Name") or clip.GetName()
        except Exception:
            name = clip.GetName()
        index.setdefault(name, []).append(clip)
    return index


def read_csv_rows(path):
    """
    Retourne une liste de tuples (name, start_tc) depuis le CSV.
    Détecte automatiquement , ou ; comme délimiteur.
    Lève ValueError si les colonnes "Name" ou "Start" sont absentes.
    """
    with open(path, newline="", encoding="utf-8-sig") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(f, dialect=dialect)

        fieldnames = reader.fieldnames or []
        norm = {fn.strip().lower(): fn for fn in fieldnames}
        if "name" not in norm or "start" not in norm:
            raise ValueError(
                f"Colonnes requises introuvables. Colonnes détectées : {fieldnames}\n"
                "Le CSV doit contenir une colonne 'Name' et une colonne 'Start'."
            )
        name_col = norm["name"]
        start_col = norm["start"]

        rows = []
        for row in reader:
            name = (row.get(name_col) or "").strip()
            start = (row.get(start_col) or "").strip()
            if name:
                rows.append((name, start))
        return rows


class CsvToTcWindow(PMWindow):
    ROW_OK = Theme.PANEL_BG
    ROW_DUP = "#4a3a1a"
    ROW_MISSING = "#4a1a1a"
    ROW_FAIL = "#5a1a1a"

    def __init__(self, master):
        self.csv_rows = []      # [(name, start_tc), ...]
        self.name_index = {}    # nom -> [MediaPoolItem, ...]
        self.plan = []          # lignes préparées pour preview/apply
        super().__init__(master, "CSV → Start TC",
                          f"DaVinci Resolve  ·  {pm_common.RESOLVE_VARIANT}")
        self._init_resolve()

    def _build_content(self, main):
        top = tk.Frame(main, bg=Theme.DARK_BG)
        top.pack(fill="x")
        tk.Label(top, text="Chemin CSV :", bg=Theme.DARK_BG, fg=Theme.FG).pack(side="left")

        self.path_var = tk.StringVar()
        self.entry_path = tk.Entry(top, textvariable=self.path_var, bg=Theme.PANEL_BG,
                                    fg=Theme.FG, insertbackground=Theme.FG, relief="flat", width=50)
        self.entry_path.pack(side="left", padx=6, ipady=3)
        self.entry_path.bind("<Return>", lambda e: self.on_load_csv())

        self.button(top, "Parcourir…", Theme.PANEL_BG, self.on_browse, side="left", padx_l=0)
        self.button(top, "Charger", Theme.PANEL_BG, self.on_load_csv, side="left", padx_l=6)
        self.btn_apply = self.button(top, "Appliquer", Theme.SUCCESS, self.on_apply, side="right")
        self.btn_apply.config(state="disabled")

        status_row = tk.Frame(main, bg=Theme.DARK_BG)
        status_row.pack(fill="x", pady=(6, 0))
        self.lbl_csv = tk.Label(status_row, text="Aucun CSV chargé", bg=Theme.DARK_BG, fg=Theme.FG)
        self.lbl_csv.pack(side="left")

        columns = ("name", "old_tc", "new_tc", "status")
        self.tree = ttk.Treeview(main, columns=columns, show="headings", height=14)
        headers = {"name": "Clip Name", "old_tc": "Start TC actuel",
                   "new_tc": "Start TC (CSV)", "status": "Statut"}
        widths = {"name": 300, "old_tc": 150, "new_tc": 150, "status": 240}
        for col in columns:
            self.tree.heading(col, text=headers[col])
            self.tree.column(col, width=widths[col], anchor="w")
        self.tree.pack(fill="both", expand=True, pady=(10, 8))

        self.tree.tag_configure("ok", background=self.ROW_OK)
        self.tree.tag_configure("dup", background=self.ROW_DUP)
        self.tree.tag_configure("missing", background=self.ROW_MISSING)
        self.tree.tag_configure("fail", background=self.ROW_FAIL)

        self.log = self.build_log(main, height=8)

    # ---------------------------------------------------------- Resolve init
    def _init_resolve(self):
        try:
            self.resolve, self.project, self.media_pool = pm_common.get_resolve_objects()
            self.log_write(self.log, f"Connecté à Resolve (variante détectée : {pm_common.RESOLVE_VARIANT}).\n", "dim")
            self.log_write(self.log, f"Projet actif : {self.project.GetName()}\n", "dim")
        except Exception as e:
            messagebox.showerror("Erreur de connexion", str(e))
            self.resolve = self.project = self.media_pool = None

    # ---------------------------------------------------------------- Parcourir
    def on_browse(self):
        """Tente d'ouvrir le dialogue natif. Dans l'environnement sandboxé de Resolve,
        ce dialogue peut échouer silencieusement ou planter — on protège l'appel et on
        retombe sur la saisie manuelle du chemin si besoin."""
        try:
            path = filedialog.askopenfilename(
                title="Choisir le fichier CSV",
                filetypes=[("CSV", "*.csv"), ("Tous les fichiers", "*.*")]
            )
        except Exception as e:
            self.log_write(self.log, f"[INFO] Le dialogue natif a échoué ({e}). "
                            "Colle le chemin du CSV directement dans le champ ci-dessus.\n", "dim")
            return

        if path:
            self.path_var.set(path)
            self.on_load_csv()
        else:
            self.log_write(self.log, "[INFO] Aucun fichier sélectionné (ou dialogue non supporté ici). "
                            "Colle le chemin du CSV directement dans le champ ci-dessus.\n", "dim")

    # ---------------------------------------------------------------- Charger CSV
    def on_load_csv(self):
        if self.media_pool is None:
            messagebox.showerror("Erreur", "Pas de connexion active à Resolve.")
            return

        raw_path = self.path_var.get().strip()
        path = raw_path.strip('"').strip("'").replace("\\ ", " ")
        path = os.path.expanduser(path)

        if not path:
            messagebox.showwarning("Chemin manquant", "Colle ou choisis d'abord le chemin du CSV.")
            return
        if not os.path.isfile(path):
            messagebox.showerror("Fichier introuvable", f"Aucun fichier à ce chemin :\n{path}")
            self.log_write(self.log, f"[ERREUR] Fichier introuvable : {path}\n", "err")
            return

        try:
            self.csv_rows = read_csv_rows(path)
        except Exception as e:
            messagebox.showerror("Erreur de lecture CSV", str(e))
            return

        self.lbl_csv.config(text=os.path.basename(path))
        self.log_write(self.log, f"\nCSV chargé : {path} ({len(self.csv_rows)} lignes)\n", "dim")

        all_clips = []
        collect_all_clips(self.media_pool.GetRootFolder(), all_clips)
        self.name_index = build_name_index(all_clips)
        self.log_write(self.log, f"{len(all_clips)} clips trouvés dans le Media Pool (tous bins confondus).\n", "dim")

        self._build_plan()

    # ---------------------------------------------------------------- Plan / preview
    def _build_plan(self):
        self.tree.delete(*self.tree.get_children())
        self.plan = []
        n_ok, n_dup, n_missing = 0, 0, 0

        for name, new_tc in self.csv_rows:
            matches = self.name_index.get(name, [])

            if len(matches) == 0:
                self.tree.insert("", "end", values=(name, "-", new_tc, "Introuvable dans le Media Pool"), tags=("missing",))
                self.log_write(self.log, f"[NON TROUVÉ] '{name}' — aucun clip correspondant dans le Media Pool.\n", "warn")
                n_missing += 1
                continue

            if len(matches) > 1:
                self.tree.insert("", "end", values=(name, "-", new_tc, f"Doublon ({len(matches)} clips) — ignoré"), tags=("dup",))
                self.log_write(self.log, f"[DOUBLON] '{name}' — {len(matches)} clips portent ce nom, ligne ignorée.\n", "warn")
                n_dup += 1
                continue

            clip = matches[0]
            try:
                old_tc = clip.GetClipProperty("Start TC") or ""
            except Exception:
                old_tc = ""

            self.tree.insert("", "end", values=(name, old_tc, new_tc, "Prêt"), tags=("ok",))
            self.plan.append({"clip": clip, "name": name, "old_tc": old_tc, "new_tc": new_tc})
            n_ok += 1

        self.log_write(self.log, f"\nRésumé preview : {n_ok} prêt(s), {n_dup} doublon(s) ignoré(s), "
                        f"{n_missing} introuvable(s).\n", "accent")
        self.btn_apply.config(state="normal" if n_ok > 0 else "disabled")

    # ---------------------------------------------------------------- Apply
    def on_apply(self):
        if not self.plan:
            return
        if not messagebox.askyesno(
            "Confirmer",
            f"Appliquer le nouveau Start TC sur {len(self.plan)} clip(s) ?\n"
            "Cette action passe par l'historique d'annulation de Resolve (undo standard)."
        ):
            return

        n_success, n_fail = 0, 0
        self.log_write(self.log, "\n── Application ──\n", "accent")

        for item in self.plan:
            clip = item["clip"]
            name = item["name"]
            new_tc = item["new_tc"]

            try:
                clip.SetClipProperty("Start TC", new_tc)
            except Exception as e:
                self.log_write(self.log, f"[ÉCHEC] '{name}' — exception à l'écriture : {e}\n", "err")
                pm_common.write_error_log(TOOL_NAME, e)
                n_fail += 1
                self._mark_row(name, "fail", f"Échec (exception : {e})")
                continue

            try:
                confirmed_tc = clip.GetClipProperty("Start TC") or ""
            except Exception:
                confirmed_tc = ""

            if confirmed_tc.strip() == new_tc.strip():
                self.log_write(self.log, f"[OK] '{name}' — Start TC mis à jour : {item['old_tc']} → {confirmed_tc}\n", "ok")
                n_success += 1
                self._mark_row(name, "ok", f"Appliqué ({confirmed_tc})")
            else:
                self.log_write(self.log, f"[ÉCHEC] '{name}' — écriture non confirmée "
                                f"(attendu '{new_tc}', lu '{confirmed_tc}'). "
                                "Probable rejet Resolve (média avec TC embarqué).\n", "err")
                n_fail += 1
                self._mark_row(name, "fail", f"Rejeté par Resolve (lu : {confirmed_tc or 'vide'})")

        self.log_write(self.log, f"\nTerminé : {n_success} succès, {n_fail} échec(s).\n", "accent")
        messagebox.showinfo("Terminé", f"{n_success} clip(s) mis à jour avec succès.\n{n_fail} échec(s) — voir le log.")

    def _mark_row(self, name, tag, status_text):
        for iid in self.tree.get_children():
            values = self.tree.item(iid, "values")
            if values[0] == name:
                self.tree.item(iid, values=(values[0], values[1], values[2], status_text), tags=(tag,))
                break


def open_window(master):
    return CsvToTcWindow(master)
