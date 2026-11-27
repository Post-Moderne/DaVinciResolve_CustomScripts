#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Langue de l'interface (français par défaut, anglais au choix).

Les textes français restent dans le code et servent de clés : tr("Dossier : {0}", chemin)
cherche la traduction dans i18n_en.EN, puis applique les arguments. Un texte sans
traduction s'affiche en français — jamais d'erreur.

Règles pour ajouter un texte :
  • l'écrire en français dans tr(...), avec {0}, {1}… pour les parties variables ;
  • ajouter la traduction dans i18n_en.py (tests/test_i18n.py signale les oublis) ;
  • une valeur interne (comparée, sauvegardée dans une config) reste en français et n'est
    traduite qu'à l'affichage : voir choices() / source().
  • ne pas appeler tr() au chargement d'un module (constante) : la langue peut changer
    pendant que le lanceur est ouvert.

Ce module vit dans pm_tools/ pour être copié par les updaters antérieurs à la v1.9.0,
qui ne connaissent pas de nouveau fichier à la racine de scripts/.
"""

import json
import os

from pm_tools.i18n_en import EN

LANGUAGES = {"fr": "Français", "en": "English"}
DEFAULT = "fr"

_USER = os.environ.get("USER") or os.environ.get("LOGNAME") or "unknown"
# Même racine que pm_common.LOG_ROOT (HOME est remappé par le sandbox App Store).
CONFIG_PATH = f"/Users/{_USER}/Logs/PM-Suite/config/language.json"

_current = DEFAULT


def language():
    return _current


def tr(text, *args):
    """Texte dans la langue courante ; `args` remplit les {0}, {1}…"""
    if _current == "en":
        text = EN.get(text, text)
    return text.format(*args) if args else text


def choices(values):
    """Libellés traduits d'une liste de valeurs internes (pour un Combobox)."""
    return [tr(v) for v in values]


def source(label, values):
    """
    Inverse de choices() : la valeur interne affichée sous `label` (sinon `label` tel quel).
    Reconnaît les deux langues : une fenêtre ouverte avant un changement de langue garde
    ses anciens libellés.
    """
    return next((v for v in values if label in (v, EN.get(v, v))), label)


def load():
    """Relit la langue choisie sur ce poste (français si aucune ou illisible)."""
    global _current
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            code = json.load(f).get("language")
    except (OSError, ValueError, AttributeError):
        code = None
    _current = code if code in LANGUAGES else DEFAULT
    return _current


def set_language(code):
    """Change la langue et la mémorise. Retourne False si l'écriture a échoué."""
    global _current
    if code not in LANGUAGES:
        raise ValueError(f"Langue inconnue : {code!r}")
    _current = code
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({"language": code}, f)
        return True
    except OSError:
        return False
