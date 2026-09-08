"""Génère grele/cartes_grele_pfdsp.ipynb — le notebook de production des cartes."""
import json
from pathlib import Path

C = []


def md(src):
    C.append({"cell_type": "markdown", "id": f"md{len(C):02d}", "metadata": {},
              "source": src.strip("\n").splitlines(keepends=True)})


def code(src):
    C.append({"cell_type": "code", "id": f"cd{len(C):02d}", "execution_count": None,
              "metadata": {}, "outputs": [],
              "source": src.strip("\n").splitlines(keepends=True)})


# --------------------------------------------------------------------------- #
md(r"""
# Cartes de grêle + plateformes de débosselage

Reprise du notebook `Grele_1`, avec deux ajouts : le calque des **plateformes de
débosselage sans peinture**, colorisé par réseau, et le **disque de couverture de
25 km** tracé autour de chaque implantation.

## Sources

| Fichier | Contenu |
|---|---|
| `Classeur1.xlsx` | les déclarations de grêle — colonnes `C_I_SOCS` (code INSEE) et `ANC_REF` (référence sinistre) |
| `PFDSP.xlsx` | les implantations de plateformes — `RESEAU`, `CP`, `COMMUNE`, `ADRESSE`, `longitude`, `latitude` |
| `correspondance-code-insee-code-postal.geojson` | géométries communales |
| `departement.geojson` | contours départementaux (fond de carte) |

## Livrables

| Fichier | Contenu |
|---|---|
| `grele_1_points.html` | points proportionnels au nombre de sinistres |
| `grele_2_polygones.html` | polygones communaux colorés |
| `pfdsp_controle.csv` | les plateformes après contrôle, avec les anomalies relevées |

Les deux cartes portent les mêmes calques de plateformes, activables séparément.

Exécuter les cellules de haut en bas. Seule la première est à adapter.
""")

# --------------------------------------------------------------------------- #
md(r"""
## 1. Réglages

Les chemins et les deux paramètres d'affichage. Le reste du notebook n'a pas à
être modifié.
""")

code(r'''
from pathlib import Path

# ═══ CHEMINS ══════════════════════════════════════════════════════════════ #
# Adapter si les fichiers ne sont pas à côté du notebook.
FICHIER_SINISTRES = Path("Classeur1.xlsx")
FICHIER_PFDSP     = Path("PFDSP.xlsx")
FEUILLE_PFDSP     = "PFDSP.geocoded"        # None = première feuille du classeur

DOSSIER_DATA  = Path("data")
FICHIER_COMMUNES     = DOSSIER_DATA / "correspondance-code-insee-code-postal.geojson"
FICHIER_DEPARTEMENTS = DOSSIER_DATA / "departement.geojson"

DOSSIER_SORTIE = Path("livrables")

# Leaflet et jQuery embarqués, pour que la carte s'ouvre sans accès aux CDN.
# Mettre None pour revenir aux CDN (page blanche si le proxy les bloque).
DOSSIER_ASSETS = Path("assets")

# ═══ AFFICHAGE ════════════════════════════════════════════════════════════ #
RAYON_COUVERTURE_KM = 25.0

# Plafond de l'échelle de couleur. La distribution est très déséquilibrée — la
# moitié des communes ont 1 sinistre, Marseille en a 2 860 — et une échelle calée
# sur le maximum écrase tout le reste dans la teinte la plus pâle. Au-delà du
# plafond, la commune prend la couleur haute.
#
# 30, soit le 98e centile, est le réglage qui fait le mieux ressortir la structure
# géographique : à 120 (la valeur du notebook d'origine) la carte est un aplat
# orange où le rouge n'apparaît presque pas. La contrepartie est assumée — la
# couleur ne distingue plus les communes les plus touchées entre elles, mais
# celles-là se repèrent de toute façon, et la question à l'échelle du pays est
# « où a-t-il grêlé », pas « laquelle est la pire ».
#
# Mettre None pour caler l'échelle sur le maximum réel.
PLAFOND_ECHELLE = 30

# Taille des points de la carte 1, en pixels : (minimum, maximum). Le rayon suit
# la racine carrée du nombre de sinistres, puis bute sur le maximum.
#
# Il est volontairement bas. La quantité est déjà portée par la couleur, et un
# gros disque coûte cher en lisibilité : il recouvre ses voisins et masque les
# disques de couverture, qui sont l'objet de la carte. Le maximum est atteint
# dès 9 sinistres — au-delà, seule la couleur continue de distinguer.
RAYON_POINT_PX = (2, 6)

# Une couleur par réseau. Volontairement froides : l'échelle des sinistres va du
# jaune au rouge, un réseau orange s'y confondrait. Ce couple est validé pour la
# vision des couleurs déficiente (écart CVD ΔE 23,1 — le seuil est 8).
COULEUR_RESEAU = {"FD": "#2a78d6", "PDR": "#1baf7a"}

# Le disque doit laisser lire la carte des sinistres qu'il recouvre : rempli
# très clair, cerné d'un trait net qui porte la lecture.
OPACITE_DISQUE = 0.10

# Bornes du curseur de rayon présent sur les cartes. Le rayon initial est
# RAYON_COUVERTURE_KM ; l'indicateur de couverture se recalcule à chaque
# déplacement, dans le navigateur, sans rien relancer.
CURSEUR_RAYON_KM = (5, 100, 1)      # (minimum, maximum, pas), en km

# Distance au-delà de laquelle une plateforme ne peut pas être dans la commune
# de son code postal — déclenche le contrôle de géocodage (§4).
ECART_ALERTE_KM = 5.0

CRS_METRIQUE = 2154        # Lambert 93 : les distances se calculent ici
CRS_AFFICHAGE = 4326       # WGS84 : la carte s'affiche là

DOSSIER_SORTIE.mkdir(parents=True, exist_ok=True)
print("Sortie :", DOSSIER_SORTIE.resolve())
''')

