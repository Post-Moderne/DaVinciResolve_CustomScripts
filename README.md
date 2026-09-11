# DaVinciResolve_CustomScripts

Collection de scripts utilitaires internes pour DaVinci Resolve, installables dans le menu Workspace > Scripts.

## À quoi ça sert

Chaque script s'exécute depuis DaVinci Resolve (Workspace > Scripts > Utility) et utilise l'API de scripting Resolve (`bmd.scriptapp("Resolve")`) pour agir directement sur le projet ouvert.

| Script | Fonction |
|---|---|
| `scripts/PM-FindAndReplace_1.1.py` | Recherche/remplacement dans les métadonnées des clips du Media Pool. |
| `scripts/PM-CSV-2-StartTC.py` | Met à jour le Start TC des clips à partir d'un `.csv` (colonnes `Name`/`Start`), avec relecture de confirmation après écriture. |
| `scripts/PM-DJI-TC.py` | Extrait l'heure de tournage depuis le nom de fichier (ex: DJI, autres presets caméra) et l'écrit dans le Start TC. |
| `scripts/bin_builder.py` | Crée plusieurs bins/sous-bins d'un coup dans le Media Pool — soit en miroir d'une arborescence de dossiers Finder, soit à partir d'une liste indentée saisie à la main. |

## Prérequis

- DaVinci Resolve 18+
- Aucune dépendance externe — uniquement la bibliothèque standard Python (`tkinter` inclus, fourni avec Resolve)

## Installation

Copier le(s) script(s) voulu(s) dans le dossier `Scripts/Utility` correspondant à la variante de Resolve installée :

**App Store (sandbox) :**
```
~/Library/Containers/com.blackmagic-design.DaVinciResolveAppStore/Data/Library/Application Support/Fusion/Scripts/Utility/
```

**DMG (standard) :**
```
/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/
```

Redémarrer Resolve (ou rafraîchir le menu Scripts). Les outils apparaissent ensuite sous **Workspace > Scripts > Utility**.

## Structure du projet

```
scripts/
  PM-FindAndReplace_1.1.py
  PM-CSV-2-StartTC.py
  PM-DJI-TC.py
  bin_builder.py
```

## Limitations connues

- **Déploiement manuel** : chaque script doit être copié à la main sur la machine de chaque monteur, dans le bon dossier selon sa variante de Resolve (App Store vs DMG) — pas de mécanisme de mise à jour centralisé pour l'instant. Une solution avait été explorée via des liens symboliques vers un dossier réseau partagé (comme c'est déjà le cas pour les Fuses/Templates Fusion de la compagnie), mais elle a été mise de côté pour l'instant.
- Dépendance à `tkinter` fourni par l'installation Python embarquée de Resolve — à vérifier après une mise à jour majeure de Resolve, certaines versions ayant eu des soucis connus avec `tkinter` sur macOS.

## Contact

Anthony — pour toute question sur ce projet
