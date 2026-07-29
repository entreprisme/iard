"""Construction de la carte interactive.

L'encodage visuel tient en quatre variables, et une seule est colorée :

* **couleur**  → segment (RP / RS / PNO) ;
* **forme**    → sinistre déclaré (triangle) ou non (disque) ;
* **plein / anneau** → propriétaire ou locataire ;
* **taille**   → niveau de certitude.

Deux traitements selon l'usage de la couche. Les niveaux retenus comme impactés
sont peu nombreux et servent à travailler : marqueurs individuels, survol
identifiant, fiche au clic. Les couches de contexte se comptent par milliers et
ne servent qu'à situer : une seule structure GeoJSON, survol seul. Un marqueur
individuel avec fiche pèse ~2,5 Ko — à 15 000 points cela ajouterait 35 Mo.
"""

from __future__ import annotations

import json
import re

import folium
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from . import config as cfg

CHAMPS_CONTEXTE = ["id_societaire", "numero_intercalaire", "segment"]
ALIAS_CONTEXTE = ["Sociétaire", "Intercalaire", "Segment"]


def _jour(v) -> str:
    """Date lisible, quelle que soit la forme reçue (Timestamp, str, NaT)."""
    if v is None or (isinstance(v, float) and pd.isna(v)) or pd.isna(v):
        return "—"
    try:
        return pd.to_datetime(v).strftime("%d/%m/%Y")
    except Exception:                                            # noqa: BLE001
        return str(v)[:10]


def _survol(r, couleur: str, statut: str, type_bien: str) -> str:
    """L'identification, et rien d'autre — c'est ce qu'on cherche en balayant
    la carte pour rapprocher un point d'un dossier."""
    return (f'<div style="font:12px/1.55 system-ui,-apple-system,sans-serif;">'
            f'<b>Sociétaire {r.id_societaire}</b><br>'
            f'Intercalaire {r.numero_intercalaire}<br>'
            f'<span style="color:{couleur};">●</span> {r.segment} · {statut}'
            f'<br>{type_bien}'
            + ("<br>🔴 <b>sinistre ouvert</b>"
               if getattr(r, "sinistre_declare", False) else "")
            + '</div>')


def _fiche(r, statut: str, type_bien: str) -> str:
    """La fiche complète, au clic."""
    dist = "—" if pd.isna(r.distance_bati_m) else f"{r.distance_bati_m:.1f} m"
    adresse = " ".join(str(getattr(r, c, "") or "") for c in
                       ("rue_adresse_risque", "code_postal_adresse_risque",
                        "commune_adresse_risque")).strip()
    if getattr(r, "sinistre_declare", False):
        bloc_sinistre = (
            f"<hr style='margin:5px 0'><b style='color:#b91c1c'>▲ Sinistre ouvert</b>"
            f"<br>N° : {getattr(r, 'numeros_sinistres', '—')}<br>"
            f"Ouvert le : {_jour(getattr(r, 'date_declaration', None))}"
            + (f"<br>({int(r.nb_sinistres_ouverts)} dossiers)"
               if getattr(r, "nb_sinistres_ouverts", 0) > 1 else ""))
    else:
        bloc_sinistre = "<hr style='margin:5px 0'><i>Aucune déclaration à ce jour</i>"

    return (f"<div style='font:12.5px/1.6 system-ui,-apple-system,sans-serif;'>"
            f"<b>{cfg.LIB_SEGMENT.get(r.segment, r.segment)}</b>"
            f"<hr style='margin:5px 0'>"
            f"<b>Sociétaire :</b> {r.id_societaire}<br>"
            f"<b>Intercalaire :</b> {r.numero_intercalaire}<br>"
            f"<b>Statut :</b> {getattr(r, 'qualite', statut)}<br>"
            f"<b>Type de bien :</b> {type_bien}<br>"
            f"{adresse}<hr style='margin:5px 0'>"
            f"Niveau : {r.niveau_impact}<br>"
            f"Distance au bâti de l'emprise : {dist}"
            + ("<br><i>⚠️ géocodage à confirmer</i>" if r.geocodage_suspect else "")
            + bloc_sinistre + "</div>")


