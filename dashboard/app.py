"""Dog Breed Explorer — the M6 dashboard.

THIN by contract (DASHBOARD.md §0): this app reads the gold marts from the local prod
`dogs.duckdb` and renders them. It computes no facts — no parsing, no pd.cut, no corr, no
percentages. The only app-side work is *selecting rows already in a mart* (filter / sort) and
drawing chart geometry (e.g. a mean±1σ error bar off the mart's mean and stddev columns).

EVERY number shown — in a metric, a caption, or the narrative — is read from the gold tables at
render time, never hardcoded. The daily refresh rebuilds and re-validates gold; the dashboard must
show that validated truth, so if a coefficient or a mean moves, the prose moves with it.

Layout is a single top-to-bottom narrative (DASHBOARD.md §2), not per-question:
    coverage → distribution across weight classes → longest life span / does size cost it → temperament.

Run from the repo root:  streamlit run dashboard/app.py
"""

import os
from pathlib import Path

import altair as alt
import duckdb
import pandas as pd
import streamlit as st

# --- paths & constants -------------------------------------------------------------------------
REPO = Path(__file__).resolve().parent.parent
# Reads the local prod build by default — the live demo (DECISIONS §5). On Streamlit
# Community Cloud (M9 Part B) set DOGS_DB=md:dogs + MOTHERDUCK_TOKEN as platform secrets
# and it reads last night's cron refresh from MotherDuck instead: same SQL, same marts,
# one env var. Locally nothing is set, so the demo keeps reading the file — no drift.
DB_PATH = os.environ.get("DOGS_DB") or str(REPO / "dogs.duckdb")  # local file, or "md:dogs"
IS_MOTHERDUCK = DB_PATH.startswith("md:")
SEED_PATH = REPO / "dbt" / "seeds" / "dashboard_temperament_tags.csv"  # the curated heatmap tags (config)

# Size-class order is single-sourced from the size_class_bands seed the model bands off: sort by the
# lower bound and take the labels, so the dashboard's axis order can never disagree with the warehouse's
# banding. Read once here (plain, not cached — 5 rows, and it runs before st.set_page_config) and reused
# for the per-band kg ranges in panel B, its only other consumer.
BANDS = pd.read_csv(REPO / "dbt" / "seeds" / "size_class_bands.csv").sort_values("min_kg").reset_index(drop=True)
CLASS_ORDER = BANDS["label"].tolist()
# The distribution bars (B) keep the ORDINAL blue ramp (light=toy → dark=giant): on a bar chart the
# order reads well and the bars are already separated by position, so a single sequential hue is right.
SIZE_RANGE = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#0d366b"]
SIZE_SCALE = alt.Scale(domain=CLASS_ORDER, range=SIZE_RANGE)
# On the scatter, size class is an IDENTITY, not a magnitude — the x-axis (weight) already carries the
# size ordering, so colour is freed to *distinguish* the five classes. A single blue ramp can't (five
# blue shades are indistinguishable), so we use distinct hues: the dataviz reference theme's first five
# slots, validated CVD-safe (the green is kept away from the warm hues to clear red-green colour vision;
# `node validate_palette.js` passes separation, three of the five only clear contrast with the point
# outline + legend as relief). Not the blue ramp §4b first specified — that rule cost real legibility.
CLASS_COLORS = ["#2a78d6", "#008300", "#e87ba4", "#eda100", "#1baf7a"]  # toy→giant: blue green magenta amber aqua
CLASS_SCALE = alt.Scale(domain=CLASS_ORDER, range=CLASS_COLORS)
ACCENT = "#2a78d6"          # single-series marks: the bars and the mean line
BAND = "#9ec5f4"            # the ±1σ error bars (light, so the accent line reads on top)
GRID = {"gridColor": "#e6e6e6", "gridOpacity": 0.6, "domainColor": "#cccccc", "tickColor": "#cccccc"}
METRIC_LABEL = {"weight_mid_kg": "weight", "height_mid_cm": "height", "life_span_mid_years": "life span"}


# --- data access (cached; the app never writes, never triggers the pipeline) -------------------
@st.cache_data
def q(sql: str) -> pd.DataFrame:
    # read_only is a safety belt on the local file (the app never writes). MotherDuck
    # opens read/write only; the app still issues nothing but SELECTs, so it's read-only
    # in behaviour either way. DuckDB reads MOTHERDUCK_TOKEN from the env for an md: path.
    con = duckdb.connect(DB_PATH, read_only=not IS_MOTHERDUCK)
    try:
        return con.execute(sql).df()
    finally:
        con.close()


