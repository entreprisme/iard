"""
Webapp minimale : upload d'un fichier Excel « Classeur1 » (colonnes C_I_SOCS et
ANC_REF) et téléchargement des deux cartes de grêle dans une archive ZIP.

Logique métier reprise du notebook Grelev3.
"""

from __future__ import annotations

import io
import math
import os
import zipfile
from functools import lru_cache
from pathlib import Path

import branca.colormap as cm
import folium
import geopandas as gpd
import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from folium.features import GeoJsonTooltip
from shapely.ops import unary_union

COL_INSEE = "C_I_SOCS"
COL_ID = "ANC_REF"

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
COMMUNES_GEOJSON = Path(
    os.environ.get("COMMUNES_GEOJSON", DATA_DIR / "correspondance-code-insee-code-postal.geojson")
)
DEPARTEMENTS_GEOJSON = Path(
    os.environ.get("DEPARTEMENTS_GEOJSON", DATA_DIR / "departement.geojson")
)

app = FastAPI(title="Cartes de grêle")

PAGE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cartes de grêle</title></head>
<body style="font-family:system-ui;max-width:520px;margin:3rem auto;padding:0 1rem">
<h1>🌧️ Cartes de grêle</h1>
<p>Déposez votre fichier Excel au format <b>Classeur1</b>
(colonnes <code>C_I_SOCS</code> et <code>ANC_REF</code>) pour télécharger les cartes.</p>
<form action="/generate" method="post" enctype="multipart/form-data">
  <input type="file" name="file" accept=".xlsx,.xls" required>
  <button type="submit">Générer les cartes</button>
