"""Génération du livrable HTML.

Un fichier unique : compteurs, carte embarquée, tableaux, méthode et limites.
Il s'ouvre dans n'importe quel navigateur et se transmet tel quel.

Tous les libellés dépendant de la sélection de feux ou des seuils sont
interpolés, jamais écrits en dur : un rapport qui annonce « les deux feux »
alors qu'un seul a été traité, ou « moins de 10 m » quand le calcul en utilise
un autre, est une erreur invisible.
"""

from __future__ import annotations

import html as _html
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from . import config as cfg
from . import donnees, resultats

CSS = """
:root{color-scheme:light dark}
*{box-sizing:border-box}
body{margin:0;font:15px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  background:var(--bg);color:var(--txt)}
:root{--bg:#f4f4f2;--surface:#fcfcfb;--txt:#0b0b0b;--txt2:#52514e;--line:#e0dfda;
  --rp:#2a78d6;--rs:#eb6834;--pno:#1baf7a;--alert:#e34948}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){
  --bg:#111110;--surface:#1a1a19;--txt:#fff;--txt2:#c3c2b7;--line:#383835;
  --rp:#3987e5;--rs:#d95926;--pno:#199e70;--alert:#e66767}}
:root[data-theme="dark"]{--bg:#111110;--surface:#1a1a19;--txt:#fff;--txt2:#c3c2b7;
  --line:#383835;--rp:#3987e5;--rs:#d95926;--pno:#199e70;--alert:#e66767}
.wrap{max-width:1180px;margin:0 auto;padding:2rem 1.25rem 4rem}
header h1{font-size:1.6rem;margin:0 0 .3rem;letter-spacing:-.01em}
header p{margin:0;color:var(--txt2);font-size:.93rem}
.bandeau{margin:1.25rem 0;padding:.8rem 1rem;border-radius:10px;font-size:.88rem;
  background:#fff7ed;border:1px solid #fed7aa;color:#9a3412}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])) .bandeau{
  background:#2a1a0d;border-color:#7c3d12;color:#fdba74}}
section{background:var(--surface);border:1px solid var(--line);border-radius:14px;
  padding:1.4rem 1.5rem;margin:1.25rem 0}
h2{font-size:1.05rem;margin:0 0 1rem;letter-spacing:-.005em}
h2 .n{color:var(--txt2);font-weight:400;margin-right:.45rem}
.kpis{display:grid;gap:.9rem;grid-template-columns:repeat(auto-fit,minmax(190px,1fr))}
.kpi{border:1px solid var(--line);border-radius:12px;padding:1rem 1.1rem;background:var(--bg)}
.kpi .v{font-size:2.1rem;font-weight:640;line-height:1.05;letter-spacing:-.02em;
  font-variant-numeric:tabular-nums}
.kpi .l{font-size:.8rem;color:var(--txt2);margin-top:.35rem;line-height:1.4}
.kpi.lead .v{color:var(--alert)}
.tbl{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%;font-size:.88rem;min-width:520px}
th,td{padding:.55rem .7rem;text-align:right;border-bottom:1px solid var(--line);
  font-variant-numeric:tabular-nums;white-space:nowrap}
th:first-child,td:first-child,th.t,td.t{text-align:left;font-variant-numeric:normal}
thead th{color:var(--txt2);font-weight:600;font-size:.8rem;text-transform:uppercase;
  letter-spacing:.03em;border-bottom:1.5px solid var(--line)}
tbody tr:last-child td{border-bottom:none}
tr.tot td{font-weight:650;border-top:1.5px solid var(--line)}
.pill{display:inline-flex;align-items:center;gap:.4rem;font-weight:600}
.dot{width:9px;height:9px;border-radius:50%;flex:none}
.lire{border:1px solid var(--line);border-radius:10px;padding:.9rem 1.1rem;
  margin:0 0 1rem;background:var(--bg)}
.lire-t{font-weight:650;font-size:.85rem;margin-bottom:.6rem}
.lire dl{display:grid;grid-template-columns:auto 1fr;gap:.4rem .8rem;margin:0;
  font-size:.86rem;color:var(--txt2);align-items:baseline}
.lire dt{display:flex;align-items:center;gap:3px;justify-content:flex-end;min-width:44px}
.lire dd{margin:0}
.lire dd b{color:var(--txt);font-weight:600}
.lire-p{margin:.8rem 0 0;font-size:.84rem;color:var(--txt2);line-height:1.55}
.lire i{flex:none;display:inline-block}
.k-dot{width:10px;height:10px;border-radius:50%}
.k-ring{width:10px;height:10px;border-radius:50%;border:2px solid;background:transparent}
.k-tri{width:0;height:0;border-left:6px solid transparent;border-right:6px solid transparent;
  border-bottom:10px solid}
.k-sq{width:10px;height:10px}
.k-dash{width:18px;border-top:1.5px dashed var(--txt2)}
.map{height:780px;border:1px solid var(--line);border-radius:12px;overflow:hidden}
.map iframe{width:100%;height:100%;border:0;display:block}
.notes{font-size:.87rem;color:var(--txt2)}
.notes li{margin-bottom:.5rem}
footer{margin-top:2rem;font-size:.78rem;color:var(--txt2);text-align:center}
"""

