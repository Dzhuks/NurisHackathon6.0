"""Editorial-quality summary tables for the conclusion slide.

Built with matplotlib (no plotly): full control over typography, inline bars,
podium cards. Aesthetic: warm cream paper #f5f3f0, elegant serif numbers,
rust/olive accents, subtle hairline rules. Designed to look like a printed
report cover, not a spreadsheet.

Outputs (PNG, 200 DPI) in outputs/figures/:
  1. headline_totals.png    big-number magazine cover
  2. holdout_quality.png    table with inline horizontal-bar percentages
  3. city_comparison.png    Almaty vs Astana with paired horizontal bars
  4. top_scenes.png         podium-style top-3 cards per category

Run:  python scripts/make_summary_tables.py
"""
from pathlib import Path
import warnings

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, Rectangle
import pandas as pd

warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")

# --- Paths ------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
SRC_MAIN = ROOT / "outputs"
SRC_BACKUP = ROOT / "outputs_backup_resnet34_15ep"

scene_csv = SRC_MAIN / "scene_metrics.csv"
holdout_csv = SRC_MAIN / "holdout_metrics.csv"
if not scene_csv.exists():
    scene_csv = SRC_BACKUP / "scene_metrics.csv"
if not holdout_csv.exists():
    holdout_csv = SRC_BACKUP / "holdout_metrics.csv"

print(f"[tables] scene_metrics:   {scene_csv.relative_to(ROOT)}")
print(f"[tables] holdout_metrics: {holdout_csv.relative_to(ROOT)}")

df = pd.read_csv(scene_csv)
hd = pd.read_csv(holdout_csv)

OUT = ROOT / "outputs" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

# --- Editorial palette -----------------------------------------------------
BG          = "#f5f3f0"   # warm cream paper (user request)
PAPER_DARK  = "#ece8e0"   # subtle row tint
INK         = "#1a1a1a"   # near-black for primary text
INK_2       = "#3d3a35"   # body text, slightly softer
INK_SOFT    = "#7a756c"   # captions / labels
RULE        = "#cbc4b6"   # hairline rule
RULE_SOFT   = "#dfd9cc"   # very faint divider
ACCENT      = "#b8895a"   # warm terracotta (hero accent)
ACCENT_DARK = "#8a6340"   # deeper accent for highlight rows
ACCENT_SOFT = "#e6d4bb"   # accent tint
GREEN       = "#5a7a3a"   # olive (positive delta)
RED         = "#a64833"   # rust (negative delta)
ALMATY_C    = "#7d4f3e"   # mountain brown for Almaty
ASTANA_C    = "#3f6680"   # cold blue-grey for Astana

# Fonts. Didot is gorgeous for Latin/digits but lacks Cyrillic glyphs, so we
# split: SERIF = Cyrillic-safe (Georgia / PT Serif), SERIF_NUM = Didot for the
# hero numbers only. Helvetica Neue handles all sans body text.
SERIF = "PT Serif"            # Cyrillic-safe headlines
SERIF_BODY = "PT Serif"       # body italic / caption
SERIF_NUM = "Didot"           # numbers-only hero font
SANS = "Helvetica Neue"
SANS_ALT = "Optima"

plt.rcParams.update({
    "font.family": SANS,
    "axes.edgecolor": INK,
    "savefig.facecolor": BG,
    "figure.facecolor": BG,
})

# --- Drawing helpers --------------------------------------------------------

def setup_ax(ax, xlim=(0, 1), ylim=(0, 1)):
    ax.set_facecolor(BG)
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)


def spaced(text, n=2):
    """Manual letter-spacing: insert spaces between characters."""
    return (" " * n).join(list(text))


def title_block(ax, title, subtitle=None, eyebrow=None, y=0.92):
    """Magazine-style title: tiny eyebrow label + big serif title + caption."""
    if eyebrow:
        ax.text(0.0, y + 0.06, spaced(eyebrow.upper(), 2),
                fontsize=10, color=ACCENT, family=SANS,
                fontweight="bold",
                transform=ax.transAxes, ha="left", va="bottom")
    ax.text(0.0, y, title, fontsize=28, color=INK, family=SERIF,
            transform=ax.transAxes, ha="left", va="bottom",
            fontweight="normal")
    if subtitle:
        ax.text(0.0, y - 0.04, subtitle,
                fontsize=12, color=INK_SOFT, family=SERIF_BODY,
                fontstyle="italic",
                transform=ax.transAxes, ha="left", va="top")
    # Decorative double rule under the title.
    ax.plot([0.0, 1.0], [y - 0.085, y - 0.085], color=INK,
            lw=1.0, transform=ax.transAxes, clip_on=False)
    ax.plot([0.0, 0.08], [y - 0.105, y - 0.105], color=ACCENT,
            lw=2.5, transform=ax.transAxes, clip_on=False)