def _forme(statut: str, couleur: str, style: dict) -> dict:
    """La couleur porte le segment et la taille la certitude : le statut passe
    donc par la forme, pas par une seconde palette."""
    if statut == "Locataire":
        return dict(color=couleur, fillColor="#ffffff", fillOpacity=0.9,
                    weight=max(2.2, style["weight"] + 0.8))
    if statut == "Propriétaire":
        return dict(color="#ffffff", fillColor=couleur,
                    fillOpacity=style["fill_opacity"], weight=style["weight"])
    return dict(color="#52514e", fillColor=couleur,
                fillOpacity=style["fill_opacity"] * 0.6,
                weight=max(1.2, style["weight"]))


def _couche_contexte(carte, sel, nom, rayon, opacite, en_gris=False,
                     identifier=True, afficher=print) -> None:
    """Couche légère : une seule structure GeoJSON, survol seul, pas de fiche.

    `identifier=False` ne garde que le segment. Chaque propriété est répétée par
    point, et le GeoJSON étant échappé pour tenir dans l'attribut srcdoc de
    l'iframe, chaque guillemet y compte pour six caractères. Sur une couche de
    milliers de points, l'identification pèse plus que les géométries.
    """
    if sel.empty:
        return
    if len(sel) > cfg.MAX_POINTS_CONTEXTE:
        afficher(f"⚠️  {nom} : {len(sel)} contrats, la carte n'en affiche que "
                 f"{cfg.MAX_POINTS_CONTEXTE} (MAX_POINTS_CONTEXTE). Affichage "
                 "échantillonné, comptages inchangés.")
        sel = sel.sample(cfg.MAX_POINTS_CONTEXTE, random_state=0)

    voulus = CHAMPS_CONTEXTE if identifier else ["segment"]
    champs = [c for c in voulus if c in sel.columns]
    alias = [a for c, a in zip(CHAMPS_CONTEXTE, ALIAS_CONTEXTE) if c in champs]
    # 15 décimales par coordonnée pèsent lourd à cette volumétrie pour une
    # précision absurde ; 5 décimales valent environ 1 m, largement assez ici.
    sel = sel.assign(geometry=sel.geometry.apply(
        lambda g: Point(round(g.x, 5), round(g.y, 5))))

    folium.GeoJson(
        sel[champs + ["geometry"]],
        name=f"{nom} ({len(sel)})",
        show=False,
        marker=folium.CircleMarker(radius=rayon, fill=True),
        style_function=lambda f: {
            "radius": rayon, "weight": 0.5, "color": "#ffffff", "fillOpacity": opacite,
            "fillColor": (cfg.PALETTE_SEGMENT["Autres"] if en_gris else
                          cfg.PALETTE_SEGMENT.get(f["properties"].get("segment"),
                                                  cfg.PALETTE_SEGMENT["Autres"])),
        },
        tooltip=folium.GeoJsonTooltip(fields=champs, aliases=alias),
    ).add_to(carte)


def _controle_cadrage(carte, contours_wgs, bornes) -> None:
    """Raccourcis « Aller à ». À l'échelle qui couvre plusieurs feux distants de
    dizaines de kilomètres, un bâtiment de 137 m² occupe moins d'un pixel : la
    vue d'ensemble situe, elle ne permet pas de lire."""
    y0, x0, y1, x1 = bornes
    zones = {"Vue d'ensemble": [[y0, x0], [y1, x1]]}
    for nom in cfg.feux_actifs():
        fx0, fy0, fx1, fy1 = contours_wgs.loc[contours_wgs.feu == nom].total_bounds
        zones[f"Feu de {nom}"] = [[fy0, fx0], [fy1, fx1]]

    carte.get_root().script.add_child(folium.Element(f"""
  window.addEventListener("load", function () {{
    var zones = {json.dumps(zones)};
    var ctlZones = L.control({{position: 'topleft'}});
    ctlZones.onAdd = function () {{
        var d = L.DomUtil.create('div', 'leaflet-bar');
        d.style.cssText = 'background:#fff;padding:7px 9px;font:12px/1.65 ' +
            'system-ui,-apple-system,sans-serif;color:#0b0b0b;';
        var h = '<div style="font-weight:650;margin-bottom:2px;">Aller à</div>';
        Object.keys(zones).forEach(function (k) {{
            h += '<a href="#" data-z="' + k + '" style="display:block;color:#1c5cab;' +
                 'text-decoration:none;white-space:nowrap;">' + k + '</a>';
        }});
        d.innerHTML = h;
        L.DomEvent.disableClickPropagation(d);
        d.querySelectorAll('a').forEach(function (a) {{
            a.onclick = function (e) {{
                e.preventDefault();
                {carte.get_name()}.fitBounds(zones[a.getAttribute('data-z')]);
            }};
        }});
        return d;
    }};
    ctlZones.addTo({carte.get_name()});
  }});
"""))


