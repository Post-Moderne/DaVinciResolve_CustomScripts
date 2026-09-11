#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BinBuilder – Post-Moderne
==========================

Outil pour DaVinci Resolve permettant de créer plusieurs bins/sous-bins
d'un coup dans le Media Pool, selon deux modes :

  1. Mode Miroir  : reproduit récursivement l'arborescence d'un dossier
                     Finder réel en bins/sous-bins Resolve.
  2. Mode Manuel   : crée une arborescence de bins à partir d'une liste
                     de noms indentée par tabulations, saisie à la main.

Installation :
  Placer ce fichier dans le dossier Utility des scripts Resolve, par exemple :
    ~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/

  Le script devient alors accessible depuis Resolve via :
    Workspace > Scripts > BinBuilder

Auteur : Post-Moderne / Anthony
"""

import os
import sys
import fnmatch
from datetime import datetime

import tkinter as tk
from tkinter import ttk, filedialog, messagebox


# ---------------------------------------------------------------------------
# Connexion à l'API Resolve
# ---------------------------------------------------------------------------
# Quand ce script est lancé depuis Workspace > Scripts, Resolve injecte
# normalement une variable globale `resolve` déjà connectée. On garde un
# fallback manuel au cas où le script serait testé autrement (par ex. relancé
# depuis la console Resolve sans passer par le menu Scripts).
try:
    resolve  # noqa: F821 - injectée par Resolve à l'exécution
except NameError:
    import DaVinciResolveScript as dvr_script  # type: ignore
    resolve = dvr_script.scriptapp("Resolve")

if resolve is None:
    raise RuntimeError(
        "Impossible de se connecter à DaVinci Resolve. "
        "Ce script doit être lancé depuis Resolve (Workspace > Scripts)."
    )


# ---------------------------------------------------------------------------
# Emplacement du log
# ---------------------------------------------------------------------------
# Note : dans la version App Store de Resolve, os.path.expanduser("~") peut
# renvoyer un chemin sandboxé qui ne correspond pas au vrai dossier utilisateur.
# On reconstruit donc le home réel à partir de la variable d'environnement USER.
_home_reel = f"/Users/{os.environ.get('USER', 'unknown')}"
LOG_DIR = os.path.join(_home_reel, "Logs", "BinBuilder")


def ecrire_log(journal_lignes):
    """Écrit le journal d'exécution dans un fichier horodaté. Retourne le chemin du log."""
    os.makedirs(LOG_DIR, exist_ok=True)
    horodatage = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    chemin_log = os.path.join(LOG_DIR, f"{horodatage}.log")
    with open(chemin_log, "w", encoding="utf-8") as f:
        f.write(f"BinBuilder – exécution du {datetime.now().isoformat()}\n")
        f.write("=" * 60 + "\n")
        for ligne in journal_lignes:
            f.write(ligne + "\n")
    return chemin_log


# ---------------------------------------------------------------------------
# Structure d'arbre
# ---------------------------------------------------------------------------
class BinNode:
    """
    Représente un bin à créer, avec ses éventuels sous-bins.
    On utilise une classe (et non un dict) pour permettre des noms
    dupliqués au même niveau, ce que Resolve autorise.
    """

    def __init__(self, name):
        self.name = name
        self.children = []  # liste de BinNode, ordre préservé

    def __repr__(self):
        return f"BinNode({self.name!r}, {len(self.children)} enfant(s))"


