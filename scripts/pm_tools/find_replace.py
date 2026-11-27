#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Find & Replace — recherche/remplacement de texte, en deux onglets :
  • Métadonnées : colonnes de métadonnées des clips du Media Pool ;
  • Timeline    : noms (clip names) des éléments de la timeline active.
Module interne de la PM Suite (voir PM-Suite.py).

NOTE (onglet Timeline)
──────────────────────
Comme pour csv_to_vfxid, la valeur de retour de SetName() n'est pas jugée
fiable : le nom est relu après écriture. Les anciens noms sont consignés dans
un log horodaté (~/Logs/PM-Suite/) — Resolve n'a pas de Cmd+Z pour un script.
"""

import re
import sys
import os
import tkinter as tk
from tkinter import ttk, messagebox

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pm_common
from pm_common import PMWindow, Theme
from pm_tools.i18n import tr, choices, source

TOOL_NAME = "PM-FindAndReplace"
TOOL_NAME_TIMELINE = "PM-FindAndReplace-Timeline"

PLACEHOLDER_FIND = "Texte ou regex à rechercher…"
PLACEHOLDER_REPLACE = "Texte de remplacement / à ajouter…"

STANDARD_COLUMNS = [
    "Clip Name", "Scene", "Shot", "Take", "Angle", "Camera #", "Camera Type",
    "Good Take", "Description", "Comments", "Keywords", "Clip Color",
    "Reel Name", "Start TC", "End TC", "FPS", "Resolution",
    "Date Modified", "Date Created", "File Name", "File Path",
    "Codec", "Duration", "Frames", "Audio Ch",
]


def get_clips(media_pool, selected_only: bool):
    """Récupère les clips sélectionnés ou tous les clips du bin courant."""
    if selected_only:
        clips = media_pool.GetSelectedClips()
        if not clips:
            raise RuntimeError(
                tr("Aucun clip sélectionné dans la bin.\n"
                   "Sélectionne au moins un clip ou déselectionne l'option 'Clips sélectionnés "
                   "seulement'.")
            )
    else:
        folder = media_pool.GetCurrentFolder()
        clips = folder.GetClipList()
        if not clips:
            raise RuntimeError(tr("Aucun clip dans le bin courant."))
    return clips


# ── Lecture / écriture tolérante aux colonnes custom ───────────────────────────
# SetClipProperty ne fonctionne que pour l'ensemble fixe de propriétés connues
# de Resolve (les "Clip Attributes"). Pour une colonne CUSTOM créée dans
# l'éditeur de métadonnées, il faut passer par SetMetadata — sinon l'appel
# retourne False silencieusement (pas d'exception) et rien n'est écrit.
def _get_clip_value(clip, column):
    val = None
    try:
        val = clip.GetClipProperty(column)
    except Exception:
        val = None
    if not val:
        try:
            meta_val = clip.GetMetadata(column)
        except Exception:
            meta_val = None
        if meta_val:
            val = meta_val
    return val or ""


def _confirmed(clip, column, value):
    """Relit la valeur après écriture : le retour des Set*() n'est pas fiable
    (ex. SetClipProperty("Clip Name") renvoie False alors que le nom change)."""
    return _get_clip_value(clip, column) == value


def _set_clip_value(clip, column, value):
    try:
        ok = clip.SetClipProperty(column, value)
    except Exception:
        ok = False
    if ok or _confirmed(clip, column, value):
        return True, "ClipProperty"
    try:
        ok = clip.SetMetadata(column, value)
    except Exception:
        ok = False
    if ok or _confirmed(clip, column, value):
        return True, "Metadata"
    return False, tr("aucune méthode n'a fonctionné")


def compute_new_value(current_value, find_text, replace_text, use_regex,
                      case_sensitive, mode="replace"):
    """
    Logique de remplacement pure (sans Resolve).
    mode : 'replace' | 'append' | 'prepend'
    Retourne la nouvelle valeur, ou None si le clip est ignoré (pas de match).
    Lève ValueError si la regex est invalide.
    """
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        if mode in ("append", "prepend"):
            if find_text:
                pattern = find_text if use_regex else re.escape(find_text)
                if not re.search(pattern, current_value, flags=flags):
                    return None
            if mode == "append":
                return current_value + replace_text
            return replace_text + current_value
        # replace
        if not current_value:
            return None
        if use_regex:
            return re.sub(find_text, replace_text, current_value, flags=flags)
        if case_sensitive:
            return current_value.replace(find_text, replace_text)
        return re.sub(re.escape(find_text), lambda _m: replace_text,
                      current_value, flags=re.IGNORECASE)
    except re.error as e:
        raise ValueError(tr("Erreur regex : {0}", e))


def run_find_replace(column, find_text, replace_text, use_regex, case_sensitive,
                     selected_only, mode="replace", dry_run=False):
    """
    mode   : 'replace' | 'append' | 'prepend'
    status : 'preview' (dry run), 'ClipProperty', 'Metadata', ou 'FAILED'
    Retourne une liste de tuples (clip_name, old_value, new_value, status).
    """
    _, _, media_pool = pm_common.get_resolve_objects()
    clips = get_clips(media_pool, selected_only)
    results = []

    for clip in clips:
        current_value = _get_clip_value(clip, column)
        new_value = compute_new_value(current_value, find_text, replace_text,
                                      use_regex, case_sensitive, mode)
        if new_value is None or new_value == current_value:
            continue
        if dry_run:
            results.append((clip.GetName(), current_value, new_value, "preview"))
        else:
            success, method = _set_clip_value(clip, column, new_value)
            status = method if success else "FAILED"
            results.append((clip.GetName(), current_value, new_value, status))

    return results


# ── Onglet Timeline : noms des éléments de la timeline active ──────────────────
TRACK_ALL, TRACK_VIDEO, TRACK_AUDIO = "Toutes les pistes", "Vidéo (toutes)", "Audio (toutes)"


def list_track_choices(timeline):
    """Valeurs du sélecteur de pistes : filtres globaux puis V1…Vn, A1…An."""
    values = [TRACK_ALL, TRACK_VIDEO, TRACK_AUDIO]
    for kind, letter in (("video", "V"), ("audio", "A")):
        n = int(timeline.GetTrackCount(kind) or 0)
        values += [f"{letter}{i}" for i in range(1, n + 1)]
    return values


def _tracks_for_choice(timeline, choice):
    """Retourne [(kind, index, label), ...] pour la sélection du combobox."""
    out = []
    for kind, letter in (("video", "V"), ("audio", "A")):
        n = int(timeline.GetTrackCount(kind) or 0)
        for i in range(1, n + 1):
            label = f"{letter}{i}"
            wanted = (choice == TRACK_ALL
                      or (choice == TRACK_VIDEO and kind == "video")
                      or (choice == TRACK_AUDIO and kind == "audio")
                      or choice == label)
            if wanted:
                out.append((kind, i, label))
    return out


def run_timeline_find_replace(find_text, replace_text, use_regex, case_sensitive,
                              track_choice, mode="replace", dry_run=False):
    """
    Renomme les éléments de la timeline active.
    status : 'preview', 'OK' ou 'FAILED'
    Retourne (timeline_name, [(track_label, old_name, new_name, status), ...]).
    """
    _, project, _ = pm_common.get_resolve_objects()
    timeline = project.GetCurrentTimeline()
    if not timeline:
        raise RuntimeError(tr("Aucune timeline active."))

    results = []
    for kind, idx, label in _tracks_for_choice(timeline, track_choice):
        for item in (timeline.GetItemListInTrack(kind, idx) or []):
            old = item.GetName() or ""
            new = compute_new_value(old, find_text, replace_text, use_regex,
                                    case_sensitive, mode)
            if new is None or new == old:
                continue
            if dry_run:
                results.append((label, old, new, "preview"))
                continue
            try:
                item.SetName(new)
                confirmed = item.GetName() or ""
            except Exception:
                confirmed = None
            results.append((label, old, new, "OK" if confirmed == new else "FAILED"))
    return timeline.GetName(), results


class _TabBase(tk.Frame):
    """Formulaire commun aux deux onglets : recherche, texte, mode, options, log."""

    SCOPE_TEXT = ""

    def __init__(self, notebook, win):
        super().__init__(notebook, bg=Theme.DARK_BG, padx=4, pady=8)
        self.win = win
        self._build_target(self)

        win.section(self, tr("RECHERCHE  (vide = tous les clips)"))
        self.find_var = tk.StringVar()
        self.find_placeholder = tr(PLACEHOLDER_FIND)
        win.entry(self, self.find_var, self.find_placeholder)

        win.section(self, tr("TEXTE"))
        self.replace_var = tk.StringVar()
        self.replace_placeholder = tr(PLACEHOLDER_REPLACE)
        win.entry(self, self.replace_var, self.replace_placeholder)

        win.section(self, "MODE")
        mode_row = tk.Frame(self, bg=Theme.DARK_BG)
        mode_row.pack(fill="x", pady=(4, 12))
        self.mode_var = tk.StringVar(value="replace")
        for val, label in [("replace", tr("Remplacer")), ("append", tr("Ajouter à la fin")), ("prepend", tr("Ajouter au début"))]:
            tk.Radiobutton(mode_row, text=label, variable=self.mode_var, value=val,
                           bg=Theme.DARK_BG, fg=Theme.FG, activebackground=Theme.DARK_BG,
                           activeforeground=Theme.FG, selectcolor=Theme.PANEL_BG,
                           font=Theme.FONT_SM, bd=0).pack(side="left", padx=(0, 16))

        win.section(self, "OPTIONS")
        opt = tk.Frame(self, bg=Theme.DARK_BG)
        opt.pack(fill="x", pady=(4, 12))
        self.regex_var = tk.BooleanVar(value=False)
        self.case_var = tk.BooleanVar(value=False)
        win.checkbox(opt, tr("Regex (mode avancé)"), self.regex_var, row=0, col=0)
        win.checkbox(opt, tr("Respecter la casse"), self.case_var, row=0, col=1)
        self._build_options(opt)

        btn_row = tk.Frame(self, bg=Theme.DARK_BG)
        btn_row.pack(fill="x", pady=(4, 0))
        win.button(btn_row, tr("PRÉVISUALISER"), Theme.ACCENT, self._preview, side="left")
        win.button(btn_row, tr("APPLIQUER"), Theme.SUCCESS, self._apply, side="left", padx_l=10)
        win.button(btn_row, tr("EFFACER LOG"), Theme.FG_DIM, self._clear, side="right")

        self.log = win.build_log(self, height=12)
        win.log_write(self.log, tr("Prêt. Configure les paramètres puis clique sur Prévisualiser.\n"), "dim")

    # -- à surcharger ---------------------------------------------------------
    def _build_target(self, parent): ...
    def _build_options(self, opt): ...
    def _run(self, dry_run): ...
    def on_show(self): ...

    # -- commun ---------------------------------------------------------------
    def _clear(self):
        self.win.log_clear(self.log)
        self.win.log_write(self.log, tr("Log effacé.\n"), "dim")

    def _validate(self):
        """Retourne (find, replace) ou None si invalide."""
        find = self.find_var.get().strip()
        if find == self.find_placeholder:
            find = ""
        if self.mode_var.get() == "replace" and not find:
            messagebox.showerror(tr("Erreur"), tr("Le champ Recherche est vide."))
            return None
        replace = self.replace_var.get().strip()
        if replace == self.replace_placeholder:
            replace = ""
        return find, replace

    def _log_params(self, dry_run, target, find, replace):
        w, log = self.win, self.log
        w.log_write(log, f"\n{'─'*56}\n", "dim")
        w.log_write(log, f"[{'DRY RUN' if dry_run else 'APPLY'}]  ", "accent")
        w.log_write(log, f"{target}\n", "dim")
        mode_label = {"replace": tr("remplacer"), "append": tr("ajouter à la fin"),
                      "prepend": tr("ajouter au début")}.get(self.mode_var.get(), "?")
        w.log_write(log, "  mode    : ", "dim"); w.log_write(log, f"{mode_label}\n", "accent")
        w.log_write(log, "  find    : ", "dim"); w.log_write(log, f"{find!r}\n", "warn")
        w.log_write(log, tr("  texte   : "), "dim"); w.log_write(log, f"{replace!r}\n", "ok")
        if self.regex_var.get():
            w.log_write(log, tr("  regex   : activé\n"), "dim")
        if self.case_var.get():
            w.log_write(log, tr("  casse   : sensible\n"), "dim")
        w.log_write(log, f"{'─'*56}\n", "dim")

    def _preview(self):
        self._run(dry_run=True)

    def _apply(self):
        if messagebox.askyesno(tr("Confirmer"), tr(self.CONFIRM_TEXT)):
            self._run(dry_run=False)


class MetadataTab(_TabBase):
    CONFIRM_TEXT = "Appliquer les modifications aux métadonnées ?"

    def _build_target(self, parent):
        self.win.section(parent, tr("COLONNE CIBLE"))
        col_row = tk.Frame(parent, bg=Theme.DARK_BG)
        col_row.pack(fill="x", pady=(4, 12))
        self.col_var = tk.StringVar(value="Scene")
        ttk.Combobox(col_row, textvariable=self.col_var, values=STANDARD_COLUMNS,
                     state="normal", width=28, font=Theme.FONT_UI).pack(side="left")
        tk.Label(col_row, text=tr("(ou tape un nom custom)"), font=Theme.FONT_SM,
                 bg=Theme.DARK_BG, fg=Theme.FG_DIM).pack(side="left", padx=(10, 0))

    def _build_options(self, opt):
        self.scope_var = tk.BooleanVar(value=True)
        self.win.checkbox(opt, tr("Clips sélectionnés seulement"), self.scope_var, row=1, col=0)

    def _run(self, dry_run):
        column = self.col_var.get().strip()
        if not column:
            messagebox.showerror(tr("Erreur"), tr("Spécifie une colonne."))
            return
        params = self._validate()
        if params is None:
            return
        find, replace = params
        w, log = self.win, self.log

        scope = tr("clips sélectionnés") if self.scope_var.get() else tr("bin entier")
        self._log_params(dry_run, tr("colonne={0}  scope={1}", column, scope), find, replace)

        try:
            results = run_find_replace(
                column=column, find_text=find, replace_text=replace,
                use_regex=self.regex_var.get(), case_sensitive=self.case_var.get(),
                selected_only=self.scope_var.get(), mode=self.mode_var.get(), dry_run=dry_run,
            )
        except Exception as e:
            w.log_write(log, tr("ERREUR : {0}\n", e), "err")
            pm_common.write_error_log(TOOL_NAME, e)
            return

        if not results:
            w.log_write(log, tr("Aucune correspondance trouvée.\n"), "dim")
            return

        n_ok = n_failed = 0
        for clip_name, old_val, new_val, status in results:
            w.log_write(log, f"  {clip_name}", "header")
            if status == "FAILED":
                w.log_write(log, tr("  [ÉCHEC]\n"), "err")
                n_failed += 1
            elif status != "preview":
                w.log_write(log, f"  [via {status}]\n", "dim")
                n_ok += 1
            else:
                w.log_write(log, "\n", "")
                n_ok += 1
            w.log_write(log, f"    {old_val!r:30s}", "warn")
            w.log_write(log, " → ", "dim")
            w.log_write(log, f"{new_val!r}\n", "ok")

        if dry_run:
            w.log_write(log, tr("\n{0} clip(s) seraient modifiés. Clique sur APPLIQUER pour confirmer.\n",
                                n_ok), "accent")
        else:
            if n_ok:
                w.log_write(log, tr("\n✓ {0} clip(s) modifié(s) avec succès.\n", n_ok), "ok")
            if n_failed:
                w.log_write(log,
                    tr("✗ {0} clip(s) n'ont pas pu être modifiés — « {1} » n'est probablement pas un nom de "
                       "colonne/métadonnée valide dans ce projet.\n", n_failed, column),
                    "err")


class TimelineTab(_TabBase):
    CONFIRM_TEXT = ("Renommer les éléments de la timeline active ?\n"
                    "Les anciens noms seront consignés dans un log.")

    def _build_target(self, parent):
        self.win.section(parent, tr("PISTES CIBLES  (timeline active)"))
        row = tk.Frame(parent, bg=Theme.DARK_BG)
        row.pack(fill="x", pady=(4, 12))
        self.track_var = tk.StringVar(value=tr(TRACK_ALL))
        self.cmb_track = ttk.Combobox(row, textvariable=self.track_var, values=[tr(TRACK_ALL)],
                                       state="readonly", width=28, font=Theme.FONT_UI)
        self.cmb_track.pack(side="left")
        tk.Label(row, text=tr("Cible : noms des clips posés sur la timeline"),
                 font=Theme.FONT_SM, bg=Theme.DARK_BG, fg=Theme.FG_DIM
                 ).pack(side="left", padx=(10, 0))

    def on_show(self):
        """Rafraîchit la liste des pistes (la timeline a pu changer)."""
        try:
            _, project, _ = pm_common.get_resolve_objects()
            timeline = project.GetCurrentTimeline()
            if not timeline:
                return
            labels = choices(list_track_choices(timeline))
        except Exception:
            return
        self.cmb_track.config(values=labels)
        if self.track_var.get() not in labels:
            self.track_var.set(tr(TRACK_ALL))

    def _run(self, dry_run):
        params = self._validate()
        if params is None:
            return
        find, replace = params
        w, log = self.win, self.log

        self._log_params(dry_run, tr("timeline  pistes={0}", self.track_var.get()), find, replace)

        try:
            tl_name, results = run_timeline_find_replace(
                find_text=find, replace_text=replace,
                use_regex=self.regex_var.get(), case_sensitive=self.case_var.get(),
                track_choice=source(self.track_var.get(),
                                                  (TRACK_ALL, TRACK_VIDEO, TRACK_AUDIO)), mode=self.mode_var.get(), dry_run=dry_run,
            )
        except Exception as e:
            w.log_write(log, tr("ERREUR : {0}\n", e), "err")
            pm_common.write_error_log(TOOL_NAME_TIMELINE, e)
            return

        w.log_write(log, tr("Timeline : {0}\n", tl_name), "dim")
        if not results:
            w.log_write(log, tr("Aucune correspondance trouvée.\n"), "dim")
            return

        n_ok = n_failed = 0
        journal = []
        for track, old, new, status in results:
            w.log_write(log, f"  [{track}] ", "header")
            if status == "FAILED":
                w.log_write(log, tr("[ÉCHEC]  "), "err")
                n_failed += 1
            else:
                n_ok += 1
            w.log_write(log, f"{old!r}", "warn")
            w.log_write(log, " → ", "dim")
            w.log_write(log, f"{new!r}\n", "ok")
            journal.append(f"[{track}]\t'{old}' -> '{new}'\t{status}")

        if dry_run:
            w.log_write(log, tr("\n{0} clip(s) seraient renommés. Clique sur APPLIQUER pour confirmer.\n",
                                n_ok), "accent")
            return
        if n_ok:
            w.log_write(log, tr("\n✓ {0} clip(s) renommé(s).\n", n_ok), "ok")
        if n_failed:
            w.log_write(log, tr("✗ {0} clip(s) non renommés (nom relu différent du nom attendu).\n", n_failed), "err")
        try:
            path = pm_common.write_log(TOOL_NAME_TIMELINE, [tr("Timeline : {0}", tl_name)] + journal)
            w.log_write(log, tr("Journal : {0}\n", path), "dim")
        except OSError as e:
            w.log_write(log, tr("[INFO] Journal non écrit ({0}).\n", e), "dim")


class FindReplaceWindow(PMWindow):
    def __init__(self, master):
        super().__init__(master, "Find & Replace",
                          f"DaVinci Resolve  ·  {pm_common.RESOLVE_VARIANT}")

    def _build_content(self, main):
        nb = ttk.Notebook(main)
        nb.pack(fill="both", expand=True)
        self.tabs = [MetadataTab(nb, self), TimelineTab(nb, self)]
        nb.add(self.tabs[0], text=tr("Métadonnées (Media Pool)"))
        nb.add(self.tabs[1], text=tr("Noms de clips (Timeline)"))
        nb.bind("<<NotebookTabChanged>>",
                lambda _e: self.tabs[nb.index("current")].on_show())


def open_window(master):
    return FindReplaceWindow(master)
