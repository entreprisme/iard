"""Chargement des données : emprises des feux, contrats, sinistres.

Deux familles de sources sans rapport l'une avec l'autre :

* les **données incendie**, des shapefiles livrés dans `data_incendie/` ;
* les **données assurance**, extraites de BigQuery ou lues sur un export local.

Aucun repli sur des données de test : à défaut de source, on lève une erreur.
Un livrable d'apparence normale construit sur autre chose que les données
réelles est plus dangereux qu'un échec.
"""

from __future__ import annotations

from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path

import geopandas as gpd
import pandas as pd

from . import config as cfg


# --------------------------------------------------------------------------- #
# Données incendie
# --------------------------------------------------------------------------- #
# Les livraisons ne sont pas normalisées : le même fichier arrive en `Bati`,
# `BATI` ou `bati`, et les dossiers alternent de la même façon. Sous Windows la
# casse est ignorée et le problème ne se voit pas ; sous Linux — où tourne
# l'automatisation — `Path.glob("*Bati*.shp")` ne trouve pas `BATI.shp`, et le
# feu passe silencieusement pour dépourvu de couche bâti. Toutes les recherches
# de fichiers passent donc par ces deux helpers, qui comparent en minuscules.
def _trouver(dossier: Path, motif: str) -> list[Path]:
    """Fichiers du dossier correspondant au motif, sans tenir compte de la casse."""
    if not dossier.is_dir():
        return []
    cible = motif.lower()
    return sorted(p for p in dossier.iterdir() if fnmatch(p.name.lower(), cible))


def _dossier_feu(nom_feu: str, nom_dossier: str) -> Path:
    """Dossier du feu dans `data_incendie/`, sans tenir compte de la casse."""
    racine = cfg.DOSSIER_INCENDIE
    direct = racine / nom_dossier
    if direct.is_dir():
        return direct
    if racine.is_dir():
        cible = nom_dossier.lower()
        for p in sorted(racine.iterdir()):
            if p.is_dir() and p.name.lower() == cible:
                return p
    presents = (sorted(p.name for p in racine.iterdir() if p.is_dir())
                if racine.is_dir() else "le dossier data_incendie/ est absent")
    raise FileNotFoundError(
        f"Feu « {nom_feu} » : dossier « {nom_dossier} » introuvable dans {racine}.\n"
        f"  Dossiers présents : {presents}\n"
        f"  Corriger la clé `dossier` du catalogue FEUX dans analyse/config.py.")


def _lire_couche(chemin: Path, crs_defaut: int, afficher=print) -> gpd.GeoDataFrame:
    """Lit un shapefile et le ramène en Lambert 93, en réparant un CRS absent."""
    gdf = gpd.read_file(chemin)
    if gdf.crs is None:
        gdf = gdf.set_crs(crs_defaut)
        afficher(f"  ⚠️  {chemin.name} : aucun .prj → CRS forcé à EPSG:{crs_defaut}")
    return gdf.to_crs(cfg.CRS_METRIQUE)


