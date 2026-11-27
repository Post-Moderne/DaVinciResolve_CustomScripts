#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CSV → VFX ID — charge un .csv (VFX ID + timecode record) puis, au choix,
renomme les clips de la timeline active dont le point d'entrée correspond au
timecode record et/ou pose des markers timeline.
Module interne de la PM Suite (voir PM-Suite.py).

Colonnes reconnues (insensible à la casse, , ou ; comme délimiteur) :
  • VFX ID   : "VFX ID", "VFX_ID", "VFXID", "ID", "Name", "Nom", "Shot"
  • Record TC: "Record In", "Rec In", "Record TC", "Rec TC", "Record Start",
               "Start", "TC In", "Timecode"
  • Notes (facultatif) : "Notes", "Commentaires", "Comments", "Remarques", "À faire"…
    → description du marker timeline si l'option « Marker » est cochée

MATCHING
─────────
Le TC record du CSV est converti en frames (DF/NDF et cadence lus sur la
timeline) puis comparé à TimelineItem.GetStart(). Un clip dont le début tombe
exactement sur le TC est prioritaire ; à défaut, on accepte (avec avertissement)
un clip qui *contient* le TC — cas d'un TC pris au milieu d'un plan.

Sans l'option « Renommer les clips », aucun clip n'est cherché : chaque marker
est posé exactement au TC du CSV, qu'il y ait un clip dessous ou non.

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
from pm_tools.i18n import tr, choices, source

TOOL_NAME = "PM-Resolve_CSV-to-VFXid"

ID_HEADERS = ("vfx id", "vfx_id", "vfxid", "vfx-id", "id", "name", "nom", "shot")
TC_HEADERS = ("rec tc in", "record tc in", "record in", "rec in", "record_in", "rec_in", "record tc", "rec tc",
              "record start", "rec start", "start", "tc in", "tc_in", "timecode", "tc")

NOTES_HEADERS = ("notes", "note", "commentaires", "commentaire", "comments", "comment",
                 "remarques", "remarque", "à faire", "a faire", "travail", "to do", "todo")

# Couleurs de markers Resolve (noms exacts attendus par Timeline.AddMarker)
MARKER_COLORS = ["Blue", "Cyan", "Green", "Yellow", "Red", "Pink", "Purple", "Fuchsia",
                 "Rose", "Lavender", "Sky", "Mint", "Lemon", "Sand", "Cocoa", "Cream"]
MARKER_POSITIONS = ["Début", "Milieu", "Fin"]     # position du marker sur le clip renommé
ALL_TRACKS = "Toutes"
MARKER_TAG = "PM-VFXID"     # customData : reconnaît nos markers pour les remplacer à la relance

TC_RE = re.compile(r"^\s*(\d{1,2})[:;.](\d{2})[:;.](\d{2})[:;.](\d{2})\s*$")


# ── Logique pure (testable hors Resolve) ───────────────────────────────────────
def tc_to_frames(tc, fps, drop_frame=False):
    """'HH:MM:SS:FF' → numéro de frame absolu. Lève ValueError si le format est invalide."""
    m = TC_RE.match(tc or "")
    if not m:
        raise ValueError(tr("Timecode invalide : '{0}' (attendu HH:MM:SS:FF)", tc))
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
    """Lit le CSV : UTF-16 (export Resolve), UTF-8, MacRoman (Excel Mac) puis cp1252 (Excel Windows)."""
    return pm_common.read_text_file(path)


class ColumnsNotFound(ValueError):
    """
    Colonnes VFX ID / TC record introuvables ; le message explique quoi corriger.
    Porte la ligne d'en-têtes supposée (header_row, headers) et les colonnes devinées
    (guess = id, tc, notes) pour le dialogue d'association.
    """

    def __init__(self, message, header_row=0, headers=(), guess=(None, None, None)):
        super().__init__(message)
        self.header_row = header_row
        self.headers = list(headers)
        self.guess = guess


