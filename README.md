# DaVinciResolve_CustomScripts

PM Suite — outils utilitaires internes pour DaVinci Resolve, regroupés dans une seule app accessible depuis le menu Workspace > Scripts.

## À quoi ça sert

**PM Suite** est le point d'entrée unique : une fenêtre lanceur qui donne accès aux 6 outils ci-dessous, chacun agissant directement sur le projet Resolve ouvert via l'API de scripting (`bmd.scriptapp("Resolve")`).

| Outil | Fonction |
|---|---|
| Metadata Find & Replace | Recherche/remplacement dans les métadonnées des clips du Media Pool. |
| CSV → Start TC | Met à jour le Start TC des clips à partir d'un `.csv` (colonnes `Name`/`Start`), avec relecture de confirmation après écriture. |
| CSV → VFX ID | Renomme les clips de la timeline avec les VFX ID d'un `.csv` (colonnes VFX ID + TC record) : le TC record est comparé au point d'entrée des clips (piste au choix), avec aperçu avant application et journal des anciens noms. |
| Markers → Stills | Exporte un still (PNG, JPG, TIFF ou DPX) à chaque marker de la timeline active, nommé d'après le nom du marker (repli : notes, puis TC). Filtre par couleur de marker ou toutes les couleurs, aperçu des noms de fichiers avant export, doublons suffixés (`_2`, `_3`…) sans jamais écraser, journal d'export. |
| Timecode Extractor | Extrait l'heure de tournage depuis le nom de fichier (ex: DJI, autres presets caméra) et l'écrit dans le Start TC. |
| BinBuilder | Crée plusieurs bins/sous-bins d'un coup dans le Media Pool — soit en miroir d'une arborescence de dossiers Finder, soit à partir d'une liste indentée saisie à la main. |

## Prérequis

- DaVinci Resolve 18+
- Aucune dépendance externe — uniquement la bibliothèque standard Python (`tkinter` inclus, fourni avec Resolve)

## Installation

### Automatique (recommandé)

Double-cliquer sur **`Install-PM-Suite.command`** (première ouverture : clic droit > Ouvrir). Il détecte Resolve App Store et/ou DMG et copie tout au bon endroit. Si un dossier système demande les droits admin (DMG), le mot de passe est demandé dans le Terminal. Les fichiers du dossier `scripts/` voisin sont utilisés s'il existe (mode hors réseau), sinon la dernière version est téléchargée depuis GitHub. Le log est écrit dans `~/Logs/PM-Suite/install/`.

### Manuelle

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

### Mises à jour

Dans la PM-Suite, bouton **Mises à jour…** : affiche la version installée, vérifie celle de GitHub et installe la nouvelle si elle est plus récente (sauvegarde + restauration automatique en cas d'échec ; relancer ensuite la PM-Suite). Sur une installation DMG dont le dossier Modules est protégé, relancer plutôt l'installeur.

**Publier une version** : incrémenter `scripts/VERSION`, committer, pousser sur `main`, puis poser et pousser le tag correspondant (`git tag -a vX.Y.Z -m "..." && git push origin vX.Y.Z`). Sans incrément, les postes ne voient aucune mise à jour.

## Structure du projet

```
scripts/
  PM-Suite.py           # point d'entrée — seul fichier à mettre dans Scripts/Utility
  pm_common.py           # connexion Resolve, thème UI, logging, boucle d'événements
  pm_update.py            # fenêtre de mise à jour (bouton du lanceur)
  VERSION                 # source de vérité pour la version installée
  pm_tools/
    __init__.py
    find_replace.py       # Metadata Find & Replace
    csv_to_tc.py           # CSV → Start TC
    dji_tc.py               # Timecode Extractor
    csv_to_vfxid.py        # CSV → VFX ID
    markers_to_stills.py   # Markers → Stills
    bin_builder.py         # BinBuilder
Install-PM-Suite.command  # installeur à double-clic
```

## Roadmap

- [x] Installeur à double-clic (`Install-PM-Suite.command`)
- [x] Mise à jour depuis la PM-Suite (bouton « Mises à jour… »)
- [x] Tags de version sur GitHub (`vX.Y.Z` à chaque release)
- [ ] Validation de l'installeur sur un poste Resolve DMG

## Limitations connues

- **Installation DMG non validée** : l'installeur et l'updater ont été testés sur Resolve App Store ; sur DMG (dossiers système, droits admin), l'installeur est à valider.
- **Markers → Stills** : le still reflète le grade actuel de la timeline ; l'export vers un volume réseau depuis Resolve App Store (sandbox) n'a pas encore été vérifié.
- Dépendance à `tkinter` fourni par l'installation Python embarquée de Resolve — à vérifier après une mise à jour majeure de Resolve, certaines versions ayant eu des soucis connus avec `tkinter` sur macOS.
- Les fichiers doivent être copiés localement sur chaque poste (pas de lien symbolique vers un volume réseau) pour que la suite fonctionne aussi hors réseau du studio.

## Contact

Anthony — pour toute question sur ce projet
