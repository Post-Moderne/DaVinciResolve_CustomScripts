#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Find & Replace — recherche/remplacement dans les métadonnées des clips
du Media Pool. Module interne de la PM Suite (voir PM-Suite.py).
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


def run_find_replace(column, find_text, replace_text, use_regex, case_sensitive,
                     selected_only, mode="replace", dry_run=False):
    """
    mode   : 'replace' | 'append' | 'prepend'
    status : 'preview' (dry run), 'ClipProperty', 'Metadata', ou 'FAILED'
    Retourne une liste de tuples (clip_name, old_value, new_value, status).
    """
    _, _, media_pool = pm_common.get_resolve_objects()
    clips = get_clips(media_pool, selected_only)

    flags = 0 if case_sensitive else re.IGNORECASE
    results = []

    for clip in clips:
        current_value = _get_clip_value(clip, column)

        try:
            if mode == "append":
                if find_text:
                    pattern = find_text if use_regex else re.escape(find_text)
                    if not re.search(pattern, current_value, flags=flags):
                        continue
                new_value = current_value + replace_text
            elif mode == "prepend":
                if find_text:
                    pattern = find_text if use_regex else re.escape(find_text)
                    if not re.search(pattern, current_value, flags=flags):
                        continue
                new_value = replace_text + current_value
            else:  # replace
                if not current_value:
                    continue
                if use_regex:
                    new_value = re.sub(find_text, replace_text, current_value, flags=flags)
                else:
                    if case_sensitive:
                        new_value = current_value.replace(find_text, replace_text)
                    else:
                        pattern = re.escape(find_text)
                        new_value = re.sub(pattern, replace_text, current_value, flags=re.IGNORECASE)
        except re.error as e:
            raise ValueError(f"Erreur regex : {e}")

        if new_value != current_value:
            if dry_run:
                results.append((clip.GetName(), current_value, new_value, "preview"))
            else:
                success, method = _set_clip_value(clip, column, new_value)
                status = method if success else "FAILED"
                results.append((clip.GetName(), current_value, new_value, status))

    return results