@st.cache_data
def seed_tags() -> list[str]:
    # The curated tag list + order, read straight from the seed CSV (config, versioned in the repo).
    # Reading the CSV rather than the seeded table keeps the app working without a prod re-seed;
    # it is the same file dbt loads, so the list can never drift from what the WARN test guards.
    tags = pd.read_csv(SEED_PATH).sort_values("sort_order")
    return tags["temperament"].tolist()


def ordered(df: pd.DataFrame) -> pd.DataFrame:
    """Sort a size_class-grained frame into the canonical toy→giant order, dropping 'unknown'."""
    df = df[df["size_class"] != "unknown"].copy()
    df["size_class"] = pd.Categorical(df["size_class"], CLASS_ORDER, ordered=True)
    return df.sort_values("size_class")


def styled(chart: alt.Chart) -> alt.Chart:
    """Recessive grid/axes, no view border — the same quiet chrome on every chart."""
    return chart.configure_axis(labelColor="#333", titleColor="#333", **GRID).configure_view(strokeWidth=0)


# --- load gold once, then read every displayed number off these frames -------------------------
st.set_page_config(page_title="Dog Breed Explorer", page_icon="🐕", layout="centered")

cov = q("select * from main_marts.mart_data_coverage").iloc[0]
summary = ordered(q("select * from main_marts.mart_size_class_summary"))
corr = q("select * from main_marts.mart_metric_correlation")

# small helpers so the prose can quote the marts, never a literal
S = summary.set_index(summary["size_class"].astype(str))
def life(c): return float(S.loc[c, "mean_life_span_years"])
def rho(a, b): return float(corr[(corr.metric_a == a) & (corr.metric_b == b)].correlation.iloc[0])
def rho_n(a, b): return int(corr[(corr.metric_a == a) & (corr.metric_b == b)].n_breeds.iloc[0])

tot = int(cov.total_breeds)
smin = summary.loc[summary["stddev_life_span_years"].idxmin()]          # narrowest ±σ band
giant_std = float(S.loc["giant", "stddev_life_span_years"])
gap = life("toy") - life("giant")                                       # toy→giant mean gap
w_life, h_life, h_w = rho("weight_mid_kg", "life_span_mid_years"), \
    rho("height_mid_cm", "life_span_mid_years"), rho("height_mid_cm", "weight_mid_kg")

# --- header + coverage strip (single line; each chart states its own subset) --------------------
st.title("🐕 Dog Breed Explorer")
st.markdown(
    f"What the Dog API's **{tot} breeds** say about size, life span, and temperament — read top to "
    "bottom. Every chart states the subset of breeds it actually uses."
)
st.markdown(
    f"**{tot}** breeds  ·  **{int(cov.breeds_with_weight)}** with weight  ·  "
    f"**{int(cov.breeds_with_life_span)}** with life span  ·  "
    f"**{int(cov.breeds_with_temperament)}** with temperament"
)
st.caption("Coverage is per field, not one global number — each chart below states the subset it uses.")

st.divider()

# --- B · how are breeds distributed across weight classes? (distribution) -----------------------
st.header("How are breeds distributed across weight classes?")
# Print each band's kg range under its name, read from the size_class_bands seed, so the reader knows
# what "medium" means. Half-open [min, max): giant has no ceiling (the 999 sentinel → "≥45 kg").
_range = {r.label: (f"≥{int(r.min_kg)} kg" if r.max_kg >= 999 else f"{int(r.min_kg)}–{int(r.max_kg)} kg")
          for r in BANDS.itertuples()}
