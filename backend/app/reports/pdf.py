"""Scientific PDF report generation (ReportLab + Matplotlib) from a stored run."""
from __future__ import annotations

import io
import uuid
from datetime import datetime

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from .. import catalog  # noqa: E402
from ..config import PROCESSED_DIR, REPORTS_DIR  # noqa: E402

PALETTE = ["#2f7ed8", "#e4572e", "#17b890", "#f3a712", "#8e5ac8", "#d64f9b", "#5aa9e6", "#7d8c3a"]
NOISE = "#9aa0a6"
INK = colors.HexColor("#1d232a")
MUTED = colors.HexColor("#5d6670")


def _color(c: int) -> str:
    return NOISE if c < 0 else PALETTE[c % len(PALETTE)]


def _fig_to_image(fig, width_mm: float) -> Image:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=170, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    img = Image(buf)
    ratio = img.imageHeight / img.imageWidth
    img.drawWidth = width_mm * mm
    img.drawHeight = width_mm * mm * ratio
    return img


def _fmt(v, nd=3):
    if v is None:
        return "–"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


_HDR = ParagraphStyle("hdr", fontName="Helvetica-Bold", fontSize=7.4, leading=8.8, textColor=INK)
_CELL = ParagraphStyle("cell", fontName="Helvetica", fontSize=7.6, leading=9.2, textColor=INK)


def _table(rows, widths=None, header=True, font=8):
    # Wrap plain-text cells so long headers/labels never overlap adjacent columns.
    rows = [[Paragraph(str(c), _HDR if (header and i == 0) else _CELL) if isinstance(c, str) else c for c in r]
            for i, r in enumerate(rows)]
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("FONT", (0, 0), (-1, -1), "Helvetica", font),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, INK),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6f8")]),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]
    if header:
        style.append(("FONT", (0, 0), (-1, 0), "Helvetica-Bold", font))
    t.setStyle(TableStyle(style))
    return t


def _map_figure(res: dict):
    g = gpd.read_file(PROCESSED_DIR / res["region"]["id"] / "base_features.gpkg")
    lab = {a["catchment_id"]: a["cluster"] for a in res["assignments"]}
    g = g[g["catchment_id"].isin(lab)]
    g["cluster"] = g["catchment_id"].map(lab)
    fig, ax = plt.subplots(figsize=(7, 5.2))
    for c, sub in g.groupby("cluster"):
        sub.plot(ax=ax, color=_color(int(c)), edgecolor="white", linewidth=0.25)
    names = {p["cluster"]: p["name"] for p in res["profiles"]}
    handles = [plt.Rectangle((0, 0), 1, 1, color=_color(c)) for c in sorted(names)]
    ax.legend(handles, [f"{c if c >= 0 else 'N'} · {names[c]}" for c in sorted(names)], fontsize=6.5,
              loc="lower left", frameon=True)
    ax.set_xlabel("Longitude (°E)", fontsize=7)
    ax.set_ylabel("Latitude (°N)", fontsize=7)
    ax.tick_params(labelsize=6)
    ax.set_title("Discovered catchment behaviour groups (HydroBASINS level 12)", fontsize=8)
    return fig


def _pca_figure(res: dict):
    fig, ax = plt.subplots(figsize=(4.6, 3.6))
    xs = [a["pca"][0] for a in res["assignments"]]
    ys = [a["pca"][1] if len(a["pca"]) > 1 else 0 for a in res["assignments"]]
    cs = [_color(a["cluster"]) for a in res["assignments"]]
    ax.scatter(xs, ys, c=cs, s=9, linewidths=0)
    ev = res["pca"]["explained_variance"]
    ax.set_xlabel(f"PC1 ({ev[0]*100:.0f}% var.)", fontsize=7)
    ax.set_ylabel(f"PC2 ({ev[1]*100:.0f}% var.)" if len(ev) > 1 else "", fontsize=7)
    ax.tick_params(labelsize=6)
    ax.set_title("PCA projection of scaled features (not geographic distance)", fontsize=7.5)
    return fig