MARQUE_STATUT = {
    "Propriétaire": "background:#52514e;border:1.5px solid #fff;",
    "Locataire": "background:#fff;border:2px solid #52514e;",
    "Autre / non renseigné": "background:#52514e;border:1.5px solid #52514e;opacity:.6;",
}


def _n(v) -> str:
    return f"{int(v):,}".replace(",", " ")


def _tab(df: pd.DataFrame, cls_first=True) -> str:
    th = "".join(
        f"<th{' class=t' if i == 0 and cls_first else ''}>{_html.escape(str(c))}</th>"
        for i, c in enumerate(df.columns))
    tr = ""
    for _, r in df.iterrows():
        tds = "".join(
            f"<td{' class=t' if i == 0 and cls_first else ''}>"
            f"{_n(v) if isinstance(v, (int, np.integer)) else _html.escape(str(v))}</td>"
            for i, v in enumerate(r))
        tr += f"<tr>{tds}</tr>"
    return (f'<div class="tbl"><table><thead><tr>{th}</tr></thead>'
            f"<tbody>{tr}</tbody></table></div>")


def ecrire(appar: gpd.GeoDataFrame, batis: gpd.GeoDataFrame, carte_html: str,
           mode_source: str, col_precision: str | None,
           chemin: Path | None = None, afficher=print) -> Path:
    """Assemble et écrit le livrable. Renvoie le chemin du fichier produit."""
    chemin = chemin or cfg.FICHIER_HTML
    chemin.parent.mkdir(parents=True, exist_ok=True)

    feux = cfg.feux_actifs()
    kpi = resultats.compteurs(appar)
    _, impact = resultats.perimetre_demande(appar)

    # --- KPI par segment ---------------------------------------------------- #
    par_seg = (impact.groupby("segment", observed=True)
                     .agg(batis=("bat_id", "nunique"), contrats=("id", "nunique"),
                          societaires=("id_societaire", "nunique"))
                     .reindex(cfg.SEGMENTS_CIBLE).fillna(0).astype(int))

    kpi_html = f"""
<div class="kpi lead"><div class="v">{_n(kpi['batis_touches'])}</div>
  <div class="l">bâtiments distincts concernés<br>portant un contrat RP / RS / PNO</div></div>
<div class="kpi"><div class="v">{_n(kpi['contrats'])}</div>
  <div class="l">contrats habitation impactés</div></div>
<div class="kpi"><div class="v">{_n(kpi['societaires'])}</div>
  <div class="l">sociétaires distincts concernés</div></div>
<div class="kpi"><div class="v">{_n(kpi['certains'])}</div>
  <div class="l">dont impact <b>certain</b><br>emprise brûlée ou moins de
  {cfg.SEUIL_CERTAIN_M:.0f} m</div></div>
<div class="kpi"><div class="v">{_n(kpi['en_perimetre'])}</div>
  <div class="l">dans le périmètre du feu mais<br>hors emprise bâtie — exposés</div></div>
<div class="kpi"><div class="v">{_n(kpi['inexploitables'])}</div>
  <div class="l">position trop imprécise<br>pour conclure</div></div>
"""

    seg_rows = "".join(
        f'<tr><td class=t><span class="pill"><span class="dot" style="background:'
        f'{cfg.PALETTE_SEGMENT[s]}"></span>{s} — {cfg.LIB_SEGMENT[s]}</span></td>'
        f"<td>{_n(par_seg.loc[s, 'batis'])}</td>"
        f"<td>{_n(par_seg.loc[s, 'contrats'])}</td>"
        f"<td>{_n(par_seg.loc[s, 'societaires'])}</td></tr>"
        for s in cfg.SEGMENTS_CIBLE)
    seg_rows += (f'<tr class=tot><td class=t>Total RP + RS + PNO</td>'
                 f"<td>{_n(kpi['batis_touches'])}</td><td>{_n(kpi['contrats'])}</td>"
                 f"<td>{_n(kpi['societaires'])}</td></tr>")

    # --- Statut d'occupation × segment -------------------------------------- #
    croise = resultats.croisement_statut(appar)
    if croise is None:
        stat_rows, nb_proprio, nb_loc, pno_loc = "", 0, 0, 0
    else:
        stat_rows = ""
        for s in cfg.ORDRE_STATUTS:
            cells = "".join(f"<td>{_n(croise.loc[s, c])}</td>"
                            for c in list(cfg.SEGMENTS_CIBLE) + ["Total"])
            stat_rows += (f'<tr><td class=t><span class="pill"><span style="width:11px;'
                          f'height:11px;border-radius:50%;display:inline-block;'
                          f'{MARQUE_STATUT[s]}"></span>{s}</span></td>{cells}</tr>')
        tot = croise.sum()
        stat_rows += ('<tr class=tot><td class=t>Total</td>'
                      + "".join(f"<td>{_n(tot[c])}</td>"
                                for c in list(cfg.SEGMENTS_CIBLE) + ["Total"])
                      + "</tr>")
        nb_proprio = int(croise.loc["Propriétaire", "Total"])
        nb_loc = int(croise.loc["Locataire", "Total"])
        pno_loc = int(croise.loc["Locataire", "PNO"]) if "PNO" in croise.columns else 0

    # --- Bandeau et textes dépendant du contexte ---------------------------- #
    bandeau = ""
    if mode_source == "fichier":
        bandeau = (f'<div class="bandeau"><b>Source : export local du '
                   f'{donnees.date_export_local()}.</b></div>')

    if col_precision:
        texte_geocodage = (
            f"{_n(kpi['suspects'])} contrat(s) impacté(s) ont une position qui n'est "
            f"pas posée sur l'adresse — centroïde de commune ou lieu-dit — d'après la "
            f"colonne <code>{col_precision}</code> de la table de géocodage. Leur "
            f"rattachement à un bâtiment n'est pas fiable. Le niveau de géocodage de "
            f"chaque contrat figure en colonne <code>niveau_geocodage</code> de "
            f"l'export CSV.")
    else:
        texte_geocodage = (
            f"{_n(kpi['suspects'])} contrat(s) impacté(s) partagent leurs coordonnées "
            f"avec d'autres contrats situés dans des rues différentes. La table de "
            f"géocodage expose une colonne de précision, plus fiable, qu'il suffirait "
            f"d'ajouter à la requête. Ces cas sont marqués "
            f"<code>geocodage_suspect</code> dans l'export CSV.")

    pluriel_feux = ("le feu de " + cfg.libelle_feux() if len(feux) == 1
                    else f"les {len(feux)} feux")

    phrase_cadrage = (
        "Le bâti n'est lisible qu'à l'échelle du quartier : zoomer, ou utiliser "
        "<b>« Aller à »</b> en haut à gauche pour revenir sur l'emprise."
        if len(feux) == 1 else
        f"Les {len(feux)} feux sont éloignés les uns des autres et le bâti n'est "
        "lisible qu'à l'échelle du quartier : utiliser <b>« Aller à »</b>, en haut "
        "à gauche, pour cadrer sur l'un d'eux.")

    # Distinguer « aucun bâtiment relevé » de « couche non livrée » : annoncer
    # « 0 bâtiments » laisserait croire à un feu sans bâti dans son emprise.
    sans_bati = [n for n in feux if not (batis["feu"] == n).any()]
    if not len(batis):
        texte_batis = (f"Aucune couche de bâtiments fournie pour {pluriel_feux} : les "
                       "contrats ne sont situés que par rapport au périmètre de "
                       "l'incendie.")
    elif sans_bati:
        texte_batis = (f"Emprises des bâtiments ({_n(len(batis))} bâtiments), non "
                       f"fournies pour {' et '.join(sans_bati)} — les contrats de "
                       f"{'ce feu' if len(sans_bati) == 1 else 'ces feux'} ne sont "
                       "situés que par rapport au périmètre.")
    else:
        texte_batis = (f"Emprises des bâtiments ({_n(len(batis))} bâtiments sur "
                       f"{pluriel_feux}) et contours des incendies.")

    entete_feux = " · ".join(
        f"feu de {nom} depuis le {pd.Timestamp(p['debut']).strftime('%d/%m/%Y')}"
        + (f", emprise relevée au {p['releve']}" if p.get("releve") else "")
        for nom, p in feux.items())
    # .capitalize() mettrait tout le reste en minuscules — « feu de var ».
    entete_feux = entete_feux[:1].upper() + entete_feux[1:]

    coherence_pno = ("les " + _n(pno_loc) + " PNO classés « locataire » signalent une "
                     "incohérence de saisie à vérifier" if pno_loc else
                     "aucun PNO n'est ici classé « locataire », la donnée est cohérente")

    detail_html = resultats.detail_par_niveau(appar).reset_index()
    sensi_html = resultats.sensibilite(appar).rename(columns={
        "seuil_m": "Seuil (m)", "batis_touches": "Bâtiments",
        "contrats": "Contrats", "societaires": "Sociétaires", "retenu": ""})
    synth_html = resultats.synthese_par_feu(appar)[
        ["feu", "segment", "batis_touches", "contrats", "societaires"]].rename(
        columns={"feu": "Feu", "segment": "Segment", "batis_touches": "Bâtiments",
                 "contrats": "Contrats", "societaires": "Sociétaires"})

    doc = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bâtis impactés — incendies {cfg.libelle_feux()}</title>
