# DASHBOARD.md — the Streamlit spec, written before the app

Contract-first for the dashboard, same discipline as tests-before-models: the next session
**renders this**, it does not invent a design. Everything here was decided across DECISIONS.md §0,
SPEC.md "Dashboard questions / Marts", and CLAUDE.md, plus the M6 open choices resolved with real
mart data on 2026-07-17. Where this conflicts with those files, flag it — don't silently choose.

Reasoning lives in DECISIONS.md · schema in SPEC.md · this file is the **design + panel contract**.
It does not restate why a mart exists; it says what the app draws from it and how.

---

## 0. Principles (non-negotiable — inherited, not reopened)

- **Thin.** The app **reads gold and renders**. No parsing, no `pd.cut`, no `corr()`, no top-N logic
  computed in Python beyond *selecting rows already in a mart* (filter, sort, take-N). Every number
  on the page is built and tested upstream. If the app computes a fact, that fact is in the wrong
  place.
- **One panel = one mart. Never a join in the app.** Each section below names the single mart it
  reads. If a panel seems to need two marts joined, the join belongs in gold, not here.
- **Organised as a narrative, not as the brief's numbered questions.** The page reads top-to-bottom
  as one argument — *coverage → how big are dogs → does size cost life → how does temperament shift
  with size → the evidence behind "size = weight"*. No "Q1 / Q2 / Q3" headings. The order **is** the
  narrative. (Confirmed M6: "I'd not present per questions.")
- **Never a dual-axis chart.** The count bars and the life-span line are two charts stacked on a
  **shared x-axis** (size_class, same order). Two y-scales align arbitrarily and fabricate a
  relationship whose strength is a styling choice (DECISIONS.md §0; saved memory `no-dual-axis-charts`).
- **Every chart prints its population.** The coverage numbers from `mart_data_coverage` are on the
  page, and per-class life-span denominators (`breeds_with_life_span`) sit **next to the bars they
  qualify** — coverage is uneven by class (toy 29/40 vs giant 58/58). Never print 627 beside a chart
  drawn from 585.
- **±1σ on the mean-life-span line is required, not optional.** σ grows 0.68 → 1.54; the mean alone
  oversells the trend. The honest claim is "real in the mean, weak per dog."
- **"Size" = weight**, defined by `mart_metric_correlation` (weight↔life −0.67 vs height↔life −0.50).
- **Interactivity: none that drives the data.** `size_class` is an **axis / grouping only**, not a
  user-driven filter (confirmed M6). The app renders the full five-class comparison every time — the
  comparison *is* the point, so there is nothing to filter down to. This keeps the read layer at its
  thinnest.

---

## 1. The marts the app reads (and the one panel each serves)

Read from the **local `dogs.duckdb`** (the prod-target build), schema `main_marts`. The dashboard
never triggers the pipeline; it reads whatever gold currently holds.

| # | section | single mart | what the app does to it |
|---|---|---|---|
| A | coverage strip | `mart_data_coverage` | read 1 row, print the per-field strip |
| B | breeds per weight class | `mart_size_class_summary` + `size_class_bands` seed | 5 real classes, bar = `breed_count`; each x tick shows the class's **kg range** (from the seed) |
| C2 | *every breed*: weight vs life span (scatter) | `mart_size_vs_lifespan` | 585 points (both non-null), colour by `size_class` (**distinct** palette); y zoomed to data ±10% |
| — | longest-lived top-5 (below the scatter) | `mart_size_vs_lifespan` | filter/sort of the *same* mart; shows each breed's **published range** (min–max) |
| C1 | mean life span ± 1σ, per class | `mart_size_class_summary` | mean line + `stddev_life_span_years`; y zoomed ±10%, band-aware so the σ bars aren't clipped |
| C3 | why weight, not height (closes C) | `mart_metric_correlation` | 3 rows + explanation — justifies the weight x-axis |
| D | temperament heatmap | `mart_size_class_temperaments` (unchanged) | curated tags (seed `dashboard_temperament_tags`) × 5 classes, colour = `pct_of_class` |

**Order within section C is scatter → mean line → correlation** (raw breeds first, then the summary,
then the axis justification), decided in M6 — not the line-first order this spec was first drafted in.

`dim_breeds` and `breed_temperaments` are **not** read by the dashboard — `dim_breeds` is
DAG-internal; `breed_temperaments` is the brief's *queryable* deliverable for a human with SQL, not
a panel.

---