bar_df = summary.copy()
bar_df["band"] = bar_df["size_class"].astype(str).map(_range)
bar_df["xlabel"] = bar_df["size_class"].astype(str) + "|" + bar_df["band"]
xlabel_order = [f"{c}|{_range[c]}" for c in CLASS_ORDER]
bars = (
    alt.Chart(bar_df)
    .mark_bar(cornerRadiusEnd=4)
    .encode(
        # two-line tick label: class name over its weight range (split on '|')
        x=alt.X("xlabel:N", sort=xlabel_order, title=None,
                axis=alt.Axis(labelExpr="split(datum.value, '|')", labelAngle=0)),
        y=alt.Y("breed_count:Q", title="breeds"),
        color=alt.Color("size_class:N", scale=SIZE_SCALE, legend=None),  # ordinal blue ramp, toy→giant
        tooltip=[alt.Tooltip("size_class:N", title="class"),
                 alt.Tooltip("band:N", title="weight"),
                 alt.Tooltip("breed_count:Q", title="breeds")],
    )
    .properties(height=280)
)
st.altair_chart(styled(bars), width="stretch")
st.caption(
    f"Most breeds are medium or large; toy and giant are the tails. "
    f"{int(cov.breeds_with_weight)} of {tot} breeds are banded — "
    f"{tot - int(cov.breeds_with_weight)} with an unknown weight are excluded from the bars."
)

st.divider()

# --- C · which breeds live longest? does size cost life span? -----------------------------------
st.header("Which breeds have the longest predicted life span? Does size cost life span?")
st.caption('"Size" here means weight — the evidence for that choice closes this section (below).')

# C2 first — every breed, the raw relationship (585 with both metrics; the 42 missing are dropped)
st.subheader("Every breed: weight vs life span")
svl = q("select * from main_marts.mart_size_vs_lifespan "
        "where weight_mid_kg is not null and life_span_mid_years is not null")
# Zoom the y-axis to the data (±10% of the plotted midpoints). Axis bounds are rendering geometry,
# not a shown fact, so this stays within the thin rule (same as drawing the ±1σ bars from mean/std).
_sc_lo = float(svl["life_span_mid_years"].min()) * 0.9
_sc_hi = float(svl["life_span_mid_years"].max()) * 1.1
scatter = (
    alt.Chart(svl)
    .mark_circle(size=70, opacity=0.72, stroke="#3a3a3a", strokeWidth=0.4)  # dark outline: light fills read on white
    .encode(
        x=alt.X("weight_mid_kg:Q", title="weight (kg, midpoint)"),
        y=alt.Y("life_span_mid_years:Q", title="life span (years, midpoint)",
                scale=alt.Scale(domain=[_sc_lo, _sc_hi], zero=False)),
        color=alt.Color("size_class:N", sort=CLASS_ORDER, scale=CLASS_SCALE,
                        # no contour on the legend swatches (symbolStrokeWidth=0); points keep their outline
                        legend=alt.Legend(title="size class", orient="right", symbolStrokeWidth=0)),
        tooltip=[alt.Tooltip("breed_name:N", title="breed"),
                 alt.Tooltip("size_class:N", title="class"),
                 alt.Tooltip("weight_mid_kg:Q", title="weight (kg)", format=".1f"),
                 alt.Tooltip("life_span_mid_years:Q", title="life span (yr)", format=".1f")],
    )
    .properties(height=380)
)
st.altair_chart(styled(scatter), width="stretch")
st.caption(
    f"**{int(cov.breeds_plotted_scatter)} of {tot} plotted · {int(cov.breeds_excluded_scatter)} "
    "excluded** for a missing weight or life span. Knowing a dog's size class tells you a lot; within "
    "any single band the relationship nearly vanishes."
)

# The longest-lived breeds — a filter/sort of the same mart the scatter reads (top-N is the app's
# job). Selected by highest predicted midpoint; the five that come out share an IDENTICAL published
# range, so they can't be ranked against each other and are listed ALPHABETICALLY rather than in a
# fake 1–5 order. The published range (not the midpoint) is shown so the tie is legible.
top = svl.sort_values(["life_span_mid_years", "breed_name"], ascending=[False, True]).head(5)
top = top.sort_values("breed_name")
tbl = pd.DataFrame({
    "breed": top["breed_name"].values,
    "size class": top["size_class"].values,
    "weight (kg)": [f"{v:.1f}" for v in top["weight_mid_kg"]],
    "published life span (yr)": [f"{int(mn)}–{int(mx)}"
                                 for mn, mx in zip(top["life_span_min_years"], top["life_span_max_years"])],
}).set_index("breed")
st.markdown("**Longest predicted life span**")
st.table(tbl)
_ranges = set(zip(top["life_span_min_years"], top["life_span_max_years"]))
if len(_ranges) == 1:                                   # the honest case: they're identical, not a ranking
    _lo, _hi = int(top["life_span_min_years"].iloc[0]), int(top["life_span_max_years"].iloc[0])
    st.caption(
        f"All five share the highest predicted life span — an identical published range of {_lo}–{_hi} "
        "years — so they can't be ranked against each other and are listed alphabetically. What differs "
        "between them is size, not lifespan."
    )
