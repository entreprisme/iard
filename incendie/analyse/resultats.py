"""Compteurs, tableaux et export de gestion.

Rien n'est imprimé ici : les fonctions renvoient des objets que le notebook
affiche. C'est ce qui permet de les réutiliser depuis un script sans sortie
console, et de les tester.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd

from . import config as cfg

# Colonnes de l'export de gestion, dans l'ordre. Celles qui manquent sont
# ignorées : l'export s'adapte aux colonnes réellement extraites.
COLONNES_EXPORT = [
    "id_societaire", "numero_intercalaire", "id", "numero_contrat", "segment",
    "qualite", "type_bien", "niveau_geocodage",
    "id_plusieurs_positions", "id_plusieurs_adresses",
    "position_incertaine", "ecart_positions_m",
    "sinistre_declare", "nb_sinistres_ouverts", "numeros_sinistres", "date_declaration",
    "rue_adresse_risque", "code_postal_adresse_risque", "commune_adresse_risque",
    "lon_contrat_mgar", "lat_contrat_mgar", "feu_rattache", "niveau_impact",
    "distance_bati_m", "bat_id", "geocodage_suspect",
]


def perimetre_demande(appar: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """(cible, impact) : les RP/RS/PNO, puis ceux retenus comme impactés."""
    cible = appar[appar["dans_perimetre_demande"]]
    return cible, cible[cible["est_impacte"]]


def compteurs(appar: gpd.GeoDataFrame) -> dict[str, int]:
    """« Combien ? » se décline en trois compteurs, et il faut les trois :
    bâtiments distincts, contrats, et sociétaires."""
    cible, impact = perimetre_demande(appar)
    return {
        "batis_touches": int(impact["bat_id"].nunique()),
        "contrats": int(impact["id"].nunique()),
        "societaires": int(impact["id_societaire"].nunique()),
        "certains": int((impact["niveau_impact"] == cfg.NIV_CERTAIN).sum()),
        "en_perimetre": int((cible["niveau_impact"] == cfg.NIV_EXPOSE).sum()),
        "hors_cible_impactes": int(appar.loc[~appar["dans_perimetre_demande"]
                                             & appar["est_impacte"], "id"].nunique()),
        "suspects": int(impact["geocodage_suspect"].sum()),
        "inexploitables": int((cible["niveau_impact"] == cfg.NIVEAU_INEXPLOITABLE).sum()),
        "declares": int(impact["sinistre_declare"].sum()),
        "impactes_sans_declaration": int((~impact["sinistre_declare"]).sum()),
        "declares_non_detectes": int(cible.loc[~cible["est_impacte"],
                                               "sinistre_declare"].sum()),
    }


def synthese_par_feu(appar: gpd.GeoDataFrame) -> pd.DataFrame:
    """Bâtiments, contrats et sociétaires par feu et par segment."""
    _, impact = perimetre_demande(appar)
    s = (impact.groupby(["feu_rattache", "segment"], observed=True)
               .agg(batis_touches=("bat_id", "nunique"),
                    contrats=("id", "nunique"),
                    societaires=("id_societaire", "nunique"))
               .reset_index()
               .rename(columns={"feu_rattache": "feu"}))
    s["libelle"] = s["segment"].map(cfg.LIB_SEGMENT)
    return (s.sort_values(["feu", "contrats"], ascending=[True, False])
             [["feu", "segment", "libelle", "batis_touches", "contrats", "societaires"]])


def detail_par_niveau(appar: gpd.GeoDataFrame) -> pd.DataFrame:
    """Tous les contrats de la demande, ventilés par niveau de certitude."""
    cible, _ = perimetre_demande(appar)
    d = (pd.crosstab(cible["feu_rattache"].fillna("Aucun feu à proximité"),
                     cible["niveau_impact"], dropna=False)
           .reindex(columns=cfg.ordre_niveaux(), fill_value=0))
    d.index.name = "Feu le plus proche"
    return d


def sensibilite(appar: gpd.GeoDataFrame) -> pd.DataFrame:
    """Effet du seuil de distance sur le compte.

    Le seuil est le principal arbitrage de la méthode : mieux vaut montrer sa
    sensibilité que défendre un nombre unique. Les positions trop imprécises
    sont exclues, leur distance n'étant pas interprétable.
    """
    cible, _ = perimetre_demande(appar)
    exploitables = cible[cible["niveau_impact"] != cfg.NIVEAU_INEXPLOITABLE]

    lignes = []
    for seuil in cfg.SEUILS_SENSIBILITE_M:
        sel = exploitables[exploitables["distance_bati_m"].le(seuil)]
        # `bat_id` est neutralisé au-delà du seuil retenu : on relit le brut.
        lignes.append({"seuil_m": seuil,
                       "batis_touches": int(appar.loc[sel.index, "bat_id_brut"].nunique()),
                       "contrats": int(sel["id"].nunique()),
                       "societaires": int(sel["id_societaire"].nunique())})
    t = pd.DataFrame(lignes)
    t["retenu"] = np.where(t["seuil_m"] == cfg.SEUIL_PROBABLE_M, "◀ retenu", "")
    return t


def matrice_validation(appar: gpd.GeoDataFrame) -> pd.DataFrame:
    """Géométrie × sinistre déclaré : le seul contrôle externe disponible.

    Il mesure la méthode au lieu de la supposer juste, isole les impactés sans
    déclaration, et compte les sinistrés que la géométrie ne retient pas — soit
    les cas où elle échoue.
    """
    cible, _ = perimetre_demande(appar)
    m = (pd.crosstab(cible["niveau_impact"], cible["sinistre_declare"], dropna=False)
           .reindex(index=cfg.ordre_niveaux(), fill_value=0))
    m.columns = [{False: "Sans déclaration", True: "Sinistre ouvert"}.get(c, c)
                 for c in m.columns]
    for c in ("Sinistre ouvert", "Sans déclaration"):
        if c not in m:
            m[c] = 0
    m = m[["Sans déclaration", "Sinistre ouvert"]]
    m["Total"] = m.sum(axis=1)
    m["Taux de déclaration"] = (m["Sinistre ouvert"] / m["Total"].replace(0, np.nan)).map(
        lambda v: "—" if pd.isna(v) else f"{v:.0%}")
    return m


def croisement_statut(appar: gpd.GeoDataFrame) -> pd.DataFrame | None:
    """Statut d'occupation × segment. Les deux axes ne se recouvrent pas : le
    segment dit à quoi sert le logement, le statut qui supporte le dommage."""
    _, impact = perimetre_demande(appar)
    if "statut" not in impact:
        return None
    c = (pd.crosstab(impact["statut"], impact["segment"])
           .reindex(index=cfg.ORDRE_STATUTS, columns=list(cfg.SEGMENTS_CIBLE))
           .fillna(0).astype(int))
    c["Total"] = c.sum(axis=1)
    return c


def croisement_type_bien(appar: gpd.GeoDataFrame) -> pd.DataFrame | None:
    _, impact = perimetre_demande(appar)
    if "type_bien" not in impact:
        return None
    return pd.crosstab(impact["type_bien"], impact["segment"],
                       margins=True, margins_name="Total")


def exporter(appar: gpd.GeoDataFrame, chemin=None) -> pd.DataFrame:
    """Écrit l'export de gestion et renvoie le tableau exporté."""
    chemin = chemin or cfg.FICHIER_CSV
    chemin.parent.mkdir(parents=True, exist_ok=True)
    _, impact = perimetre_demande(appar)
    cols = [c for c in COLONNES_EXPORT if c in impact.columns]
    export = impact[cols].sort_values(["feu_rattache", "niveau_impact", "distance_bati_m"])
    export.to_csv(chemin, index=False, encoding="utf-8-sig")
    return export
