#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SnapDrive — plan et exécution de l'import des sources des disques montés.
Sans Tk ni pm_common : le media pool Resolve est reçu en paramètre (donc testable avec
un faux media pool).

PRINCIPE
─────────
• plan_import() : à partir du rapport d'analyse, ne garde que les sources dont le disque
  retenu est monté MAINTENANT (la priorité des disques départage les doublons).
• run_import() : pour chaque disque, crée le bin « _SnapDrive/<DISQUE> » au besoin, ignore
  les fichiers déjà dans le projet (comparaison par chemin) et importe le reste par chemin
  complet. Relancer est donc sans danger. Les timelines ne sont jamais touchées.
"""

import os
import unicodedata
from collections import OrderedDict, namedtuple

from pm_tools.snapdrive import is_mounted
from pm_tools.snapdrive_analysis import choose_entry

ROOT_BIN = "_SnapDrive"

Plan = namedtuple("Plan", "by_disk waiting")      # by_disk : disque → [(SourceResult, Entry)]
Result = namedtuple("Result", "disk name path status detail")
# status : "imported", "present", "absent" (dans le SnapDrive mais pas sur le disque),
#          "error", "skipped" (séquence d'images : non gérée en v1)


def norm_path(p):
    """Clé de comparaison de chemins : normalisé, Unicode NFC, insensible à la casse."""
    return unicodedata.normalize("NFC", os.path.normpath(p or "")).lower()


def plan_import(report, priority=(), mounted=is_mounted):
    """Sources à importer par disque monté ; `waiting` = sources trouvées dont aucun disque n'est monté."""
    by_disk, waiting = OrderedDict(), []
    for s in report.sources:
        if not s.hits:
            continue
        e = choose_entry(s.hits, priority, mounted)
        if mounted(e.disk):
            by_disk.setdefault(e.disk, []).append((s, e))
        else:
            waiting.append(s)
    for disk in by_disk:
        by_disk[disk].sort(key=lambda se: se[0].name.lower())
    return Plan(OrderedDict(sorted(by_disk.items(), key=lambda kv: kv[0].lower())), waiting)


# ── Media pool Resolve ─────────────────────────────────────────────────────────
def collect_existing_paths(folder):
    """Chemins (normalisés) de tous les clips du media pool, sous-bins compris."""
    paths, stack = set(), [folder]
    while stack:
        f = stack.pop()
        for clip in f.GetClipList() or []:
            p = clip.GetClipProperty("File Path")
            if p:
                paths.add(norm_path(p))
        stack.extend(f.GetSubFolderList() or [])
    return paths


def ensure_bin(media_pool, parent, name):
    """Sous-bin `name` de `parent` (créé s'il n'existe pas). None si Resolve refuse."""
    for sub in parent.GetSubFolderList() or []:
        if sub.GetName() == name:
            return sub
    return media_pool.AddSubFolder(parent, name)


def run_import(media_pool, plan, existing=None, file_exists=os.path.isfile, progress=None):
    """
    Importe `plan` (voir plan_import). Retourne la liste de Result.
    `existing` : chemins déjà dans le projet (collect_existing_paths) ; mis à jour au fil de l'eau.
    `progress(i, total, result)` est appelé après chaque fichier.
    """
    root = media_pool.GetRootFolder()
    if existing is None:
        existing = collect_existing_paths(root)
    original = media_pool.GetCurrentFolder()
    total = sum(len(v) for v in plan.by_disk.values())
    results, done = [], 0
    try:
        for disk, pairs in plan.by_disk.items():
            target = None                       # bin créé seulement si on a quelque chose à y mettre
            for source, entry in pairs:
                path = entry.path
                key = norm_path(path)
                if entry.type == "sequence":
                    r = Result(disk, source.name, path, "skipped", "séquence d'images : non gérée en v1")
                elif key in existing:
                    r = Result(disk, source.name, path, "present", "déjà dans le projet")
                elif not file_exists(path):
                    r = Result(disk, source.name, path, "absent", "présent dans le SnapDrive mais absent du disque")
                else:
                    r, target = _import_one(media_pool, root, disk, target, source, path)
                    if r.status == "imported":
                        existing.add(key)
                results.append(r)
                done += 1
                if progress:
                    progress(done, total, r)
    finally:
        if original:
            media_pool.SetCurrentFolder(original)
    return results


def _import_one(media_pool, root, disk, target, source, path):
    try:
        if target is None:
            top = ensure_bin(media_pool, root, ROOT_BIN)
            target = ensure_bin(media_pool, top, disk) if top else None
            if target is None:
                return Result(disk, source.name, path, "error",
                              f"impossible de créer le bin {ROOT_BIN}/{disk}"), None
        media_pool.SetCurrentFolder(target)
        items = media_pool.ImportMedia([path])
    except Exception as e:                     # l'API Resolve peut lever : on garde un message de tech
        return Result(disk, source.name, path, "error", f"exception Resolve : {e}"), target
    if not items:
        return Result(disk, source.name, path, "error", "Resolve a refusé l'import (format non reconnu ?)"), target
    return Result(disk, source.name, path, "imported", ""), target


def summarize(results):
    """Compteurs par statut + phrase de résumé."""
    c = {k: 0 for k in ("imported", "present", "absent", "error", "skipped")}
    for r in results:
        c[r.status] += 1
    text = f"{c['imported']} importé(s), {c['present']} déjà présent(s), {c['error']} en erreur"
    if c["absent"]:
        text += f", {c['absent']} absent(s) du disque"
    if c["skipped"]:
        text += f", {c['skipped']} séquence(s) non gérée(s)"
    return c, text
