"""
Logique métier de génération des cartes de grêle.

Reprise fidèle du notebook ``Grelev3`` :

- lecture d'un fichier Excel au format « Classeur1 » (colonnes ``C_I_SOCS`` et
  ``ANC_REF``) ;
- géolocalisation par code INSEE commune (jointure sur ``insee_com`` du
  référentiel communes) ;
- regroupement des arrondissements de Paris / Marseille / Lyon ;
- comptage des sinistres par commune (``ANC_REF``) ;
- production de deux cartes Folium : points proportionnels (``grele_1``) et
  polygones communaux (``grele_2``).

Le module est conçu pour être appelé par une webapp : il prend les octets du
fichier Excel en entrée et renvoie le HTML des deux cartes + un petit rapport
qualité, sans jamais écrire sur le disque.
"""

from __future__ import annotations

import io
import math
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

import branca.colormap as cm
import folium
import geopandas as gpd
import pandas as pd
from folium.features import GeoJsonTooltip
from shapely.ops import unary_union

# ---------------------------------------------------------------------------
# Colonnes métier (identiques au notebook Grele.ipynb / Grelev3)
# ---------------------------------------------------------------------------
COL_CODE_INSEE_SINISTRE = "C_I_SOCS"
COL_ID_SINISTRE = "ANC_REF"

# ---------------------------------------------------------------------------
# Chemins des référentiels géographiques (surchargables par variables d'env)
# ---------------------------------------------------------------------------
DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
COMMUNES_GEOJSON = Path(
    os.environ.get(
        "COMMUNES_GEOJSON",
        DATA_DIR / "correspondance-code-insee-code-postal.geojson",
    )
)
DEPARTEMENTS_GEOJSON = Path(
    os.environ.get("DEPARTEMENTS_GEOJSON", DATA_DIR / "departement.geojson")
)


class ReferentielManquant(Exception):
    """Levée lorsqu'un fichier de référentiel géographique est introuvable."""


class FichierSinistresInvalide(Exception):
    """Levée lorsque le fichier Excel uploadé n'a pas le format attendu."""


@dataclass
class ResultatCartes:
    """Résultat de la génération : HTML des cartes + rapport qualité."""

    carte_points_html: str
    carte_polygones_html: str
    nb_communes: int
    nb_sinistres_localises: int
    nb_sinistres_non_localises: int
    codes_insee_non_localises: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Fonctions utilitaires de normalisation
# ---------------------------------------------------------------------------
def normalize_insee(value):
    if pd.isna(value):
        return None
    value = str(value).strip()
    if value.endswith(".0"):
        value = value[:-2]
    return value.zfill(5)


def normalize_postal(value):
    if pd.isna(value):
        return None
    value = str(value).strip()
    if value.endswith(".0"):
        value = value[:-2]
    return value.zfill(5)


# ---------------------------------------------------------------------------
# Chargement / standardisation du référentiel communes (coûteux -> mis en cache)
# ---------------------------------------------------------------------------
def _build_city_from_arrondissements(gdf, city_prefix, city_name, code_insee, code_postal):
    """Regroupe les arrondissements d'une ville en une seule commune."""
    mask = (
        gdf["nom_com"].str.startswith(city_prefix, na=False)
        & gdf["nom_com"].str.endswith("ARRONDISSEMENT", na=False)
    )
    arr = gdf.loc[mask].copy()
    if arr.empty:
        return None

    geom = unary_union(arr.geometry.values)
    row = arr.iloc[[0]].copy()
    row["code_insee"] = code_insee
    row["code_postal"] = code_postal
    row["nom_com"] = city_name
    row["geometry"] = geom
    return row