def hairline(ax, y, x0=0, x1=1, color=RULE_SOFT, lw=0.6):
    ax.plot([x0, x1], [y, y], color=color, lw=lw,
            transform=ax.transAxes, clip_on=False)


# ---------------------------------------------------------------------------
# 1. HEADLINE TOTALS - editorial spread: 3 hero numbers + AOI composition
#    bar + two feature blocks (buildings / cars). Tells a story instead of
#    repeating cell after cell.
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


def fmt_n(x):
    return f"{x:,}".replace(",", " ")


al_area = df[df.city == "Almaty"]["aoi_area_km2"].sum()
ast_area = df[df.city == "Astana"]["aoi_area_km2"].sum()
al_cars_avg = df[df.city == "Almaty"]["cars_density_per_km2"].mean()
ast_cars_avg = df[df.city == "Astana"]["cars_density_per_km2"].mean()
peak_cars_row = df.sort_values("cars_density_per_km2", ascending=False).iloc[0]

fig = plt.figure(figsize=(14, 9.5), facecolor=BG)
ax = fig.add_axes([0.05, 0.04, 0.90, 0.93])
setup_ax(ax)

title_block(ax, "Что увидел пайплайн на 20 сценах",
            subtitle="Алматы и Астана  ·  весна 2022  ·  ~12 км² городской застройки",
            eyebrow="HackNU \'26  ·  Итог проекта", y=0.94)

# Section 1: three monumental hero numbers
hero_y_top = 0.80
hero_y_bot = 0.62
hero_xs = [0.0, 0.36, 0.72]
heroes = [
    (fmt_n(total_objects),    "ОБЪЕКТОВ",       f"извлечено из 20 сцен  ·  ~{total_area_km2:.2f} км²"),
    (f"{total_area_km2:.2f}", "КМ² AOI",   f"Алматы {al_area:.2f}  ·  Астана {ast_area:.2f}  ·  по 10 сцен"),
    ("9",                     "КЛАССОВ ЗДАНИЙ", "от частного дома до индустриального объекта"),
]
for hx, (val, label, caption) in zip(hero_xs, heroes):
    ax.text(hx, hero_y_top, spaced(label, 1),
            fontsize=10, color=ACCENT, family=SANS, fontweight="bold",
            transform=ax.transAxes, ha="left", va="top")
    ax.text(hx, hero_y_top - 0.025, val,
            fontsize=68, color=INK, family=SERIF_NUM,
            transform=ax.transAxes, ha="left", va="top")
    ax.text(hx, hero_y_bot + 0.005, caption,
            fontsize=11, color=INK_2, family=SERIF_BODY, fontstyle="italic",
            transform=ax.transAxes, ha="left", va="bottom")

ax.plot([0, 1], [hero_y_bot - 0.01, hero_y_bot - 0.01],
        color=RULE, lw=0.6, transform=ax.transAxes)

# Section 2: AOI composition stacked bar
comp_y_top = hero_y_bot - 0.04
ax.text(0.0, comp_y_top, spaced("ИЗ ЧЕГО СОСТОИТ AOI", 1),
        fontsize=10, color=INK_SOFT, family=SANS, fontweight="bold",
        transform=ax.transAxes, ha="left", va="top")
ax.text(1.0, comp_y_top, f"{total_area_km2:.2f} км²  ·  100 %",
        fontsize=10.5, color=INK_2, family=SERIF_BODY, fontstyle="italic",
        transform=ax.transAxes, ha="right", va="top")

bar_y = comp_y_top - 0.07
bar_h = 0.07
COMP_COLORS = {
    "buildings":  "#7d4f3e",
    "vegetation": "#5a7a3a",
    "soil":       "#c9a06b",
    "other":      "#a8a09a",
}
segments = [
    ("buildings",  bld_pct,  f"Здания  {bld_pct:.1f} %",                  COMP_COLORS["buildings"]),
    ("vegetation", veg_pct,  f"Растительность  {veg_pct:.1f} %",          COMP_COLORS["vegetation"]),
    ("soil",       soil_pct, f"Голая земля  {soil_pct:.1f} %",            COMP_COLORS["soil"]),
    ("other",      other_pct,f"Дороги, вода, прочее  {other_pct:.1f} %",  COMP_COLORS["other"]),
]
x_cursor = 0.0
for key, pct_v, label, color in segments:
    w = pct_v / 100.0
    ax.add_patch(Rectangle((x_cursor, bar_y), w, bar_h,
                           transform=ax.transAxes, facecolor=color,
                           edgecolor=BG, linewidth=2, zorder=2))
    label_y = bar_y + bar_h / 2
    if w > 0.085:
        ax.text(x_cursor + w / 2, label_y, label,
                fontsize=11, color="white", family=SANS, fontweight="bold",
                transform=ax.transAxes, ha="center", va="center", zorder=3)
    else:
        ax.text(x_cursor + w / 2, bar_y - 0.025, label,
                fontsize=9.5, color=INK_2, family=SANS,
                transform=ax.transAxes, ha="center", va="top", zorder=3)
    x_cursor += w