# --------------------------------------------------------------------------- #
code(r'''
import difflib
import json
import math
import re
import unicodedata

import branca.colormap as cm
import folium
import geopandas as gpd
import pandas as pd
from folium.features import GeoJsonTooltip
from shapely.geometry import Point


def code5(valeur):
    """Code INSEE ou postal sur 5 caractères — Excel rend « 7200 » ou « 7200.0 »."""
    if pd.isna(valeur):
        return None
    valeur = str(valeur).strip()
    if valeur.endswith(".0"):
        valeur = valeur[:-2]
    return valeur.zfill(5)


def cle(nom):
    """Nom de commune réduit à sa forme comparable : sans accent ni séparateur."""
    if not isinstance(nom, str):
        return ""
    sans_accent = "".join(c for c in unicodedata.normalize("NFD", nom)
                          if unicodedata.category(c) != "Mn")
    return " ".join(sans_accent.upper().replace("-", " ").replace("'", " ").split())


def demojibake(valeur):
    """Rétablit un texte UTF-8 relu en cp1252 : « CompiÃ¨gne » → « Compiègne »."""
    if not isinstance(valeur, str):
        return valeur
    for codec in ("cp1252", "latin-1"):
        try:
            repare = valeur.encode(codec).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if "�" not in repare:
            return repare
    return valeur


def verifier(chemin):
    """Résout un chemin relatif depuis le dossier courant, puis ses parents.

    Le notebook tourne ainsi aussi bien à plat — tout dans un même dossier — que
    depuis un sous-dossier d'un dépôt dont les référentiels sont à la racine,
    sans avoir à retoucher la cellule Réglages.
    """
    chemin = Path(chemin)
    if chemin.is_absolute():
        if chemin.exists():
            return chemin
        essais = [chemin]
    else:
        depart = Path.cwd()
        essais = [depart / chemin] + [p / chemin for p in depart.parents]
        for essai in essais:
            if essai.exists():
                return essai
    raise FileNotFoundError(
        f"« {chemin} » introuvable.\n"
        f"  Répertoire courant : {Path.cwd()}\n"
        f"  Il contient        : {sorted(p.name for p in Path.cwd().iterdir())}\n"
        f"  Cherché dans       : {[str(e.parent) for e in essais[:4]]}\n"
        "  Corriger le chemin dans la cellule Réglages.")


FICHIER_SINISTRES    = verifier(FICHIER_SINISTRES)
FICHIER_PFDSP        = verifier(FICHIER_PFDSP)
FICHIER_COMMUNES     = verifier(FICHIER_COMMUNES)
FICHIER_DEPARTEMENTS = verifier(FICHIER_DEPARTEMENTS)
for nom, f in [("sinistres", FICHIER_SINISTRES), ("plateformes", FICHIER_PFDSP),
               ("communes", FICHIER_COMMUNES), ("départements", FICHIER_DEPARTEMENTS)]:
    print(f"{nom:<13} {f}")
''')

# --------------------------------------------------------------------------- #
md(r"""
## 2. Référentiels géographiques

Les arrondissements de Paris, Marseille et Lyon sont fusionnés en une commune
unique : les sinistres y sont déclarés sur le code INSEE de la ville, pas sur
celui de l'arrondissement.
""")

code(r'''
brut = gpd.read_file(FICHIER_COMMUNES)
communes = brut.rename(columns={"insee_com": "code_insee",
                                "postal_code": "code_postal",
                                "nom_comm": "nom_com"})
manquantes = {"code_insee", "code_postal", "nom_com", "geometry"} - set(communes.columns)
if manquantes:
    raise KeyError(f"Colonnes absentes du geojson communes : {sorted(manquantes)}")

communes = communes[["code_insee", "code_postal", "nom_com", "geometry"]].copy()
communes["code_insee"] = communes["code_insee"].map(code5)
# Une commune peut porter plusieurs codes postaux, séparés par « / ».
communes["code_postal"] = communes["code_postal"].astype(str).str.split("/")
communes = communes.explode("code_postal")
communes["code_postal"] = communes["code_postal"].map(code5)
communes = communes.drop_duplicates(subset=["code_insee", "code_postal", "nom_com"])

fusions = []
for prefixe, nom, insee, cp in [("MARSEILLE", "MARSEILLE", "13055", "13000"),
                                ("LYON", "LYON", "69123", "69000"),
                                ("PARIS", "PARIS", "75056", "75000")]:
    arr = communes[communes.nom_com.str.startswith(prefixe, na=False)
                   & communes.nom_com.str.endswith("ARRONDISSEMENT", na=False)]
    if len(arr):
        ligne = arr.iloc[[0]].copy()
        ligne[["code_insee", "code_postal", "nom_com"]] = insee, cp, nom
        ligne["geometry"] = [arr.geometry.union_all()]
        fusions.append(ligne)
        print(f"{nom} : {len(arr)} arrondissements fusionnés → INSEE {insee}")

communes = gpd.GeoDataFrame(pd.concat([communes, *fusions], ignore_index=True),
                            geometry="geometry", crs=brut.crs or "EPSG:4326")
departements = gpd.read_file(FICHIER_DEPARTEMENTS)

print(f"\n{len(communes)} lignes commune × code postal, "
      f"{communes.code_insee.nunique()} communes distinctes")
print(f"{len(departements)} départements")
''')