def charger_feux(afficher=print) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Emprises et bâtiments des feux retenus, en Lambert 93.

    Renvoie (contours, batis). `batis` peut être vide si aucun feu traité n'a
    fourni sa couche de bâtiments — possible seulement avec INTEGRER_PERIMETRE.
    """
    feux = cfg.feux_actifs()
    afficher(f"Feu(x) traité(s) : {cfg.libelle_feux()}"
          + (f"  —  écarté(s) : "
             f"{', '.join(n for n in cfg.FEUX if n not in feux)}"
             if len(feux) < len(cfg.FEUX) else ""))

    contours_l, batis_l = [], []
    for nom, param in feux.items():
        dossier = _dossier_feu(nom, param["dossier"])
        fichiers_contour = _trouver(dossier, param["contour"])
        if not fichiers_contour:
            raise FileNotFoundError(
                f"Feu « {nom} » : aucun contour ({param['contour']}) dans {dossier}.\n"
                f"  Fichiers présents : {sorted(p.name for p in dossier.iterdir())}\n"
                f"  Corriger la clé `contour` du catalogue FEUX dans analyse/config.py.")
        f_contour = fichiers_contour[0]
        afficher(f"• {nom}")

        contour = _lire_couche(f_contour, param["crs_defaut"], afficher)
        # Un contour issu de vectorisation raster arrive en centaines de
        # polygones (celui du Var en compte 97, dont 17 sous 0,1 ha). On les
        # fusionne : sans cela la carte afficherait autant d'entités et les
        # surfaces seraient ventilées par éclat de trace.
        if len(contour) > 1:
            afficher(f"  {len(contour)} polygones fusionnés en une emprise")
            contour = gpd.GeoDataFrame({"geometry": [contour.geometry.union_all()]},
                                       crs=cfg.CRS_METRIQUE)
        contour["feu"] = nom
        contour["fichier"] = f_contour.name
        contours_l.append(contour[["feu", "fichier", "geometry"]])

        fichiers_bati = _trouver(dossier, param["bati"])
        if not fichiers_bati:
            if not cfg.INTEGRER_PERIMETRE:
                raise FileNotFoundError(
                    f"Feu « {nom} » : aucune couche de bâtiments "
                    f"({param['bati']}) dans {dossier}.\n"
                    "Sans elle, la distance au bâti ne peut pas être calculée et "
                    "aucun contrat de ce feu n'atteindrait un niveau d'impact — le "
                    "feu serait sous-estimé sans que le livrable ne le signale.\n"
                    "Trois issues : fournir le shapefile des bâtiments, activer "
                    "INTEGRER_PERIMETRE pour se contenter du périmètre, ou retirer "
                    f"« {nom} » de FEUX_A_TRAITER."
                )
            afficher(f"  ⚠️  aucune couche de bâtiments : ce feu ne produira que des "
                  f"contrats « {cfg.NIV_EXPOSE} »")
            continue

        bati = _lire_couche(fichiers_bati[0], param["crs_defaut"], afficher)
        bati["feu"] = nom
        bati["fichier"] = fichiers_bati[0].name
        bati["surface_bati_m2"] = bati.geometry.area.round(1)
        batis_l.append(bati[["feu", "fichier", "surface_bati_m2", "geometry"]])

    contours = gpd.GeoDataFrame(pd.concat(contours_l, ignore_index=True),
                                geometry="geometry", crs=cfg.CRS_METRIQUE)
    contours["surface_feu_ha"] = (contours.geometry.area / 10_000).round(0)

    batis = gpd.GeoDataFrame(
        pd.concat(batis_l, ignore_index=True) if batis_l else
        pd.DataFrame(columns=["feu", "fichier", "surface_bati_m2", "geometry"]),
        geometry="geometry", crs=cfg.CRS_METRIQUE)
    # `cleabs` étant constant sur le fichier Gironde, on fabrique notre propre clé.
    batis["bat_id"] = [f"{f[:4].upper()}-{i:05d}" for i, f in enumerate(batis["feu"], 1)]
    return contours, batis


def controle_recouvrement(contours: gpd.GeoDataFrame, batis: gpd.GeoDataFrame,
                          afficher=print) -> None:
    """Les bâtis relevés tombent-ils bien dans leur périmètre ?"""
    for nom in (n for n in cfg.feux_actifs() if (batis.feu == n).any()):
        c = contours.loc[contours.feu == nom].geometry.union_all()
        b = batis.loc[batis.feu == nom]
        dedans = b.representative_point().within(c).mean()
        afficher(f"{nom:<12} {len(b):>5} bâtis — {dedans:6.1%} strictement dans le "
              "contour (le reste affleure la limite du périmètre)")


def emprises_requete(contours: gpd.GeoDataFrame, afficher=print) -> list[tuple]:
    """Une bounding box **par feu**, élargie de MARGE_REQUETE_M, en WGS84.

    C'est le pré-filtre de la requête : sans lui on rapatrierait les contrats de
    la France entière.

    Une boîte par feu, et non une boîte englobant tout : les feux traités peuvent
    être aux deux bouts du pays. Le rectangle couvrant Gironde + Biscarrosse + Var
    mesure 101 000 km² — 229 fois la surface réellement brûlée — et va de
    l'Atlantique aux Alpes. Il ramènerait des dizaines de milliers de contrats
    sans aucun rapport avec les feux : sans effet sur le comptage, qui reste
    géométrique, mais de quoi noyer les diagnostics et faire scanner à BigQuery
    un volume sans commune mesure avec la question posée.

    Renvoie [(feu, lon_min, lat_min, lon_max, lat_max), …].
    """
    boites = []
    for nom in contours["feu"].drop_duplicates():
        part = contours[contours["feu"] == nom]
        b = (part.geometry.buffer(cfg.MARGE_REQUETE_M)
                 .to_crs(cfg.CRS_AFFICHAGE).total_bounds)
        boites.append((nom, *(round(v, 4) for v in b)))

    afficher(f"Zone interrogée — {len(boites)} rectangle(s), "
             f"marge de {cfg.MARGE_REQUETE_M / 1000:.0f} km :")
    for nom, lon_min, lat_min, lon_max, lat_max in boites:
        afficher(f"  {nom:<14} lon [{lon_min}, {lon_max}]  "
                 f"lat [{lat_min}, {lat_max}]")
    return boites


# --------------------------------------------------------------------------- #
# Requêtes
# --------------------------------------------------------------------------- #
def _filtre_emprises(emprises: list[tuple], col_lon: str, col_lat: str) -> str:
    """Clause WHERE : l'union des rectangles, un par feu.

    Un OR de rectangles plutôt qu'un rectangle englobant — voir emprises_requete.
    """
    clauses = [
        f"({col_lon} BETWEEN {lon_min} AND {lon_max}"
        f" AND {col_lat} BETWEEN {lat_min} AND {lat_max})   -- {nom}"
        for nom, lon_min, lat_min, lon_max, lat_max in emprises
    ]
    return "\n       OR ".join(clauses)


def requete_contrats(emprises: list[tuple]) -> str:
    """Contrats habitation en cours, géolocalisés, dans l'emprise des feux.

    Deux sources de multiplicité, traitées dans cet ordre.

    1. `contrat_mgar` porte plusieurs contrats par couple (id_societaire,
       numero_intercalaire) : ce sont des contrats successifs, avec leurs
       propres dates d'effet. On ne garde que le plus récent — c'est lui qui
       décrit le risque assuré aujourd'hui, donc lui qui fournit l'adresse.
    2. La table de géocodage porte plusieurs lignes par contrat. Le contrat
       retenu pilote la jointure : son code postal sélectionne le géocodage
       correspondant. Ce qui subsiste est arbitré côté Python sur
       `level_contrat_mgar`, la requête n'ayant pas de critère pour le faire.

    `t1.geom` est volontairement absent : BigQuery interdit SELECT DISTINCT sur
    une colonne GEOGRAPHY. La géométrie est reconstruite depuis lon/lat ; si le
    WKT est nécessaire, ST_ASTEXT(t1.geom) est une STRING et supporte DISTINCT.
    """
    filtre = _filtre_emprises(emprises, "t1.lon_contrat_mgar", "t1.lat_contrat_mgar")
    opt_cte = "".join(f",\n    {c}" for c in cfg.COLONNES_FACULTATIVES)
    opt_sel = "".join(f",\n  c.{c}" for c in cfg.COLONNES_FACULTATIVES)
    join_adresse = ("""
  AND t1.rue_adresse_risque         = c.rue_adresse_risque
  AND t1.commune_adresse_risque     = c.commune_adresse_risque"""
                    if cfg.JOINTURE_STRICTE_ADRESSE else
                    "\n  -- jointure sur 3 clés : voir JOINTURE_STRICTE_ADRESSE")

    return f"""
