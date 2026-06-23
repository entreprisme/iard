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
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cartes de grêle</title>
<style>
  *{box-sizing:border-box}
  body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
    font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:#1f2937;
    background:linear-gradient(135deg,#1e3a8a 0%,#2563eb 55%,#38bdf8 100%);padding:1.5rem}
  .card{background:#fff;border-radius:18px;box-shadow:0 20px 50px rgba(0,0,0,.25);
    width:100%;max-width:540px;padding:2.5rem}
  h1{margin:0 0 .25rem;font-size:1.6rem}
  .sub{margin:0 0 1.75rem;color:#6b7280;font-size:.95rem;line-height:1.5}
  code{background:#eff6ff;color:#1e3a8a;padding:.1rem .4rem;border-radius:5px;font-size:.85em}
  .drop{border:2px dashed #cbd5e1;border-radius:14px;padding:2.25rem 1rem;text-align:center;
    cursor:pointer;transition:.15s;display:block}
  .drop:hover{border-color:#93c5fd;background:#f8fafc}
  .drop.drag{border-color:#2563eb;background:#eff6ff}
  .drop .icon{font-size:2.75rem;line-height:1}
  .drop .label{margin-top:.6rem;color:#64748b;font-size:.92rem}
  .filename{margin-top:.7rem;font-weight:600;color:#1e3a8a;word-break:break-all}
  .drop input{display:none}
  button{margin-top:1.5rem;width:100%;border:none;border-radius:12px;padding:.9rem 1rem;
    font-size:1rem;font-weight:600;color:#fff;background:#2563eb;cursor:pointer;transition:.15s}
  button:hover:not(:disabled){background:#1e3a8a}
  button:disabled{background:#9ca3af;cursor:not-allowed}
  .msg{margin-top:1.1rem;padding:.85rem 1rem;border-radius:10px;font-size:.9rem;
    line-height:1.45;display:none}
  .msg.show{display:block}
  .msg.ok{background:#ecfdf5;color:#065f46;border:1px solid #a7f3d0}
  .msg.err{background:#fef2f2;color:#b91c1c;border:1px solid #fecaca}
  .msg.info{background:#eff6ff;color:#1e3a8a;border:1px solid #bfdbfe}
  .msg b{font-weight:700}
  .spin{display:inline-block;width:1em;height:1em;border:2px solid rgba(255,255,255,.5);
    border-top-color:#fff;border-radius:50%;animation:spin .7s linear infinite;
    vertical-align:-.15em;margin-right:.5rem}
  @keyframes spin{to{transform:rotate(360deg)}}
  .hint{margin-top:1.5rem;font-size:.8rem;color:#9ca3af;line-height:1.5}
</style>
</head>
<body>
  <div class="card">
    <h1>🌧️ Cartes de grêle</h1>
    <p class="sub">Déposez votre fichier Excel au format <b>Classeur1</b>
      (colonnes <code>C_I_SOCS</code> et <code>ANC_REF</code>) pour générer et
      télécharger les cartes.</p>

    <label class="drop" id="drop">
      <div class="icon">📄</div>
      <div class="label">Cliquez ou glissez votre fichier <code>.xlsx</code> ici</div>
      <div class="filename" id="filename"></div>
      <input type="file" id="file" accept=".xlsx,.xls">
    </label>
    <button id="submit" disabled>Générer les cartes</button>

    <div class="msg" id="msg"></div>

    <p class="hint">L'archive téléchargée contient deux cartes interactives :
      <code>grele_1_points.html</code> (points proportionnels) et
      <code>grele_2_polygones.html</code> (polygones communaux).</p>
  </div>

<script>
const drop=document.getElementById("drop"),input=document.getElementById("file"),
  fn=document.getElementById("filename"),btn=document.getElementById("submit"),
  msg=document.getElementById("msg");

function show(html,type){msg.innerHTML=html;msg.className="msg show "+type;}
function hide(){msg.className="msg";}

input.onchange=()=>{
  if(input.files.length){fn.textContent=input.files[0].name;btn.disabled=false;hide();}
  else{fn.textContent="";btn.disabled=true;}
};
["dragenter","dragover"].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.add("drag");}));
["dragleave","drop"].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.remove("drag");}));
drop.addEventListener("drop",ev=>{if(ev.dataTransfer.files.length){input.files=ev.dataTransfer.files;input.onchange();}});

async function errDetail(resp){try{return (await resp.json()).detail;}catch(e){return "Erreur "+resp.status;}}

btn.onclick=async()=>{
  if(!input.files.length)return;
  const f=input.files[0];
  btn.disabled=true;

  // 1) Validation du format
  show('<span class="spin"></span>Vérification du format du fichier…',"info");
  try{
    const fd=new FormData();fd.append("file",f);
    const v=await fetch("/validate",{method:"POST",body:fd});
    if(!v.ok)throw new Error(await errDetail(v));
    const r=await v.json();
    show("✅ <b>Format Excel valide.</b><br>"+r.lignes+" lignes — "+
      r.codes_insee_distincts+" codes INSEE distincts. Colonnes <code>"+
      r.colonnes.join("</code> et <code>")+"</code> détectées.<br>"+
      '<span class="spin"></span>Génération des cartes…',"ok");
  }catch(e){show("❌ "+e.message,"err");btn.disabled=false;
    btn.textContent="Générer les cartes";return;}

  // 2) Génération + téléchargement
  btn.innerHTML='<span class="spin"></span>Génération en cours…';
  try{
    const fd=new FormData();fd.append("file",f);
    const g=await fetch("/generate",{method:"POST",body:fd});
    if(!g.ok)throw new Error(await errDetail(g));
    const url=URL.createObjectURL(await g.blob());
    const a=document.createElement("a");a.href=url;a.download="cartes_grele.zip";
    document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url);
    show("✅ <b>Cartes générées et téléchargées</b> (cartes_grele.zip).","ok");
  }catch(e){show("❌ "+e.message,"err");}
  finally{btn.disabled=false;btn.textContent="Générer les cartes";}
};
</script>
</body>
</html>"""


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


def parse_sinistres(xlsx_bytes: bytes) -> pd.DataFrame:
    """Lit et valide le fichier Excel « Classeur1 ». Lève HTTPException(400) si KO."""
    try:
        df = pd.read_excel(io.BytesIO(xlsx_bytes), dtype=str)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Fichier Excel illisible : {exc}") from exc

    missing = {COL_INSEE, COL_ID} - set(df.columns)
    if missing:
        raise HTTPException(
            400,
            f"Format invalide : colonne(s) manquante(s) {sorted(missing)}. "
            f"Le format Classeur1 attend les colonnes {COL_INSEE} et {COL_ID}.",
        )
    df[COL_INSEE] = df[COL_INSEE].apply(normalize_code)
    return df


def build_maps(xlsx_bytes: bytes):
    df = parse_sinistres(xlsx_bytes)

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


def _check_extension(file: UploadFile):
    if not (file.filename or "").lower().endswith((".xlsx", ".xls")):
        raise HTTPException(400, "Merci d'uploader un fichier Excel (.xlsx) au format Classeur1.")


@app.post("/validate")
async def validate(file: UploadFile = File(...)):
    """Vérifie le format du fichier et renvoie un petit récapitulatif."""
    _check_extension(file)
    df = parse_sinistres(await file.read())
    return {
        "ok": True,
        "lignes": int(len(df)),
        "codes_insee_distincts": int(df[COL_INSEE].nunique()),
        "colonnes": [COL_INSEE, COL_ID],
    }


@app.post("/generate")
async def generate(file: UploadFile = File(...)):
    _check_extension(file)
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