def _profile_figure(res: dict):
    feats = [f["key"] for f in res["features"]]
    labels = [f["label"] for f in res["features"]]
    profs = [p for p in res["profiles"] if p["cluster"] >= 0]
    fig, ax = plt.subplots(figsize=(7, 0.22 * len(feats) + 1.2))
    import numpy as np
    w = 0.8 / max(len(profs), 1)
    y = np.arange(len(feats))
    for i, p in enumerate(profs):
        ax.barh(y + i * w, [p["z_profile"].get(k, 0) for k in feats], height=w, color=_color(p["cluster"]),
                label=f"{p['cluster']} · {p['name']}")
    ax.set_yticks(y + 0.4 - w / 2, labels, fontsize=6)
    ax.axvline(0, color="#333", lw=0.6)
    ax.set_xlabel("Cluster median vs regional median (robust z, IQR units)", fontsize=7)
    ax.tick_params(axis="x", labelsize=6)
    ax.invert_yaxis()
    ax.legend(fontsize=6, loc="lower right")
    return fig


def _assoc_figure(res: dict, window="concurrent", etype="all"):
    w = res["validation"]["windows"].get(window)
    if not w:
        return None
    cl = [g for g in w[etype]["clusters"]["groups"]]
    bl = w[etype]["baseline"]["groups"]
    fig, axs = plt.subplots(1, 2, figsize=(7, 2.6), sharey=True)
    axs[0].bar([str(g["group"]) if g["group"] >= 0 else "N" for g in cl], [g["events_per_catchment_year"] for g in cl],
               color=[_color(g["group"]) for g in cl])
    axs[0].set_title("Discovered clusters", fontsize=7.5)
    axs[1].bar([g["name"].split()[0] for g in bl], [g["events_per_catchment_year"] for g in bl], color="#8b95a1")
    axs[1].set_title("Elevation-band baseline", fontsize=7.5)
    axs[0].set_ylabel("Recorded events / catchment / yr", fontsize=7)
    for a in axs:
        a.tick_params(labelsize=6)
    return fig