# --------------------------------------------------------------------------- #
md(r"""
## 3. Déclarations de grêle

Un sinistre par ligne. On compte par commune, puis on rattache la géométrie.

Le nombre de codes INSEE non reconnus est affiché : s'il n'est pas nul, ces
sinistres **n'apparaissent sur aucune carte**, et il faut savoir combien avant de
commenter les cartes.
""")

code(r'''
sinistres = pd.read_excel(verifier(FICHIER_SINISTRES), dtype=str)
manquantes = {"C_I_SOCS", "ANC_REF"} - set(sinistres.columns)
if manquantes:
    raise KeyError(f"Colonnes absentes de {FICHIER_SINISTRES} : {sorted(manquantes)}. "
                   "Le format attendu est C_I_SOCS et ANC_REF.")
sinistres["C_I_SOCS"] = sinistres["C_I_SOCS"].map(code5)

geometries = communes.drop_duplicates(subset=["code_insee"])[
    ["code_insee", "nom_com", "geometry"]]

par_commune = (sinistres.merge(geometries, how="left",
                               left_on="C_I_SOCS", right_on="code_insee")
                        .dropna(subset=["geometry"])
                        .groupby(["code_insee", "nom_com"], as_index=False)["ANC_REF"]
                        .count())
grele = gpd.GeoDataFrame(
    par_commune.merge(geometries[["code_insee", "geometry"]], on="code_insee"),
    geometry="geometry", crs=f"EPSG:{CRS_AFFICHAGE}")

places = int(grele.ANC_REF.sum())
inconnus = sorted(set(sinistres.C_I_SOCS.dropna()) - set(grele.code_insee))
print(f"{len(sinistres):,} déclarations — {sinistres.C_I_SOCS.nunique():,} codes INSEE"
      .replace(",", " "))
print(f"{len(grele):,} communes géolocalisées, {places:,} sinistres placés"
      .replace(",", " "))
if inconnus:
    perdus = int((~sinistres.C_I_SOCS.isin(grele.code_insee)).sum())
    print(f"\n⚠️  {len(inconnus)} code(s) INSEE non reconnu(s) — {perdus} sinistre(s) "
          f"absent(s) des cartes : {inconnus[:15]}")
else:
    print("Aucun code INSEE perdu : la totalité des déclarations est cartographiée.")

# Les centroïdes se calculent en Lambert 93 : pris sur des degrés, ils sont
# faussés — d'autant plus que l'on monte vers le nord du pays.
centroides_l93 = grele.to_crs(CRS_METRIQUE).geometry.centroid
centroides = centroides_l93.to_crs(CRS_AFFICHAGE)

display(grele.drop(columns="geometry").nlargest(10, "ANC_REF")
             .rename(columns={"ANC_REF": "nb_sinistres"}))
''')

# --------------------------------------------------------------------------- #
md(r"""
## 4. Plateformes de débosselage

Le classeur est déjà géocodé en amont. Deux contrôles avant de s'en servir, parce
qu'un disque de 25 km centré au mauvais endroit se lit exactement comme un bon.

**Position** — on mesure la distance entre le point fourni et la commune de son
code postal. Au-delà de `ECART_ALERTE_KM`, deux cas se distinguent sur le code
postal rendu par le géocodeur :

- il a **changé de département** → c'est le point qui est faux, il est ramené sur
  la commune déclarée et marqué `position_approchee` ;
- il reste dans le département → c'est le **code postal déclaré** qui est
  douteux, la position est conservée telle quelle.

**Nom** — le nom déclaré fait foi. Celui du géocodeur ne sert qu'à lui rendre ses
accents et à réparer une coquille, et seulement s'il désigne bien la même commune :
il rend « Nantes » pour une adresse de Labatut.
""")

