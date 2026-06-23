@echo off
REM ============================================================
REM build.bat - BUILD + PUSH de la webapp "Cartes de grele"
REM Build de l'image, tag, run local de controle puis push artifactory.
REM ============================================================

REM ---- Version de l'image (a modifier ici) -------------------
set VERSION=dev-1.0.0
REM ------------------------------------------------------------

set IMAGE_LATEST=artifactory.intra.matmut.fr/docker/grele:latest
set IMAGE_TAG=artifactory.intra.matmut.fr/docker-matmut/data/data_science/dev/grele:%VERSION%

REM ---- Image de base Python (defaut Dockerfile = artifactory interne) ----
REM En reseau ouvert, decommenter :
REM set BASE_IMAGE=python:3.11-slim
REM ------------------------------------------------------------

docker stop grele 2>nul
docker rm grele 2>nul

set BUILD_ARGS=--build-arg HTTP_PROXY=%HTTP_PROXY% --build-arg HTTPS_PROXY=%HTTPS_PROXY%
if defined BASE_IMAGE set BUILD_ARGS=%BUILD_ARGS% --build-arg BASE_IMAGE=%BASE_IMAGE%

docker build %BUILD_ARGS% -t %IMAGE_LATEST% .
if errorlevel 1 (
    echo ERREUR: echec du build.
    exit /b 1
)

docker tag %IMAGE_LATEST% %IMAGE_TAG%

REM Run local de controle (referentiels geojson embarques, aucun volume/.env).
docker run -d --name grele -p 8010:8010 %IMAGE_LATEST%

docker push %IMAGE_TAG%
if errorlevel 1 (
    echo ERREUR: echec du push.
    exit /b 1
)

echo.
echo Image %IMAGE_TAG% poussee.