# Section 3: two feature blocks (buildings / cars)
sec3_y_top = bar_y - 0.07
sec3_y_bot = 0.10
ax.plot([0, 1], [sec3_y_top - 0.005, sec3_y_top - 0.005],
        color=RULE, lw=0.6, transform=ax.transAxes)

card_top = sec3_y_top - 0.03
left_x = 0.0
right_x = 0.50
divider_x = 0.485
ax.plot([divider_x, divider_x], [sec3_y_bot, card_top + 0.03],
        color=RULE, lw=0.5, transform=ax.transAxes)

# Buildings block
ax.text(left_x, card_top, spaced("ЗДАНИЯ", 2),
        fontsize=10, color=ACCENT, family=SANS, fontweight="bold",
        transform=ax.transAxes, ha="left", va="top")
ax.text(left_x, card_top - 0.025, fmt_n(total_bld),
        fontsize=54, color=INK, family=SERIF_NUM,
        transform=ax.transAxes, ha="left", va="top")
ax.text(left_x + 0.20, card_top - 0.115,
        f"полигонов общей площадью {bld_area_m2/1e6:.2f} км²",
        fontsize=11, color=INK_2, family=SERIF_BODY, fontstyle="italic",
        transform=ax.transAxes, ha="left", va="top")

bld_stats_y = card_top - 0.16
ax.text(left_x, bld_stats_y, fmt_n(total_house),
        fontsize=22, color=INK, family=SERIF_NUM,
        transform=ax.transAxes, ha="left", va="top")
ax.text(left_x, bld_stats_y - 0.04, "частных домов",
        fontsize=10, color=INK_SOFT, family=SANS,
        transform=ax.transAxes, ha="left", va="top")

ax.text(left_x + 0.18, bld_stats_y, fmt_n(total_apt),
        fontsize=22, color=INK, family=SERIF_NUM,
        transform=ax.transAxes, ha="left", va="top")
ax.text(left_x + 0.18, bld_stats_y - 0.04, "многоквартирных",
        fontsize=10, color=INK_SOFT, family=SANS,
        transform=ax.transAxes, ha="left", va="top")

ax.text(left_x + 0.36, bld_stats_y, "+7",
        fontsize=22, color=INK, family=SERIF_NUM,
        transform=ax.transAxes, ha="left", va="top")
ax.text(left_x + 0.36, bld_stats_y - 0.04, "других классов",
        fontsize=10, color=INK_SOFT, family=SANS,
        transform=ax.transAxes, ha="left", va="top")

# Cars block
ax.text(right_x, card_top, spaced("АВТОМОБИЛИ", 2),
        fontsize=10, color=ACCENT, family=SANS, fontweight="bold",
        transform=ax.transAxes, ha="left", va="top")
ax.text(right_x, card_top - 0.025, fmt_n(total_cars),
        fontsize=54, color=INK, family=SERIF_NUM,
        transform=ax.transAxes, ha="left", va="top")
ax.text(right_x + 0.20, card_top - 0.115,
        f"машин на снапшоте, ~{total_cars/total_area_km2:.0f} на км²",
        fontsize=11, color=INK_2, family=SERIF_BODY, fontstyle="italic",
        transform=ax.transAxes, ha="left", va="top")

ax.text(right_x, bld_stats_y, f"{al_cars_avg:.0f}",
        fontsize=22, color=ALMATY_C, family=SERIF_NUM,
        transform=ax.transAxes, ha="left", va="top")
ax.text(right_x, bld_stats_y - 0.04, "Алматы (avg/км²)",
        fontsize=10, color=INK_SOFT, family=SANS,
        transform=ax.transAxes, ha="left", va="top")

