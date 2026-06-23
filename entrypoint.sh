#!/bin/sh
# =============================================================================
# entrypoint.sh - Webapp Cartes de grêle
# =============================================================================
set -e

echo "[entrypoint] Démarrage de la webapp Cartes de grêle"
echo "[entrypoint] HOST=${HOST:-0.0.0.0} PORT=${PORT:-8010}"
echo "[entrypoint] COMMUNES_GEOJSON=${COMMUNES_GEOJSON:-data/correspondance-code-insee-code-postal.geojson}"

if [ ! -f "${COMMUNES_GEOJSON:-data/correspondance-code-insee-code-postal.geojson}" ]; then
  echo "[entrypoint] ATTENTION : référentiel communes introuvable." >&2
  echo "[entrypoint] L'app démarre mais /generate renverra une erreur 503" >&2
  echo "[entrypoint] tant que le fichier geojson communes n'est pas fourni." >&2
fi

exec uvicorn backend.app:app \
  --host "${HOST:-0.0.0.0}" \
  --port "${PORT:-8010}" \
  --log-level "${LOG_LEVEL:-info}"
