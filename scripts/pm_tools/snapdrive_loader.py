#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SnapDrive Loader — analyse les timelines (clips offline d'un import XML/AAF) et les
croise avec les SnapDrive (.html) pour savoir quelle source se trouve sur quel disque.
Module interne de la PM Suite (voir PM-Suite.py).

FONCTIONNEMENT
───────────────
1. Le dossier des SnapDrive est parsé en index (snapdrive.py).
2. Les timelines cochées sont lues sur toutes leurs pistes vidéo (nom du timeline item :
   un XML/AAF non relinké ne crée pas de media pool item), filtrées par couleur de timeline item (snapdrive_analysis.py fait le match :
   nom du clip == nom du fichier sans extension, exact, insensible à la casse).
3. Le rapport groupe les sources par disque (pull list), liste les introuvables, les
   doublons (source sur plusieurs disques) et les éléments ignorés. Export CSV.

« Analyser » est strictement en lecture seule : seuls des getters de l'API Resolve
sont appelés, aucune timeline ni aucun clip n'est modifié.

4. « Importer les disques montés » importe les sources des disques branchés dans le bin
   _SnapDrive/<DISQUE> du media pool (snapdrive_import.py), en ignorant ce qui est déjà
   dans le projet : on peut le relancer à chaque nouveau disque branché.
"""

import json
import os
import sys
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
from pm_tools import snapdrive, snapdrive_analysis as an, snapdrive_import as si

TOOL_NAME = "PM-Resolve_SnapDrive-Loader"
CONFIG_PATH = os.path.join(pm_common.LOG_ROOT, "snapdrive_loader.json")

CLIP_COLORS = ["Orange", "Apricot", "Yellow", "Lime", "Olive", "Green", "Teal", "Navy",
               "Blue", "Purple", "Violet", "Pink", "Tan", "Beige", "Brown", "Chocolate"]


# ── Config (dossier des SnapDrive, priorité des disques) ───────────────────────
def load_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


# ── Lecture des timelines (getters uniquement) ─────────────────────────────────
def read_timeline(timeline, color, types_seen=None):
    """RawItem de toutes les pistes vidéo d'une timeline, filtrés par couleur de timeline item."""
    name = timeline.GetName() or "(sans nom)"
    items = []
    for track in range(1, int(timeline.GetTrackCount("video") or 0) + 1):
        for it in timeline.GetItemListInTrack("video", track) or []:
            if color != an.ALL_COLORS and (it.GetClipColor() or "") != color:
                continue
            # Un clip offline issu d'un XML/AAF n'a pas de media pool item : le nom de référence
            # est celui du timeline item (colonne « Élément »).
            mpi = it.GetMediaPoolItem()
            ctype = (mpi.GetClipProperty("Type") or "") if mpi else ""
            clip_name = ((it.GetName() or "") or (mpi.GetName() if mpi else "") or "").strip()
            kind = an.classify(bool(mpi), ctype, clip_name)
            if types_seen is not None:
                types_seen.add(ctype or "(aucun media pool item)")
            usage = None
            if mpi and kind == "source":
                u = mpi.GetClipProperty("Usage")
                usage = str(u) if u not in (None, "") else None
            items.append(an.RawItem(name, track, clip_name, it.GetClipColor() or "", kind, usage,
                                    f"Type : {ctype}" if kind != "source" and ctype else ""))
    return items


def short_list(names, n=6):
    """'A, B, C, … (+N autres)' pour ne pas noyer une boîte de dialogue."""
    names = list(names)
    return ", ".join(names[:n]) + (f", … (+{len(names) - n} autres)" if len(names) > n else "")


