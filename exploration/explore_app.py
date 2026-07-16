"""THROWAWAY scratch explorer — delete after picking questions + buckets.

The parsing here is a rough prototype, not the real thing: the production
dashboard reads the dbt gold marts, never this in-app parse.

Run:  streamlit run exploration/explore_app.py
"""
import json
import re
from collections import Counter
from itertools import combinations
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

RAW = Path(__file__).parent / "raw_breeds.json"


def span(value):
    """Overall (min, max) of every number in the value; 'unknown'/empty -> None."""
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", value or "")]
    return (min(nums), max(nums)) if nums else (None, None)


breeds = json.loads(RAW.read_text())
rows = []
for b in breeds:
    w_lo, w_hi = span((b.get("weight") or {}).get("metric"))
    h_lo, h_hi = span((b.get("height") or {}).get("metric"))
    l_lo, l_hi = span(b.get("life_span"))
    mid = lambda lo, hi: (lo + hi) / 2 if lo is not None else None
    rows.append({
        "id": b["id"], "name": b["name"], "breed_group": b.get("breed_group"),
        "weight_kg": mid(w_lo, w_hi), "height_cm": mid(h_lo, h_hi),
        "life_span_years": mid(l_lo, l_hi),
        "temperament": b.get("temperament") or "",
    })
df = pd.DataFrame(rows)

st.write(f"{len(df)} breeds — weight parsed for {df.weight_kg.notna().sum()}, "
         f"life_span for {df.life_span_years.notna().sum()}")

pick = st.selectbox("Raw record", df["name"])
st.json(next(b for b in breeds if b["name"] == pick))

st.subheader("Size buckets")
cuts = [st.number_input(lbl, value=v, step=1.0)
        for lbl, v in [("toy <", 5.0), ("small <", 12.0), ("medium <", 25.0), ("large <", 45.0)]]
labels = ["toy", "small", "medium", "large", "giant"]
cuts = sorted(cuts)  # dragging one past its neighbour would otherwise crash pd.cut
# right=False => half-open [min, max), matching the dbt seed convention. 31 breeds
# sit exactly on a boundary (23 on 25kg alone), so the closed side is not cosmetic:
# a 45.0 kg breed is GIANT here, and must be giant in the model too.
df["size_class"] = pd.cut(df.weight_kg, [0, *cuts, float("inf")], labels=labels,
                          right=False, ordered=False)
st.bar_chart(df.size_class.value_counts().reindex(labels).fillna(0))

st.write("Weight quantiles (kg)")
st.write(df.weight_kg.quantile([0, .1, .25, .5, .75, .9, 1]))

st.subheader("Size vs life span")
st.scatter_chart(df.dropna(subset=["weight_kg", "life_span_years"]),
                 x="weight_kg", y="life_span_years")
st.scatter_chart(df.dropna(subset=["height_cm", "life_span_years"]),
                 x="height_cm", y="life_span_years")

band = (df.groupby("size_class", observed=True)
          .agg(mean_life=("life_span_years", "mean"), mean_kg=("weight_kg", "mean"),
               mean_cm=("height_cm", "mean"), n=("name", "count"))
          .reindex(labels).round(1).reset_index())
st.write("Mean life span per band (re-bucket live with the inputs above)")
st.write(band)

# Two charts sharing an x-axis, NOT one dual-axis plot. Two y-scales on one figure
# align arbitrarily, so the crossing point is an authoring choice rather than a
# fact — it invents a correlation. Stacked, one scale each, the reader compares
# honestly.
st.write("Breeds per band + mean life span")
base = alt.Chart(band).encode(
    x=alt.X("size_class", sort=labels, title=None, axis=alt.Axis(labelAngle=0)))
st.altair_chart(
    base.mark_bar(size=40, color="#2a78d6").encode(
        y=alt.Y("n", title="breeds")).properties(height=150)
    & base.mark_line(point=True, color="#2a78d6", size=2).encode(
        y=alt.Y("mean_life", title="mean life span (yrs)",
                scale=alt.Scale(zero=False))).properties(height=150),
    use_container_width=True)

st.subheader("Height vs weight — isometry breaks")
d = df.dropna(subset=["height_cm", "weight_kg"]).copy()
k, c = np.polyfit(np.log(d.height_cm), np.log(d.weight_kg), 1)

# Real breeds vs what the cube law (weight ~ height^3) would predict, both
# anchored on the same reference dog so the two lines start together.
ref = d.loc[d.height_cm.sub(d.height_cm.median()).abs().idxmin()]
grid = pd.DataFrame({"height_cm": np.linspace(d.height_cm.min(), d.height_cm.max(), 60)})
grid["cube law (^3)"] = ref.weight_kg * (grid.height_cm / ref.height_cm) ** 3
grid[f"actual fit (^{k:.2f})"] = ref.weight_kg * (grid.height_cm / ref.height_cm) ** k