code(r'''
pfdsp_brut = pd.read_excel(verifier(FICHIER_PFDSP), sheet_name=FEUILLE_PFDSP)
attendues = {"RESEAU", "CP", "COMMUNE", "ADRESSE", "longitude", "latitude"}
manquantes = attendues - set(pfdsp_brut.columns)
if manquantes:
    raise KeyError(f"Colonnes absentes de {FICHIER_PFDSP} : {sorted(manquantes)}")

for col in ("COMMUNE", "ADRESSE", "result_city"):
    if col in pfdsp_brut:
        pfdsp_brut[col] = pfdsp_brut[col].map(demojibake)
for col in ("CP", "result_postcode"):
    if col in pfdsp_brut:
        pfdsp_brut[col] = pfdsp_brut[col].map(code5)
for col in ("longitude", "latitude"):
    pfdsp_brut[col] = pd.to_numeric(pfdsp_brut[col], errors="coerce")

sans_position = pfdsp_brut[["longitude", "latitude"]].isna().any(axis=1)
if sans_position.any():
    print(f"⚠️  {sans_position.sum()} plateforme(s) sans coordonnées, écartée(s) :")
    display(pfdsp_brut.loc[sans_position, ["RESEAU", "CP", "COMMUNE", "ADRESSE"]])
    pfdsp_brut = pfdsp_brut[~sans_position]

communes_l = communes.to_crs(CRS_METRIQUE)
lignes = []
for r in pfdsp_brut.itertuples():
    point = gpd.GeoSeries([Point(r.longitude, r.latitude)],
                          crs=CRS_AFFICHAGE).to_crs(CRS_METRIQUE).iloc[0]
    candidates = communes_l[communes_l.code_postal == r.CP]
    ecart = (candidates.geometry.distance(point).min() / 1000
             if len(candidates) else float("nan"))
    hors_cp = len(candidates) > 0 and ecart > ECART_ALERTE_KM
    postal_geo = getattr(r, "result_postcode", None)
    point_suspect = (hors_cp and isinstance(postal_geo, str)
                     and postal_geo[:2] != r.CP[:2])

    lon, lat, approchee, remarque = r.longitude, r.latitude, 0, ""
    if point_suspect:
        # Le point est faux : c'est le nom déclaré qui désigne la commune, parmi
        # celles du code postal — 63200 couvre Riom et Saint-Bonnet-Près-Riom.
        noms = {cle(n): i for i, n in zip(candidates.index, candidates.nom_com)}
        proche = difflib.get_close_matches(cle(r.COMMUNE), list(noms), 1, 0.5)
        commune = candidates.loc[noms[proche[0]]] if proche else candidates.iloc[0]
        repli = gpd.GeoSeries([commune.geometry.representative_point()],
                              crs=CRS_METRIQUE).to_crs(CRS_AFFICHAGE).iloc[0]
        lon, lat, approchee = round(repli.x, 6), round(repli.y, 6), 1
        remarque = (f"géocodage erroné ({getattr(r, 'result_city', '?')}, "
                    f"à {ecart:.0f} km) → ramené sur {commune.nom_com.title()}")
    elif hors_cp:
        remarque = (f"CP déclaré {r.CP} incohérent avec la position "
                    f"(le géocodeur rend {postal_geo}) — point conservé")

    nom = str(r.COMMUNE).strip().title()
    ville_geo = getattr(r, "result_city", None)
    if isinstance(ville_geo, str) and difflib.SequenceMatcher(
            None, cle(r.COMMUNE), cle(ville_geo)).ratio() >= 0.85:
        nom = ville_geo

    lignes.append({"reseau": r.RESEAU, "cp": r.CP, "commune": nom,
                   "adresse": str(r.ADRESSE).strip(),
                   "longitude": lon, "latitude": lat,
                   "position_approchee": approchee, "remarque": remarque})

pfdsp = pd.DataFrame(lignes).sort_values(["reseau", "cp"]).reset_index(drop=True)
pfdsp.to_csv(DOSSIER_SORTIE / "pfdsp_controle.csv", index=False, encoding="utf-8")

inconnus_reseau = set(pfdsp.reseau) - set(COULEUR_RESEAU)
if inconnus_reseau:
    raise KeyError(f"Réseau(x) sans couleur : {sorted(inconnus_reseau)} — "
                   "compléter COULEUR_RESEAU dans la cellule Réglages.")

RESEAUX = sorted(pfdsp.reseau.unique())
print(f"{len(pfdsp)} plateformes — "
      + ", ".join(f"{k} : {v}" for k, v in pfdsp.reseau.value_counts().items()))
signalees = pfdsp[pfdsp.remarque != ""]
if len(signalees):
    print(f"\n{len(signalees)} anomalie(s) de géocodage :")
    for r in signalees.itertuples():
        print(f"  ⚠️  [{r.reseau}] {r.commune} ({r.cp}) — {r.remarque}")
else:
    print("Aucune anomalie de géocodage.")
display(pfdsp)
''')

# --------------------------------------------------------------------------- #
md(r"""
## 5. Couverture à 25 km

Combien de déclarations tombent dans le rayon d'au moins une plateforme. Le
calcul se fait en Lambert 93 — en degrés, un rayon de 25 km n'aurait pas la même
longueur au nord et au sud du pays.

La commune est réputée couverte si **son centroïde** est à moins du rayon d'une
plateforme. C'est une approximation : une grande commune peut être partiellement
couverte et compter pour zéro, ou l'inverse. Le total des deux réseaux dépasse le
cumul, leurs couvertures se recouvrant.

Le test porte sur la **distance**, pas sur l'appartenance à un disque dessiné.
Un disque tracé est un polygone à 64 côtés : il tombe légèrement en deçà du cercle
et écarte quelques communes qui sont pourtant dans le rayon. La distance donne le
compte exact, et c'est elle que le curseur des cartes réutilise — une seule
mesure, donc un seul chiffre.
""")