## 2. Page layout — one scrolling page, top to bottom

```
┌──────────────────────────────────────────────────────────────┐
│  🐕  Dog Breed Explorer                                        │  ← title + one-line framing
│  627 breeds · weight 625 · life span 587 · temperament 626     │  ← A: coverage strip (per-FIELD;
│  each chart below states the subset it actually uses           │    no single global "excluded")
├──────────────────────────────────────────────────────────────┤
│  HOW ARE BREEDS DISTRIBUTED ACROSS WEIGHT CLASSES?            │
│  ▁▃▇▆▂   count bars, blue ordinal ramp                         │  ← B: distribution
│  toy      small    medium   large    giant                     │    each tick: class + its kg range
│  0–5 kg   5–12     12–25    25–45    ≥45 kg                     │    (from the size_class_bands seed)
├──────────────────────────────────────────────────────────────┤
│  WHICH BREEDS LIVE LONGEST? DOES SIZE COST LIFE SPAN?         │
│  ("size" = weight — evidence at the foot of this section)      │
│  ┌ every breed: weight vs life span (585) ───────────┐         │  ← C2-scatter FIRST, DISTINCT
│  │  · ·:·. · ·   toy·small·medium·large·giant colours │         │    colours; y zoomed to data ±10%
│  └────────────────────────────────────────────────────┘        │
│  585 of 627 plotted · 42 excluded                              │
│  ┌ Longest predicted life span (top 5) ───────────────┐        │  ← top-5 table, same mart
│  │  breed · size class · weight · published range 12–18│        │    (all five tie; alphabetical)
│  └────────────────────────────────────────────────────┘        │
│  ┌ mean life span ± 1σ, per weight class ────────────┐         │  ← C1-line; y zoomed ±10%,
│  │  13.3 ─ 13.2 ─ 13.0 ─ 12.2 ─ 10.6   (bars = ±1σ)  │         │    band-aware (σ bars not clipped)
│  └────────────────────────────────────────────────────┘        │
│  n with life span: toy 29/40 · … · giant 58/58                 │
│  → smaller breeds tend to live longer — real in the mean,      │
│    weak per dog (giant σ 1.54 vs a 2.7 yr gap)                 │
│  ── why weight, not height (the axis choice) ──────────        │  ← C3: correlation evidence,
│  weight↔life −0.67 · height↔life −0.50 · height↔weight 0.86    │    closes the section because it
│  weight predicts life span better; height 0.86-coupled.        │    justifies the x-axis above
├──────────────────────────────────────────────────────────────┤
│  HOW DOES TEMPERAMENT SHIFT WITH SIZE?                         │
│           toy  small med  large giant                          │  ← D: heatmap (mark_rect)
│  playful  ███  ▓▓▓  ▒▒   ░░   ·    (colour = pct_of_class)     │    rows = seed tags (sort_order)
│  alert    ███  ███  ▓▓   ▒▒   ░░                               │    cols = size_class (toy→giant)
│  energetic ▒   ▓▓   ▓▓▓  ▒▒   ·    → diagonal gradient:        │
│  protective ·   ·   ░░   ▓▓   ███    playful bright top-left,  │
│  calm      ·    ·   ░░   ▒▒   ███    calm/protective bot-right │
├──────────────────────────────────────────────────────────────┤
│  ▸ Data coverage (full table)  — expander, honest footer      │  ← A (full), on demand
└──────────────────────────────────────────────────────────────┘
```

Visual hierarchy: **B + C are the headline** (the distribution and the size↔life-span finding — the
two questions with a strong, honest signal). **C closes with its own evidence (C3)** — the
correlation numbers that justify measuring size as weight sit *inside* the size-vs-life-span section
they explain, not as a detached footnote. **D is a supporting section** (temperament texture). The
coverage strip is persistent context at the top; the full coverage table is an on-demand expander at
the bottom.

---

## 3. Panel specs

Each panel: **what it shows · the single mart · chart type + the rule that dictates it · the claim it
lets a reader write · the honesty shown alongside.** Numbers below are live from the prod warehouse
on 2026-07-17.

### A — Coverage (top strip + footer table) — the honesty spine of the page
- **Shows:** the population every chart below is drawn from, stated as a fact, not hidden. This is
  the rule DECISIONS.md §0 and SPEC make load-bearing: **"every chart prints its population; never
  print 627 next to a chart drawn from 585."** A dashboard that says "627 breeds" above a plot of 585
  is quietly lying — exposing the denominator is the difference between a chart and a claim.