class SnapDriveLoaderWindow(PMWindow):
    def __init__(self, master):
        self.index = snapdrive.SnapDriveIndex()
        self.report = None
        self.timelines = []         # noms, dans l'ordre du listbox
        self.cfg = load_config()
        self._sort = {}             # tree → (colonne, décroissant)
        self._skeys = {}            # tree → {iid: {colonne: valeur de tri}}
        self._heads = {}            # (tree, colonne) → titre d'origine
        super().__init__(master, "SnapDrive Loader",
                          f"DaVinci Resolve  ·  {pm_common.RESOLVE_VARIANT}")
        self._init_resolve()
        if self.cfg.get("folder") and os.path.isdir(self.cfg["folder"]):
            self._load_index()

    # ------------------------------------------------------------------ UI
    def _build_content(self, main):
        top = tk.Frame(main, bg=Theme.DARK_BG)
        top.pack(fill="x")
        tk.Label(top, text="SnapDrive :", bg=Theme.DARK_BG, fg=Theme.FG).pack(side="left")
        self.folder_var = tk.StringVar(value=self.cfg.get("folder", ""))
        e = tk.Entry(top, textvariable=self.folder_var, bg=Theme.PANEL_BG, fg=Theme.FG,
                      insertbackground=Theme.FG, relief="flat", width=52)
        e.pack(side="left", padx=6, ipady=3)
        e.bind("<Return>", lambda ev: self._load_index())
        self.button(top, "Parcourir…", Theme.PANEL_BG, self.on_browse, side="left")
        self.lbl_index = tk.Label(main, text="Aucun SnapDrive chargé.", bg=Theme.DARK_BG, fg=Theme.FG_DIM)
        self.lbl_index.pack(anchor="w", pady=(4, 0))

        prio = tk.Frame(main, bg=Theme.DARK_BG)
        prio.pack(fill="x", pady=(6, 0))
        tk.Label(prio, text="Priorité des disques :", bg=Theme.DARK_BG, fg=Theme.FG).pack(side="left")
        self.prio_var = tk.StringVar(value=", ".join(self.cfg.get("priority", [])))
        tk.Entry(prio, textvariable=self.prio_var, bg=Theme.PANEL_BG, fg=Theme.FG,
                  insertbackground=Theme.FG, relief="flat", width=40).pack(side="left", padx=6, ipady=3)
        tk.Label(prio, text="ex. IMT_TRNS_*, IMT_SHTL_*  (1er = préféré en cas de doublon)",
                 font=Theme.FONT_SM, bg=Theme.DARK_BG, fg=Theme.FG_DIM).pack(side="left")

        mid = tk.Frame(main, bg=Theme.DARK_BG)
        mid.pack(fill="x", pady=(10, 0))
        left = tk.Frame(mid, bg=Theme.DARK_BG)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text="Timelines à analyser (clic = cocher/décocher) :", bg=Theme.DARK_BG,
                 fg=Theme.FG_DIM, font=Theme.FONT_SM).pack(anchor="w")
        box = tk.Frame(left, bg=Theme.PANEL_BG)
        box.pack(fill="x")
        self.lst = tk.Listbox(box, selectmode="multiple", height=6, bg=Theme.PANEL_BG, fg=Theme.FG,
                              selectbackground=Theme.ACCENT, selectforeground="#0a0a10",
                              exportselection=False, relief="flat", highlightthickness=0, activestyle="none")
        sb = tk.Scrollbar(box, command=self.lst.yview)
        self.lst.config(yscrollcommand=sb.set)
        self.lst.pack(side="left", fill="x", expand=True)
        sb.pack(side="right", fill="y")

        right = tk.Frame(mid, bg=Theme.DARK_BG)
        right.pack(side="left", padx=(14, 0), anchor="n")
        tk.Label(right, text="Couleur des clips :", bg=Theme.DARK_BG, fg=Theme.FG_DIM,
                 font=Theme.FONT_SM).pack(anchor="w")
        self.color_var = tk.StringVar(value=an.ALL_COLORS)
        ttk.Combobox(right, textvariable=self.color_var, width=20, state="readonly",
                      values=[an.ALL_COLORS] + CLIP_COLORS).pack(anchor="w", pady=(0, 6))
        row = tk.Frame(right, bg=Theme.DARK_BG)
        row.pack(anchor="w")
        self.button(row, "Tout", Theme.PANEL_BG, lambda: self.lst.select_set(0, "end"), side="left")
        self.button(row, "Aucune", Theme.PANEL_BG, lambda: self.lst.select_clear(0, "end"),
                    side="left", padx_l=4)
        self.button(right, "Relire", Theme.PANEL_BG, self._reload_timelines, side="top").pack_configure(
            anchor="w", pady=(6, 0))

        act = tk.Frame(main, bg=Theme.DARK_BG)
        act.pack(fill="x", pady=(10, 0))
        self.btn_analyze = self.button(act, "Analyser", Theme.ACCENT, self.on_analyze, side="left")
        self.btn_csv = self.button(act, "Exporter CSV", Theme.PANEL_BG, self.on_export_csv,
                                    side="left", padx_l=8)
        self.btn_csv.config(state="disabled")
        self.btn_import = self.button(act, "Importer les disques montés", Theme.SUCCESS, self.on_import,
                                       side="left", padx_l=8)
        self.btn_import.config(state="disabled")
        self.progress = ttk.Progressbar(main, mode="determinate")
        self.progress.pack(fill="x", pady=(8, 0))

        self.lbl_summary = tk.Label(main, text="", bg=Theme.DARK_BG, fg=Theme.FG, justify="left")
        self.lbl_summary.pack(anchor="w", pady=(8, 0))

        self.nb = ttk.Notebook(main)
        self.nb.pack(fill="both", expand=True, pady=(6, 0))
        self.tab_pull = self._tab("Pull list", ("uses", "size", "path"),
                                  (("#0", "Disque / source", 300), ("uses", "Util.", 50),
                                   ("size", "Taille", 90), ("path", "Chemin", 420)), tree=True)
        self.tab_missing = self._tab("Introuvables", ("uses", "tl"),
                                     (("#0", "Source", 340), ("uses", "Util.", 50), ("tl", "Timelines", 300)))
        self.tab_dup = self._tab("Doublons", ("disks", "chosen"),
                                 (("#0", "Source", 300), ("disks", "Disques", 260), ("chosen", "Retenu", 160)))
        self.tab_ign = self._tab("Ignorés", ("tl", "why"),
                                 (("#0", "Élément", 260), ("tl", "Timeline", 160), ("why", "Raison", 360)))

        self.log = self.build_log(main, height=6)

    def _tab(self, title, cols, heads, tree=False):
        frame = tk.Frame(self.nb, bg=Theme.DARK_BG)
        t = ttk.Treeview(frame, columns=cols, show="tree headings", height=9)
        if tree:
            bar = tk.Frame(frame, bg=Theme.DARK_BG)
            bar.pack(fill="x", pady=(4, 4))
            hint = tk.Label(bar, text="Clic sur un en-tête de colonne : trier", font=Theme.FONT_SM,
                            bg=Theme.DARK_BG, fg=Theme.FG_DIM)
            for icon, tip, opened in (("⊟", "Tout replier", False), ("⊞", "Tout déplier", True)):
                # Label cliquable plutôt que tk.Button : sous macOS un Button natif ignore bg et reste blanc.
                b = tk.Label(bar, text=icon, font=(Theme.FONT_UI[0], 14), bg=Theme.PANEL_BG, fg=Theme.FG,
                             padx=9, pady=1, cursor="hand2", highlightthickness=1,
                             highlightbackground=Theme.BORDER)
                b.pack(side="left", padx=(0, 4))
                b.bind("<Button-1>", lambda e, o=opened: self._expand_all(t, o))
                b.bind("<Enter>", lambda e, tx=tip, w=b: (hint.config(text=tx), w.config(bg=Theme.BORDER)))
                b.bind("<Leave>", lambda e, w=b: (hint.config(text="Clic sur un en-tête de colonne : trier"),
                                                  w.config(bg=Theme.PANEL_BG)))
            hint.pack(side="left", padx=10)
        self._sort[t], self._skeys[t] = None, {}
        for col, text, w in heads:
            self._heads[(t, col)] = text
            t.heading(col, text=text, command=lambda c=col, tv=t: self._sort_by(tv, c))
            t.column(col, width=w, anchor="w", stretch=(col in ("#0", "path", "why", "tl")))
        sb = tk.Scrollbar(frame, command=t.yview)
        t.config(yscrollcommand=sb.set)
        t.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        t.tag_configure("mounted", foreground=Theme.SUCCESS)
        t.tag_configure("unmounted", foreground=Theme.FG_DIM)
        self.nb.add(frame, text=title)
        return t

    # ------------------------------------------------------- Tri et repli
    def _add(self, tree, parent, text, values, sort=None, **kw):
        """Insère une ligne ; `sort` = valeurs de tri réelles (nombres) par colonne."""
        iid = tree.insert(parent, "end", text=text, values=values, **kw)
        if sort:
            self._skeys[tree][iid] = sort
        return iid

    def _sort_value(self, tree, iid, col):
        v = self._skeys[tree].get(iid, {}).get(col)
        if v is None:
            v = tree.item(iid, "text") if col == "#0" else tree.set(iid, col)
        if isinstance(v, (int, float)):
            return (0, v)
        try:
            return (0, float(v))
        except (TypeError, ValueError):
            return (1, str(v).lower())

    def _sort_by(self, tree, col):
        cur = self._sort.get(tree)
        self._sort[tree] = (col, bool(cur and cur[0] == col and not cur[1]))   # 2e clic : inverse
        self._apply_sort(tree)

    def _apply_sort(self, tree):
        state = self._sort.get(tree)
        if not state:
            return
        col, rev = state
        for parent in ("",) + tuple(tree.get_children("")):         # disques, puis sources de chaque disque
            kids = sorted(tree.get_children(parent), key=lambda i: self._sort_value(tree, i, col), reverse=rev)
            for n, iid in enumerate(kids):
                tree.move(iid, parent, n)
        for (tv, c), title in self._heads.items():
            if tv is tree:
                mark = (" ▼" if rev else " ▲") if c == col else ""
                tree.heading(c, text=title + mark)

    @staticmethod
    def _expand_all(tree, opened):
        for iid in tree.get_children(""):
            tree.item(iid, open=opened)

    # ------------------------------------------------------- Resolve / index
    def _init_resolve(self):
        try:
            self.resolve, self.project, _ = pm_common.get_resolve_objects()
        except Exception as e:
            messagebox.showerror("Erreur de connexion", str(e))
            self.resolve = self.project = None
            return
        self.log_write(self.log, f"Connecté à Resolve (variante : {pm_common.RESOLVE_VARIANT}).\n", "dim")
        self._reload_timelines()

    def _reload_timelines(self):
        self.lst.delete(0, "end")
        self.timelines = []
        if not self.project:
            return
        for i in range(1, int(self.project.GetTimelineCount() or 0) + 1):
            tl = self.project.GetTimelineByIndex(i)
            if tl:
                self.timelines.append(tl.GetName())
                self.lst.insert("end", tl.GetName())
        self.log_write(self.log, f"{len(self.timelines)} timeline(s) dans le projet.\n", "dim")

    def on_browse(self):
        folder = pm_common.pick_folder("Dossier contenant les SnapDrive (.html)", parent=self)
        if folder:
            self.folder_var.set(folder)
            self._load_index()

    def _load_index(self):
        folder = os.path.expanduser(self.folder_var.get().strip().strip('"').strip("'").replace("\\ ", " "))
        try:
            self.index, errors = snapdrive.load_folder(folder)
        except snapdrive.SnapDriveError as e:
            self.index = snapdrive.SnapDriveIndex()
            self.lbl_index.config(text=str(e), fg=Theme.DANGER)
            self.log_write(self.log, f"[ERREUR] {e}\n", "err")
            return
        for msg in errors:
            self.log_write(self.log, f"[ATTENTION] {msg}\n", "warn")
        mounted = [d for d in self.index.drives if snapdrive.is_mounted(d)]
        self.lbl_index.config(
            text=f"{len(self.index.drives)} disque(s), {len(self.index):,} fichiers indexés".replace(",", " ")
                 + f"  ·  {len(mounted)} monté(s)" + (f"  ·  {len(errors)} fichier(s) ignoré(s)" if errors else ""),
            fg=Theme.FG if self.index.drives else Theme.WARNING)
        self.log_write(self.log, f"SnapDrive : {len(self.index.drives)} disque(s) depuis {folder}\n", "dim")
        self.cfg["folder"] = folder
        save_config(self.cfg)

    # ------------------------------------------------------------- Analyse
    def _priority(self):
        return [p.strip() for p in self.prio_var.get().split(",") if p.strip()]

    def on_analyze(self):
        """Lecture seule : getters Resolve + calcul local. Rien n'est écrit dans le projet."""
        if not self.project:
            messagebox.showerror("Resolve", "Pas de connexion à Resolve.")
            return
        if not self.index.drives:
            messagebox.showwarning("SnapDrive", "Charge d'abord un dossier de SnapDrive.")
            return
        names = [self.timelines[i] for i in self.lst.curselection()]
        if not names:
            messagebox.showwarning("Timelines", "Coche au moins une timeline.")
            return
        color = self.color_var.get()
        self.cfg["priority"] = self._priority()
        save_config(self.cfg)
        self.btn_analyze.config(state="disabled")
        self.log_write(self.log, f"\n── Analyse : {len(names)} timeline(s), couleur : {color} ──\n", "accent")
        raw, types_seen, journal = [], set(), [f"Couleur : {color}", f"Priorité : {self._priority()}"]
        try:
            for i in range(1, int(self.project.GetTimelineCount() or 0) + 1):
                tl = self.project.GetTimelineByIndex(i)
                if not tl or tl.GetName() not in names:
                    continue
                items = read_timeline(tl, color, types_seen)
                raw += items
                self.log_write(self.log, f"  {tl.GetName()} : {len(items)} élément(s) lus\n", "dim")
                journal.append(f"Timeline {tl.GetName()} : {len(items)} élément(s)")
                self.update()
            self.report = an.analyze(raw, self.index, names, color, self._priority())
        except Exception as e:
            log_path = pm_common.write_error_log(TOOL_NAME, e)
            self.log_write(self.log, f"[ERREUR] Analyse interrompue : {e}\n  Log : {log_path}\n", "err")
            messagebox.showerror("Analyse", f"L'analyse a échoué :\n{e}\n\nLog : {log_path}")
            self.btn_analyze.config(state="normal")
            return
        self.log_write(self.log, "Types de clips rencontrés : " + ", ".join(sorted(types_seen)) + "\n", "dim")
        self._show_report(self.report)
        journal += self._journal_lines(self.report) + ["Types : " + ", ".join(sorted(types_seen))]
        try:
            self.log_write(self.log, f"Journal : {pm_common.write_log(TOOL_NAME, journal)}\n", "dim")
        except OSError as e:
            self.log_write(self.log, f"[INFO] Journal non écrit ({e}).\n", "dim")
        self.btn_analyze.config(state="normal")
        self.btn_csv.config(state="normal")
        self.btn_import.config(state="normal")

    def _show_report(self, r, quiet=False):
        for t in (self.tab_pull, self.tab_missing, self.tab_dup, self.tab_ign):
            t.delete(*t.get_children())
            self._skeys[t] = {}
        pull = r.pull_list()
        for disk, d in pull.items():
            tag = "mounted" if d["mounted"] else "unmounted"
            parent = self._add(
                self.tab_pull, "", f"{'●' if d['mounted'] else '○'} {disk}  ({d['sources']} source(s))",
                (d["uses"], an.human_size(d["size"]), "monté" if d["mounted"] else "non monté"),
                {"#0": disk.lower(), "uses": d["uses"], "size": d["size"], "path": int(d["mounted"])},
                open=True, tags=(tag,))
            for s in sorted((x for x in r.found if x.chosen.disk == disk), key=lambda x: x.name.lower()):
                self._add(self.tab_pull, parent, s.name,
                          (s.uses, an.human_size(s.chosen.size), s.chosen.path),
                          {"uses": s.uses, "size": s.chosen.size or 0})
        for s in r.missing:
            self.tab_missing.insert("", "end", text=s.name, values=(s.uses, " | ".join(sorted(s.timelines))))
        for s in r.duplicates:
            self.tab_dup.insert("", "end", text=s.name, values=(", ".join(s.disks), s.chosen.disk))
        for it in r.ignored:
            self.tab_ign.insert("", "end", text=it.name or "(sans nom)",
                                values=(it.timeline, an.IGNORED_LABELS.get(it.kind, it.kind)
                                        + (f" [{it.detail}]" if it.detail else "")))
        for t in (self.tab_pull, self.tab_missing, self.tab_dup, self.tab_ign):
            self._apply_sort(t)         # garde le tri choisi d'une analyse à l'autre
        for i, (title, n) in enumerate((("Pull list", len(r.found)), ("Introuvables", len(r.missing)),
                                        ("Doublons", len(r.duplicates)), ("Ignorés", len(r.ignored)))):
            self.nb.tab(i, text=f"{title} ({n})")
        total = sum(d["size"] for d in pull.values())
        ign = r.ignored_summary()
        self.lbl_summary.config(
            text=f"{len(r.sources)} source(s) distincte(s) : {len(r.found)} trouvée(s) sur {len(pull)} disque(s) "
                 f"({an.human_size(total)}), {len(r.missing)} introuvable(s), {len(r.duplicates)} en doublon.\n"
                 f"Ignorés : {ign.get('generator', 0)} générateur(s)/titre(s), "
                 f"{ign.get('compound', 0)} compound/imbriqué(s) NON ANALYSÉ(S)"
                 + (f", {ign['noname']} sans nom" if ign.get("noname") else "") + ".")
        if quiet:
            return
        for s in r.sources:     # contre-vérification optionnelle du compte d'utilisations
            if s.usage and s.usage.isdigit() and int(s.usage) != s.uses:
                self.log_write(self.log, f"[INFO] {s.name} : {s.uses} utilisation(s) comptées ici (filtre/timelines "
                                         f"choisies), Usage Resolve = {s.usage} (projet entier).\n", "dim")
        self.log_write(self.log, f"Terminé : {len(r.found)} trouvée(s), {len(r.missing)} introuvable(s), "
                                 f"{len(r.duplicates)} doublon(s), {len(r.ignored)} ignoré(s).\n", "accent")
        if ign.get("compound"):
            self.log_write(self.log, "[ATTENTION] Compound clips / timelines imbriquées présents : "
                                     "leur contenu n'est pas analysé.\n", "warn")

    @staticmethod
    def _journal_lines(r):
        lines = [""]
        for row in an.report_rows(r):
            lines.append("\t".join(str(c) for c in row))
        return lines

    # -------------------------------------------------------------- Import
    def on_import(self):
        """Importe les sources des disques montés (écrit dans le media pool ; jamais dans les timelines)."""
        if not self.report or not self.project:
            return
        plan = si.plan_import(self.report, self._priority())
        if not plan.by_disk:
            waiting = sorted({e for s in plan.waiting for e in s.disks})
            messagebox.showinfo("Importer", "Aucun disque monté ne contient de source nécessaire.\n\n"
                                + (f"Disques à brancher : {short_list(waiting)}" if waiting
                                   else "Aucune source trouvée dans les SnapDrive."))
            return
        lines = [f"  {d} : {len(p)} source(s), {an.human_size(sum(e.size or 0 for _, e in p))}"
                 for d, p in plan.by_disk.items()]
        later = sorted({s.chosen.disk for s in plan.waiting})
        msg = ("Importer dans _SnapDrive/<disque> :\n\n" + "\n".join(lines) +
               (f"\n\nPas encore montés : {short_list(later)}" if later else "") +
               "\n\nCe qui est déjà dans le projet est ignoré. Continuer ?")
        if not messagebox.askyesno("Importer les disques montés", msg):
            return
        for b in (self.btn_import, self.btn_analyze):
            b.config(state="disabled")
        total = sum(len(v) for v in plan.by_disk.values())
        self.progress.config(maximum=total, value=0)
        self.log_write(self.log, f"\n── Import : {len(plan.by_disk)} disque(s), {total} source(s) ──\n", "accent")
        tags = {"imported": ("ok", "[OK]"), "present": ("dim", "[déjà là]"), "absent": ("warn", "[ABSENT]"),
                "error": ("err", "[ERREUR]"), "skipped": ("warn", "[ignoré]")}

        def progress(i, n, r):
            tag, label = tags[r.status]
            self.log_write(self.log, f"{label} {r.disk}  {r.name}" + (f" — {r.detail}" if r.detail else "") + "\n", tag)
            self.progress.config(value=i)
            self.update()

        try:
            results = si.run_import(self.project.GetMediaPool(), plan, progress=progress)
        except Exception as e:
            log_path = pm_common.write_error_log(TOOL_NAME, e)
            self.log_write(self.log, f"[ERREUR] Import interrompu : {e}\n  Log : {log_path}\n", "err")
            messagebox.showerror("Import", f"L'import a échoué :\n{e}\n\nLog : {log_path}")
            self.btn_analyze.config(state="normal")
            self.btn_import.config(state="normal")
            return
        counts, text = si.summarize(results)
        journal = [f"Import : {text}"] + [f"{r.status}\t{r.disk}\t{r.path}\t{r.detail}" for r in results]
        try:
            self.log_write(self.log, f"Journal : {pm_common.write_log(TOOL_NAME + '_import', journal)}\n", "dim")
        except OSError as e:
            self.log_write(self.log, f"[INFO] Journal non écrit ({e}).\n", "dim")
        self.log_write(self.log, f"Terminé : {text}.\n", "accent")
        if later:
            self.log_write(self.log, f"Disques restants à brancher : {short_list(later, 50)}\n", "warn")
        self._show_report(self.report, quiet=True)      # met à jour les ● monté / ○ non monté
        self.btn_analyze.config(state="normal")
        self.btn_import.config(state="normal")
        messagebox.showinfo("Import terminé", text + (f"\n\nDisques restants : {short_list(later)}" if later else ""))

    def on_export_csv(self):
        if not self.report:
            return
        folder = pm_common.pick_folder("Dossier où écrire le CSV du rapport", parent=self)
        if not folder:
            return
        path = os.path.join(folder, "snapdrive_rapport.csv")
        n = 2
        while os.path.exists(path):         # jamais d'écrasement
            path = os.path.join(folder, f"snapdrive_rapport_{n}.csv")
            n += 1
        try:
            an.write_csv(self.report, path)
        except OSError as e:
            messagebox.showerror("Export CSV", f"Écriture impossible :\n{e.strerror or e}")
            return
        self.log_write(self.log, f"CSV exporté : {path}\n", "ok")


def open_window(master):
    return SnapDriveLoaderWindow(master)


def main():
    """Lancement autonome (Workspace > Scripts) : racine Tk cachée + fenêtre de l'outil."""
    root = tk.Tk()
    root.withdraw()
    try:
        win = SnapDriveLoaderWindow(root)
        win.protocol("WM_DELETE_WINDOW", root.destroy)
        pm_common.run_app(root)
    except Exception as e:
        pm_common.write_error_log(TOOL_NAME, e)
        raise


if __name__ == "__main__":
    main()