st.altair_chart(
    alt.Chart(d).mark_circle(opacity=.35).encode(x="height_cm", y="weight_kg")
    + alt.Chart(grid.melt("height_cm", var_name="line", value_name="weight_kg"))
      .mark_line().encode(x="height_cm", y=alt.Y("weight_kg", scale=alt.Scale(domain=[0, 120])),
                          color="line"),
    use_container_width=True)

# Same thing as one sentence: scale a small breed up by the cube law and see how
# absurd the answer is next to real dogs of that height.
small = d.nsmallest(15, "height_cm").iloc[0]
tall = d[d.height_cm > 70]
f = tall.height_cm.mean() / small.height_cm
st.write(f"**{small['name']}** ({small.height_cm:.0f} cm, {small.weight_kg:.1f} kg) scaled ×{f:.1f} "
         f"to {tall.height_cm.mean():.0f} cm: cube law says **{small.weight_kg * f**3:.0f} kg**, "
         f"real dogs that tall average **{tall.weight_kg.mean():.0f} kg**.")

d["build_index"] = d.weight_kg / d.height_cm ** 3 * 1000
st.write("Build index (kg / cm³ ×1000) — flat if isometric, falls if taller breeds are leaner")
st.bar_chart(d.groupby("size_class", observed=True).build_index.mean())

st.subheader("Correlations")
st.write(df[["weight_kg", "height_cm", "life_span_years"]].corr().round(3))

st.subheader("Temperament tags")
tags = Counter(t.strip().lower() for s in df.temperament for t in s.split(",") if t.strip())
st.dataframe(pd.DataFrame(tags.most_common(), columns=["tag", "breeds"]), height=300)

# Hand-rolled tag -> trait mapping. A judgement call, not ground truth: it is
# the thing to argue about, so keep it visible rather than buried in a helper.
GROUPS = {
    "guardian": ["protective", "courageous", "alert", "confident", "fearless",
                 "determined", "tenacious", "reserved", "aloof"],
    "affectionate": ["affectionate", "friendly", "gentle", "loyal", "devoted", "outgoing",
                     "good-natured", "amiable", "charming", "merry", "cheerful",
                     "sensitive", "optimistic", "happy"],
    "energetic": ["energetic", "playful", "lively", "spirited", "athletic", "agile",
                  "curious", "mischievous", "hardy"],
    "calm": ["calm", "docile", "even-tempered", "easygoing", "patient", "dignified"],
    "clever": ["intelligent", "smart", "work-focused", "eager to please", "adaptable",
               "independent"],
}
T2G = {t: g for g, ts in GROUPS.items() for t in ts}

st.subheader("Trait groups by size band")
st.write(f"Mapping covers {len(T2G)} of {len(tags)} tags; unmapped: "
         f"{sorted(set(tags) - set(T2G))}")

g = pd.DataFrame([(r.name, r.size_class, T2G[t.strip().lower()])
                  for r in df.dropna(subset=["size_class"]).itertuples()
                  for t in r.temperament.split(",")
                  if t.strip() and t.strip().lower() in T2G],
                 columns=["name", "size_class", "grp"]).drop_duplicates()
n_band = df.groupby("size_class", observed=True).size()

# Two normalisations that tell different stories — see both before believing either.
breed_pct = (g.groupby(["grp", "size_class"], observed=True).name.nunique()
              .unstack(fill_value=0) / n_band * 100).reindex(columns=labels)
st.write("% of breeds in band carrying ≥1 tag from group")
st.write(breed_pct.round(0))
st.altair_chart(
    alt.Chart(breed_pct.reset_index().melt("grp", var_name="size_class", value_name="pct"))
    .mark_rect().encode(x=alt.X("size_class", sort=labels, title=None),
                        y=alt.Y("grp", title=None), color=alt.Color("pct", title="%"),
                        tooltip=["grp", "size_class", alt.Tooltip("pct", format=".0f")]),
    use_container_width=True)

mentions = g.groupby(["grp", "size_class"], observed=True).size().unstack(fill_value=0)
st.write("Share of a band's trait mentions (column sums to 100) — mix, not prevalence")
st.write((mentions / mentions.sum() * 100).reindex(columns=labels).round(0))

# One continuous axis beats a class here: net energy = energetic tags - calm tags.
CALM = {"calm", "docile", "even-tempered", "easygoing", "patient", "dignified",
        "gentle", "reserved", "aloof"}
ENER = {"energetic", "playful", "lively", "spirited", "athletic", "agile",
        "curious", "mischievous"}
df["tag_list"] = df.temperament.apply(
    lambda s: [t.strip().lower() for t in s.split(",") if t.strip()])