def build_report(res: dict) -> tuple[str, str, int]:
    rid = uuid.uuid4().hex[:12]
    path = REPORTS_DIR / f"report_{res['run_id']}_{rid}.pdf"
    ss = getSampleStyleSheet()
    H1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=17, textColor=INK, spaceAfter=4)
    H2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=12, textColor=INK, spaceBefore=8, spaceAfter=4)
    B = ParagraphStyle("b", parent=ss["BodyText"], fontSize=8.6, leading=11.5, textColor=INK)
    S = ParagraphStyle("s", parent=B, fontSize=7.4, leading=9.5, textColor=MUTED)
    sel = res["selected"]
    m = sel["metrics"]
    region = res["region"]
    period = res["period"]
    story = []

    story += [Paragraph("HillScope AI — Catchment Behaviour Discovery Report", H1),
              Paragraph(f"{region['name']}, {region['country']} · rainfall period {period['label']} · run "
                        f"<b>{res['run_id']}</b> · generated {datetime.now():%Y-%m-%d %H:%M}", S), Spacer(1, 6)]
    story.append(Paragraph(
        "This report documents an <b>unsupervised</b> analysis that groups hill catchments by similarity of terrain, "
        "rainfall regime, land surface and estimated response characteristics. The groups describe behavioural "
        "similarity and potential flash-flood susceptibility patterns; they are <b>not</b> forecasts of flash floods, "
        "and clustering does not establish causation.", B))

    # 1. study region
    f = res.get("filters", {})
    story += [Paragraph("1. Study region", H2), Paragraph(
        f"{region['name']} (bounding box {region['bbox']}). Catchments are HydroBASINS level-12 sub-basins whose "
        f"representative point lies inside the state boundary (geoBoundaries ADM1). Of {f.get('initial_catchments', '–')} "
        f"catchments, {f.get('below_hill_threshold', '–')} with mean elevation below {f.get('hill_threshold_m', '–')} m "
        f"(plains) and {f.get('slivers_lt_10km2', '–')} boundary slivers (&lt;10 km²) were excluded, leaving "
        f"<b>{len(res['assignments'])}</b> hill catchments.", B)]

    # 2. data sources
    story.append(Paragraph("2. Data sources", H2))
    rows = [["Dataset", "Provider", "Nature", "Role", "Status"]]
    for d in catalog.status(region["id"]):
        rows.append([Paragraph(d["name"], S), Paragraph(d["provider"], S), Paragraph(d["nature"], S),
                     Paragraph(d["role"], S), Paragraph(d["status"], S)])
    story.append(_table(rows, [38 * mm, 38 * mm, 30 * mm, 50 * mm, 22 * mm]))
    story.append(Paragraph(
        "Observed discharge is unavailable for these catchments; hydrological response is represented only by "
        "<b>estimated proxies</b> (Kirpich time of concentration with Hack's-law flow length; Rx1day / Tc). These are "
        "never presented as measured streamflow.", S))

    # 3. features
    story.append(Paragraph("3. Feature methodology", H2))
    pre = res["preprocessing"]
    rows = [["Feature", "Group", "Unit", "Nature", "Definition"]]
    for ft in res["features"]:
        rows.append([Paragraph(ft["label"], S), ft["group"], ft["unit"], Paragraph(ft["nature"], S),
                     Paragraph(ft["description"], S)])
    story.append(_table(rows, [34 * mm, 22 * mm, 16 * mm, 24 * mm, 82 * mm]))
    red = "; ".join(f"{d['feature']} (ρ={d['rho']} with {d['redundant_with']})" for d in pre["dropped_redundant"]) or "none"
    story.append(Paragraph(
        f"Feature set: <b>{res['feature_set']['label']}</b>. Preprocessing: median imputation; "
        f"log1p for skewed features ({', '.join(pre['log_transformed']) or 'none'}); robust scaling (median/IQR) "
        f"winsorised at ±5; redundant features removed: {red}. Rainfall indices use only days inside the selected "
        f"period; antecedent rainfall uses strictly preceding days.", S))

    # 4. algorithm & evaluation
    story.append(Paragraph("4. Clustering and model evaluation", H2))
    story.append(Paragraph(
        f"Displayed model: <b>{res['algorithm_name']}</b> with parameters {sel['params']}. "
        f"The most defensible configuration by internal criteria was <b>{res['recommended_algorithm']}</b>. "
        f"Selection rule: {res['selection_rule'].splitlines()[0]} Historical events were not used for selection.", B))
    rows = [["Algorithm", "Params", "k", "Noise", "Silhouette", "Davies–Bouldin", "Calinski–H.", "Stability (ARI)", "Score"]]
    for c in res["comparison"]:
        cm = c["metrics"]
        rows.append([c["name"], Paragraph(str(c["params"]), S), cm["n_clusters"], _fmt(cm["noise_fraction"], 2),
                     _fmt(cm["silhouette"]), _fmt(cm["davies_bouldin"]), _fmt(cm["calinski_harabasz"], 1),
                     _fmt(cm.get("stability")), _fmt(cm["selection_score"])])
    bm = res["baseline"]["metrics"]
    rows.append(["Elevation bands (baseline)", "tertiles", bm["n_clusters"], "0.00", _fmt(bm["silhouette"]),
                 _fmt(bm["davies_bouldin"]), _fmt(bm["calinski_harabasz"], 1), "–", "–"])
    story.append(_table(rows, [30 * mm, 36 * mm, 8 * mm, 12 * mm, 17 * mm, 20 * mm, 18 * mm, 20 * mm, 13 * mm]))
    story.append(Spacer(1, 4))
    story.append(KeepTogether([_fig_to_image(_map_figure(res), 165)]))
    story.append(_fig_to_image(_pca_figure(res), 105))
    story.append(Paragraph(res["pca"]["note"], S))

    # 5. profiles
    story.append(PageBreak())
    story.append(Paragraph("5. Behavioural cluster profiles", H2))
    story.append(Paragraph("Profile names were assigned after clustering from the measured feature distributions "
                           "(cluster median relative to regional median). They are descriptive, not risk ratings.", S))
    rows = [["#", "Profile", "n", "Mean elev. (m)", "Slope (°)", "Rx1day (mm)", "Tc est. (h)", "Distinguishing traits"]]
    for p in res["profiles"]:
        st = p["stats"]
        rows.append([p["cluster"] if p["cluster"] >= 0 else "N", Paragraph(p["name"], S), p["n_catchments"],
                     _fmt(st.get("elev_mean", {}).get("median"), 0), _fmt(st.get("slope_mean", {}).get("median"), 1),
                     _fmt(st.get("rx1day", {}).get("median"), 1), _fmt(st.get("tc_kirpich_h", {}).get("median"), 2),
                     Paragraph(p["summary"], S)])
    story.append(_table(rows, [7 * mm, 32 * mm, 9 * mm, 17 * mm, 13 * mm, 17 * mm, 15 * mm, 70 * mm]))
    story.append(Spacer(1, 4))
    story.append(_fig_to_image(_profile_figure(res), 165))

    # 6. validation
    story.append(PageBreak())
    story.append(Paragraph("6. Independent historical validation", H2))
    for wname, label in (("concurrent", "Concurrent window"), ("out_of_period", "Out-of-period window")):
        w = res["validation"]["windows"].get(wname)
        if not w:
            continue
        for et, etl in (("all", "all flood events"), ("flash", "flash-flood / cloudburst events")):
            d = w[et]
            story.append(Paragraph(
                f"<b>{label} {w['years'][0]}–{w['years'][1]}, {etl}</b>: {d['n_events']} district-located IFI events; "
                f"{d['catchments_with_events']} of {len(res['assignments'])} catchments associated "
                f"(coverage {d['spatial_coverage']:.0%}).", B))
            rows = [["Group", "n", "Events", "Catchments w/ events", "Assoc. rate", "Events / catchment / yr", "Lift"]]
            for g in d["clusters"]["groups"]:
                rows.append([Paragraph(f"{g['group'] if g['group'] >= 0 else 'N'} · {g['name']}", S), g["n_catchments"],
                             g["n_events"], g["catchments_with_events"], _fmt(g["association_rate"], 2),
                             _fmt(g["events_per_catchment_year"], 3), _fmt(g["lift"], 2)])
            for g in d["baseline"]["groups"]:
                rows.append([Paragraph(f"Baseline · {g['name']}", S), g["n_catchments"], g["n_events"],
                             g["catchments_with_events"], _fmt(g["association_rate"], 2),
                             _fmt(g["events_per_catchment_year"], 3), _fmt(g["lift"], 2)])
            story.append(_table(rows, [55 * mm, 10 * mm, 14 * mm, 28 * mm, 18 * mm, 32 * mm, 14 * mm]))
            c, b, bk = d["clusters"], d["baseline"], d["baseline_same_k"]
            story.append(Paragraph(
                f"Association strength (Kruskal–Wallis ε² of per-catchment event counts): clusters "
                f"<b>{_fmt(c['epsilon_squared'])}</b> (p={_fmt(c['kruskal_p'], 4)}), elevation tertiles "
                f"<b>{_fmt(b['epsilon_squared'])}</b>, elevation bands with same k <b>{_fmt(bk['epsilon_squared'])}</b>.", S))
            story.append(Spacer(1, 4))
    fig = _assoc_figure(res)
    if fig:
        story.append(_fig_to_image(fig, 160))

    # 7. baseline
    story.append(Paragraph("7. Baseline comparison", H2))
    bm, sm = res["baseline"]["metrics"], m
    story.append(Paragraph(
        f"In the scaled behavioural feature space, the discovered clustering has silhouette {_fmt(sm['silhouette'])} and "
        f"Davies–Bouldin {_fmt(sm['davies_bouldin'])}; elevation tertiles give silhouette {_fmt(bm['silhouette'])} and "
        f"Davies–Bouldin {_fmt(bm['davies_bouldin'])}. " + _baseline_sentence(res), B))

    # 8. limitations
    story.append(Paragraph("8. Limitations", H2))
    lims = [
        "No observed discharge: response features are terrain/rainfall-derived estimates, not measured hydrographs.",
        "CHIRPS (0.05°, ~5 km) under-resolves convective cloudbursts; sub-daily intensity uses coarse ERA5-Land samples "
        "(0.25°, JJAS of a short window) and is model-derived.",
        "Historical events are district-level (IFI) or regional (DFO); district-scale geolocation limits validation resolution.",
        "Event reporting is incomplete and uneven; absence of records is not evidence of low susceptibility.",
        "Spatial autocorrelation inflates apparent significance; p-values are indicative.",
        "SoilGrids texture and WorldCover classes are infiltration-related proxies, not measured infiltration.",
        "Cluster structure in multivariate geophysical data is often continuous; groups are a convenient partition.",
    ] + [f"Provider issue — {i['dataset']}: {i['message']}" for i in res.get("issues", [])]
    for l in lims:
        story.append(Paragraph("• " + l, B))

    # 9. conclusions
    story.append(Paragraph("9. Conclusions", H2))
    story.append(Paragraph(_conclusion(res), B))
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"Dataset version {res['dataset_version']} · model file {res['model_path'].split('/')[-1].split(chr(92))[-1]} · "
                           f"runtime {res['duration_s']} s.", S))

    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm,
                            bottomMargin=14 * mm, title=f"HillScope report {res['run_id']}", author="HillScope AI")
    pages = {"n": 0}

    def _footer(canvas, d):
        pages["n"] = d.page
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(14 * mm, 8 * mm, "HillScope AI · unsupervised discovery — not a flood forecast")
        canvas.drawRightString(196 * mm, 8 * mm, f"Page {d.page}")

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return rid, str(path), pages["n"]


