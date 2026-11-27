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
import io
import re
import tkinter as tk
from tkinter import ttk, messagebox

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pm_common
from pm_common import PMWindow, Theme
from pm_tools.i18n import tr

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


NAME_ALIASES = ["name", "clip name", "clipname", "file name", "filename", "file", "nom",
                "nom du clip", "nom de fichier", "clip", "source file", "source name"]
START_ALIASES = ["start", "start tc", "starttc", "start timecode", "timecode", "time code",
                 "tc", "tc in", "source in", "source tc", "debut", "début", "tc debut", "tc début"]


class ColumnsNotFound(ValueError):
    """Colonnes Name/Start introuvables. Porte les en-têtes lus et les meilleures suppositions."""

    def __init__(self, fieldnames, name_col=None, start_col=None):
        self.fieldnames = list(fieldnames)
        self.name_col = name_col
        self.start_col = start_col
        super().__init__(
            tr("Colonnes requises introuvables. Colonnes détectées : {0}\n"
               "Le CSV doit contenir une colonne 'Name' et une colonne 'Start'.",
               self.fieldnames)
        )


def detect_columns(fieldnames):
    """Retourne (name_col, start_col) : colonne exacte 'Name'/'Start' d'abord, puis alias courants.
    Une valeur vaut None si rien ne correspond."""
    norm = {(fn or "").strip().lower(): fn for fn in fieldnames}

    def pick(aliases):
        for a in aliases:
            if a in norm:
                return norm[a]
        return None

    return pick(NAME_ALIASES), pick(START_ALIASES)


_TC_OK = re.compile(r"^(\d\d):(\d\d):(\d\d)([:;])(\d\d)$")


def normalize_tc(raw):
    """
    Valide / répare un timecode. Retourne (tc, statut, détail) :
      statut "ok"      — déjà au format HH:MM:SS:FF (ou ;FF en drop-frame)
      statut "fixed"   — réparé automatiquement (détail = ce qui a été corrigé)
      statut "invalid" — irréparable (détail = raison)
    """
    s = (raw or "").strip()
    if not s:
        return "", "invalid", tr("TC vide")
    m = _TC_OK.match(s)
    if m:
        h, mi, se = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if h > 23 or mi > 59 or se > 59:
            return s, "invalid", tr("heures/minutes/secondes hors limites")
        return s, "ok", ""

    last_sep = ";" if re.search(r"\d;\d+$", s) else ":"       # drop-frame : on garde le ';' final
    if re.fullmatch(r"\d{6}|\d{8}", s):
        parts = [s[i:i + 2] for i in range(0, len(s), 2)]
    else:
        parts = re.split(r"[:;.,\s]+", s)
    if not parts or not all(p.isdigit() and len(p) <= 3 for p in parts) or len(parts) not in (3, 4):
        return s, "invalid", tr("format non reconnu (attendu HH:MM:SS:FF)")
    note = []
    if len(parts) == 3:
        parts.append("00")
        note.append(tr("images ajoutées (:00)"))
    parts = [p.zfill(2) for p in parts]
    if any(len(p) > 2 for p in parts):
        return s, "invalid", tr("champ trop long (attendu HH:MM:SS:FF)")
    if int(parts[0]) > 23 or int(parts[1]) > 59 or int(parts[2]) > 59:
        return s, "invalid", tr("heures/minutes/secondes hors limites")
    fixed = ":".join(parts[:3]) + last_sep + parts[3]
    if not note:
        note.append(tr("séparateurs/zéros normalisés"))
    return fixed, "fixed", ", ".join(note)


