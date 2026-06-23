# Dossier `data/` — référentiels géographiques

- `departement.geojson` — versionné, contours des départements (fond de carte).
- `correspondance-code-insee-code-postal.geojson` — **à fournir ici**, non
  versionné car volumineux. Géométries des communes (colonnes attendues :
  `insee_com`, `postal_code`, `nom_comm`, `geometry`). Sans ce fichier, la
  route `/generate` renvoie une erreur 503 explicite.
