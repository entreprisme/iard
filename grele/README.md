# Cartes de grêle + plateformes de débosselage

Notebook `cartes_grele_pfdsp.ipynb` — reprise de `Grelev3_2`, avec deux ajouts :
le calque des **plateformes de débosselage sans peinture** colorisé par réseau, et
le **disque de couverture de 25 km** autour de chaque implantation.

## Exécution

```bash
pip install -r ../requirements.txt jupyter
jupyter lab cartes_grele_pfdsp.ipynb
```

Puis exécuter de haut en bas. **Seule la première cellule est à adapter** —
chemins des fichiers et deux ou trois paramètres d'affichage.

Les chemins relatifs sont résolus depuis le dossier courant *puis ses parents* :
le notebook tourne aussi bien à plat, tout dans un même dossier, que depuis ce
sous-dossier du dépôt dont les référentiels sont à la racine.

## Sources

| Fichier | Contenu |
|---|---|
| `Classeur1.xlsx` | déclarations de grêle — `C_I_SOCS` (code INSEE) et `ANC_REF` |
| `PFDSP.xlsx` | plateformes — `RESEAU`, `CP`, `COMMUNE`, `ADRESSE`, `longitude`, `latitude` |
| `data/correspondance-code-insee-code-postal.geojson` | géométries communales |
| `data/departement.geojson` | contours départementaux |

Les deux premiers portent des données clients : ils sont **exclus du dépôt** par
`.gitignore`, comme le dossier `livrables/`.

## Livrables

| Fichier | Contenu |
|---|---|
| `livrables/grele_1_points.html` | points proportionnels au nombre de sinistres |
| `livrables/grele_2_polygones.html` | polygones communaux colorés |
| `livrables/pfdsp_controle.csv` | plateformes après contrôle, colonne `remarque` |

## Le calque des plateformes

Quatre groupes activables séparément dans le sélecteur de couches : les points et
les disques, pour chaque réseau. Les disques se masquent d'un clic pour lire la
carte des sinistres qu'ils recouvrent.

**Couleurs** — `FD` bleu `#2a78d6`, `PDR` aqua `#1baf7a`. Volontairement froides :
l'échelle des sinistres va du jaune au rouge, un réseau orange s'y confondrait. Le
couple est validé pour la vision des couleurs déficiente (écart CVD ΔE 23,1, le
seuil est 8). Un réseau supplémentaire doit recevoir sa couleur dans
`COULEUR_RESEAU` — le notebook s'arrête sinon plutôt que de le peindre au hasard.

**Disques** — remplis à 10 % et cernés d'un trait net. Un remplissage plus dense
masquerait les sinistres, qui sont l'objet de la carte.

## Le plafond de l'échelle

`PLAFOND_ECHELLE = 120`, repris du notebook d'origine. La distribution est très
déséquilibrée : la moitié des communes comptent 1 sinistre, Marseille en compte
2 860. Une échelle calée sur le maximum écraserait tout le reste dans la teinte la
plus pâle.

La légende affiche « 120 et + » : au-delà, les communes prennent toutes la couleur
haute. Le notebook liste celles qui saturent et la part de sinistres qu'elles
représentent. `PLAFOND_ECHELLE = None` revient au maximum réel.

## La taille des points

`RAYON_POINT_PX = (2, 9)` — le rayon suit la racine carrée du nombre de sinistres
puis bute sur le maximum, atteint dès 20 sinistres (93 communes sur 2 866).

Il est volontairement bas, et **découplé du plafond de couleur**. La quantité est
déjà portée par la couleur ; un gros disque coûte cher en lisibilité, il recouvre
ses voisins et masque les disques de couverture, qui sont l'objet de la carte. Non
plafonnée, Marseille ferait 107 pixels de rayon et recouvrirait un quart du pays.

L'aire du disque, pas son rayon, doit être proportionnelle à la quantité : d'où la
racine carrée. Un rayon proportionnel ferait paraître quatre fois pire une commune
deux fois plus touchée.

## Contrôles

Le notebook s'arrête ou signale plutôt que de produire une carte muette :

- **codes INSEE non reconnus** — ces sinistres n'apparaissent sur aucune carte ;
  leur nombre est affiché, nul sur le jeu du 1/04 au 1/09 ;
