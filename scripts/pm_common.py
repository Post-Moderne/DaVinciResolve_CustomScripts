#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pm_common – Post-Moderne
==========================

Module partagé par les outils de la PM Suite pour DaVinci Resolve
(connexion à l'API Resolve, thème d'interface, logging, boucle d'événements).

Ce module n'est PAS un script exécutable depuis Resolve : il doit être
copié à côté de PM-Suite.py dans le même dossier Scripts/Utility pour
que les imports fonctionnent.
"""

import os
import sys
import tkinter as tk
from tkinter import ttk
from datetime import datetime


# ---------------------------------------------------------------------------
# Connexion à l'API Resolve
# ---------------------------------------------------------------------------
# os.environ["HOME"] est remappé par le sandbox de la variante App Store —
# on reconstruit le vrai home à partir de USER/LOGNAME.
_USER = os.environ.get("USER") or os.environ.get("LOGNAME") or "unknown"
REAL_HOME = f"/Users/{_USER}"

PATHS = {
    "appstore": {
        "scripts": REAL_HOME + "/Library/Containers/com.blackmagic-design.DaVinciResolveAppStore/Data/Library/Application Support/Fusion/Scripts",
        "modules": REAL_HOME + "/Library/Containers/com.blackmagic-design.DaVinciResolveAppStore/Data/Library/Application Support/Developer/Scripting/Modules",
    },
    "dmg": {
        "scripts": REAL_HOME + "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts",
        "modules": "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules",
    },
}


def resolve_variant(module_file=None):
    """
    Retourne 'appstore', 'dmg' ou 'unknown'.

    1. Source de vérité : l'endroit où CE module est installé. Une copie sous le
       conteneur App Store appartient à Resolve App Store, une copie sous
       /Library/Application Support/Blackmagic Design à Resolve DMG — ce qui reste
       juste quand les deux versions cohabitent sur le poste.
    2. Repli (module lancé depuis le repo, etc.) : le premier dossier Fusion/Scripts
       qui existe. Attention : le conteneur App Store survit à la suppression de
       l'app, donc ce repli peut se tromper sur un poste où l'App Store a été retiré.
    """
    here = os.path.realpath(os.path.dirname(os.path.abspath(module_file or __file__)))
    for variant, p in PATHS.items():
        for root in (p["modules"], p["scripts"]):
            root = os.path.realpath(root)
            if here == root or here.startswith(root + os.sep):
                return variant
    for variant, p in PATHS.items():
        if os.path.isdir(p["scripts"]):
            return variant
    return "unknown"


RESOLVE_VARIANT = resolve_variant()


def install_paths(variant=None):
    """
    Retourne {"utility": ..., "modules": ...} : où vit PM-Suite.py (menu Utility)
    et où vivent pm_common.py / VERSION / pm_tools/ pour la variante donnée
    (par défaut la variante détectée).
    """
    variant = variant or RESOLVE_VARIANT
    if variant not in PATHS:
        raise RuntimeError("Variante de DaVinci Resolve non détectée (dossier Fusion/Scripts introuvable).")
    p = PATHS[variant]
    return {"utility": p["scripts"] + "/Utility", "modules": p["modules"]}


def get_version():
    """
    Lit la version installée depuis le fichier VERSION à côté de ce module —
    source de vérité unique, comparée par l'updater à la version disponible
    sur le repo GitHub public.
    """
    version_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION")
    try:
        with open(version_file, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return "0.0.0-dev"


def get_resolve_objects():
    """
    Retourne (resolve, project, media_pool) ou lève RuntimeError.

    Import manuel de DaVinciResolveScript avec fallback sur les deux chemins
    de modules connus — approche retenue plutôt que la variable globale
    `resolve` injectée par Resolve, pour que la connexion fonctionne de façon
    identique que le code tourne dans le script lancé directement ou dans un
    module importé par celui-ci (l'injection de globale ne traverse pas les
    frontières d'import).
    """
    # La variante courante est insérée en dernier, donc en tête de sys.path : quand
    # les deux Resolve cohabitent, on importe le DaVinciResolveScript de la bonne.
    order = sorted(PATHS, key=lambda v: v == RESOLVE_VARIANT)
    for v in order:
        p = PATHS[v]["modules"]
        if p not in sys.path:
            sys.path.insert(0, p)

    try:
        import DaVinciResolveScript as dvr
    except ImportError:
        raise RuntimeError(
            "Le module DaVinciResolveScript est introuvable.\n"
            "Lance ce script depuis Workspace > Scripts dans DaVinci Resolve."
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


# ---------------------------------------------------------------------------
# Logging fichier
# ---------------------------------------------------------------------------
LOG_ROOT = os.path.join(REAL_HOME, "Logs", "PM-Suite")


def write_log(tool_name, lines):
    """
    Écrit `lines` (liste de str) dans un fichier horodaté sous
    ~/Logs/PM-Suite/<tool_name>/. Retourne le chemin du log écrit.
    """
    log_dir = os.path.join(LOG_ROOT, tool_name)
    os.makedirs(log_dir, exist_ok=True)
    horodatage = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    chemin = os.path.join(log_dir, f"{horodatage}.log")
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(f"{tool_name} – exécution du {datetime.now().isoformat()}\n")
        f.write("=" * 60 + "\n")
        for ligne in lines:
            f.write(str(ligne) + "\n")
    return chemin


def write_error_log(tool_name, exc):
    """Raccourci pour logger une exception non gérée. Retourne le chemin du log."""
    import traceback
    lines = [f"ERREUR : {exc}", "", "Traceback :", traceback.format_exc()]
    return write_log(tool_name, lines)


# ---------------------------------------------------------------------------
# Thème d'interface partagé
# ---------------------------------------------------------------------------
class Theme:
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


def style_ttk(root):
    """Applique le thème dark aux widgets ttk (Combobox, Treeview) utilisés par la suite."""
    s = ttk.Style(root)
    s.theme_use("clam")

    s.configure("TCombobox",
                fieldbackground=Theme.PANEL_BG, background=Theme.PANEL_BG,
                foreground=Theme.FG, selectbackground=Theme.ACCENT,
                selectforeground="white", bordercolor=Theme.BORDER,
                arrowcolor=Theme.FG_DIM, relief="flat")
    s.map("TCombobox", fieldbackground=[("readonly", Theme.PANEL_BG)])

    s.configure("Treeview", background=Theme.PANEL_BG, foreground=Theme.FG,
                fieldbackground=Theme.PANEL_BG, rowheight=24, borderwidth=0)
    s.configure("Treeview.Heading", background=Theme.BORDER, foreground=Theme.FG,
                relief="flat")
    s.map("Treeview", background=[("selected", Theme.ACCENT)])

    s.configure("TNotebook", background=Theme.DARK_BG, borderwidth=0)
    s.configure("TNotebook.Tab", background=Theme.PANEL_BG, foreground=Theme.FG,
                padding=(12, 6), borderwidth=0)
    s.map("TNotebook.Tab",
          background=[("selected", Theme.ACCENT)],
          foreground=[("selected", "#0a0a10")])

    s.configure("TLabelframe", background=Theme.DARK_BG, foreground=Theme.FG,
                bordercolor=Theme.BORDER)
    s.configure("TLabelframe.Label", background=Theme.DARK_BG, foreground=Theme.FG_DIM,
                font=Theme.FONT_SM)
    s.configure("TFrame", background=Theme.DARK_BG)
    s.configure("TLabel", background=Theme.DARK_BG, foreground=Theme.FG)
    s.configure("TButton", background=Theme.PANEL_BG, foreground=Theme.FG,
                bordercolor=Theme.BORDER, relief="flat", padding=6)
    s.map("TButton", background=[("active", Theme.ACCENT_HO)])
    s.configure("TCheckbutton", background=Theme.DARK_BG, foreground=Theme.FG)
    s.configure("TRadiobutton", background=Theme.DARK_BG, foreground=Theme.FG)
    s.configure("TEntry", fieldbackground=Theme.PANEL_BG, foreground=Theme.FG,
                bordercolor=Theme.BORDER, insertcolor=Theme.ACCENT)


class PMWindow(tk.Toplevel):
    """
    Fenêtre de base pour les outils de la PM Suite : header uniforme,
    helpers de layout (section, entry avec placeholder, checkbox, bouton)
    et zone de log taguée. Les outils héritent de cette classe et
    n'implémentent que leur contenu propre dans `_build_content(main)`.

    Toujours un tk.Toplevel (jamais tk.Tk) : PM-Suite.py est l'unique
    fenêtre racine de l'app, chaque outil s'ouvre comme fenêtre enfant
    dans la même boucle d'événements — voir run_app().
    """

    def __init__(self, master, title, subtitle=None):
        super().__init__(master)
        self.title(title)
        self.resizable(True, True)
        self.configure(bg=Theme.DARK_BG)
        style_ttk(self)
        self._build_header(title.upper(), subtitle)
        self.main = tk.Frame(self, bg=Theme.DARK_BG, padx=20, pady=20)
        self.main.pack(fill="both", expand=True)
        self._build_content(self.main)
        self._center()
        # Taille initiale = taille minimale : on peut agrandir, pas écraser le contenu.
        self.minsize(self.winfo_width(), self.winfo_height())

    # -- à surcharger par les sous-classes ---------------------------------
    def _build_content(self, main):
        raise NotImplementedError

    # -- layout --------------------------------------------------------------
    def _center(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

    def _build_header(self, label, subtitle):
        hdr = tk.Frame(self, bg="#111116", pady=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text=f"⬡  {label}", font=(Theme.FONT_UI[0], 13, "bold"),
                 bg="#111116", fg=Theme.ACCENT).pack(side="left", padx=20)
        if subtitle:
            tk.Label(hdr, text=subtitle, font=Theme.FONT_SM,
                     bg="#111116", fg=Theme.FG_DIM).pack(side="right", padx=20)

    def section(self, parent, label):
        tk.Label(parent, text=label, font=(Theme.FONT_UI[0], 9, "bold"),
                  bg=Theme.DARK_BG, fg=Theme.FG_DIM).pack(anchor="w", pady=(10, 2))

    def entry(self, parent, var, placeholder=""):
        e = tk.Entry(parent, textvariable=var, font=Theme.FONT_MONO,
                     bg=Theme.PANEL_BG, fg=Theme.FG, bd=0, relief="flat",
                     insertbackground=Theme.ACCENT,
                     highlightbackground=Theme.BORDER, highlightthickness=1,
                     highlightcolor=Theme.ACCENT)
        e.pack(fill="x", ipady=7, padx=1, pady=(0, 2))
        if placeholder:
            e.insert(0, placeholder)
            e.config(fg=Theme.FG_DIM)

            def on_focus_in(_ev):
                if e.get() == placeholder:
                    e.delete(0, "end")
                    e.config(fg=Theme.FG)

            def on_focus_out(_ev):
                if not e.get():
                    e.insert(0, placeholder)
                    e.config(fg=Theme.FG_DIM)

            e.bind("<FocusIn>", on_focus_in)
            e.bind("<FocusOut>", on_focus_out)
        return e

    def checkbox(self, parent, label, var, row=0, col=0):
        cb = tk.Checkbutton(parent, text=label, variable=var,
                             bg=Theme.DARK_BG, fg=Theme.FG,
                             activebackground=Theme.DARK_BG, activeforeground=Theme.FG,
                             selectcolor=Theme.PANEL_BG, font=Theme.FONT_SM, bd=0)
        cb.grid(row=row, column=col, sticky="w", padx=(0, 20), pady=2)
        return cb

    def button(self, parent, label, color, cmd, side="left", padx_l=0):
        b = tk.Button(parent, text=label, font=(Theme.FONT_UI[0], 10, "bold"),
                      bg=color, fg="#0a0a10" if color != Theme.FG_DIM else Theme.DARK_BG,
                      activebackground=Theme.ACCENT_HO, relief="flat", bd=0,
                      padx=18, pady=8, cursor="hand2", command=cmd)
        b.pack(side=side, padx=(padx_l, 0))
        return b

    def build_log(self, parent, height=14, expanded=False):
        """
        Construit une zone de log taguée, repliable (clic sur l'en-tête « LOG »), et
        retourne le widget tk.Text. Repliée par défaut ; elle s'ouvre toute seule dès
        qu'une ligne d'erreur (tag "err") y est écrite, pour ne jamais cacher un échec.
        """
        sep = tk.Frame(parent, bg=Theme.BORDER, height=1)
        sep.pack(fill="x", pady=(16, 0))

        log_hdr = tk.Frame(parent, bg=Theme.DARK_BG, cursor="hand2")
        log_hdr.pack(fill="x", pady=(8, 4))
        arrow = tk.Label(log_hdr, font=(Theme.FONT_UI[0], 10, "bold"),
                          bg=Theme.DARK_BG, fg=Theme.FG_DIM, cursor="hand2")
        arrow.pack(side="left")

        log_frame = tk.Frame(parent, bg=Theme.PANEL_BG, bd=0,
                              highlightbackground=Theme.BORDER, highlightthickness=1)

        log = tk.Text(log_frame, bg=Theme.PANEL_BG, fg=Theme.FG,
                       font=Theme.FONT_MONO, bd=0, relief="flat",
                       width=66, height=height, wrap="none",
                       insertbackground=Theme.ACCENT, selectbackground=Theme.ACCENT)
        log.pack(side="left", fill="both", expand=True, padx=8, pady=8)

        sb = tk.Scrollbar(log_frame, command=log.yview, bg=Theme.PANEL_BG,
                           troughcolor=Theme.PANEL_BG, bd=0, relief="flat")
        sb.pack(side="right", fill="y")
        log.config(yscrollcommand=sb.set)

        state = {"open": False}

        def set_open(opened):
            state["open"] = opened
            arrow.config(text=("▾  LOG" if opened else "▸  LOG"))
            if opened:
                log_frame.pack(fill="both", expand=True, after=log_hdr)
                top = log.winfo_toplevel()
                top.update_idletasks()
                if top.winfo_reqheight() > top.winfo_height():     # fait grandir la fenêtre au besoin
                    top.geometry(f"{top.winfo_width()}x{top.winfo_reqheight()}")
            else:
                log_frame.pack_forget()

        for w in (log_hdr, arrow):
            w.bind("<Button-1>", lambda e: set_open(not state["open"]))
        log._pm_set_open = set_open
        set_open(expanded)

        log.tag_config("dim", foreground=Theme.FG_DIM)
        log.tag_config("ok", foreground=Theme.SUCCESS)
        log.tag_config("warn", foreground=Theme.WARNING)
        log.tag_config("err", foreground=Theme.DANGER)
        log.tag_config("accent", foreground=Theme.ACCENT)
        log.tag_config("header", foreground=Theme.FG,
                        font=(Theme.FONT_MONO[0], Theme.FONT_MONO[1], "bold"))
        return log

    @staticmethod
    def log_write(log_widget, text, tag=""):
        log_widget.config(state="normal")
        log_widget.insert("end", text, tag) if tag else log_widget.insert("end", text)
        log_widget.see("end")
        log_widget.config(state="disabled")
        if tag == "err" and hasattr(log_widget, "_pm_set_open"):
            log_widget._pm_set_open(True)       # une erreur ne reste jamais cachée

    @staticmethod
    def log_clear(log_widget):
        log_widget.config(state="normal")
        log_widget.delete("1.0", "end")
        log_widget.config(state="disabled")


# ---------------------------------------------------------------------------
# Sélecteur de fichier
# ---------------------------------------------------------------------------
def pick_file(title="Choisir un fichier", extensions=None, parent=None):
    """
    Ouvre un sélecteur de fichier et retourne le chemin choisi, ou "" si annulé
    ou indisponible.

    Le dialogue Tk natif (filedialog) ne s'affiche pas de façon fiable dans le
    Python embarqué de Resolve sur macOS (retour vide sans erreur). On passe donc
    d'abord par le sélecteur système via osascript, puis en dernier recours par
    filedialog. `extensions` : liste sans point, ex. ["csv"].
    """
    import subprocess
    if sys.platform == "darwin":
        script = f'POSIX path of (choose file with prompt "{title}"'
        if extensions:
            script += " of type {" + ", ".join(f'"{e}"' for e in extensions) + "}"
        script += ")"
        try:
            r = subprocess.run(["osascript", "-e", script], capture_output=True,
                               text=True, timeout=600)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
            if "-128" in r.stderr:      # annulé par l'utilisateur
                return ""
        except (OSError, subprocess.SubprocessError):
            pass
    from tkinter import filedialog
    try:
        types = [("Fichiers", " ".join(f"*.{e}" for e in extensions))] if extensions else []
        return filedialog.askopenfilename(title=title, parent=parent,
                                          filetypes=types + [("Tous les fichiers", "*.*")]) or ""
    except Exception:
        return ""


def pick_folder(title="Choisir un dossier", parent=None):
    """
    Sélecteur de dossier : même logique que pick_file (osascript d'abord, car
    filedialog ne s'affiche pas de façon fiable dans Resolve). Retourne "" si
    annulé ou indisponible.
    """
    import subprocess
    if sys.platform == "darwin":
        script = f'POSIX path of (choose folder with prompt "{title}")'
        try:
            r = subprocess.run(["osascript", "-e", script], capture_output=True,
                               text=True, timeout=600)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip().rstrip("/") or "/"
            if "-128" in r.stderr:      # annulé par l'utilisateur
                return ""
        except (OSError, subprocess.SubprocessError):
            pass
    from tkinter import filedialog
    try:
        return filedialog.askdirectory(title=title, parent=parent) or ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Boucle d'événements
# ---------------------------------------------------------------------------
def run_app(root):
    """
    Fait tourner `root` (tk.Tk) via une boucle d'update manuelle plutôt que
    root.mainloop(). Retenu pour toute la suite (au lieu du mainloop()
    bloquant utilisé par 3 des 4 scripts d'origine) pour éviter tout risque
    de geler l'interface de Resolve, comme le faisait déjà bin_builder.py.
    """
    try:
        while True:
            root.update_idletasks()
            root.update()
    except tk.TclError:
        pass  # fenêtre fermée — sortie propre