def _load_communes_uncached(path_str: str, _mtime: float) -> gpd.GeoDataFrame:
    raw_communes = gpd.read_file(path_str)

    rename_map = {}
    if "insee_com" in raw_communes.columns:
        rename_map["insee_com"] = "code_insee"
    if "postal_code" in raw_communes.columns:
        rename_map["postal_code"] = "code_postal"
    if "nom_comm" in raw_communes.columns:
        rename_map["nom_comm"] = "nom_com"

    gdf_com = raw_communes.rename(columns=rename_map).copy()

    required_geo_cols = {"code_insee", "code_postal", "nom_com", "geometry"}
    missing_geo_cols = required_geo_cols - set(gdf_com.columns)
    if missing_geo_cols:
        raise ReferentielManquant(
            "Colonnes obligatoires absentes du geojson communes : "
            + ", ".join(sorted(missing_geo_cols))
        )

    gdf_com = gdf_com[["code_insee", "code_postal", "nom_com", "geometry"]].copy()
    gdf_com["code_insee"] = gdf_com["code_insee"].apply(normalize_insee)

    # Certains fichiers regroupent plusieurs codes postaux dans une cellule.
    gdf_com["code_postal"] = gdf_com["code_postal"].astype(str).str.split("/")
    gdf_com = gdf_com.explode("code_postal")
    gdf_com["code_postal"] = gdf_com["code_postal"].apply(normalize_postal)

    gdf_com = gdf_com.drop_duplicates(
        subset=["code_insee", "code_postal", "nom_com", "geometry"]
    ).reset_index(drop=True)

    # Paris / Marseille / Lyon : on fusionne les arrondissements.
    extra_rows = []
    for args in [
        ("MARSEILLE", "MARSEILLE", "13055", "13000"),
        ("LYON", "LYON", "69123", "69000"),
        ("PARIS", "PARIS", "75056", "75000"),
    ]:
        city_row = _build_city_from_arrondissements(gdf_com, *args)
        if city_row is not None:
            extra_rows.append(city_row)

    if extra_rows:
        gdf_com = pd.concat([gdf_com, *extra_rows], ignore_index=True)

    gdf_com = gpd.GeoDataFrame(
        gdf_com, geometry="geometry", crs=raw_communes.crs or "EPSG:4326"
    )
    gdf_com["code_insee"] = gdf_com["code_insee"].apply(normalize_insee)
    return gdf_com


@lru_cache(maxsize=4)
def _load_communes_cached(path_str: str, mtime: float) -> gpd.GeoDataFrame:
    return _load_communes_uncached(path_str, mtime)


def load_communes(path: Optional[Path] = None) -> gpd.GeoDataFrame:
    path = Path(path or COMMUNES_GEOJSON)
    if not path.exists():
        raise ReferentielManquant(
            f"Référentiel communes introuvable : {path}. "
            "Placez le fichier 'correspondance-code-insee-code-postal.geojson' "
            "dans le dossier data/ (voir README)."
        )
    return _load_communes_cached(str(path), path.stat().st_mtime)


@lru_cache(maxsize=4)
def _load_departements_cached(path_str: str, mtime: float) -> gpd.GeoDataFrame:
    return gpd.read_file(path_str)


def load_departements(path: Optional[Path] = None) -> gpd.GeoDataFrame:
    path = Path(path or DEPARTEMENTS_GEOJSON)
    if not path.exists():
        raise ReferentielManquant(f"Référentiel départements introuvable : {path}.")
    return _load_departements_cached(str(path), path.stat().st_mtime)


# ---------------------------------------------------------------------------
# Lecture du fichier sinistres (Excel « Classeur1 »)
# ---------------------------------------------------------------------------
def read_sinistres(xlsx_bytes: bytes) -> pd.DataFrame:
    try:
        df = pd.read_excel(io.BytesIO(xlsx_bytes), dtype=str)
    except Exception as exc:  # noqa: BLE001
        raise FichierSinistresInvalide(
            f"Impossible de lire le fichier Excel : {exc}"
        ) from exc

    required_cols = {COL_CODE_INSEE_SINISTRE, COL_ID_SINISTRE}
    missing_cols = required_cols - set(df.columns)
    if missing_cols:
        raise FichierSinistresInvalide(
            "Colonnes obligatoires absentes du fichier : "
            + ", ".join(sorted(missing_cols))
            + f". Le format attendu (Classeur1) contient {COL_CODE_INSEE_SINISTRE} "
            f"et {COL_ID_SINISTRE}."
        )

    df[COL_CODE_INSEE_SINISTRE] = df[COL_CODE_INSEE_SINISTRE].apply(normalize_insee)
    return df


# ---------------------------------------------------------------------------
# Construction des cartes
# ---------------------------------------------------------------------------
def _centroids_4326(gdf: gpd.GeoDataFrame) -> gpd.GeoSeries:
    """Centroïdes corrects : calcul en projection métrique (Lambert 93) puis WGS84."""
    return gdf.geometry.to_crs("EPSG:2154").centroid.to_crs("EPSG:4326")


