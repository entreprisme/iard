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
  FEU GIRONDE/                       # contour du feu + bâtis de l'emprise
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
   `data_incendie/export_societaires.csv`.

À défaut, le notebook **s'arrête** avec un message indiquant les deux sources
tentées. Il n'existe pas de repli sur des données de test : un livrable
d'apparence normale construit sur autre chose que les données réelles serait plus
dangereux qu'une erreur.

Même logique pour les sinistres, avec `data_incendie/export_sinistres.csv`. Si la
table est inaccessible, `CROISER_SINISTRES = False` produit le livrable sans ce
croisement — donc sans son seul contrôle externe.

## Méthode

Le point GPS de chaque contrat est comparé à l'emprise des bâtiments relevés dans
la zone brûlée, en Lambert 93 :

| Niveau | Règle |
|---|---|
| Certain — emprise ou moins de 5 m | le point tombe dans l'emprise d'un bâti relevé, ou à moins de 5 m |
| Très probable — de 5 à 15 m | 5 à 15 m d'un bâti relevé |
| Probable — de 15 à 30 m | 15 à 30 m d'un bâti relevé |
| Exposé — dans le périmètre du feu | dans le contour, au-delà de 30 m de tout bâti relevé |
| Hors périmètre | reste |

Le vocabulaire est volontairement prudent : la couche source s'appelle « Bâti
**concerné** » et recense les bâtiments *situés dans l'emprise brûlée*. Elle ne
qualifie pas le degré de destruction, donc le notebook ne parle jamais de bâti
« détruit ».

Les trois premiers niveaux constituent la réponse à « effectivement impactés ».
Le notebook produit un tableau de sensibilité (0 à 100 m) pour objectiver ce choix.

Les seuils se règlent par `SEUIL_CERTAIN_M`, `SEUIL_TRES_PROBABLE_M` et
`SEUIL_PROBABLE_M`. Les libellés en sont dérivés, y compris dans la légende de la
carte et le rapport : changer un seuil ne laisse pas de texte périmé derrière lui.

### Le géocodage borne la conclusion

La colonne `level_contrat_mgar` de `contrat_mgar_gps_iris` donne le niveau de
géocodage, au sens de la Base Adresse Nationale. Une distance ne vaut que ce que
vaut la position dont elle part :

| `level_contrat_mgar` | Point posé sur | Traitement |
|---|---|---|
| `housenumber` | le point adresse | seuils appliqués tels quels |
| `street` | l'axe de la voie | plafonné à « très probable », jamais « certain » |
| `locality` | le centre d'un lieu-dit | **exclu du comptage** |
| `municipality` | le centroïde de la commune | **exclu du comptage** |

Exclure les deux derniers évite des faux positifs mécaniques : le centroïde d'une
commune sinistrée tombe forcément près des bâtis brûlés. Ces contrats ne sont pas
perdus, ils sortent sous « position trop imprécise pour conclure » et doivent être
instruits autrement. Réglages : `PLAFONNER_NIVEAU_VOIE` et
`NIVEAUX_GEOCODAGE_INEXPLOITABLES`.

## Les deux axes d'analyse

**Segment** — à quoi sert le logement. Lu sur **`code_sous_type`** : `1`–`5` → RP,
`6` → PNO, `7` → RS. Les autres modalités (jeune, étudiant, hébergé…) sont hors
demande mais comptées séparément.

**Statut d'occupation** — qui supporte le dommage au bâti. Lu sur
**`code_qualite_assure_habitation`**, regroupé en trois postes :

| Statut | Modalités source |
|---|---|
| Propriétaire | `P` propriétaire, `N` nu-propriétaire, `U` usufruitier |
| Locataire | `L` locataire, `I` colocation individuelle, `G` colocation commune |
| Autre / non renseigné | `H` hébergé gratuit, `C` logement de service, `R` maison de retraite, `M` établissement médical, `S` sans résidence fixe |

Les statuts qui ne relèvent ni du propriétaire ni du locataire restent à part plutôt
que d'être rattachés arbitrairement. Le détail des modalités reste disponible dans la
colonne `qualite` de l'export CSV.

Sur la carte, la **couleur** porte le segment et la **forme** le statut : disque plein
pour un propriétaire, anneau pour un locataire, contour gris pour les autres — une
seule dimension colorée, conformément aux règles de lisibilité en vision des couleurs
déficiente.

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