ax.text(right_x + 0.18, bld_stats_y, f"{ast_cars_avg:.0f}",
        fontsize=22, color=ASTANA_C, family=SERIF_NUM,
        transform=ax.transAxes, ha="left", va="top")
ax.text(right_x + 0.18, bld_stats_y - 0.04, "Астана (avg/км²)",
        fontsize=10, color=INK_SOFT, family=SANS,
        transform=ax.transAxes, ha="left", va="top")

ax.text(right_x + 0.36, bld_stats_y, f"{peak_cars_row['cars_density_per_km2']:.0f}",
        fontsize=22, color=INK, family=SERIF_NUM,
        transform=ax.transAxes, ha="left", va="top")
ax.text(right_x + 0.36, bld_stats_y - 0.04,
        f"пик ({peak_cars_row['scene_id']})",
        fontsize=10, color=INK_SOFT, family=SANS,
        transform=ax.transAxes, ha="left", va="top")

# Footer
ax.plot([0, 1], [0.045, 0.045], color=INK, lw=1.0, transform=ax.transAxes)
ax.text(0.0, 0.012, "Источник эталона: Overture Maps Foundation  ·  модель: U-Net + ResNet-34, 40 эпох",
        fontsize=9.5, color=INK_SOFT, family=SANS, fontstyle="italic",
        transform=ax.transAxes, ha="left", va="bottom")
ax.text(1.0, 0.012, "outputs/figures/headline_totals.png",
        fontsize=9, color=INK_SOFT, family=SANS,
        transform=ax.transAxes, ha="right", va="bottom")

fig.savefig(OUT / "headline_totals.png", dpi=200, facecolor=BG,
            bbox_inches="tight", pad_inches=0.25)
plt.close(fig)
print("[tables] -> headline_totals.png")


# ---------------------------------------------------------------------------
# 2. HOLDOUT QUALITY - elegant table with inline horizontal bars
# ---------------------------------------------------------------------------
hd2 = hd.copy()
agg_mask = hd2["scene_id"] == "AGGREGATE"
ordered = pd.concat([hd2[~agg_mask], hd2[agg_mask]], ignore_index=True)
agg_idx = len(ordered) - 1 if agg_mask.any() else None
n_rows = len(ordered)

fig = plt.figure(figsize=(13, 7.2), facecolor=BG)
ax = fig.add_axes([0.05, 0.04, 0.90, 0.92])
setup_ax(ax)

title_block(ax, "Качество модели на hold-out",
            subtitle="4 сцены, метки Overture полностью скрыты от модели  ·  ИТОГО — взвешенно по объектам",
            eyebrow="Honest test  ·  никакой утечки", y=0.90)

# Column layout (in axes fraction):
# Scene | GT | Pred | TP | Precision-bar | Recall-bar | F1-bar | Pixel F1 | Pixel Acc
col_x = [0.000, 0.115, 0.190, 0.260, 0.335, 0.555, 0.770, 0.895, 0.965]
col_align = ["left", "right", "right", "right", "left", "left", "left", "right", "right"]
headers = ["Сцена", "GT", "Pred", "TP", "Precision", "Recall", "F1", "Px F1", "Px Acc"]

header_y = 0.74
ax.plot([0, 1], [header_y + 0.02, header_y + 0.02], color=INK, lw=0.8,
        transform=ax.transAxes)
for x, h, al in zip(col_x, headers, col_align):
    ax.text(x, header_y + 0.005, spaced(h.upper(), 1),
            fontsize=10, color=INK_SOFT, family=SANS, fontweight="bold",
            transform=ax.transAxes, ha=al, va="top")
ax.plot([0, 1], [header_y - 0.02, header_y - 0.02], color=RULE, lw=0.6,
        transform=ax.transAxes)