def read_csv_rows(path, columns=None, info=None):
    """
    Retourne une liste de tuples (name, start_tc) depuis le CSV.
    Détecte automatiquement , ou ; comme délimiteur, et reconnaît les en-têtes
    courants (Clip Name, Timecode, Start TC, Nom…).
    columns=(name_col, start_col) force le choix des colonnes (dialogue de mappage).
    info (dict, optionnel) reçoit 'name_col', 'start_col' et 'auto' (True si alias).
    Lève ColumnsNotFound (ValueError) si les colonnes restent introuvables.
    """
    # UTF-16 (export Resolve), UTF-8 ou encodages Excel — détectés automatiquement
    with io.StringIO(pm_common.read_text_file(path), newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(f, dialect=dialect)

        fieldnames = reader.fieldnames or []
        if columns:
            name_col, start_col = columns
        else:
            name_col, start_col = detect_columns(fieldnames)
        if name_col not in fieldnames or start_col not in fieldnames:
            raise ColumnsNotFound(fieldnames, name_col, start_col)
        if info is not None:
            info.update(name_col=name_col, start_col=start_col,
                        auto=(name_col.strip().lower() != "name" or start_col.strip().lower() != "start"))

        rows = []
        for row in reader:
            name = (row.get(name_col) or "").strip()
            start = (row.get(start_col) or "").strip()
            if name:
                rows.append((name, start))
        return rows


SAMPLE_FILENAME = "exemple_StartTC.csv"
SAMPLE_ROWS = [
    ("Name", "Start"),
    ("A001_C001_0101AB.mov", "01:00:00:00"),
    ("A001_C002_0101AB.mov", "01:05:12:10"),
    ("B002_C001_0102CD.mov", "02:00:00:00"),
]


def write_sample_csv(folder):
    """Écrit le CSV exemple dans folder sans écraser un fichier existant. Retourne le chemin."""
    base, ext = os.path.splitext(tr(SAMPLE_FILENAME))
    path = os.path.join(folder, tr(SAMPLE_FILENAME))
    n = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{base}_{n}{ext}")
        n += 1
    # UTF-8 avec BOM : s'ouvre correctement dans Excel (accents) et est relu par read_csv_rows
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows(SAMPLE_ROWS)
    return path


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
        tk.Label(top, text=tr("Chemin CSV :"), bg=Theme.DARK_BG, fg=Theme.FG).pack(side="left")

        self.path_var = tk.StringVar()
        self.entry_path = tk.Entry(top, textvariable=self.path_var, bg=Theme.PANEL_BG,
                                    fg=Theme.FG, insertbackground=Theme.FG, relief="flat", width=50)
        self.entry_path.pack(side="left", padx=6, ipady=3)
        self.entry_path.bind("<Return>", lambda e: self.on_load_csv())

        self.button(top, tr("Parcourir…"), Theme.PANEL_BG, self.on_browse, side="left", padx_l=0)
        self.button(top, tr("Charger"), Theme.PANEL_BG, self.on_load_csv, side="left", padx_l=6)
        self.button(top, tr("CSV exemple…"), Theme.PANEL_BG, self.on_sample_csv, side="left", padx_l=6)
        self.btn_apply = self.button(top, tr("Appliquer"), Theme.SUCCESS, self.on_apply, side="right")
        self.btn_apply.config(state="disabled")

        status_row = tk.Frame(main, bg=Theme.DARK_BG)
        status_row.pack(fill="x", pady=(6, 0))
        self.lbl_csv = tk.Label(status_row, text=tr("Aucun CSV chargé"), bg=Theme.DARK_BG, fg=Theme.FG)
        self.lbl_csv.pack(side="left")

        columns = ("name", "old_tc", "new_tc", "status")
        self.tree = ttk.Treeview(main, columns=columns, show="headings", height=14)
        headers = {"name": "Clip Name", "old_tc": tr("Start TC actuel"),
                   "new_tc": "Start TC (CSV)", "status": tr("Statut")}
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
            self.log_write(self.log, tr("Connecté à Resolve (variante détectée : {0}).\n",
                                        pm_common.RESOLVE_VARIANT), "dim")
            self.log_write(self.log, tr("Projet actif : {0}\n", self.project.GetName()), "dim")
        except Exception as e:
            messagebox.showerror(tr("Erreur de connexion"), str(e))
            self.resolve = self.project = self.media_pool = None

    # ---------------------------------------------------------------- Parcourir
    def on_browse(self):
        """Ouvre le sélecteur système (osascript) ; filedialog ne s'affiche pas de façon
        fiable dans Resolve. En cas d'échec, saisie manuelle du chemin."""
        path = pm_common.pick_file(tr("Choisir le fichier CSV"), ["csv"], parent=self)

        if path:
            self.path_var.set(path)
            self.on_load_csv()
        else:
            self.log_write(self.log, tr("[INFO] Aucun fichier sélectionné (ou dialogue non supporté ici). Colle le chemin du "
                                        "CSV directement dans le champ ci-dessus.\n"), "dim")

    # ---------------------------------------------------------------- CSV exemple
    def on_sample_csv(self):
        folder = pm_common.pick_folder(tr("Où enregistrer le CSV exemple ?"), parent=self)
        if not folder:
            return
        self._create_sample(folder)

    def _create_sample(self, folder):
        try:
            path = write_sample_csv(folder)
        except OSError as e:
            messagebox.showerror(tr("Erreur"), tr("Impossible d'écrire le CSV exemple :\n{0}", e))
            return
        self.log_write(self.log, tr("CSV exemple créé : {0}\nFormat : colonnes 'Name' (nom exact du clip) et 'Start' "
                                    "(HH:MM:SS:FF), séparateur , ou ;\n",
                                    path), "ok")
        messagebox.showinfo(tr("CSV exemple créé"),
                            tr("{0}\n\nColonnes : Name (nom du clip tel qu'affiché dans le Media Pool) et Start "
                               "(timecode HH:MM:SS:FF).", path))

    def _ask_columns(self, err):
        """Dialogue d'association des colonnes. Retourne (name, start) ou None."""
        headers = err.fieldnames

        def index(name):
            return headers.index(name) if name in headers else None

        def sample(window):
            folder = pm_common.pick_folder(tr("Où enregistrer le CSV exemple ?"), parent=window)
            if folder:
                self._create_sample(folder)

        chosen = pm_common.ask_columns(
            self, tr("Je ne reconnais pas les colonnes de ce CSV.\n"
                     "Indique laquelle contient le nom du clip et laquelle contient le Start TC\n"
                     "(ou génère un CSV exemple pour voir le format attendu)."),
            [(tr("Nom du clip :"), index(err.name_col), True), (tr("Start TC :"), index(err.start_col), True)],
            headers, sample)
        return None if chosen is None else tuple(headers[i] for i in chosen)

    # ---------------------------------------------------------------- Charger CSV
    def on_load_csv(self):
        if self.media_pool is None:
            messagebox.showerror(tr("Erreur"), tr("Pas de connexion active à Resolve."))
            return

        raw_path = self.path_var.get().strip()
        path = raw_path.strip('"').strip("'").replace("\\ ", " ")
        path = os.path.expanduser(path)

        if not path:
            messagebox.showwarning(tr("Chemin manquant"), tr("Colle ou choisis d'abord le chemin du CSV."))
            return
        if not os.path.isfile(path):
            messagebox.showerror(tr("Fichier introuvable"), tr("Aucun fichier à ce chemin :\n{0}", path))
            self.log_write(self.log, tr("[ERREUR] Fichier introuvable : {0}\n", path), "err")
            return

        info = {}
        try:
            try:
                self.csv_rows = read_csv_rows(path, info=info)
            except ColumnsNotFound as e:
                cols = self._ask_columns(e)
                if not cols:
                    self.log_write(self.log, tr("[INFO] Chargement annulé : colonnes non identifiées.\n"), "warn")
                    return
                self.csv_rows = read_csv_rows(path, columns=cols, info=info)
                info["auto"] = True
        except Exception as e:
            messagebox.showerror(tr("Erreur de lecture CSV"), str(e))
            return
        if info.get("auto"):
            self.log_write(self.log, tr("Colonnes utilisées : '{0}' → nom du clip, '{1}' → Start TC.\n",
                                        info['name_col'], info['start_col']), "dim")

        self.lbl_csv.config(text=os.path.basename(path))
        self.log_write(self.log, tr("\nCSV chargé : {0} ({1} lignes)\n", path, len(self.csv_rows)), "dim")

        all_clips = []
        collect_all_clips(self.media_pool.GetRootFolder(), all_clips)
        self.name_index = build_name_index(all_clips)
        self.log_write(self.log, tr("{0} clips trouvés dans le Media Pool (tous bins confondus).\n",
                                    len(all_clips)), "dim")

        self._build_plan()

    # ---------------------------------------------------------------- Plan / preview
    def _build_plan(self):
        self.tree.delete(*self.tree.get_children())
        self.plan = []
        n_ok, n_dup, n_missing, n_fixed, n_bad = 0, 0, 0, 0, 0

        for name, raw_tc in self.csv_rows:
            new_tc, tc_state, tc_note = normalize_tc(raw_tc)
            if tc_state == "invalid":
                self.tree.insert("", "end", values=(name, "-", raw_tc, tr("TC invalide : {0}", tc_note)), tags=("fail",))
                self.log_write(self.log, tr("[TC INVALIDE] '{0}' — '{1}' : {2}. Ligne ignorée.\n",
                                            name, raw_tc, tc_note), "warn")
                n_bad += 1
                continue
            matches = self.name_index.get(name, [])

            if len(matches) == 0:
                self.tree.insert("", "end", values=(name, "-", new_tc, tr("Introuvable dans le Media Pool")), tags=("missing",))
                self.log_write(self.log, tr("[NON TROUVÉ] '{0}' — aucun clip correspondant dans le Media Pool.\n",
                                            name), "warn")
                n_missing += 1
                continue

            if len(matches) > 1:
                self.tree.insert("", "end", values=(name, "-", new_tc, tr("Doublon ({0} clips) — ignoré",
                                                                          len(matches))), tags=("dup",))
                self.log_write(self.log, tr("[DOUBLON] '{0}' — {1} clips portent ce nom, ligne ignorée.\n",
                                            name, len(matches)), "warn")
                n_dup += 1
                continue

            clip = matches[0]
            try:
                old_tc = clip.GetClipProperty("Start TC") or ""
            except Exception:
                old_tc = ""

            status = tr("Prêt")
            if tc_state == "fixed":
                status = tr("Prêt — TC corrigé ('{0}' : {1})", raw_tc, tc_note)
                self.log_write(self.log, tr("[TC CORRIGÉ] '{0}' — '{1}' → '{2}' ({3}).\n",
                                            name, raw_tc, new_tc, tc_note), "warn")
                n_fixed += 1
            self.tree.insert("", "end", values=(name, old_tc, new_tc, status), tags=("ok",))
            self.plan.append({"clip": clip, "name": name, "old_tc": old_tc, "new_tc": new_tc})
            n_ok += 1

        self.log_write(self.log, tr("\nRésumé preview : {0} prêt(s), {1} doublon(s) ignoré(s), {2} introuvable(s), {3} TC "
                                    "invalide(s), {4} TC corrigé(s) automatiquement.\n",
                                    n_ok, n_dup, n_missing, n_bad, n_fixed), "accent")
        self.btn_apply.config(state="normal" if n_ok > 0 else "disabled")

    # ---------------------------------------------------------------- Apply
    def on_apply(self):
        if not self.plan:
            return
        if not messagebox.askyesno(
            tr("Confirmer"),
            tr("Appliquer le nouveau Start TC sur {0} clip(s) ?\n"
               "Cette action passe par l'historique d'annulation de Resolve (undo standard).",
               len(self.plan))
        ):
            return

        n_success, n_fail = 0, 0
        self.log_write(self.log, tr("\n── Application ──\n"), "accent")

        for item in self.plan:
            clip = item["clip"]
            name = item["name"]
            new_tc = item["new_tc"]

            try:
                clip.SetClipProperty("Start TC", new_tc)
            except Exception as e:
                self.log_write(self.log, tr("[ÉCHEC] '{0}' — exception à l'écriture : {1}\n", name, e), "err")
                pm_common.write_error_log(TOOL_NAME, e)
                n_fail += 1
                self._mark_row(name, "fail", tr("Échec (exception : {0})", e))
                continue

            try:
                confirmed_tc = clip.GetClipProperty("Start TC") or ""
            except Exception:
                confirmed_tc = ""

            if confirmed_tc.strip() == new_tc.strip():
                self.log_write(self.log, tr("[OK] '{0}' — Start TC mis à jour : {1} → {2}\n",
                                            name, item['old_tc'], confirmed_tc), "ok")
                n_success += 1
                self._mark_row(name, "ok", tr("Appliqué ({0})", confirmed_tc))
            else:
                self.log_write(self.log, tr("[ÉCHEC] '{0}' — écriture non confirmée (attendu '{1}', lu '{2}'). Probable rejet "
                                            "Resolve (média avec TC embarqué).\n",
                                            name, new_tc, confirmed_tc), "err")
                n_fail += 1
                self._mark_row(name, "fail", tr("Rejeté par Resolve (lu : {0})", confirmed_tc or tr("vide")))

        self.log_write(self.log, tr("\nTerminé : {0} succès, {1} échec(s).\n", n_success, n_fail), "accent")
        messagebox.showinfo(tr("Terminé"), tr("{0} clip(s) mis à jour avec succès.\n{1} échec(s) — voir le log.",
                                          n_success, n_fail))

    def _mark_row(self, name, tag, status_text):
        for iid in self.tree.get_children():
            values = self.tree.item(iid, "values")
            if values[0] == name:
                self.tree.item(iid, values=(values[0], values[1], values[2], status_text), tags=(tag,))
                break


def open_window(master):
    return CsvToTcWindow(master)
