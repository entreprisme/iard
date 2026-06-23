@echo off
REM ============================================================
REM test.bat - Test LOCAL de la webapp "Cartes de grele"
REM Build de l'image Docker puis lancement sur http://localhost:8080
REM ============================================================

REM ---- Version de l'image (a modifier ici) -------------------
set VERSION=dev-1.0.0
REM ------------------------------------------------------------

REM ---- Images (artifactory interne Matmut) -------------------
set IMAGE_LATEST=artifactory.intra.matmut.fr/docker/grele:latest
set IMAGE_TAG=artifactory.intra.matmut.fr/docker-matmut/data/data_science/dev/grele:%VERSION%
REM ------------------------------------------------------------

REM ---- Image de base Python (stage builder + runtime) --------
REM Defaut du Dockerfile = artifactory interne. En reseau ouvert (CI publique)
REM decommenter pour utiliser l'image publique :
REM set BASE_IMAGE=python:3.11-slim
REM ------------------------------------------------------------

git pull
docker stop grele 2>nul
docker rm grele 2>nul

REM Construit la liste des build-args (n'ajoute BASE_IMAGE que s'il est defini,
REM sinon la valeur par defaut du Dockerfile prime).
set BUILD_ARGS=--build-arg HTTP_PROXY=%HTTP_PROXY% --build-arg HTTPS_PROXY=%HTTPS_PROXY%
if defined BASE_IMAGE set BUILD_ARGS=%BUILD_ARGS% --build-arg BASE_IMAGE=%BASE_IMAGE%

docker build %BUILD_ARGS% -t %IMAGE_LATEST% .
if errorlevel 1 (
    echo ERREUR: echec du build.
    exit /b 1
)

docker tag %IMAGE_LATEST% %IMAGE_TAG%

REM Les referentiels geojson sont embarques dans l'image (COPY ./data),
REM aucun volume ni .env n'est necessaire pour un test local.
docker run -d --name grele -p 8080:8080 %IMAGE_LATEST%

REM L'application est servie sur http://localhost:8080
REM (page d'upload ; healthcheck sur /health)
docker logs -f grele