# Rows
row_top = header_y - 0.05
row_h = 0.105
for i, r in ordered.iterrows():
    is_agg = (i == agg_idx)
    y_top = row_top - i * row_h
    y_mid = y_top - row_h / 2 + 0.005
    y_bot = y_top - row_h

    # Background highlight for AGGREGATE
    if is_agg:
        rect = Rectangle((0, y_bot - 0.005), 1, row_h, transform=ax.transAxes,
                         facecolor=ACCENT_SOFT, edgecolor="none", zorder=0)
        ax.add_patch(rect)
        # Left accent bar
        ax.add_patch(Rectangle((-0.005, y_bot - 0.005), 0.005, row_h,
                               transform=ax.transAxes, facecolor=ACCENT_DARK,
                               edgecolor="none", zorder=1))

    sid = "ИТОГО" if is_agg else str(r["scene_id"])  # short label avoids overlap
    weight = "bold" if is_agg else "normal"
    family = SANS if is_agg else SERIF_BODY
    color = INK if is_agg else INK_2

    # Scene name
    ax.text(col_x[0], y_mid, sid, fontsize=13.5,
            color=color, family=family, fontweight=weight,
            transform=ax.transAxes, ha=col_align[0], va="center")

    # Counts
    for ci, key in [(1, "n_gt"), (2, "n_pred"), (3, "tp_gt")]:
        ax.text(col_x[ci], y_mid, fmt_n(int(r[key])),
                fontsize=13, color=color, family=SERIF_BODY,
                fontweight=weight,
                transform=ax.transAxes, ha=col_align[ci], va="center")

    # Inline bars for Precision, Recall, F1
    bar_specs = [
        (4, "precision", 0.20, ACCENT),
        (5, "recall",    0.20, ASTANA_C),
        (6, "f1",        0.115, ACCENT_DARK),
    ]
    for ci, key, max_w, color_b in bar_specs:
        v = r[key]
        if pd.isna(v):
            continue
        x0 = col_x[ci]
        bw = max_w * v
        # Faint full track
        ax.add_patch(Rectangle((x0, y_mid - 0.018), max_w, 0.005,
                               transform=ax.transAxes, facecolor=RULE_SOFT,
                               edgecolor="none", zorder=1))
        # Filled bar
        ax.add_patch(Rectangle((x0, y_mid - 0.022), bw, 0.013,
                               transform=ax.transAxes, facecolor=color_b,
                               edgecolor="none", zorder=2,
                               alpha=1.0 if is_agg else 0.85))
        # Number above bar
        ax.text(x0, y_mid + 0.012, f"{100 * v:.1f}%",
                fontsize=12.5, color=color, family=SERIF_BODY,
                fontweight=weight,
                transform=ax.transAxes, ha="left", va="center")

    # Pixel metrics (only present for non-AGGREGATE)
    for ci, key in [(7, "pixel_f1"), (8, "pixel_accuracy")]:
        v = r[key]
        text = f"{100 * v:.1f}%" if pd.notna(v) else "—"
        ax.text(col_x[ci], y_mid, text,
                fontsize=12.5,
                color=INK_SOFT if pd.isna(v) else color,
                family=SERIF_BODY, fontweight=weight,
                transform=ax.transAxes, ha=col_align[ci], va="center")

    # Hairline below row
    if not is_agg:
        ax.plot([0, 1], [y_bot, y_bot], color=RULE_SOFT, lw=0.5,
                transform=ax.transAxes)

# Footer
ax.plot([0, 1], [0.05, 0.05], color=INK, lw=1.0, transform=ax.transAxes)
ax.text(0.0, 0.012, "Object-level any-intersection: TP_pred = предикт пересёк ≥1 GT, TP_gt = GT поймана ≥1 предиктом.  ",
        fontsize=10, color=INK_SOFT, family=SANS, fontstyle="italic",
        transform=ax.transAxes, ha="left", va="bottom")

fig.savefig(OUT / "holdout_quality.png", dpi=200, facecolor=BG,
            bbox_inches="tight", pad_inches=0.25)
plt.close(fig)
print("[tables] -> holdout_quality.png")


# ---------------------------------------------------------------------------
# 3. CITY COMPARISON - paired horizontal bars per metric
# ---------------------------------------------------------------------------
def city_summary(city):
    s = df[df.city == city]
    cs = (s.buildings_share_of_aoi_pct - s.vegetation_share_pct).mean()
    return {
        "scenes": len(s),
        "area": s.aoi_area_km2.sum(),
        "bld_total": int(s.n_buildings_total.sum()),
        "house": int(s.n_house.sum()),
        "apt": int(s.n_apartment_block.sum()),
        "cars": int(s.n_cars.sum()),
        "cars_per_km2": s.cars_density_per_km2.mean(),
        "bld_share": s.buildings_share_of_aoi_pct.mean(),
        "veg": s.vegetation_share_pct.mean(),
        "soil": s.bare_soil_share_pct.mean(),
        "concrete": cs,
    }

al = city_summary("Almaty")
ast = city_summary("Astana")

# Each row: (label, almaty_value, astana_value, formatter, lower_is_better, unit)
# Use real Unicode minus (U+2212) instead of ASCII hyphen-minus.
# PT Serif renders U+2212 correctly; ASCII "-" rendered as a tofu square here.
def _minus(s): return s.replace("-", "−")
def fmt_int(x): return _minus(fmt_n(int(round(x))))
def fmt_1(x):   return _minus(f"{x:.1f}")
def fmt_2(x):   return _minus(f"{x:.2f}")

