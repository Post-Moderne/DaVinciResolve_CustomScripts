#!/usr/bin/env python3
"""
Resolve CSV → Start TC
=======================
Charge un fichier .csv (colonnes "Name" et "Start") et met à jour le
Start TC des clips du Media Pool dont le "Clip Name" correspond à "Name".

Lance depuis : Workspaces > Scripts > Utility

Compatibilité : DaVinci Resolve 18+

INSTALLATION
─────────────
App Store (sandbox) :
  ~/Library/Containers/com.blackmagic-design.DaVinciResolveAppStore/Data/Library/Application Support/Fusion/Scripts/Utility/

DMG (standard) :
  /Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/

Ce script détecte automatiquement la variante active au lancement.

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
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# ── Détection du vrai home (contourne le sandbox App Store) ───────────────────
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
    for variant, p in _PATHS.items():
        if os.path.isdir(p["scripts"]):
            return variant
    return "unknown"


RESOLVE_VARIANT = _resolve_variant()


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
    if resolve is None:
        raise RuntimeError("Impossible de se connecter à Resolve.")

    project_manager = resolve.GetProjectManager()
    project = project_manager.GetCurrentProject()
    if project is None:
        raise RuntimeError("Aucun projet ouvert dans Resolve.")

    media_pool = project.GetMediaPool()
    return resolve, project, media_pool


# ── Parcours récursif du Media Pool ────────────────────────────────────────────
def collect_all_clips(folder, out_list):
    """Ajoute récursivement tous les MediaPoolItem de folder (et sous-bins) dans out_list."""
    clips = folder.GetClipList() or []
    out_list.extend(clips)
    for sub in (folder.GetSubFolderList() or []):
        collect_all_clips(sub, out_list)


def build_name_index(all_clips):
    """
    Retourne dict: nom_clip -> liste de MediaPoolItem (pour repérer les doublons).
    """
    index = {}
    for clip in all_clips:
        try:
            name = clip.GetClipProperty("Clip Name") or clip.GetName()
        except Exception:
            name = clip.GetName()
        index.setdefault(name, []).append(clip)
    return index


# ── Lecture CSV ────────────────────────────────────────────────────────────────
def read_csv_rows(path):
    """
    Retourne une liste de tuples (name, start_tc) depuis le CSV.
    Détecte automatiquement , ou ; comme délimiteur.
    Lève ValueError si les colonnes "Name" ou "Start" sont absentes.
    """
    with open(path, newline="", encoding="utf-8-sig") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(f, dialect=dialect)

        fieldnames = reader.fieldnames or []
        norm = {fn.strip().lower(): fn for fn in fieldnames}
        if "name" not in norm or "start" not in norm:
            raise ValueError(
                f"Colonnes requises introuvables. Colonnes détectées : {fieldnames}\n"
                "Le CSV doit contenir une colonne 'Name' et une colonne 'Start'."
            )
        name_col = norm["name"]
        start_col = norm["start"]

        rows = []
        for row in reader:
            name = (row.get(name_col) or "").strip()
            start = (row.get(start_col) or "").strip()
            if name:
                rows.append((name, start))
        return rows


# ── Application GUI ────────────────────────────────────────────────────────────
class App(tk.Tk):
    BG = "#1e1e1e"
    FG = "#e0e0e0"
    ACCENT = "#3a7ca5"
    ROW_OK = "#1e1e1e"
    ROW_DUP = "#4a3a1a"
    ROW_MISSING = "#4a1a1a"
    ROW_FAIL = "#5a1a1a"

    def __init__(self):
        super().__init__()
        self.title("Resolve CSV → Start TC")
        self.geometry("980x620")
        self.configure(bg=self.BG)

        self.csv_rows = []          # [(name, start_tc), ...]
        self.name_index = {}        # nom -> [MediaPoolItem, ...]
        self.plan = []              # lignes préparées pour preview/apply

        self._build_ui()
        self._init_resolve()

    # ---------------------------------------------------------------- UI
    def _build_ui(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Treeview", background="#2a2a2a", foreground=self.FG,
                         fieldbackground="#2a2a2a", rowheight=24)
        style.configure("Treeview.Heading", background="#3a3a3a", foreground=self.FG)
        style.map("Treeview", background=[("selected", self.ACCENT)])

        top = tk.Frame(self, bg=self.BG)
        top.pack(fill="x", padx=10, pady=8)

        tk.Label(top, text="Chemin CSV :", bg=self.BG, fg=self.FG).pack(side="left")

        self.path_var = tk.StringVar()
        self.entry_path = tk.Entry(top, textvariable=self.path_var, bg="#2a2a2a",
                                    fg=self.FG, insertbackground=self.FG, relief="flat",
                                    width=55)
        self.entry_path.pack(side="left", padx=6, ipady=3)
        # Entrée (Enter) dans le champ = charger directement
        self.entry_path.bind("<Return>", lambda e: self.on_load_csv())

        self.btn_browse = tk.Button(top, text="Parcourir...", command=self.on_browse,
                                     bg="#333", fg=self.FG, relief="flat", padx=8, pady=4)
        self.btn_browse.pack(side="left", padx=(0, 6))

        self.btn_load = tk.Button(top, text="Charger", command=self.on_load_csv,
                                   bg="#333", fg=self.FG, relief="flat", padx=10, pady=4)
        self.btn_load.pack(side="left")

        self.btn_apply = tk.Button(top, text="Appliquer", command=self.on_apply,
                                    bg=self.ACCENT, fg="white", relief="flat",
                                    padx=10, pady=4, state="disabled")
        self.btn_apply.pack(side="right")

        status_row = tk.Frame(self, bg=self.BG)
        status_row.pack(fill="x", padx=10)
        self.lbl_csv = tk.Label(status_row, text="Aucun CSV chargé", bg=self.BG, fg=self.FG)
        self.lbl_csv.pack(side="left")

        # Tableau preview
        columns = ("name", "old_tc", "new_tc", "status")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=18)
        headers = {"name": "Clip Name", "old_tc": "Start TC actuel",
                   "new_tc": "Start TC (CSV)", "status": "Statut"}
        widths = {"name": 320, "old_tc": 160, "new_tc": 160, "status": 260}
        for col in columns:
            self.tree.heading(col, text=headers[col])
            self.tree.column(col, width=widths[col], anchor="w")
        self.tree.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        self.tree.tag_configure("ok", background=self.ROW_OK)
        self.tree.tag_configure("dup", background=self.ROW_DUP)
        self.tree.tag_configure("missing", background=self.ROW_MISSING)
        self.tree.tag_configure("fail", background=self.ROW_FAIL)

        # Log
        log_frame = tk.Frame(self, bg=self.BG)
        log_frame.pack(fill="both", expand=False, padx=10, pady=(0, 10))
        tk.Label(log_frame, text="Log", bg=self.BG, fg=self.FG).pack(anchor="w")
        self.log = tk.Text(log_frame, height=8, bg="#111", fg="#9fdf9f",
                            insertbackground=self.FG, relief="flat")
        self.log.pack(fill="both", expand=True)

    def _log(self, msg):
        self.log.insert("end", msg + "\n")
        self.log.see("end")

    # ---------------------------------------------------------- Resolve init
    def _init_resolve(self):
        try:
            self.resolve, self.project, self.media_pool = get_resolve_objects()
            self._log(f"Connecté à Resolve (variante détectée : {RESOLVE_VARIANT}).")
            self._log(f"Projet actif : {self.project.GetName()}")
        except Exception as e:
            messagebox.showerror("Erreur de connexion", str(e))
            self.resolve = self.project = self.media_pool = None

    # ---------------------------------------------------------------- Parcourir (fallback)
    def on_browse(self):
        """Tente d'ouvrir le dialogue natif. Dans l'environnement sandboxé de Resolve,
        ce dialogue peut échouer silencieusement ou planter — on protège l'appel et on
        retombe sur la saisie manuelle du chemin si besoin."""
        try:
            path = filedialog.askopenfilename(
                title="Choisir le fichier CSV",
                filetypes=[("CSV", "*.csv"), ("Tous les fichiers", "*.*")]
            )
        except Exception as e:
            self._log(f"[INFO] Le dialogue natif a échoué ({e}). "
                       "Colle le chemin du CSV directement dans le champ ci-dessus.")
            return

        if path:
            self.path_var.set(path)
            self.on_load_csv()
        else:
            self._log("[INFO] Aucun fichier sélectionné (ou dialogue non supporté ici). "
                       "Colle le chemin du CSV directement dans le champ ci-dessus.")

    # ---------------------------------------------------------------- Charger CSV
    def on_load_csv(self):
        if self.media_pool is None:
            messagebox.showerror("Erreur", "Pas de connexion active à Resolve.")
            return

        raw_path = self.path_var.get().strip()
        # Nettoyage : guillemets ajoutés par un glisser-déposer depuis le Finder,
        # espaces d'échappement "\ " ajoutés par certains terminaux/Finder
        path = raw_path.strip('"').strip("'").replace("\\ ", " ")
        path = os.path.expanduser(path)

        if not path:
            messagebox.showwarning("Chemin manquant", "Colle ou choisis d'abord le chemin du CSV.")
            return

        if not os.path.isfile(path):
            messagebox.showerror("Fichier introuvable", f"Aucun fichier à ce chemin :\n{path}")
            self._log(f"[ERREUR] Fichier introuvable : {path}")
            return

        try:
            self.csv_rows = read_csv_rows(path)
        except Exception as e:
            messagebox.showerror("Erreur de lecture CSV", str(e))
            return

        self.lbl_csv.config(text=os.path.basename(path))
        self._log(f"\nCSV chargé : {path} ({len(self.csv_rows)} lignes)")

        # Indexer les clips du Media Pool (tous les bins, récursivement)
        all_clips = []
        collect_all_clips(self.media_pool.GetRootFolder(), all_clips)
        self.name_index = build_name_index(all_clips)
        self._log(f"{len(all_clips)} clips trouvés dans le Media Pool (tous bins confondus).")

        self._build_plan()

    # ---------------------------------------------------------------- Plan / preview
    def _build_plan(self):
        self.tree.delete(*self.tree.get_children())
        self.plan = []

        n_ok, n_dup, n_missing = 0, 0, 0

        for name, new_tc in self.csv_rows:
            matches = self.name_index.get(name, [])

            if len(matches) == 0:
                self.tree.insert("", "end", values=(name, "-", new_tc, "Introuvable dans le Media Pool"),
                                  tags=("missing",))
                self._log(f"[NON TROUVÉ] '{name}' — aucun clip correspondant dans le Media Pool.")
                n_missing += 1
                continue

            if len(matches) > 1:
                self.tree.insert("", "end", values=(name, "-", new_tc,
                                  f"Doublon ({len(matches)} clips) — ignoré"),
                                  tags=("dup",))
                self._log(f"[DOUBLON] '{name}' — {len(matches)} clips portent ce nom, ligne ignorée.")
                n_dup += 1
                continue

            clip = matches[0]
            try:
                old_tc = clip.GetClipProperty("Start TC") or ""
            except Exception:
                old_tc = ""

            self.tree.insert("", "end", values=(name, old_tc, new_tc, "Prêt"), tags=("ok",))
            self.plan.append({"clip": clip, "name": name, "old_tc": old_tc, "new_tc": new_tc})
            n_ok += 1

        self._log(f"\nRésumé preview : {n_ok} prêt(s), {n_dup} doublon(s) ignoré(s), "
                   f"{n_missing} introuvable(s).")

        self.btn_apply.config(state="normal" if n_ok > 0 else "disabled")

    # ---------------------------------------------------------------- Apply
    def on_apply(self):
        if not self.plan:
            return

        if not messagebox.askyesno(
            "Confirmer",
            f"Appliquer le nouveau Start TC sur {len(self.plan)} clip(s) ?\n"
            "Cette action passe par l'historique d'annulation de Resolve (undo standard)."
        ):
            return

        n_success, n_fail = 0, 0
        self._log("\n── Application ──")

        for item in self.plan:
            clip = item["clip"]
            name = item["name"]
            new_tc = item["new_tc"]

            try:
                clip.SetClipProperty("Start TC", new_tc)
            except Exception as e:
                self._log(f"[ÉCHEC] '{name}' — exception à l'écriture : {e}")
                n_fail += 1
                self._mark_row(name, "fail", f"Échec (exception : {e})")
                continue

            # Relecture pour confirmer que le changement a réellement pris effet
            try:
                confirmed_tc = clip.GetClipProperty("Start TC") or ""
            except Exception:
                confirmed_tc = ""

            if confirmed_tc.strip() == new_tc.strip():
                self._log(f"[OK] '{name}' — Start TC mis à jour : {item['old_tc']} → {confirmed_tc}")
                n_success += 1
                self._mark_row(name, "ok", f"Appliqué ({confirmed_tc})")
            else:
                self._log(f"[ÉCHEC] '{name}' — écriture non confirmée "
                          f"(attendu '{new_tc}', lu '{confirmed_tc}'). "
                          "Probable rejet Resolve (média avec TC embarqué).")
                n_fail += 1
                self._mark_row(name, "fail",
                                f"Rejeté par Resolve (lu : {confirmed_tc or 'vide'})")

        self._log(f"\nTerminé : {n_success} succès, {n_fail} échec(s).")
        messagebox.showinfo(
            "Terminé",
            f"{n_success} clip(s) mis à jour avec succès.\n{n_fail} échec(s) — voir le log."
        )

    def _mark_row(self, name, tag, status_text):
        for iid in self.tree.get_children():
            values = self.tree.item(iid, "values")
            if values[0] == name:
                new_values = (values[0], values[1], values[2], status_text)
                self.tree.item(iid, values=new_values, tags=(tag,))
                break


if __name__ == "__main__":
    app = App()
    app.mainloop()