WITH contrat_courant AS (
  SELECT
    id_societaire,
    numero_intercalaire,
    id AS numero_contrat,             -- traçabilité : quel contrat a été retenu
    rue_adresse_risque,
    code_postal_adresse_risque,
    commune_adresse_risque,
    date_premier_effet,
    date_effet,
    code_sous_type,                   -- segmentation RP / RS / PNO
    code_qualite_assure_habitation{opt_cte}
  FROM `{cfg.TABLE_CONTRATS}`
  WHERE tech_date_fin_historisation IS NULL
    AND date_resiliation IS NULL      -- contrats en cours uniquement
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY id_societaire, numero_intercalaire
    ORDER BY date_effet DESC NULLS LAST, date_premier_effet DESC NULLS LAST, id DESC
  ) = 1
)
SELECT DISTINCT
  c.id_societaire,
  c.numero_intercalaire,
  CONCAT(c.id_societaire, c.numero_intercalaire) AS id,
  c.numero_contrat,
  c.rue_adresse_risque,
  c.code_postal_adresse_risque,
  c.commune_adresse_risque,
  c.date_premier_effet,
  c.date_effet,
  c.code_sous_type,
  c.code_qualite_assure_habitation{opt_sel},
  t1.lon_contrat_mgar,
  t1.lat_contrat_mgar,
  t1.level_contrat_mgar               -- housenumber / street / locality / municipality