rows = [
    ("Зданий извлечено",         al["bld_total"],     ast["bld_total"],     fmt_int, False, ""),
    ("Машин извлечено",          al["cars"],          ast["cars"],          fmt_int, False, ""),
    ("Машин/км² (среднее)",      al["cars_per_km2"],  ast["cars_per_km2"],  fmt_int, False, ""),
    ("Доля зданий, %",           al["bld_share"],     ast["bld_share"],     fmt_1,   False, " %"),
    ("Растительность, %",        al["veg"],           ast["veg"],           fmt_1,   False, " %"),
    ("Голая земля, %",           al["soil"],          ast["soil"],          fmt_1,   False, " %"),
    ("Concrete-score (avg)",     al["concrete"],      ast["concrete"],      fmt_2,   True,  ""),
]

fig = plt.figure(figsize=(13, 8.5), facecolor=BG)
ax = fig.add_axes([0.05, 0.04, 0.90, 0.92])
setup_ax(ax)

title_block(ax, "Алматы vs Астана: что показал пайплайн",
            subtitle="одинаковая модель и пороги  ·  10 сцен × 10 сцен  ·  площадь почти идентична (6.08 км² vs 6.09 км²)",
            eyebrow="Сравнение городов", y=0.92)

# Bar geometry (used by both header and rows)
bar_x_a = 0.27   # Almaty bar start
bar_x_z = 0.63   # Astana bar start (wider gap so 4-digit numbers don't crowd)
bar_max = 0.22   # max bar width

# Column header for each city
col_label_y = 0.78
ax.add_patch(Rectangle((bar_x_a - 0.005, col_label_y - 0.005), 0.025, 0.025,
                       transform=ax.transAxes, facecolor=ALMATY_C, edgecolor="none"))
ax.text(bar_x_a + 0.030, col_label_y + 0.008, spaced("АЛМАТЫ", 2), fontsize=11, color=INK,
        family=SANS, fontweight="bold",
        transform=ax.transAxes, ha="left", va="center")

ax.add_patch(Rectangle((bar_x_z - 0.005, col_label_y - 0.005), 0.025, 0.025,
                       transform=ax.transAxes, facecolor=ASTANA_C, edgecolor="none"))
ax.text(bar_x_z + 0.030, col_label_y + 0.008, spaced("АСТАНА", 2), fontsize=11, color=INK,
        family=SANS, fontweight="bold",
        transform=ax.transAxes, ha="left", va="center")

ax.text(0.0, col_label_y + 0.008, spaced("МЕТРИКА", 1), fontsize=10, color=INK_SOFT,
        family=SANS, fontweight="bold",
        transform=ax.transAxes, ha="left", va="center")
ax.text(1.0, col_label_y + 0.008, "Δ", fontsize=12, color=INK_SOFT,
        family=SANS, fontweight="bold",
        transform=ax.transAxes, ha="right", va="center")

ax.plot([0, 1], [col_label_y - 0.02, col_label_y - 0.02], color=INK, lw=0.8,
        transform=ax.transAxes)

# Rows: paired bars
n = len(rows)
top = 0.70
row_h = 0.085