- **Mart:** `mart_data_coverage` — **grain: one row**, 7 columns. What each column *is*, and **which
  panel consumes it** (this is how the mart is used — not one header number, but a figure threaded
  onto every chart):

  | column | live | meaning — what it drops | feeds panel |
  |---|---|---|---|
  | `total_breeds` | **627** | post-dedupe (raw 628 → Caucasian Shepherd removed) | header + every panel's denominator |
  | `breeds_with_weight` | **625** | 2 have no parsed weight → `size_class = 'unknown'` | **B** (2 not banded) |
  | `breeds_with_life_span` | **587** | 40 have no life span → excluded from every life-span mean | **C1** (whole-dataset) |
  | `breeds_with_both` | **585** | scatter needs weight *and* life span | **C2**, **C3** (= `n_breeds`) |
  | `breeds_with_temperament` | **626** | 1 (Mongrel) — its only tag is a sentinel, excluded | **D** |
  | `breeds_plotted_scatter` | **585** | = `breeds_with_both` | **C2** |
  | `breeds_excluded_scatter` | **42** | 627 − 585 | **C2** headline |

- **Chart:** a single-line strip stating coverage **per field, not one global "excluded"** —
  **"627 breeds · 625 with weight · 587 with life span · 626 with temperament"** (a `st.markdown`
  line of bold numbers, with a `st.caption` *"each chart below states the subset it uses"*). Built as
  a line, not `st.metric` cards, on request. The full 7-column table lives in a bottom expander.
- **Why per-field, and why NO single "42 excluded" headline:** exclusion is **chart-specific**, so a
  lone global number misleads. Each chart drops a *different* set for a *different* reason, and that
  count lives **on the chart**, not in the strip:

  | chart | needs | drops | shows |
  |---|---|---|---|
  | B distribution | a weight | 2 (unknown weight) | **625 of 627 banded** |
  | C1 life-span line | a life span | 40 | **587**, + per-class (toy 29/40 … giant 58/58) |
  | C2 scatter | weight **and** life span | 42 | **585 of 627 plotted · 42 excluded** |
  | D heatmap | a temperament | 1 (Mongrel sentinel) | **626 of 627** |

  The "585 plotted · 42 excluded" belongs to the **scatter alone** (it's the only chart needing both
  metrics) — so it sits on C2, never in the header. **The per-chart numbers below are not read from
  the strip** — each panel prints its own figure from its coverage column, so coverage travels *with*
  each chart.
- **The consistency check to state on the page:** `breeds_with_both` (585) == `breeds_plotted_scatter`
  (585) == `mart_metric_correlation.n_breeds` (585). Three panels agreeing on 585 is a built-in proof
  the marts are coherent.
- **The uneven-by-class point (why the strip alone is not enough):** whole-dataset coverage hides
  that life-span missingness is **not evenly spread** — toy 29/40 (27.5% missing) vs giant 58/58 (0%).
  The toy bar rests on 72% of toy breeds, the giant bar on 100%, and the top strip can't show that.
  So the **per-class denominators live on C1**, from `mart_size_class_summary.breeds_with_life_span`,
  not from this one-row mart. `mart_data_coverage` = whole-dataset totals; per-class = the summary mart.
- **Claim it enables:** "every chart states what it drops."
- **Honesty:** this panel *is* the honesty. It exists so no other panel silently prints 627.

### B — How are breeds distributed across weight classes? (distribution)
- **Shows:** how the 627 breeds distribute across the five size classes, **with each band's kg range
  under its name** so the reader knows what "medium" means.
- **Mart:** `mart_size_class_summary`, filtered to the 5 real classes (drop `unknown`, n=2 — noted,
  not plotted). Bar height = `breed_count`. The kg ranges come from the **`size_class_bands` seed**
  (read from the CSV), so the printed range can't disagree with the model's banding.
- **Chart:** vertical **count bars** on the **ordinal blue ramp** (light=toy → dark=giant — the bars
  are a distribution, and a single sequential hue reads the size order well). x = `size_class` in
  fixed order toy → small → medium → large → giant, each tick a two-line label (class over its range:
  `0–5 kg` … `≥45 kg`). Both C1 and this chart use the same class order, but the scatter (C2) now sits
  between them, so they are no longer physically stacked (the M6 reorder — see §2).
- **Live values:** toy **40** · small **104** · medium **220** · large **203** · giant **58** (= 625
  banded; +2 `unknown` = 627).
