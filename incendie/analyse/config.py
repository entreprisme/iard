"""Paramètres de l'analyse.

C'est le seul module à ouvrir en usage courant. Tout le reste du package le lit
au moment de l'appel, pas à l'import : depuis un notebook, il suffit donc de
réaffecter un paramètre avant d'appeler les fonctions pour qu'il soit pris en
compte.

    from analyse import config as cfg
    cfg.FEUX_A_TRAITER = ("Var",)
    cfg.INTEGRER_PERIMETRE = True

Les valeurs dérivées (feux retenus, niveaux d'impact, libellés) sont exposées
sous forme de fonctions et non de constantes, précisément pour qu'elles suivent
ces réaffectations au lieu d'être figées à l'import.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

# --------------------------------------------------------------------------- #
# Arborescence
# --------------------------------------------------------------------------- #
# `data_incendie` est cherché à partir de deux ancres : le répertoire courant
# (cas normal, le notebook est lancé à côté des données) et l'emplacement du
# package lui-même (cas d'un lancement depuis un autre dossier). On remonte les
# parents de chacune. Le traitement tourne ainsi aussi bien depuis le dépôt —
# data_incendie/ à la racine, à côté de incendie/ — que depuis un poste où tout
# a été rassemblé dans un seul dossier.
_PKG = Path(__file__).resolve().parent          # …/incendie/analyse
_ANCRES = (Path.cwd(), _PKG.parent)             # …/incendie

RACINE = Path.cwd()
for _ancre in _ANCRES:
    _trouve = next((c for c in (_ancre, *_ancre.parents)
                    if (c / "data_incendie").is_dir()), None)
    if _trouve is not None:
        RACINE = _trouve
        break

DOSSIER_INCENDIE = RACINE / "data_incendie"
DOSSIER_SORTIE = RACINE / "livrables"
DOSSIER_ASSETS = _PKG.parent / "assets"

FICHIER_HTML = DOSSIER_SORTIE / "carte_incendie_societaires.html"
FICHIER_CSV = DOSSIER_SORTIE / "contrats_impactes.csv"
FICHIER_LOCAL_CONTRATS = DOSSIER_INCENDIE / "export_societaires.csv"
FICHIER_LOCAL_SINISTRES = DOSSIER_INCENDIE / "export_sinistres.csv"

# --------------------------------------------------------------------------- #
# Catalogue des feux
# --------------------------------------------------------------------------- #
# `crs_defaut` ne sert que si le shapefile n'embarque pas de .prj.
# `debut`  : date de départ du feu, qui borne la recherche de sinistres.
# `releve` : date du relevé de l'emprise, affichée dans l'en-tête du rapport.
FEUX = {
    "Gironde":     {"dossier": "FEU GIRONDE",    "contour": "*Contour*.shp",
                    "bati": "*Bati*.shp", "crs_defaut": 2154,
                    "debut": "2026-07-23", "releve": "26/07/2026 16 h"},
    "Biscarrosse": {"dossier": "FEU BISCAROSSE", "contour": "*Contour*.shp",
                    "bati": "*Bati*.shp", "crs_defaut": 2154,
                    "debut": "2026-07-24", "releve": "26/07/2026 16 h"},
    "Var":         {"dossier": "FEU VAR",        "contour": "*Contour*.shp",
                    "bati": "*Bati*.shp", "crs_defaut": 2154,
                    "debut": "2026-07-24", "releve": "28/07/2026"},
}

# ═══ LE SEUL RÉGLAGE À CHANGER POUR CHOISIR LES FEUX ═══════════════════════ #
#   ("Gironde", "Biscarrosse")  → les deux feux de juillet
#   ("Var",)                    → Pontevès seul   (la virgule est obligatoire)
#   None                        → tous les feux du catalogue
FEUX_A_TRAITER = ("Gironde", "Biscarrosse")
# ═════════════════════════════════════════════════════════════════════════ #


def feux_actifs() -> dict:
    """Les feux effectivement traités, dans l'ordre de FEUX_A_TRAITER."""
    if FEUX_A_TRAITER is None:
        retenus = dict(FEUX)
    else:
        inconnus = [n for n in FEUX_A_TRAITER if n not in FEUX]
        if inconnus:
            raise KeyError(f"FEUX_A_TRAITER : {inconnus} absent(s) du catalogue. "
                           f"Choix possibles : {list(FEUX)}")
        retenus = {n: FEUX[n] for n in FEUX_A_TRAITER}
    if not retenus:
        raise ValueError("FEUX_A_TRAITER est vide : aucun feu à traiter.")
    return retenus


