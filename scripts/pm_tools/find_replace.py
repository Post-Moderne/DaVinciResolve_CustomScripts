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
                "Aucun clip sélectionné dans la bin.\n"
                "Sélectionne au moins un clip ou déselectionne l'option 'Clips sélectionnés seulement'."
            )
    else:
        folder = media_pool.GetCurrentFolder()
        clips = folder.GetClipList()
        if not clips:
            raise RuntimeError("Aucun clip dans le bin courant.")
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


def _set_clip_value(clip, column, value):
    try:
        ok = clip.SetClipProperty(column, value)
    except Exception:
        ok = False
    if ok:
        return True, "ClipProperty"
    try:
        ok = clip.SetMetadata(column, value)
    except Exception:
        ok = False
    if ok:
        return True, "Metadata"
    return False, "aucune méthode n'a fonctionné"


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
        raise ValueError(f"Erreur regex : {e}")


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
    choices = [TRACK_ALL, TRACK_VIDEO, TRACK_AUDIO]
    for kind, letter in (("video", "V"), ("audio", "A")):
        n = int(timeline.GetTrackCount(kind) or 0)
        choices += [f"{letter}{i}" for i in range(1, n + 1)]
    return choices


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
        raise RuntimeError("Aucune timeline active.")

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

        win.section(self, "RECHERCHE  (vide = tous les clips)")
        self.find_var = tk.StringVar()
        win.entry(self, self.find_var, PLACEHOLDER_FIND)

        win.section(self, "TEXTE")
        self.replace_var = tk.StringVar()
        win.entry(self, self.replace_var, PLACEHOLDER_REPLACE)

        win.section(self, "MODE")
        mode_row = tk.Frame(self, bg=Theme.DARK_BG)
        mode_row.pack(fill="x", pady=(4, 12))
        self.mode_var = tk.StringVar(value="replace")
        for val, label in [("replace", "Remplacer"), ("append", "Ajouter à la fin"), ("prepend", "Ajouter au début")]:
            tk.Radiobutton(mode_row, text=label, variable=self.mode_var, value=val,
                           bg=Theme.DARK_BG, fg=Theme.FG, activebackground=Theme.DARK_BG,
                           activeforeground=Theme.FG, selectcolor=Theme.PANEL_BG,
                           font=Theme.FONT_SM, bd=0).pack(side="left", padx=(0, 16))

        win.section(self, "OPTIONS")
        opt = tk.Frame(self, bg=Theme.DARK_BG)
        opt.pack(fill="x", pady=(4, 12))
        self.regex_var = tk.BooleanVar(value=False)
        self.case_var = tk.BooleanVar(value=False)
        win.checkbox(opt, "Regex (mode avancé)", self.regex_var, row=0, col=0)
        win.checkbox(opt, "Respecter la casse", self.case_var, row=0, col=1)
        self._build_options(opt)

        btn_row = tk.Frame(self, bg=Theme.DARK_BG)
        btn_row.pack(fill="x", pady=(4, 0))
        win.button(btn_row, "PRÉVISUALISER", Theme.ACCENT, self._preview, side="left")
        win.button(btn_row, "APPLIQUER", Theme.SUCCESS, self._apply, side="left", padx_l=10)
        win.button(btn_row, "EFFACER LOG", Theme.FG_DIM, self._clear, side="right")

        self.log = win.build_log(self, height=12)
        win.log_write(self.log, "Prêt. Configure les paramètres puis clique sur Prévisualiser.\n", "dim")

    # -- à surcharger ---------------------------------------------------------
    def _build_target(self, parent): ...
    def _build_options(self, opt): ...
    def _run(self, dry_run): ...
    def on_show(self): ...

    # -- commun ---------------------------------------------------------------
    def _clear(self):
        self.win.log_clear(self.log)
        self.win.log_write(self.log, "Log effacé.\n", "dim")

    def _validate(self):
        """Retourne (find, replace) ou None si invalide."""
        find = self.find_var.get().strip()
        if find == PLACEHOLDER_FIND:
            find = ""
        if self.mode_var.get() == "replace" and not find:
            messagebox.showerror("Erreur", "Le champ Recherche est vide.")
            return None
        replace = self.replace_var.get().strip()
        if replace == PLACEHOLDER_REPLACE:
            replace = ""
        return find, replace

    def _log_params(self, dry_run, target, find, replace):
        w, log = self.win, self.log
        w.log_write(log, f"\n{'─'*56}\n", "dim")
        w.log_write(log, f"[{'DRY RUN' if dry_run else 'APPLY'}]  ", "accent")
        w.log_write(log, f"{target}\n", "dim")
        mode_label = {"replace": "remplacer", "append": "ajouter à la fin",
                      "prepend": "ajouter au début"}.get(self.mode_var.get(), "?")
        w.log_write(log, "  mode    : ", "dim"); w.log_write(log, f"{mode_label}\n", "accent")
        w.log_write(log, "  find    : ", "dim"); w.log_write(log, f"{find!r}\n", "warn")
        w.log_write(log, "  texte   : ", "dim"); w.log_write(log, f"{replace!r}\n", "ok")
        if self.regex_var.get():
            w.log_write(log, "  regex   : activé\n", "dim")
        if self.case_var.get():
            w.log_write(log, "  casse   : sensible\n", "dim")
        w.log_write(log, f"{'─'*56}\n", "dim")

    def _preview(self):
        self._run(dry_run=True)

    def _apply(self):
        if messagebox.askyesno("Confirmer", self.CONFIRM_TEXT):
            self._run(dry_run=False)


