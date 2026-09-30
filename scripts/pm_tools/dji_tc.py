#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Timecode Extractor — extrait l'heure de tournage depuis le nom de fichier
des clips sélectionnés et l'écrit dans "Start TC".
Module interne de la PM Suite (voir PM-Suite.py).

Exemple DJI : DJI_20260404093439_0031_D  →  Start TC : 09:34:39:00
"""

import os
import re
import sys
import tkinter as tk
from tkinter import ttk, messagebox

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pm_common
from pm_common import PMWindow, Theme

TOOL_NAME = "PM-DJI-TC"

PRESETS = [
    {
        "label"  : "DJI (Mavic / Air / Mini / FPV)",
        "pattern": r"DJI_\d{8}(?P<tc>\d{6})",
        "example": "DJI_20260404093439_0031_D",
    },
    {
        "label"  : "Custom — Pattern Extractor",
        "pattern": "",
        "example": "",
    },
]


def generate_strict_pattern(filename, tc_portion):
    """
    Génère un regex strict à partir d'un nom de fichier exemple et de la
    portion HHMMSS identifiée manuellement.
    """
    stem = os.path.splitext(filename.strip())[0]
    tc = tc_portion.strip()

    if not tc:
        raise ValueError("La portion HHMMSS est vide.")
    if not re.fullmatch(r"\d{6}", tc):
        raise ValueError(f"La portion HHMMSS doit faire exactement 6 chiffres, trouvé : {tc!r}")
    if tc not in stem:
        raise ValueError(f"{tc!r} introuvable dans {stem!r}")

    hh, mm, ss = int(tc[0:2]), int(tc[2:4]), int(tc[4:6])
    if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59):
        raise ValueError(f"Valeurs TC invalides : {hh:02d}h{mm:02d}m{ss:02d}s")

    placeholder = "\x00TC\x00"
    marked = stem.replace(tc, placeholder, 1)

    parts = marked.split(placeholder)
    if len(parts) != 2:
        raise ValueError("La portion HHMMSS apparaît plusieurs fois dans le nom — ambiguïté.")

    def segment_to_regex(seg):
        result = ""
        i = 0
        while i < len(seg):
            if seg[i].isdigit():
                j = i
                while j < len(seg) and seg[j].isdigit():
                    j += 1
                result += rf"\d{{{j - i}}}"
                i = j
            else:
                result += re.escape(seg[i])
                i += 1
        return result

    return segment_to_regex(parts[0]) + r"(?P<tc>\d{6})" + segment_to_regex(parts[1])


def extract_tc_from_filename(filename, pattern):
    stem = os.path.splitext(filename)[0]
    try:
        m = re.search(pattern, stem)
    except re.error as e:
        raise ValueError(f"Regex invalide : {e}")

    if not m:
        raise ValueError(f"Pattern non trouvé dans : {stem!r}")

    gd = m.groupdict()

    if "tc" in gd and gd["tc"]:
        raw = gd["tc"]
        if len(raw) != 6:
            raise ValueError(f"Groupe 'tc' doit faire 6 chiffres, trouvé : {raw!r}")
        hh, mm, ss = raw[0:2], raw[2:4], raw[4:6]
    elif "hh" in gd and "mm" in gd and "ss" in gd:
        hh, mm, ss = gd["hh"], gd["mm"], gd["ss"]
    else:
        raise ValueError("Le pattern doit contenir (?P<tc>HHMMSS) ou (?P<hh>HH)(?P<mm>MM)(?P<ss>SS)")

    if not (0 <= int(hh) <= 23): raise ValueError(f"Heure invalide : {hh}")
    if not (0 <= int(mm) <= 59): raise ValueError(f"Minutes invalides : {mm}")
    if not (0 <= int(ss) <= 59): raise ValueError(f"Secondes invalides : {ss}")

    return hh, mm, ss


def format_tc(hh, mm, ss):
    return f"{hh}:{mm}:{ss}:00"


def run_tc_extraction(pattern, dry_run=False):
    _, _, media_pool = pm_common.get_resolve_objects()

    clips = media_pool.GetSelectedClips()
    if not clips:
        raise RuntimeError("Aucun clip sélectionné.\nSélectionne au moins un clip dans la bin.")

    resultats, ignores = [], []
    for clip in clips:
        name = clip.GetClipProperty("Clip Name") or clip.GetName()
        try:
            hh, mm, ss = extract_tc_from_filename(name, pattern)
            tc_str = format_tc(hh, mm, ss)
            if not dry_run:
                clip.SetClipProperty("Start TC", tc_str)
            resultats.append((name, tc_str))
        except ValueError as e:
            ignores.append((name, str(e)))

    return resultats, ignores


class DjiTcWindow(PMWindow):
    def __init__(self, master):
        super().__init__(master, "Timecode Extractor", "DaVinci Resolve  ·  Media Pool")

    def _build_content(self, main):
        self.section(main, "CAMÉRA / FORMAT")
        self.preset_var = tk.StringVar(value=PRESETS[0]["label"])
        combo = ttk.Combobox(main, textvariable=self.preset_var,
                             values=[p["label"] for p in PRESETS],
                             state="readonly", width=40, font=Theme.FONT_UI)
        combo.pack(anchor="w", pady=(4, 0))
        combo.bind("<<ComboboxSelected>>", self._on_preset_change)

        self.example_var = tk.StringVar(value=f"ex: {PRESETS[0]['example']}")
        self.example_lbl = tk.Label(main, textvariable=self.example_var,
                                     font=Theme.FONT_SM, bg=Theme.DARK_BG, fg=Theme.FG_DIM)
        self.example_lbl.pack(anchor="w", pady=(4, 0))

        self.custom_frame = tk.Frame(main, bg=Theme.DARK_BG)

        self.section(self.custom_frame, "ÉTAPE 1 — Nom de fichier exemple")
        tk.Label(self.custom_frame, text="Colle le nom d'un fichier représentatif (avec ou sans extension)",
                 font=Theme.FONT_SM, bg=Theme.DARK_BG, fg=Theme.FG_DIM).pack(anchor="w", pady=(0, 4))
        self.filename_var = tk.StringVar()
        self.filename_var.trace_add("write", self._on_fields_change)
        self.entry(self.custom_frame, self.filename_var)

        self.section(self.custom_frame, "ÉTAPE 2 — Portion HHMMSS")
        tk.Label(self.custom_frame, text="Copie uniquement les 6 chiffres qui représentent l'heure (ex: 093439)",
                 font=Theme.FONT_SM, bg=Theme.DARK_BG, fg=Theme.FG_DIM).pack(anchor="w", pady=(0, 4))
        self.tc_portion_var = tk.StringVar()
        self.tc_portion_var.trace_add("write", self._on_fields_change)
        self.entry(self.custom_frame, self.tc_portion_var)

        self.section(self.custom_frame, "ÉTAPE 3 — Regex généré")
        self.generated_pattern_var = tk.StringVar(value="—")
        self.pattern_status_var = tk.StringVar(value="")

        gen_frame = tk.Frame(self.custom_frame, bg=Theme.PANEL_BG,
                              highlightbackground=Theme.BORDER, highlightthickness=1)
        gen_frame.pack(fill="x", pady=(4, 0))
        tk.Label(gen_frame, textvariable=self.generated_pattern_var,
                 font=Theme.FONT_MONO, bg=Theme.PANEL_BG, fg=Theme.ACCENT,
                 anchor="w", padx=10, pady=6).pack(fill="x")

        self.pattern_status_lbl = tk.Label(self.custom_frame, textvariable=self.pattern_status_var,
                                            font=Theme.FONT_SM, bg=Theme.DARK_BG, fg=Theme.SUCCESS, anchor="w")
        self.pattern_status_lbl.pack(anchor="w", pady=(4, 0))

        self.section(main, "APERÇU")
        preview_frame = tk.Frame(main, bg=Theme.PANEL_BG,
                                  highlightbackground=Theme.BORDER, highlightthickness=1)
        preview_frame.pack(fill="x", pady=(4, 0))
        self.preview_var = tk.StringVar(value="Lance une prévisualisation pour voir le résultat.")
        tk.Label(preview_frame, textvariable=self.preview_var, font=Theme.FONT_MONO,
                 bg=Theme.PANEL_BG, fg=Theme.FG_DIM, anchor="w", padx=10, pady=8).pack(fill="x")

        btn_row = tk.Frame(main, bg=Theme.DARK_BG)
        btn_row.pack(fill="x", pady=(16, 0))
        self.button(btn_row, "PRÉVISUALISER", Theme.ACCENT, self._preview, side="left")
        self.button(btn_row, "APPLIQUER", Theme.SUCCESS, self._apply, side="left", padx_l=10)
        self.button(btn_row, "EFFACER LOG", Theme.FG_DIM, self._clear, side="right")

        self.log = self.build_log(main, height=10)
        self.log_write(self.log, "Prêt. Sélectionne des clips dans la bin puis clique sur Prévisualiser.\n", "dim")

    # ── Helpers ─────────────────────────────────────────────────────────────
    def _clear(self):
        self.log_clear(self.log)
        self.log_write(self.log, "Log effacé.\n", "dim")

    def _on_preset_change(self, event=None):
        label = self.preset_var.get()
        preset = next((p for p in PRESETS if p["label"] == label), None)
        if not preset:
            return
        is_custom = preset["pattern"] == ""
        if is_custom:
            self.custom_frame.pack(fill="x", before=self._get_apercu_frame())
            self.example_lbl.pack_forget()
        else:
            self.custom_frame.pack_forget()
            self.example_lbl.pack(anchor="w", pady=(4, 0))
            self.example_var.set(f"ex: {preset['example']}" if preset["example"] else "")

    def _get_apercu_frame(self):
        for child in self.main.winfo_children():
            if isinstance(child, tk.Label) and "APERÇU" in (child.cget("text") or ""):
                return child
        return None

    def _on_fields_change(self, *args):
        filename = self.filename_var.get().strip()
        tc = self.tc_portion_var.get().strip()

        if not filename or not tc:
            self.generated_pattern_var.set("—")
            self.pattern_status_var.set("")
            return

        try:
            pattern = generate_strict_pattern(filename, tc)
            self.generated_pattern_var.set(pattern)
            hh, mm, ss = extract_tc_from_filename(filename, pattern)
            tc_result = format_tc(hh, mm, ss)
            self.pattern_status_var.set(f"✓  Test sur l'exemple  →  {tc_result}")
            self.pattern_status_lbl.config(fg=Theme.SUCCESS)
        except ValueError as e:
            self.generated_pattern_var.set("—")
            self.pattern_status_var.set(f"✗  {e}")
            self.pattern_status_lbl.config(fg=Theme.DANGER)

    def _get_pattern(self):
        label = self.preset_var.get()
        preset = next((p for p in PRESETS if p["label"] == label), None)
        if preset and preset["pattern"]:
            return preset["pattern"]
        pattern = self.generated_pattern_var.get().strip()
        if not pattern or pattern == "—":
            raise ValueError("Aucun pattern généré.\nRemplis le nom de fichier exemple et la portion HHMMSS.")
        return pattern

    # ── Actions ────────────────────────────────────────────────────────────
    def _run(self, dry_run):
        try:
            pattern = self._get_pattern()
        except ValueError as e:
            messagebox.showerror("Erreur", str(e))
            return

        mode = "DRY RUN" if dry_run else "APPLY"
        self.log_write(self.log, f"\n{'─'*56}\n", "dim")
        self.log_write(self.log, f"[{mode}]  ", "accent")
        self.log_write(self.log, f"pattern={pattern!r}\n", "dim")
        self.log_write(self.log, f"{'─'*56}\n", "dim")

        try:
            resultats, ignores = run_tc_extraction(pattern, dry_run=dry_run)
        except Exception as e:
            self.log_write(self.log, f"ERREUR : {e}\n", "err")
            pm_common.write_error_log(TOOL_NAME, e)
            return

        for name, tc in resultats:
            self.log_write(self.log, f"  {name}\n", "header")
            self.log_write(self.log, "    Start TC  →  ", "dim")
            self.log_write(self.log, f"{tc}\n", "ok")

        if ignores:
            self.log_write(self.log, f"\n  — {len(ignores)} clip(s) ignoré(s) —\n", "dim")
            for name, raison in ignores:
                self.log_write(self.log, f"  {name}\n", "warn")
                self.log_write(self.log, f"    {raison}\n", "dim")

        n = len(resultats)
        if dry_run:
            if resultats:
                sample = resultats[0][1]
                self.preview_var.set(f"{n} clip(s) → Start TC : {sample}" + (" …" if n > 1 else ""))
            self.log_write(self.log, f"\n{n} clip(s) seraient modifiés. Clique sur APPLIQUER pour confirmer.\n", "accent")
        else:
            self.log_write(self.log, f"\n✓ {n} clip(s) modifié(s) avec succès.\n", "ok")

    def _preview(self):
        self._run(dry_run=True)

    def _apply(self):
        if messagebox.askyesno("Confirmer", "Écrire le Start TC sur les clips sélectionnés ?\n"
                                "Cette action modifie les métadonnées dans la bin."):
            self._run(dry_run=False)


def open_window(master):
    return DjiTcWindow(master)