- **position des plateformes** — la distance entre le point fourni et la commune
  de son code postal est mesurée. Au-delà de `ECART_ALERTE_KM`, deux cas se
  distinguent sur le code postal rendu par le géocodeur : s'il a changé de
  département, c'est **le point** qui est faux et il est ramené sur la commune
  déclarée (marqué `position_approchee`) ; sinon c'est **le code postal déclaré**
  qui est douteux et la position est conservée.

Sur le fichier fourni, deux anomalies :

| Plateforme | Anomalie | Traitement |
|---|---|---|
| Riom (63200) | le géocodeur a ignoré le code postal et apparié l'adresse à Limoges — 139 km | point ramené sur Riom |
| Val-de-Reuil (27310) | le code postal déclaré désigne une autre commune (le bon est 27100) | position conservée |

Sans la première correction, un disque de couverture de 25 km aurait été centré
sur la Haute-Vienne.

**Noms de commune** — le nom déclaré fait foi. Celui du géocodeur ne sert qu'à lui
rendre ses accents (« CompiÃ¨gne » → « Compiègne ») et à réparer une coquille
(« Carcassone » → « Carcassonne »), et seulement s'il désigne bien la même
commune : il rend « Nantes » pour une adresse de Labatut. Le résoudre par la
géométrie serait pire — les adresses de zone d'activité tombent souvent de l'autre
côté d'une limite communale, et Aubagne deviendrait « La Penne-sur-Huveaune ».

## Couverture, et le curseur de rayon

Les deux cartes portent, en haut à droite, un **curseur de rayon** de 5 à 100 km,
au kilomètre près (`CURSEUR_RAYON_KM`). Le déplacer redimensionne tous les disques
et recalcule aussitôt la part de sinistres couverts — au total et par réseau. Tout
se passe dans la page : rien à relancer, et le fichier reste ouvrable seul.

Le calcul ne refait aucune géométrie. Pour chaque commune on connaît sa distance
à la plateforme la plus proche **de chaque réseau** ; la part couverte à un rayon
R se lit alors sur une comparaison « distance ≤ R », 2 866 fois — instantané. Ce
sont ces distances qui sont embarquées, pas les 26 positions à recroiser en direct.

La commune est réputée couverte si **son centroïde** est à moins du rayon —
approximation assumée : une grande commune peut être partiellement couverte et
compter pour zéro, ou l'inverse.

Le test porte sur la distance, jamais sur l'appartenance au disque dessiné : un
disque tracé est un polygone à 64 côtés, il tombe un peu en deçà du cercle et
écarterait quelques communes pourtant dans le rayon. Les distances sont arrondies
au mètre **avant** toute comparaison, dans le notebook comme dans la page — sans
quoi les communes posées juste sur le seuil feraient diverger les deux chiffres.
Vérifié : les deux donnent le même compte à 7, 10, 13, 18, 23, 25, 37, 50, 64, 75,
99 et 100 km.

Sur le jeu du 1/04 au 1/09 :

| Rayon | Sinistres couverts | Part |
|---:|---:|---:|
| 10 km | 8 501 | 57,6 % |
| **25 km** | **10 863** | **73,6 %** |
| 50 km | 12 212 | 82,8 % |
| 75 km | 13 084 | 88,7 % |
| 100 km | 13 800 | 93,5 % |

À 25 km, FD couvre 56,5 % et PDR 50,9 % — le total dépasse le cumul, les deux
réseaux se recouvrant.

## Dépendance réseau

Leaflet et jQuery sont embarqués depuis `assets/` et injectés en dur dans le HTML.
Le livrable ne dépend d'aucun CDN : c'est ce qui évite l'incident « page blanche »
déjà rencontré sur ces cartes, quand le proxy bloque `cdn.jsdelivr.net`.

jQuery est injecté **avant** Leaflet : folium construit chaque popup avec `$(...)`,
et une `ReferenceError` sur `$` interromprait tout le script — marqueurs et
sélecteur de couches compris.

Seules les **tuiles du fond de carte** demandent encore un accès Internet. Sans
lui, la carte s'affiche sur fond blanc : départements, communes, points et disques
restent là.

`DOSSIER_ASSETS = None` revient aux CDN.

## Rapport avec la webapp

`backend/app.py` fait le même travail pour les deux premières cartes, en service
web. Il ne porte pas le calque des plateformes : le notebook est la version de
référence pour cette analyse.
