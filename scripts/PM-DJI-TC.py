#!/usr/bin/env python3
"""
PM — Timecode Extractor
========================
Extrait l'heure de tournage depuis le nom de fichier des clips sélectionnés
et l'écrit dans le champ "Start TC" de DaVinci Resolve.

Exemple DJI : DJI_20260404093439_0031_D  →  Start TC : 09:34:39:00

Lance depuis : Workspaces > Scripts > Utility
Compatibilité : DaVinci Resolve 18+
"""

import os
import re
import sys
import tkinter as tk
from tkinter import ttk, messagebox

# ── Vrai home (contourne le sandbox App Store) ────────────────────────────────
_USER      = os.environ.get("USER") or os.environ.get("LOGNAME")
_REAL_HOME = f"/Users/{_USER}"

# ── Presets caméra ─────────────────────────────────────────────────────────────
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


# ── Générateur de regex strict ─────────────────────────────────────────────────
def generate_strict_pattern(filename, tc_portion):
    """
    Génère un regex strict à partir d'un nom de fichier exemple et de la
    portion HHMMSS identifiée manuellement.

    Logique :
      - La portion tc_portion est remplacée par (?P<tc>\d{6})
      - Les autres groupes de chiffres consécutifs → \d{N}
      - Les caractères texte restent littéraux (échappés pour regex)

    Retourne le pattern regex sous forme de string.
    Lève ValueError si tc_portion introuvable ou invalide.
    """
    stem = os.path.splitext(filename.strip())[0]
    tc   = tc_portion.strip()

    # Validations de base
    if not tc:
        raise ValueError("La portion HHMMSS est vide.")
    if not re.fullmatch(r"\d{6}", tc):
        raise ValueError(f"La portion HHMMSS doit faire exactement 6 chiffres, trouvé : {tc!r}")
    if tc not in stem:
        raise ValueError(f"{tc!r} introuvable dans {stem!r}")

    # Vérifie que la portion est bien des chiffres HHMMSS valides
    hh, mm, ss = int(tc[0:2]), int(tc[2:4]), int(tc[4:6])
    if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59):
        raise ValueError(f"Valeurs TC invalides : {hh:02d}h{mm:02d}m{ss:02d}s")

    # Remplace la portion TC par un placeholder unique
    placeholder = "\x00TC\x00"
    marked = stem.replace(tc, placeholder, 1)

    # Découpe en segments et construit le regex
    parts  = marked.split(placeholder)
    if len(parts) != 2:
        raise ValueError("La portion HHMMSS apparaît plusieurs fois dans le nom — ambiguïté.")

    def segment_to_regex(seg):
        """Convertit un segment texte en regex : chiffres → \d{N}, texte → littéral."""
        result  = ""
        i       = 0
        while i < len(seg):
            if seg[i].isdigit():
                # Groupe de chiffres consécutifs
                j = i
                while j < len(seg) and seg[j].isdigit():
                    j += 1
                result += rf"\d{{{j - i}}}"
                i = j
            else:
                result += re.escape(seg[i])
                i += 1
        return result

    pattern = segment_to_regex(parts[0]) + r"(?P<tc>\d{6})" + segment_to_regex(parts[1])
    return pattern


# ── Connexion Resolve ──────────────────────────────────────────────────────────
def get_resolve_objects():
    fallback_paths = [
        _REAL_HOME + "/Library/Containers/com.blackmagic-design.DaVinciResolveAppStore/Data/Library/Application Support/Developer/Scripting/Modules",
        "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules",
    ]
    for p in fallback_paths:
        if p not in sys.path:
            sys.path.insert(0, p)

    try:
        import DaVinciResolveScript as dvr
    except ImportError:
        raise RuntimeError(
            "Le module DaVinciResolveScript est introuvable.\n"
            "Lance ce script depuis Workspaces > Scripts dans DaVinci Resolve."
        )

    resolve = dvr.scriptapp("Resolve")
    if not resolve:
        raise RuntimeError("Impossible de se connecter à DaVinci Resolve. Est-il ouvert ?")

    pm      = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    if not project:
        raise RuntimeError("Aucun projet ouvert dans Resolve.")

    return resolve, project, project.GetMediaPool()


# ── Extraction TC ──────────────────────────────────────────────────────────────
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
        raise ValueError(
            "Le pattern doit contenir (?P<tc>HHMMSS) "
            "ou (?P<hh>HH)(?P<mm>MM)(?P<ss>SS)"
        )

    if not (0 <= int(hh) <= 23): raise ValueError(f"Heure invalide : {hh}")
    if not (0 <= int(mm) <= 59): raise ValueError(f"Minutes invalides : {mm}")
    if not (0 <= int(ss) <= 59): raise ValueError(f"Secondes invalides : {ss}")

    return hh, mm, ss


