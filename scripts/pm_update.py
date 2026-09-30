#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pm_update – Post-Moderne
==========================

Mise à jour de la PM Suite depuis le repo GitHub public. Ouvert depuis le
bouton « Mises à jour… » du lanceur (PM-Suite.py).

Principe : on compare scripts/VERSION (installé) à celui de la branche main
sur GitHub ; si le distant est plus récent on télécharge le zip du repo et on
recopie PM-Suite.py (Scripts/Utility) puis pm_common.py, VERSION et pm_tools/
(dossier Modules). Les fichiers remplacés sont sauvegardés dans
<Modules>/.pm_suite_backup/ et restaurés automatiquement si la copie échoue.

Pour publier une mise à jour : incrémenter scripts/VERSION, committer, pousser.
Sans incrément de VERSION, les postes ne voient rien de nouveau.

Les téléchargements passent par curl (certificats du système) : le Python
embarqué de Resolve n'embarque pas toujours de bundle de certificats.
"""

import os
import sys
import glob
import shutil
import subprocess
import tempfile
import zipfile
import tkinter as tk
from tkinter import messagebox

import pm_common
from pm_common import PMWindow, Theme

TOOL_NAME = "PM-Update"
REPO = "Post-Moderne/DaVinciResolve_CustomScripts"
BRANCH = "main"
# Surchargeables pour tester hors GitHub (file:///…).
VERSION_URL = os.environ.get("PM_UPDATE_VERSION_URL",
                             f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/scripts/VERSION")
API_VERSION_URL = f"https://api.github.com/repos/{REPO}/contents/scripts/VERSION?ref={BRANCH}"
ZIP_URL = os.environ.get("PM_UPDATE_ZIP_URL",
                         f"https://codeload.github.com/{REPO}/zip/refs/heads/{BRANCH}")

BACKUP_DIR = ".pm_suite_backup"
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")


# ── Versions ───────────────────────────────────────────────────────────────────
def parse_version(v):
    """'1.2.3' (ou '1.2.3-dev') → (1, 2, 3). Lève ValueError si illisible."""
    core = (v or "").strip().split("-")[0]
    parts = core.split(".")
    if not parts or not all(p.isdigit() for p in parts):
        raise ValueError(f"Version illisible : '{v}'")
    return tuple(int(p) for p in parts)


def is_newer(remote, local):
    return parse_version(remote) > parse_version(local)


# ── Réseau (curl) ──────────────────────────────────────────────────────────────
def _curl(url, dest=None, headers=()):
    cmd = ["curl", "-fsSL", "--max-time", "120"]
    for h in headers:
        cmd += ["-H", h]
    cmd.append(url)
    if dest:
        cmd += ["-o", dest]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=150)
    except (OSError, subprocess.SubprocessError) as e:
        raise RuntimeError(f"curl indisponible ou expiré : {e}")
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"Téléchargement impossible (curl {r.returncode}) : {err or url}")
    return r.stdout


def fetch_remote_version():
    """
    Lit scripts/VERSION sur GitHub. On passe par l'API (cache 60 s) plutôt que par
    raw.githubusercontent.com dont le cache peut garder une ancienne valeur
    plusieurs minutes après un push ; raw reste le secours si l'API est injoignable
    ou saturée (60 requêtes/h par IP).
    """
    if "PM_UPDATE_VERSION_URL" in os.environ:          # tests hors GitHub
        return _curl(VERSION_URL).decode("utf-8").strip()
    try:
        out = _curl(API_VERSION_URL, headers=["Accept: application/vnd.github.raw"])
        parse_version(out.decode("utf-8"))             # refuse une réponse inattendue
        return out.decode("utf-8").strip()
    except (RuntimeError, ValueError):
        return _curl(VERSION_URL).decode("utf-8").strip()


def download_source(tmp_dir):
    """Télécharge et extrait le repo ; retourne le chemin de son dossier scripts/."""
    zpath = os.path.join(tmp_dir, "repo.zip")
    _curl(ZIP_URL, zpath)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(tmp_dir)
    found = glob.glob(os.path.join(tmp_dir, "*", "scripts", "PM-Suite.py"))
    if not found:
        raise RuntimeError("Archive inattendue : scripts/PM-Suite.py introuvable.")
    return os.path.dirname(found[0])


# ── Application ────────────────────────────────────────────────────────────────
def apply_update(src, utility_dir, modules_dir):
    """
    Copie les fichiers de `src` (dossier scripts/ du repo) vers les dossiers
    d'installation, avec sauvegarde et restauration en cas d'échec.
    """
    for name in ("PM-Suite.py", "pm_common.py", "pm_update.py", "VERSION", "pm_tools"):
        if not os.path.exists(os.path.join(src, name)):
            raise RuntimeError(f"Source incomplète : {name} manquant.")
    for d in (utility_dir, modules_dir):
        os.makedirs(d, exist_ok=True)
        if not os.access(d, os.W_OK):
            raise PermissionError(
                f"Pas le droit d'écrire dans :\n{d}\n"
                "Relance l'installeur (Install-PM-Suite.command), qui demande le mot de passe admin.")

    # (nom, dossier cible) — PM-Suite.py va dans Utility, le reste dans Modules.
    targets = [("PM-Suite.py", utility_dir)] + [
        (n, modules_dir) for n in ("pm_common.py", "pm_update.py", "VERSION", "pm_tools")]

    backup = os.path.join(modules_dir, BACKUP_DIR)
    shutil.rmtree(backup, ignore_errors=True)
    os.makedirs(backup)
    saved = []
    try:
        for name, dest_dir in targets:
            cur = os.path.join(dest_dir, name)
            if os.path.exists(cur):
                bak = os.path.join(backup, name)
                shutil.copytree(cur, bak) if os.path.isdir(cur) else shutil.copy2(cur, bak)
                saved.append((name, dest_dir))
        for name, dest_dir in targets:
            s, d = os.path.join(src, name), os.path.join(dest_dir, name)
            if os.path.isdir(s):
                shutil.rmtree(d, ignore_errors=True)
                shutil.copytree(s, d, ignore=IGNORE)
            else:
                shutil.copy2(s, d)
    except Exception:
        for name, dest_dir in saved:   # restauration
            d, bak = os.path.join(dest_dir, name), os.path.join(backup, name)
            if os.path.isdir(bak):
                shutil.rmtree(d, ignore_errors=True)
                shutil.copytree(bak, d)
            else:
                shutil.copy2(bak, d)
        raise


# ── Fenêtre ────────────────────────────────────────────────────────────────────
class UpdateWindow(PMWindow):
    def __init__(self, master):
        self.remote = None
        super().__init__(master, "Mises à jour", f"Resolve  ·  {pm_common.RESOLVE_VARIANT}")

    def _build_content(self, main):
        grid = tk.Frame(main, bg=Theme.DARK_BG)
        grid.pack(fill="x")
        self.lbl_local = self._row(grid, 0, "Version installée", f"v{pm_common.get_version()}")
        self.lbl_remote = self._row(grid, 1, "Dernière version", "—")

        btns = tk.Frame(main, bg=Theme.DARK_BG)
        btns.pack(fill="x", pady=(14, 0))
        self.btn_check = self.button(btns, "Vérifier", Theme.PANEL_BG, self.on_check, side="left")
        self.btn_install = self.button(btns, "Installer la mise à jour", Theme.SUCCESS,
                                        self.on_install, side="right")
        self.btn_install.config(state="disabled")

        self.log = self.build_log(main, height=8)
        self.log_write(self.log, "Clique sur « Vérifier » pour interroger GitHub.\n", "dim")

    def _row(self, parent, r, label, value):
        tk.Label(parent, text=label, bg=Theme.DARK_BG, fg=Theme.FG_DIM,
                 font=Theme.FONT_SM).grid(row=r, column=0, sticky="w", pady=2)
        lbl = tk.Label(parent, text=value, bg=Theme.DARK_BG, fg=Theme.FG,
                       font=(Theme.FONT_UI[0], 12, "bold"))
        lbl.grid(row=r, column=1, sticky="w", padx=(20, 0), pady=2)
        return lbl

    def on_check(self):
        self.btn_install.config(state="disabled")
        self.log_write(self.log, "\nInterrogation de GitHub…\n", "dim")
        self.update_idletasks()
        try:
            self.remote = fetch_remote_version()
            newer = is_newer(self.remote, pm_common.get_version())
        except Exception as e:
            self.log_write(self.log, f"[ERREUR] {e}\n", "err")
            self.lbl_remote.config(text="indisponible")
            return
        self.lbl_remote.config(text=f"v{self.remote}")
        if newer:
            self.log_write(self.log, f"Mise à jour disponible : v{self.remote}.\n", "accent")
            self.btn_install.config(state="normal")
        else:
            self.log_write(self.log, "Tu as déjà la dernière version.\n", "ok")

    def on_install(self):
        if not messagebox.askyesno("Mise à jour", f"Installer la v{self.remote} ?\n"
                                   "Relance ensuite PM-Suite pour l'utiliser.", parent=self):
            return
        self.log_write(self.log, "\nTéléchargement…\n", "dim")
        self.update_idletasks()
        try:
            paths = pm_common.install_paths()
            with tempfile.TemporaryDirectory() as tmp:
                src = download_source(tmp)
                apply_update(src, paths["utility"], paths["modules"])
        except Exception as e:
            log = pm_common.write_error_log(TOOL_NAME, e)
            self.log_write(self.log, f"[ERREUR] {e}\nLog : {log}\n", "err")
            messagebox.showerror("Mise à jour", f"Échec (fichiers précédents conservés) :\n{e}", parent=self)
            return
        self.btn_install.config(state="disabled")
        self.log_write(self.log, f"Installé : v{self.remote}. Ferme et relance PM-Suite.\n", "ok")
        messagebox.showinfo("Mise à jour", f"v{self.remote} installée.\nFerme et relance PM-Suite.", parent=self)


def open_window(master):
    return UpdateWindow(master)