for i, (label, va_, vb, fmt, lower_better, unit) in enumerate(rows):
    y_center = top - i * row_h
    y_top = y_center + row_h * 0.4
    y_bot = y_center - row_h * 0.4

    vmax = max(abs(va_), abs(vb)) or 1.0
    bw_a = bar_max * (abs(va_) / vmax)
    bw_z = bar_max * (abs(vb) / vmax)

    # Decide winner direction (which is "better")
    if lower_better:
        a_better = va_ < vb
    else:
        a_better = va_ > vb

    # Faint background bars
    ax.add_patch(Rectangle((bar_x_a, y_center - 0.009), bar_max, 0.018,
                           transform=ax.transAxes, facecolor=PAPER_DARK,
                           edgecolor="none", zorder=1))
    ax.add_patch(Rectangle((bar_x_z, y_center - 0.009), bar_max, 0.018,
                           transform=ax.transAxes, facecolor=PAPER_DARK,
                           edgecolor="none", zorder=1))

    # Filled bars
    a_color = ALMATY_C if a_better else ALMATY_C
    z_color = ASTANA_C if not a_better else ASTANA_C
    a_alpha = 1.0 if a_better else 0.55
    z_alpha = 1.0 if not a_better else 0.55

    ax.add_patch(Rectangle((bar_x_a, y_center - 0.009), bw_a, 0.018,
                           transform=ax.transAxes, facecolor=a_color,
                           alpha=a_alpha, edgecolor="none", zorder=2))
    ax.add_patch(Rectangle((bar_x_z, y_center - 0.009), bw_z, 0.018,
                           transform=ax.transAxes, facecolor=z_color,
                           alpha=z_alpha, edgecolor="none", zorder=2))

    # Numbers next to bars (right-aligned at bar end)
    ax.text(bar_x_a + bar_max + 0.005, y_center, fmt(va_) + unit,
            fontsize=13, color=INK, family=SERIF_BODY, fontweight="bold",
            transform=ax.transAxes, ha="left", va="center")
    ax.text(bar_x_z + bar_max + 0.005, y_center, fmt(vb) + unit,
            fontsize=13, color=INK, family=SERIF_BODY, fontweight="bold",
            transform=ax.transAxes, ha="left", va="center")

    # Label
    ax.text(0.0, y_center, label,
            fontsize=13, color=INK_2, family=SERIF_BODY,
            transform=ax.transAxes, ha="left", va="center")

    # Delta arrow
    delta = va_ - vb
    arrow = "+" if delta > 0 else ("−" if delta < 0 else "·")
    delta_color = (GREEN if (delta > 0 and not lower_better) or (delta < 0 and lower_better)
                   else RED if delta != 0 else INK_SOFT)
    ax.text(1.0, y_center, f"{arrow} {abs(delta):.1f}" if abs(delta) >= 1 else f"{arrow} {abs(delta):.2f}",
            fontsize=12, color=delta_color, family=SANS, fontweight="bold",
            transform=ax.transAxes, ha="right", va="center")

    # Hairline below row
    if i < n - 1:
        ax.plot([0, 1], [y_bot - 0.005, y_bot - 0.005],
                color=RULE_SOFT, lw=0.4, transform=ax.transAxes)

# Footer rule + insight
ax.plot([0, 1], [0.06, 0.06], color=INK, lw=1.0, transform=ax.transAxes)
ax.text(0.0, 0.012,
        "Главное:  Алматы автомобилизована в 1.8× плотнее Астаны при сопоставимой зелени  ·  "
        "Астана компенсирует пыльными пустырями (голая земля 13.9 % vs 4.1 %)",
        fontsize=10, color=INK_SOFT, family=SERIF_BODY, fontstyle="italic",
        transform=ax.transAxes, ha="left", va="bottom")

fig.savefig(OUT / "city_comparison.png", dpi=200, facecolor=BG,
            bbox_inches="tight", pad_inches=0.25)
plt.close(fig)
print("[tables] -> city_comparison.png")


# ---------------------------------------------------------------------------
# 4. TOP SCENES - podium-style top-3 cards per category
# ---------------------------------------------------------------------------
df = df.copy()
df["concrete_score"] = df["buildings_share_of_aoi_pct"] - df["vegetation_share_pct"]
df["bld_density"] = df["n_buildings_total"] / df["aoi_area_km2"]


def topN(by, n=3, ascending=False, fmt=lambda x: f"{x:.0f}"):
    s = df.sort_values(by, ascending=ascending).head(n)
    return [(r["scene_id"], r["city"], fmt(r[by])) for _, r in s.iterrows()]


categories = [
    ("ТРАФИК", "Машин на квадратный километр",
     topN("cars_density_per_km2", fmt=lambda x: f"{x:.0f}")),
    ("ПЛОТНОСТЬ ЗАСТРОЙКИ", "Зданий на квадратный километр",
     topN("bld_density", fmt=lambda x: f"{x:.0f}")),
    ("ОЗЕЛЕНЁННОСТЬ", "Доля растительности",
     topN("vegetation_share_pct", fmt=lambda x: f"{x:.1f}%")),
    ("БЕТОННАЯ ЗАСТРОЙКА", "Concrete-score: % зданий минус % зелени",
     topN("concrete_score", fmt=lambda x: _minus(f"{x:+.1f}"))),
    ("ЗЕЛЁНЫЙ ПОЯС", "Самый отрицательный concrete-score",
     topN("concrete_score", ascending=True, fmt=lambda x: _minus(f"{x:+.1f}"))),
]

fig = plt.figure(figsize=(13, 9.2), facecolor=BG)
ax = fig.add_axes([0.04, 0.04, 0.92, 0.92])
setup_ax(ax)

title_block(ax, "Топ-3 сцены по ключевым метрикам",
            subtitle="лидер каждой категории  ·  цвет рамки кодирует город",
            eyebrow="Where to look first", y=0.93)

