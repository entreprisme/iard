# =============================================================================
# Dockerfile - Webapp Cartes de grêle
# Multi-stage build pour déploiement OpenShift / Docker
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1 : Builder - compilation des wheels Python
# ---------------------------------------------------------------------------
# Image de base paramétrable : défaut = artifactory interne Matmut ; la CI
# publique peut surcharger avec --build-arg BASE_IMAGE=python:3.11-slim.
ARG BASE_IMAGE=artifactory.intra.matmut.fr/docker/python:3.11-slim
FROM ${BASE_IMAGE} AS builder

ARG HTTP_PROXY_APT=""
ARG HTTP_PROXY=http://10.131.72.5:80

ENV HTTP_PROXY=$HTTP_PROXY
ENV HTTPS_PROXY=$HTTP_PROXY
ENV http_proxy=$HTTP_PROXY
ENV https_proxy=$HTTP_PROXY
ENV PYTHONHTTPSVERIFY=0
ENV NO_PROXY=localhost,127.0.0.1,artifactory.intra.matmut.fr,10.0.0.0/8,*intra.matmut.fr
ENV no_proxy=localhost,127.0.0.1,artifactory.intra.matmut.fr,10.0.0.0/8,*intra.matmut.fr

# Configuration pip trusted hosts (registre public via proxy)
RUN pip config set global.trusted-host \
  "pypi.org files.pythonhosted.org pypi.python.org" \
  --trusted-host=pypi.python.org \
  --trusted-host=pypi.org \
  --trusted-host=files.pythonhosted.org

COPY requirements.txt requirements.txt
RUN pip install --upgrade pip
RUN mkdir /wheels && pip wheel --wheel-dir=/wheels -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 2 : Runtime - image finale légère
# ---------------------------------------------------------------------------
FROM ${BASE_IMAGE}

ARG HTTP_PROXY=http://10.131.72.5:80
ENV HTTP_PROXY=$HTTP_PROXY
ENV HTTPS_PROXY=$HTTP_PROXY
ENV http_proxy=$HTTP_PROXY
ENV https_proxy=$HTTP_PROXY
ENV NO_PROXY=localhost,127.0.0.1,10.0.0.0/8

# Installation des wheels Python (aucun paquet système requis : geopandas,
# shapely et pyogrio embarquent leurs binaires GDAL/GEOS via les wheels).
COPY --from=builder /wheels /wheels
COPY requirements.txt /requirements.txt
RUN pip install --no-index --find-links=/wheels -r /requirements.txt \
    && rm -rf /wheels /requirements.txt

# Création de l'utilisateur non-root
RUN useradd -m defuser \
    && mkdir -p /home/defuser/app \
    && chown -R defuser:0 /home/defuser \
    && chmod 775 /home/defuser /home/defuser/app

WORKDIR /home/defuser/app

# Copie du code applicatif
COPY ./backend ./backend
COPY ./data ./data
COPY ./main.py ./main.py
COPY ./entrypoint.sh ./entrypoint.sh

# sed supprime les fins de ligne Windows (CRLF) éventuelles
RUN sed -i 's/\r$//' ./entrypoint.sh && chmod +x ./entrypoint.sh

# OpenShift exécute les conteneurs avec un UID arbitraire du groupe root (0).
RUN chown -R defuser:0 /home/defuser/app \
    && chmod -R g+rwX /home/defuser/app

USER defuser

# Variables d'environnement applicatives
ENV HOST=0.0.0.0
ENV PORT=8010
ENV LOG_LEVEL=info
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/home/defuser/app
ENV DATA_DIR=data
ENV COMMUNES_GEOJSON=data/correspondance-code-insee-code-postal.geojson
ENV DEPARTEMENTS_GEOJSON=data/departement.geojson

EXPOSE 8010

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8010/health')" || exit 1

ENTRYPOINT ["./entrypoint.sh"]