<style>{CSS}</style></head><body><div class="wrap">

<header>
  <h1>Bâtis impactés par les incendies</h1>
  <p>{entete_feux}<br>Stock contrats MGAR en cours · analyse du {cfg.DATE_ANALYSE}</p>
</header>
{bandeau}

<section>
  <h2><span class="n">1</span>Où ?</h2>
  <div class="lire">
    <div class="lire-t">Comment lire la carte</div>
    <dl>
      <dt><i class="k-dot" style="background:var(--rp)"></i><i class="k-dot"
          style="background:var(--rs)"></i><i class="k-dot"
          style="background:var(--pno)"></i></dt>
      <dd><b>La couleur</b> donne le segment : RP, RS, PNO.</dd>

      <dt><i class="k-dot" style="background:var(--txt2)"></i><i class="k-ring"
          style="border-color:var(--txt2)"></i></dt>
      <dd><b>Plein ou évidé</b> : propriétaire ou locataire.</dd>

      <dt><i class="k-tri" style="border-bottom-color:var(--txt2)"></i></dt>
      <dd><b>Le triangle</b> signale un sinistre incendie déjà déclaré ; le disque,
          une absence de déclaration.</dd>

      <dt><i class="k-dot" style="background:var(--txt2);width:13px;height:13px"></i><i
          class="k-dot" style="background:var(--txt2);width:7px;height:7px"></i></dt>
      <dd><b>La taille</b> décroît avec la certitude : emprise brûlée,
          puis {cfg.SEUIL_CERTAIN_M:.0f}–{cfg.SEUIL_TRES_PROBABLE_M:.0f} m,
          puis {cfg.SEUIL_TRES_PROBABLE_M:.0f}–{cfg.SEUIL_PROBABLE_M:.0f} m.</dd>

      <dt><i class="k-sq" style="background:#1f2937"></i><i class="k-dash"></i></dt>
      <dd><b>Les bâtis</b> de l'emprise brûlée sont en gris foncé, la
          <b>limite de la zone analysée</b> en pointillés.</dd>
    </dl>
    <p class="lire-p">{phrase_cadrage} <b>Survoler</b> un point l'identifie,
    <b>cliquer</b> ouvre sa fiche. Le sélecteur en haut à droite active ou masque
    chaque couche.</p>
  </div>
  <div class="map"><iframe srcdoc="{_html.escape(carte_html, quote=True)}"
    loading="lazy" title="Carte des bâtis impactés"></iframe></div>