def date_debut_feux() -> str:
    """Départ du premier feu traité — borne basse de la recherche de sinistres."""
    return min(f["debut"] for f in feux_actifs().values())


def libelle_feux() -> str:
    """« Gironde et Biscarrosse », « Gironde, Biscarrosse et Var »…"""
    noms = list(feux_actifs())
    if len(noms) < 3:
        return " et ".join(noms)
    return ", ".join(noms[:-1]) + f" et {noms[-1]}"


# --------------------------------------------------------------------------- #
# Géodésie
# --------------------------------------------------------------------------- #
CRS_METRIQUE = 2154        # Lambert 93 : toutes les distances sont calculées ici
CRS_AFFICHAGE = 4326       # WGS84 : projection de la carte

# Marge autour de chaque emprise pour le pré-filtre de la requête. Elle doit
# rester nettement au-dessus du plus grand seuil d'appariement : un contrat à
# 30 m du bord extérieur du contour doit entrer dans l'extraction pour pouvoir
# être classé. 2 km laissent aussi voir le voisinage immédiat sur la carte.
MARGE_REQUETE_M = 2_000

# --------------------------------------------------------------------------- #
# Seuils d'appariement (mètres)
# --------------------------------------------------------------------------- #
# Un point contrat tombe rarement pile dans l'emprise du bâtiment : le géocodage
# ramène souvent l'adresse au bord de la parcelle ou à l'axe de la voie.
SEUIL_CERTAIN_M = 5.0           # dans l'emprise, ou collé au bâti
SEUIL_TRES_PROBABLE_M = 15.0    # décalage de géocodage courant (bord de parcelle)
SEUIL_PROBABLE_M = 30.0         # tolérance haute du géocodage adresse
SEUILS_SENSIBILITE_M = [0.0, 5.0, 15.0, 30.0, 50.0, 100.0]

# Écart au-delà duquel plusieurs géocodages d'un même contrat ne désignent
# manifestement pas le même bâtiment : la position retenue devient un choix par
# défaut, à signaler plutôt qu'à présenter comme une localisation.
SEUIL_ECART_POSITIONS_M = 100.0

# Les libellés sont dérivés des seuils : changer un seuil sans reprendre les
# textes laisserait des valeurs fausses dans la légende, le rapport, les tableaux.
NIV_CERTAIN = f"Certain — emprise ou moins de {SEUIL_CERTAIN_M:.0f} m"
NIV_TRES_PROBABLE = (f"Très probable — de {SEUIL_CERTAIN_M:.0f} "
                     f"à {SEUIL_TRES_PROBABLE_M:.0f} m")
NIV_PROBABLE = (f"Probable — de {SEUIL_TRES_PROBABLE_M:.0f} "
                f"à {SEUIL_PROBABLE_M:.0f} m")
NIV_EXPOSE = "Exposé — dans le périmètre du feu"
NIV_HORS = "Hors périmètre"
NIVEAU_INEXPLOITABLE = "Position trop imprécise pour conclure"

# Compter comme impactés les contrats situés dans le périmètre du feu mais à
# l'écart de tout bâti relevé. Leur niveau reste distinct : il dit exactement ce
# qu'on sait d'eux, à savoir qu'ils sont dans l'emprise, sans plus de précision.
#
# À activer quand le périmètre est une trace de brûlé précise — le contour du Var
# est une vectorisation satellite, y être veut alors dire quelque chose. À
# laisser désactivé quand le contour est une enveloppe large : celui de Gironde
# couvre 37 000 ha en grande majorité forestiers, et tout y compter noierait les
# impacts réels dans l'exposition.
#
# C'est aussi la seule façon de traiter un feu dont la couche de bâtiments n'a
# pas été livrée.
INTEGRER_PERIMETRE = False