FROM contrat_courant c
INNER JOIN `{cfg.TABLE_GPS}` t1
  ON  t1.id_societaire              = c.id_societaire
  AND t1.numero_intercalaire        = c.numero_intercalaire
  AND t1.code_postal_adresse_risque = c.code_postal_adresse_risque{join_adresse}
-- Pré-filtre : un rectangle par feu, pas un rectangle englobant — celui qui
-- couvrirait des feux éloignés ramènerait la moitié du pays.
WHERE (   {filtre}
      )
"""


def requete_sinistres() -> str:
    """Sinistres incendie ouverts depuis le départ du premier feu.

    L'ordre des filtres n'est pas indifférent. `tech_date_fin_historisation IS
    NULL` ne suffit pas : un sinistre garde plusieurs mouvements courants, du
    premier au dernier. Il faut d'abord réduire chaque dossier à son dernier
    `numero_mouvement`, puis seulement filtrer — `est_clos` change d'un
    mouvement à l'autre, et filtrer avant ferait ressortir un dossier ouvert au
    mouvement 2 mais clos au mouvement 7.

    Le seuil porte sur `date_enregistrement`, posée par le système à l'ouverture
    du dossier, plutôt que sur `date_survenance`, déclarative donc exposée aux
    saisies approximatives. Un sinistre ne pouvant être enregistré avant d'être
    survenu, le seuil reste couvrant.
    """
    ouverts = "\n  AND s.est_clos = FALSE" if cfg.SINISTRES_OUVERTS_UNIQUEMENT else ""
    fenetre = ("" if not cfg.FENETRE_SINISTRE_JOURS else
               f"\n  AND s.date_enregistrement >= "
               f"DATE_SUB(CURRENT_DATE(), INTERVAL {cfg.FENETRE_SINISTRE_JOURS} DAY)")
    codes = ("" if not cfg.CODES_SINISTRE_INCENDIE else
             "\n  AND s.code_descriptif_sinistre IN ("
             + ", ".join(f"'{c}'" for c in cfg.CODES_SINISTRE_INCENDIE) + ")")

    return f"""
WITH derniere_situation AS (
  SELECT *
  FROM `{cfg.TABLE_SINISTRES}`
  WHERE tech_date_fin_historisation IS NULL
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY numero_sinistre, cle_controle_numero_sinistre
    -- `numero_mouvement` est cadré à gauche par des zéros ('0000', '0004') : le
    -- tri texte suffirait, le cast protège d'une valeur non cadrée.
    ORDER BY SAFE_CAST(numero_mouvement AS INT64) DESC, numero_mouvement DESC
  ) = 1
)
SELECT DISTINCT
  s.id_societaire,
  s.numero_intercalaire_contrat   AS numero_intercalaire,
  s.numero_sinistre,
  s.numero_mouvement,
  s.code_descriptif_sinistre,
  s.date_enregistrement,
  s.date_survenance,
  s.numero_evenement_grande_ampleur
FROM derniere_situation s
WHERE s.date_enregistrement >= DATE '{cfg.date_debut_feux()}'{ouverts}{fenetre}{codes}
"""


def requetes_controle(emprises: list[tuple]) -> dict[str, str]:
    """Requêtes de contrôle à passer une fois dans BigQuery, sans lesquelles on
    conclurait sur des chiffres dont on ignore la fiabilité."""
    filtre = ("(   "
              + _filtre_emprises(emprises, "lon_contrat_mgar", "lat_contrat_mgar")
                .replace("\n       OR ", "\n        OR ")
              + "\n    )")
    return {
        "jointure": f"""