# ---------------------------------------------------------------------------
# Mode Manuel : parsing d'une liste indentée par tabulations
# ---------------------------------------------------------------------------
def parser_liste_indentee(texte):
    """
    Transforme un texte indenté par tabulations en une liste de BinNode
    (les racines de l'arbre, éventuellement plusieurs bins de même niveau).

    Exemple d'entrée :
        VFX
        \tPlates
        \tComp
        Sound
        \tSFX
        \tDialogue

    Lève ValueError si l'indentation est incohérente (ex: saut de plus
    d'un niveau d'un coup).
    """
    racine_virtuelle = BinNode("__racine__")
    pile = [(-1, racine_virtuelle)]  # (niveau, node)

    for numero_ligne, ligne_brute in enumerate(texte.split("\n"), start=1):
        if not ligne_brute.strip():
            continue  # on ignore les lignes vides

        sans_tabs = ligne_brute.lstrip("\t")
        niveau = len(ligne_brute) - len(sans_tabs)
        nom = sans_tabs.strip()

        if not nom:
            continue

        # Une ligne ne peut descendre que d'un niveau à la fois par rapport
        # au dernier niveau connu dans la pile, sinon la hiérarchie est ambiguë.
        niveau_max_autorise = pile[-1][0] + 1
        if niveau > niveau_max_autorise:
            raise ValueError(
                f"Ligne {numero_ligne} ('{nom}') : indentation incohérente "
                f"(saut de niveau non autorisé)."
            )

        # On remonte la pile jusqu'à trouver le bon parent
        while pile and pile[-1][0] >= niveau:
            pile.pop()

        parent = pile[-1][1]
        node = BinNode(nom)
        parent.children.append(node)
        pile.append((niveau, node))

    return racine_virtuelle.children


# ---------------------------------------------------------------------------
# Mode Miroir : construction de l'arbre à partir d'un dossier Finder réel
# ---------------------------------------------------------------------------
def dossier_est_exclu(nom, patterns_exclusion):
    """Retourne True si le nom du dossier doit être ignoré."""
    if nom.startswith("."):
        return True
    for pattern in patterns_exclusion:
        if fnmatch.fnmatch(nom, pattern):
            return True
    return False


def construire_arbre_depuis_dossier(chemin, patterns_exclusion):
    """
    Parcourt récursivement `chemin` et construit un BinNode représentant
    ce dossier, avec un enfant par sous-dossier (fichiers ignorés : seuls
    les dossiers deviennent des bins).
    """
    node = BinNode(os.path.basename(chemin.rstrip("/")) or chemin)

    try:
        sous_dossiers = sorted(
            e.name for e in os.scandir(chemin) if e.is_dir()
        )
    except PermissionError:
        # On ne bloque pas tout l'arbre pour un dossier illisible :
        # on le signale simplement en le laissant sans enfants.
        return node

    for nom in sous_dossiers:
        if dossier_est_exclu(nom, patterns_exclusion):
            continue
        node.children.append(
            construire_arbre_depuis_dossier(os.path.join(chemin, nom), patterns_exclusion)
        )

    return node


# ---------------------------------------------------------------------------
# Création effective des bins dans Resolve
# ---------------------------------------------------------------------------
def creer_bins(media_pool, dossier_parent_resolve, arbre, journal):
    """
    Crée récursivement les bins définis par `arbre` (liste de BinNode)
    sous `dossier_parent_resolve`. Alimente `journal` avec le résultat
    de chaque création (succès ou échec).
    """
    for node in arbre:
        nouveau_bin = media_pool.AddSubFolder(dossier_parent_resolve, node.name)
        if nouveau_bin:
            journal.append(f"OK     : '{node.name}' créé sous '{dossier_parent_resolve.GetName()}'")
            if node.children:
                creer_bins(media_pool, nouveau_bin, node.children, journal)
        else:
            journal.append(f"ERREUR : échec de création pour '{node.name}' sous '{dossier_parent_resolve.GetName()}'")