class MetadataTab(_TabBase):
    CONFIRM_TEXT = "Appliquer les modifications aux métadonnées ?"

    def _build_target(self, parent):
        self.win.section(parent, "COLONNE CIBLE")
        col_row = tk.Frame(parent, bg=Theme.DARK_BG)
        col_row.pack(fill="x", pady=(4, 12))
        self.col_var = tk.StringVar(value="Scene")
        ttk.Combobox(col_row, textvariable=self.col_var, values=STANDARD_COLUMNS,
                     state="normal", width=28, font=Theme.FONT_UI).pack(side="left")
        tk.Label(col_row, text="(ou tape un nom custom)", font=Theme.FONT_SM,
                 bg=Theme.DARK_BG, fg=Theme.FG_DIM).pack(side="left", padx=(10, 0))

    def _build_options(self, opt):
        self.scope_var = tk.BooleanVar(value=True)
        self.win.checkbox(opt, "Clips sélectionnés seulement", self.scope_var, row=1, col=0)

    def _run(self, dry_run):
        column = self.col_var.get().strip()
        if not column:
            messagebox.showerror("Erreur", "Spécifie une colonne.")
            return
        params = self._validate()
        if params is None:
            return
        find, replace = params
        w, log = self.win, self.log

        scope = "clips sélectionnés" if self.scope_var.get() else "bin entier"
        self._log_params(dry_run, f"colonne={column}  scope={scope}", find, replace)

        try:
            results = run_find_replace(
                column=column, find_text=find, replace_text=replace,
                use_regex=self.regex_var.get(), case_sensitive=self.case_var.get(),
                selected_only=self.scope_var.get(), mode=self.mode_var.get(), dry_run=dry_run,
            )
        except Exception as e:
            w.log_write(log, f"ERREUR : {e}\n", "err")
            pm_common.write_error_log(TOOL_NAME, e)
            return

        if not results:
            w.log_write(log, "Aucune correspondance trouvée.\n", "dim")
            return

        n_ok = n_failed = 0
        for clip_name, old_val, new_val, status in results:
            w.log_write(log, f"  {clip_name}", "header")
            if status == "FAILED":
                w.log_write(log, "  [ÉCHEC]\n", "err")
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
            w.log_write(log, f"\n{n_ok} clip(s) seraient modifiés. Clique sur APPLIQUER pour confirmer.\n", "accent")
        else:
            if n_ok:
                w.log_write(log, f"\n✓ {n_ok} clip(s) modifié(s) avec succès.\n", "ok")
            if n_failed:
                w.log_write(log,
                    f"✗ {n_failed} clip(s) n'ont pas pu être modifiés — "
                    f"« {column} » n'est probablement pas un nom de colonne/métadonnée valide dans ce projet.\n",
                    "err")