def _legende() -> str:
    """Légende en HTML/CSS pur : les seuils sont interpolés depuis les
    paramètres, un texte figé finirait par contredire le calcul."""
    return f"""
<div style="position:fixed;bottom:24px;right:12px;z-index:9999;background:rgba(255,255,255,.94);
  padding:9px 11px;border-radius:9px;box-shadow:0 1px 8px rgba(0,0,0,.28);max-width:225px;
  font:11.5px/1.35 system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;color:#0b0b0b;">
  <div style="font-weight:650;margin-bottom:6px;">Segment</div>
  <div><span style="display:inline-block;width:11px;height:11px;border-radius:50%;
    background:{cfg.PALETTE_SEGMENT['RP']};margin-right:6px;"></span>RP — rés. principale</div>
  <div><span style="display:inline-block;width:11px;height:11px;border-radius:50%;
    background:{cfg.PALETTE_SEGMENT['RS']};margin-right:6px;"></span>RS — rés. secondaire</div>
  <div><span style="display:inline-block;width:11px;height:11px;border-radius:50%;
    background:{cfg.PALETTE_SEGMENT['PNO']};margin-right:6px;"></span>PNO — propr. non occupant</div>
  <div style="font-weight:650;margin:7px 0 4px;">Occupation</div>
  <div><span style="display:inline-block;width:11px;height:11px;border-radius:50%;
    background:#2a78d6;border:1.5px solid #fff;margin-right:6px;
    vertical-align:-1px;"></span>Propriétaire — plein</div>
  <div><span style="display:inline-block;width:11px;height:11px;border-radius:50%;
    background:#fff;border:2px solid #2a78d6;margin-right:6px;
    vertical-align:-1px;"></span>Locataire — anneau</div>
  <div><span style="display:inline-block;width:11px;height:11px;border-radius:50%;
    background:#2a78d6;border:1.5px solid #52514e;margin-right:6px;
    vertical-align:-1px;opacity:.6;"></span>Autre — contour gris</div>
  <div style="font-weight:650;margin:7px 0 4px;">Sinistre</div>
  <div><span style="display:inline-block;width:0;height:0;border-left:6px solid transparent;
    border-right:6px solid transparent;border-bottom:10px solid #2a78d6;margin-right:6px;
    vertical-align:0px;"></span>sinistre incendie ouvert</div>
  <div><span style="display:inline-block;width:11px;height:11px;border-radius:50%;
    background:#2a78d6;margin-right:6px;vertical-align:-1px;"></span>aucune déclaration</div>
  <div style="font-weight:650;margin:7px 0 4px;">Certitude</div>
  <div>● grand — emprise ou &lt; {cfg.SEUIL_CERTAIN_M:.0f} m</div>
  <div>● moyen — {cfg.SEUIL_CERTAIN_M:.0f} à {cfg.SEUIL_TRES_PROBABLE_M:.0f} m</div>
  <div>● petit — {cfg.SEUIL_TRES_PROBABLE_M:.0f} à {cfg.SEUIL_PROBABLE_M:.0f} m</div>
  <div style="margin-top:7px;"><span style="display:inline-block;width:11px;height:11px;
    background:#1f2937;margin-right:6px;"></span>Bâti de l'emprise brûlée</div>
  <div style="margin-top:5px;"><span style="display:inline-block;width:16px;
    border-top:1.5px dashed #52514e;margin-right:6px;vertical-align:3px;"></span>Zone analysée</div>
  <div style="margin-top:8px;padding-top:7px;border-top:1px solid #e0dfda;color:#52514e;">
    Survol : sociétaire, intercalaire,<br>segment, statut, type de bien<br>Clic : fiche complète</div>
</div>"""


