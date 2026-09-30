#!/bin/bash
# Installeur PM Suite — Post-Moderne
# Double-clic : installe (ou réinstalle) la PM Suite pour DaVinci Resolve.
#  • Utilise le dossier scripts/ à côté de ce fichier s'il existe (mode hors réseau),
#    sinon télécharge la dernière version depuis GitHub.
#  • Détecte Resolve App Store et/ou DMG et installe dans chacun.
#  • Écrit un log dans ~/Logs/PM-Suite/install/ (à envoyer en cas de problème).
# Première ouverture : clic droit > Ouvrir (Gatekeeper bloque les .command téléchargés).

REPO="Post-Moderne/DaVinciResolve_CustomScripts"
ZIP_URL="${PM_UPDATE_ZIP_URL:-https://codeload.github.com/$REPO/zip/refs/heads/main}"

LOG_DIR="$HOME/Logs/PM-Suite/install"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/$(date +%Y-%m-%d_%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1

pause() { [ -z "$PM_NO_PAUSE" ] && { echo; read -r -p "Appuie sur Entrée pour fermer…" _; }; }
fail() { echo; echo "✗ ERREUR : $1"; echo "Log : $LOG"; pause; exit 1; }

echo "PM Suite — installation ($(date))"

# ── Source ─────────────────────────────────────────────────────────────────────
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$HERE/scripts/PM-Suite.py" ]; then
  SRC="$HERE/scripts"
  echo "Source : dossier local ($SRC)"
else
  TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
  echo "Téléchargement depuis GitHub…"
  curl -fsSL --max-time 120 "$ZIP_URL" -o "$TMP/repo.zip" || fail "téléchargement impossible (connexion ?)"
  unzip -q "$TMP/repo.zip" -d "$TMP" || fail "archive illisible"
  SRC="$(ls -d "$TMP"/*/scripts 2>/dev/null | head -1)"
  [ -f "$SRC/PM-Suite.py" ] || fail "archive inattendue (scripts/PM-Suite.py introuvable)"
fi
for f in PM-Suite.py pm_common.py pm_update.py VERSION pm_tools/__init__.py; do
  [ -e "$SRC/$f" ] || fail "source incomplète : $f manquant"
done
VERSION="$(tr -d '[:space:]' < "$SRC/VERSION")"

# ── Copie (sudo uniquement si le dossier n'est pas modifiable) ─────────────────
install_to() {  # $1 = dossier Scripts Fusion, $2 = dossier Modules
  local UTIL="$1/Utility" MODS="$2" SUDO=""
  echo; echo "→ Scripts : $UTIL"; echo "→ Modules : $MODS"
  mkdir -p "$UTIL" 2>/dev/null || sudo mkdir -p "$UTIL" || return 1
  [ -d "$MODS" ] || mkdir -p "$MODS" 2>/dev/null || sudo mkdir -p "$MODS" || return 1
  [ -w "$MODS" ] || { echo "  (droits admin requis pour Modules)"; SUDO=sudo; }
  $SUDO rm -rf "$MODS/pm_tools" "$MODS/PM-Suite.py"      # PM-Suite.py ne doit PAS rester dans Modules
  $SUDO cp "$SRC/pm_common.py" "$SRC/pm_update.py" "$SRC/VERSION" "$MODS/" || return 1
  $SUDO cp -R "$SRC/pm_tools" "$MODS/pm_tools" || return 1
  $SUDO find "$MODS/pm_tools" \( -name '__pycache__' -o -name '.DS_Store' \) -prune -exec rm -rf {} + 2>/dev/null
  cp "$SRC/PM-Suite.py" "$UTIL/PM-Suite.py" || return 1
  echo "  ✓ installé"
}

FOUND=0
APPSTORE="$HOME/Library/Containers/com.blackmagic-design.DaVinciResolveAppStore/Data/Library/Application Support"
if [ -d "$APPSTORE/Fusion/Scripts" ]; then
  FOUND=1; echo; echo "Resolve App Store détecté."
  install_to "$APPSTORE/Fusion/Scripts" "$APPSTORE/Developer/Scripting/Modules" || fail "copie App Store échouée"
fi
DMG="$HOME/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts"
if [ -d "$DMG" ]; then
  FOUND=1; echo; echo "Resolve (DMG) détecté."
  install_to "$DMG" "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules" || fail "copie DMG échouée"
fi
[ "$FOUND" = 1 ] || fail "aucune installation de DaVinci Resolve trouvée. Lance Resolve une première fois, puis réessaie."

echo; echo "✓ PM Suite v$VERSION installée."
echo "Dans Resolve : Workspace > Scripts > Utility > PM-Suite (redémarre Resolve si absent)."
echo "Log : $LOG"
pause
