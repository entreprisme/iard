"""
Webapp FastAPI : upload d'un fichier Excel « Classeur1 » et téléchargement des
cartes de grêle (points + polygones) sous forme d'archive ZIP.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse

from backend import grele

app = FastAPI(title="Cartes de grêle", version="1.0.0")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX_HTML.read_text(encoding="utf-8")


@app.post("/generate")
async def generate(file: UploadFile = File(...)):
    filename = (file.filename or "").lower()
    if not filename.endswith((".xlsx", ".xls")):
        raise HTTPException(
            status_code=400,
            detail="Merci d'uploader un fichier Excel (.xlsx) au format Classeur1.",
        )

    xlsx_bytes = await file.read()

    try:
        resultat = grele.build_maps(xlsx_bytes)
    except grele.ReferentielManquant as exc:
        # 503 : la configuration serveur est incomplète (référentiel absent).
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except grele.FichierSinistresInvalide as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Construction de l'archive ZIP en mémoire.
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("grele_1_points.html", resultat.carte_points_html)
        zf.writestr("grele_2_polygones.html", resultat.carte_polygones_html)
        zf.writestr("rapport.txt", _build_report(resultat))
    buffer.seek(0)

    headers = {"Content-Disposition": 'attachment; filename="cartes_grele.zip"'}
    return StreamingResponse(buffer, media_type="application/zip", headers=headers)


def _build_report(resultat: grele.ResultatCartes) -> str:
    lignes = [
        "Rapport de génération des cartes de grêle",
        "=========================================",
        f"Communes avec sinistres        : {resultat.nb_communes}",
        f"Sinistres localisés            : {resultat.nb_sinistres_localises}",
        f"Sinistres NON localisés        : {resultat.nb_sinistres_non_localises}",
        "",
        "Codes INSEE non localisés :",
    ]
    if resultat.codes_insee_non_localises:
        lignes.extend(f"  - {code}" for code in resultat.codes_insee_non_localises)
    else:
        lignes.append("  (aucun)")
    return "\n".join(lignes) + "\n"
