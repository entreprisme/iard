# Bâtis de sociétaires impactés par les incendies

Analyse répondant à la demande :

> *« Je souhaiterais savoir combien et positionner géographiquement les bâtis
> (RP, RS, PNO) de nos sociétaires qui auraient effectivement été impactés par
> les incendies. »*

## Organisation

Le code est un package Python ; le notebook n'est qu'un **lanceur**. Il appelle
les fonctions dans l'ordre en affichant les diagnostics, mais ne contient aucune
logique. Reprendre le traitement, c'est donc ouvrir un module — pas un notebook
de 2 000 lignes.

```
incendie/
  carte_incendie_societaires.ipynb   # notebook de lancement, à exécuter de haut en bas
  analyse/                           # le traitement
    config.py       les paramètres — le seul fichier à ouvrir en usage courant
    donnees.py      emprises des feux, requêtes SQL, extractions
    traitement.py   diagnostics, segmentation, géocodage, appariement spatial
    resultats.py    compteurs, tableaux, export de gestion
    carte.py        carte interactive
    rapport.py      livrable HTML
    __init__.py     `analyser()` : tout l'enchaînement d'un bloc
  assets/                            # Leaflet + jQuery embarqués (HTML sans CDN)
data_incendie/
  FEU GIRONDE/                       # contour du feu + bâtis de l'emprise
  FEU BISCAROSSE/
  FEU VAR/                           # contour seul — pas de couche bâti livrée
livrables/                           # produit par le traitement — NON versionné
  carte_incendie_societaires.html    # le livrable one shot
  contrats_impactes.csv              # export pour la gestion
```

Chaque module lit `config` **au moment de l'appel**, jamais à l'import. Une
valeur réaffectée depuis le notebook est donc prise en compte, sans avoir à
relancer le noyau. C'est aussi pour cela que les valeurs dérivées (feux retenus,
libellés, niveaux d'impact) sont des **fonctions** — `cfg.feux_actifs()`,
`cfg.niveaux_impactes()` — et non des constantes figées à l'import.

## Exécution

```bash
pip install -r ../requirements.txt jupyter
# facultatif, pour interroger directement l'entrepôt :
pip install google-cloud-bigquery db-dtypes
jupyter lab carte_incendie_societaires.ipynb
```

Les deux réglages courants sont dans la première cellule du notebook :

```python
cfg.FEUX_A_TRAITER = ("Gironde", "Biscarrosse")   # ("Var",) → Pontevès seul
cfg.INTEGRER_PERIMETRE = False                     # cf. plus bas
```

Tout le reste se règle dans `analyse/config.py`.

En automatisé — cron, relance, test — le même traitement tient en trois lignes :

```python
from analyse import config as cfg, analyser
cfg.FEUX_A_TRAITER = ("Var",)
cfg.INTEGRER_PERIMETRE = True
resultat = analyser(silencieux=True)      # dict des objets intermédiaires
```

`analyser()` renvoie contours, bâtis, contrats, sinistres, appariement,
compteurs, export, carte et chemin du livrable : on peut inspecter une étape
sans relancer, ou en tester une isolément.

## Source des données

Le traitement cherche les contrats dans cet ordre :

1. **BigQuery** — la requête est construite par `donnees.requete_contrats()`
   (jointure `contrat_mgar_gps_iris` × `contrat_mgar`, pré-filtrée sur l'emprise
   des feux traités, voir plus bas) ;
2. **export local** — déposer le résultat de cette requête dans
   `data_incendie/export_societaires.csv`.

À défaut, le traitement **s'arrête** avec un message indiquant les deux sources
tentées. Il n'existe pas de repli sur des données de test : un livrable
d'apparence normale construit sur autre chose que les données réelles serait plus
dangereux qu'une erreur.

Même logique pour les sinistres, avec `data_incendie/export_sinistres.csv`. Si la
table est inaccessible, `CROISER_SINISTRES = False` produit le livrable sans ce
croisement — donc sans son seul contrôle externe.

### La zone interrogée : un rectangle par feu

Le pré-filtre géographique de la requête est **un rectangle par feu**, élargi de
`MARGE_REQUETE_M` (2 km), et non un rectangle englobant tous les feux.

La marge doit rester nettement au-dessus du plus grand seuil d'appariement : un
contrat à 30 m du bord extérieur du contour doit entrer dans l'extraction pour
pouvoir être classé.

Un rectangle englobant serait sans effet sur le comptage — l'appariement reste
géométrique, un contrat lointain ressort « hors périmètre » — mais les feux
traités peuvent être aux deux bouts du pays :

| Feux traités | Rectangle englobant | Un rectangle par feu | Surface brûlée |
|---|---:|---:|---:|
| Gironde + Biscarrosse | 2 720 km² | **1 377 km²** | 404 km² |
| Gironde + Biscarrosse + Var | 101 486 km² | **1 656 km²** | 443 km² |

Le rectangle couvrant les trois feux va de l'Atlantique aux Alpes, soit 229 fois
la surface réellement brûlée. Il ramènerait des dizaines de milliers de contrats
sans rapport avec les feux : de quoi noyer les diagnostics de doublons — le
« cas le plus chargé » se trouvait à Salon-de-Provence, à 60 km du feu le plus
proche — et faire scanner à BigQuery un volume sans commune mesure avec la
question posée.

Les rectangles apparaissent sur la carte sous « Limite de la zone analysée », un
par feu.

### Un contrat = (id_societaire, numero_intercalaire)

