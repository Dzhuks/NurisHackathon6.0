"""Plotly headline graphs for the conclusion slide.

Produces four self-contained plotly charts that together replace the static
matplotlib `headline_totals.png`. Each chart is saved as both HTML (interactive,
hover tooltips) and PNG (slide-ready). Background colour matches the rest of
the deck (#f5f3f0).

Outputs in `outputs/figures/plotly/`:
  1. headline_indicators.{html,png}    three big-number cards (objects / km² / classes)
  2. aoi_composition.{html,png}        donut chart of AOI composition
  3. cars_by_scene.{html,png}          horizontal bar of cars/km² by scene
  4. buildings_class_split.{html,png}  building counts by 9 sub-classes

A combined `headline_dashboard.html` stitches all four into one figure.

Run:  python scripts/make_headline_plotly.py
"""
from pathlib import Path
import warnings

import pandas as pd
import geopandas as gpd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

warnings.filterwarnings("ignore", category=UserWarning)

ROOT = Path(__file__).resolve().parents[1]
SRC_MAIN = ROOT / "outputs"
SRC_BACKUP = ROOT / "outputs_backup_resnet34_15ep"

scene_csv = SRC_MAIN / "scene_metrics.csv"
if not scene_csv.exists():
    scene_csv = SRC_BACKUP / "scene_metrics.csv"
print(f"[plotly] scene_metrics: {scene_csv.relative_to(ROOT)}")
df = pd.read_csv(scene_csv)

OUT = ROOT / "outputs" / "figures" / "plotly"
OUT.mkdir(parents=True, exist_ok=True)

# Editorial palette (same as matplotlib version)
BG = "#f5f3f0"
INK = "#1a1a1a"
INK_SOFT = "#7a756c"
ACCENT = "#b8895a"
ALMATY_C = "#7d4f3e"
ASTANA_C = "#3f6680"
COMP = {
    "buildings":  "#7d4f3e",
    "vegetation": "#5a7a3a",
    "soil":       "#c9a06b",
    "other":      "#a8a09a",
}
SERIF = "Georgia, 'Times New Roman', serif"
SANS = "Helvetica Neue, Helvetica, Arial, sans-serif"


def fmt_n(x):
    return f"{x:,}".replace(",", " ")


def save(fig, name, w=1200, h=600):
    """Write both interactive HTML and slide-ready PNG."""
    fig.write_html(str(OUT / f"{name}.html"), include_plotlyjs="cdn")
    fig.write_image(str(OUT / f"{name}.png"), width=w, height=h, scale=2)
    print(f"[plotly] -> {name}.html + .png")


# ---------------------------------------------------------------------------
# Aggregates from scene_metrics
# ---------------------------------------------------------------------------
total_area_km2 = df["aoi_area_km2"].sum()
total_area_m2 = total_area_km2 * 1e6
total_bld = int(df["n_buildings_total"].sum())
total_house = int(df["n_house"].sum())
total_apt = int(df["n_apartment_block"].sum())
total_cars = int(df["n_cars"].sum())
total_objects = total_bld + total_cars

bld_area_m2 = df["buildings_total_area_m2"].sum()
veg_area_m2 = df["vegetation_area_m2"].sum()
soil_area_m2 = df["bare_soil_area_m2"].sum()
other_m2 = total_area_m2 - bld_area_m2 - veg_area_m2 - soil_area_m2

bld_pct = 100 * bld_area_m2 / total_area_m2
veg_pct = 100 * veg_area_m2 / total_area_m2
soil_pct = 100 * soil_area_m2 / total_area_m2
other_pct = 100 - bld_pct - veg_pct - soil_pct

al_cars_avg = df[df.city == "Almaty"]["cars_density_per_km2"].mean()
ast_cars_avg = df[df.city == "Astana"]["cars_density_per_km2"].mean()


