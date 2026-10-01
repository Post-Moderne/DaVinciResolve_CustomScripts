#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SnapDrive — parseur des scans de disques (.html) et règle de match des sources.
Module interne de la PM Suite (utilisé par snapdrive_loader.py). Logique pure :
aucune dépendance à Tk, à Resolve ni à pm_common, donc testable hors Resolve.

FORMAT D'UN SNAPDRIVE
──────────────────────
Les données sont dans un <script>, un appel JavaScript par dossier :

    D.p(["/Volumes/DISQUE/a/b*0*1773835504","clip.mxf*189718665376*1773836097*Fichier MXF*null", ..., 32937,"15*16"]);

  [0]       chemin_du_dossier*0*timestamp
  [1..n-2]  un fichier : nom*taille*timestamp*type*info
            (type « sequence » = séquence d'images, info = nombre d'images)
  [n-2]     taille totale du dossier
  [n-1]     IDs des sous-dossiers, séparés par « * »

Chaque tableau est du JSON valide. On ne s'ancre pas sur le début de ligne (la
première ligne D.p est indentée). Le nom du disque est le segment après /Volumes/.
"""

import json
import os
import re
from collections import defaultdict, namedtuple

# Un appel D.p(...) : tableau JSON suivi de « ); » puis fin de ligne, autre D.p( ou </script>.
# Le lookahead évite de s'arrêter sur un « ]); » qui apparaîtrait dans un nom de fichier.
_DP_RE = re.compile(r'D\.p\((\[.*?\])\);(?=\s*(?:D\.p\(|$|</script>))', re.M)
_VOLUME_RE = re.compile(r'^/Volumes/([^/]+)')
_TITLE_RE = re.compile(r'<title>(.*?)</title>', re.I | re.S)

Entry = namedtuple("Entry", "disk folder name size mtime type info")
Entry.path = property(lambda self: self.folder.rstrip("/") + "/" + self.name)


class SnapDriveError(Exception):
    """Erreur de lecture d'un SnapDrive, message destiné à un tech."""


# ── Règle de match ─────────────────────────────────────────────────────────────
def normalize(name):
    """Clé de comparaison : trim des espaces + insensible à la casse."""
    return (name or "").strip().lower()


def stem(filename):
    """Nom de fichier sans (dernière) extension : 'A_001.mxf' → 'A_001'."""
    base = (filename or "").strip()
    head, dot, _ = base.rpartition(".")
    return head if dot and head else base


def match_key(filename):
    """Clé d'un fichier source, à comparer avec normalize(nom du clip)."""
    return normalize(stem(filename))


# ── Parsing ────────────────────────────────────────────────────────────────────
class SnapDrive:
    """Un disque scanné : nom, fichier .html d'origine et liste des Entry (fichiers seulement)."""

    def __init__(self, disk, source, entries, title=""):
        self.disk = disk
        self.source = source
        self.entries = entries
        self.title = title

    def __len__(self):
        return len(self.entries)

    def total_size(self):
        return sum(e.size or 0 for e in self.entries)


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_file_item(item, folder, disk):
    """'nom*taille*ts*type*info' → Entry. Découpe par la droite : le nom peut contenir « * »."""
    parts = item.rsplit("*", 4)
    if len(parts) != 5:                         # un fichier a toujours 5 champs
        return None
    name, size, ts, ftype, info = parts
    return Entry(disk, folder, name, _to_int(size), _to_int(ts), ftype,
                 None if info in ("", "null") else info)


def parse_snapdrive_text(text, source="", disk=None):
    """
    Parse le contenu d'un SnapDrive. `disk` force le nom du disque ; sinon il est déduit
    des chemins (/Volumes/<NOM>), puis du <title>, puis du nom du fichier source.
    Les blocs D.p illisibles sont ignorés mais comptés (attribut `bad_blocks` de l'objet).
    """
    entries, bad = [], 0
    detected = None
    for m in _DP_RE.finditer(text):
        try:
            block = json.loads(m.group(1))
            folder = str(block[0]).split("*")[0]
        except (ValueError, IndexError):
            bad += 1
            continue
        if detected is None:
            vm = _VOLUME_RE.match(folder)
            if vm:
                detected = vm.group(1)
        name_disk = disk or detected or ""
        for item in block[1:-2]:
            if isinstance(item, str):
                e = _parse_file_item(item, folder, name_disk)
                if e:
                    entries.append(e)

    tm = _TITLE_RE.search(text)
    title = tm.group(1).strip() if tm else ""
    final = disk or detected or title or os.path.splitext(os.path.basename(source))[0]
    if final != (disk or detected or ""):          # nom connu seulement après coup (pas de /Volumes/)
        entries = [e._replace(disk=final) for e in entries]
    drive = SnapDrive(final, source, entries, title)
    drive.bad_blocks = bad
    return drive


def parse_snapdrive_file(path):
    """Lit un .html SnapDrive. Lève SnapDriveError avec un message clair si illisible ou vide."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        raise SnapDriveError(f"Lecture impossible : {os.path.basename(path)} ({e.strerror or e})")
    drive = parse_snapdrive_text(text, source=path)
    if not drive.entries:
        raise SnapDriveError(f"Aucune donnée SnapDrive reconnue dans {os.path.basename(path)} "
                             f"(appels D.p introuvables ou vides).")
    return drive


class SnapDriveIndex:
    """Index de tous les disques : clé de match → liste d'Entry (un disque peut apparaître plusieurs fois)."""

    def __init__(self):
        self.drives = {}                        # nom de disque → SnapDrive
        self._by_key = defaultdict(list)

    def add(self, drive):
        if drive.disk in self.drives:           # deux scans du même disque : le dernier remplace
            self._remove(drive.disk)
        self.drives[drive.disk] = drive
        for e in drive.entries:
            self._by_key[match_key(e.name)].append(e)

    def _remove(self, disk):
        for key in list(self._by_key):
            kept = [e for e in self._by_key[key] if e.disk != disk]
            if kept:
                self._by_key[key] = kept
            else:
                del self._by_key[key]
        del self.drives[disk]

    def lookup(self, clip_name):
        """Entrées dont le nom sans extension == nom du clip (exact, insensible à la casse, trim)."""
        return list(self._by_key.get(normalize(clip_name), ()))

    def __len__(self):
        return sum(len(d) for d in self.drives.values())


def load_folder(folder):
    """
    Parse tous les .html du dossier (non récursif). Retourne (SnapDriveIndex, erreurs)
    où erreurs = liste de messages lisibles : un fichier invalide n'arrête pas les autres.
    """
    index, errors = SnapDriveIndex(), []
    try:
        names = sorted(n for n in os.listdir(folder) if n.lower().endswith((".html", ".htm")))
    except OSError as e:
        raise SnapDriveError(f"Dossier illisible : {folder} ({e.strerror or e})")
    for n in names:
        try:
            index.add(parse_snapdrive_file(os.path.join(folder, n)))
        except SnapDriveError as e:
            errors.append(str(e))
    return index, errors


def is_mounted(disk, volumes_root="/Volumes"):
    """Un disque est monté si /Volumes/<NOM> existe."""
    return os.path.isdir(os.path.join(volumes_root, disk))