class TimelineTab(_TabBase):
    CONFIRM_TEXT = ("Renommer les éléments de la timeline active ?\n"
                    "Les anciens noms seront consignés dans un log.")

    def _build_target(self, parent):
        self.win.section(parent, "PISTES CIBLES  (timeline active)")
        row = tk.Frame(parent, bg=Theme.DARK_BG)
        row.pack(fill="x", pady=(4, 12))
        self.track_var = tk.StringVar(value=TRACK_ALL)
        self.cmb_track = ttk.Combobox(row, textvariable=self.track_var, values=[TRACK_ALL],
                                       state="readonly", width=28, font=Theme.FONT_UI)
        self.cmb_track.pack(side="left")
        tk.Label(row, text="Cible : noms des clips posés sur la timeline",
                 font=Theme.FONT_SM, bg=Theme.DARK_BG, fg=Theme.FG_DIM
                 ).pack(side="left", padx=(10, 0))

    def on_show(self):
        """Rafraîchit la liste des pistes (la timeline a pu changer)."""
        try:
            _, project, _ = pm_common.get_resolve_objects()
            timeline = project.GetCurrentTimeline()
            if not timeline:
                return
            choices = list_track_choices(timeline)
        except Exception:
            return
        self.cmb_track.config(values=choices)
        if self.track_var.get() not in choices:
            self.track_var.set(TRACK_ALL)

    def _run(self, dry_run):
        params = self._validate()
        if params is None:
            return
        find, replace = params
        w, log = self.win, self.log

        self._log_params(dry_run, f"timeline  pistes={self.track_var.get()}", find, replace)

        try:
            tl_name, results = run_timeline_find_replace(
                find_text=find, replace_text=replace,
                use_regex=self.regex_var.get(), case_sensitive=self.case_var.get(),
                track_choice=self.track_var.get(), mode=self.mode_var.get(), dry_run=dry_run,
            )
        except Exception as e:
            w.log_write(log, f"ERREUR : {e}\n", "err")
            pm_common.write_error_log(TOOL_NAME_TIMELINE, e)
            return

        w.log_write(log, f"Timeline : {tl_name}\n", "dim")
        if not results:
            w.log_write(log, "Aucune correspondance trouvée.\n", "dim")
            return

        n_ok = n_failed = 0
        journal = []
        for track, old, new, status in results:
            w.log_write(log, f"  [{track}] ", "header")
            if status == "FAILED":
                w.log_write(log, "[ÉCHEC]  ", "err")
                n_failed += 1
            else:
                n_ok += 1
            w.log_write(log, f"{old!r}", "warn")
            w.log_write(log, " → ", "dim")
            w.log_write(log, f"{new!r}\n", "ok")
            journal.append(f"[{track}]\t'{old}' -> '{new}'\t{status}")

        if dry_run:
            w.log_write(log, f"\n{n_ok} clip(s) seraient renommés. Clique sur APPLIQUER pour confirmer.\n", "accent")
            return
        if n_ok:
            w.log_write(log, f"\n✓ {n_ok} clip(s) renommé(s).\n", "ok")
        if n_failed:
            w.log_write(log, f"✗ {n_failed} clip(s) non renommés (nom relu différent du nom attendu).\n", "err")
        try:
            path = pm_common.write_log(TOOL_NAME_TIMELINE, [f"Timeline : {tl_name}"] + journal)
            w.log_write(log, f"Journal : {path}\n", "dim")
        except OSError as e:
            w.log_write(log, f"[INFO] Journal non écrit ({e}).\n", "dim")


class FindReplaceWindow(PMWindow):
    def __init__(self, master):
        super().__init__(master, "Find & Replace",
                          f"DaVinci Resolve  ·  {pm_common.RESOLVE_VARIANT}")

    def _build_content(self, main):
        nb = ttk.Notebook(main)
        nb.pack(fill="both", expand=True)
        self.tabs = [MetadataTab(nb, self), TimelineTab(nb, self)]
        nb.add(self.tabs[0], text="Métadonnées (Media Pool)")
        nb.add(self.tabs[1], text="Noms de clips (Timeline)")
        nb.bind("<<NotebookTabChanged>>",
                lambda _e: self.tabs[nb.index("current")].on_show())


def open_window(master):
    return FindReplaceWindow(master)