def format_tc(hh, mm, ss):
    return f"{hh}:{mm}:{ss}:00"


# ── Logique principale ─────────────────────────────────────────────────────────
def run_tc_extraction(pattern, dry_run=False):
    _, _, media_pool = get_resolve_objects()

    clips = media_pool.GetSelectedClips()
    if not clips:
        raise RuntimeError(
            "Aucun clip sélectionné.\n"
            "Sélectionne au moins un clip dans la bin."
        )

    resultats, ignores = [], []

    for clip in clips:
        name = clip.GetClipProperty("Clip Name") or clip.GetName()
        try:
            hh, mm, ss = extract_tc_from_filename(name, pattern)
            tc_str     = format_tc(hh, mm, ss)
            if not dry_run:
                clip.SetClipProperty("Start TC", tc_str)
            resultats.append((name, tc_str))
        except ValueError as e:
            ignores.append((name, str(e)))

    return resultats, ignores


# ── Interface ──────────────────────────────────────────────────────────────────
class App(tk.Tk):
    DARK_BG   = "#1a1a1f"
    PANEL_BG  = "#22222a"
    BORDER    = "#35354a"
    ACCENT    = "#5b8eff"
    ACCENT_HO = "#7aa3ff"
    SUCCESS   = "#3ecf6e"
    WARNING   = "#f0c040"
    DANGER    = "#e05555"
    FG        = "#d8d8e8"
    FG_DIM    = "#7878a0"
    FONT_MONO = ("Menlo", 11) if sys.platform == "darwin" else ("Consolas", 10)
    FONT_UI   = ("SF Pro Display", 12) if sys.platform == "darwin" else ("Segoe UI", 11)
    FONT_SM   = ("SF Pro Display", 10) if sys.platform == "darwin" else ("Segoe UI", 9)

    def __init__(self):
        super().__init__()
        self.title("Resolve — Timecode Extractor")
        self.resizable(False, False)
        self.configure(bg=self.DARK_BG)
        self._build()
        self._center()

    def _center(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw-w)//2}+{(sh-h)//2}")

    def _build(self):
        P = 20

        # Header
        hdr = tk.Frame(self, bg="#111116", pady=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text="⬡  TIMECODE EXTRACTOR",
                 font=(self.FONT_UI[0], 13, "bold"),
                 bg="#111116", fg=self.ACCENT).pack(side="left", padx=P)
        tk.Label(hdr, text="DaVinci Resolve  ·  Media Pool",
                 font=self.FONT_SM, bg="#111116", fg=self.FG_DIM).pack(side="right", padx=P)

        self.main = tk.Frame(self, bg=self.DARK_BG, padx=P, pady=P)
        self.main.pack(fill="both")

        # ── Preset selector ────────────────────────────────────────────────────
        self._section(self.main, "CAMÉRA / FORMAT")
        self.preset_var = tk.StringVar(value=PRESETS[0]["label"])
        combo = ttk.Combobox(self.main, textvariable=self.preset_var,
                             values=[p["label"] for p in PRESETS],
                             state="readonly", width=40, font=self.FONT_UI)
        combo.pack(anchor="w", pady=(4, 0))
        combo.bind("<<ComboboxSelected>>", self._on_preset_change)

        # Exemple nom de fichier (presets connus)
        self.example_var = tk.StringVar(value=f"ex: {PRESETS[0]['example']}")
        self.example_lbl = tk.Label(self.main, textvariable=self.example_var,
                                     font=self.FONT_SM, bg=self.DARK_BG, fg=self.FG_DIM)
        self.example_lbl.pack(anchor="w", pady=(4, 0))

        # ── Panneau Custom — Pattern Extractor ────────────────────────────────
        self.custom_frame = tk.Frame(self.main, bg=self.DARK_BG)

        self._section(self.custom_frame, "ÉTAPE 1 — Nom de fichier exemple")
        tk.Label(self.custom_frame,
                 text="Colle le nom d'un fichier représentatif (avec ou sans extension)",
                 font=self.FONT_SM, bg=self.DARK_BG, fg=self.FG_DIM).pack(anchor="w", pady=(0, 4))

        self.filename_var = tk.StringVar()
        self.filename_var.trace_add("write", self._on_fields_change)
        tk.Entry(self.custom_frame, textvariable=self.filename_var,
                 font=self.FONT_MONO, bg=self.PANEL_BG, fg=self.FG,
                 bd=0, relief="flat", insertbackground=self.ACCENT,
                 highlightbackground=self.BORDER, highlightthickness=1,
                 highlightcolor=self.ACCENT, width=52
                 ).pack(fill="x", ipady=7, padx=1)

        self._section(self.custom_frame, "ÉTAPE 2 — Portion HHMMSS")
        tk.Label(self.custom_frame,
                 text="Copie uniquement les 6 chiffres qui représentent l'heure (ex: 093439)",
                 font=self.FONT_SM, bg=self.DARK_BG, fg=self.FG_DIM).pack(anchor="w", pady=(0, 4))

        self.tc_portion_var = tk.StringVar()
        self.tc_portion_var.trace_add("write", self._on_fields_change)
        tk.Entry(self.custom_frame, textvariable=self.tc_portion_var,
                 font=self.FONT_MONO, bg=self.PANEL_BG, fg=self.FG,
                 bd=0, relief="flat", insertbackground=self.ACCENT,
                 highlightbackground=self.BORDER, highlightthickness=1,
                 highlightcolor=self.ACCENT, width=16
                 ).pack(anchor="w", ipady=7, padx=1)

        self._section(self.custom_frame, "ÉTAPE 3 — Regex généré")
        self.generated_pattern_var = tk.StringVar(value="—")
        self.pattern_status_var    = tk.StringVar(value="")

        gen_frame = tk.Frame(self.custom_frame, bg=self.PANEL_BG,
                              highlightbackground=self.BORDER, highlightthickness=1)
        gen_frame.pack(fill="x", pady=(4, 0))
        tk.Label(gen_frame, textvariable=self.generated_pattern_var,
                 font=self.FONT_MONO, bg=self.PANEL_BG, fg=self.ACCENT,
                 anchor="w", padx=10, pady=6).pack(fill="x")

        self.pattern_status_lbl = tk.Label(self.custom_frame,
                                            textvariable=self.pattern_status_var,
                                            font=self.FONT_SM, bg=self.DARK_BG,
                                            fg=self.SUCCESS, anchor="w")
        self.pattern_status_lbl.pack(anchor="w", pady=(4, 0))

        # ── Aperçu TC ──────────────────────────────────────────────────────────
        self._section(self.main, "APERÇU")
        preview_frame = tk.Frame(self.main, bg=self.PANEL_BG,
                                  highlightbackground=self.BORDER, highlightthickness=1)
        preview_frame.pack(fill="x", pady=(4, 0))
        self.preview_var = tk.StringVar(value="Lance une prévisualisation pour voir le résultat.")
        tk.Label(preview_frame, textvariable=self.preview_var,
                 font=self.FONT_MONO, bg=self.PANEL_BG, fg=self.FG_DIM,
                 anchor="w", padx=10, pady=8).pack(fill="x")

        # ── Boutons ────────────────────────────────────────────────────────────
        btn_row = tk.Frame(self.main, bg=self.DARK_BG)
        btn_row.pack(fill="x", pady=(16, 0))
        self._btn(btn_row, "PRÉVISUALISER", self.ACCENT,  self._preview, side="left")
        self._btn(btn_row, "APPLIQUER",     self.SUCCESS, self._apply,   side="left", padx_l=10)
        self._btn(btn_row, "EFFACER LOG",   self.FG_DIM,  self._clear,   side="right")

        # ── Log ────────────────────────────────────────────────────────────────
        tk.Frame(self.main, bg=self.BORDER, height=1).pack(fill="x", pady=(16, 0))
        tk.Label(self.main, text="LOG", font=(self.FONT_UI[0], 10, "bold"),
                 bg=self.DARK_BG, fg=self.FG_DIM).pack(anchor="w", pady=(8, 4))

        log_frame = tk.Frame(self.main, bg=self.PANEL_BG,
                              highlightbackground=self.BORDER, highlightthickness=1)
        log_frame.pack(fill="both", expand=True)

        self.log = tk.Text(log_frame, bg=self.PANEL_BG, fg=self.FG,
                            font=self.FONT_MONO, bd=0, relief="flat",
                            width=66, height=10, wrap="none",
                            insertbackground=self.ACCENT,
                            selectbackground=self.ACCENT)
        self.log.pack(side="left", fill="both", expand=True, padx=8, pady=8)

        sb = tk.Scrollbar(log_frame, command=self.log.yview,
                           bg=self.PANEL_BG, troughcolor=self.PANEL_BG, bd=0, relief="flat")
        sb.pack(side="right", fill="y")
        self.log.config(yscrollcommand=sb.set)

        self.log.tag_config("dim",    foreground=self.FG_DIM)
        self.log.tag_config("ok",     foreground=self.SUCCESS)
        self.log.tag_config("warn",   foreground=self.WARNING)
        self.log.tag_config("err",    foreground=self.DANGER)
        self.log.tag_config("accent", foreground=self.ACCENT)
        self.log.tag_config("header", foreground=self.FG,
                             font=(self.FONT_MONO[0], self.FONT_MONO[1], "bold"))

        self._log("Prêt. Sélectionne des clips dans la bin puis clique sur Prévisualiser.\n", "dim")

    # ── Helpers UI ─────────────────────────────────────────────────────────────
    def _section(self, parent, label):
        tk.Label(parent, text=label, font=(self.FONT_UI[0], 9, "bold"),
                 bg=self.DARK_BG, fg=self.FG_DIM).pack(anchor="w", pady=(12, 2))

    def _btn(self, parent, label, color, cmd, side="left", padx_l=0):
        tk.Button(parent, text=label, font=(self.FONT_UI[0], 10, "bold"),
                   bg=color, fg="#0a0a10" if color != self.FG_DIM else self.DARK_BG,
                   activebackground=self.ACCENT_HO, relief="flat", bd=0,
                   padx=18, pady=8, cursor="hand2", command=cmd
                  ).pack(side=side, padx=(padx_l, 0))

    def _log(self, text, tag=""):
        self.log.config(state="normal")
        self.log.insert("end", text, tag) if tag else self.log.insert("end", text)
        self.log.see("end")
        self.log.config(state="disabled")

    def _clear(self):
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")
        self._log("Log effacé.\n", "dim")

    def _on_preset_change(self, event=None):
        label  = self.preset_var.get()
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
        """Retourne le widget Aperçu pour pouvoir insérer custom_frame avant lui."""
        # On cherche le label "APERÇU" dans main
        for child in self.main.winfo_children():
            if isinstance(child, tk.Label) and "APERÇU" in (child.cget("text") or ""):
                return child
        return None

    def _on_fields_change(self, *args):
        """Régénère le pattern en temps réel quand filename ou tc_portion changent."""
        filename = self.filename_var.get().strip()
        tc       = self.tc_portion_var.get().strip()

        if not filename or not tc:
            self.generated_pattern_var.set("—")
            self.pattern_status_var.set("")
            return

        try:
            pattern = generate_strict_pattern(filename, tc)
            self.generated_pattern_var.set(pattern)
            # Test immédiat sur le nom de fichier fourni
            hh, mm, ss = extract_tc_from_filename(filename, pattern)
            tc_result  = format_tc(hh, mm, ss)
            self.pattern_status_var.set(f"✓  Test sur l'exemple  →  {tc_result}")
            self.pattern_status_lbl.config(fg=self.SUCCESS)
        except ValueError as e:
            self.generated_pattern_var.set("—")
            self.pattern_status_var.set(f"✗  {e}")
            self.pattern_status_lbl.config(fg=self.DANGER)

    def _get_pattern(self):
        label  = self.preset_var.get()
        preset = next((p for p in PRESETS if p["label"] == label), None)
        if preset and preset["pattern"]:
            return preset["pattern"]
        # Mode custom — utilise le pattern généré
        pattern = self.generated_pattern_var.get().strip()
        if not pattern or pattern == "—":
            raise ValueError(
                "Aucun pattern généré.\n"
                "Remplis le nom de fichier exemple et la portion HHMMSS."
            )
        return pattern

    # ── Actions ────────────────────────────────────────────────────────────────
    def _run(self, dry_run):
        try:
            pattern = self._get_pattern()
        except ValueError as e:
            messagebox.showerror("Erreur", str(e))
            return

        mode = "DRY RUN" if dry_run else "APPLY"
        self._log(f"\n{'─'*56}\n", "dim")
        self._log(f"[{mode}]  ", "accent")
        self._log(f"pattern={pattern!r}\n", "dim")
        self._log(f"{'─'*56}\n", "dim")

        try:
            resultats, ignores = run_tc_extraction(pattern, dry_run=dry_run)
        except Exception as e:
            self._log(f"ERREUR : {e}\n", "err")
            return

        for name, tc in resultats:
            self._log(f"  {name}\n", "header")
            self._log(f"    Start TC  →  ", "dim")
            self._log(f"{tc}\n", "ok")

        if ignores:
            self._log(f"\n  — {len(ignores)} clip(s) ignoré(s) —\n", "dim")
            for name, raison in ignores:
                self._log(f"  {name}\n", "warn")
                self._log(f"    {raison}\n", "dim")

        n = len(resultats)
        if dry_run:
            if resultats:
                sample = resultats[0][1]
                self.preview_var.set(
                    f"{n} clip(s) → Start TC : {sample}" + (" …" if n > 1 else "")
                )
            self._log(f"\n{n} clip(s) seraient modifiés. Clique sur APPLIQUER pour confirmer.\n", "accent")
        else:
            self._log(f"\n✓ {n} clip(s) modifié(s) avec succès.\n", "ok")

    def _preview(self): self._run(dry_run=True)
    def _apply(self):
        if messagebox.askyesno("Confirmer",
                               "Écrire le Start TC sur les clips sélectionnés ?\n"
                               "Cette action modifie les métadonnées dans la bin."):
            self._run(dry_run=False)


# ── Entrypoint ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = App()
    app.mainloop()
