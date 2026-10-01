#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SnapDrive — analyse des sources d'une sélection de timelines et rapport.
Logique pure (ni Tk, ni Resolve, ni pm_common) : testable hors Resolve.
Utilisé par snapdrive_loader.py, qui lit les timelines via l'API Resolve et
transmet ici des RawItem déjà extraits.

Règle de match : nom du clip == nom du fichier sans extension, exact, insensible
à la casse, trim des espaces (voir snapdrive.match_key / normalize). Un clip offline
issu d'un XML/AAF n'a PAS de media pool item : on se fie au nom du timeline item, qui
peut porter une extension (« A_001.mov ») : elle est retirée avant le match, ce qui
permet aussi de retrouver un .mxf sur disque.
"""

import csv
import fnmatch
import re
from collections import OrderedDict, namedtuple

from pm_tools.snapdrive import is_mounted, normalize

# kind : "source" (clip à chercher dans les SnapDrive), "generator" (titre, générateur,
# adjustment), "compound" (compound clip / timeline imbriquée), "noname".
RawItem = namedtuple("RawItem", "timeline track name color kind usage detail")

IGNORED_LABELS = {
    "generator": "Générateur / titre / adjustment (nom générique)",
    "compound": "Compound clip ou timeline imbriquée : non analysé",
    "noname": "Media pool item sans nom",
}

ALL_COLORS = "Toutes les couleurs"


# Noms génériques de Resolve pour les éléments sans média (sans media pool item, impossible
# de les distinguer d'un clip offline autrement que par leur nom).
GENERATOR_PREFIXES = ("adjustment clip", "solid color", "text", "fusion title", "subtitle",
                      "scroll", "lower third", "generator", "gradient", "noise", "fade in",
                      "fade out", "cross dissolve", "transition")

_EXT_RE = re.compile(r"\.[A-Za-z][A-Za-z0-9]{1,4}$")


def clip_stem(name):
    """Nom de clip sans extension média éventuelle : 'A_001.mov' → 'A_001' ; 'A_001.5' inchangé."""
    return _EXT_RE.sub("", (name or "").strip())


def classify(has_media_pool_item, clip_type="", name=""):
    """
    kind d'un timeline item. `clip_type` = propriété « Type » du media pool item
    (« Compound Clip », « Video »…) quand il existe. Sans media pool item (clip offline d'un
    XML/AAF non relinké), seul le nom permet d'écarter les générateurs/titres.
    """
    if not has_media_pool_item:
        n = (name or "").strip().lower()
        if n.startswith(GENERATOR_PREFIXES) and clip_stem(n) == n:     # un vrai clip porte une extension
            return "generator"
        return "source"
    t = (clip_type or "").lower()
    if "compound" in t or t == "timeline":
        return "compound"
    if any(w in t for w in ("generator", "title", "adjustment")):
        return "generator"
    return "source"


# ── Choix du disque ────────────────────────────────────────────────────────────
def priority_rank(disk, patterns):
    """Rang du disque dans la liste de motifs (fnmatch, insensible à la casse) ; inconnu = en dernier."""
    d = disk.lower()
    for i, p in enumerate(patterns):
        if fnmatch.fnmatch(d, p.strip().lower()):
            return i
    return len(patterns)


def choose_entry(hits, priority=(), mounted=is_mounted):
    """
    Entrée retenue parmi plusieurs candidats : les disques montés d'abord, puis l'ordre
    de priorité configuré, puis ordre alphabétique (déterministe).
    """
    if not hits:
        return None
    return min(hits, key=lambda e: (not mounted(e.disk), priority_rank(e.disk, priority),
                                    e.disk.lower(), e.path))


# ── Analyse ────────────────────────────────────────────────────────────────────
class SourceResult:
    def __init__(self, name):
        self.name = name
        self.uses = 0
        self.usage = None           # propriété « Usage » du media pool item (contre-vérification)
        self.timelines = set()
        self.hits = []              # toutes les Entry SnapDrive correspondantes
        self.chosen = None

    @property
    def duplicate(self):
        return len(self.hits) > 1

    @property
    def disks(self):
        return sorted({e.disk for e in self.hits})


class Report:
    def __init__(self, timelines, color):
        self.timelines = list(timelines)
        self.color = color
        self.sources = []           # SourceResult, ordre de première apparition
        self.ignored = []           # RawItem

    @property
    def found(self):
        return [s for s in self.sources if s.chosen]

    @property
    def missing(self):
        return [s for s in self.sources if not s.chosen]

    @property
    def duplicates(self):
        return [s for s in self.sources if s.duplicate]

    def pull_list(self, mounted=is_mounted):
        """disque → {sources, uses, size, mounted}, trié par nom de disque."""
        out = OrderedDict()
        for s in sorted(self.found, key=lambda s: (s.chosen.disk.lower(), s.name.lower())):
            d = out.setdefault(s.chosen.disk, {"sources": 0, "uses": 0, "size": 0,
                                               "mounted": mounted(s.chosen.disk)})
            d["sources"] += 1
            d["uses"] += s.uses
            d["size"] += s.chosen.size or 0
        return out

    def ignored_summary(self):
        counts = OrderedDict()
        for it in self.ignored:
            counts[it.kind] = counts.get(it.kind, 0) + 1
        return counts


def analyze(raw_items, index, timelines=(), color=ALL_COLORS, priority=(), mounted=is_mounted):
    """
    raw_items : RawItem déjà filtrés par couleur côté lecture. Retourne un Report.
    Une source utilisée plusieurs fois n'apparaît qu'une fois, avec son nombre d'utilisations.
    """
    report = Report(timelines, color)
    by_key = OrderedDict()
    for it in raw_items:
        if it.kind != "source":
            report.ignored.append(it)
            continue
        if not normalize(it.name):
            report.ignored.append(it._replace(kind="noname"))
            continue
        # D'abord le nom tel quel, puis sans extension (« A_001.mov » → « A_001 »).
        hits = index.lookup(it.name)
        label = it.name.strip() if hits else clip_stem(it.name)
        key = normalize(label)
        s = by_key.get(key)
        if s is None:
            s = by_key[key] = SourceResult(label)
            s.hits = hits or index.lookup(label)
            s.chosen = choose_entry(s.hits, priority, mounted)
        s.uses += 1
        s.timelines.add(it.timeline)
        if it.usage and not s.usage:
            s.usage = it.usage
    report.sources = list(by_key.values())
    return report


# ── Export CSV ─────────────────────────────────────────────────────────────────
CSV_HEADER = ["Statut", "Disque", "Source", "Chemin", "Taille (octets)", "Utilisations",
              "Usage (Resolve)", "Timelines", "Détail"]


def report_rows(report, mounted=is_mounted):
    """Lignes du CSV : une par source retenue/introuvable, une par doublon alternatif, une par élément ignoré."""
    rows = []
    for s in report.sources:
        tl = " | ".join(sorted(s.timelines))
        if not s.chosen:
            rows.append(["INTROUVABLE", "", s.name, "", "", s.uses, s.usage or "", tl, ""])
            continue
        c = s.chosen
        detail = "disque monté" if mounted(c.disk) else "disque non monté"
        rows.append(["TROUVÉ" + (" (doublon)" if s.duplicate else ""), c.disk, s.name, c.path,
                     c.size if c.size is not None else "", s.uses, s.usage or "", tl, detail])
        for e in s.hits:
            if e is not c:
                rows.append(["DOUBLON (alternative)", e.disk, s.name, e.path,
                             e.size if e.size is not None else "", "", "", tl, ""])
    for it in report.ignored:
        rows.append(["IGNORÉ", "", it.name, "", "", "", "", it.timeline,
                     IGNORED_LABELS.get(it.kind, it.kind) + (f" [{it.detail}]" if it.detail else "")])
    return rows


def write_csv(report, path, mounted=is_mounted):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        w.writerows(report_rows(report, mounted))


def human_size(n):
    n = float(n or 0)
    for unit in ("o", "Ko", "Mo", "Go", "To"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "o" else f"{int(n)} o"
        n /= 1024
    return f"{n:.1f} Po"