SAMPLE_FILENAME = "exemple_VFX-ID.csv"
SAMPLE_ROWS = [
    ("VFX ID", "Record In", "Notes"),
    ("VFX_010", "01:00:05:00", "Retirer le fil visible à gauche"),
    ("VFX_020", "01:00:12:10", "Remplacer l'écran du téléphone"),
    ("VFX_030", "01:01:03:00", ""),
]


def write_sample_csv(folder):
    """Écrit le CSV exemple dans folder sans écraser un fichier existant. Retourne le chemin."""
    base, ext = os.path.splitext(tr(SAMPLE_FILENAME))
    path = os.path.join(folder, tr(SAMPLE_FILENAME))
    n = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{base}_{n}{ext}")
        n += 1
    with open(path, "w", encoding="utf-8-sig", newline="") as f:      # BOM : accents corrects dans Excel
        header, *rows = SAMPLE_ROWS
        csv.writer(f).writerows([header] + [(i, tc, tr(note) if note else "") for i, tc, note in rows])
    return path


def find_notes_column(header, taken=()):
    """Index de la colonne de notes parmi les colonnes non déjà utilisées (`taken`), sinon None."""
    return find_column([None if i in taken else h for i, h in enumerate(header)], NOTES_HEADERS)


def guess_header_row(rows):
    """Ligne d'en-têtes la plus probable : une ligne avec une colonne reconnue, sinon la 1re à 2 cellules."""
    head = rows[:15]
    for i, row in enumerate(head):
        if find_column(row, ID_HEADERS) is not None or find_column(row, TC_HEADERS) is not None:
            if sum(1 for c in row if c.strip()) >= 2:
                return i
    return next((i for i, row in enumerate(head) if sum(1 for c in row if c.strip()) >= 2), 0)


def _detect_columns(rows):
    """(ligne d'en-têtes, id, tc, notes) reconnus automatiquement, sinon lève ColumnsNotFound."""
    for i, header in enumerate(rows[:15]):
        id_col = find_column(header, ID_HEADERS)
        tc_col = find_column(header, TC_HEADERS)
        if id_col is not None and tc_col is not None:
            return i, id_col, tc_col, find_notes_column(header, (id_col, tc_col))

    first = next((r for r in rows[:15] if any(c.strip() for c in r)), [])
    problems = []
    if not any(find_column(r, ID_HEADERS) is not None for r in rows[:15]):
        problems.append(tr("la colonne VFX ID (nom : VFX ID, ID, Shot, Nom…)"))
    if not any(find_column(r, TC_HEADERS) is not None for r in rows[:15]):
        problems.append(tr("la colonne du TC record (nom : Record In, Rec In, Start, Timecode…)"))
    message = tr("Ce CSV ne peut pas être lu : il manque ") + tr(" et ").join(problems) + tr(
        ".\n\nColonnes lues dans ton fichier : {0}\n\n"
        "Il faut une ligne d'en-têtes avec au minimum :\n"
        "   VFX ID  |  Record In   (+ Notes, facultatif)\n"
        "   VFX_010 |  01:00:05:00\n\n"
        "Renomme les en-têtes dans ton CSV, ou génère un CSV exemple.",
        ', '.join(c.strip() or tr("(vide)") for c in first) or tr("(fichier vide)"))

    row = guess_header_row(rows)
    headers = rows[row] if rows else []
    id_col, tc_col = find_column(headers, ID_HEADERS), find_column(headers, TC_HEADERS)
    raise ColumnsNotFound(message, row, headers,
                          (id_col, tc_col, find_notes_column(headers, (id_col, tc_col))))


def read_csv_rows(path, columns=None):
    """
    Retourne une liste de tuples (vfx_id, record_tc, note) (note = "" sans colonne de notes). L'en-tête est cherché dans
    les 15 premières lignes (les exports de breakdown ont souvent une ligne de
    titre au-dessus). Lève ColumnsNotFound (ValueError) si les deux colonnes sont introuvables.
    columns = (ligne d'en-têtes, id, tc, notes ou None) : association choisie à la main.
    """
    text = read_text(path)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text, newline=""), dialect=dialect))

    i, id_col, tc_col, notes_col = columns or _detect_columns(rows)

    out = []
    for row in rows[i + 1:]:
        vfx_id = row[id_col].strip() if id_col < len(row) else ""
        tc = row[tc_col].strip() if tc_col < len(row) else ""
        note = row[notes_col].strip() if notes_col is not None and notes_col < len(row) else ""
        if vfx_id or tc:
            out.append((vfx_id, tc, note))
    return out


