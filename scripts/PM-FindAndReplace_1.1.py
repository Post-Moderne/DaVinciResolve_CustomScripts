#!/usr/bin/env python3
"""
Resolve Metadata Find & Replace
================================
Script de remplacement de métadonnées pour DaVinci Resolve.
Lance depuis : Workspaces > Scripts > Utility

Compatibilité : DaVinci Resolve 18+

INSTALLATION
─────────────
App Store (sandbox) :
  ~/Library/Containers/com.blackmagic-design.DaVinciResolveAppStore/Data/Library/Application Support/Fusion/Scripts/Utility/

DMG (standard) :
  /Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/

Ce script détecte automatiquement la variante active au lancement.
"""

import os
import re
import sys
import tkinter as tk
from tkinter import ttk, messagebox

# ── Détection du vrai home (contourne le sandbox App Store) ───────────────────
# os.environ["HOME"] est remappé par le sandbox — on utilise USER à la place
_USER      = os.environ.get("USER") or os.environ.get("LOGNAME")
_REAL_HOME = f"/Users/{_USER}"

# ── Paths App Store vs DMG ────────────────────────────────────────────────────
_PATHS = {
    "appstore": {
        "scripts": _REAL_HOME + "/Library/Containers/com.blackmagic-design.DaVinciResolveAppStore/Data/Library/Application Support/Fusion/Scripts",
        "modules": _REAL_HOME + "/Library/Containers/com.blackmagic-design.DaVinciResolveAppStore/Data/Library/Application Support/Developer/Scripting/Modules",
    },
    "dmg": {
        "scripts": _REAL_HOME + "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts",
        "modules": "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules",
    },
}

def _resolve_variant():
    """Retourne 'appstore', 'dmg' ou 'unknown' selon la variante détectée."""
    for variant, p in _PATHS.items():
        if os.path.isdir(p["scripts"]):
            return variant
    return "unknown"

RESOLVE_VARIANT = _resolve_variant()

# ── Colonnes standard Resolve ──────────────────────────────────────────────────
STANDARD_COLUMNS = [
    "Clip Name", "Scene", "Shot", "Take", "Angle", "Camera #", "Camera Type",
    "Good Take", "Description", "Comments", "Keywords", "Clip Color",
    "Reel Name", "Start TC", "End TC", "FPS", "Resolution",
    "Date Modified", "Date Created", "File Name", "File Path",
    "Codec", "Duration", "Frames", "Audio Ch",
]


# ── Connexion à Resolve ────────────────────────────────────────────────────────
def get_resolve_objects():
    """Retourne (resolve, project, media_pool) ou lève une exception."""
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

    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    if not project:
        raise RuntimeError("Aucun projet ouvert dans Resolve.")

    media_pool = project.GetMediaPool()
    return resolve, project, media_pool


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
    """Lit la valeur via GetClipProperty, avec fallback GetMetadata pour les
    colonnes custom qui ne sont pas reconnues comme 'Clip Property'."""
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
    """Écrit la valeur via SetClipProperty, avec fallback SetMetadata pour les
    colonnes custom. Retourne (success: bool, method: str)."""
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


# ── Logique find & replace ─────────────────────────────────────────────────────
def run_find_replace(column, find_text, replace_text, use_regex, case_sensitive,
                     selected_only, mode="replace", dry_run=False):
    """
    Effectue le find & replace / append / prepend sur les clips.
    Retourne une liste de tuples (clip_name, old_value, new_value, status).
    mode   : 'replace' | 'append' | 'prepend'
    status : 'preview' (dry run), 'ClipProperty', 'Metadata', ou 'FAILED'
    """
    _, _, media_pool = get_resolve_objects()
    clips = get_clips(media_pool, selected_only)

    flags = 0 if case_sensitive else re.IGNORECASE
    results = []

    for clip in clips:
        current_value = _get_clip_value(clip, column)

        try:
            if mode == "append":
                # Si find_text fourni, n'appliquer qu'aux clips qui matchent
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