</form>
</body></html>"""


# --------------------------------------------------------------------------- #
# Normalisation                                                               #
# --------------------------------------------------------------------------- #
def normalize_code(value):
    if pd.isna(value):
        return None
    value = str(value).strip()
    if value.endswith(".0"):
        value = value[:-2]
    return value.zfill(5)


# --------------------------------------------------------------------------- #
# Référentiel communes (coûteux -> mis en cache sur chemin + mtime)           #
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=2)
def load_communes(path_str: str, _mtime: float) -> gpd.GeoDataFrame:
    raw = gpd.read_file(path_str)
    gdf = raw.rename(
        columns={"insee_com": "code_insee", "postal_code": "code_postal", "nom_comm": "nom_com"}
    )
    missing = {"code_insee", "code_postal", "nom_com", "geometry"} - set(gdf.columns)
    if missing:
        raise HTTPException(503, f"Colonnes absentes du geojson communes : {sorted(missing)}")

    gdf = gdf[["code_insee", "code_postal", "nom_com", "geometry"]].copy()
    gdf["code_insee"] = gdf["code_insee"].apply(normalize_code)
    gdf["code_postal"] = gdf["code_postal"].astype(str).str.split("/")
    gdf = gdf.explode("code_postal")
    gdf["code_postal"] = gdf["code_postal"].apply(normalize_code)
    gdf = gdf.drop_duplicates(
        subset=["code_insee", "code_postal", "nom_com", "geometry"]
    ).reset_index(drop=True)

    # Fusion des arrondissements Paris / Marseille / Lyon
    extra = []
    for prefix, name, insee, cp in [
        ("MARSEILLE", "MARSEILLE", "13055", "13000"),
        ("LYON", "LYON", "69123", "69000"),
        ("PARIS", "PARIS", "75056", "75000"),
    ]:
        mask = gdf["nom_com"].str.startswith(prefix, na=False) & gdf["nom_com"].str.endswith(
            "ARRONDISSEMENT", na=False
        )
        arr = gdf.loc[mask]
        if not arr.empty:
            row = arr.iloc[[0]].copy()
            row["code_insee"], row["code_postal"], row["nom_com"] = insee, cp, name
            row["geometry"] = unary_union(arr.geometry.values)
            extra.append(row)
    if extra:
        gdf = pd.concat([gdf, *extra], ignore_index=True)

    gdf = gpd.GeoDataFrame(gdf, geometry="geometry", crs=raw.crs or "EPSG:4326")
    gdf["code_insee"] = gdf["code_insee"].apply(normalize_code)
    return gdf


@lru_cache(maxsize=2)
def load_departements(path_str: str, _mtime: float) -> gpd.GeoDataFrame:
    return gpd.read_file(path_str)


def _referentiel(path: Path, loader):
    if not path.exists():
        raise HTTPException(503, f"Référentiel introuvable : {path}. Voir README (dossier data/).")
    return loader(str(path), path.stat().st_mtime)


# --------------------------------------------------------------------------- #
# Génération des cartes                                                       #
# --------------------------------------------------------------------------- #
def _centroids(gdf):
    return gdf.geometry.to_crs("EPSG:2154").centroid.to_crs("EPSG:4326")


def build_maps(xlsx_bytes: bytes):
    try:
        df = pd.read_excel(io.BytesIO(xlsx_bytes), dtype=str)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Fichier Excel illisible : {exc}") from exc

    missing = {COL_INSEE, COL_ID} - set(df.columns)
    if missing:
        raise HTTPException(400, f"Colonnes obligatoires absentes : {sorted(missing)} (format Classeur1).")
    df[COL_INSEE] = df[COL_INSEE].apply(normalize_code)

    gdf_com = _referentiel(COMMUNES_GEOJSON, load_communes)
    gdf_dept = _referentiel(DEPARTEMENTS_GEOJSON, load_departements)

    merged = df.merge(gdf_com, how="left", left_on=COL_INSEE, right_on="code_insee")
    stats = (
        merged.dropna(subset=["geometry"])
        .groupby([COL_INSEE, "code_insee", "code_postal", "nom_com"], dropna=False)[COL_ID]
        .count()
        .reset_index()
    )
    if stats.empty:
        raise HTTPException(400, "Aucun sinistre géolocalisé (codes INSEE non reconnus).")

    geoms = gdf_com.drop_duplicates(subset=["code_insee"])[["code_insee", "geometry"]]
    stats = stats.merge(geoms, how="left", on="code_insee")
    gdf = gpd.GeoDataFrame(stats, geometry="geometry", crs="EPSG:4326")

    max_sin = max(1, int(gdf[COL_ID].max()))
    linear = (
        cm.LinearColormap(colors=cm.linear.YlOrRd_05.scale().to_step(14).colors[5:])
        .scale(0, max_sin)
        .to_step(20)
    )
    linear.caption = "Nombre de sinistres grêle"

    def base_map():
        c = _centroids(gdf)
        m = folium.Map(location=[c.y.mean(), c.x.mean()], zoom_start=6, control_scale=True)
        folium.GeoJson(
            gdf_dept,
            style_function=lambda _: {"color": "black", "weight": 0.75, "fillOpacity": 0},
            name="Départements",
        ).add_to(m)
        return m, c

    # Carte 1 : points proportionnels
    m1, centroids = base_map()
    for row, centroid in zip(gdf.itertuples(), centroids):
        nb = getattr(row, COL_ID)
        folium.CircleMarker(
            location=[centroid.y, centroid.x],
            popup=f"{row.nom_com}<br>INSEE : {row.code_insee}<br>Nombre sinistres : {nb}",
            radius=max(2, 2 * math.sqrt(float(nb))),
            color=linear(nb),
            fill=True,
            fill_color=linear(nb),
        ).add_to(m1)
    linear.add_to(m1)

    # Carte 2 : polygones communaux
    m2, _ = base_map()
    folium.GeoJson(
        gdf,
        style_function=lambda x: {
            "fillColor": linear(x["properties"][COL_ID]),
            "color": "black",
            "fillOpacity": 0.5,
            "weight": 0.2,
            "dashArray": "5, 5",
        },
        tooltip=GeoJsonTooltip(
            fields=["nom_com", COL_INSEE, COL_ID],
            aliases=["Commune", "Code INSEE sinistre", "Nombre de sinistres"],
            localize=True,
        ),
        highlight_function=lambda _: {"weight": 0.5, "color": "black"},
        name="Sinistres grêle par commune",
    ).add_to(m2)
    folium.LayerControl(position="bottomright").add_to(m2)
    linear.add_to(m2)

    return m1.get_root().render(), m2.get_root().render()


# --------------------------------------------------------------------------- #
# Routes                                                                      #
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE


@app.post("/generate")
async def generate(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith((".xlsx", ".xls")):
        raise HTTPException(400, "Merci d'uploader un fichier Excel (.xlsx) au format Classeur1.")

    points_html, polys_html = build_maps(await file.read())

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("grele_1_points.html", points_html)
        zf.writestr("grele_2_polygones.html", polys_html)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="cartes_grele.zip"'},
    )