df["energy"] = df.tag_list.apply(
    lambda ts: sum(t in ENER for t in ts) - sum(t in CALM for t in ts))
st.write(f"Energy index (energetic − calm tags) — corr with weight "
         f"{df.weight_kg.corr(df.energy):.2f}")
st.bar_chart(df.groupby("size_class", observed=True).energy.mean().reindex(labels))

# Which tag PAIRS define a band: lift = how much more common here than overall.
# Combinations without a classifier.
st.write("Most distinctive trait pairs per band — leave-one-out lift")
pf = pd.DataFrame([(r.size_class, p) for r in df.dropna(subset=["size_class"]).itertuples()
                   for p in combinations(sorted(set(r.tag_list)), 2)],
                  columns=["size_class", "pair"])
# Baseline is every band EXCEPT this one. Comparing against the overall average
# would compare medium/large (67% of breeds) largely against themselves, so they
# could not deviate from a baseline they dominate.
n_tot = int(n_band.sum())
out = []
for bd in labels:
    ins = pf[pf.size_class == bd].pair.value_counts() / n_band.get(bd, 1)
    outs = pf[pf.size_class != bd].pair.value_counts() / (n_tot - n_band.get(bd, 0))
    lift = (ins / outs).dropna()
    lift = lift[ins >= .25]
    out += [{"band": bd, "pair": " + ".join(p), "in_band_%": round(ins[p] * 100),
             "other_bands_%": round(outs[p] * 100), "lift": round(lift[p], 1)}
            for p in lift.nlargest(3).index]
lifts = pd.DataFrame(out)
st.write(lifts)

# Lollipop, small-multiplied by band. Stem runs from lift=1 (the "no association"
# baseline) to the value, so distance from the rule IS the finding. Bands are an
# ordered category, so they carry an ordinal one-hue ramp; the pairs inside a band
# are nominal and must NOT be ramped by value.
BAND_BLUE = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"]  # validated --ordinal
enc_y = alt.Y("pair:N", sort="-x", title=None,
              axis=alt.Axis(labelLimit=220, domain=False, ticks=False))
lolli = alt.layer(
    alt.Chart().mark_rule(size=2, opacity=.5).encode(
        x=alt.X("lift:Q", title="lift vs all other bands (1 = no association)",
                scale=alt.Scale(domainMin=0)),
        x2=alt.datum(1), y=enc_y,
        color=alt.Color("band:N", sort=labels, legend=None,
                        scale=alt.Scale(domain=labels, range=BAND_BLUE))),
    alt.Chart().mark_circle(size=110).encode(
        x="lift:Q", y=enc_y,
        color=alt.Color("band:N", sort=labels, legend=None,
                        scale=alt.Scale(domain=labels, range=BAND_BLUE)),
        tooltip=["band", "pair", alt.Tooltip("in_band_%", title="% of band"),
                 alt.Tooltip("other_bands_%", title="% of other bands"), "lift"]),
    alt.Chart().mark_text(align="left", dx=10, fontSize=11, color="#52514e").encode(
        x="lift:Q", y=enc_y, text=alt.Text("in_band_%:Q", format=".0f")),
    alt.Chart().mark_rule(color="#c3c2b7", size=1).encode(x=alt.datum(1)),
).properties(width=380, height=alt.Step(22))

st.altair_chart(
    lolli.facet(row=alt.Row("band:N", sort=labels, title=None,
                            header=alt.Header(labelAngle=0, labelAlign="left",
                                              labelFontWeight="bold")),
                data=lifts)
         .resolve_scale(y="independent")
         .configure_view(stroke=None).configure_axis(grid=False),
    use_container_width=False)
st.caption("Number at each dot = % of breeds in that band with the pair.")

# Per-tag detail: the grouping can average away the sharpest signals.
st.subheader("Temperament by size band (raw tags)")
ex = pd.DataFrame([(r.size_class, t.strip().lower())
                   for r in df.dropna(subset=["size_class"]).itertuples()
                   for t in r.temperament.split(",") if t.strip()],
                  columns=["size_class", "tag"])
top = [t for t, _ in tags.most_common(18)]
pct = (ex[ex.tag.isin(top)].groupby(["tag", "size_class"], observed=True).size()
         .unstack(fill_value=0)
         .div(df.groupby("size_class", observed=True).size(), axis=1) * 100)
st.altair_chart(
    alt.Chart(pct.reset_index().melt("tag", var_name="size_class", value_name="pct"))
    .mark_rect().encode(
        x=alt.X("size_class", sort=labels, title=None),
        y=alt.Y("tag", sort=top, title=None),
        color=alt.Color("pct", title="% of breeds"),
        tooltip=["tag", "size_class", alt.Tooltip("pct", format=".0f")]),
    use_container_width=True)
st.write(pct.reindex(columns=labels).round(0))