</section>

<section>
  <h2><span class="n">2</span>Combien ?</h2>
  <div class="kpis">{kpi_html}</div>
</section>

<section>
  <h2><span class="n">3</span>Répartition par segment</h2>
  <div class="tbl"><table>
    <thead><tr><th class=t>Segment</th><th>Bâtiments concernés</th>
      <th>Contrats</th><th>Sociétaires</th></tr></thead>
    <tbody>{seg_rows}</tbody></table></div>
  <p class="notes" style="margin-top:.9rem">Le total en bâtiments est inférieur à la
  somme des lignes : un même immeuble peut porter plusieurs contrats de segments
  différents. {_n(kpi['hors_cible_impactes'])} contrat(s) impacté(s) relèvent d'autres
  segments (jeune, étudiant, hébergé…) et sortent du périmètre de la demande.</p>
</section>

<section>
  <h2><span class="n">4</span>Propriétaires et locataires</h2>
  <div class="tbl"><table>
    <thead><tr><th class=t>Statut d'occupation</th><th>RP</th><th>RS</th>
      <th>PNO</th><th>Total</th></tr></thead>
    <tbody>{stat_rows}</tbody></table></div>
  <p class="notes" style="margin-top:.9rem"><b>{_n(nb_proprio)} propriétaires</b> et
  <b>{_n(nb_loc)} locataires</b> parmi les contrats impactés. La distinction est lue
  sur <code>code_qualite_assure_habitation</code> : nu-propriétaire et usufruitier
  sont comptés côté propriétaire, les colocations côté locataire. Hébergé gratuit,
  logement de service et chambre en établissement ne relèvent ni de l'un ni de l'autre
  et restent à part plutôt que d'être rattachés arbitrairement.</p>
  <p class="notes">Les deux axes ne se recouvrent pas : le segment dit à quoi sert le
  logement, le statut dit qui supporte le dommage au bâti. Un PNO est propriétaire par
  construction — {coherence_pno}. Le détail des modalités figure dans la colonne
  <code>qualite</code> de l'export CSV.</p>