def _make_carte_points(gdf, gdf_dept, linear) -> str:
    centroids = _centroids_4326(gdf)
    n = folium.Map(
        location=[centroids.y.mean(), centroids.x.mean()],
        zoom_start=6,
        control_scale=True,
    )
    folium.GeoJson(
        gdf_dept,
        style_function=lambda _: {"color": "black", "weight": 0.75, "fillOpacity": 0},
        name="Départements",
    ).add_to(n)

    for row, centroid in zip(gdf.itertuples(), centroids):
        if row.geometry is None:
            continue
        nb = getattr(row, COL_ID_SINISTRE)
        folium.CircleMarker(
            location=[centroid.y, centroid.x],
            popup=f"{row.nom_com}<br>INSEE : {row.code_insee}<br>Nombre sinistres : {nb}",
            radius=max(2, 2 * math.sqrt(float(nb))),
            color=linear(nb),
            fill=True,
            fill_color=linear(nb),
        ).add_to(n)

    linear.add_to(n)
    return n.get_root().render()


def _make_carte_polygones(gdf, gdf_dept, linear) -> str:
    centroids = _centroids_4326(gdf)
    m = folium.Map(
        location=[centroids.y.mean(), centroids.x.mean()],
        zoom_start=6,
        control_scale=True,
    )

    tooltip = GeoJsonTooltip(
        fields=["nom_com", COL_CODE_INSEE_SINISTRE, COL_ID_SINISTRE],
        aliases=["Commune", "Code INSEE sinistre", "Nombre de sinistres"],
        localize=True,
        sticky=False,
        labels=True,
    )

    folium.GeoJson(
        gdf_dept,
        style_function=lambda _: {"color": "black", "weight": 0.75, "fillOpacity": 0},
        name="Départements",
    ).add_to(m)

    folium.GeoJson(
        gdf,
        style_function=lambda x: {
            "fillColor": linear(x["properties"][COL_ID_SINISTRE]),
            "color": "black",
            "fillOpacity": 0.5,
            "weight": 0.2,
            "dashArray": "5, 5",
        },
        tooltip=tooltip,
        highlight_function=lambda _: {"weight": 0.5, "color": "black"},
        name="Sinistres grêle par commune",
    ).add_to(m)

    folium.LayerControl(position="bottomright").add_to(m)
    linear.add_to(m)
    return m.get_root().render()


def build_maps(
    xlsx_bytes: bytes,
    communes_path: Optional[Path] = None,
    departements_path: Optional[Path] = None,
) -> ResultatCartes:
    """Génère les deux cartes de grêle à partir du fichier Excel uploadé."""
    df = read_sinistres(xlsx_bytes)
    gdf_com = load_communes(communes_path)
    gdf_dept = load_departements(departements_path)

    # Jointure métier : C_I_SOCS -> code_insee
    df_merge = df.merge(
        gdf_com,
        how="left",
        left_on=COL_CODE_INSEE_SINISTRE,
        right_on="code_insee",
    )

    # Agrégation par commune (comptage des ANC_REF)
    df_stats = (
        df_merge.dropna(subset=["geometry"])
        .groupby(
            [COL_CODE_INSEE_SINISTRE, "code_insee", "code_postal", "nom_com"],
            dropna=False,
        )[COL_ID_SINISTRE]
        .count()
        .reset_index()
    )

    if df_stats.empty:
        raise FichierSinistresInvalide(
            "Aucun sinistre n'a pu être géolocalisé : vérifiez que les codes INSEE "
            f"({COL_CODE_INSEE_SINISTRE}) correspondent au référentiel communes."
        )

    geoms = gdf_com.drop_duplicates(subset=["code_insee"])[["code_insee", "geometry"]]
    df_stats = df_stats.merge(geoms, how="left", on="code_insee")
    gdf = gpd.GeoDataFrame(df_stats, geometry="geometry", crs="EPSG:4326")

    # Échelle de couleurs
    max_sin = max(1, int(gdf[COL_ID_SINISTRE].max()))
    linear = cm.LinearColormap(
        colors=cm.linear.YlOrRd_05.scale().to_step(14).colors[5:]
    ).scale(0, max_sin).to_step(20)
    linear.caption = "Nombre de sinistres grêle"

    carte_points = _make_carte_points(gdf, gdf_dept, linear)
    carte_polygones = _make_carte_polygones(gdf, gdf_dept, linear)

    # Rapport qualité
    non_loc_mask = df_merge["geometry"].isna()
    codes_non_loc = sorted(
        df_merge.loc[non_loc_mask, COL_CODE_INSEE_SINISTRE].dropna().unique().tolist()
    )

    return ResultatCartes(
        carte_points_html=carte_points,
        carte_polygones_html=carte_polygones,
        nb_communes=len(gdf),
        nb_sinistres_localises=int(gdf[COL_ID_SINISTRE].sum()),
        nb_sinistres_non_localises=int(non_loc_mask.sum()),
        codes_insee_non_localises=codes_non_loc,
    )