class FindReplaceWindow(PMWindow):
    def __init__(self, master):
        super().__init__(master, "Metadata Find & Replace",
                          f"DaVinci Resolve  ·  {pm_common.RESOLVE_VARIANT}")

    def _build_content(self, main):
        self.section(main, "COLONNE CIBLE")
        col_row = tk.Frame(main, bg=Theme.DARK_BG)
        col_row.pack(fill="x", pady=(4, 12))
        self.col_var = tk.StringVar(value="Scene")
        self.col_combo = ttk.Combobox(col_row, textvariable=self.col_var,
                                       values=STANDARD_COLUMNS, state="normal",
                                       width=28, font=Theme.FONT_UI)
        self.col_combo.pack(side="left")
        tk.Label(col_row, text="(ou tape un nom custom)", font=Theme.FONT_SM,
                 bg=Theme.DARK_BG, fg=Theme.FG_DIM).pack(side="left", padx=(10, 0))

        self.section(main, "RECHERCHE  (vide = tous les clips)")
        self.find_var = tk.StringVar()
        self.entry(main, self.find_var, "Texte ou regex à rechercher…")

        self.section(main, "TEXTE")
        self.replace_var = tk.StringVar()
        self.entry(main, self.replace_var, "Texte de remplacement / à ajouter…")

        self.section(main, "MODE")
        mode_row = tk.Frame(main, bg=Theme.DARK_BG)
        mode_row.pack(fill="x", pady=(4, 12))
        self.mode_var = tk.StringVar(value="replace")
        for val, label in [("replace", "Remplacer"), ("append", "Ajouter à la fin"), ("prepend", "Ajouter au début")]:
            tk.Radiobutton(mode_row, text=label, variable=self.mode_var, value=val,
                           bg=Theme.DARK_BG, fg=Theme.FG, activebackground=Theme.DARK_BG,
                           activeforeground=Theme.FG, selectcolor=Theme.PANEL_BG,
                           font=Theme.FONT_SM, bd=0).pack(side="left", padx=(0, 16))

        self.section(main, "OPTIONS")
        opt = tk.Frame(main, bg=Theme.DARK_BG)
        opt.pack(fill="x", pady=(4, 12))
        self.regex_var = tk.BooleanVar(value=False)
        self.case_var = tk.BooleanVar(value=False)
        self.scope_var = tk.BooleanVar(value=True)
        self.checkbox(opt, "Regex (mode avancé)", self.regex_var, row=0, col=0)
        self.checkbox(opt, "Respecter la casse", self.case_var, row=0, col=1)
        self.checkbox(opt, "Clips sélectionnés seulement", self.scope_var, row=1, col=0)

        btn_row = tk.Frame(main, bg=Theme.DARK_BG)
        btn_row.pack(fill="x", pady=(4, 0))
        self.button(btn_row, "PRÉVISUALISER", Theme.ACCENT, self._preview, side="left")
        self.button(btn_row, "APPLIQUER", Theme.SUCCESS, self._apply, side="left", padx_l=10)
        self.button(btn_row, "EFFACER LOG", Theme.FG_DIM, self._clear, side="right")

        self.log = self.build_log(main)
        self.log_write(self.log, "Prêt. Configure les paramètres puis clique sur Prévisualiser.\n", "dim")

    def _clear(self):
        self.log_clear(self.log)
        self.log_write(self.log, "Log effacé.\n", "dim")

    def _validate(self):
        placeholders = {"Texte ou regex à rechercher…", "Texte de remplacement / à ajouter…"}
        column = self.col_var.get().strip()
        find = self.find_var.get().strip()
        if find in placeholders:
            find = ""
        mode = self.mode_var.get()

        if not column:
            messagebox.showerror("Erreur", "Spécifie une colonne.")
            return None, None, None
        if mode == "replace" and not find:
            messagebox.showerror("Erreur", "Le champ Recherche est vide.")
            return None, None, None

        replace = self.replace_var.get().strip()
        if replace in placeholders:
            replace = ""
        return column, find, replace

    def _run(self, dry_run):
        result = self._validate()
        if result[0] is None:
            return
        column, find, replace = result

        scope = "clips sélectionnés" if self.scope_var.get() else "bin entier"
        mode = "DRY RUN" if dry_run else "APPLY"

        self.log_write(self.log, f"\n{'─'*56}\n", "dim")
        self.log_write(self.log, f"[{mode}]  ", "accent")
        self.log_write(self.log, f"colonne={column}  scope={scope}\n", "dim")
        mode_label = {"replace": "remplacer", "append": "ajouter à la fin", "prepend": "ajouter au début"}.get(self.mode_var.get(), "?")
        self.log_write(self.log, "  mode    : ", "dim"); self.log_write(self.log, f"{mode_label}\n", "accent")
        self.log_write(self.log, "  find    : ", "dim"); self.log_write(self.log, f"{find!r}\n", "warn")
        self.log_write(self.log, "  texte   : ", "dim"); self.log_write(self.log, f"{replace!r}\n", "ok")
        if self.regex_var.get():
            self.log_write(self.log, "  regex   : activé\n", "dim")
        if self.case_var.get():
            self.log_write(self.log, "  casse   : sensible\n", "dim")
        self.log_write(self.log, f"{'─'*56}\n", "dim")

        try:
            results = run_find_replace(
                column=column, find_text=find, replace_text=replace,
                use_regex=self.regex_var.get(), case_sensitive=self.case_var.get(),
                selected_only=self.scope_var.get(), mode=self.mode_var.get(), dry_run=dry_run,
            )
        except Exception as e:
            self.log_write(self.log, f"ERREUR : {e}\n", "err")
            pm_common.write_error_log(TOOL_NAME, e)
            return

        if not results:
            self.log_write(self.log, "Aucune correspondance trouvée.\n", "dim")
            return

        n_ok = n_failed = 0
        for clip_name, old_val, new_val, status in results:
            self.log_write(self.log, f"  {clip_name}", "header")
            if status == "FAILED":
                self.log_write(self.log, "  [ÉCHEC]\n", "err")
                n_failed += 1
            elif status not in ("preview",):
                self.log_write(self.log, f"  [via {status}]\n", "dim")
                n_ok += 1
            else:
                self.log_write(self.log, "\n", "")
                n_ok += 1
            self.log_write(self.log, f"    {old_val!r:30s}", "warn")
            self.log_write(self.log, " → ", "dim")
            self.log_write(self.log, f"{new_val!r}\n", "ok")

        if dry_run:
            self.log_write(self.log, f"\n{n_ok} clip(s) seraient modifiés. Clique sur APPLIQUER pour confirmer.\n", "accent")
        else:
            if n_ok:
                self.log_write(self.log, f"\n✓ {n_ok} clip(s) modifié(s) avec succès.\n", "ok")
            if n_failed:
                self.log_write(self.log,
                    f"✗ {n_failed} clip(s) n'ont pas pu être modifiés — "
                    f"« {column} » n'est probablement pas un nom de colonne/métadonnée valide dans ce projet.\n",
                    "err")

    def _preview(self):
        self._run(dry_run=True)

    def _apply(self):
        if messagebox.askyesno("Confirmer", "Appliquer les modifications aux métadonnées ?"):
            self._run(dry_run=False)


def open_window(master):
    return FindReplaceWindow(master)