</section>

<section>
  <h2><span class="n">5</span>Détail par feu</h2>
  {_tab(synth_html)}
  <p class="notes" style="margin:1.1rem 0 .5rem">Ventilation de tous les contrats
  RP / RS / PNO par niveau de certitude :</p>
  {_tab(detail_html)}
</section>

<section>
  <h2><span class="n">6</span>Sensibilité au seuil de distance</h2>
  <p class="notes" style="margin-top:-.4rem">Le géocodage d'une adresse ne tombe pas
  toujours dans l'emprise du bâtiment. Ce tableau montre combien de contrats sont
  comptés selon la tolérance retenue — le seuil de {cfg.SEUIL_PROBABLE_M:.0f} m est
  celui appliqué ci-dessus.</p>
  {_tab(sensi_html)}
</section>

<section>
  <h2><span class="n">7</span>Méthode et limites</h2>
  <ul class="notes">
    <li><b>Sources.</b> {texte_batis} Contrats issus de
      <code>contrat_mgar_gps_iris</code> × <code>contrat_mgar</code>
      (<code>tech_date_fin_historisation IS NULL</code>).</li>
    <li><b>Segmentation.</b> <code>code_sous_type</code> : 1–5 → RP, 6 → PNO, 7 → RS.
      Les segments jeune / étudiant / hébergé sont exclus du périmètre de la demande
      mais comptés séparément.</li>
    <li><b>Appariement.</b> Distances calculées en Lambert 93 (EPSG:2154) entre le
      point GPS du contrat et l'emprise du bâtiment relevé le plus proche.</li>
    <li><b>Précision du géocodage.</b> {texte_geocodage}</li>
    <li><b>Emprise minimale 50 m².</b> Les annexes plus petites (abris de jardin,
      cabanons) sont absentes de la couche source : un contrat dont seule la
      dépendance a brûlé n'est pas détecté.</li>
  </ul>
</section>

<footer>Généré le {cfg.DATE_ANALYSE} — source contrats : {mode_source.upper()} ·
Export gestion : <code>{cfg.FICHIER_CSV.name}</code></footer>
</div></body></html>"""

    chemin.write_text(doc, encoding="utf-8")
    afficher(f"✅ Livrable écrit : {chemin}  "
             f"({chemin.stat().st_size / 1024:.0f} Ko)")
    return chemin