-- Ce que la jointure à 5 clés fait tomber par rapport à 3 clés : un INNER JOIN
-- sur des libellés d'adresse écarte silencieusement les lignes dont le formatage
-- diffère entre la table gold géocodée et la source silver.
WITH base AS (
  SELECT id_societaire, numero_intercalaire, code_postal_adresse_risque,
         rue_adresse_risque, commune_adresse_risque
  FROM `{cfg.TABLE_GPS}`
  WHERE {filtre}
)
SELECT
  COUNT(DISTINCT CONCAT(b.id_societaire, b.numero_intercalaire))  AS contrats_t1,
  COUNT(DISTINCT IF(j3.id_societaire IS NOT NULL,
        CONCAT(b.id_societaire, b.numero_intercalaire), NULL))    AS apparies_3_cles,
  COUNT(DISTINCT IF(j5.id_societaire IS NOT NULL,
        CONCAT(b.id_societaire, b.numero_intercalaire), NULL))    AS apparies_5_cles
FROM base b
LEFT JOIN `{cfg.TABLE_CONTRATS}` j3
  ON  b.id_societaire = j3.id_societaire
  AND b.numero_intercalaire = j3.numero_intercalaire
  AND b.code_postal_adresse_risque = j3.code_postal_adresse_risque
  AND j3.tech_date_fin_historisation IS NULL
LEFT JOIN `{cfg.TABLE_CONTRATS}` j5
  ON  b.id_societaire = j5.id_societaire
  AND b.numero_intercalaire = j5.numero_intercalaire
  AND b.code_postal_adresse_risque = j5.code_postal_adresse_risque
  AND b.rue_adresse_risque = j5.rue_adresse_risque
  AND b.commune_adresse_risque = j5.commune_adresse_risque
  AND j5.tech_date_fin_historisation IS NULL
""",
        "unicite_gps": f"""
-- À quel niveau de clé la table de géocodage devient-elle unique ?
-- Si `lignes` > `cles_soc_intercalaire`, elle porte elle-même les doublons et la
-- jointure ne fait que les propager.
SELECT
  COUNT(*)                                                   AS lignes,
  COUNT(DISTINCT CONCAT(id_societaire, numero_intercalaire))  AS cles_soc_intercalaire,
  COUNT(DISTINCT CONCAT(id_societaire, numero_intercalaire,
                        code_postal_adresse_risque))          AS cles_avec_code_postal,
  COUNT(DISTINCT CONCAT(id_societaire, numero_intercalaire,
                        code_postal_adresse_risque,
                        IFNULL(rue_adresse_risque, ''),
                        IFNULL(commune_adresse_risque, '')))   AS cles_5_colonnes
FROM `{cfg.TABLE_GPS}`
WHERE {filtre}
""",
        "causes_doublons_gps": f"""
-- Sur les clés en doublon, qu'est-ce qui varie exactement ?
WITH doublons AS (
  SELECT
    id_societaire, numero_intercalaire,
    COUNT(*)                                          AS n_lignes,
    COUNT(DISTINCT code_postal_adresse_risque)        AS n_code_postal,
    COUNT(DISTINCT rue_adresse_risque)                AS n_rue,
    COUNT(DISTINCT commune_adresse_risque)            AS n_commune,
    COUNT(DISTINCT FORMAT('%.6f|%.6f',
          lon_contrat_mgar, lat_contrat_mgar))         AS n_positions
  FROM `{cfg.TABLE_GPS}`
  WHERE {filtre}
  GROUP BY id_societaire, numero_intercalaire
  HAVING COUNT(*) > 1
)
SELECT
  COUNT(*)                     AS cles_en_doublon,
  SUM(n_lignes - 1)            AS lignes_en_exces,
  COUNTIF(n_code_postal > 1)   AS varie_code_postal,
  COUNTIF(n_rue > 1)           AS varie_rue,
  COUNTIF(n_commune > 1)       AS varie_commune,
  COUNTIF(n_positions > 1)     AS varie_position,
  COUNTIF(n_code_postal = 1 AND n_rue = 1
          AND n_commune = 1 AND n_positions = 1) AS lignes_identiques
FROM doublons
""",
        "modalites_precision": f"""
-- Modalités de la colonne de précision du géocodage, pour compléter les
-- ensembles MODALITES_* de config.py si les libellés ne sont pas ceux de la BAN.
SELECT
  level_contrat_mgar                                          AS modalite,
  COUNT(*)                                                    AS lignes,
  COUNT(DISTINCT CONCAT(id_societaire, numero_intercalaire))   AS contrats
