# Cartes de grêle — webapp

Petite webapp permettant à un client d'**uploader un fichier Excel au format
« Classeur1 »** et de **télécharger les cartes de grêle** générées
automatiquement (logique reprise du notebook `Grelev3`).

## Fonctionnement

1. L'utilisateur dépose un fichier `.xlsx` contenant les colonnes
   `C_I_SOCS` (code INSEE commune) et `ANC_REF` (référence sinistre).
2. L'app géolocalise chaque sinistre par code INSEE, compte les sinistres par
   commune, regroupe les arrondissements de Paris / Marseille / Lyon.
3. Elle renvoie une archive ZIP `cartes_grele.zip` contenant :
   - `grele_1_points.html` — carte à points proportionnels ;
   - `grele_2_polygones.html` — carte des polygones communaux colorés ;
   - `rapport.txt` — rapport qualité (sinistres localisés / non localisés).

## Référentiels géographiques requis (dossier `data/`)

| Fichier | Versionné ? | Rôle |
|---|---|---|
| `departement.geojson` | ✅ oui | Contours des départements (fond de carte) |
| `correspondance-code-insee-code-postal.geojson` | ❌ **non** (volumineux) | Géométries des communes (INSEE → polygone) |

> ⚠️ Le fichier **`correspondance-code-insee-code-postal.geojson`** n'est pas
> versionné (trop volumineux). Vous devez le **placer dans `data/`** avant de
> lancer l'app, sinon la génération renverra une erreur 503 explicite.
> Source : référentiel communes data.gouv.fr (colonnes attendues `insee_com`,
> `postal_code`, `nom_comm`, `geometry`).

Les chemins sont surchargeables via les variables d'environnement
`DATA_DIR`, `COMMUNES_GEOJSON`, `DEPARTEMENTS_GEOJSON`.

## Lancer en local

```bash
pip install -r requirements.txt
# placez correspondance-code-insee-code-postal.geojson dans data/
python main.py
# puis ouvrez http://localhost:8010
```

## Lancer avec Docker

```bash
# Build (CI publique) :
docker build --build-arg BASE_IMAGE=python:3.11-slim --build-arg HTTP_PROXY="" -t cartes-grele .

# Le référentiel communes peut être monté en volume si non inclus dans l'image :
docker run -p 8010:8010 \
  -v $(pwd)/data:/home/defuser/app/data \
  cartes-grele
```

## Structure

```
backend/
  app.py     # API FastAPI (routes / , /generate , /health)
  grele.py   # logique métier (lecture xlsx, jointure INSEE, cartes Folium)
static/
  index.html # page d'upload
data/
  departement.geojson
  correspondance-code-insee-code-postal.geojson   # à fournir
main.py      # point d'entrée uvicorn
Dockerfile
```
