"""Du contrat brut au contrat classé : diagnostics, segmentation, appariement.

L'ordre des fonctions suit celui de l'analyse, et chacune renvoie le tableau
enrichi plutôt que de modifier un état partagé. Les diagnostics impriment
volontairement : ils font partie du livrable, pas du débogage — c'est là que se
voient les doublons, les géocodages douteux et les arbitrages.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd

from . import config as cfg

CLE_CONTRAT = ["id_societaire", "numero_intercalaire"]
# L'adresse est toujours affichée dans les relevés d'anomalie, même quand elle ne
# varie pas : depuis que le contrat retenu la fournit, elle est identique sur
# toutes les lignes d'une clé et sortirait des « colonnes qui diffèrent ». Or
# c'est elle qui rend le relevé exploitable.
COLONNES_ADRESSE = ["rue_adresse_risque", "code_postal_adresse_risque",
                    "commune_adresse_risque"]


# --------------------------------------------------------------------------- #
# Diagnostic des doublons
# --------------------------------------------------------------------------- #
def diagnostiquer_doublons(contrats: pd.DataFrame, afficher=print) -> None:
    """Quelles colonnes font qu'une même clé apparaît plusieurs fois ?

    La requête sort en SELECT DISTINCT : deux lignes de même clé diffèrent donc
    forcément sur au moins une colonne sélectionnée. La cause ne se devine pas,
    et ses conséquences vont du bénin — même adresse géocodée deux fois — à
    l'anomalie d'historisation.
    """
    doublons = contrats[contrats["id"].duplicated(keep=False)]
    if doublons.empty:
        afficher("Aucun doublon : la clé (id_societaire, numero_intercalaire) "
                 "est unique ici.")
        return

    n_id = doublons["id"].nunique()
    afficher(f"{len(doublons)} lignes portent {n_id} clés (id_societaire, "
             f"numero_intercalaire) dupliquées "
             f"({len(contrats) - contrats['id'].nunique()} lignes en excès).\n")

    # Sur combien de clés chaque colonne prend-elle plusieurs valeurs ?
    varie = (doublons.groupby("id").nunique(dropna=False) > 1).sum()
    varie = varie[varie > 0].sort_values(ascending=False)
    afficher(pd.DataFrame({"clés concernées": varie,
                           "part": (varie / n_id).map("{:.0%}".format)}))

    adresse = [c for c in COLONNES_ADRESSE if c in doublons.columns]

    def montrer(ex_id, titre):
        ex = doublons[doublons["id"] == ex_id]
        cols_var = [c for c in ex.columns
                    if c not in CLE_CONTRAT + adresse and ex[c].nunique(dropna=False) > 1]
        adr_var = [c for c in adresse if ex[c].nunique(dropna=False) > 1]
        afficher(f"\n{titre} — sociétaire {ex[CLE_CONTRAT[0]].iloc[0]}, intercalaire "
                 f"{ex[CLE_CONTRAT[1]].iloc[0]} ({len(ex)} lignes)")
        afficher(f"  colonnes qui diffèrent : "
                 f"{(adr_var + cols_var) or 'aucune (lignes identiques)'}")
        if adresse and not adr_var:
            afficher("  adresse identique sur toutes les lignes : le doublon vient "
                     "du géocodage, pas du contrat.")
        afficher(ex[CLE_CONTRAT + adresse + cols_var])
        if not cols_var and not adr_var:
            afficher("  ⚠️  Lignes strictement identiques : doublon de la source, "
                     "à remonter au producteur.")

    montrer(doublons["id"].value_counts().index[0], "Cas le plus chargé")

    if adresse:
        n_adr = doublons.groupby("id")[adresse].nunique().max(axis=1)
        multi = n_adr[n_adr > 1]
        if not multi.empty:
            if multi.index[0] != doublons["id"].value_counts().index[0]:
                montrer(multi.sort_values(ascending=False).index[0],
                        "Cas à adresses de risque multiples")
            afficher(f"\n{len(multi)} clé(s) portent plusieurs adresses de risque : "
                     "plusieurs lieux assurés, ou historique d'adresse resté dans la "
                     "table gold. Le choix de position y est un arbitrage par défaut, "
                     "marqué `id_plusieurs_adresses` dans l'export.")


# --------------------------------------------------------------------------- #
# Segmentation
# --------------------------------------------------------------------------- #
def _mapper(df: pd.DataFrame, colonne: str, table: dict, cible: str,
            afficher=print) -> None:
    """Applique un mapping et signale toute modalité inconnue plutôt que de la
    ranger en « non renseigné » : une modalité muette fausserait tous les
    comptages sans laisser de trace."""
    if colonne not in df:
        return
    brut = df[colonne].astype("string").str.strip().str.upper()
    df[cible] = brut.map(table).fillna("Non renseigné")
    inconnues = sorted(set(brut.dropna().unique()) - set(table) - {""})
    if inconnues:
        n = int(brut.isin(inconnues).sum())
        afficher(f"⚠️  {colonne} : modalité(s) non reconnue(s) {inconnues} "
                 f"({n} lignes, {n / len(df):.1%}) → classées « Non renseigné ». "
                 "Compléter la table de correspondance.")


def segmenter(contrats: pd.DataFrame, afficher=print) -> pd.DataFrame:
    """Ajoute segment (RP / RS / PNO…), statut d'occupation et type de bien.

    Le segment se lit sur `code_sous_type`. Les segments hors demande — jeune,
    étudiant, hébergé — sont comptés à part plutôt qu'écartés en silence : ce
    sont aussi des logements occupés.
    """
    contrats = contrats.copy()
    contrats["code_sous_type"] = (contrats["code_sous_type"].astype("string")
                                  .str.strip().str.upper())
    contrats["segment"] = contrats["code_sous_type"].map(cfg.MAP_SOUS_TYPE).fillna("INCONNU")
    contrats["dans_perimetre_demande"] = contrats["segment"].isin(cfg.SEGMENTS_CIBLE)

    _mapper(contrats, "code_type_bien", cfg.LIB_TYPE_BIEN, "type_bien", afficher)
    _mapper(contrats, "code_qualite_assure_habitation", cfg.LIB_QUALITE, "qualite", afficher)
    if "code_qualite_assure_habitation" in contrats:
        q = (contrats["code_qualite_assure_habitation"].astype("string")
             .str.strip().str.upper())
        contrats["statut"] = q.map(cfg.STATUT_OCCUPATION).fillna("Autre / non renseigné")

    repartition = (contrats["segment"].value_counts(dropna=False).rename("contrats")
                   .to_frame()
                   .assign(part=lambda d: (d.contrats / d.contrats.sum()).map("{:.1%}".format),
                           libelle=lambda d: d.index.map(cfg.LIB_SEGMENT),
                           demande=lambda d: np.where(d.index.isin(cfg.SEGMENTS_CIBLE),
                                                      "✅", "—")))
    afficher(repartition[["libelle", "contrats", "part", "demande"]])
    return contrats


def rattacher_sinistres(contrats: pd.DataFrame, sinistres: pd.DataFrame,
                        afficher=print) -> pd.DataFrame:
    """Un indicateur de sinistre incendie ouvert par contrat.

    Un contrat peut porter plusieurs sinistres : on ramène à un compteur, les
    trois premiers numéros et la date de la première déclaration.
    """
    contrats = contrats.copy()
    sinistres = sinistres.copy()
    for c in CLE_CONTRAT:
        sinistres[c] = sinistres[c].astype("string").str.strip()

    agg = (sinistres.groupby(CLE_CONTRAT, dropna=False)
                    .agg(nb_sinistres_ouverts=("numero_sinistre", "nunique"),
                         numeros_sinistres=("numero_sinistre",
                                            lambda x: ", ".join(sorted(set(x.dropna()))[:3])),
                         date_declaration=("date_enregistrement", "min"))
                    .reset_index())

    contrats = contrats.merge(agg, how="left", on=CLE_CONTRAT)
    contrats["nb_sinistres_ouverts"] = contrats["nb_sinistres_ouverts"].fillna(0).astype(int)
    contrats["sinistre_declare"] = contrats["nb_sinistres_ouverts"] > 0

    afficher(f"{len(sinistres)} sinistre(s) ouvert(s) sur {len(agg)} contrat(s) "
             f"distinct(s).")
    afficher(f"{contrats['sinistre_declare'].sum()} contrat(s) de la zone analysée "
             f"portent un sinistre ouvert ({contrats['sinistre_declare'].mean():.1%}).")
    orphelins = len(agg) - contrats["sinistre_declare"].sum()
    if orphelins > 0:
        afficher(f"⚠️  {orphelins} contrat(s) sinistrés absents de l'extraction : hors "
                 "emprise géographique, ou hors du stock courant de contrat_mgar.")
    return contrats


# --------------------------------------------------------------------------- #
# Qualité du géocodage
# --------------------------------------------------------------------------- #
def geolocaliser(contrats: pd.DataFrame, afficher=print) -> tuple[gpd.GeoDataFrame, str | None]:
    """Construit les points en Lambert 93 et qualifie la précision du géocodage.

    Renvoie (points, nom de la colonne de précision utilisée ou None).

    Partager une coordonnée n'est pas un défaut en soi : un immeuble de 30 lots
    produit légitimement 30 contrats au même point, et sur le littoral landais
    les campings font partager un point à tous leurs emplacements. La colonne de
    précision de la table de géocodage, quand elle existe, fait donc foi sur
    toute heuristique.
    """
    contrats = contrats.dropna(subset=["lon_contrat_mgar", "lat_contrat_mgar"]).copy()
    pts = gpd.GeoDataFrame(
        contrats,
        geometry=gpd.points_from_xy(contrats["lon_contrat_mgar"],
                                    contrats["lat_contrat_mgar"]),
        crs=cfg.CRS_AFFICHAGE).to_crs(cfg.CRS_METRIQUE)

    pts["cle_xy"] = (pts.geometry.x.round(0).astype(int).astype(str) + "_"
                     + pts.geometry.y.round(0).astype(int).astype(str))
    pts["rue_norm"] = (pts.get("rue_adresse_risque", pd.Series("", index=pts.index))
                       .astype("string").str.upper()
                       .str.replace(r"\s+", " ", regex=True).str.strip())

    g = pts.groupby("cle_xy")
    nb_contrats_xy = g["id"].transform("size")
    nb_rues_xy = g["rue_norm"].transform("nunique")
    pts["coord_partagee"] = nb_contrats_xy >= cfg.SEUIL_COORD_PARTAGEE
    pts["coord_multi_voies"] = pts["coord_partagee"] & (nb_rues_xy > 1)
    pts["coord_immeuble"] = pts["coord_partagee"] & (nb_rues_xy == 1)
    pts["geocodage_suspect"] = pts["coord_multi_voies"]      # estimation provisoire

    afficher(f"{len(pts):,} contrats géolocalisés".replace(",", " "))
    afficher(f"{pts['cle_xy'].nunique():,} positions distinctes".replace(",", " "))

    recap = pd.DataFrame([
        {"cas": f"Coordonnée portant ≥ {cfg.SEUIL_COORD_PARTAGEE} contrats, une seule voie",
         "positions": int(pts.loc[pts["coord_immeuble"], "cle_xy"].nunique()),
         "contrats": int(pts["coord_immeuble"].sum()),
         "lecture": "immeuble — normal"},
        {"cas": f"Coordonnée portant ≥ {cfg.SEUIL_COORD_PARTAGEE} contrats, plusieurs voies",
         "positions": int(pts.loc[pts["coord_multi_voies"], "cle_xy"].nunique()),
         "contrats": int(pts["coord_multi_voies"].sum()),
         "lecture": "site à emplacements, ou centroïde — à qualifier"},
    ])
    recap["part des contrats"] = (recap["contrats"] / len(pts)).map("{:.1%}".format)
    afficher(recap.set_index("cas"))

    col_precision = next((c for c in cfg.CANDIDATS_COLONNE_PRECISION
                          if c in pts.columns), None)
    if col_precision is None:
        afficher("\nAucune colonne de précision de géocodage dans l'export : le "
                 "classement repose sur l'heuristique multi-voies, dont 94 % des "
                 "alertes se sont révélées fausses sur les données réelles.")
        return pts, None

    afficher(f"\nColonne de précision détectée : `{col_precision}` — elle fait foi.")
    modalite = pts[col_precision].astype("string").str.strip().str.lower()

    def classer(v):
        if pd.isna(v) or v == "":
            return "Non renseigné"
        if v in cfg.MODALITES_CENTROIDE_COMMUNE:
            return "Centroïde commune"
        if v in cfg.MODALITES_LIEU_DIT:
            return "Lieu-dit"
        if v in cfg.MODALITES_VOIE:
            return "Voie"
        if v in cfg.MODALITES_ADRESSE:
            return "Adresse exacte"
        return f"Non classé : {v}"

    pts["niveau_geocodage"] = modalite.map(classer)
    afficher(pts["niveau_geocodage"].value_counts(dropna=False)
             .rename("contrats").to_frame()
             .assign(part=lambda d: (d.contrats / len(pts)).map("{:.1%}".format)))

    non_classes = [m for m in modalite.dropna().unique() if classer(m).startswith("Non classé")]
    if non_classes:
        afficher(f"⚠️  Modalités non reconnues : {non_classes} → compléter les "
                 "ensembles MODALITES_* de config.py avant de conclure.")

    pts["geocodage_suspect_heuristique"] = pts["geocodage_suspect"]
    pts["geocodage_suspect"] = pts["niveau_geocodage"].isin(
        cfg.NIVEAUX_GEOCODAGE_INEXPLOITABLES)
    afficher(f"\nPositions non fiables : {pts['geocodage_suspect'].sum():,} contrats "
             f"({pts['geocodage_suspect'].mean():.1%})".replace(",", " "))

    tab = pd.crosstab(pts["geocodage_suspect_heuristique"], pts["geocodage_suspect"],
                      rownames=["heuristique multi-voies"], colnames=["colonne source"])
    afficher(tab)
    vp = int(tab.loc[True, True]) if True in tab.index and True in tab.columns else 0
    fp = int(tab.loc[True, False]) if True in tab.index and False in tab.columns else 0
    fn = int(tab.loc[False, True]) if False in tab.index and True in tab.columns else 0
    if vp + fp:
        afficher(f"\nL'heuristique alerte sur {vp + fp} contrats dont {fp} à tort "
                 f"({fp / (vp + fp):.0%}) et en manque {fn}. Elle confond les sites à "
                 "emplacements — campings, villages de vacances, où chaque « voie » est "
                 "un numéro d'emplacement — avec des centroïdes de commune.")
    return pts, col_precision


# --------------------------------------------------------------------------- #
# Appariement spatial
# --------------------------------------------------------------------------- #
def apparier(pts: gpd.GeoDataFrame, batis: gpd.GeoDataFrame,
             contours: gpd.GeoDataFrame, col_precision: str | None,
             afficher=print) -> gpd.GeoDataFrame:
    """Classe chaque contrat par niveau de certitude d'impact.

    Le niveau de géocodage borne ce qu'une distance autorise à conclure : les
    points au centroïde d'une commune ou d'un lieu-dit sont sortis du comptage,
    et les points posés sur l'axe d'une voie sont plafonnés à « très probable ».
    """
    bat_cols = ["bat_id", "feu", "surface_bati_m2", "geometry"]
    if len(batis):
        appar = gpd.sjoin_nearest(pts, batis[bat_cols], how="left",
                                  max_distance=max(cfg.SEUILS_SENSIBILITE_M),
                                  distance_col="distance_bati_m")
        # sjoin_nearest peut renvoyer plusieurs ex-aequo : on garde le plus proche
        appar = (appar.sort_values("distance_bati_m")
                      .loc[~appar.index.duplicated(keep="first")]
                      .sort_index()
                      .drop(columns=["index_right"], errors="ignore"))
    else:
        appar = pts.copy()
        appar["distance_bati_m"] = np.nan
        appar["bat_id"] = pd.NA
        appar["feu"] = pd.NA
        appar["surface_bati_m2"] = np.nan

    peri = gpd.sjoin(pts[["geometry"]], contours[["feu", "geometry"]],
                     how="left", predicate="within")
    peri = peri.loc[~peri.index.duplicated(keep="first")]
    appar["feu_perimetre"] = peri["feu"]

    def niveau(r):
        d = r["distance_bati_m"]
        if pd.notna(d):
            if d <= cfg.SEUIL_CERTAIN_M:      # dans l'emprise (0 m) ou collé au bâti
                return cfg.NIV_CERTAIN
            if d <= cfg.SEUIL_TRES_PROBABLE_M:
                return cfg.NIV_TRES_PROBABLE
            if d <= cfg.SEUIL_PROBABLE_M:
                return cfg.NIV_PROBABLE
        if pd.notna(r["feu_perimetre"]):
            return cfg.NIV_EXPOSE
        return cfg.NIV_HORS

    appar["niveau_impact"] = appar.apply(niveau, axis=1)
    appar["feu_rattache"] = appar["feu"].fillna(appar["feu_perimetre"])

    if col_precision:
        geo = appar["niveau_geocodage"]

        if cfg.PLAFONNER_NIVEAU_VOIE:
            a_plafonner = (geo == "Voie") & (appar["niveau_impact"] == cfg.NIV_CERTAIN)
            appar.loc[a_plafonner, "niveau_impact"] = cfg.NIV_TRES_PROBABLE
            if a_plafonner.any():
                afficher(f"{a_plafonner.sum()} contrat(s) géocodés à la voie tombaient "
                         "dans une emprise : ramenés de « certain » à « très probable » "
                         "— sur un axe de voie, c'est une coïncidence géométrique, pas "
                         "une preuve.")

        # Le doute ne concerne que les contrats qui auraient été retenus : un
        # contrat à 40 km du feu n'est pas « trop imprécis pour conclure », il est
        # hors sujet. Les basculer tous gonflerait le compteur d'un bruit sans
        # rapport avec le sinistre — et la carte d'autant de marqueurs inutiles.
        inexploitable = (geo.isin(cfg.NIVEAUX_GEOCODAGE_INEXPLOITABLES)
                         & (appar["niveau_impact"] != cfg.NIV_HORS))
        appar.loc[inexploitable, "niveau_impact"] = cfg.NIVEAU_INEXPLOITABLE
        if inexploitable.any():
            total = int(geo.isin(cfg.NIVEAUX_GEOCODAGE_INEXPLOITABLES).sum())
            afficher(f"{inexploitable.sum()} contrat(s) au centroïde de commune ou de "
                     "lieu-dit ET dans la zone du feu : sortis du comptage, leur "
                     "distance à un bâtiment ne veut rien dire.")
            afficher(f"  ({total} contrats sont géocodés à ce niveau sur l'ensemble de "
                     "la zone analysée ; les autres sont hors périmètre, hors sujet.)")

    appar["est_impacte"] = appar["niveau_impact"].isin(cfg.niveaux_impactes())
    # Le bâti le plus proche est conservé quel que soit le seuil (test de
    # sensibilité), mais n'est déclaré « touché » que pour les contrats impactés.
    appar["bat_id_brut"] = appar["bat_id"]
    appar.loc[~appar["est_impacte"], "bat_id"] = pd.NA

    appar = _dedoublonner(appar, col_precision, afficher)

    appar["niveau_impact"] = pd.Categorical(appar["niveau_impact"],
                                            cfg.ordre_niveaux(), ordered=True)
    afficher(appar["niveau_impact"].value_counts().sort_index()
             .rename("contrats").to_frame())
    return appar


def _dedoublonner(appar: gpd.GeoDataFrame, col_precision: str | None,
                  afficher=print) -> gpd.GeoDataFrame:
    """Un contrat, une position.

    Les lignes en double sont des géocodages concurrents du même contrat. On
    retient le plus précis — `level_contrat_mgar` fait foi, `housenumber` en
    tête — puis, à niveau égal, la première ligne venue.

    Le second critère n'arbitre rien : à niveau égal les positions concurrentes
    peuvent être distantes de plusieurs kilomètres, et aucune information
    disponible ici ne permet de les départager. Prendre la première est un choix
    par défaut assumé, et surtout **neutre** — comme le niveau. Départager sur la
    distance au bâti reviendrait à retenir systématiquement la position la plus
    incriminante, donc à surestimer l'impact par construction.

    Le caractère arbitraire du choix n'est pas perdu : `ecart_positions_m` mesure
    l'étendue des candidats et `position_incertaine` signale ceux qui se jouent
    au-delà de SEUIL_ECART_POSITIONS_M.
    """
    appar["id_plusieurs_positions"] = appar["id"].duplicated(keep=False)

    # À adresse identique le niveau tranche sans ambiguïté ; à adresses
    # différentes, choisir un niveau revient à choisir un lieu de risque, ce
    # qu'aucune règle automatique ne peut fonder. Ces cas sont signalés.
    adresse = (appar["rue_norm"].fillna("") + "|"
               + appar["code_postal_adresse_risque"].astype("string").fillna("") + "|"
               + appar.get("commune_adresse_risque",
                           pd.Series("", index=appar.index)).astype("string").fillna(""))
    n_adresses = adresse.groupby(appar["id"]).transform("nunique")
    appar["id_plusieurs_adresses"] = appar["id_plusieurs_positions"] & (n_adresses > 1)

    avant = len(appar)
    appar["_rang_geo"] = (appar["niveau_geocodage"].map(cfg.RANG_NIVEAU_GEOCODAGE).fillna(9)
                          if col_precision else 0)

    # Seules les lignes du meilleur niveau sont en concurrence : c'est entre
    # elles, et elles seules, que le choix se joue. Mesurer l'étendue sur toutes
    # les lignes signalerait à tort le contrat dont l'unique `housenumber` est net
    # mais qui traîne trois centroïdes de commune à 40 km.
    meilleur = appar.groupby("id")["_rang_geo"].transform("min")
    candidat = appar["_rang_geo"] == meilleur

    # Étendue des positions candidates : deux géocodages à 5 m l'un de l'autre
    # sont sans conséquence, à 3 km la position retenue relève du tirage au sort.
    cand = appar.loc[candidat]
    etendue = (pd.DataFrame({"id": cand["id"].to_numpy(),
                             "_x": cand.geometry.x.to_numpy(),
                             "_y": cand.geometry.y.to_numpy()})
                 .groupby("id").agg(x0=("_x", "min"), x1=("_x", "max"),
                                    y0=("_y", "min"), y1=("_y", "max")))
    ecart = np.hypot(etendue.x1 - etendue.x0, etendue.y1 - etendue.y0)
    appar["ecart_positions_m"] = appar["id"].map(ecart).round(1)
    appar["position_incertaine"] = appar["ecart_positions_m"] > cfg.SEUIL_ECART_POSITIONS_M

    # `kind="stable"` : à niveau égal l'ordre d'origine est préservé, donc
    # `keep="first"` retient bien la première ligne venue.
    appar = (appar.sort_values("_rang_geo", kind="stable")
                  .drop_duplicates(subset="id", keep="first")
                  .sort_index()
                  .drop(columns=["_rang_geo"], errors="ignore"))

    if avant == len(appar):
        return appar

    multi = appar["id_plusieurs_positions"].sum()
    multi_adr = appar["id_plusieurs_adresses"].sum()
    afficher(f"{avant - len(appar)} ligne(s) écartée(s) sur {multi} contrat(s) à "
             "géocodages concurrents.")
    afficher(f"  {multi - multi_adr} à adresse identique — le niveau tranche ;")
    afficher(f"  {multi_adr} à adresses différentes — plusieurs lieux de risque "
             "possibles, marqués `id_plusieurs_adresses` : la règle ne fait qu'un "
             "choix par défaut.")
    if col_precision:
        retenus = appar.loc[appar["id_plusieurs_positions"], "niveau_geocodage"]
        afficher("  niveau retenu pour ces contrats :")
        for niv, nb in retenus.value_counts().items():
            afficher(f"    {niv:<20} {nb}")
    ecarts = appar.loc[appar["id_plusieurs_positions"], "ecart_positions_m"]
    loin = int((ecarts > cfg.SEUIL_ECART_POSITIONS_M).sum())
    afficher(f"  écart entre positions candidates : médiane {ecarts.median():.0f} m, "
             f"max {ecarts.max():.0f} m")
    afficher(f"  {loin} contrat(s) au-delà de {cfg.SEUIL_ECART_POSITIONS_M:.0f} m "
             "d'écart : la position retenue y est un choix par défaut, pas une "
             "localisation fiable — marqués `position_incertaine` dans l'export.")
    garde = appar.loc[appar["id_plusieurs_positions"] & appar["est_impacte"]]
    afficher(f"  dont {len(garde)} contrat(s) impacté(s) issus d'une clé à plusieurs "
             "positions — leur localisation demande vérification.")
    return appar