- **Claim:** "most breeds are medium or large; toy and giant are the tails."
- **Honesty:** `breed_count` is *all* breeds in the class (not just those with a life span), so this
  bar has full 627-based coverage — the missing-life-span caveat belongs on C, not here. Prints its
  population from `mart_data_coverage.breeds_with_weight`: **"625 of 627 banded; 2 unknown-weight
  breeds excluded from the bars."**

### C — Which breeds live longest? Does size cost life span? (the finding + its evidence)

The section reads **scatter → mean line → correlation**: the raw per-breed cloud first, then the
per-class summary, then the axis justification. (Drafted line-first; **reordered in M6**.)

**C2 — every breed: weight vs life span (scatter)**
- **Shows:** the within-class spread the means hide, and where the longest-lived breeds sit.
- **Mart:** `mart_size_vs_lifespan` (breed grain). Plot the **585** breeds with both `weight_mid_kg`
  and `life_span_mid_years` non-null; the mart keeps the 42 null rows on purpose and the **app drops
  them** (DECISIONS.md §0).
- **Chart:** scatter, x = `weight_mid_kg`, y = `life_span_mid_years`.
  - **Colour = `size_class` on a DISTINCT (categorical) palette** — blue / green / magenta / amber /
    aqua, validated CVD-safe (`validate_palette.js`). This **overrides §4b's original "single
    sequential blue ramp, never categorical"** for this one chart, deliberately: the x-axis already
    encodes the size *ordering*, so colour is freed to encode *identity*, and five blue shades were
    indistinguishable in the cloud. Points carry a dark outline so lighter fills read on white; the
    **legend swatches have no outline** (`symbolStrokeWidth=0`, on request). The bars (B) keep the
    ordinal blue ramp — two jobs, two encodings.
  - **y zoomed to the data ±10%** (`[min(mid)·0.9, max(mid)·1.1]`) so the cloud uses the vertical
    space. Axis bounds are rendering geometry, not a shown fact → within the thin rule.
- **Claim:** "knowing a dog's size class tells you a lot; within any single band the relationship
  nearly vanishes." (The specific within-band −0.1..−0.4 figure is **not** printed — it isn't in a
  mart, so nothing hardcoded.)
- **Honesty:** prints its population from `mart_data_coverage`: **"585 of 627 plotted · 42 excluded"**
  (`breeds_plotted_scatter` / `breeds_excluded_scatter`) — the same 585 as C1's base and C3's `n`. The
  colour legend doubles as the class key for the whole page.