# ===========================================================================
# 1. Headline indicators — three big-number cards
# ===========================================================================
fig1 = go.Figure()
fig1.add_trace(go.Indicator(
    mode="number",
    value=total_objects,
    number=dict(font=dict(family=SERIF, size=88, color=INK), valueformat=",.0f"),
    title=dict(text="<b>ОБЪЕКТОВ ИЗВЛЕЧЕНО</b><br><span style='font-size:13px;color:#7a756c'>"
                    f"из 20 сцен · {total_area_km2:.2f} км²</span>",
               font=dict(family=SANS, size=14, color=ACCENT)),
    domain=dict(x=[0.00, 0.32], y=[0.0, 1.0]),
))
fig1.add_trace(go.Indicator(
    mode="number",
    value=total_area_km2,
    number=dict(font=dict(family=SERIF, size=88, color=INK),
                valueformat=".2f", suffix=""),
    title=dict(text="<b>КМ² ОБЩЕЙ ПЛОЩАДИ</b><br>"
                    "<span style='font-size:13px;color:#7a756c'>"
                    f"Алматы {df[df.city=='Almaty']['aoi_area_km2'].sum():.2f} · "
                    f"Астана {df[df.city=='Astana']['aoi_area_km2'].sum():.2f}</span>",
               font=dict(family=SANS, size=14, color=ACCENT)),
    domain=dict(x=[0.34, 0.66], y=[0.0, 1.0]),
))
fig1.add_trace(go.Indicator(
    mode="number",
    value=9,
    number=dict(font=dict(family=SERIF, size=88, color=INK)),
    title=dict(text="<b>КЛАССОВ ЗДАНИЙ</b><br>"
                    "<span style='font-size:13px;color:#7a756c'>"
                    "от частного дома до индустриального</span>",
               font=dict(family=SANS, size=14, color=ACCENT)),
    domain=dict(x=[0.68, 1.00], y=[0.0, 1.0]),
))
fig1.update_layout(
    paper_bgcolor=BG, plot_bgcolor=BG,
    margin=dict(l=40, r=40, t=80, b=40),
    title=dict(text="<b>Что увидел пайплайн на 20 сценах</b>",
               font=dict(family=SERIF, size=24, color=INK), x=0.02, y=0.97),
)
save(fig1, "headline_indicators", w=1400, h=420)


# ===========================================================================
# 2. AOI composition — donut chart
# ===========================================================================
labels = [
    f"Здания  {bld_pct:.1f} %",
    f"Растительность  {veg_pct:.1f} %",
    f"Голая земля  {soil_pct:.1f} %",
    f"Дороги, вода, прочее  {other_pct:.1f} %",
]
values = [bld_pct, veg_pct, soil_pct, other_pct]
colors = [COMP["buildings"], COMP["vegetation"], COMP["soil"], COMP["other"]]

fig2 = go.Figure(go.Pie(
    labels=labels, values=values,
    hole=0.55, sort=False, direction="clockwise",
    marker=dict(colors=colors, line=dict(color=BG, width=3)),
    textfont=dict(family=SANS, size=14, color="white"),
    textposition="inside",
    textinfo="label",
    hovertemplate="<b>%{label}</b><br>%{value:.2f} %<extra></extra>",
))
fig2.update_layout(
    paper_bgcolor=BG, plot_bgcolor=BG,
    title=dict(text=f"<b>Из чего состоит AOI · {total_area_km2:.2f} км²</b>",
               font=dict(family=SERIF, size=22, color=INK), x=0.02, y=0.95),
    showlegend=False,
    margin=dict(l=40, r=40, t=80, b=40),
    annotations=[dict(
        text=f"<b style='font-size:38px;font-family:Georgia'>{total_area_km2:.2f}</b><br>"
             f"<span style='font-size:13px;color:#7a756c'>км² AOI</span>",
        x=0.5, y=0.5, showarrow=False,
        font=dict(family=SERIF, color=INK),
    )],
)
save(fig2, "aoi_composition", w=900, h=620)


# ===========================================================================
# 3. Cars per km² by scene — horizontal bar, sorted, coloured by city
# ===========================================================================
cars_df = df.sort_values("cars_density_per_km2", ascending=True)
city_colors = [ALMATY_C if c == "Almaty" else ASTANA_C for c in cars_df["city"]]

fig3 = go.Figure(go.Bar(
    x=cars_df["cars_density_per_km2"],
    y=cars_df["scene_id"],
    orientation="h",
    marker=dict(color=city_colors, line=dict(width=0)),
    text=[f"{v:.0f}" for v in cars_df["cars_density_per_km2"]],
    textposition="outside",
    textfont=dict(family=SERIF, size=12, color=INK),
    hovertemplate="<b>%{y}</b><br>%{x:.0f} машин/км²<extra></extra>",
))
# Mean reference lines
fig3.add_vline(x=al_cars_avg, line_dash="dash", line_color=ALMATY_C, line_width=1,
               annotation_text=f"Алматы avg {al_cars_avg:.0f}",
               annotation_position="top",
               annotation_font=dict(family=SANS, size=11, color=ALMATY_C))
fig3.add_vline(x=ast_cars_avg, line_dash="dash", line_color=ASTANA_C, line_width=1,
               annotation_text=f"Астана avg {ast_cars_avg:.0f}",
               annotation_position="bottom",
               annotation_font=dict(family=SANS, size=11, color=ASTANA_C))
fig3.update_layout(
    paper_bgcolor=BG, plot_bgcolor=BG,
    title=dict(text="<b>Плотность транспорта по сценам</b><br>"
                    "<span style='font-size:13px;color:#7a756c'>"
                    "машин на квадратный километр · цвет по городу</span>",
               font=dict(family=SERIF, size=22, color=INK), x=0.02, y=0.96),
    xaxis=dict(title="машин/км²", showgrid=True,
               gridcolor="#e2ddd2", zerolinecolor="#cbc4b6",
               tickfont=dict(family=SANS, size=11, color=INK_SOFT)),
    yaxis=dict(showgrid=False, tickfont=dict(family=SANS, size=11, color=INK)),
    margin=dict(l=100, r=100, t=110, b=60),
    showlegend=False,
)
save(fig3, "cars_by_scene", w=1100, h=720)


