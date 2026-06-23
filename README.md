# Cartes de grêle — webapp

Petite webapp permettant à un client d'**uploader un fichier Excel au format
« Classeur1 »** et de **télécharger les cartes de grêle** générées
automatiquement (logique reprise du notebook `Grelev3`).

## Fonctionnement

1. L'utilisateur dépose un fichier `.xlsx` contenant les colonnes
   `C_I_SOCS` (code INSEE commune) et `ANC_REF` (référence sinistre).
2. L'app géolocalise chaque sinistre par code INSEE, compte les sinistres par
   commune et regroupe les arrondissements de Paris / Marseille / Lyon.
3. Elle renvoie une archive ZIP `cartes_grele.zip` contenant les deux cartes
   HTML interactives : `grele_1_points.html` (points proportionnels) et
   `grele_2_polygones.html` (polygones communaux colorés).

## Référentiels géographiques (`data/`)

- `departement.geojson` — contours des départements (fond de carte) ;
- `correspondance-code-insee-code-postal.geojson` — géométries des communes
  (INSEE → polygone). Colonnes attendues : `insee_com`, `postal_code`,
  `nom_comm`, `geometry`.

Chemins surchargeables via `DATA_DIR`, `COMMUNES_GEOJSON`, `DEPARTEMENTS_GEOJSON`.

## Lancer en local

```bash
pip install -r requirements.txt
python main.py
# puis http://localhost:8080
```

## Lancer avec Docker

```bash
docker build --build-arg BASE_IMAGE=python:3.11-slim --build-arg HTTP_PROXY="" -t cartes-grele .
docker run -p 8080:8080 cartes-grele
```

## Structure

```
backend/app.py   # tout-en-un : logique métier + API FastAPI + page d'upload
data/            # référentiels geojson
main.py          # point d'entrée uvicorn
Dockerfile
```