# ── Interface tkinter ──────────────────────────────────────────────────────────
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
        self.title("Resolve — Metadata Find & Replace")
        self.resizable(False, False)
        self.configure(bg=self.DARK_BG)
        self._style()
        self._build()
        self._center()

    def _center(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw-w)//2}+{(sh-h)//2}")

    def _style(self):
        s = ttk.Style(self)
        s.theme_use("default")
        s.configure("TCombobox",
                     fieldbackground=self.PANEL_BG,
                     background=self.PANEL_BG,
                     foreground=self.FG,
                     selectbackground=self.ACCENT,
                     selectforeground="white",
                     bordercolor=self.BORDER,
                     arrowcolor=self.FG_DIM,
                     relief="flat")
        s.map("TCombobox", fieldbackground=[("readonly", self.PANEL_BG)])

    # ── Layout ─────────────────────────────────────────────────────────────────
    def _build(self):
        P = 20

        # Header
        hdr = tk.Frame(self, bg="#111116", pady=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text="⬡  METADATA FIND & REPLACE",
                 font=(self.FONT_UI[0], 13, "bold"),
                 bg="#111116", fg=self.ACCENT).pack(side="left", padx=P)
        variant_label = {"appstore": "App Store", "dmg": "DMG"}.get(RESOLVE_VARIANT, "?")
        tk.Label(hdr, text=f"DaVinci Resolve  ·  {variant_label}",
                 font=self.FONT_SM, bg="#111116", fg=self.FG_DIM).pack(side="right", padx=P)

        # Main container
        main = tk.Frame(self, bg=self.DARK_BG, padx=P, pady=P)
        main.pack(fill="both")

        # Column selector
        self._section(main, "COLONNE CIBLE")
        col_row = tk.Frame(main, bg=self.DARK_BG)
        col_row.pack(fill="x", pady=(4, 12))

        self.col_var = tk.StringVar(value="Scene")
        self.col_combo = ttk.Combobox(col_row, textvariable=self.col_var,
                                       values=STANDARD_COLUMNS, state="normal",
                                       width=28, font=self.FONT_UI)
        self.col_combo.pack(side="left")
        tk.Label(col_row, text="(ou tape un nom custom)",
                 font=self.FONT_SM, bg=self.DARK_BG, fg=self.FG_DIM).pack(side="left", padx=(10, 0))

        # Find / Replace / Append / Prepend fields
        self._section(main, "RECHERCHE  (vide = tous les clips)")
        self.find_var = tk.StringVar()
        self._entry(main, self.find_var, "Texte ou regex à rechercher…")

        self._section(main, "TEXTE")
        self.replace_var = tk.StringVar()
        self._entry(main, self.replace_var, "Texte de remplacement / à ajouter…")

        # Mode selector
        self._section(main, "MODE")
        mode_row = tk.Frame(main, bg=self.DARK_BG)
        mode_row.pack(fill="x", pady=(4, 12))
        self.mode_var = tk.StringVar(value="replace")
        for val, label in [("replace", "Remplacer"), ("append", "Ajouter à la fin"), ("prepend", "Ajouter au début")]:
            rb = tk.Radiobutton(mode_row, text=label, variable=self.mode_var, value=val,
                                bg=self.DARK_BG, fg=self.FG, activebackground=self.DARK_BG,
                                activeforeground=self.FG, selectcolor=self.PANEL_BG,
                                font=self.FONT_SM, bd=0)
            rb.pack(side="left", padx=(0, 16))

        # Options
        self._section(main, "OPTIONS")
        opt = tk.Frame(main, bg=self.DARK_BG)
        opt.pack(fill="x", pady=(4, 12))

        self.regex_var = tk.BooleanVar(value=False)
        self.case_var  = tk.BooleanVar(value=False)
        self.scope_var = tk.BooleanVar(value=True)

        self._checkbox(opt, "Regex (mode avancé)", self.regex_var, row=0, col=0)
        self._checkbox(opt, "Respecter la casse",  self.case_var,  row=0, col=1)
        self._checkbox(opt, "Clips sélectionnés seulement", self.scope_var, row=1, col=0)

        # Action buttons
        btn_row = tk.Frame(main, bg=self.DARK_BG)
        btn_row.pack(fill="x", pady=(4, 0))

        self._btn(btn_row, "PRÉVISUALISER", self.ACCENT,  self._preview,  side="left")
        self._btn(btn_row, "APPLIQUER",     self.SUCCESS, self._apply,   side="left", padx_l=10)
        self._btn(btn_row, "EFFACER LOG",   self.FG_DIM,  self._clear,   side="right")

        # Log area
        sep = tk.Frame(main, bg=self.BORDER, height=1)
        sep.pack(fill="x", pady=(16, 0))

        log_hdr = tk.Frame(main, bg=self.DARK_BG)
        log_hdr.pack(fill="x", pady=(8, 4))
        self.log_title = tk.Label(log_hdr, text="LOG", font=(self.FONT_UI[0], 10, "bold"),
                                   bg=self.DARK_BG, fg=self.FG_DIM)
        self.log_title.pack(side="left")

        log_frame = tk.Frame(main, bg=self.PANEL_BG, bd=0,
                              highlightbackground=self.BORDER, highlightthickness=1)
        log_frame.pack(fill="both", expand=True)

        self.log = tk.Text(log_frame, bg=self.PANEL_BG, fg=self.FG,
                            font=self.FONT_MONO, bd=0, relief="flat",
                            width=66, height=14, wrap="none",
                            insertbackground=self.ACCENT,
                            selectbackground=self.ACCENT)
        self.log.pack(side="left", fill="both", expand=True, padx=8, pady=8)

        sb = tk.Scrollbar(log_frame, command=self.log.yview, bg=self.PANEL_BG,
                           troughcolor=self.PANEL_BG, bd=0, relief="flat")
        sb.pack(side="right", fill="y")
        self.log.config(yscrollcommand=sb.set)

        self.log.tag_config("dim",     foreground=self.FG_DIM)
        self.log.tag_config("ok",      foreground=self.SUCCESS)
        self.log.tag_config("warn",    foreground=self.WARNING)
        self.log.tag_config("err",     foreground=self.DANGER)
        self.log.tag_config("accent",  foreground=self.ACCENT)
        self.log.tag_config("header",  foreground=self.FG, font=(self.FONT_MONO[0], self.FONT_MONO[1], "bold"))

        self._log("Prêt. Configure les paramètres puis clique sur Prévisualiser.\n", "dim")

    def _section(self, parent, label):
        tk.Label(parent, text=label, font=(self.FONT_UI[0], 9, "bold"),
                 bg=self.DARK_BG, fg=self.FG_DIM).pack(anchor="w", pady=(10, 2))

    def _entry(self, parent, var, placeholder):
        e = tk.Entry(parent, textvariable=var, font=self.FONT_MONO,
                     bg=self.PANEL_BG, fg=self.FG, bd=0, relief="flat",
                     insertbackground=self.ACCENT,
                     highlightbackground=self.BORDER, highlightthickness=1,
                     highlightcolor=self.ACCENT)
        e.pack(fill="x", ipady=7, padx=1, pady=(0, 2))
        e.insert(0, placeholder)
        e.config(fg=self.FG_DIM)
        def on_focus_in(ev, en=e, ph=placeholder):
            if en.get() == ph:
                en.delete(0, "end")
                en.config(fg=self.FG)
        def on_focus_out(ev, en=e, v=var, ph=placeholder):
            if not en.get():
                en.insert(0, ph)
                en.config(fg=self.FG_DIM)
        e.bind("<FocusIn>",  on_focus_in)
        e.bind("<FocusOut>", on_focus_out)

    def _checkbox(self, parent, label, var, row, col):
        cb = tk.Checkbutton(parent, text=label, variable=var,
                             bg=self.DARK_BG, fg=self.FG,
                             activebackground=self.DARK_BG,
                             activeforeground=self.FG,
                             selectcolor=self.PANEL_BG,
                             font=self.FONT_SM, bd=0)
        cb.grid(row=row, column=col, sticky="w", padx=(0, 20), pady=2)

    def _btn(self, parent, label, color, cmd, side="left", padx_l=0):
        b = tk.Button(parent, text=label, font=(self.FONT_UI[0], 10, "bold"),
                       bg=color, fg="#0a0a10" if color != self.FG_DIM else self.DARK_BG,
                       activebackground=self.ACCENT_HO,
                       relief="flat", bd=0, padx=18, pady=8, cursor="hand2",
                       command=cmd)
        b.pack(side=side, padx=(padx_l, 0))

    # ── Log helpers ────────────────────────────────────────────────────────────
    def _log(self, text, tag=""):
        self.log.config(state="normal")
        if tag:
            self.log.insert("end", text, tag)
        else:
            self.log.insert("end", text)
        self.log.see("end")
        self.log.config(state="disabled")

    def _clear(self):
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")
        self._log("Log effacé.\n", "dim")

    # ── Validation ─────────────────────────────────────────────────────────────
    def _validate(self):
        placeholders = {"Texte ou regex à rechercher…", "Texte de remplacement / à ajouter…"}
        column = self.col_var.get().strip()
        find   = self.find_var.get().strip()
        if find in placeholders:
            find = ""
        mode   = self.mode_var.get()

        if not column:
            messagebox.showerror("Erreur", "Spécifie une colonne.")
            return None, None, None
        if mode == "replace" and not find:
            messagebox.showerror("Erreur", "Le champ Recherche est vide.")
            return None, None, None

        replace = self.replace_var.get().strip()
        if replace in placeholders:
            replace = ""
        #if not replace:
        #    messagebox.showerror("Erreur", "Le champ Texte est vide.")
        #    return None, None, None

        return column, find, replace

    # ── Actions ────────────────────────────────────────────────────────────────
    def _run(self, dry_run):
        result = self._validate()
        if result[0] is None:
            return
        column, find, replace = result

        scope = "clips sélectionnés" if self.scope_var.get() else "bin entier"
        mode  = "DRY RUN" if dry_run else "APPLY"

        self._log(f"\n{'─'*56}\n", "dim")
        self._log(f"[{mode}]  ", "accent")
        self._log(f"colonne={column}  scope={scope}\n", "dim")
        mode_label = {"replace": "remplacer", "append": "ajouter à la fin", "prepend": "ajouter au début"}.get(self.mode_var.get(), "?")
        self._log(f"  mode    : ", "dim"); self._log(f"{mode_label}\n", "accent")
        self._log(f"  find    : ", "dim"); self._log(f"{find!r}\n", "warn")
        self._log(f"  texte   : ", "dim"); self._log(f"{replace!r}\n", "ok")
        if self.regex_var.get():
            self._log("  regex   : activé\n", "dim")
        if self.case_var.get():
            self._log("  casse   : sensible\n", "dim")
        self._log(f"{'─'*56}\n", "dim")

        try:
            results = run_find_replace(
                column        = column,
                find_text     = find,
                replace_text  = replace,
                use_regex     = self.regex_var.get(),
                case_sensitive= self.case_var.get(),
                selected_only = self.scope_var.get(),
                mode          = self.mode_var.get(),
                dry_run       = dry_run,
            )
        except Exception as e:
            self._log(f"ERREUR : {e}\n", "err")
            return

        if not results:
            self._log("Aucune correspondance trouvée.\n", "dim")
            return

        n_ok = 0
        n_failed = 0
        for clip_name, old_val, new_val, status in results:
            self._log(f"  {clip_name}", "header")
            if status == "FAILED":
                self._log("  [ÉCHEC]\n", "err")
                n_failed += 1
            elif status not in ("preview",):
                self._log(f"  [via {status}]\n", "dim")
                n_ok += 1
            else:
                self._log("\n", "")
                n_ok += 1
            self._log(f"    {old_val!r:30s}", "warn")
            self._log(" → ", "dim")
            self._log(f"{new_val!r}\n", "ok")

        if dry_run:
            self._log(f"\n{n_ok} clip(s) seraient modifiés. Clique sur APPLIQUER pour confirmer.\n", "accent")
        else:
            if n_ok:
                self._log(f"\n✓ {n_ok} clip(s) modifié(s) avec succès.\n", "ok")
            if n_failed:
                self._log(
                    f"✗ {n_failed} clip(s) n'ont pas pu être modifiés — "
                    f"« {column} » n'est probablement pas un nom de colonne/métadonnée valide dans ce projet.\n",
                    "err"
                )

    def _preview(self): self._run(dry_run=True)
    def _apply(self):
        if messagebox.askyesno("Confirmer", "Appliquer les modifications aux métadonnées ?"):
            self._run(dry_run=False)


# ── Entrypoint ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = App()
    app.mainloop()