Un même bien porte plusieurs `id` de contrat, les dépendances recevant leur
propre numéro. La clé métier est donc le couple **`id_societaire` +
`numero_intercalaire`**, et le numéro de contrat n'apparaît nulle part dans les
analyses. Le SQL retient, pour chaque couple, le contrat de **dernière
`date_effet`** (`tech_date_fin_historisation IS NULL`, non résilié), et c'est
**son** adresse qui sert à rejoindre la table de géocodage.

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
qualifie pas le degré de destruction, donc le traitement ne parle jamais de bâti
« détruit ».

Les trois premiers niveaux constituent la réponse à « effectivement impactés ».
Un tableau de sensibilité (0 à 100 m) objective ce choix.

Les seuils se règlent par `SEUIL_CERTAIN_M`, `SEUIL_TRES_PROBABLE_M` et
`SEUIL_PROBABLE_M`. Les libellés en sont dérivés, y compris dans la légende de la
carte et le rapport : changer un seuil ne laisse pas de texte périmé derrière lui.

**Il n'y a pas de distance au contour du feu.** Une trace de brûlé n'est pas un
gradient : elle contient des îlots intacts en plein cœur et des bâtiments touchés
sur le bord. La distance au contour ne porterait donc aucune information sur la
probabilité d'impact.

### `INTEGRER_PERIMETRE`

Compte comme impactés les contrats situés dans le périmètre mais à l'écart de
tout bâti relevé, sous un niveau distinct qui dit exactement ce qu'on en sait.

À activer quand le périmètre est une trace de brûlé précise — le contour du Var
est une vectorisation satellite, y être veut alors dire quelque chose. À laisser
désactivé quand le contour est une enveloppe large : celui de Gironde couvre
37 000 ha en grande majorité forestiers, et tout y compter noierait les impacts
réels dans l'exposition.

C'est aussi la seule façon de traiter un feu dont la couche de bâtiments n'a pas
été livrée — cas du Var.

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

La table de géocodage n'est pas à la maille contrat : elle porte une dizaine de
lignes par contrat, très majoritairement identiques. Quand un contrat garde
plusieurs positions concurrentes, on retient **le niveau de géocodage le plus
précis** (`RANG_NIVEAU_GEOCODAGE`, `housenumber` en tête), puis, à niveau égal,
**la première ligne venue**. Les deux critères sont neutres par construction : ils
ne regardent pas où sont les bâtis brûlés, donc ils ne peuvent pas fabriquer
d'impact.

Le second critère n'arbitre rien, et c'est assumé — le niveau n'est pas une clé
d'unicité. Un cas réel : un contrat de Salon-de-Provence porte **quatre positions
`housenumber` pour la même adresse, réparties sur 1 900 m**, dont l'une à 55 m
d'une position étiquetée `street`. Aucune information disponible ici ne permet de
les départager ; prendre la première est un choix par défaut, pas une
localisation.

C'est pourquoi le choix est tracé : `ecart_positions_m` mesure l'étendue des
positions **du niveau retenu** — les seules réellement en concurrence — et
`position_incertaine` marque celles qui se jouent au-delà de
`SEUIL_ECART_POSITIONS_M`. Les deux colonnes sont dans l'export CSV, et les
lignes écartées sont comptées dans les diagnostics.

## Croisement avec les sinistres déclarés

`situation_sinistre_mgar`, joint sur `(id_societaire, numero_intercalaire)` :
dernier `numero_mouvement`, `code_descriptif_sinistre = '05'` (incendie),
`date_enregistrement` postérieure au départ du premier feu traité, dossier
ouvert. C'est le **seul contrôle externe** de la méthode : une déclaration
d'incendie sur un contrat que la géométrie classe « certain » confirme les deux.
La matrice de validation croise les deux lectures.

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

Sur la carte, la **couleur** porte le segment, la **forme** le statut — disque plein
pour un propriétaire, anneau pour un locataire —, le **triangle** signale un sinistre
incendie déclaré et la **taille** le degré de certitude. Une seule dimension colorée,
conformément aux règles de lisibilité en vision des couleurs déficiente.

## Ajouter un nouveau feu

Déposer le dossier dans `data_incendie/`, ajouter une entrée au dictionnaire
`FEUX` de `analyse/config.py` (dossier, motifs de fichiers, date de départ, date
de relevé), puis citer son nom dans `FEUX_A_TRAITER`. Le reste suit
automatiquement : chargement, appariement, compteurs, carte et HTML. Un nom absent
du catalogue lève une erreur explicite avec la liste des choix possibles.

Le nom du dossier et les motifs de fichiers sont **insensibles à la casse** :
`*Bati*.shp` trouve aussi bien `BATI_concerné.shp` que `bati.shp`, et `FEU VAR`
trouve `feu var`. Les livraisons ne sont pas normalisées, et sous Linux — où
tourne l'automatisation — une recherche sensible à la casse ferait passer le feu
pour dépourvu de couche bâti sans rien signaler. Dossier ou motif réellement
introuvable : l'erreur liste ce qui est effectivement présent.

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
- **Le Var n'a pas de couche bâti.** L'archive livrée ne contient que le contour ;
  le nombre de bâtiments dans l'emprise n'existe que sur l'image jointe. Ce feu ne
  peut donc être traité qu'avec `INTEGRER_PERIMETRE = True`, ce que le chargement
  rappelle par une erreur explicite le cas échéant.

## Dépendance réseau

Leaflet et jQuery sont embarqués depuis `assets/` et injectés en dur dans le HTML :
le livrable ne dépend d'aucun CDN (l'incident « page blanche » rencontré sur les
cartes de grêle ne peut pas se reproduire). Seules les **tuiles du fond de carte**
nécessitent un accès Internet — mettre `FOND_DE_CARTE = None` pour s'en passer,
les périmètres, bâtis et points restent affichés.
