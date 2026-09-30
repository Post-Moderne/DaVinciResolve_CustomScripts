# DaVinciResolve_CustomScripts

PM Suite — outils utilitaires internes pour DaVinci Resolve, regroupés dans une seule app accessible depuis le menu Workspace > Scripts.

## À quoi ça sert

**PM Suite** est le point d'entrée unique : une fenêtre lanceur qui donne accès aux 4 outils ci-dessous, chacun agissant directement sur le projet Resolve ouvert via l'API de scripting (`bmd.scriptapp("Resolve")`).

| Outil | Fonction |
|---|---|
| Metadata Find & Replace | Recherche/remplacement dans les métadonnées des clips du Media Pool. |
| CSV → Start TC | Met à jour le Start TC des clips à partir d'un `.csv` (colonnes `Name`/`Start`), avec relecture de confirmation après écriture. |
| Timecode Extractor | Extrait l'heure de tournage depuis le nom de fichier (ex: DJI, autres presets caméra) et l'écrit dans le Start TC. |
| BinBuilder | Crée plusieurs bins/sous-bins d'un coup dans le Media Pool — soit en miroir d'une arborescence de dossiers Finder, soit à partir d'une liste indentée saisie à la main. |

## Prérequis

- DaVinci Resolve 18+
- Aucune dépendance externe — uniquement la bibliothèque standard Python (`tkinter` inclus, fourni avec Resolve)

## Installation

Deux emplacements différents selon le type de fichier, pour qu'une seule entrée ("PM-Suite") apparaisse dans le menu Scripts (Resolve liste tout `.py` présent directement dans `Scripts/Utility`) :

- **`scripts/PM-Suite.py`** → dossier `Scripts/Utility`
- **`scripts/pm_common.py`, `scripts/VERSION` et `scripts/pm_tools/`** → dossier `Developer/Scripting/Modules` (à côté du module `DaVinciResolveScript` fourni par Resolve)

**App Store (sandbox) :**
```
Scripts/Utility  → ~/Library/Containers/com.blackmagic-design.DaVinciResolveAppStore/Data/Library/Application Support/Fusion/Scripts/Utility/
Modules          → ~/Library/Containers/com.blackmagic-design.DaVinciResolveAppStore/Data/Library/Application Support/Developer/Scripting/Modules/
```

**DMG (standard) :**
```
Scripts/Utility  → /Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/
Modules          → /Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules/
```

Redémarrer Resolve (ou rafraîchir le menu Scripts). L'app apparaît ensuite sous **Workspace > Scripts > Utility > PM-Suite**.

*(Un installeur à double-clic automatisant ce découpage est prévu — voir Roadmap.)*

## Structure du projet

```
scripts/
  PM-Suite.py           # point d'entrée — seul fichier à mettre dans Scripts/Utility
  pm_common.py           # connexion Resolve, thème UI, logging, boucle d'événements
  VERSION                 # source de vérité pour la version installée
  pm_tools/
    __init__.py
    find_replace.py       # Metadata Find & Replace
    csv_to_tc.py           # CSV → Start TC
    dji_tc.py               # Timecode Extractor
    bin_builder.py         # BinBuilder
```

## Roadmap

- [ ] Installeur à double-clic (copie automatique vers les bons dossiers selon la variante détectée, log d'erreur)
- [ ] App de mise à jour (affiche la version installée, vérifie/récupère la dernière version publiée sur ce repo)

## Limitations connues

- **Déploiement manuel pour l'instant** : les fichiers doivent être copiés à la main dans les deux dossiers ci-dessus, selon la variante de Resolve (App Store vs DMG) — l'installeur automatisera ça (voir Roadmap).
- Dépendance à `tkinter` fourni par l'installation Python embarquée de Resolve — à vérifier après une mise à jour majeure de Resolve, certaines versions ayant eu des soucis connus avec `tkinter` sur macOS.
- Les fichiers doivent être copiés localement sur chaque poste (pas de lien symbolique vers un volume réseau) pour que la suite fonctionne aussi hors réseau du studio.

## Contact

Anthony — pour toute question sur ce projet