def _baseline_sentence(res: dict) -> str:
    w = res["validation"]["windows"].get("concurrent", {}).get("all")
    if not w:
        return ""
    c, b = w["clusters"]["epsilon_squared"], w["baseline"]["epsilon_squared"]
    if c is None or b is None:
        return "Event association could not be compared (insufficient variation in event counts)."
    rel = "stronger than" if c > b * 1.1 else ("weaker than" if c < b * 0.9 else "similar to")
    return (f"Association with recorded events is {rel} the elevation baseline (ε² {c:.3f} vs {b:.3f}), indicating "
            f"{'that rainfall and terrain-form features add information beyond elevation alone' if rel.startswith('stronger') else 'that elevation alone captures much of the recorded-event pattern at district resolution'}.")


def _conclusion(res: dict) -> str:
    k = res["selected"]["metrics"]["n_clusters"]
    names = ", ".join(p["name"] for p in res["profiles"] if p["cluster"] >= 0)
    s = res["selected"]["metrics"]
    return (f"{res['algorithm_name']} identified {k} behavioural groups among {len(res['assignments'])} hill catchments "
            f"of {res['region']['name']} ({names}), with silhouette {_fmt(s['silhouette'])} and bootstrap stability "
            f"{_fmt(s.get('stability'))}. {_baseline_sentence(res)} These results support using behaviour-based "
            f"groupings as a screening layer for differentiated flash-flood preparedness, subject to the limitations "
            f"above; they do not constitute a validated predictive model.")