def marker_frame(item_start, item_end, timeline_start, position="Milieu"):
    """Frame du marker timeline au début, au milieu ou à la fin (dernière image) du clip ;
    item_end est exclusif. Timeline.AddMarker compte depuis le début de la timeline (et non
    depuis 01:00:00:00), d'où la soustraction de timeline_start."""
    if position == "Début":
        frame = item_start
    elif position == "Fin":
        frame = max(item_start, item_end - 1)
    else:
        frame = item_start + (item_end - item_start) // 2
    return frame - timeline_start


def marker_only_frame(frame, timeline_start, used):
    """
    Frame du marker timeline posé directement au TC (sans clip). used : {frame: vfx_id} déjà
    planifiés (Resolve n'accepte qu'un marker par frame). Lève ValueError si impossible.
    """
    rel = frame - timeline_start
    if rel < 0:
        raise ValueError(tr("TC avant le début de la timeline"))
    if rel in used:
        raise ValueError(tr("Même TC que '{0}'", used[rel]))
    return rel


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
        self.trace = pm_common.Trace.__new__(pm_common.Trace)   # inactif tant qu'aucun chargement
        self.trace._f = None
        super().__init__(master, "CSV → VFX ID",
                          f"DaVinci Resolve  ·  {pm_common.RESOLVE_VARIANT}")
        self._init_resolve()

    def _build_content(self, main):
        top = tk.Frame(main, bg=Theme.DARK_BG)
        top.pack(fill="x")
        tk.Label(top, text=tr("Chemin CSV :"), bg=Theme.DARK_BG, fg=Theme.FG).pack(side="left")
        self.path_var = tk.StringVar()
        entry = tk.Entry(top, textvariable=self.path_var, bg=Theme.PANEL_BG, fg=Theme.FG,
                          insertbackground=Theme.FG, relief="flat", width=50)
        entry.pack(side="left", padx=6, ipady=3)
        entry.bind("<Return>", lambda e: self.on_load_csv())
        self.button(top, tr("Parcourir…"), Theme.PANEL_BG, self.on_browse, side="left")
        self.button(top, tr("Charger"), Theme.PANEL_BG, self.on_load_csv, side="left", padx_l=6)
        self.button(top, tr("CSV exemple…"), Theme.PANEL_BG, self.on_sample_csv, side="left", padx_l=6)
        self.btn_apply = self.button(top, tr("Appliquer"), Theme.SUCCESS, self.on_apply, side="right")
        self.btn_apply.config(state="disabled")

        opts = tk.Frame(main, bg=Theme.DARK_BG)
        opts.pack(fill="x", pady=(8, 0))
        self.rename_var = tk.BooleanVar(value=True)
        tk.Checkbutton(opts, text=tr("Renommer les clips"),
                        variable=self.rename_var, command=self._on_mode_change,
                        bg=Theme.DARK_BG, fg=Theme.FG, activebackground=Theme.DARK_BG,
                        activeforeground=Theme.FG, selectcolor=Theme.PANEL_BG,
                        font=Theme.FONT_SM, bd=0).pack(side="left", padx=(0, 16))
        tk.Label(opts, text=tr("Piste vidéo :"), bg=Theme.DARK_BG, fg=Theme.FG).pack(side="left")
        self.track_var = tk.StringVar(value="V1")
        self.cmb_track = ttk.Combobox(opts, textvariable=self.track_var, width=8, state="readonly",
                                       values=["V1"])
        self.cmb_track.pack(side="left", padx=6)
        self.cmb_track.bind("<<ComboboxSelected>>", lambda e: self._rebuild_plan())
        self.inside_var = tk.BooleanVar(value=True)
        self.chk_inside = tk.Checkbutton(opts, text=tr("Accepter un TC à l'intérieur d'un clip"),
                        variable=self.inside_var, command=self._rebuild_plan,
                        bg=Theme.DARK_BG, fg=Theme.FG, activebackground=Theme.DARK_BG,
                        activeforeground=Theme.FG, selectcolor=Theme.PANEL_BG,
                        font=Theme.FONT_SM, bd=0)
        self.chk_inside.pack(side="left", padx=(16, 0))

        mk = tk.Frame(main, bg=Theme.DARK_BG)
        mk.pack(fill="x", pady=(6, 0))
        self.marker_var = tk.BooleanVar(value=True)
        tk.Checkbutton(mk, text=tr("Ajouter Marker timeline"),
                        variable=self.marker_var, command=self._on_mode_change,
                        bg=Theme.DARK_BG, fg=Theme.FG, activebackground=Theme.DARK_BG,
                        activeforeground=Theme.FG, selectcolor=Theme.PANEL_BG,
                        font=Theme.FONT_SM, bd=0).pack(side="left")
        tk.Label(mk, text=tr("Couleur :"), bg=Theme.DARK_BG, fg=Theme.FG).pack(side="left", padx=(16, 6))
        self.marker_color_var = tk.StringVar(value="Red")
        ttk.Combobox(mk, textvariable=self.marker_color_var, width=10, state="readonly",
                     values=MARKER_COLORS).pack(side="left")
        tk.Label(mk, text=tr("Position sur le clip :"), bg=Theme.DARK_BG, fg=Theme.FG).pack(side="left", padx=(16, 6))
        self.marker_pos_var = tk.StringVar(value=tr("Début"))
        self.cmb_marker_pos = ttk.Combobox(mk, textvariable=self.marker_pos_var, width=8,
                                           state="readonly", values=choices(MARKER_POSITIONS))
        self.cmb_marker_pos.pack(side="left")

        self.lbl_csv = tk.Label(main, text=tr("Aucun CSV chargé"), bg=Theme.DARK_BG, fg=Theme.FG)
        self.lbl_csv.pack(anchor="w", pady=(6, 0))

        columns = ("vfx_id", "tc", "clip", "note", "status")
        self.tree = ttk.Treeview(main, columns=columns, show="headings", height=14)
        for col, title, w in (("vfx_id", "VFX ID", 200), ("tc", tr("TC record"), 120),
                              ("clip", tr("Clip actuel"), 240), ("note", "Notes (CSV)", 220),
                              ("status", tr("Statut"), 260)):
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
            messagebox.showerror(tr("Erreur de connexion"), str(e))
            self.resolve = self.project = None
            return
        self.log_write(self.log, tr("Connecté à Resolve (variante : {0}).\n", pm_common.RESOLVE_VARIANT), "dim")
        self._refresh_timeline()

    def _refresh_timeline(self):
        """Relit la timeline active, sa cadence/DF et la liste des pistes vidéo."""
        self.trace.step("API : GetCurrentTimeline")
        self.timeline = self.project.GetCurrentTimeline() if self.project else None
        self.trace.step("API : timeline obtenue")
        if not self.timeline:
            self.log_write(self.log, tr("[ERREUR] Aucune timeline active.\n"), "err")
            return False
        try:
            self.fps = float(self.timeline.GetSetting("timelineFrameRate") or 24)
        except (TypeError, ValueError):
            self.fps = 24.0
        self.drop_frame = str(self.timeline.GetSetting("timelineDropFrameTimecode")) == "1"
        self.trace.step("API : réglages de la timeline lus")
        n = int(self.timeline.GetTrackCount("video") or 1)
        self.trace.step(f"API : {n} piste(s) vidéo")
        self.cmb_track.config(values=[tr(ALL_TRACKS)] + [f"V{i}" for i in range(1, n + 1)])
        if self.track_var.get() not in self.cmb_track["values"]:
            self.track_var.set("V1")
        self.log_write(self.log, tr("Timeline : {0}  ·  {1:g} fps{2}  ·  {3} piste(s) vidéo\n",
                                    self.timeline.GetName(), self.fps, ' DF' if self.drop_frame else '', n), "dim")
        return True

    def _track_items(self):
        """Retourne [(item, start, end), ...] pour la/les piste(s) choisie(s)."""
        sel = self.track_var.get()
        n = int(self.timeline.GetTrackCount("video") or 1)
        tracks = range(1, n + 1) if source(sel, (ALL_TRACKS,)) == ALL_TRACKS else [int(sel[1:])]
        out = []
        for t in tracks:
            self.trace.step(f"piste V{t} : lecture des clips")
            lst = self.timeline.GetItemListInTrack("video", t) or []
            self.trace.step(f"piste V{t} : {len(lst)} clip(s), lecture des positions")
            for it in lst:
                out.append((it, int(it.GetStart()), int(it.GetEnd())))
        self.trace.step(f"{len(out)} clip(s) indexés")
        return out

    # ---------------------------------------------------------------- CSV
    def on_browse(self):
        path = pm_common.pick_file(tr("Choisir le fichier CSV"), ["csv"], parent=self)
        if path:
            self.path_var.set(path)
            self.on_load_csv()
        else:
            self.log_write(self.log, tr("[INFO] Aucun fichier choisi (ou sélecteur indisponible). Colle le chemin du CSV "
                                        "dans le champ.\n"), "dim")

    def on_sample_csv(self, parent=None):
        """Écrit un CSV exemple (VFX ID / Record In / Notes) dans le dossier choisi."""
        folder = pm_common.pick_folder(tr("Où enregistrer le CSV exemple ?"), parent=parent or self)
        if not folder:
            return
        try:
            path = write_sample_csv(folder)
        except OSError as e:
            messagebox.showerror(tr("Erreur"), tr("Impossible d'écrire le CSV exemple :\n{0}", e))
            return
        self.log_write(self.log, tr("CSV exemple créé : {0}\n", path), "ok")
        messagebox.showinfo(tr("CSV exemple créé"),
                            tr("{0}\n\nColonnes : VFX ID (nom du plan), Record In (TC d'entrée du clip dans la "
                               "timeline, HH:MM:SS:FF) et Notes (facultatif).",
                               path))

    def _ask_columns(self, err):
        """Dialogue d'association des colonnes. Retourne les columns de read_csv_rows ou None."""
        def sample(window):
            self.on_sample_csv(parent=window)

        id_col, tc_col, notes_col = err.guess
        chosen = pm_common.ask_columns(
            self, tr("Je ne reconnais pas les colonnes de ce CSV.\n"
                     "Indique laquelle contient le VFX ID et laquelle contient le TC record\n"
                     "(ou génère un CSV exemple pour voir le format attendu)."),
            [(tr("VFX ID :"), id_col, True), (tr("TC record :"), tc_col, True),
             (tr("Notes (facultatif) :"), notes_col, False)],
            err.headers, sample)
        return None if chosen is None else (err.header_row, *chosen)

    def _columns_or_sample(self, err):
        """Association manuelle ; sans au moins deux en-têtes, propose seulement un CSV exemple."""
        if sum(1 for h in err.headers if h.strip()) < 2:
            if messagebox.askyesno(tr("Colonnes introuvables"),
                                   tr("{0}\n\nCréer un CSV exemple maintenant ?", err)):
                self.on_sample_csv()
            return None
        columns = self._ask_columns(err)
        if not columns:
            self.log_write(self.log, tr("[INFO] Chargement annulé : colonnes non identifiées.\n"), "warn")
        return columns

    def _log_columns(self, headers, columns):
        _, id_col, tc_col, notes_col = columns
        self.log_write(self.log, tr("Colonnes utilisées : '{0}' → VFX ID, '{1}' → TC record, '{2}' → Notes.\n",
                                    headers[id_col], headers[tc_col],
                                    "-" if notes_col is None else headers[notes_col]), "dim")

    def on_load_csv(self):
        if self.project is None:
            messagebox.showerror(tr("Erreur"), tr("Pas de connexion active à Resolve."))
            return
        path = os.path.expanduser(self.path_var.get().strip().strip('"').strip("'").replace("\\ ", " "))
        if not os.path.isfile(path):
            messagebox.showerror(tr("Fichier introuvable"), tr("Aucun fichier à ce chemin :\n{0}", path))
            return
        # Trace + affichage immédiat : si Resolve fige, le fichier de trace dit à quelle étape.
        self.trace = pm_common.Trace(TOOL_NAME)
        self.lbl_csv.config(text=tr("Chargement de {0}…", os.path.basename(path)))
        self.log_write(self.log, tr("\nChargement : {0}\n", path), "dim")
        self.update_idletasks()
        try:
            self.trace.step(f"lecture du CSV : {path} ({os.path.getsize(path)} octets)")
            try:
                try:
                    self.csv_rows = read_csv_rows(path)
                except ColumnsNotFound as e:
                    self.trace.step("colonnes introuvables → dialogue")
                    self.trace.close()                  # le temps passé dans le dialogue n'est pas un gel
                    columns = self._columns_or_sample(e)
                    if not columns:
                        self.lbl_csv.config(text=tr("Aucun CSV chargé"))
                        return
                    self.trace = pm_common.Trace(TOOL_NAME)
                    self.csv_rows = read_csv_rows(path, columns=columns)
                    self._log_columns(e.headers, columns)
            except Exception as e:
                self.trace.step(f"erreur de lecture : {e!r}")
                self.trace.close(keep=True)
                self.lbl_csv.config(text=tr("Aucun CSV chargé"))
                messagebox.showerror(tr("Erreur de lecture CSV"), str(e))
                return
            self.trace.step(f"CSV lu : {len(self.csv_rows)} lignes")
            if not self._refresh_timeline():
                self.trace.close()
                self.lbl_csv.config(text=tr("Aucun CSV chargé"))
                messagebox.showerror(tr("Erreur"), tr("Ouvre d'abord une timeline dans Resolve."))
                return
            self.trace.step("timeline lue")
            self.lbl_csv.config(text=os.path.basename(path))
            self.log_write(self.log, tr("CSV chargé : {0} ({1} lignes)\n", path, len(self.csv_rows)), "dim")
            self._rebuild_plan()
            self.trace.step("terminé")
            self.trace.close()
        except Exception as e:
            self.trace.step(f"EXCEPTION : {e!r}")
            self.trace.close(keep=True)
            pm_common.write_error_log(TOOL_NAME, e)
            raise

    # ---------------------------------------------------------------- Plan
    def _on_mode_change(self):
        """Les options de recherche de clip n'ont de sens que si on renomme."""
        renaming = self.rename_var.get()
        self.cmb_track.config(state="readonly" if renaming else "disabled")
        self.chk_inside.config(state="normal" if renaming else "disabled")
        self.cmb_marker_pos.config(state="readonly" if renaming and self.marker_var.get() else "disabled")
        self._rebuild_plan()

    def _rebuild_plan(self):
        if not self.csv_rows or not self.timeline:
            return
        self.tree.delete(*self.tree.get_children())
        self.plan = []
        renaming = self.rename_var.get()
        if not renaming and not self.marker_var.get():
            self.log_write(self.log, tr("[INFO] Coche « Renommer les clips » et/ou « Ajouter Marker timeline ».\n"), "warn")
            self.btn_apply.config(state="disabled")
            return
        if renaming:
            items = self._track_items()
        else:
            timeline_start = int(self.timeline.GetStartFrame())
        used = {}   # id(item) ou frame du marker -> vfx_id, pour détecter deux lignes au même endroit
        n_ok = n_warn = n_bad = 0

        for n_row, (vfx_id, tc, note) in enumerate(self.csv_rows, 1):
            if n_row % 50 == 0:
                self.trace.step(f"plan : ligne {n_row}/{len(self.csv_rows)}")
            def bad(status):
                nonlocal n_bad
                self.tree.insert("", "end", values=(vfx_id, tc, "-", note, status), tags=("bad",))
                self.log_write(self.log, tr("[IGNORÉ] '{0}' @ {1} — {2}\n", vfx_id, tc, status), "warn")
                n_bad += 1

            if not vfx_id:
                bad(tr("VFX ID vide"))
                continue
            try:
                frame = tc_to_frames(tc, self.fps, self.drop_frame)
            except ValueError as e:
                bad(str(e))
                continue

            if not renaming:
                try:
                    rel = marker_only_frame(frame, timeline_start, used)
                except ValueError as e:
                    bad(str(e))
                    continue
                used[rel] = vfx_id
                self.tree.insert("", "end", values=(vfx_id, tc, "-", note, tr("Prêt (marker)")), tags=("ok",))
                self.plan.append({"item": None, "frame": rel, "vfx_id": vfx_id, "tc": tc,
                                  "old": "", "note": note})
                n_ok += 1
                continue

            matches, mode = match_item(frame, items)
            if mode == "inside" and not self.inside_var.get():
                matches, mode = [], "none"
            if mode == "none":
                bad(tr("Aucun clip à ce TC"))
                continue
            if len(matches) > 1:
                bad(tr("{0} clips à ce TC — choisis une piste précise", len(matches)))
                continue

            item = matches[0]
            if id(item) in used:
                bad(tr("Clip déjà ciblé par '{0}'", used[id(item)]))
                continue
            used[id(item)] = vfx_id

            old = item.GetName() or ""
            if mode == "exact":
                tag, status = "ok", tr("Prêt")
                n_ok += 1
            else:
                tag, status = "warn", tr("Prêt (TC à l'intérieur du clip)")
                n_warn += 1
            self.tree.insert("", "end", values=(vfx_id, tc, old, note, status), tags=(tag,))
            self.plan.append({"item": item, "vfx_id": vfx_id, "tc": tc, "old": old, "note": note})

        summary = (tr("{0} exact(s), {1} à l'intérieur", n_ok, n_warn) if renaming
                   else tr("{0} marker(s) à poser", n_ok))
        self.log_write(self.log, tr("Preview : {0}, {1} ignoré(s).\n", summary, n_bad), "accent")
        self.btn_apply.config(state="normal" if self.plan else "disabled")

    # ---------------------------------------------------------------- Apply
    def on_apply(self):
        if not self.plan:
            return
        renaming = self.rename_var.get()
        with_markers = self.marker_var.get()
        color = self.marker_color_var.get()
        if renaming:
            question = tr("Renommer {0} clip(s) de la timeline avec leur VFX ID ?\n", len(self.plan))
            if with_markers:
                question += (tr("Un marker {0} sera ajouté sur chaque clip (position : {1}).\n",
                                color, self.marker_pos_var.get().lower()))
            question += tr("Les anciens noms seront consignés dans un log.")
        else:
            question = (tr("Ajouter {0} marker(s) {1} à la timeline, au TC du CSV ?\nAucun clip ne sera renommé.",
                           len(self.plan), color))
        if not messagebox.askyesno(tr("Confirmer"), question):
            return

        n_ok = n_fail = n_mk = n_mk_fail = 0
        journal = []
        self.log_write(self.log, tr("\n── Application ──\n"), "accent")
        for p in self.plan:
            item, vfx_id = p["item"], p["vfx_id"]
            status = ""
            if renaming:
                try:
                    item.SetName(vfx_id)
                    confirmed = item.GetName() or ""
                except Exception as e:
                    confirmed = f"<exception : {e}>"
                journal.append(f"{p['tc']}\t'{p['old']}' -> '{vfx_id}'\t{'OK' if confirmed == vfx_id else tr('ECHEC')}")
                if confirmed != vfx_id:
                    n_fail += 1
                    self.log_write(self.log, tr("[ÉCHEC] {0} — lu '{1}', attendu '{2}'\n",
                                                p['tc'], confirmed, vfx_id), "err")
                    self._mark_row(p, "bad", tr("Non appliqué (lu : {0})", confirmed or tr("vide")))
                    continue
                n_ok += 1
                self.log_write(self.log, f"[OK] {p['tc']}  '{p['old']}' → '{vfx_id}'\n", "ok")
                status = tr("Appliqué")
            tag = "ok"
            if with_markers:
                mk_state, mk_detail = self._add_marker(p, color)
                journal.append(f"{p['tc']}\t'{vfx_id}'\tmarker {color}: {mk_state} {mk_detail}")
                if mk_state == "ok":
                    n_mk += 1
                    status = tr("{0} + marker", status) if renaming else tr("Marker posé")
                    if not renaming:
                        self.log_write(self.log, f"[OK] {p['tc']}  marker '{vfx_id}'\n", "ok")
                else:
                    n_mk_fail += 1
                    status = tr("{0} — marker NON posé", status) if renaming else tr("Marker NON posé")
                    tag = "ok" if renaming else "bad"
                    self.log_write(self.log, tr("[ÉCHEC MARKER] '{0}' — {1}\n", vfx_id, mk_detail), "err")
            self._mark_row(p, tag, status)

        try:
            log_path = pm_common.write_log(TOOL_NAME, [tr("Timeline : {0}", self.timeline.GetName())] + journal)
            self.log_write(self.log, tr("\nJournal : {0}\n", log_path), "dim")
        except OSError as e:
            self.log_write(self.log, tr("\n[INFO] Journal non écrit ({0}).\n", e), "dim")
        results = []
        if renaming:
            results.append(tr("{0} clip(s) renommé(s), {1} échec(s)", n_ok, n_fail))
        if with_markers:
            results.append(tr("{0} marker(s) posé(s), {1} échec(s)", n_mk, n_mk_fail))
        self.log_write(self.log, tr("Terminé : {0}.\n", ' · '.join(results)), "accent")
        messagebox.showinfo(tr("Terminé"), "\n".join(results) + tr("\n\nDétails dans le log."))

    def _add_marker(self, p, color):
        """Pose (ou remplace, si c'est un des nôtres) un marker sur le clip (début, milieu ou fin),
        ou directement au frame planifié s'il n'y a pas de clip (p["item"] is None).
        Retourne ("ok"|"fail", détail). Le résultat est relu via GetMarkers()."""
        item, vfx_id, note = p["item"], p["vfx_id"], p["note"]
        try:
            if item is None:
                frame = p["frame"]
            else:
                frame = marker_frame(int(item.GetStart()), int(item.GetEnd()),
                                     int(self.timeline.GetStartFrame()), source(self.marker_pos_var.get(), MARKER_POSITIONS))
            existing = (self.timeline.GetMarkers() or {}).get(frame)
            if existing:
                if existing.get("customData") != MARKER_TAG:
                    return "fail", tr("un autre marker existe déjà au frame {0} (laissé intact)", frame)
                self.timeline.DeleteMarkerAtFrame(frame)       # relance : on remplace le nôtre
            self.timeline.AddMarker(frame, color, vfx_id, note, 1, MARKER_TAG)
            got = (self.timeline.GetMarkers() or {}).get(frame)
        except Exception as e:
            return "fail", tr("exception : {0}", e)
        if got and got.get("name") == vfx_id:
            return "ok", f"frame {frame}"
        found = sorted((self.timeline.GetMarkers() or {}).keys())[:5]
        return "fail", tr("marker non retrouvé au frame {0} (frames présents : {1})", frame, found)

    def _mark_row(self, plan_item, tag, status):
        for iid in self.tree.get_children():
            v = self.tree.item(iid, "values")
            if v[0] == plan_item["vfx_id"] and v[1] == plan_item["tc"]:
                self.tree.item(iid, values=(v[0], v[1], v[2], v[3], status), tags=(tag,))
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