# ---------------------------------------------------------------------------
# Interface graphique
# ---------------------------------------------------------------------------
class BinBuilderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("BinBuilder – Post-Moderne")
        self.root.geometry("620x620")

        self.projet = resolve.GetProjectManager().GetCurrentProject()
        if self.projet is None:
            messagebox.showerror(
                "BinBuilder",
                "Aucun projet Resolve n'est actuellement ouvert.\n"
                "Ouvre un projet avant de lancer BinBuilder."
            )
            self.root.destroy()
            return

        self.media_pool = self.projet.GetMediaPool()
        self.arbre_en_attente = None  # liste de BinNode, alimentée par "Prévisualiser"

        self._construire_interface()

    # -- Construction de l'UI ------------------------------------------------
    def _construire_interface(self):
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=False, padx=10, pady=10)

        self._construire_onglet_miroir(notebook)
        self._construire_onglet_manuel(notebook)

        # -- Destination --
        cadre_destination = ttk.LabelFrame(self.root, text="Où créer les bins")
        cadre_destination.pack(fill="x", padx=10, pady=(0, 10))

        self.destination_var = tk.StringVar(value="racine")
        ttk.Radiobutton(
            cadre_destination, text="Racine du Media Pool",
            variable=self.destination_var, value="racine"
        ).pack(anchor="w", padx=10, pady=2)
        ttk.Radiobutton(
            cadre_destination, text="Bin actuellement sélectionné dans Resolve",
            variable=self.destination_var, value="selection"
        ).pack(anchor="w", padx=10, pady=2)

        # -- Aperçu --
        cadre_apercu = ttk.LabelFrame(self.root, text="Aperçu de l'arborescence à créer")
        cadre_apercu.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.arbre_apercu = ttk.Treeview(cadre_apercu, show="tree")
        self.arbre_apercu.pack(fill="both", expand=True, padx=5, pady=5)

        # -- Actions --
        cadre_actions = ttk.Frame(self.root)
        cadre_actions.pack(fill="x", padx=10, pady=(0, 10))

        self.bouton_creer = ttk.Button(
            cadre_actions, text="Créer les bins",
            command=self._creer_bins_clic, state="disabled"
        )
        self.bouton_creer.pack(side="right")

        self.label_statut = ttk.Label(self.root, text="", foreground="gray")
        self.label_statut.pack(fill="x", padx=10, pady=(0, 10))

    def _construire_onglet_miroir(self, notebook):
        onglet = ttk.Frame(notebook)
        notebook.add(onglet, text="Mode Miroir (dossier Finder)")

        ttk.Label(onglet, text="Dossier source :").pack(anchor="w", padx=10, pady=(10, 0))

        cadre_chemin = ttk.Frame(onglet)
        cadre_chemin.pack(fill="x", padx=10, pady=5)
        self.chemin_var = tk.StringVar(value="(aucun dossier sélectionné)")
        ttk.Label(cadre_chemin, textvariable=self.chemin_var, foreground="gray").pack(side="left", fill="x", expand=True)
        ttk.Button(cadre_chemin, text="Choisir…", command=self._choisir_dossier).pack(side="right")

        self.inclure_racine_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            onglet, text="Créer un bin pour le dossier sélectionné lui-même (pas seulement son contenu)",
            variable=self.inclure_racine_var
        ).pack(anchor="w", padx=10, pady=5)

        ttk.Label(onglet, text="Motifs à exclure (séparés par des virgules, syntaxe glob type *.tmp) :").pack(
            anchor="w", padx=10, pady=(10, 0)
        )
        self.exclusions_var = tk.StringVar(value="_historique*, node_modules, .git")
        ttk.Entry(onglet, textvariable=self.exclusions_var).pack(fill="x", padx=10, pady=5)
        ttk.Label(
            onglet, text="(les dossiers commençant par un point sont toujours exclus automatiquement)",
            foreground="gray"
        ).pack(anchor="w", padx=10)

        ttk.Button(
            onglet, text="Prévisualiser", command=self._previsualiser_miroir
        ).pack(anchor="e", padx=10, pady=15)

        self.chemin_dossier_source = None

    def _construire_onglet_manuel(self, notebook):
        onglet = ttk.Frame(notebook)
        notebook.add(onglet, text="Mode Manuel (liste indentée)")

        ttk.Label(
            onglet,
            text="Une entrée par ligne. Indentation par TABULATION pour créer un sous-bin."
        ).pack(anchor="w", padx=10, pady=(10, 5))

        self.zone_texte = tk.Text(onglet, height=14, wrap="none")
        self.zone_texte.pack(fill="both", expand=True, padx=10, pady=5)
        self.zone_texte.insert(
            "1.0",
            "VFX\n\tPlates\n\tComp\nSound\n\tSFX\n\tDialogue\n"
        )

        ttk.Button(
            onglet, text="Prévisualiser", command=self._previsualiser_manuel
        ).pack(anchor="e", padx=10, pady=10)

    # -- Actions ---------------------------------------------------------
    def _choisir_dossier(self):
        chemin = filedialog.askdirectory(title="Choisir le dossier à reproduire")
        if chemin:
            self.chemin_dossier_source = chemin
            self.chemin_var.set(chemin)

    def _previsualiser_miroir(self):
        if not self.chemin_dossier_source:
            messagebox.showwarning("BinBuilder", "Choisis d'abord un dossier source.")
            return

        patterns = [p.strip() for p in self.exclusions_var.get().split(",") if p.strip()]

        try:
            node_racine = construire_arbre_depuis_dossier(self.chemin_dossier_source, patterns)
        except Exception as e:
            messagebox.showerror("BinBuilder", f"Erreur lors de la lecture du dossier :\n{e}")
            return

        arbre = [node_racine] if self.inclure_racine_var.get() else node_racine.children

        if not arbre:
            messagebox.showinfo("BinBuilder", "Aucun sous-dossier trouvé (après filtrage). Rien à créer.")
            return

        self._afficher_apercu(arbre)

    def _previsualiser_manuel(self):
        texte = self.zone_texte.get("1.0", "end")
        if not texte.strip():
            messagebox.showwarning("BinBuilder", "La liste est vide.")
            return

        try:
            arbre = parser_liste_indentee(texte)
        except ValueError as e:
            messagebox.showerror("BinBuilder", f"Erreur de format :\n{e}")
            return

        if not arbre:
            messagebox.showinfo("BinBuilder", "Aucune entrée valide trouvée.")
            return

        self._afficher_apercu(arbre)

    def _afficher_apercu(self, arbre):
        """Peuple le Treeview d'aperçu et active le bouton de création."""
        self.arbre_apercu.delete(*self.arbre_apercu.get_children())

        def inserer(parent_tk, nodes):
            for node in nodes:
                item_id = self.arbre_apercu.insert(parent_tk, "end", text=node.name, open=True)
                if node.children:
                    inserer(item_id, node.children)

        inserer("", arbre)

        self.arbre_en_attente = arbre
        self.bouton_creer.config(state="normal")

        nb_total = self._compter_bins(arbre)
        self.label_statut.config(text=f"{nb_total} bin(s) prêt(s) à être créé(s). Vérifie l'aperçu ci-dessus.")

    def _compter_bins(self, arbre):
        total = 0
        for node in arbre:
            total += 1 + self._compter_bins(node.children)
        return total

    def _creer_bins_clic(self):
        if not self.arbre_en_attente:
            return

        if self.destination_var.get() == "racine":
            dossier_parent = self.media_pool.GetRootFolder()
        else:
            dossier_parent = self.media_pool.GetCurrentFolder()
            if dossier_parent is None:
                messagebox.showerror("BinBuilder", "Impossible de récupérer le bin sélectionné dans Resolve.")
                return

        journal = []
        creer_bins(self.media_pool, dossier_parent, self.arbre_en_attente, journal)

        chemin_log = ecrire_log(journal)

        nb_erreurs = sum(1 for l in journal if l.startswith("ERREUR"))
        nb_ok = len(journal) - nb_erreurs

        if nb_erreurs:
            messagebox.showwarning(
                "BinBuilder",
                f"{nb_ok} bin(s) créé(s), {nb_erreurs} erreur(s).\nDétail dans le log :\n{chemin_log}"
            )
        else:
            messagebox.showinfo(
                "BinBuilder",
                f"{nb_ok} bin(s) créé(s) avec succès.\nLog : {chemin_log}"
            )

        self.label_statut.config(text=f"Terminé. Log : {chemin_log}")
        self.bouton_creer.config(state="disabled")
        self.arbre_en_attente = None


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------
def main():
    root = tk.Tk()
    app = BinBuilderApp(root)

    # On évite root.mainloop() : dans le contexte d'un script Resolve, la
    # boucle bloquante standard peut geler l'interface de Resolve (même
    # thread). On implémente donc une boucle d'update manuelle, qui se
    # termine proprement quand la fenêtre est fermée.
    try:
        while True:
            root.update_idletasks()
            root.update()
    except tk.TclError:
        pass  # la fenêtre a été fermée, on sort proprement


if __name__ == "__main__":
    main()