code(r'''
pfdsp_l = gpd.GeoDataFrame(
    pfdsp, geometry=gpd.points_from_xy(pfdsp.longitude, pfdsp.latitude),
    crs=CRS_AFFICHAGE).to_crs(CRS_METRIQUE)

# Distance de chaque commune à la plateforme la plus proche, par réseau.
# 2 866 communes × 26 plateformes : la force brute suffit largement, et elle
# évite d'introduire une dépendance pour un calcul instantané.
xc, yc = centroides_l93.x.to_numpy(), centroides_l93.y.to_numpy()
distance_min = pd.DataFrame(index=grele.index)
for reseau in RESEAUX:
    lot = pfdsp_l[pfdsp_l.reseau == reseau]
    dx = xc[:, None] - lot.geometry.x.to_numpy()[None, :]
    dy = yc[:, None] - lot.geometry.y.to_numpy()[None, :]
    distance_min[reseau] = (dx ** 2 + dy ** 2).min(axis=1) ** 0.5 / 1000

# Arrondi au mètre, une fois pour toutes : c'est cette valeur-là qui sert aux
# comparaisons ici ET qui part dans la page. Arrondir après coup, ou plus
# grossièrement d'un côté que de l'autre, ferait diverger le chiffre du notebook
# et celui du curseur sur les communes posées juste sur le seuil.
distance_min = distance_min.round(3)
grele["distance_ptf_km"] = distance_min.min(axis=1)
grele["couvert"] = grele.distance_ptf_km <= RAYON_COUVERTURE_KM

total = int(grele.ANC_REF.sum())
couverts = int(grele.loc[grele.couvert, "ANC_REF"].sum())
print(f"{couverts:,} / {total:,} sinistres à moins de {RAYON_COUVERTURE_KM:.0f} km "
      f"d'une plateforme — {couverts / total:.1%}".replace(",", " "))
print(f"{int(grele.couvert.sum()):,} / {len(grele):,} communes couvertes"
      .replace(",", " "))

for reseau in RESEAUX:
    n = int(grele.loc[distance_min[reseau] <= RAYON_COUVERTURE_KM, "ANC_REF"].sum())
    print(f"   dont {reseau:<4} {n:>6,} ({n / total:.1%})".replace(",", " "))

# Ce que donnerait un autre rayon — le curseur des cartes parcourt cette courbe.
paliers = [r for r in (10, 25, 50, 75, 100) if r != RAYON_COUVERTURE_KM]
apercu = pd.DataFrame(
    [{"rayon_km": r,
      "sinistres_couverts": int(grele.loc[grele.distance_ptf_km <= r, "ANC_REF"].sum()),
      "part": f"{grele.loc[grele.distance_ptf_km <= r, 'ANC_REF'].sum() / total:.1%}"}
     for r in sorted(paliers + [RAYON_COUVERTURE_KM])])
display(apercu)
''')

# --------------------------------------------------------------------------- #
md(r"""
## 6. Couleurs et légende

L'échelle des sinistres est celle du notebook d'origine — `YlOrRd`, du jaune au
rouge. La légende est reconstruite en HTML/CSS plutôt que par `branca` : celle de
branca charge d3.js depuis un CDN, et une page ouverte sans accès Internet reste
blanche.
""")

code(r'''
reel_max = int(grele.ANC_REF.max())
plafond = int(PLAFOND_ECHELLE or reel_max) or 1
echelle = (cm.LinearColormap(colors=cm.linear.YlOrRd_05.scale().to_step(14).colors[5:])
             .scale(0, plafond).to_step(20))

satures = grele[grele.ANC_REF > plafond]
print(f"Échelle : 0 → {plafond} sinistres (maximum réel : {reel_max}, "
      f"{grele.loc[grele.ANC_REF.idxmax(), 'nom_com']})")
if len(satures):
    print(f"{len(satures)} commune(s) au-dessus du plafond, "
          f"{int(satures.ANC_REF.sum()):,} sinistres "
          f"({satures.ANC_REF.sum() / grele.ANC_REF.sum():.1%}) — elles prennent "
          "toutes la couleur haute. Les 10 premières :".replace(",", " "))
    display(satures.drop(columns="geometry").nlargest(10, "ANC_REF")
                   .rename(columns={"ANC_REF": "nb_sinistres"}))


def legende_html(echelle, vmax, reseaux, plafonnee=False, n=24):
    """Légende unique : l'échelle des sinistres, puis les réseaux."""
    degrade = ", ".join(
        f"{echelle.rgb_hex_str(vmax * i / n)} {100 * i / n:.0f}%" for i in range(n + 1))
    lignes = "".join(
        f'<div style="display:flex;align-items:center;gap:7px;margin-top:5px;">'
        f'<span style="width:13px;height:13px;border-radius:50%;flex:none;'
        f'background:{COULEUR_RESEAU[r]};border:2px solid #fff;'
        f'box-shadow:0 0 0 1px rgba(0,0,0,.35);"></span>'
        f'<span>{r} — {n_pf} plateforme{"s" if n_pf > 1 else ""}</span></div>'
        for r, n_pf in sorted(reseaux.items()))
    return f"""
    <div style="position:fixed;bottom:24px;left:12px;z-index:9999;
      background:rgba(255,255,255,.93);padding:11px 13px;border-radius:8px;
      box-shadow:0 1px 6px rgba(0,0,0,.3);
      font:12px/1.35 system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;color:#1f2937;">
      <div style="font-weight:600;margin-bottom:6px;">Nombre de sinistres grêle</div>
      <div style="display:flex;align-items:stretch;gap:6px;height:110px;">
        <div style="width:14px;border-radius:3px;
          background:linear-gradient(to top,{degrade});"></div>
        <div style="display:flex;flex-direction:column;justify-content:space-between;">
          <span>{vmax:g}{' et +' if plafonnee else ''}</span><span>{vmax / 2:g}</span><span>0</span>
        </div>
      </div>
      <div style="margin-top:9px;padding-top:8px;border-top:1px solid #e5e7eb;
        font-weight:600;">Plateformes de débosselage</div>
      {lignes}
      <div style="margin-top:6px;color:#6b7280;">
        Disque : zone de couverture,<br>rayon réglable en haut à droite</div>
    </div>"""


LEGENDE = legende_html(echelle, plafond, pfdsp.reseau.value_counts().to_dict(),
                       plafonnee=len(satures) > 0)
''')

