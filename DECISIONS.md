# DECISIONS.md

> One paragraph per layer: what I chose, what I traded off, what I'd do differently with more
> time. This is the reasoning record — fill it in **as I build**, not at the end, so it captures
> real decisions rather than reconstructed ones.

## Context & guiding principle

The Dog API is a small, static reference dataset. The engineering challenge is **craft, not
volume**: clean parsing of messy fields, a legible model, and a reliable, idempotent daily
pipeline. My guiding principle throughout is **right-sizing** — the smallest stack that does the
job well and that I can fully explain, rather than the heaviest set of managed services. I
designed the architecture first and used Claude Code as the implementer against that design, so
every decision below is mine to defend.

---

## 0. Data exploration — **profiling + a throwaway Streamlit explorer**

Before designing anything I profiled the source (`exploration/profile_breeds.py` → `PROFILE_REPORT.md`)
and built a disposable Streamlit explorer (`exploration/explore_app.py`) to eyeball relationships and
settle the size buckets. Both are **scratch, deleted after this milestone** — the dashboard reads the
gold marts, never that rough in-app parse. What the exploration decided:

**Shape of the source.** 628 breeds; `id` unique and non-null (**primary key confirmed**). Weight
parses for 626/628 (the 2 misses are `'unknown'` string sentinels), `life_span` for 588 (6.4% null).
So every chart below runs on ~586 breeds with weight + life span both present — small enough that
the honest framing is "descriptive of this dataset", not inferential.

### What I'm putting on the dashboard, and why the data earned it

