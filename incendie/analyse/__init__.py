"""Analyse des bâtis de sociétaires impactés par un incendie.

Le package suit l'ordre de l'analyse, un module par étape :

    config      les paramètres — le seul fichier à ouvrir en usage courant
    donnees     emprises des feux, requêtes SQL, extractions
    traitement  diagnostics, segmentation, géocodage, appariement spatial
    resultats   compteurs, tableaux, export de gestion
    carte       carte interactive
    rapport     livrable HTML

Le notebook `carte_incendie_societaires.ipynb` enchaîne ces étapes en affichant
les diagnostics : c'est le point d'entrée normal. `analyser()` fait la même
chose d'un bloc, pour un lancement automatisé sans sortie console.

    from analyse import config as cfg, analyser
    cfg.FEUX_A_TRAITER = ("Var",)
    cfg.INTEGRER_PERIMETRE = True
    resultat = analyser()
"""

from __future__ import annotations

import warnings

import pandas as pd

from . import carte, config, donnees, rapport, resultats, traitement

__all__ = ["analyser", "carte", "config", "donnees", "rapport", "resultats",
           "traitement"]

warnings.filterwarnings("ignore", category=UserWarning)
pd.set_option("display.max_columns", 80)
pd.set_option("display.width", 200)


def analyser(silencieux: bool = False) -> dict:
    """Déroule l'analyse complète et écrit le livrable.

    Renvoie un dictionnaire contenant les objets intermédiaires — utile pour
    inspecter un résultat sans relancer, ou pour tester une étape isolément.
    """
    log = (lambda *a, **k: None) if silencieux else print

    contours, batis = donnees.charger_feux(log)
    donnees.controle_recouvrement(contours, batis, log)
    emprises = donnees.emprises_requete(contours, log)

    contrats, mode = donnees.charger_contrats(donnees.requete_contrats(emprises))
    log(f"Mode = {mode.upper()} — {len(contrats):,} lignes chargées"
        .replace(",", " "))
    traitement.diagnostiquer_doublons(contrats, log)

    contrats = traitement.segmenter(contrats, log)
    sinistres, mode_sin = donnees.charger_sinistres(donnees.requete_sinistres(), mode)
    contrats = traitement.rattacher_sinistres(contrats, sinistres, log)

    pts, col_precision = traitement.geolocaliser(contrats, log)
    appar = traitement.apparier(pts, batis, contours, col_precision, log)

    kpi = resultats.compteurs(appar)
    export = resultats.exporter(appar)
    log(f"{len(export)} contrats exportés → {config.FICHIER_CSV}")

    m = carte.construire(appar, batis, contours, emprises, log)
    html = carte.rendre_autonome(m, log)
    chemin = rapport.ecrire(appar, batis, html, mode, col_precision, afficher=log)

    return {"contours": contours, "batis": batis, "contrats": contrats,
            "sinistres": sinistres, "appariement": appar, "compteurs": kpi,
            "export": export, "carte": m, "livrable": chemin,
            "mode_source": mode, "mode_sinistres": mode_sin,
            "colonne_precision": col_precision, "emprises": emprises}