# --------------------------------------------------------------------------- #
md(r"""
## 7. Le calque des plateformes

Quatre groupes activables séparément : les points et les disques, pour chaque
réseau. Les disques peuvent être masqués d'un clic pour lire la carte des
sinistres qu'ils recouvrent.

Le point porte un liseré blanc — sans lui, il se confondrait avec son propre
disque et avec ses voisins.
""")

code(r'''
def ajouter_plateformes(carte, pfdsp, rayon_km, opacite):
    """Ajoute, par réseau, un groupe de disques et un groupe de points.

    Renvoie {réseau: [noms JS des disques]} — c'est ce que le curseur pilote.
    """
    noms_js = {}
    for reseau in sorted(pfdsp.reseau.unique()):
        lot = pfdsp[pfdsp.reseau == reseau]
        couleur = COULEUR_RESEAU[reseau]

        # Pas de distance dans le nom du calque : le curseur la fait varier.
        disques = folium.FeatureGroup(name=f"Couverture — {reseau}", show=True)
        points = folium.FeatureGroup(
            name=f"Plateformes — {reseau} ({len(lot)})", show=True)

        noms_js[reseau] = []
        for r in lot.itertuples():
            approx = ("<br><i>position approchée : "
                      f"{r.remarque}</i>" if r.position_approchee else "")
            fiche = (f"<b>{r.commune}</b> ({r.cp})<br>{r.adresse}"
                     f"<br>Réseau : <b>{r.reseau}</b>{approx}")

            # Le rayon n'est pas dans l'infobulle : le curseur le fait varier,
            # un texte figé y mentirait dès le premier déplacement.
            disque = folium.Circle(
                location=[r.latitude, r.longitude], radius=rayon_km * 1000,
                color=couleur, weight=1.5, opacity=0.75,
                fill=True, fill_color=couleur, fill_opacity=opacite,
                tooltip=f"{r.commune} — {reseau} : zone de couverture",
            )
            disque.add_to(disques)
            noms_js[reseau].append(disque.get_name())

            folium.CircleMarker(
                location=[r.latitude, r.longitude], radius=6,
                color="#ffffff", weight=2, opacity=1,
                fill=True, fill_color=couleur, fill_opacity=1,
                tooltip=f"{r.commune} — {reseau}",
                popup=folium.Popup(fiche, max_width=280),
            ).add_to(points)

        disques.add_to(carte)
        points.add_to(carte)
    return noms_js


def fond_de_carte(centroides, departements):
    carte = folium.Map(location=[centroides.y.mean(), centroides.x.mean()],
                       zoom_start=6, control_scale=True)
    folium.GeoJson(
        departements, name="Départements",
        style_function=lambda _: {"color": "black", "weight": 0.75, "fillOpacity": 0},
    ).add_to(carte)
    return carte


def ajouter_curseur(carte, noms_js, distance_min, poids, rayon_km, bornes):
    """Curseur de rayon et indicateur de couverture, recalculés dans la page.

    Le calcul ne refait aucune géométrie : pour chaque commune on connaît déjà
    sa distance à la plateforme la plus proche de chaque réseau. La part
    couverte à un rayon R se lit alors sur une comparaison « distance ≤ R »,
    2 866 fois — instantané à chaque déplacement du curseur.

    C'est aussi ce qui garde le fichier raisonnable : on embarque une distance
    par commune et par réseau, pas les 26 positions à recroiser en direct.
    """
    reseaux = list(noms_js)
    lignes = [[int(n)] + [round(float(d), 3) for d in ligne]
              for n, ligne in zip(poids, distance_min[reseaux].to_numpy())]
    mini, maxi, pas = bornes

    barres = "".join(
        f'<div style="display:flex;align-items:center;gap:6px;margin-top:3px;">'
        f'<span style="width:13px;height:13px;border-radius:50%;flex:none;'
        f'background:{COULEUR_RESEAU[r]};border:2px solid #fff;'
        f'box-shadow:0 0 0 1px rgba(0,0,0,.35);"></span>'
        f'<span style="flex:none;width:34px;">{r}</span>'
        f'<b id="pct_{r}" style="margin-left:auto;">–</b></div>'
        for r in reseaux)

    bloc = f"""
<div style="position:fixed;top:12px;right:12px;z-index:9999;width:246px;
  background:rgba(255,255,255,.95);padding:12px 14px;border-radius:8px;
  box-shadow:0 1px 6px rgba(0,0,0,.3);
  font:12px/1.4 system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;color:#1f2937;">
  <div style="font-weight:600;">Rayon de couverture</div>
  <input type="range" id="curseur_rayon" min="{mini}" max="{maxi}" step="{pas}"
    value="{rayon_km:g}" style="width:100%;margin:8px 0 2px;">
  <div style="display:flex;justify-content:space-between;color:#6b7280;">
    <span>{mini} km</span><b id="valeur_rayon" style="color:#1f2937;font-size:14px;">
    {rayon_km:g} km</b><span>{maxi} km</span></div>
  <div style="margin-top:10px;padding-top:9px;border-top:1px solid #e5e7eb;">
    <div style="display:flex;align-items:baseline;justify-content:space-between;">
      <span style="font-weight:600;">Sinistres couverts</span>
      <b id="pct_total" style="font-size:20px;">–</b></div>
    <div id="abs_total" style="color:#6b7280;margin-top:1px;">&nbsp;</div>
    {barres}
  </div>
</div>
<script>
document.addEventListener("DOMContentLoaded", function () {{
  var RESEAUX = {json.dumps(reseaux)};
  var DISQUES = {{{", ".join(f'"{r}": [{", ".join(noms_js[r])}]' for r in reseaux)}}};
  var LIGNES  = {json.dumps(lignes)};
  var TOTAL   = LIGNES.reduce(function (s, l) {{ return s + l[0]; }}, 0);

  var curseur = document.getElementById("curseur_rayon");

  function formate(n) {{ return n.toLocaleString("fr-FR"); }}

  function rafraichir(km) {{
    var couverts = 0, parReseau = RESEAUX.map(function () {{ return 0; }});
    for (var i = 0; i < LIGNES.length; i++) {{
      var l = LIGNES[i], nb = l[0], dedans = false;
      for (var j = 0; j < RESEAUX.length; j++) {{
        if (l[j + 1] <= km) {{ parReseau[j] += nb; dedans = true; }}
      }}
      if (dedans) couverts += nb;
    }}
    document.getElementById("valeur_rayon").textContent = km + " km";
    document.getElementById("pct_total").textContent =
      (100 * couverts / TOTAL).toFixed(1).replace(".", ",") + " %";
    document.getElementById("abs_total").textContent =
      formate(couverts) + " sur " + formate(TOTAL) + " sinistres";
    RESEAUX.forEach(function (r, j) {{
      document.getElementById("pct_" + r).textContent =
        (100 * parReseau[j] / TOTAL).toFixed(1).replace(".", ",") + " %";
      DISQUES[r].forEach(function (c) {{ c.setRadius(km * 1000); }});
    }});
  }}

  curseur.addEventListener("input", function () {{ rafraichir(+this.value); }});
  rafraichir(+curseur.value);
}});
</script>"""
    carte.get_root().html.add_child(folium.Element(bloc))
    return carte


def enregistrer(carte, fichier):
    """Écrit la carte en HTML sans aucune dépendance à un CDN.

    folium référence Leaflet, jQuery, Bootstrap et awesome-markers par des
    <script src> distants. Sur un poste dont le proxy bloque ces CDN, la page
    reste blanche — c'est l'incident déjà rencontré sur les cartes de grêle. On
    retire donc toutes les ressources externes et on réinjecte Leaflet et
    jQuery, les seules réellement nécessaires.

    jQuery avant Leaflet : folium construit chaque popup avec `$(...)`, et une
    ReferenceError sur `$` interromprait tout le script — marqueurs et sélecteur
    de couches compris.

    Seules les tuiles du fond de carte restent en ligne. Sans Internet, la carte
    s'affiche sur fond blanc : départements, communes, points et disques sont là.
    """
    doc = carte.get_root().render()
    assets = Path(DOSSIER_ASSETS) if DOSSIER_ASSETS else None
    try:
        assets = verifier(assets) if assets else None
    except FileNotFoundError:
        assets = None

    if assets and (assets / "leaflet.js").exists():
        doc = re.sub(r'<script[^>]+src="https?://[^"]+"[^>]*>\s*</script>', "", doc)
        doc = re.sub(r'<link[^>]+href="https?://[^"]+"[^>]*/?>', "", doc)

        def lire(nom):
            return ((assets / nom).read_text(encoding="utf-8")
                    .replace("</script>", r"<\/script>"))

        injection = (f"<style>{lire('leaflet.css')}</style>\n"
                     f"<script>{lire('jquery.js')}</script>\n"
                     f"<script>{lire('leaflet.js')}</script>\n")
        doc = doc.replace("</head>", injection + "</head>", 1)
        autonome = True
    else:
        autonome = False

    fichier = Path(fichier)
    fichier.write_text(doc, encoding="utf-8")
    print(f"{fichier} — {fichier.stat().st_size / 1024:,.0f} Ko"
          .replace(",", " ")
          + ("  (Leaflet embarqué)" if autonome
             else "  ⚠️  Leaflet via CDN : page blanche si le proxy les bloque"))
    return fichier


print("Fonctions de carte définies.")
''')