def niveaux_impactes() -> tuple:
    """Niveaux comptés comme « effectivement impactés »."""
    socle = (NIV_CERTAIN, NIV_TRES_PROBABLE, NIV_PROBABLE)
    return socle + (NIV_EXPOSE,) if INTEGRER_PERIMETRE else socle


def ordre_niveaux() -> list:
    """Tous les niveaux, du plus certain au plus lointain."""
    return [NIV_CERTAIN, NIV_TRES_PROBABLE, NIV_PROBABLE,
            NIV_EXPOSE, NIVEAU_INEXPLOITABLE, NIV_HORS]


# --------------------------------------------------------------------------- #
# Précision du géocodage
# --------------------------------------------------------------------------- #
# Si la table de géocodage expose une colonne qualifiant la précision du point,
# elle fait foi et remplace l'heuristique multi-voies. Elle est cherchée sous
# ces noms ; il suffit de l'ajouter au SELECT pour qu'elle soit exploitée.
CANDIDATS_COLONNE_PRECISION = (
    "level_contrat_mgar",          # nom réel dans contrat_mgar_gps_iris
    "type_geocodage", "result_type", "ban_result_type", "niveau_geocodage",
    "precision_geocodage", "qualite_geocodage", "code_precision_geocodage",
    "code_precision", "type_localisation", "niveau_localisation",
    "score_geocodage", "indice_confiance_geocodage",
)
# Modalités dénotant un point NON posé sur l'adresse. Compléter après lecture de
# REQ_GPS_MODALITES_PRECISION : les libellés maison ne sont pas ceux de la BAN.
MODALITES_CENTROIDE_COMMUNE = {
    "municipality", "commune", "centroide_commune", "centroide commune",
    "centroïde commune", "mairie", "city", "municipalite",
}
MODALITES_VOIE = {"street", "voie", "rue", "axe", "troncon", "tronçon"}
MODALITES_LIEU_DIT = {"locality", "lieu-dit", "lieu_dit", "hameau"}
MODALITES_ADRESSE = {"housenumber", "numero", "numéro", "adresse", "point_adresse",
                     "batiment", "bâtiment", "parcelle", "toit", "rooftop"}

# `municipality` place le point au centroïde de la commune, `locality` au centre
# d'un lieu-dit : à cette échelle, la distance à un bâtiment ne veut rien dire.
# Ces contrats sont sortis du comptage — les compter reviendrait à fabriquer des
# faux positifs par pur hasard géométrique — et suivis à part.
NIVEAUX_GEOCODAGE_INEXPLOITABLES = ("Centroïde commune", "Lieu-dit")

# `street` pose le point sur l'axe de la voie, pas sur le bâti : tomber dans une
# emprise y est une coïncidence géométrique, pas une preuve. On plafonne donc ces
# contrats à « très probable » plutôt que « certain ».
PLAFONNER_NIVEAU_VOIE = True

# Ordre de préférence quand un contrat porte plusieurs géocodages concurrents.
RANG_NIVEAU_GEOCODAGE = {"Adresse exacte": 0, "Voie": 1, "Lieu-dit": 2,
                         "Centroïde commune": 3, "Non renseigné": 4}

# Nombre de contrats à partir duquel une coordonnée partagée est examinée.
SEUIL_COORD_PARTAGEE = 5

# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #
PROJET_BQ = "matmut-dda-common-xpl-07c7"   # projet d'exécution / facturation

TABLE_CONTRATS = ("matmut-dni-datalake-prd-8ec7."
                  "silver_produitetcontrat_sigmainframe_prd.contrat_mgar")
TABLE_GPS = ("matmut-dda-irisation-prd-26f3."
             "gold_irisation_prd.contrat_mgar_gps_iris")