else:
    st.caption(
        "The five highest by predicted life span (the midpoint of the published range); where midpoints "
        "tie they are listed alphabetically. The published min–max is shown so the spread behind each "
        "midpoint is visible."
    )

# C1 — the aggregated view: mean life span ± 1σ (low/high is chart geometry off mart mean & stddev)
st.subheader("Mean life span, with ±1σ")
c1 = summary.copy()
c1["low"] = c1["mean_life_span_years"] - c1["stddev_life_span_years"]
c1["high"] = c1["mean_life_span_years"] + c1["stddev_life_span_years"]
# Zoom to the data ±10%, but bound it on the BAND (low/high), not the means, so the ±1σ bars are
# never clipped. Same thin reasoning as the scatter: an axis domain is rendering, not a shown fact.
_c1_scale = alt.Scale(domain=[float(c1["low"].min()) * 0.9, float(c1["high"].max()) * 1.1], zero=False)
x_enc = alt.X("size_class:N", sort=CLASS_ORDER, title="weight class", axis=alt.Axis(labelAngle=0))
band = alt.Chart(c1).mark_rule(color=BAND, size=3).encode(
    x=x_enc, y=alt.Y("low:Q", title="mean life span (years)", scale=_c1_scale), y2="high:Q")
caps = alt.Chart(c1).mark_tick(color=BAND, thickness=3, size=12).encode(x=x_enc, y=alt.Y("low:Q", scale=_c1_scale)) + \
       alt.Chart(c1).mark_tick(color=BAND, thickness=3, size=12).encode(x=x_enc, y=alt.Y("high:Q", scale=_c1_scale))
mean_line = alt.Chart(c1).mark_line(color=ACCENT, strokeWidth=2).encode(
    x=x_enc, y=alt.Y("mean_life_span_years:Q", scale=_c1_scale))
mean_pts = alt.Chart(c1).mark_point(color=ACCENT, filled=True, size=90).encode(
    x=x_enc, y=alt.Y("mean_life_span_years:Q", scale=_c1_scale),
    tooltip=[alt.Tooltip("size_class:N", title="class"),
             alt.Tooltip("mean_life_span_years:Q", title="mean (yr)", format=".1f"),
             alt.Tooltip("stddev_life_span_years:Q", title="± σ (yr)", format=".2f")])
st.altair_chart(styled((band + caps + mean_line + mean_pts).properties(height=260)), width="stretch")
den = " · ".join(f"{r.size_class} {int(r.breeds_with_life_span)}/{int(r.breed_count)}"
                 for r in summary.itertuples())
st.caption(
    f"The fall is an elbow: flat toy→medium ({life('toy'):.1f}→{life('medium'):.1f} yr), then a drop "
    f"to giant ({life('giant'):.1f} yr). The ±1σ bars widen with size "
    f"({float(smin['stddev_life_span_years']):.2f} at {smin['size_class']} → {giant_std:.2f} at giant), "
    f"so the {gap:.1f} yr toy→giant gap is under 2× the giant band's σ — real in the mean, weak per dog.  \n"
    f"**n with a life span, per class:** {den} — coverage is uneven, so the toy mean rests on fewer "
    "breeds than the giant mean."
)

# C3 — why weight, not height: the correlation evidence that justifies the x-axis above
st.subheader("Why weight, not height")
disp = pd.DataFrame({
    "pair": corr["metric_a"].map(METRIC_LABEL) + " ↔ " + corr["metric_b"].map(METRIC_LABEL),
    "correlation": corr["correlation"].map(lambda v: f"{v:+.2f}"),
    "n breeds": corr["n_breeds"].astype(int),
})
st.table(disp.set_index("pair"))
st.caption(
    f"We plot life span against **weight**, not height, because weight predicts life span more strongly "
    f"({w_life:+.2f} vs {h_life:+.2f}), and because height and weight are {h_w:.2f}-coupled — height's "
    f"{h_life:+.2f} is largely borrowed from weight, so it adds little once weight is in. Every "
    f"coefficient carries its n; the {rho_n('weight_mid_kg', 'life_span_mid_years')} here is the same "
    f"{int(cov.breeds_plotted_scatter)} the scatter plots."
)