# ===========================================================================
# 4. Building class distribution — bar chart by 9 sub-classes
# ===========================================================================
BUILDING_CLASSES = {
    "house", "apartment_block", "school", "hospital", "religious",
    "civic", "commercial", "industrial", "outbuilding", "agricultural",
}
all_geo = ROOT / "outputs" / "geojson" / "all.geojson"
class_counts = None
if all_geo.exists():
    g = gpd.read_file(all_geo)
    bld_only = g[g["class"].isin(BUILDING_CLASSES)]
    if not bld_only.empty:
        class_counts = bld_only["class"].value_counts()

if class_counts is None or class_counts.empty:
    # Fallback: just house/apartment_block from CSV
    class_counts = pd.Series({
        "house": total_house,
        "apartment_block": total_apt,
        "other (school, hospital, ...)": total_bld - total_house - total_apt,
    })

# Russian labels
RU = {
    "house": "Частный дом",
    "apartment_block": "Многоквартирный",
    "school": "Школа",
    "hospital": "Больница",
    "religious": "Религиозное",
    "civic": "Общественное",
    "commercial": "Коммерческое",
    "industrial": "Индустриальное",
    "outbuilding": "Хозпостройка",
    "agricultural": "С/х",
    "building": "Прочее здание",
}

cc = class_counts.sort_values(ascending=True)
labels_ru = [RU.get(c, c) for c in cc.index]
bar_colors = [ACCENT if c in ("house", "apartment_block") else "#a89685"
              for c in cc.index]

fig4 = go.Figure(go.Bar(
    x=cc.values,
    y=labels_ru,
    orientation="h",
    marker=dict(color=bar_colors, line=dict(width=0)),
    text=[fmt_n(v) for v in cc.values],
    textposition="outside",
    textfont=dict(family=SERIF, size=13, color=INK),
    hovertemplate="<b>%{y}</b><br>%{x:,} зданий<extra></extra>",
))
fig4.update_layout(
    paper_bgcolor=BG, plot_bgcolor=BG,
    title=dict(text=f"<b>Структура {fmt_n(total_bld)} зданий по классам</b><br>"
                    "<span style='font-size:13px;color:#7a756c'>"
                    "акцент — два массовых класса; остальные классы найдены через Overture-сопоставление</span>",
               font=dict(family=SERIF, size=22, color=INK), x=0.02, y=0.96),
    xaxis=dict(title="полигонов", showgrid=True,
               gridcolor="#e2ddd2", zerolinecolor="#cbc4b6",
               tickfont=dict(family=SANS, size=11, color=INK_SOFT)),
    yaxis=dict(showgrid=False, tickfont=dict(family=SANS, size=12, color=INK)),
    margin=dict(l=180, r=80, t=110, b=60),
    showlegend=False,
)
save(fig4, "buildings_class_split", w=1100, h=540)


# ===========================================================================
# 5. Combined dashboard HTML — all four charts on one page
# ===========================================================================
dash_html = f"""<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8"><title>HackNU '26 — итог пайплайна</title>
<style>
  body {{ background: {BG}; margin: 0; padding: 32px;
         font-family: 'Helvetica Neue', Arial, sans-serif; color: {INK}; }}
  h1 {{ font-family: Georgia, serif; font-size: 30px; margin: 0 0 4px; }}
  h1 small {{ font-size: 14px; color: {INK_SOFT}; font-weight: normal; font-style: italic; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-top: 24px; }}
  .full {{ grid-column: 1 / -1; }}
  iframe {{ border: 0; width: 100%; background: {BG}; }}
  hr {{ border: 0; border-top: 1px solid #d8d3c8; margin: 14px 0; }}
</style></head>
<body>
<h1>Что увидел пайплайн на 20 сценах
    <small>· Алматы и Астана · ~12 км² городской застройки</small></h1>
<hr>
<div class="grid">
  <div class="full"><iframe src="headline_indicators.html" height="420"></iframe></div>
  <div><iframe src="aoi_composition.html"      height="620"></iframe></div>
  <div><iframe src="buildings_class_split.html" height="540"></iframe></div>
  <div class="full"><iframe src="cars_by_scene.html" height="720"></iframe></div>
</div>
</body></html>
"""
(OUT / "headline_dashboard.html").write_text(dash_html, encoding="utf-8")
print("[plotly] -> headline_dashboard.html (combined view)")

print()
print(f"[plotly] All charts saved to: {OUT.relative_to(ROOT)}/")
print("[plotly] Files: headline_indicators, aoi_composition, "
      "cars_by_scene, buildings_class_split, headline_dashboard")