TABLE_SINISTRES = ("matmut-dni-datalake-prd-8ec7."
                   "silver_sinistreetprestation_sigmainframe_prd.situation_sinistre_mgar")

# True  : jointure sur 5 clés, adresse comprise — élimine les doublons dès le SQL,
#         mais écarte les contrats dont le libellé d'adresse diffère entre les
#         deux tables (mesuré : au moins 100 clés ont un point identique et un
#         libellé différent, et l'appariement perd 5,1 % des contrats).
# False : jointure sur 3 clés — recall maximal. Les contrats à positions
#         multiples sont dédoublonnés côté Python, sur le niveau de géocodage,
#         ce que le SQL ne sait pas faire.
JOINTURE_STRICTE_ADRESSE = False

# Colonnes facultatives. Seule `code_type_bien` est conservée : elle porte la
# distinction immeuble / maison / mobile home, qui sert à qualifier les
# coordonnées partagées. Surface, pièces et capital mobilier ont été retirés du
# reporting — sans usage dans l'analyse, et inutile de faire circuler des données
# de contrat au-delà du nécessaire.
COLONNES_FACULTATIVES = ("code_type_bien",)

# --------------------------------------------------------------------------- #
# Sinistres
# --------------------------------------------------------------------------- #
# Le croisement est le seul contrôle externe de la méthode. Le désactiver produit
# un livrable valide mais non validé — à n'utiliser que si la table est
# inaccessible.
CROISER_SINISTRES = True

# Code incendie de `code_descriptif_sinistre`, confirmé par le métier.
CODES_SINISTRE_INCENDIE = ("05",)

# Fenêtre sur la date d'ouverture du dossier. La date de survenance depuis le
# départ du feu est plus juste et ne dérive pas ; cette fenêtre glissante
# écarterait les déclarations tardives. Mettre un entier pour la réactiver.
FENETRE_SINISTRE_JOURS = None

# `est_clos = FALSE` répond à « sinistre ouvert ». Passer à False pour compter
# aussi les dossiers clos : ils restent une preuve d'impact.
SINISTRES_OUVERTS_UNIQUEMENT = True

# --------------------------------------------------------------------------- #
# Segmentation et libellés métier
# --------------------------------------------------------------------------- #
SEGMENTS_CIBLE = ("RP", "RS", "PNO")

# `code_sous_type` : regroupement fonctionnel documenté dans le dictionnaire.
MAP_SOUS_TYPE = {
    **{c: "RP" for c in "12345"},
    "6": "PNO",
    "7": "RS",
    **{c: "JEUN" for c in "89J"},
    **{c: "ETUD" for c in "ABCDPR"},
    **{c: "ETUE" for c in "EF"},
    "H": "HEB",
    "T": "TBNH",
}
LIB_SEGMENT = {
    "RP": "Résidence principale", "RS": "Résidence secondaire",
    "PNO": "Propriétaire non occupant", "JEUN": "Contrat jeune",
    "ETUD": "Étudiant", "ETUE": "Étudiant étranger",
    "HEB": "Hébergé", "TBNH": "Bien temporairement non habité",
    "INCONNU": "Sous-type absent ou non référencé",
}

# Le dictionnaire documente les modalités sous la forme {"IM": "'APPARTEMENT'"}
# sans préciser si la colonne stocke le code ou le libellé. Les deux sont donc
# acceptés : se tromper ferait basculer toute la population en « non renseigné ».
LIB_TYPE_BIEN = {
    "IM": "Immeuble",       "IMMEUBLE": "Immeuble", "APPARTEMENT": "Immeuble",
    "MP": "Maison particulière", "MAISON PART.": "Maison particulière",
    "MAISON PART": "Maison particulière", "MAISON PARTICULIERE": "Maison particulière",
    "MH": "Mobile home",    "MOBILE HOME": "Mobile home",
}