# --------------------------------------------------------------------------- #
md(r"""
## 8. Carte 1 — points proportionnels

Le rayon du cercle suit la **racine carrée** du nombre de sinistres : c'est l'aire
du disque qui doit être proportionnelle à la quantité, pas son rayon, sinon une
commune deux fois plus touchée paraît quatre fois pire.
""")

code(r'''
rayon_min, rayon_max = RAYON_POINT_PX
sature_taille = int((2 * (grele.ANC_REF ** 0.5) > rayon_max).sum())
print(f"Points de {rayon_min} à {rayon_max} px — taille maximale atteinte dès "
      f"{(rayon_max / 2) ** 2:.0f} sinistres, soit {sature_taille} commune(s) "
      f"sur {len(grele)} ; au-delà, seule la couleur distingue.")

carte_points = fond_de_carte(centroides, departements)

groupe_sinistres = folium.FeatureGroup(name="Sinistres grêle (points)", show=True)
for ligne, centre in zip(grele.itertuples(), centroides):
    nb = int(ligne.ANC_REF)
    folium.CircleMarker(
        location=[centre.y, centre.x],
        radius=min(rayon_max, max(rayon_min, 2 * math.sqrt(nb))),
        color=echelle(nb), fill=False, fill_color=echelle(nb),
        popup=f"{ligne.nom_com}<br>INSEE : {ligne.code_insee}<br>Sinistres : {nb}",
        tooltip=f"{ligne.nom_com} — {nb} sinistre{'s' if nb > 1 else ''}",
    ).add_to(groupe_sinistres)
groupe_sinistres.add_to(carte_points)

disques_js = ajouter_plateformes(carte_points, pfdsp, RAYON_COUVERTURE_KM,
                                     OPACITE_DISQUE)
ajouter_curseur(carte_points, disques_js, distance_min, grele.ANC_REF,
                RAYON_COUVERTURE_KM, CURSEUR_RAYON_KM)
folium.LayerControl(position="bottomright", collapsed=False).add_to(carte_points)
carte_points.get_root().html.add_child(folium.Element(LEGENDE))

enregistrer(carte_points, DOSSIER_SORTIE / "grele_1_points.html")
carte_points
''')