- **Two stacked charts sharing an x-axis — count bars above, mean-life-span line below.** One tile
  answers **two** of the four questions ("How are breeds distributed across weight classes?" and "Is
  there a relationship between size and life span?"). The data justifies pairing them: mean life
  span falls monotonically **13.3 yr (toy) → 10.6 yr (giant)**, so the distribution and the trend
  are the same story told twice.
  - **Deliberately NOT a dual-axis chart.** My first draft put both on one plot with two y-scales.
    Two y-scales align arbitrarily — I set `zero=False` on the life-span axis, and that choice alone
    decides how dramatic the decline looks; with `zero=True` the line flattens and the story visually
    disappears. Same data, opposite impression, nothing telling the reader which they're seeing. The
    chart would manufacture a relationship whose strength I dialled in. It matters here specifically
    because the real finding is an *elbow* (flat toy→medium, then a drop), and on a dual axis the
    elbow's position is a styling decision. Two charts, one scale each, same category order: the
    comparison survives, the fabrication doesn't.
- **`size_class` / `mean_life` table.** The numbers behind the chart. Also carries the nuance the
  chart hides: the decline is **flat across toy→medium (13.3 → 13.0) then drops sharply** for large
  and giant. The size penalty is a *large-and-giant* effect, not a smooth gradient — worth stating
  plainly rather than implying a straight line.
- **Weight vs life-span scatter.** Kept because the means hide the spread. Overall correlation is
  **−0.67**, but within any single band it's only ~−0.1 to −0.4. So: *knowing a dog's size class
  tells you a lot; knowing one giant outweighs another tells you little.* The scatter shows that
  variance honestly; a bar chart alone would oversell −0.67. (I explored a per-band correlation
  matrix that made this precise, and dropped it — too much machinery for the point. The sentence
  survives; the table doesn't.)
- **Height vs weight — the isometry break.** A genuine finding, cheap to show. Weight scales as
  **height^2.07**, not the **height^3** that geometric similarity predicts (log-log fits better:
  R² 0.86 vs 0.74 linear). Plain-language claim: **dog breeds get proportionally lighter as they get
  taller** — tall breeds are built long and lean, not scaled-up small dogs. Charted as the scatter
  plus a cube-law reference curve, so the divergence is visible rather than asserted.
- **3×3 correlation matrix (weight / height / life span).** Enough on its own: weight~life **−0.67**,
  height~life **−0.503**, weight~height **0.860**. It justifies a modeling choice in one glance —
  **weight is the better size proxy**: it predicts life span more strongly, and because weight and
  height are 0.860-coupled, height adds little once weight is in. Height's −0.503 is largely borrowed
  from weight. (The case asks about "size" without defining it; this is where I define it as weight,
  and why.)

### Explored, deliberately NOT shipped: trait-pair lift by size band

**Kept as an exploration artifact (`exploration/temperament_pairs_chart.png`), not a gold mart,
because it does not serve either chosen question.** It is the most striking thing in the data and it
was tempting — which is why it's worth recording *why it stayed out*. Scope discipline: a third
mart, its seven tests, and a self-join to maintain, all to answer a question nobody asked. The
finding is written down, the chart is in the repo, and the implementation is specified under "with
more time" (§3) — that costs nothing and can be built in an hour if a reviewer wants it.

**The finding.** Folk belief says big dogs are aggressive. **The word "aggressive" does not occur
once in the 46-tag vocabulary** — nor do "territorial" or "stubborn"; the vocabulary is uniformly
positive. What the descriptions *do* say: **59% of giants are `calm + protective` vs 4% of every
other band (×14.6)**, while **60% of toys are `affectionate + playful` vs 10% elsewhere (×6.1)**.
Medium and large have no strong signature (best ×2.0 and ×2.4). The claim I'd make: *"breed
descriptions associate size with calm and protective, not with aggression"* — a statement about
**editorial copy, not behaviour**. The absence of "aggressive" is a fact about who writes breed
blurbs; nobody markets a dog as aggressive. Stated that way it's defensible; as "big dogs are calm"
it isn't.

- **Why lift on *pairs*, not tag frequency:** what distinguishes a band is the *combination*.
  Single-tag counts are dominated by `intelligent` (535) and `loyal` (450) — applied to ~95% of
  breeds in **every** band, i.e. marketing vocabulary carrying zero discriminating information. Pair
  lift is association-rule counting: ~10 lines, no model, every number explainable. I tried a
  5-group trait mapping first and dropped it — bundling `protective` (0% toy → 86% giant) with the
  near-universal `alert`/`courageous` averaged the signal to nothing.
- **Baseline = all *other* bands (leave-one-out), not the overall average.** Medium + large are
  **68% of breeds**, so lift-vs-overall compares them largely against themselves — they cannot
  deviate from a baseline they dominate, which manufactures "the middle is boring". Leave-one-out
  removes that artifact and sharpens every band: giant's headline goes **×6.4 → ×14.6**.
- **Not tested for significance.** "Distinctive", never "significant". 59%-vs-4% at n=59 giants is
  not chance by any reasonable standard; medium's ×2.0 would need a test before leaning on it.

### Choosing the `size_class` boundaries (5 / 12 / 25 / 45 kg)

I tested four ways of cutting: **fixed** domain bands, **quantile** (equal-count), **1-D k-means /
Jenks natural breaks**, and a **supervised decision tree** with splits chosen to separate life span.

All four produce the same monotonic decline (≈13.2 → 10.2–11.1, spread 2.2–3.0 yr). **The conclusion
does not depend on the boundaries.** That robustness is the real result, and it frees the choice to
be made on engineering grounds rather than statistical ones:

**Fixed constants win because a data-driven cut is a bad warehouse dimension.** Quantile or k-means
boundaries recomputed on each daily refresh would drift as the source changes — a breed could move
from `medium` to `large` **without its weight changing**. That makes the dimension
non-deterministic and breaks any comparison over time. Fixed cuts are reproducible, testable, and
conventional enough (roughly the vet/AKC classes) that a PM needs no legend.

I did let the data *inform* them: k-means puts the natural low break near **13 kg**, not 10, and the
default 10–25 band swallowed 42% of breeds (median 22.2 kg). So I nudged the second cut to **12 kg**
and froze the set at **5 / 12 / 25 / 45 kg** — data-informed, then held constant and documented.

**The boundaries live in a dbt seed (`seeds/size_class_bands.csv`: label, min_kg, max_kg), not a
`CASE WHEN`.** The constants then exist once, as reviewable data in the repo, and cannot drift
between models — or between the exploration app and the warehouse, which is exactly the failure I
hit (below). `accepted_values` on `size_class` tests against the seed (§3).

**Convention: bands are half-open `[min_kg, max_kg)`.** Lower bound inclusive, upper exclusive — so
a breed at **exactly 45.0 kg is `giant`**, not `large`; at exactly 25.0 kg it is `large`, not
`medium`. This is not pedantry. I found it by prototyping the mart in SQL and getting **59 giants
where the pandas explorer said 57**: `pd.cut` defaults to *right*-closed `(min, max]`, my `CASE WHEN
mid < 45 THEN 'large' ELSE 'giant'` is half-open, and the two silently disagree.
**31 breeds — 5% of the dataset — sit exactly on a boundary** (23 on 25 kg alone; Cane Corso and
Estrela Mountain Dog on 45). Left unstated, DECISIONS.md would quote one number and a reviewer
re-running the model would get another, and the reproducibility of everything else here would be
fairly doubted. Stating the convention *is* the deliverable; the seed makes it enforceable.

Under the frozen bands + half-open convention: **toy 40 · small 104 · medium 220 · large 203 ·
giant 59** (626 breeds with a parsed weight), mean life span **13.3 / 13.2 / 13.0 / 12.2 / 10.6**.

### Units: the source never declares them

Nothing in the payload states a unit — no `unit` field, no suffix (`life_span` is `"12-15"`, not
`"12 - 15 years"`). That `weight.metric` is kg is an **inference, not a given**. I verified it in
exploration by dividing each `imperial` value by its `metric` twin across all breeds: median ratio
**2.200** over 2,108 pairs (kg→lb = 2.205), and **2.542** for height (in→cm = 2.54). Close enough to
confirm kg/cm.

An assumption that load-bearing shouldn't live only in a README, so it becomes a **dbt test —
specified here, built in the dbt/testing milestone** (§3): assert the median imperial:metric ratio
stays within tolerance of 2.205 / 2.54. If the
source ever silently switches units or swaps the fields, every downstream number — `size_class`,
the life-span story — would shift while still looking plausible. The test turns a silent corruption
into a loud red build. This is exploration paying for itself: the check exists *because* profiling
surfaced the missing-unit risk.

---

## 1. Extraction & ingestion — **[TOOL: dlt / hand-rolled Python + requests]**

- **Chose:** _[state the tool]_
- **Why:** _[idempotency handling, raw payload preserved untouched, partitioning by run date]_
- **Idempotency approach:** _[full-refresh replace vs upsert on breed_id — and why full-refresh is defensible for a tiny static set]_
- **Failure handling:** _[retry with backoff on transient API errors; validate completeness before promoting; on failure, fail loudly and DO NOT overwrite last-good curated data]_
- **Traded off:** _[e.g. chose simplicity over incremental-load machinery the data doesn't need]_
- **With more time:** _[change-detection via row hashing; a proper run-metadata/audit table]_

## 2. Database / warehouse — **DuckDB**

- **Chose:** DuckDB (embedded, file-based).
- **Why:** The workload is **analytical (OLAP)** — scan-and-aggregate queries, not transactional
  row lookups — so a column-oriented analytical engine is the right fit, not MySQL/Postgres
  (OLTP). DuckDB is zero-infrastructure, reads JSON/Parquet natively (trivial ingestion), and is
  the modern default for local analytics.
- **Layering:** raw (bronze) → staging (silver) → marts (gold). _[note schema/file layout]_
- **Traded off:** no always-on warehouse / no cloud — fine for a POC; a real deployment might use
  MotherDuck or BigQuery for shared access.
- **With more time:** _[MotherDuck for a hosted shared copy]_

## 3. Transformation & modeling — **dbt Core**

- **Chose:** dbt Core with the `dbt-duckdb` adapter.
- **Why:** transformations as version-controlled SELECTs, automatic dependency ordering via
  `ref()`, built-in tests, generated docs + lineage, dev/prod parameterization. Brings
  software-engineering discipline to the transformation layer.
- **What I modeled and why:** four gold objects, one per job the dashboard actually has. Every tile
  in §0 reads one of them; nothing is computed in the dashboard.
  **Names are canonical in SPEC.md** — SPEC is the single source of truth for schema, exactly as the
  seed is for the bucket constants. (I drifted to `dim_breed` / `bridge_breed_temperament` /
  `mart_size_class_summary` while reasoning here and reconciled back; the same drift the seed
  argument is about, one level up.)
  | model | grain | serves |
  |---|---|---|
  | `dim_breeds` | breed_id | both scatters + the record lookup |
  | `breed_temperaments` | (breed_id, temperament) | tag frequency; the queryable temperament list |
  | `mart_size_class_summary` | size_class | the count bars + mean-life-span line + the table |
  | `mart_size_vs_lifespan` | breed | the per-breed scatters |
  | `mart_metric_correlation` | (metric_a, metric_b) | the 3×3 correlation matrix |
  | `mart_size_scaling_fit` | one row | the isometry exponent + its curve |

  `dim_breeds` carries `weight_min_kg` / `weight_max_kg` / `weight_mid_kg` (same shape for height and
  life span) plus `size_class` — min/max/mid as separate typed columns so the midpoint rule is
  **visible and testable**, not an artifact of a regex. **`mart_size_class_summary` consolidates
  what was `mart_weight_distribution`**: one mart per grain, since two marts keyed on `size_class`
  is drift waiting to happen.

  **Fits and correlations are computed by dbt at pipeline time, never in the dashboard.** Both are
  plain SQL aggregates (`corr(x, y)`; `regr_slope(ln(weight), ln(height))`), so the numbers quoted in
  the narrative are built, tested and reproducible rather than recomputed live by the read layer —
  the same "logic lives in gold" line I draw everywhere else. Each carries **`n_breeds`**, because a
  correlation without its population is not a fact — and the population choice moves the number:
  **pairwise** (each pair uses its own non-null rows) gives height↔weight **0.860 / k=2.07** on 626
  breeds, where **listwise** (breeds with all three metrics) gives **0.851 / k=2.03** on 586. SPEC
  fixes pairwise; the earlier figures in this file were listwise, from the pandas explorer.
- **Messy-field handling:**
  - `life_span` "12-15" (no "years" suffix; 6.4% null) → `life_span_min_years`, `life_span_max_years`, midpoint
  - `weight`/`height` `.metric` → `weight_min_kg`, `weight_max_kg` (+ height) — see units note below
  - `temperament` comma-list → bridge table `breed_temperaments`, tags **lowercased+trimmed** (66→46 tags once case-folded)
  - `size_class` derived from weight midpoint → **5 / 12 / 25 / 45 kg**, fixed constants, data-informed but frozen (rationale in §0)
  - `'unknown'` string sentinels (2 weight, 2 height) → NULL **before** casting, else they poison numeric parsing
  - duplicate "Caucasian Shepherd Dog" (ids 70 & 269) → dedupe in staging, keep more-complete row
- **Units & sex-specific ranges (the one real modeling judgment):** The API declares units
  nowhere, so I inferred metric = kg/cm from the imperial:metric ratio (~2.205 for weight,
  ~2.54 for height) and specified a dbt test asserting the ratio stays plausible — **to be built in
  the dbt/testing milestone** (see Tests below) — to catch a silent
  source change. Weight/height arrive mostly (430/628) as sex-specific ranges
  ("Male: X-Y; Female: A-B"). I collapse each to a **whole-breed envelope** — `weight_min_kg` =
  overall min, `weight_max_kg` = overall max — and store `weight_mid_kg` = (min+max)/2 as an
  **explicit derived column in gold**, from which `size_class` is bucketed. I chose the envelope
  midpoint over averaging per-sex midpoints *deliberately*: they diverge for ~65% of sex-specific
  breeds, enough to flip a breed's size class near a bucket boundary, and `size_class` is one of
  my two dashboard answers. Keeping min/max/mid as typed columns makes the rule visible and
  testable rather than an artifact of the parser's regex. Male/female as separate columns would be
  a product feature the breed-level size questions don't need — noted under "with more time".
  `life_span` "12-15" → 13.5 is the midpoint of the published range, so the narrative says
  "predicted lifespan (midpoint of published range)", not a real prediction.
- **Tests (≥3):** unique + not_null on `breed_id`; `accepted_values` on `size_class` **against the
  seed**; custom: `life_span_min <= life_span_max` (and the same for weight/height); range checks on
  weight/life span; `breed_temperaments` unique on (breed_id, temperament). Plus two the exploration
  earned:
  - **imperial:metric ratio** (custom) — median ratio within tolerance of 2.205 (weight) / 2.54
    (height). The source declares no units; this is the tripwire for a silent unit switch.
  - **junk-tag guard** (custom, warn) — flag any temperament tag over ~3 words. Catches the literal
    tag `"variable depending on ancestry and individual traits"` found in profiling, and the whole
    class of free-text leaking into a controlled vocabulary — not just that one instance.
  - **duplicate breed:** "Caucasian Shepherd Dog" exists twice (ids 70 & 269) → deduped in staging
    keeping the more-complete row; the `unique` test on `breed_id` alone would not have caught it.
- **Two kinds of test, two severities (the deliberate call).** My tests split into **hard
  invariants** — things true by the logic of the data (min ≤ max, PK unique, no `'unknown'` sentinel
  surviving into a numeric) — and **distributional guards**, which encode "this run looks like a
  normal run" (row count ~628, null rates, the size of the `unknown` bucket).
  - **Invariants are `error`.** Logically broken data must not ship.
  - **Distributional guards are `warn`.** A row-count jump or a null-rate spike might be a real
    regression *or* legitimate drift — if the API genuinely adds 40 breeds, auto-failing the build
    blocks a perfectly good run. A human should judge "real problem or legitimate change?", so the
    signal must be loud, not fatal. (dbt's `warn_if` / `error_if` give a graduated band if a
    catastrophic threshold is ever wanted: warn at 5% deviation, error at 25%.)
  - **Why the guards exist:** a pipeline with only invariants is blind to a whole failure mode —
    **data that degrades without breaking any invariant**. A run returning 300 null weights, or `""`
    instead of `"unknown"`, is *valid*: min ≤ max still holds, the PK is still unique. Every hard
    test goes green, CI reports success, and the dashboard quietly renders a half-empty
    distribution. Silent, passing, and visible only to whoever wonders why the chart looks wrong.
    The guards turn that into a red flag — the same job `assert_unit_ratio_plausible` already does
    for the inferred units, generalised to nulls and counts.
  - **Scoped to three, on purpose.** `unknown` bucket ≤ 1%, row count ±5%, life-span null rate
    ≤ 10%. The `unknown` guard is the most valuable because it defends a *chosen deliverable* — the
    weight-distribution chart is visibly wrong the moment that bucket grows. Three wired properly
    beats ten half-wired; this is a bonus that sits on top of the fundamentals, not a substitute
    for them.
- **Where computation lives:** business logic (parsing, derived attributes, key aggregations) is
  pushed **upstream into the gold layer**, so the dashboard stays thin and the logic is
  centralized, tested, and reusable. _[state this explicitly — it's a key design point]_
- **Traded off:** _[rich dim_breeds + a couple of marts vs a mart-per-question — avoided both
  under- and over-modeling]_
- **With more time — `mart_temperament_pair_lift`** (the §0 finding, specified but not built).
  Grain **(size_class, tag_a, tag_b)**; ≤ ~5k rows, so cost is irrelevant and the only real question
  is correctness:
  - **Self-join the bridge on `breed_id` with `WHERE a.tag < b.tag`.** The strict `<` is what makes
    each unordered pair appear once and excludes self-pairs; it is the model's load-bearing
    invariant. Leave-one-out lift = `(in_band/band_breeds) / ((total_pair − in_band)/(total_breeds −
    band_breeds))`.
  - **Store counts, not conclusions:** every pair with `in_band`, `band_breeds`, `pct_in_band`,
    `pct_other_bands`, `lift`. The `≥25%` support threshold and the top-3 cut are **presentation**
    and stay in the read layer — bake them into gold and you cannot change the top-N without a
    rebuild.
  - **The seven tests** — these are the invariants the derived-on-derived logic assumes, not padding:
    1. `unique` on (size_class, tag_a, tag_b) — the grain holds
    2. `not_null` on the three keys + `lift`
    3. **`tag_a < tag_b`** (custom) — canonical ordering; a `<=` typo silently creates self-pairs
       (`calm + calm`) that no eyeball catches
    4. `pair_breed_count <= band_breed_count` — a pair cannot occur more often than there are breeds
    5. `pct_in_band` between 0 and 100; `lift > 0`
    6. `relationships`: `tag_a` and `tag_b` both exist in `breed_temperaments.temperament`
    7. `accepted_values` on `size_class` against `seeds/size_class_bands.csv`
  - **Upstream prerequisite:** `breed_temperaments` **unique on (breed_id, temperament)**. The pair
    join assumes it; one duplicated tag double-counts the pair and inflates the lift silently.
- **With more time:** _[snapshots for slowly-changing history; more granular marts]_

## 4. Version control — **GitHub**

- **Chose:** GitHub, _[public / private + viewer access]_.
- **Why / discipline:** meaningful **incremental commit history** (one commit per milestone, not
  one giant final commit); secrets kept out of the repo (API key in `.env` gitignored locally,
  GitHub Actions secret in CI); a README another engineer could follow.
- **With more time:** _[branch protection, PR templates]_

## 5. CI / CD — **GitHub Actions**

- **Chose:** GitHub Actions.
- **Why:** tests + `dbt build` run on every PR (visible green/red status); a scheduled run on a
  daily cron deploys/refreshes on merge to main.
- **Traded off:** _[Actions over a managed orchestrator — see layer 6]_
- **With more time:** _[artifact upload of dbt docs; Slack/email alert on failed run]_

## 6. Orchestration & scheduling — **GitHub Actions cron (NOT Airflow)**

- **Chose:** the cron scheduler built into GitHub Actions, daily at **02:00 UTC**.
- **Why (the deliberate right-sizing call):** this is **one daily job**. Standing up Airflow /
  Dagster / Prefect for a single scheduled task is operational overhead I can't justify. Actions
  cron runs it reliably, unattended, with visible pass/fail status in the run log. _[This is the
  choice they said they'd "gently push on" if over-built — I'm deliberately under-building here
  and can defend it.]_
- **Freshness visibility:** the Actions run status (last run green/red + logs) + a `loaded_at`
  timestamp column on the curated data + _[optional run-metadata table]_.
- **With more time:** Dagster if the DAG grew beyond a handful of steps or needed richer
  backfills/observability.

## 7. Dashboard & visualization — **[Streamlit / Evidence.dev]**

- **Chose:** _[tool]_, delivered as _[PDF export / screenshots in README / hosted link]_.
- **Questions answered (≥2):** _[which of the four, e.g. size vs life span; weight-class
  distribution]_
- **Narrative:** the README says **what the data says** (e.g. "smaller breeds tend to live
  longer"), not just what the charts show.
- **Thin by design:** reads the gold marts, minimal presentation logic only.
- **With more time:** _[hosted deploy on Streamlit Cloud; more questions; interactivity]_

## Bonus — LLM enrichment **[if fundamentals are solid first]**

- **Feature:** turn free-text `temperament` / `bred_for` into a structured column
  (`energy_level` score or `good_with_kids` flag), folded back into the dbt model as a real column.
- **Engineering treatment (not magic):** where it sits in the pipeline _[enrichment step between
  raw and staging / a separate model]_, how it's prompted, **cost & latency** _[batch all breeds
  once per run; ~N tokens; cache so unchanged breeds aren't re-called]_, and a **light output
  eval** _[schema-valid, value in expected range, spot-check against a few hand-labels]_.
- **Why this over a flashier bonus:** a small evaluated feature beats a large eyeballed one — and
  it plays to my applied-LLM background (same unstructured→structured pattern as my other work).

---

## What I'd build next given another week
_[3–5 bullets: run-metadata/audit table + alerting; change detection; hosted dashboard; more
marts; snapshots for history; IaC (Terraform) for reproducibility]_