LIB_QUALITE = {
    "P": "Propriétaire", "L": "Locataire", "H": "Hébergé gratuit",
    "I": "Colocation individuelle", "R": "Chambre maison de retraite",
    "M": "Chambre établissement médical", "G": "Colocation commune",
    "N": "Nu-propriétaire", "C": "Logement de service",
    "U": "Usufruitier", "S": "Sans résidence fixe",
    # libellés, au cas où la colonne les stocke en clair
    "PROPRIETAIRE": "Propriétaire", "LOCATAIRE": "Locataire",
    "HEB GRATUIT": "Hébergé gratuit", "COL CT INDIV": "Colocation individuelle",
    "CH MAIS RET": "Chambre maison de retraite",
    "CH MEDICAL.": "Chambre établissement médical",
    "COL CT COM": "Colocation commune", "NU-PROPRIET.": "Nu-propriétaire",
    "LOGT SERVICE": "Logement de service", "USUFRUITIER": "Usufruitier",
    "SANS RESID": "Sans résidence fixe",
    "CH INST SPEC": "Chambre établissement spécialisé",
}

# Regroupement en trois postes selon « qui supporte le dommage au bâti ».
# Hébergé gratuit, logement de service et chambres en établissement ne relèvent
# ni de l'un ni de l'autre : les classer arbitrairement fausserait la lecture.
STATUT_OCCUPATION = {
    "P": "Propriétaire", "PROPRIETAIRE": "Propriétaire",
    "N": "Propriétaire", "NU-PROPRIET.": "Propriétaire", "NU-PROPRIET": "Propriétaire",
    "U": "Propriétaire", "USUFRUITIER": "Propriétaire",
    "L": "Locataire", "LOCATAIRE": "Locataire",
    "I": "Locataire", "COL CT INDIV": "Locataire",
    "G": "Locataire", "COL CT COM": "Locataire", "COLOC": "Locataire",
    "H": "Autre / non renseigné", "HEB GRATUIT": "Autre / non renseigné",
    "C": "Autre / non renseigné", "LOGT SERVICE": "Autre / non renseigné",
    "R": "Autre / non renseigné", "CH MAIS RET": "Autre / non renseigné",
    "M": "Autre / non renseigné", "CH MEDICAL.": "Autre / non renseigné",
    "CH MEDICAL": "Autre / non renseigné",
    "S": "Autre / non renseigné", "SANS RESID": "Autre / non renseigné",
    "CH INST SPEC": "Autre / non renseigné",
}
ORDRE_STATUTS = ["Propriétaire", "Locataire", "Autre / non renseigné"]

# --------------------------------------------------------------------------- #
# Carte et livrable
# --------------------------------------------------------------------------- #
FOND_DE_CARTE = "OpenStreetMap"   # None => aucun fond tuilé (poste sans Internet)

# Plafond d'affichage des couches de contexte : elles servent de repère de
# volume, pas d'outil de gestion. Au-delà, l'affichage est échantillonné et le
# fait est annoncé — les comptages portent toujours sur la totalité.
MAX_POINTS_CONTEXTE = 20_000

PALETTE_SEGMENT = {"RP": "#2a78d6", "RS": "#eb6834", "PNO": "#1baf7a",
                   "Autres": "#8a8983"}


def style_niveau() -> dict:
    """Taille et opacité du marqueur par niveau de certitude."""
    return {
        NIV_CERTAIN:          dict(radius=7.5, fill_opacity=0.95, weight=2.0),
        NIV_TRES_PROBABLE:    dict(radius=6.0, fill_opacity=0.75, weight=1.5),
        NIV_PROBABLE:         dict(radius=5.0, fill_opacity=0.50, weight=1.2),
        NIV_EXPOSE:           dict(radius=3.5, fill_opacity=0.25, weight=0.8),
        NIVEAU_INEXPLOITABLE: dict(radius=4.0, fill_opacity=0.30, weight=1.0),
    }


def leaflet_embarque() -> bool:
    """Leaflet et jQuery présents dans incendie/assets ? Le livrable ne dépend
    alors d'aucun CDN — seules les tuiles du fond de carte demandent le réseau."""
    return all((DOSSIER_ASSETS / f).exists()
               for f in ("leaflet.js", "leaflet.css", "jquery.js"))


DATE_ANALYSE = date.today().isoformat()