**Longest predicted life span — top-5 table (directly under the scatter)**
- **Shows:** the longest-lived breeds, by name.
- **Mart:** `mart_size_vs_lifespan` — a **filter/sort of the same mart** (top-N is the app's job), no
  new read. Shows each breed's **published range** via `life_span_min_years` / `life_span_max_years`
  (added to the mart in M6 as a pass-through from `dim_breeds`).
- **The ordering call (honest, DECISIONS.md §0):** the five highest tie **identically** — all `12–18`
  yr (min, max, *and* midpoint equal) — so **no life-span sort can rank them**. They are listed
  **alphabetically**, not in a fake 1–5 order, and the range is shown so the tie is legible. What
  differs between them is size, not lifespan. The caption branches: if a refresh breaks the tie it
  switches to midpoint-ranked wording.

**C1 — mean life span ± 1σ, per class**
- **Shows:** the central trend and its spread.
- **Mart:** `mart_size_class_summary` — `mean_life_span_years` (line/points) and
  `stddev_life_span_years` (± error bars). low/high = mean∓σ is chart geometry drawn off the mart.
- **Chart:** a **line/point with ±1σ error bars**, x = the *same* `size_class` order as B. **Never**
  overlaid on B's counts as a second y-axis. **y zoomed to the data ±10%, bounded on the BAND**
  (`[min(mean−σ)·0.9, max(mean+σ)·1.1]`) so the σ bars are never clipped. Zooming makes the decline
  look steeper (the DECISIONS §0 zero-suppression worry) — the **required-visible ±1σ band is the
  honesty guard**.
- **Live values:**

  | class | n / with life span | mean | ±σ |
  |---|---|---|---|
  | toy | 40 / **29** | 13.3 | 0.86 |
  | small | 104 / **86** | 13.2 | 0.68 |
  | medium | 220 / 212 | 13.0 | 0.77 |
  | large | 203 / 200 | 12.2 | 1.03 |
  | giant | 58 / 58 | 10.6 | 1.54 |

- **Claim:** "mean life span falls 13.3 → 10.6 yr from toy to giant, and the fall is an *elbow* —
  flat toy→medium, then a drop at large/giant — not a smooth gradient. The spread grows with size."
- **Honesty:** the **per-class denominators sit right here**, from
  `mart_size_class_summary.breeds_with_life_span`: the toy mean rests on **29/40** breeds, the giant
  mean on **58/58**. This is the uneven-by-class bias DECISIONS.md §0 insists on surfacing. The ±1σ
  bars stop the mean overselling the trend (giant σ 1.54 vs a 2.7 yr toy→giant gap → bands overlap).

**C3 — why weight, not height (the evidence closing this section)**
- **Shows:** why the two charts above use **weight** as the size axis — it belongs *here*, inside the
  size-vs-life-span argument it justifies, not as a detached footnote after temperament.
- **Mart:** `mart_metric_correlation` (3 rows) — presented **in full**, with explanation (confirmed
  M6).
- **Chart:** a small labelled panel/table of the three coefficients, **each with its `n`**, plus one
  short paragraph of prose:

  | pair | correlation | n |
  |---|---|---|
  | weight ↔ life span | **−0.67** | 585 |
  | height ↔ life span | −0.50 | 585 |
  | height ↔ weight | 0.86 | 625 |

  **Prose:** *"We plot life span against **weight**, not height, because weight predicts life span
  more strongly (−0.67 vs −0.50), and because height and weight are 0.86-coupled — height's −0.50 is
  largely borrowed from weight, so it adds little once weight is in. That is what 'size' means on
  this page."*
- **Claim:** the −0.67 is the single number that quantifies the C1/C2 finding; the other two rows
  justify the choice of axis. Placing it at the *foot* of the section answers the reader's "why
  weight?" exactly when it arises — after they've seen the finding, before temperament.
- **Honesty:** `n` is on every coefficient — a correlation without its population is not a fact. The
  585 here equals the scatter's 585 (C2) and the coverage strip's `breeds_with_both`, a built-in
  consistency check across the section.

### D — How does temperament shift with size? (heatmap)
- **Shows:** temperament as a **distinctive** signature per class, not a list of universal tags —
  read as one grid where the bright cells trace a diagonal from small-and-playful to big-and-calm.
- **Mart:** `mart_size_class_temperaments` — **unchanged**, grain (size_class, temperament), value =
  `pct_of_class` (= `breed_count / breeds_in_class`, already computed in gold). The app filters to
  the curated tags (from the seed, below) × 5 classes and renders; **no computation.**
- **Chart:** a **heatmap** (Altair `mark_rect` on the mart's long rows — no pivot, no reshape into
  wide in the app):
  - **x** = `size_class`, sorted toy → small → medium → large → giant.
  - **y** = `temperament`, sorted by the seed's `sort_order`.
  - **colour** = `pct_of_class`, the sequential ramp §4 fixes (dark = higher).
- **Why a heatmap and NOT the radars this spec first proposed** — the reason is the one this project
  already enforces for the count/life-span pair. A radar's stated finding ("the shape *rotates* as
  size increases") is **manufactured by the axis order you choose**: reorder the five spokes and the
  rotation moves or disappears — a relationship whose strength is a *styling choice*, the exact sin
  cut for the dual axis (DECISIONS.md §0; saved memory `no-dual-axis-charts`). Radars pile area
  distortion on top (the eye reads enclosed area, which scales with the square of the values). A
  heatmap shows the identical numbers honestly: **one colour per cell reads true regardless of
  row/column order**, there is no area, and a missing or stale tag is a blank *cell*, never a blank
  chart. The "rotation" becomes a clean **diagonal gradient** — playful bright at toy, protective/calm
  bright at giant — that survives any reordering.

  **The curated tags live in a seed, not an app literal: `seeds/dashboard_temperament_tags.csv`**
  (`temperament, sort_order`) — same playbook as `size_class_bands`. The five, chosen by cross-class
  spread of `pct_of_class` (recorded here, frozen like the size bands):

  | tag | sort | toy | small | medium | large | giant | spread | role |
  |---|---|---|---|---|---|---|---|---|
  | playful | 1 | 80 | 56 | 14 | 10 | 0 | 80 | toy end |
  | alert | 2 | 80 | 82 | 69 | 47 | 22 | 59 | toy/small end |
  | energetic | 3 | 35 | 55 | 64 | 44 | 0 | 64 | middle |
  | protective | 4 | 0 | 1 | 11 | 33 | 86 | 86 | giant end |
  | calm | 5 | 5 | 2 | 13 | 26 | 69 | 67 | giant end |

  The `sort_order` (playful→calm) is what makes the bright cells fall on the diagonal.

  > **Why this is thin, and where the cut lives.**
  > 1. **Every plotted value is `pct_of_class`, computed in gold** — "69% of giant breeds are calm"
  >    is a row in the mart. The app computes no percentage, ratio, or aggregate.
  > 2. **The curated cut stays in the read layer — the mart is untouched.** The app reads the seed to
  >    get the tag list + order, then filters the *unchanged* mart to those tags. That is "selecting
  >    rows already in a mart" (DASHBOARD.md §0), the same category as top-N. Deliberately **not**
  >    baked into gold: no `is_dashboard_axis` flag, no new "grid" mart — that would contradict the
  >    mart's own header (*"TOP-N IS NOT HERE… bake the cut in and you can't change it without a
  >    rebuild"*). The seed carries only the **list + order**, never `pct_of_class`, so it is config,
  >    not a data grid. It is **not** the leave-one-out pair-lift DECISIONS.md §0 cut — no baseline,
  >    no lift, no inference; distinctive-by-spread was decided once, offline, and frozen.
  > 3. **Sparse cells read fine.** The mart is sparse — a tag with 0 breeds in a class has no row
  >    (e.g. `protective/toy`, `playful/giant`); on a heatmap those simply render as empty cells,
  >    which is honest. If you'd rather draw them as an explicit `0`, a pandas reindex onto the
  >    seed-tags × classes grid is **presentation reshaping, not a computed fact** — allowed either
  >    way; note in the build which you did.
  >
  > **The seed is guarded by one test that earns its place:** `relationships` seed.temperament →
  > `breed_temperaments.temperament`, **severity WARN**. It fires on a typo, a casing/normalization
  > mismatch (the bridge is lowercased+trimmed, so `'Calm'` matches nothing), or a vocabulary drift
  > that drops a displayed tag — each of which silently empties a heatmap row. WARN, not error:
  > **editing the seed IS the correct response**, and M5's `annotate_warns.py` surfaces it without
  > failing the build. This guards a **curated input** (like `assert_size_class_bands_cover`), *not* a
  > guessed volume constant — so it is not the DECISIONS.md §3 "wallpaper" anti-pattern. (Proven:
  > green on the five real tags; inject `Calm` → `WARN 1`, exit 0.) A cheap `unique` on the tag
  > (error) guards against a duplicated row doubling a heatmap row.

  > **`intelligent` is deliberately excluded** (90/86/93/86/53, spread 40): it applies to ~85-93% of
  > breeds in every class, so it is marketing vocabulary with zero discriminating power — a flat,
  > uniformly-dark row that says nothing. `loyal`, `affectionate`, `independent` are the alternates if
  > a sixth row is ever wanted; five is the spec (edit the seed, not code).

- **Claim:** "temperament varies systematically with size — small breeds skew playful and alert,
  giant breeds protective and calm — the bright cells fall on a diagonal."
- **Honesty:** two denominators, both shown. Whole-section population from
  `mart_data_coverage.breeds_with_temperament`: **"626 of 627 breeds have a temperament"** (Mongrel's
  lone tag is a sentinel, excluded). Per-column, the base `breeds_in_class` (toy 40 … giant 58) — the
  percentages are of breeds-in-class, shown not implied. State plainly that these are the
  *distinctive* tags **by design**, and that the near-universal tags (intelligent, loyal) were set
  aside on purpose so the reader isn't misled into thinking the brightest tags are the whole story.

---

## 4. Visual design

Two layers: the **app shell** (theme, layout, sections — how the page looks and is organised) and
the **chart encodings** (per-mark colour/axis rules). Both stay native and thin — Streamlit's
defaults already read clean and modern; the job is to use its heading hierarchy and theme, **not** to
hand-set fonts or inject CSS.

### 4a. App shell — clean, modern, sectioned, all native

Decided M6: **Light theme · centered narrative width · native theming only (no custom CSS).**

- **Theme via `.streamlit/config.toml [theme]`** — the one place look-and-feel is set, versioned in
  the repo:
  - `base = "light"` — white canvas, near-black text. Conventional for a data dashboard and the
    safest for the **PDF/screenshot delivery** (dark backgrounds export muddy).
  - `primaryColor` — a **single calm accent** (headers/metrics/interactive), from which the
    sequential chart ramps are derived so the page reads as one system. Exact hue chosen at build
    under the **dataviz** skill; a restrained blue/teal is the default direction.
  - `font` — Streamlit's default clean **sans-serif**; do not swap in a custom font (native-only).
- **Page config:** `st.set_page_config(page_title="Dog Breed Explorer", page_icon="🐕",
  layout="centered")`. **Centered** keeps prose at a comfortable reading length for a top-to-bottom
  narrative; charts sit at full content width.
- **Sections built from native primitives — this is what makes it look "organised in nice
  sections":**
  - Each narrative section (How big · Does size cost life span · Temperament) opens with a
    **`st.header`**; sub-panels (C1/C2/C3) use **`st.subheader`**. Font sizes come from this
    hierarchy, never set by hand.
  - **`st.divider()`** between sections for clean visual separation.
  - Panels that read as cards use **`st.container(border=True)`**; paired elements use
    **`st.columns()`** (e.g. the coverage metrics, or a chart beside its caption).
  - The **coverage strip** = a row of **`st.metric`** (627 · weight 625 · life span 587 ·
    temperament 626); the **coverage footer** = **`st.expander`** holding the full table.
  - Secondary/honesty text (n, σ, denominators, "midpoint of published range") = **`st.caption`**,
    so it reads as supporting fine-print, not body copy.
- **Rhythm:** one chart per row within the centered column; consistent spacing from the primitives
  above; no manual pixel padding.
- **Styling discipline:** **no `unsafe_allow_html`, no injected CSS.** Native theming + layout only —
  clean, modern, and stable across Streamlit versions, and consistent with the thin principle. If a
  reviewer ever wants heavier bespoke design, that's a documented step away from thin, not the spec.
- **Delivery fit:** light + centered screenshots and exports to PDF cleanly — the delivery format
  (DECISIONS.md §5 / ARCHITECTURE_PLAN M6) drove the light+centered choice, not just taste.

### 4b. Chart encodings

- **Three colour encodings — sequential where the variable is a magnitude, categorical where it's an
  identity.** *(This revises the spec's original "both sequential, never categorical" line — the
  scatter changed at M6 after the blue ramp proved illegible in the cloud.)*
  - **Bars (B): ordinal `size_class`, sequential blue ramp** (light = toy → dark = giant). On a bar
    chart the order reads well and position already separates the classes, so one hue is right.
  - **Heatmap (D): `pct_of_class`, sequential blue ramp** (dark = higher). A magnitude → one hue.
  - **Scatter (C2): `size_class`, DISTINCT (categorical) palette** — blue/green/magenta/amber/aqua,
    validated CVD-safe. Here colour is an **identity**, not a magnitude: the x-axis (weight) already
    carries the size ordering, and five blue shades couldn't be told apart in a dense cloud. This is
    the one place categorical hues are correct; validate any change with `validate_palette.js`.
  Exact hues are chosen at build under the **dataviz** skill — this spec fixes the *encodings*, not
  every hex.
- **y-axes zoom to the data (±10%), not to zero.** C2 bounds on the plotted midpoints; C1 bounds on
  the **±1σ band** so the error bars are never clipped. Axis bounds are rendering geometry (not a
  shown fact), so this is within the thin rule — but zooming a trend off zero looks steeper, so C1
  keeps the ±1σ band visible as the honesty guard (DECISIONS §0).
- **Shared class order** toy → small → medium → large → giant on B, C1, D. B and C1 are no longer
  physically adjacent (C2 sits between them after the M6 reorder), so the order is a consistency cue,
  not a stacked-pair alignment.
- **`unknown` (n=2) never appears as a plotted class.** It is real (2 breeds with no parsed weight)
  and lives in the coverage/footer, not on the size axis.
- **Fonts/labels:** every axis labelled with units (kg, years); every chart carries its `n`. No
  chart junk, no second y-axis, ever.
- **Responsive/thin:** all rendering from cached mart reads; the app must run against the local
  `dogs.duckdb` and never touch the network or the pipeline.

---

## 5. What the data says (the narrative the README draws from)

Plain-language claims, stated honestly — this is the source text for the README's "what the data
SAYS" section:

1. **Most dog breeds are mid-sized.** 220 medium + 203 large of 627 breeds; toy (40) and giant (58)
   are the tails.
2. **Smaller breeds tend to live longer — but it's a large-and-giant effect, not a smooth slope.**
   Mean life span is flat across toy→medium (13.3 → 13.0 yr) and then drops for large (12.2) and
   giant (10.6). Life span here is the **midpoint of the published range**, not a prediction.
3. **The trend is real in the mean and weak for any individual dog.** The spread grows with size
   (σ 0.68 → 1.54), and the 2.7-year toy→giant gap is under 2σ of the giant band — the distributions
   overlap heavily. A giant breed *tends* to live less than a toy, but plenty don't.
4. **Temperament shifts systematically with size.** Small breeds skew **playful and alert**; giant
   breeds skew **protective and calm**; energetic peaks in the middle. (The universal tags —
   intelligent, loyal — are true of nearly every class and say nothing distinctive, so they're set
   aside.)
5. **"Size" means weight.** Weight predicts life span better than height (−0.67 vs −0.50), and
   height is 0.86-coupled to weight, so weight is the right single size axis.
6. **Every chart states its own population — coverage is per-field, not one global number.** Of 627
   breeds, 625 have a weight, 587 a life span, 626 a temperament; each chart shows the subset it
   uses. The scatter specifically needs both metrics, so it plots 585 and drops 42 — and that
   missingness is uneven by class (toy 29/40 vs giant 58/58), which the dashboard shows rather than
   hides.

---

## 6. Explicitly NOT building (settled — do not reopen at build time)

- **No dual-axis chart.** B and C stay two charts on a shared x-axis (DECISIONS.md §0 · saved memory).
- **No `size_class` filter / no interactivity that drives the data.** Axis only (M6).
- **No pair-lift / leave-one-out temperament analysis in the app.** The heatmap uses `pct_of_class`
  (descriptive); the distinctive *finding* (giant calm+protective ×14.9) lives in DECISIONS.md §0 as
  an explored artifact. Selecting distinctive tags by spread ≠ computing lift.
- **The curated tag cut stays in the read layer.** No `is_dashboard_axis` flag on the mart, no new
  "grid" mart — both bake the cut into gold, contradicting the mart's header. The seed carries only
  the list + order (config, not a data grid); the mart is untouched.
- **No height-vs-weight scatter or isometry curve.** Cut to DECISIONS.md §0 — a regression exponent
  is not a fact about a dog.
- **No business logic in the app.** If the build finds itself computing a fact, that fact belongs in
  a mart — stop and add it upstream.
- **No custom CSS / `unsafe_allow_html`, no custom fonts, no `layout="wide"`.** Light theme, centered
  narrative, native theming + layout primitives only (M6, §4a). Look-and-feel lives in
  `.streamlit/config.toml`, not in per-element styling.

---

## 7. Resolved at build (M6) — how the open choices were settled

The app is built (`dashboard/app.py`, `.streamlit/config.toml`) and demoed live off the local prod
`dogs.duckdb`. How each deferred choice landed:

- **Temperament tag list:** the app reads the **seed CSV** directly (`dashboard_temperament_tags.csv`)
  — robust with no prod re-seed dependency; it's the same file dbt loads.
- **Heatmap:** Altair `mark_rect` on the mart's long rows. **Sparse cells → drawn as explicit 0** via
  a pandas reindex onto the seed-tags × classes grid (presentation reshaping, not a computed fact).
- **Palettes:** bars + heatmap use a **sequential blue ramp**; the **scatter uses a distinct
  categorical palette** (blue/green/magenta/amber/aqua, CVD-validated) because there colour is
  identity, not magnitude (§4b). `primaryColor = #2171b5`, `base = light` in `config.toml`.
- **Numbers are read from gold at render time — none hardcoded.** Every coefficient, mean, σ, count,
  and denominator in the captions is computed from the marts, so a daily refresh moves the prose too.
- **Gold touched (small, additive):** `mart_size_vs_lifespan` gained `life_span_min_years` /
  `life_span_max_years` (pass-through from `dim_breeds`, contract updated) so the longest-lived table
  can show each breed's published range. `min≤max` already tested upstream, so no new test.
- **Axis zoom + legend polish:** y-axes zoom to data ±10% (C1 band-aware); the scatter legend swatches
  drop their outline (`symbolStrokeWidth=0`), plot points keep theirs.

**Still genuinely open (next milestones):** the README narrative (M6 last box, drawn from §5) and the
PDF/screenshot export (delivery). Neither changes the app.