def construire(appar: gpd.GeoDataFrame, batis: gpd.GeoDataFrame,
               contours: gpd.GeoDataFrame, bbox, afficher=print) -> folium.Map:
    """Assemble la carte : emprises, bâtis, contrats, couches de contexte."""
    lon_min, lat_min, lon_max, lat_max = bbox
    carte_pts = appar.to_crs(cfg.CRS_AFFICHAGE)
    contours_wgs = contours.to_crs(cfg.CRS_AFFICHAGE)
    centre = contours_wgs.geometry.union_all().centroid

    m = folium.Map(location=[centre.y, centre.x], tiles=cfg.FOND_DE_CARTE,
                   control_scale=True)
    # On cadre sur l'emprise commune plutôt que sur un zoom fixe, sinon les feux
    # les plus éloignés sortent de l'écran.
    x0, y0, x1, y1 = contours_wgs.total_bounds
    m.fit_bounds([[y0, x0], [y1, x1]], padding=(20, 20))

    folium.GeoJson(
        contours_wgs.assign(geometry=contours_wgs.geometry.set_precision(1e-6)),
        name="Périmètre des feux",
        style_function=lambda _: {"color": "#e34948", "weight": 2.5,
                                  "fillColor": "#e34948", "fillOpacity": 0.06},
        tooltip=folium.GeoJsonTooltip(fields=["feu", "surface_feu_ha"],
                                      aliases=["Feu", "Surface (ha)"]),
    ).add_to(m)

    # Emprises simplifiées de 30 cm et coordonnées arrondies au décimètre avant
    # sérialisation : à plusieurs milliers de polygones, les 15 décimales par
    # défaut pèsent lourd pour une précision sans objet à l'écran.
    # La couche est absente quand aucun feu n'a fourni ses bâtiments : folium
    # refuse une infobulle sur un GeoJSON sans attributs.
    if len(batis):
        b = batis.copy()
        b["geometry"] = b.geometry.simplify(0.3, preserve_topology=True)
        b = b.to_crs(cfg.CRS_AFFICHAGE)
        b["geometry"] = b.geometry.set_precision(1e-6)
        folium.GeoJson(
            b,
            name=f"Bâtiments dans l'emprise brûlée ({len(b)})",
            style_function=lambda _: {"color": "#0d366b", "weight": 0.6,
                                      "fillColor": "#1f2937", "fillOpacity": 0.85},
            tooltip=folium.GeoJsonTooltip(fields=["feu", "bat_id", "surface_bati_m2"],
                                          aliases=["Feu", "Bâtiment", "Emprise (m²)"]),
        ).add_to(m)

    styles = cfg.style_niveau()
    for niveau in cfg.niveaux_impactes():
        style = styles[niveau]
        sel = carte_pts[(carte_pts["niveau_impact"] == niveau)
                        & carte_pts["dans_perimetre_demande"]]
        if sel.empty:
            continue
        fg = folium.FeatureGroup(name=f"{niveau} ({len(sel)})", show=True)
        for r in sel.itertuples():
            couleur = cfg.PALETTE_SEGMENT.get(r.segment, cfg.PALETTE_SEGMENT["Autres"])
            if r.niveau_impact == cfg.NIVEAU_INEXPLOITABLE:
                couleur = cfg.PALETTE_SEGMENT["Autres"]   # gris : position non fiable
            statut = getattr(r, "statut", "Autre / non renseigné")
            type_bien = getattr(r, "type_bien", None) or "Type non renseigné"
            survol = _survol(r, couleur, statut, type_bien)
            fiche = _fiche(r, statut, type_bien)
            forme = _forme(statut, couleur, style)

            # Un sinistre déclaré est le signal le plus fort de la carte : il
            # change la forme du marqueur, pas seulement sa couleur. Le plein et
            # l'anneau continuent de porter le statut — un triangle évidé reste
            # un triangle.
            if getattr(r, "sinistre_declare", False):
                cote = style["radius"] * 2 + 5
                folium.Marker(
                    location=[r.geometry.y, r.geometry.x],
                    icon=folium.DivIcon(
                        html=(f'<svg width="{cote:.0f}" height="{cote:.0f}" '
                              f'viewBox="0 0 20 20">'
                              f'<polygon points="10,1.6 18.6,17.4 1.4,17.4" '
                              f'fill="{forme["fillColor"]}" '
                              f'fill-opacity="{forme["fillOpacity"]}" '
                              f'stroke="{forme["color"]}" '
                              f'stroke-width="{forme["weight"] + 0.4:.1f}" '
                              f'stroke-linejoin="round"/></svg>'),
                        icon_size=(cote, cote), icon_anchor=(cote / 2, cote / 2),
                        class_name=""),
                    tooltip=folium.Tooltip(survol, sticky=True),
                    popup=folium.Popup(fiche, max_width=340),
                ).add_to(fg)
            else:
                folium.CircleMarker(
                    location=[r.geometry.y, r.geometry.x], radius=style["radius"],
                    fill=True, tooltip=folium.Tooltip(survol, sticky=True),
                    popup=folium.Popup(fiche, max_width=340), **forme,
                ).add_to(fg)
        fg.add_to(m)

    # Le dénominateur : la zone analysée et les contrats examinés mais non
    # retenus. Sans eux la carte ne montre que des impacts et ne dit rien de ce
    # qui a été regardé.
    fg_zone = folium.FeatureGroup(name="Limite de la zone analysée", show=True)
    folium.Rectangle(
        bounds=[[lat_min, lon_min], [lat_max, lon_max]],
        color="#52514e", weight=1.5, dash_array="7,6", fill=False,
        tooltip=("Limite de la zone analysée — "
                 f"lon [{lon_min}, {lon_max}] / lat [{lat_min}, {lat_max}]"),
    ).add_to(fg_zone)
    fg_zone.add_to(m)

    demande = carte_pts[carte_pts["dans_perimetre_demande"]]
    contexte = [
        # exposés et positions douteuses restent identifiables : on travaille dessus
        (cfg.NIV_EXPOSE, 3.5, 0.45, False, True),
        (cfg.NIVEAU_INEXPLOITABLE, 3.5, 0.40, True, True),
        # hors périmètre : repère de volume, l'identification n'y sert à rien
        (cfg.NIV_HORS, 2.5, 0.55, False, False),
    ]
    for niveau, rayon, opacite, gris, ident in contexte:
        if niveau in cfg.niveaux_impactes():
            continue                     # déjà rendu en marqueurs individuels
        _couche_contexte(m, demande[demande["niveau_impact"] == niveau],
                         niveau, rayon, opacite, gris, ident, afficher)

    folium.LayerControl(position="topright", collapsed=False).add_to(m)
    _controle_cadrage(m, contours_wgs, (y0, x0, y1, x1))
    m.get_root().html.add_child(folium.Element(_legende()))
    return m


