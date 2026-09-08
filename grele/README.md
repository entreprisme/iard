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

Le plafond porte sur **la couleur et le rayon**. Sans lui, Marseille fait un
disque de 107 pixels qui recouvre un quart du pays et masque les disques de
couverture. La légende affiche « 120 et + » : au-delà, les communes prennent
toutes la couleur et la taille hautes. Le notebook liste celles qui saturent et
la part de sinistres qu'elles représentent.

`PLAFOND_ECHELLE = None` revient au maximum réel.

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

## Couverture

Le notebook chiffre la part des déclarations situées à moins de 25 km d'une
plateforme. La commune est réputée couverte si **son centroïde** tombe dans un
disque — approximation assumée : une grande commune peut être partiellement
couverte et compter pour zéro, ou l'inverse.

Sur le jeu du 1/04 au 1/09 : **10 862 / 14 757 sinistres, soit 73,6 %**, dont FD
56,5 % et PDR 50,9 % — le total dépasse le cumul, les deux réseaux se recouvrant.

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