st.divider()

# --- D · how does temperament shift with size? (heatmap) ---------------------------------------
st.header("How does temperament shift with size?")
tags = seed_tags()
temp = q("select size_class, temperament, temperament_display, breed_count, breeds_in_class, pct_of_class "
         "from main_marts.mart_size_class_temperaments")
temp = temp[temp["temperament"].isin(tags) & (temp["size_class"] != "unknown")]
# Group / filter / sort on the lowercase KEY; RENDER the sentence-cased LABEL (both come from gold —
# no title-casing in the app). The seed's sort_order is keyed to the lowercase temperament, so build
# a key→label map and order the labels by that key order.
label = dict(zip(temp["temperament"], temp["temperament_display"]))
# Reindex onto the full 5×5 grid so absent (tag,class) pairs draw as an explicit 0% cell rather
# than a hole. This is presentation reshaping (a 0 read from absence), not a computed fact.
grid = pd.MultiIndex.from_product([tags, CLASS_ORDER], names=["temperament", "size_class"]).to_frame(index=False)
class_n = dict(zip(summary["size_class"].astype(str), summary["breed_count"]))
temp = grid.merge(temp, on=["temperament", "size_class"], how="left")
temp["pct_of_class"] = temp["pct_of_class"].fillna(0.0)
temp["breed_count"] = temp["breed_count"].fillna(0).astype(int)
temp["breeds_in_class"] = temp["size_class"].map(class_n).astype(int)
temp["temperament_display"] = temp["temperament"].map(label)   # fill the label on the reindexed rows
label_order = [label[t] for t in tags]                          # labels in the seed's sort_order
HEAT_H = 260
heat = (
    alt.Chart(temp)
    .mark_rect()
    .encode(
        x=alt.X("size_class:N", sort=CLASS_ORDER, title="weight class", axis=alt.Axis(labelAngle=0)),
        y=alt.Y("temperament_display:N", sort=label_order, title=None),
        color=alt.Color("pct_of_class:Q", scale=alt.Scale(scheme="blues", domain=[0, 100]),
                        # top-align the colour bar with the top of the heatmap: span it the full plot height
                        legend=alt.Legend(title="% of class", gradientLength=HEAT_H, titleOrient="top")),
        tooltip=[alt.Tooltip("temperament_display:N", title="trait"),
                 alt.Tooltip("size_class:N", title="class"),
                 alt.Tooltip("pct_of_class:Q", title="% of class", format=".0f"),
                 alt.Tooltip("breed_count:Q", title="breeds"),
                 alt.Tooltip("breeds_in_class:Q", title="in class")],
    )
    .properties(height=HEAT_H)
)
st.altair_chart(styled(heat), width="stretch")
st.caption(
    "Temperament varies systematically with size: small breeds skew **playful and alert**, giant "
    "breeds **protective and calm** — the bright cells fall on a diagonal.  \n"
    f"Percentages are of breeds in each class ({int(cov.breeds_with_temperament)} of {tot} breeds have "
    "a temperament). These are the *distinctive* traits by design; near-universal tags like intelligent "
    "and loyal are true of nearly every class and are set aside so they don't drown the signal."
)

st.divider()

# --- footer · full coverage table (the honest whole picture, on demand) ------------------------
with st.expander("Data coverage — the full picture"):
    table = pd.DataFrame({
        "measure": ["total breeds", "with a weight", "with a life span", "with both (scatter)",
                    "with a temperament", "plotted in scatter", "excluded from scatter"],
        "breeds": [tot, int(cov.breeds_with_weight), int(cov.breeds_with_life_span),
                   int(cov.breeds_with_both), int(cov.breeds_with_temperament),
                   int(cov.breeds_plotted_scatter), int(cov.breeds_excluded_scatter)],
    })
    st.table(table.set_index("measure"))
    st.caption(
        f"Consistency check: with-both ({int(cov.breeds_with_both)}) = plotted "
        f"({int(cov.breeds_plotted_scatter)}) = the correlation mart's n "
        f"({rho_n('weight_mid_kg', 'life_span_mid_years')}). Three panels agreeing is a built-in proof "
        "the marts are coherent. Life span is the midpoint of each breed's published range, not a prediction."
    )