# --------------------------------------------------------------------------- #
md(r"""
## 9. Carte 2 — polygones communaux

La même information portée par la surface de la commune plutôt que par un point.
Plus juste sur les grandes communes, moins lisible là où elles sont petites — les
deux cartes sont complémentaires, c'est pourquoi le notebook d'origine produisait
déjà les deux.
""")

code(r'''
carte_polygones = fond_de_carte(centroides, departements)

folium.GeoJson(
    grele[["code_insee", "nom_com", "ANC_REF", "geometry"]],
    name="Sinistres grêle par commune",
    style_function=lambda x: {
        "fillColor": echelle(x["properties"]["ANC_REF"]),
        "color": "black", "weight": 0.2, "fillOpacity": 0.5, "dashArray": "5, 5",
    },
    highlight_function=lambda _: {"weight": 0.5, "color": "black"},
    tooltip=GeoJsonTooltip(
        fields=["nom_com", "code_insee", "ANC_REF"],
        aliases=["Commune", "Code INSEE", "Nombre de sinistres"], localize=True),
).add_to(carte_polygones)

disques_js = ajouter_plateformes(carte_polygones, pfdsp, RAYON_COUVERTURE_KM,
                                     OPACITE_DISQUE)
ajouter_curseur(carte_polygones, disques_js, distance_min, grele.ANC_REF,
                RAYON_COUVERTURE_KM, CURSEUR_RAYON_KM)
folium.LayerControl(position="bottomright", collapsed=False).add_to(carte_polygones)
carte_polygones.get_root().html.add_child(folium.Element(LEGENDE))

enregistrer(carte_polygones, DOSSIER_SORTIE / "grele_2_polygones.html")
carte_polygones
''')

# --------------------------------------------------------------------------- #
md(r"""
---

## Ce qui est produit

Les trois fichiers sont dans `livrables/`. Les cartes sont autonomes — un simple
double-clic les ouvre — à ceci près que **les tuiles du fond de carte demandent un
accès Internet** ; sans lui, les départements, les communes, les points et les
disques restent affichés sur fond blanc.

`pfdsp_controle.csv` porte la colonne `remarque` : c'est là qu'on retrouve les
plateformes dont le géocodage a été corrigé, et pourquoi.
""")

# --------------------------------------------------------------------------- #
nb = {"cells": C,
      "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python",
                                  "name": "python3"},
                   "language_info": {"name": "python", "version": "3.11"}},
      "nbformat": 4, "nbformat_minor": 5}

sortie = Path("grele/cartes_grele_pfdsp.ipynb")
sortie.parent.mkdir(parents=True, exist_ok=True)
sortie.write_text(json.dumps(nb, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(f"écrit : {sortie.resolve()} — {len(C)} cellules")
