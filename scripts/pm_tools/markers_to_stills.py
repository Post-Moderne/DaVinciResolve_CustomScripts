#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Markers → Stills — exporte un still (image) à chaque marker de la timeline active
et construit le nom du fichier à partir de « briques » ordonnables.
Module interne de la PM Suite (voir PM-Suite.py).

FONCTIONNEMENT
───────────────
Les markers de timeline (timeline.GetMarkers()) sont indexés par frame *relative*
au début de la timeline : on y ajoute le Start TC de la timeline pour obtenir le
timecode absolu, on déplace le playhead dessus (SetCurrentTimecode) puis on appelle
project.ExportCurrentFrameAsStill(). Le format est déterminé par l'extension.

NOM DU FICHIER
───────────────
Le nom est assemblé à partir d'une liste ordonnée de briques (nom/notes du marker,
nom ou fichier source du clip du dessus, TC record, TC source, date, numéro
séquentiel, texte libre) reliées par un séparateur. Les briques vides sont
ignorées ; si tout est vide, le nom devient « Marker_<TC> ». Le « clip du dessus »
est le clip activé de la piste vidéo la plus haute qui couvre la frame du marker.
Les caractères interdits sont remplacés par « _ » ; en cas de doublon (dans le lot
ou déjà sur le disque) un suffixe _2, _3… est ajouté : rien n'est jamais écrasé.
La dernière configuration est mémorisée (~/Logs/PM-Suite/config/).
Le still reflète le grade actuel de la timeline.
"""

import os
import sys
import re
import json
import time
from datetime import datetime
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
from pm_tools.csv_to_vfxid import tc_to_frames

TOOL_NAME = "PM-Resolve_Markers-to-Stills"

ALL_COLORS = "Toutes les couleurs"
FORMATS = ["png", "jpg", "tif", "dpx"]
BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

# Briques de nom : id → libellé affiché. "text" est une brique à contenu libre.
BRICKS = {
    "marker_name": "Nom du marker",
    "marker_note": "Notes du marker",
    "clip_name":   "Nom du clip du dessus",
    "clip_file":   "Fichier source du clip du dessus",
    "tc_record":   "TC record",
    "tc_source":   "TC source",
    "date":        "Date",
    "index":       "Numéro séquentiel",
    "text":        "Texte libre",
}
DEFAULT_PIECES = [{"id": "marker_name"}]
SEPARATORS = {"_  (underscore)": "_", "-  (tiret)": "-", "espace": " ", "aucun": ""}
DATE_FORMATS = {"AAAA-MM-JJ": "%Y-%m-%d", "AAMMJJ": "%y%m%d", "AAAAMMJJ": "%Y%m%d"}
CONFIG_PATH = os.path.join(pm_common.LOG_ROOT, "config", "markers_to_stills.json")


# ── Logique pure (testable hors Resolve) ───────────────────────────────────────
def frames_to_tc(frame, fps, drop_frame=False):
    """Numéro de frame absolu → 'HH:MM:SS:FF' (ou 'HH:MM:SS;FF' en drop frame)."""
    nominal = int(round(float(fps)))
    frame = int(frame)
    if drop_frame:
        drop = 2 if nominal <= 30 else 4
        per_10min = nominal * 600 - drop * 9
        per_min = nominal * 60 - drop
        d, m = divmod(frame, per_10min)
        if m > drop:
            frame += drop * 9 * d + drop * ((m - drop) // per_min)
        else:
            frame += drop * 9 * d
    ff = frame % nominal
    ss = (frame // nominal) % 60
    mm = (frame // (nominal * 60)) % 60
    hh = frame // (nominal * 3600)
    sep = ";" if drop_frame else ":"
    return f"{hh:02d}:{mm:02d}:{ss:02d}{sep}{ff:02d}"



def sanitize(name):
    """Nom de fichier sûr : caractères interdits → '_', espaces/points de bord retirés."""
    clean = BAD_CHARS.sub("_", name or "").strip().strip(".")
    return clean[:150]


def tc_for_filename(tc):
    """'01:00:01;06' → '01-00-01-06' (le ':' est interdit dans un nom de fichier)."""
    return tc.replace(":", "-").replace(";", "-")


def find_top_item(candidates, frame):
    """
    candidates : liste de dicts {track, start, end, enabled, ...}. Retourne le clip activé
    de la piste la plus haute dont [start, end) contient `frame`, sinon None.
    """
    best = None
    for c in candidates:
        if c.get("enabled", True) and c["start"] <= frame < c["end"]:
            if best is None or c["track"] > best["track"]:
                best = c
    return best


def source_timecode(clip_start_tc, source_offset, frame_in_clip, fps, drop_frame=False):
    """
    TC source à la frame `frame_in_clip` (nombre de frames depuis le début du clip sur la
    timeline) : Start TC du média + décalage de début de clip + position dans le clip.
    Retourne "" si le Start TC n'est pas exploitable.
    """
    try:
        base = tc_to_frames(clip_start_tc, fps, drop_frame)
    except ValueError:
        return ""
    return frames_to_tc(base + int(source_offset) + int(frame_in_clip), fps, drop_frame)


def build_name(pieces, sep, values):
    """
    Assemble le nom à partir des briques. `values` : dict {id: texte} ; la brique "text"
    porte son contenu dans piece["text"]. Retourne (nom, [libellés des briques vides]).
    """
    parts, empty = [], []
    for piece in pieces:
        pid = piece["id"]
        raw = piece.get("text", "") if pid == "text" else values.get(pid, "")
        part = sanitize(raw)
        if part:
            parts.append(part)
        elif pid != "text":
            empty.append(BRICKS[pid])
    return sep.join(parts), empty


def build_plan(markers, start_frame, fps, drop_frame, color, folder, ext,
               pieces=None, sep="_", date_str="", resolver=None, exists=os.path.exists):
    """
    markers : dict {offset: {color, name, note, ...}} tel que rendu par GetMarkers().
    resolver(frame_absolu) → dict {clip_name, clip_file, tc_source} du clip du dessus
    ({} si aucun) ; injectable pour les tests.
    Retourne une liste triée de dicts {tc, color, label, path, status, warn}.
    """
    pieces = pieces or DEFAULT_PIECES
    plan, used, index = [], set(), 0
    for offset in sorted(markers):
        m = markers[offset]
        if color != ALL_COLORS and m.get("color") != color:
            continue
        index += 1
        frame = start_frame + int(offset)
        tc = frames_to_tc(frame, fps, drop_frame)
        values = {"marker_name": m.get("name") or "", "marker_note": m.get("note") or "",
                  "tc_record": tc_for_filename(tc), "date": date_str, "index": f"{index:03d}"}
        if resolver and any(p["id"] in ("clip_name", "clip_file", "tc_source") for p in pieces):
            values.update(resolver(frame) or {})
        label, empty = build_name(pieces, sep, values)
        fallback = not label
        if fallback:
            label = "Marker_" + tc_for_filename(tc)
        base, n = label, 1
        while True:
            fname = f"{base}.{ext}" if n == 1 else f"{base}_{n}.{ext}"
            path = os.path.join(folder, fname)
            if fname.lower() not in used and not exists(path):
                break
            n += 1
        used.add(fname.lower())
        notes = []
        if fallback:
            notes.append("nom vide → TC")
        elif empty:
            notes.append("brique vide : " + ", ".join(empty))
        if n > 1:
            notes.append(f"doublon → _{n}")
        plan.append({"tc": tc, "color": m.get("color", ""), "label": label, "path": path,
                     "status": "Prêt" + (f" ({' ; '.join(notes)})" if notes else ""),
                     "warn": bool(notes)})
    return plan


def load_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        return {}
    pieces = [p for p in cfg.get("pieces", []) if isinstance(p, dict) and p.get("id") in BRICKS]
    cfg["pieces"] = pieces
    return cfg


def save_config(cfg):
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


class MarkersToStillsWindow(PMWindow):
    def __init__(self, master):
        self.markers = {}
        self.plan = []
        self.timeline = None
        self._candidates = []
        self._resolved = {}
        cfg = load_config()
        self.pieces = cfg.get("pieces") or [dict(p) for p in DEFAULT_PIECES]
        self._cfg = cfg
        super().__init__(master, "Markers → Stills",
                          f"DaVinci Resolve  ·  {pm_common.RESOLVE_VARIANT}")
        self._init_resolve()

    # ------------------------------------------------------------------ UI
    def _label(self, parent, text, **kw):
        return tk.Label(parent, text=text, bg=Theme.DARK_BG, fg=Theme.FG, **kw)

    def _build_content(self, main):
        top = tk.Frame(main, bg=Theme.DARK_BG)
        top.pack(fill="x")
        self._label(top, "Dossier :").pack(side="left")
        self.folder_var = tk.StringVar()
        entry = tk.Entry(top, textvariable=self.folder_var, bg=Theme.PANEL_BG, fg=Theme.FG,
                          insertbackground=Theme.FG, relief="flat", width=50)
        entry.pack(side="left", padx=6, ipady=3)
        entry.bind("<Return>", lambda e: self._rebuild_plan())
        self.button(top, "Parcourir…", Theme.PANEL_BG, self.on_browse, side="left")
        self.btn_export = self.button(top, "Exporter", Theme.SUCCESS, self.on_export, side="right")
        self.btn_export.config(state="disabled")

        opts = tk.Frame(main, bg=Theme.DARK_BG)
        opts.pack(fill="x", pady=(8, 0))
        self._label(opts, "Couleur :").pack(side="left")
        self.color_var = tk.StringVar(value=ALL_COLORS)
        self.cmb_color = ttk.Combobox(opts, textvariable=self.color_var, width=22,
                                       state="readonly", values=[ALL_COLORS])
        self.cmb_color.pack(side="left", padx=6)
        self.cmb_color.bind("<<ComboboxSelected>>", lambda e: self._rebuild_plan())
        self._label(opts, "Format :").pack(side="left", padx=(16, 0))
        self.fmt_var = tk.StringVar(value=self._cfg.get("ext") if self._cfg.get("ext") in FORMATS else "png")
        cmb_fmt = ttk.Combobox(opts, textvariable=self.fmt_var, width=6, state="readonly", values=FORMATS)
        cmb_fmt.pack(side="left", padx=6)
        cmb_fmt.bind("<<ComboboxSelected>>", lambda e: self._on_naming_changed())
        self.button(opts, "Relire les markers", Theme.PANEL_BG, self._reload, side="right")

        # ── Constructeur de nom ──
        self.section(main, "NOM DU FICHIER  —  briques dans l'ordre d'assemblage")
        box = tk.Frame(main, bg=Theme.DARK_BG)
        box.pack(fill="x")
        self.lst = tk.Listbox(box, height=5, width=44, bg=Theme.PANEL_BG, fg=Theme.FG,
                              selectbackground=Theme.ACCENT, selectforeground="#0a0a10",
                              highlightbackground=Theme.BORDER, highlightthickness=1,
                              relief="flat", bd=0, exportselection=False, activestyle="none",
                              font=Theme.FONT_UI)
        self.lst.pack(side="left", fill="y")
        side = tk.Frame(box, bg=Theme.DARK_BG)
        side.pack(side="left", padx=(8, 0), fill="y")
        for txt, cmd in (("↑", lambda: self._move(-1)), ("↓", lambda: self._move(1)),
                         ("✕", self._remove)):
            tk.Button(side, text=txt, width=3, font=Theme.FONT_SM, bg=Theme.PANEL_BG, fg=Theme.FG,
                      relief="flat", bd=0, pady=3, cursor="hand2", command=cmd).pack(pady=1)

        add = tk.Frame(box, bg=Theme.DARK_BG)
        add.pack(side="left", padx=(20, 0), anchor="n")
        self._label(add, "Ajouter une brique :").grid(row=0, column=0, sticky="w")
        self.add_var = tk.StringVar(value=BRICKS["marker_name"])
        ttk.Combobox(add, textvariable=self.add_var, width=30, state="readonly",
                     values=list(BRICKS.values())).grid(row=1, column=0, sticky="w", pady=(2, 0))
        tk.Button(add, text="Ajouter", font=Theme.FONT_SM, bg=Theme.PANEL_BG, fg=Theme.FG,
                  relief="flat", bd=0, padx=10, pady=3, cursor="hand2",
                  command=self._add).grid(row=1, column=1, padx=(6, 0))
        self._label(add, "Texte (pour « Texte libre ») :").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.text_var = tk.StringVar()
        tk.Entry(add, textvariable=self.text_var, bg=Theme.PANEL_BG, fg=Theme.FG,
                 insertbackground=Theme.FG, relief="flat", width=32).grid(row=3, column=0, sticky="w", ipady=3)

        fmt = tk.Frame(main, bg=Theme.DARK_BG)
        fmt.pack(fill="x", pady=(8, 0))
        self._label(fmt, "Séparateur :").pack(side="left")
        sep_name = next((k for k, v in SEPARATORS.items() if v == self._cfg.get("sep", "_")),
                        list(SEPARATORS)[0])
        self.sep_var = tk.StringVar(value=sep_name)
        cmb = ttk.Combobox(fmt, textvariable=self.sep_var, width=14, state="readonly",
                           values=list(SEPARATORS))
        cmb.pack(side="left", padx=6)
        cmb.bind("<<ComboboxSelected>>", lambda e: self._on_naming_changed())
        self._label(fmt, "Format de date :").pack(side="left", padx=(16, 0))
        date_name = self._cfg.get("date_fmt") if self._cfg.get("date_fmt") in DATE_FORMATS else "AAAA-MM-JJ"
        self.date_var = tk.StringVar(value=date_name)
        cmb = ttk.Combobox(fmt, textvariable=self.date_var, width=12, state="readonly",
                           values=list(DATE_FORMATS))
        cmb.pack(side="left", padx=6)
        cmb.bind("<<ComboboxSelected>>", lambda e: self._on_naming_changed())
        self.skip_var = tk.BooleanVar(value=self._cfg.get("skip_no_media", True))
        tk.Checkbutton(fmt, text="Ignorer les clips sans média (titres, adjustment…)",
                       variable=self.skip_var, command=self._on_naming_changed,
                       bg=Theme.DARK_BG, fg=Theme.FG, activebackground=Theme.DARK_BG,
                       activeforeground=Theme.FG, selectcolor=Theme.PANEL_BG,
                       font=Theme.FONT_SM, bd=0).pack(side="left", padx=(16, 0))

        self.lbl_info = self._label(main, "")
        self.lbl_info.pack(anchor="w", pady=(8, 0))

        columns = ("tc", "color", "file", "status")
        self.tree = ttk.Treeview(main, columns=columns, show="headings", height=9)
        for col, title, w in (("tc", "TC", 110), ("color", "Couleur", 90),
                              ("file", "Fichier", 380), ("status", "Statut", 240)):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, pady=(6, 8))
        self.tree.tag_configure("ok", background=Theme.PANEL_BG)
        self.tree.tag_configure("warn", background="#4a3a1a")
        self.tree.tag_configure("bad", background="#4a1a1a")

        self.progress = ttk.Progressbar(main, mode="determinate")
        self.progress.pack(fill="x")
        self.log = self.build_log(main, height=7)
        self._refresh_list()

    # ------------------------------------------------- Constructeur de nom
    def _piece_text(self, piece):
        if piece["id"] == "text":
            return f"Texte libre : « {piece.get('text', '')} »"
        return BRICKS[piece["id"]]

    def _refresh_list(self, select=None):
        self.lst.delete(0, "end")
        for p in self.pieces:
            self.lst.insert("end", self._piece_text(p))
        if select is not None and 0 <= select < len(self.pieces):
            self.lst.selection_set(select)

    def _selected(self):
        sel = self.lst.curselection()
        return sel[0] if sel else None

    def _add(self):
        pid = next((k for k, v in BRICKS.items() if v == self.add_var.get()), "marker_name")
        piece = {"id": pid}
        if pid == "text":
            txt = self.text_var.get().strip()
            if not txt:
                messagebox.showinfo("Texte libre", "Saisis d'abord le texte à ajouter.")
                return
            piece["text"] = txt
        self.pieces.append(piece)
        self._refresh_list(select=len(self.pieces) - 1)
        self._on_naming_changed()

    def _remove(self):
        i = self._selected()
        if i is None:
            return
        del self.pieces[i]
        self._refresh_list(select=min(i, len(self.pieces) - 1))
        self._on_naming_changed()

    def _move(self, delta):
        i = self._selected()
        if i is None or not 0 <= i + delta < len(self.pieces):
            return
        self.pieces[i], self.pieces[i + delta] = self.pieces[i + delta], self.pieces[i]
        self._refresh_list(select=i + delta)
        self._on_naming_changed()

    def _sep(self):
        return SEPARATORS.get(self.sep_var.get(), "_")

    def _on_naming_changed(self):
        self._resolved.clear()
        self._save_cfg()
        self._rebuild_plan()

    def _save_cfg(self):
        save_config({"pieces": self.pieces, "sep": self._sep(), "date_fmt": self.date_var.get(),
                     "ext": self.fmt_var.get(), "skip_no_media": bool(self.skip_var.get())})

    # ---------------------------------------------------------- Resolve init
    def _init_resolve(self):
        try:
            self.resolve, self.project, _ = pm_common.get_resolve_objects()
        except Exception as e:
            messagebox.showerror("Erreur de connexion", str(e))
            self.resolve = self.project = None
            return
        self.log_write(self.log, f"Connecté à Resolve (variante : {pm_common.RESOLVE_VARIANT}).\n", "dim")
        self._reload()

    def _scan_items(self):
        """Liste les clips de toutes les pistes vidéo (pour trouver le clip du dessus)."""
        out = []
        n = int(self.timeline.GetTrackCount("video") or 1)
        for t in range(1, n + 1):
            for it in (self.timeline.GetItemListInTrack("video", t) or []):
                try:
                    enabled = bool(it.GetClipEnabled())
                except Exception:
                    enabled = True
                out.append({"track": t, "item": it, "start": int(it.GetStart()),
                            "end": int(it.GetEnd()), "enabled": enabled})
        return out

    def _reload(self):
        """Relit la timeline active, ses markers, ses clips et les couleurs présentes."""
        self.timeline = self.project.GetCurrentTimeline() if self.project else None
        if not self.timeline:
            self.log_write(self.log, "[ERREUR] Aucune timeline active.\n", "err")
            return
        try:
            self.fps = float(self.timeline.GetSetting("timelineFrameRate") or 24)
        except (TypeError, ValueError):
            self.fps = 24.0
        self.drop_frame = str(self.timeline.GetSetting("timelineDropFrameTimecode")) == "1"
        self.start_frame = tc_to_frames(self.timeline.GetStartTimecode() or "01:00:00:00",
                                        self.fps, self.drop_frame)
        self.markers = self.timeline.GetMarkers() or {}
        self._candidates = self._scan_items()
        self._resolved.clear()
        colors = sorted({m.get("color", "") for m in self.markers.values() if m.get("color")})
        self.cmb_color.config(values=[ALL_COLORS] + colors)
        if self.color_var.get() not in self.cmb_color["values"]:
            self.color_var.set(ALL_COLORS)
        self.lbl_info.config(text=f"{self.timeline.GetName()}  ·  {self.fps:g} fps"
                              f"{' DF' if self.drop_frame else ''}  ·  {len(self.markers)} marker(s)")
        self.log_write(self.log, f"Timeline : {self.timeline.GetName()}  ·  {len(self.markers)} marker(s)"
                        f"  ·  {len(self._candidates)} clip(s) vidéo"
                        f"  ·  couleurs : {', '.join(colors) or 'aucune'}\n", "dim")
        self._rebuild_plan()

    def _resolve_top_clip(self, frame):
        """Infos du clip du dessus à `frame` : {clip_name, clip_file, tc_source} ou {}."""
        if frame in self._resolved:
            return self._resolved[frame]
        cands = self._candidates
        if self.skip_var.get():
            cands = [c for c in cands if self._media_item(c)]
        top = find_top_item(cands, frame)
        info = {}
        if top:
            it, mpi = top["item"], self._media_item(top)
            info["clip_name"] = it.GetName() or ""
            if mpi:
                info["clip_file"] = os.path.splitext(str(mpi.GetClipProperty("File Name") or ""))[0]
                info["tc_source"] = self._source_tc(it, mpi, frame - top["start"])
        self._resolved[frame] = info
        return info

    @staticmethod
    def _media_item(cand):
        if "mpi" not in cand:
            try:
                cand["mpi"] = cand["item"].GetMediaPoolItem()
            except Exception:
                cand["mpi"] = None
        return cand["mpi"]

    def _source_tc(self, item, mpi, frame_in_clip):
        """TC source = Start TC du média + décalage de début de clip + position dans le clip."""
        try:
            offset = None
            for getter in ("GetSourceStartFrame", "GetLeftOffset"):
                if hasattr(item, getter):
                    offset = getattr(item, getter)()
                    if offset is not None:
                        break
            start_tc = str(mpi.GetClipProperty("Start TC") or "")
            if offset is None or not start_tc:
                return ""
            try:
                fps = float(mpi.GetClipProperty("FPS") or self.fps)
            except (TypeError, ValueError):
                fps = self.fps
            df = ";" in start_tc
            return tc_for_filename(source_timecode(start_tc, offset, frame_in_clip, fps, df))
        except Exception:
            return ""

    # ---------------------------------------------------------------- Plan
    def on_browse(self):
        folder = pm_common.pick_folder("Dossier de destination des stills", parent=self)
        if folder:
            self.folder_var.set(folder)
            self._rebuild_plan()

    def _folder(self):
        return os.path.expanduser(self.folder_var.get().strip().strip('"').strip("'").replace("\\ ", " "))

    def _rebuild_plan(self):
        self.tree.delete(*self.tree.get_children())
        self.plan = []
        self.btn_export.config(state="disabled")
        if not self.timeline:
            return
        folder = self._folder()
        date_str = datetime.now().strftime(DATE_FORMATS.get(self.date_var.get(), "%Y-%m-%d"))
        self.plan = build_plan(self.markers, self.start_frame, self.fps, self.drop_frame,
                               self.color_var.get(), folder or ".", self.fmt_var.get(),
                               pieces=self.pieces, sep=self._sep(), date_str=date_str,
                               resolver=self._resolve_top_clip)
        for p in self.plan:
            self.tree.insert("", "end", iid=p["tc"],
                             values=(p["tc"], p["color"], os.path.basename(p["path"]), p["status"]),
                             tags=("warn" if p["warn"] else "ok",))
        if not self.plan:
            self.log_write(self.log, "Aucun marker pour ce filtre.\n", "warn")
        elif folder and os.path.isdir(folder):
            self.btn_export.config(state="normal")
        else:
            self.log_write(self.log, f"{len(self.plan)} marker(s) — choisis un dossier de destination.\n", "dim")

    # -------------------------------------------------------------- Export
    def _goto(self, tc):
        """Place le playhead sur `tc` et attend que Resolve l'ait pris en compte."""
        for _ in range(10):
            self.timeline.SetCurrentTimecode(tc)
            time.sleep(0.15)
            self.update()
            if (self.timeline.GetCurrentTimecode() or "").replace(";", ":") == tc.replace(";", ":"):
                return True
        return False

    def _export_one(self, p):
        if not self._goto(p["tc"]):
            return False, "playhead non positionné"
        for _ in range(3):
            ok = self.project.ExportCurrentFrameAsStill(p["path"])
            for _ in range(10):         # l'écriture peut finir après le retour de l'API
                if os.path.isfile(p["path"]):
                    return True, ""
                time.sleep(0.1)
            time.sleep(0.3)
        return False, "export refusé par Resolve" if not ok else "fichier non créé"

    def on_export(self):
        folder = self._folder()
        if not self.plan or not os.path.isdir(folder):
            messagebox.showerror("Dossier introuvable", f"Choisis un dossier existant :\n{folder}")
            return
        if not messagebox.askyesno("Confirmer", f"Exporter {len(self.plan)} still(s) vers\n{folder} ?"):
            return
        self._save_cfg()
        self._rebuild_plan()            # nouveaux noms si des fichiers sont apparus entre-temps
        self.btn_export.config(state="disabled")
        self.progress.config(maximum=len(self.plan), value=0)
        self.log_write(self.log, "\n── Export ──\n", "accent")

        original_tc = self.timeline.GetCurrentTimecode()
        n_ok, journal = 0, [f"Timeline : {self.timeline.GetName()}", f"Dossier : {folder}"]
        for i, p in enumerate(self.plan, 1):
            try:
                ok, why = self._export_one(p)
            except Exception as e:
                ok, why = False, f"exception : {e}"
            iid = p["tc"]
            if ok:
                n_ok += 1
                self.log_write(self.log, f"[OK] {p['tc']}  → {os.path.basename(p['path'])}\n", "ok")
                self.tree.item(iid, tags=("ok",))
                self.tree.set(iid, "status", "Exporté")
            else:
                self.log_write(self.log, f"[ÉCHEC] {p['tc']}  {os.path.basename(p['path'])} — {why}\n", "err")
                self.tree.item(iid, tags=("bad",))
                self.tree.set(iid, "status", f"Échec ({why})")
            journal.append(f"{p['tc']}\t{p['color']}\t{p['path']}\t{'OK' if ok else 'ECHEC : ' + why}")
            self.progress.config(value=i)
            self.update()

        if original_tc:
            self.timeline.SetCurrentTimecode(original_tc)
        try:
            log_path = pm_common.write_log(TOOL_NAME, journal)
            self.log_write(self.log, f"\nJournal : {log_path}\n", "dim")
        except OSError as e:
            self.log_write(self.log, f"\n[INFO] Journal non écrit ({e}).\n", "dim")
        n_fail = len(self.plan) - n_ok
        self.log_write(self.log, f"Terminé : {n_ok} succès, {n_fail} échec(s).\n", "accent")
        messagebox.showinfo("Terminé", f"{n_ok} still(s) exporté(s).\n{n_fail} échec(s) — voir le log.")
        self.btn_export.config(state="normal")


def open_window(master):
    return MarkersToStillsWindow(master)


def main():
    """Lancement autonome (Workspace > Scripts) : racine Tk cachée + fenêtre de l'outil."""
    root = tk.Tk()
    root.withdraw()
    try:
        win = MarkersToStillsWindow(root)
        win.protocol("WM_DELETE_WINDOW", root.destroy)
        pm_common.run_app(root)
    except Exception as e:
        pm_common.write_error_log(TOOL_NAME, e)
        raise


if __name__ == "__main__":
    main()