FROM `{cfg.TABLE_GPS}`
WHERE {filtre}
GROUP BY modalite
ORDER BY contrats DESC
""",
        "codes_sinistre": f"""
-- Vérifier que '05' domine bien les survenances postérieures au départ du feu
-- en Gironde, dans les Landes et le Var.
SELECT
  code_descriptif_sinistre,
  COUNT(*)                                        AS sinistres,
  MIN(date_survenance)                            AS premiere_survenance,
  MAX(date_survenance)                            AS derniere_survenance,
  COUNT(DISTINCT numero_evenement_grande_ampleur) AS evenements_grande_ampleur
FROM `{cfg.TABLE_SINISTRES}`
WHERE tech_date_fin_historisation IS NULL
  AND date_survenance >= DATE '{cfg.date_debut_feux()}'
  AND code_departement_survenance IN ('33', '40', '83')
GROUP BY code_descriptif_sinistre
ORDER BY sinistres DESC
""",
    }


# --------------------------------------------------------------------------- #
# Extractions
# --------------------------------------------------------------------------- #
def _via_bigquery(sql: str) -> pd.DataFrame:
    from google.cloud import bigquery
    return bigquery.Client(project=cfg.PROJET_BQ).query(sql).to_dataframe()


def charger_contrats(sql: str) -> tuple[pd.DataFrame, str]:
    """BigQuery, sinon export local. Aucun repli : mieux vaut un arrêt net qu'un
    livrable qui ressemble à une analyse sans en être une."""
    erreurs = []
    try:
        return _via_bigquery(sql), "bigquery"
    except Exception as exc:                                    # noqa: BLE001
        erreurs.append(f"BigQuery : {type(exc).__name__} — {exc}")

    if cfg.FICHIER_LOCAL_CONTRATS.exists():
        df = pd.read_csv(cfg.FICHIER_LOCAL_CONTRATS, dtype=str)
        for c in ("lon_contrat_mgar", "lat_contrat_mgar"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df, "fichier"
    erreurs.append(f"Export local : {cfg.FICHIER_LOCAL_CONTRATS} introuvable")

    raise RuntimeError(
        "Aucune source de contrats disponible.\n  - " + "\n  - ".join(erreurs)
        + "\n\nSoit exécuter depuis un poste ayant accès à BigQuery, soit y déposer"
          f"\nle résultat de la requête dans {cfg.FICHIER_LOCAL_CONTRATS}."
    )


def charger_sinistres(sql: str, mode_contrats: str) -> tuple[pd.DataFrame, str]:
    """Idem, et sans blocage si le croisement est désactivé."""
    if not cfg.CROISER_SINISTRES:
        print("⚠️  CROISER_SINISTRES = False : le livrable sera produit sans le "
              "contrôle externe que constitue le rapprochement des sinistres.")
        return pd.DataFrame(columns=["id_societaire", "numero_intercalaire",
                                     "numero_sinistre", "date_enregistrement"]), "désactivé"

    erreurs = []
    if mode_contrats == "bigquery":
        try:
            return _via_bigquery(sql), "bigquery"
        except Exception as exc:                                 # noqa: BLE001
            erreurs.append(f"BigQuery : {type(exc).__name__} — {exc}")

    if cfg.FICHIER_LOCAL_SINISTRES.exists():
        return pd.read_csv(cfg.FICHIER_LOCAL_SINISTRES, dtype=str), "fichier"
    erreurs.append(f"Export local : {cfg.FICHIER_LOCAL_SINISTRES} introuvable")

    raise RuntimeError(
        "Aucune source de sinistres disponible.\n  - " + "\n  - ".join(erreurs)
        + f"\n\nDéposer le résultat de la requête dans {cfg.FICHIER_LOCAL_SINISTRES},"
          "\nou mettre CROISER_SINISTRES à False pour s'en passer."
    )


def date_export_local() -> str:
    """Date de l'export local, lue sur le fichier. Écrite en dur elle
    deviendrait fausse au prochain export sans que personne ne le remarque."""
    return datetime.fromtimestamp(
        cfg.FICHIER_LOCAL_CONTRATS.stat().st_mtime).strftime("%d/%m/%Y")