def rendre_autonome(carte: folium.Map, afficher=print) -> str:
    """Rend la carte en HTML sans aucune dépendance CDN.

    folium référence Leaflet, jQuery, Bootstrap et awesome-markers via des
    <script src> distants. Sur un poste dont le proxy bloque ces CDN, la page
    reste blanche — incident déjà rencontré sur les cartes de grêle. On retire
    donc toutes les ressources externes et on réinjecte Leaflet et jQuery, les
    seules réellement nécessaires, depuis `incendie/assets/`.

    jQuery avant Leaflet : folium construit chaque popup avec `$(...)`, et une
    ReferenceError sur `$` interrompt tout le script — y compris les marqueurs
    et le sélecteur de couches déclarés plus loin.
    """
    doc = carte.get_root().render()
    if not cfg.leaflet_embarque():
        afficher("⚠️  incendie/assets/leaflet.js absent → la carte dépendra des CDN.")
        return doc

    doc = re.sub(r'<script[^>]+src="https?://[^"]+"[^>]*>\s*</script>', "", doc)
    doc = re.sub(r'<link[^>]+href="https?://[^"]+"[^>]*/?>', "", doc)

    def lire(nom):
        return ((cfg.DOSSIER_ASSETS / nom).read_text(encoding="utf-8")
                .replace("</script>", r"<\/script>"))

    inject = (f"<style>{lire('leaflet.css')}</style>\n"
              f"<script>{lire('jquery.js')}</script>\n"
              f"<script>{lire('leaflet.js')}</script>\n")
    return doc.replace("</head>", inject + "</head>", 1)