# Card layout
n_cats = len(categories)
top = 0.77
cat_h = 0.135
card_x = [0.30, 0.535, 0.770]
card_w = [0.215, 0.215, 0.215]
card_h = 0.105
medal_color = [ACCENT_DARK, "#9c8765", "#6f6253"]  # gold, silver, bronze tones
medal_label = ["1", "2", "3"]

for ci, (eyebrow, label, top3) in enumerate(categories):
    y_center = top - ci * cat_h
    y_top = y_center + cat_h * 0.45
    y_bot = y_center - cat_h * 0.45

    # Category eyebrow + label on the left
    ax.text(0.0, y_center + 0.018, spaced(eyebrow, 2),
            fontsize=10, color=ACCENT, family=SANS, fontweight="bold",
            transform=ax.transAxes, ha="left", va="center")
    ax.text(0.0, y_center - 0.012, label,
            fontsize=12.5, color=INK_2, family=SERIF_BODY, fontstyle="italic",
            transform=ax.transAxes, ha="left", va="center")

    for rank, (sid, city, val) in enumerate(top3):
        cx = card_x[rank]
        cy = y_center - card_h / 2
        city_color = ALMATY_C if city == "Almaty" else ASTANA_C
        is_first = rank == 0

        # Card background (slightly tinted for #1)
        card_bg = ACCENT_SOFT if is_first else BG
        rect = FancyBboxPatch((cx, cy), card_w[rank], card_h,
                              transform=ax.transAxes,
                              boxstyle="round,pad=0.005,rounding_size=0.008",
                              facecolor=card_bg, edgecolor=RULE,
                              linewidth=0.8, zorder=1)
        ax.add_patch(rect)
        # Left accent bar in city color
        ax.add_patch(Rectangle((cx, cy), 0.005, card_h,
                               transform=ax.transAxes,
                               facecolor=city_color, edgecolor="none", zorder=2))

        # Rank number (huge, Didot for digits)
        ax.text(cx + 0.022, cy + card_h * 0.55, medal_label[rank],
                fontsize=34 if is_first else 28,
                color=medal_color[rank], family=SERIF_NUM, fontweight="normal",
                transform=ax.transAxes, ha="left", va="center", zorder=3)
        # Scene ID
        ax.text(cx + 0.07, cy + card_h * 0.70, sid,
                fontsize=14 if is_first else 13,
                color=INK, family=SANS, fontweight="bold",
                transform=ax.transAxes, ha="left", va="center", zorder=3)
        # City small caption
        ax.text(cx + 0.07, cy + card_h * 0.42, spaced(city, 1),
                fontsize=10, color=INK_SOFT, family=SANS,
                transform=ax.transAxes, ha="left", va="center", zorder=3)
        # Value (right-aligned, Didot for digits)
        ax.text(cx + card_w[rank] - 0.012, cy + card_h * 0.22, val,
                fontsize=17 if is_first else 15,
                color=INK, family=SERIF_NUM, fontweight="normal",
                transform=ax.transAxes, ha="right", va="center", zorder=3)

    # Hairline between categories
    if ci < n_cats - 1:
        ax.plot([0, 1], [y_bot - 0.008, y_bot - 0.008],
                color=RULE_SOFT, lw=0.5, transform=ax.transAxes)

# Footer
ax.plot([0, 1], [0.04, 0.04], color=INK, lw=1.0, transform=ax.transAxes)
# City legend
lx, ly = 0.0, 0.012
ax.add_patch(Rectangle((lx, ly + 0.002), 0.018, 0.012,
                       transform=ax.transAxes, facecolor=ALMATY_C, edgecolor="none"))
ax.text(lx + 0.025, ly + 0.008, "Алматы",
        fontsize=10, color=INK_2, family=SANS,
        transform=ax.transAxes, ha="left", va="center")
ax.add_patch(Rectangle((lx + 0.085, ly + 0.002), 0.018, 0.012,
                       transform=ax.transAxes, facecolor=ASTANA_C, edgecolor="none"))
ax.text(lx + 0.110, ly + 0.008, "Астана",
        fontsize=10, color=INK_2, family=SANS,
        transform=ax.transAxes, ha="left", va="center")

fig.savefig(OUT / "top_scenes.png", dpi=200, facecolor=BG,
            bbox_inches="tight", pad_inches=0.25)
plt.close(fig)
print("[tables] -> top_scenes.png")


print()
print(f"[tables] All 4 tables saved to: {OUT.relative_to(ROOT)}/")
print("[tables] Files: headline_totals, holdout_quality, city_comparison, top_scenes")
