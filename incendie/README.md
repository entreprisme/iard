# Bâtis de sociétaires impactés par les incendies

Notebook d'analyse répondant à la demande :

> *« Je souhaiterais savoir combien et positionner géographiquement les bâtis
> (RP, RS, PNO) de nos sociétaires qui auraient effectivement été impactés par
> les incendies. »*

## Contenu

```
incendie/
  carte_incendie_societaires.ipynb   # le notebook (à exécuter de haut en bas)
  assets/                            # Leaflet + jQuery embarqués (HTML sans CDN)
data_incendie/
  FEU GIRONDE/                       # contour + bâtis brûlés (SIG)
  FEU BISCAROSSE/
livrables/                           # produit par le notebook — NON versionné
  carte_incendie_societaires.html    # le livrable one shot
  contrats_impactes.csv              # export pour la gestion
```

## Exécution

```bash
pip install -r ../requirements.txt jupyter
# facultatif, pour interroger directement l'entrepôt :
pip install google-cloud-bigquery db-dtypes
jupyter lab carte_incendie_societaires.ipynb
```

Le notebook cherche les contrats dans cet ordre :

1. **BigQuery** — la requête est dans le notebook (jointure `contrat_mgar_gps_iris`
   × `contrat_mgar`, pré-filtrée sur l'emprise des deux feux) ;
2. **export local** — déposer le résultat de cette requête dans
   `data_incendie/export_societaires.csv` ;
3. **simulation** — jeu de test synthétique, pour dérouler la chaîne sans données
   réelles. Le HTML produit affiche alors un bandeau d'avertissement.

Les données incendie sont toujours les données réelles, quel que soit le mode.

## Méthode

Le point GPS de chaque contrat est comparé à l'emprise des bâtiments effectivement
brûlés, en Lambert 93 :

| Niveau | Règle |
|---|---|
| Bâti détruit (certain) | le point tombe dans l'emprise d'un bâti brûlé |
| Impact très probable | ≤ 10 m d'un bâti brûlé |
| Impact probable | ≤ 25 m d'un bâti brûlé |
| Dans le périmètre du feu | dans le contour, > 25 m de tout bâti brûlé |
| Hors périmètre | reste |

Les trois premiers niveaux constituent la réponse à « effectivement impactés ».
Le notebook produit un tableau de sensibilité (0 à 100 m) pour objectiver ce choix.

La segmentation RP / RS / PNO se lit sur **`code_sous_type`** :
`1`–`5` → RP, `6` → PNO, `7` → RS. Les autres modalités (jeune, étudiant, hébergé…)
sont hors demande mais comptées séparément.

## Ajouter un nouveau feu

Déposer le dossier dans `data_incendie/` et ajouter une entrée au dictionnaire
`FEUX` du notebook (nom du dossier + motifs de fichiers). Le reste suit
automatiquement : chargement, appariement, compteurs, carte et HTML.

## Points d'attention sur les données source

- Le contour de Biscarrosse **n'a pas de `.prj`** : le CRS est forcé à EPSG:2154
  (vérifié par l'étendue des coordonnées et le recouvrement avec les bâtis).
- Le champ `cleabs` du fichier Gironde est **constant** sur les 1 607 lignes : il
  est ignoré, un identifiant de bâtiment est régénéré.
- Les attributs `Surface` / `sup 2607` du contour Gironde **ne concordent pas**
  avec l'aire géométrique ; toutes les surfaces sont recalculées.
- La couche « bâti concerné » recense les bâtiments **situés dans l'emprise
  brûlée** ; elle ne qualifie pas le degré de destruction. Emprise minimale 50 m²,
  donc les petites annexes sont absentes.

## Dépendance réseau

Leaflet et jQuery sont embarqués depuis `assets/` et injectés en dur dans le HTML :
le livrable ne dépend d'aucun CDN (l'incident « page blanche » rencontré sur les
cartes de grêle ne peut pas se reproduire). Seules les **tuiles du fond de carte**
nécessitent un accès Internet — mettre `FOND_DE_CARTE = None` pour s'en passer,
les périmètres, bâtis et points restent affichés.
