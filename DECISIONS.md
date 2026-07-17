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

**Shape of the source.** **628 breeds in raw; 627 in `dim_breeds`** after the Caucasian Shepherd
dedupe — the two are not interchangeable and every gold-grain number below is post-dedupe. `id` is
unique and non-null (**primary key confirmed**). Weight parses for **625/627** (the 2 misses are
`'unknown'` sentinels), `life_span` for **587** (6.4% null). So every chart below runs on **585
breeds** with weight + life span both present — small enough that the honest framing is
"descriptive of this dataset", not inferential.

> **Caught late, worth recording:** every figure in this file and SPEC was first computed **pre-dedupe**,
> because the M0.5 explorer never deduped. The dedupe is a *staging* decision made after the numbers
> were taken. Conclusions are unchanged (−0.671 → −0.670), but the counts were all one out — the
> expected distribution said `giant 59 … = 628` when `dim_breeds` yields `giant 58 … = 627`, which
> would have failed the row-count guard on day one. Recomputed post-dedupe throughout.

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
- **±1σ error bars on the mean-life-span line** (`stddev_life_span_years`, added to the same mart).
  The mean alone oversells the finding, which is the exact sin §0 already refuses on the dual axis.
  Two facts only the std shows: **the spread grows with size** (σ 0.68 small → **1.54 giant** — giant
  breeds are shorter-lived *and* less predictable), and the toy→giant gap of 2.7 yr is **under 2σ of
  the giant band**, so the distributions overlap heavily. Honest claim: *the trend is real in the
  mean and weak for any individual dog.* A bare mean line invites the reader to conclude the
  opposite.
- **Every chart prints its population** (`mart_data_coverage`): "585 of 627 breeds; 42 excluded for
  missing weight or life span". This is not pedantry — **the missing life spans are not evenly
  spread**: toy has **29 of 40** (27.5% missing), giant has **58 of 58** (0%). The toy bar rests on
  72% of toy breeds, the giant bar on 100%, and nothing on the chart says so. A dashboard that prints
  "627 breeds" above a plot drawn from 585 is quietly lying; exposing the denominator costs one line
  and is the difference between a chart and a claim.
- **Weight vs life-span scatter.** Kept because the means hide the spread. Overall correlation is
  **−0.67**, but within any single band it's only ~−0.1 to −0.4. So: *knowing a dog's size class
  tells you a lot; knowing one giant outweighs another tells you little.* The scatter shows that
  variance honestly; a bar chart alone would oversell −0.67. (I explored a per-band correlation
  matrix that made this precise, and dropped it — too much machinery for the point. The sentence
  survives; the table doesn't.)
- **Top temperaments per size class, as a % of the class.** This is what makes **temperament** — one
  of the three fields the brief names — a headline fact instead of a bridge table nobody opens.
  `Giant: calm 72% · protective 61%` / `Toy: alert 68% · playful 63%`, and the narrative writes
  itself: *temperament varies systematically with size.* One `GROUP BY size_class, temperament` over
  two tables I already have.
  - **Percentage, not raw count** — and that's the whole subtlety. Raw counts favour big classes:
    220 medium breeds out-count 40 toy breeds on every tag purely by existing. Normalising *within*
    the class makes them comparable. Note what this deliberately is **not**: no lift, no baseline, no
    leave-one-out. Dividing by the group size is arithmetic; comparing against a baseline is
    inference. That distinction is exactly the line between this mart and the pair-lift one below.
  - **Top-N lives in the dashboard, not the mart.** Gold holds every (class, tag) pair; the read
    layer takes the top 3–5. Bake the cut into gold and you can't change it without a rebuild.
- **3×3 correlation matrix (weight / height / life span).** Enough on its own: weight~life **−0.670**
  (n=585), height~life **−0.502** (n=585), weight~height **0.860** (n=625). It justifies a modeling choice in one glance —
  **weight is the better size proxy**: it predicts life span more strongly, and because weight and
  height are 0.860-coupled, height adds little once weight is in. Height's −0.502 is largely borrowed
  from weight. (The case asks about "size" without defining it; this is where I define it as weight,
  and why.)

### Explored, deliberately NOT shipped: the isometry break (height vs weight)

**A genuine finding, cut from the delivery.** Weight scales as **height^2.07**, not the **height^3**
geometric similarity predicts (log-log fits better: R² 0.86 vs 0.74 linear) — **dog breeds get
proportionally lighter as they get taller**; tall breeds are built long and lean, not scaled-up
small dogs. It was specified as a gold mart (`mart_size_scaling_fit`) and a dashboard curve, and
**removed before either was built**.

**Why it's out:** the brief asks for "a curated analytics layer exposing facts about dog breeds
(life span, size class, temperament, and so on)". An isometry exponent is not a fact about a dog —
it's an inference about allometry, answering a question nobody asked, in a language the audience
doesn't speak. It was the most intellectually satisfying thing in the data, which is precisely the
reason to be suspicious of it: I'd have been building it because *I* found it interesting.

**The rule it establishes, applied consistently:** **descriptive fact → gold; inferential cleverness
→ DECISIONS.md.** `mart_size_class_temperaments` (count, normalised within a group) is on the ships
side. This and the pair-lift below are not. `mart_metric_correlation` **stays** — its rows are about
life span, which is the actual question, and a correlation is legible where a fitted exponent isn't.

Cost of removing it: none. It costs one paragraph here and no build, no tests, no maintenance.

### Explored, deliberately NOT shipped: trait-pair lift by size band

**Kept as an exploration artifact (`exploration/temperament_pairs_chart.png`), not a gold mart,
because it does not serve either chosen question.** It is the most striking thing in the data and it
was tempting — which is why it's worth recording *why it stayed out*. Scope discipline: a third
mart, its seven tests, and a self-join to maintain, all to answer a question nobody asked. The
finding is written down, the chart is in the repo, and the implementation is specified under "with
more time" (§3) — that costs nothing and can be built in an hour if a reviewer wants it.

**The finding.** Folk belief says big dogs are aggressive. **The word "aggressive" does not occur
once in the 46-tag vocabulary** — nor do "territorial" or "stubborn"; the vocabulary is uniformly
positive. What the descriptions *do* say: **60% of giants are `calm + protective` (35/58) vs 4% of
every other band (23/569) — ×14.9**, while **60% of toys are `affectionate + playful` vs 10%
elsewhere (×6.1)**.
Medium and large have no strong signature (best ×2.0 and ×2.4). The claim I'd make: *"breed
descriptions associate size with calm and protective, not with aggression"* — a statement about
**editorial copy, not behaviour**. The absence of "aggressive" is a fact about who writes breed
blurbs; nobody markets a dog as aggressive. Stated that way it's defensible; as "big dogs are calm"
it isn't.

- **Why lift on *pairs*, not tag frequency:** what distinguishes a band is the *combination*.
  Single-tag counts are dominated by `intelligent` (536) and `loyal` (450) — applied to ~95% of
  breeds in **every** band, i.e. marketing vocabulary carrying zero discriminating information. Pair
  lift is association-rule counting: ~10 lines, no model, every number explainable. I tried a
  5-group trait mapping first and dropped it — bundling `protective` (0% toy → 86% giant) with the
  near-universal `alert`/`courageous` averaged the signal to nothing.
- **Baseline = all *other* bands (leave-one-out), not the overall average.** Medium + large are
  **68% of breeds**, so lift-vs-overall compares them largely against themselves — they cannot
  deviate from a baseline they dominate, which manufactures "the middle is boring". Leave-one-out
  removes that artifact and sharpens every band: giant's headline goes **×6.5 → ×14.9**.
- **Not tested for significance.** "Distinctive", never "significant". 60%-vs-4% at n=58 giants is
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
where the pandas explorer said 57** (both **pre-dedupe** — the same prototype today gives 58, since
the duplicate Caucasian Shepherd is itself a giant; the 59-vs-57 *gap* is the finding, not the 59):
`pd.cut` defaults to *right*-closed `(min, max]`, my `CASE WHEN
mid < 45 THEN 'large' ELSE 'giant'` is half-open, and the two silently disagree.
**31 breeds — 5% of the dataset — sit exactly on a boundary** (23 on 25 kg alone; Cane Corso and
Estrela Mountain Dog on 45). Left unstated, DECISIONS.md would quote one number and a reviewer
re-running the model would get another, and the reproducibility of everything else here would be
fairly doubted. Stating the convention *is* the deliverable; the seed makes it enforceable.

Under the frozen bands + half-open convention: **toy 40 · small 104 · medium 220 · large 203 ·
giant 58** (625 breeds with a parsed weight, post-dedupe), mean life span **13.3 / 13.2 / 13.0 / 12.2 / 10.6**.

### Units: the source never declares them

Nothing in the payload states a unit — no `unit` field, no suffix (`life_span` is `"12-15"`, not
`"12 - 15 years"`). That `weight.metric` is kg is an **inference, not a given**. I verified it in
exploration by dividing each `imperial` value by its `metric` twin across all breeds: median ratio
**2.200** over 2,108 pairs (kg→lb = 2.205), and **2.542** for height (in→cm = 2.54). Close enough to
confirm kg/cm.

An assumption that load-bearing shouldn't live only in a README, so it becomes a **dbt test**
(`assert_unit_ratio_plausible`, built in M2). If the source ever silently switches units or swaps
the fields, every downstream number — `size_class`, the life-span story — would shift while still
looking plausible. The test turns a silent corruption into a loud red build. This is exploration
paying for itself: the check exists *because* profiling surfaced the missing-unit risk.

**The ratio directions differ, and I got this wrong first.** I wrote "median **imperial:metric**
ratio near 2.205 (weight) / 2.54 (height)" here and in SPEC. That is arithmetically impossible:

| metric | which side is the bigger number | assertion | bounds (±5%) |
|---|---|---|---|
| weight | **imperial** (7 lb vs 3.2 kg) | `imperial/metric` ≈ **2.205** lb/kg | [2.095, 2.315] |
| height | **metric** (23 cm vs 9 in) | `metric/imperial` ≈ **2.54** cm/in | [2.413, 2.667] |

In the imperial:metric direction height is **0.394** (= 1/2.54). I'd copied the pair "2.205 / 2.54"
from my exploration notes without noticing the exploration had computed height the *other* way
round. **The test caught it on its first run against real data, before the model it guards even
existed** — which is the clearest argument for the contract-first order I'm going to make all week:
a test written from the data found an error in the spec written from the same data.

**The test deliberately does NOT reuse the model's parser** — and this is the part worth defending.
It reads `source('raw', 'breeds')`, not `ref('stg_breeds')`, and re-implements a simpler
first-number extraction of its own. Reusing `stg_breeds`' parsed columns would be less code and
strictly worse: **a test that shares the implementation's code agrees with it by construction.** If
the regex mis-extracts, both the model and the test mis-extract identically, the ratio still looks
like 2.205, and the test reports green while the data is wrong. The duplication *is* the feature —
it makes this a genuine second opinion rather than the parser grading its own homework. The same
reasoning is why the test takes only the first number (it needs a ratio, not an envelope) instead of
importing the min/max logic.

---

## 1. Extraction & ingestion — **hand-rolled Python + `requests` + `tenacity`**

- **Chose:** `ingestion/ingest.py` — `requests` for one GET, `tenacity` for retry/backoff, DuckDB's
  Python API for the write. No `dlt`.
- **Why not `dlt`:** dlt earns its keep on many sources, schema evolution, and incremental state.
  This is *one* endpoint returning *one* JSON array. dlt would add a dependency and a layer of
  its own abstractions between me and the two properties that actually matter here (idempotency,
  partial-failure safety) — and I'd be explaining dlt's semantics in the debrief instead of my own.
  ~90 lines of explicit Python is the right size. If a second and third source appeared, dlt starts
  winning.
- **Raw is untouched:** each breed lands as verbatim JSON in `raw.breeds.payload`. No parsing, no
  casting, no cleaning — that is dbt's job. If the parser turns out to be wrong, raw is still the
  truth and we rebuild without re-fetching. `breed_id` is lifted out beside the payload as the
  partition key (so idempotency is expressible in SQL); it's a key, not an interpretation.
  Note the API returns `id` as a **string** (`"id":"1"`) — another reason raw stays verbatim and
  the INTEGER cast is a staging decision.

### Stateless: every run re-fetches and rebuilds. **The API is the source of truth.**

- **Chose:** the pipeline holds **no state between runs**. Each run fetches the full breed list and
  rebuilds silver/gold from scratch. A fresh, empty warehouse is a supported starting point, not a
  failure — which is exactly what GitHub Actions hands us, since every run gets a new VM and
  `dogs.duckdb` does not survive it.
- **Verified end-to-end at M5, not just asserted.** This claim sat here unproven for two days: M1
  only ever tested the *ingestion* half against an empty file, and "the rest rebuilds fine" was an
  argument, not a result. Against a warehouse that did not exist,
  `DBT_DUCKDB_PATH=/tmp/fresh.duckdb ./scripts/run_pipeline.sh` reproduced **every** published
  number from nothing: **628** raw rows in **1** partition → **627** `dim_breeds` → **3,538** bridge
  rows → coverage **627 / 585 / 42**, toy **29/40** vs giant **58/58**, and `PASS=45 WARN=0
  ERROR=0`. That is the CI VM's exact starting condition, so CI is not a special case — it's the
  same run. Worth the ten minutes: the whole statelessness argument rests on this working, and I'd
  have found out at 02:00 on the first cron otherwise.
- **Why (and this reverses an earlier decision):** I first designed raw to **accumulate** one
  628-row partition per `run_date`, to keep a history of long-term change. Then the CI question
  exposed what that actually costs: to keep that history I'd have to bolt persistence onto the
  pipeline (MotherDuck, S3, an Actions cache) purely to protect it. On a source this static the
  history was near-worthless anyway — I'd be storing 628 identical rows a day to record that nothing
  had changed. Dropping the requirement removes the persistence problem instead of solving it.
  Stateless is simpler, more robust, and has **no drift failure mode**: there is no stale state that
  can silently disagree with the API.
- **`run_date` still partitions raw** — the case study explicitly asks for partitioning by run date,
  it costs nothing, and it is the mechanism that makes the write idempotent: DELETE+INSERT of the
  day's partition, so a re-run replaces rather than appends. In CI exactly one partition ever
  exists. Locally, where the file *does* persist, partitions accumulate as a **side effect** — not a
  designed feature — which is why **`stg_breeds` still filters to the latest `run_date`**
  (`where run_date = (select max(run_date) from raw.breeds)`). One line, and it makes a local run
  behave exactly like CI instead of double-counting on day two.
- **The cost, stated honestly:** with no prior partition, the completeness check has no last-good
  count to compare against and falls back to the **fixed 628 baseline** from M0 profiling. It still
  catches a truncated pull (<565), but the floor no longer tracks reality: if the API grew to 700
  breeds, CI would keep measuring against 628 until I bumped the constant. A persistent warehouse is
  what makes that floor self-updating — this is the concrete thing statelessness costs.
- **With more time / if change-history were a requirement:** durable storage — **MotherDuck** (hosted
  DuckDB the dashboard connects to directly) or a `.duckdb`/Parquet file in **S3/GCS** — plus an
  **SCD-2 / dbt snapshot** so a row is appended only when a breed actually *changes*, rather than a
  full daily copy of an unchanged table. That is the scale answer. It is not this POC's answer, and
  the difference is the whole point: I'd add it when someone can name a question that needs
  "what did this breed look like last month?", not before.

### Failure handling: nothing is promoted until it's proven

- **Retry only what a retry can fix:** backoff (exponential, 2→30s, 5 attempts) on timeouts,
  connection errors, 429 and 5xx. A **403 fails immediately** — retrying a bad key five times just
  delays the real error message.
- **Validate before touching the warehouse:** structure (is it a breeds array?), the PK claim (`id`
  present, non-null, unique — the assumption SPEC.md rests on), then completeness.
- **Completeness is a tolerance, not equality:** a run must return ≥ **90%** of a reference count —
  the **last-good partition** when one exists (a persisted local run), otherwise the **M0 baseline of
  628**, which is the branch stateless CI always takes. Today's own partition is excluded from the
  reference, or a re-run would compare the fetch against itself and validate nothing. Equality would
  be wrong: **629 breeds is real data, not an error**. A truncated 300-breed pull is what this
  catches. Drift *within* the band is surfaced by the **warn**-severity row-count test in dbt (§3),
  not by failing the job — legitimate growth must not auto-fail the build.
- **Atomic promote:** `DELETE` the partition + `INSERT` inside one transaction, so a crash mid-write
  rolls back to the previous partition instead of leaving a half-written day. Verified end-to-end:
  a bad key, a missing key, and a truncated payload all exit 1 with `raw.breeds` still holding 628.
- **The key is never logged** — it exists only in the `x-api-key` header. Local: gitignored `.env`.
  CI: a GitHub Actions secret, or the cron 403s.
- **With more time:** change-detection via row hashing (the SCD-2 point above), and a proper
  `raw.ingestion_runs` audit table (run id, status, row count, duration) instead of stdout logs.

## 2. Database / warehouse — **DuckDB**

- **Chose:** DuckDB (embedded, file-based).
- **Why:** The workload is **analytical (OLAP)** — scan-and-aggregate queries, not transactional
  row lookups — so a column-oriented analytical engine is the right fit, not MySQL/Postgres
  (OLTP). DuckDB is zero-infrastructure, reads JSON/Parquet natively (trivial ingestion), and is
  the modern default for local analytics.
- **Layering:** one file, `dogs.duckdb`, four schemas — the layers are *schemas*, not folders, so
  the boundary is enforced by the warehouse rather than by convention:

  | schema | holds | written by | materialized |
  |---|---|---|---|
  | `raw` | `breeds` — verbatim JSON + `run_date`, `loaded_at` | **`ingest.py`**, never dbt | table |
  | `main` | `size_class_bands` (the seed) | `dbt seed` | table |
  | `main_staging` | `stg_breeds`, `stg_breed_temperaments` | dbt | **view** |
  | `main_marts` | `dim_breeds`, the bridge, 5 marts | dbt | **table** |

  (dbt *concatenates* a custom schema onto the target's, so the config says `staging` and you get
  `main_staging`. Writing `main_staging` yields `main_main_staging` — a five-minute lesson.)

### Materialization: **views for staging, tables for marts** — and the scale answer

Set once per layer in `dbt_project.yml`, never per model: a model that has to know where it lives
is a model you can't move.

**A view is a saved query, not rows.** `stg_breeds` stores zero data — it *is* the parser, and the
regex re-executes on every read. It's read **~12× per build** (10 of its own tests + the two
downstream models). A table pays the parser **once** and the 12 reads become cheap scans.

**Measured**, on a 628,000-row synthetic source (1000× the real one, to make the gap visible):

| | build | 12 reads | total |
|---|---|---|---|
| view | 0.00s | 0.75s | **0.75s** |
| table | 0.14s | 0.00s | **0.15s** |

**So why is staging still a view?** Because at **628 rows** that entire cost is ~1ms × 12, and a
view buys two things a table can't: **zero storage**, and it **cannot go stale** — it's consistent
with `raw` by construction, whereas a table is a snapshot until dbt rebuilds it. Staging is a
parse-and-type pass with exactly one consumer (marts), so re-running it is free and never wrong.

**Marts are tables for the mirror-image reason:** the dashboard reads them repeatedly and on demand,
so the read path must never re-execute the parser. Build once, scan many.

**The rule, and the crossover:** *views for a cheap pass with one consumer; tables for what's read
repeatedly.* You flip when `reads × parse_cost > storage + rebuild_cost` — which at 100M rows is a
6-minute recomputation of an identical answer versus a few GB of disk. **Storage is cheap; repeated
compute isn't.** And the flip is **one line in `dbt_project.yml`, no SQL touched** — which is the
real point: the materialization is a deployment decision, not a modelling one, so it stays out of
the models entirely.

_(One trap, verified: a **contract constraint on a view is silently ignored** — `PASS`, no warning.
So contracts only mean anything on the marts. On staging they'd be theatre. See §3.)_

- **Traded off:** no always-on warehouse / no cloud — fine for a POC; a real deployment might use
  MotherDuck or BigQuery for shared access.
- **With more time:** MotherDuck for a hosted shared copy — the same dbt code, one profile change.

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
  | `dim_breeds` | breed_id | **internal** — the marts' building block. Nothing outside dbt reads it |
  | `breed_temperaments` | (breed_id, temperament) | **the brief's "queryable" deliverable** — read by humans with SQL, not by the dashboard |
  | `mart_size_class_summary` | size_class | the count bars + mean-life-span line + the table |
  | `mart_size_vs_lifespan` | breed | the per-breed scatters |
  | `mart_metric_correlation` | (metric_a, metric_b) | the correlation numbers + the size=weight evidence |
  | `mart_size_class_temperaments` | (size_class, temperament) | top tags per size class, as % of class |
  | `mart_data_coverage` | one row | what each chart drops — 627 total, 585 plotted |

  `dim_breeds` carries `weight_min_kg` / `weight_max_kg` / `weight_mid_kg` (same shape for height and
  life span) plus `size_class` — min/max/mid as separate typed columns so the midpoint rule is
  **visible and testable**, not an artifact of a regex. **`mart_size_class_summary` consolidates
  what was `mart_weight_distribution`**: one mart per grain, since two marts keyed on `size_class`
  is drift waiting to happen.

  **Correlations are computed by dbt at pipeline time, never in the dashboard.** `corr(x, y)` is a
  plain SQL aggregate, so the numbers quoted in the narrative are built, tested and reproducible
  rather than recomputed live by the read layer — the same "logic lives in gold" line I draw
  everywhere else. It carries **`n_breeds`**, because a correlation without its population is not a
  fact — and the population choice moves the number: **pairwise** (each pair uses its own non-null
  rows) gives height↔weight **0.860** on 625 breeds, where **listwise** (breeds with all three
  metrics) gives **0.851** on 585. SPEC fixes pairwise; the earlier figures in this file were
  listwise, from the pandas explorer.

  **Cut before building: `mart_size_scaling_fit`** (the isometry fit, `weight ~ height^k`, k=2.07,
  R²=0.864) **and the height-vs-weight curve it fed.** The brief asks for "a curated analytics layer
  exposing facts about dog breeds (**life span, size class, temperament**, and so on)". A log-log
  regression exponent is a nice data-science finding and *not* a fact about a dog — it answers a
  question nobody asked, in a language the audience doesn't speak. It survives here as a recorded
  finding (§0) and nowhere else. **`mart_metric_correlation` stays and ships**: its rows are about
  life span, which *is* the question, and a correlation coefficient is legible in a way a fitted
  exponent isn't. The line I'm drawing: **descriptive fact = gold; inferential cleverness =
  DECISIONS.md.** `mart_size_class_temperaments` is on the ships side of that same line, and
  `mart_temperament_pair_lift` (below) is not — which is the consistency check on the rule.

  **Consequence:** `height_mid_cm` leaves `mart_size_vs_lifespan` — the fit and the height-vs-weight
  view were its only readers. Height stays a breed fact in `dim_breeds` and as `mean_height_cm` in
  `mart_size_class_summary`; it just stops being carried where nothing reads it.
- **Messy-field handling:**
  - `life_span` "12-15" (no "years" suffix; 6.4% null) → `life_span_min_years`, `life_span_max_years`, midpoint
  - `weight`/`height` `.metric` → `weight_min_kg`, `weight_max_kg` (+ height) — see units note below
  - `temperament` comma-list → bridge table `breed_temperaments`, tags **lowercased+trimmed** (66→46 tags once case-folded)

  **The duplicate-tag decision: absorb the problem, keep the signal.** A breed could ship the same
  tag twice — and our own case-folding can *create* one that isn't in the source (`"Loyal, loyal"` →
  `'loyal','loyal'`), so the risk is ours, not the API's. Three options, and I built the wrong one
  first:
  - **`DISTINCT` alone** — correct numbers, but the source could change and nobody would ever know.
  - **No `DISTINCT`, error test** (my first build) — loud, but **one odd breed fails the daily
    unattended cron**, and the fix would almost certainly *be* to add `DISTINCT` anyway.
  - **`DISTINCT` + a `warn` test that re-derives the split from `stg_breeds`** ← chosen. Correct
    numbers, a green build, *and* a visible signal. The test parses independently — reading the
    bridge would be pointless, since the `DISTINCT` has already removed the thing it's looking for.
    Same trick as `assert_unit_ratio_plausible`: **a test downstream of the fix cannot see what the
    fix hid.**

  **The severity followed the design, not the other way round.** I first called a duplicate tag a
  grain violation → `error`. That was only true *while it could reach the mart*. Once `DISTINCT`
  guarantees the grain, a repeated source tag isn't broken data in my warehouse — it's the source
  doing something new, which is **drift → warn**, exactly as the rule below says. The grain itself
  stays guarded at `error` by `assert_tag_unique_per_breed` on the model's *output*, which now does
  the job it's actually good at: catching someone deleting the `DISTINCT`. Two tests, two jobs.

  **Why a bridge, and does it scale?** The comma string is the thing that *doesn't* scale: you cannot
  index, group or join it at any size — `LIKE '%playful%'` is a full scan that also matches the wrong
  rows. The bridge is one row per (breed, tag): **3,544 rows** today (628 breeds × ~5.6 tags). This is
  the standard star-schema many-to-many, and columnar engines are built for exactly this shape —
  at 100k breeds it's ~560k rows, still trivial for DuckDB. **The grain is the right call at any
  size**; what changes with scale is two mechanical optimizations, neither altering the shape:
  **dictionary-encode the tag** (`tag_id INT` + a `dim_temperament` lookup, instead of repeating the
  string `"intelligent"` 536 times) and cluster/partition on the join key. At *this* size both would
  be premature — 3.5k rows of short strings is nothing, and an int key would cost a join to read.
  Noted here so the scaling answer is a decision, not an omission.
  - `size_class` derived from weight midpoint → **5 / 12 / 25 / 45 kg**, fixed constants, data-informed but frozen (rationale in §0)
  - `'unknown'` string sentinels (2 weight, 2 height) → NULL **before** casting, else they poison numeric parsing
  - duplicate "Caucasian Shepherd Dog" (ids 70 & 269) → dedupe in staging, keep more-complete row
- **Units & sex-specific ranges (the one real modeling judgment):** The API declares units
  nowhere, so I inferred metric = kg/cm from the ratio between the imperial and metric twins
  (weight `imperial/metric` ~2.205 lb/kg; height `metric/imperial` ~2.54 cm/in — the directions
  differ because imperial is the bigger number for weight and metric is for height, see §0) and
  built `assert_unit_ratio_plausible` to catch a silent source change. Weight/height arrive mostly (430/628) as sex-specific ranges
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
  - **unit ratio** (custom, `assert_unit_ratio_plausible`) — median within ±5% of **2.205**
    (weight, `imperial/metric`) and **2.54** (height, `metric/imperial` — the directions differ; §0).
    The source declares no units; this is the tripwire for a silent unit switch. It reads the
    SOURCE and parses independently on purpose: a test that reuses the model's parser agrees with
    it by construction and cannot catch a bug in it.
  - **junk-tag guard** (custom, warn) — flag any temperament tag over ~3 words. Catches the literal
    tag `"variable depending on ancestry and individual traits"` found in profiling, and the whole
    class of free-text leaking into a controlled vocabulary — not just that one instance.
  - **duplicate breed:** "Caucasian Shepherd Dog" exists twice (ids 70 & 269) → deduped in staging
    keeping the more-complete row; the `unique` test on `breed_id` alone would not have caught it.
- **Model contracts on gold — enforced exactly at the DAG's edge (M3).** A dbt model is just a
  SELECT: its output schema is an *accident* of whatever the SQL emits today. Rename
  `weight_mid_kg` → `weight_midpoint_kg` and `dbt build` goes **green** — then the dashboard dies
  with `KeyError` in front of whoever is watching. dbt didn't catch it because **dbt cannot see the
  dashboard**: it isn't a `ref()`, so nothing in the DAG depends on that column.
  `contract: {enforced: true}` writes the promise down and checks the model's real output against it
  *before* materializing, so **the failure moves from the consumer to the producer** — from the demo
  to CI. A contract is a **function signature for a table**.

  **The rule: contract where dbt's knowledge ends.** Not "contract gold" — *contract the boundary*.
  Everything inside the DAG is already protected for free: rename a `stg_breeds` column and
  `dim_breeds` fails at compile, because `ref()` makes that dependency visible.

  | model | consumer | contract? |
  |---|---|---|
  | `mart_size_class_summary` · `mart_size_vs_lifespan` · `mart_size_class_temperaments` · `mart_metric_correlation` · `mart_data_coverage` | the **dashboard** — outside the DAG | **yes** |
  | `breed_temperaments` | **humans with SQL** — the brief's "turn the comma list into something queryable" is a deliverable in its own right, and its reader is outside the DAG too. 3 columns, so it's the cheapest contract here | **yes** |
  | `dim_breeds` | only the marts, via `ref()` | **no** — DAG-protected, and its ~18 columns are the one genuinely expensive contract |
  | `stg_breeds` · `stg_breed_temperaments` | only marts, via `ref()` | **no** |

  **The cost, stated:** contracts are all-or-nothing — every column needs a declared `data_type`,
  maintained alongside the model, which is a second place types can drift. That's precisely why the
  line is drawn at the boundary rather than everywhere: paying it on `dim_breeds` would buy nothing
  the DAG doesn't already give.

  _(Watch the trap: a constraint on a **view** is silently ignored — `PASS`, no warning. Verified.
  So contracts only mean anything on the marts, which are tables. On staging they'd be theatre.)_
- **Two kinds of test, two severities (the deliberate call).** My tests split into **hard
  invariants** — things true by the logic of the data (min ≤ max, PK unique, no `'unknown'` sentinel
  surviving into a numeric) — and **distributional guards**, which encode "this run looks like a
  normal run" (row count **~627 at gold** — not raw's 628, see SPEC "The thresholds are `vars`" —
  null rates, the size of the `unknown` bucket).
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
  - **A `warn` nobody sees is not a signal — it's a comment.** dbt prints WARN to stdout and exits
    **0**, so CI goes green and the warning dies in a collapsed log. Choosing `warn` severity is
    therefore only half a decision; the other half is *making it visible*. M5's CI parses
    `target/run_results.json` and emits GitHub `::warning::` annotations plus a job-summary table —
    visible on the PR and the run page, **without failing the build**, which is exactly the point of
    warn. Same principle as the red-cron-nobody-sees note in §5. Without this step the entire
    warn/error split is theatre: I'd have carefully classified tests into a bucket that no human
    ever reads.
  - **Scoped to TWO, and the third was cut in M4 — the more useful story.** What survives:
    `unknown` bucket ≤ 1% and life-span null rate ≤ 10%. The `unknown` guard is the most valuable
    of anything here because it defends a *chosen deliverable* — the weight-distribution chart is
    visibly wrong the moment that bucket grows, while every hard test still passes. Two wired
    properly beats ten half-wired; this is a bonus on top of the fundamentals, not a substitute.

    **What I cut, and why it's the most instructive decision in this section.** SPEC specified
    "row count 628 ±5%" from M0. At M4 I found the constant was wrong (628 is *raw*; `dim_breeds`
    is **627**) and fixed it to 627 — a guard that had been comparing against a number the pipeline
    never produces, sitting ~1 breed inside its own tolerance, **green forever for the wrong
    reason**. Then, challenged on why the guard existed at all, three things fell out:
    - **It was blind to the failure I justified it with.** I claimed it caught a staging bug
      silently dropping breeds. Measured: silent at losing 1, 5, or **31** breeds; it woke at 32.
    - **It rotted by construction.** `expected_breed_count` is hand-maintained, so an API growing
      to 667 warns on *every run* until someone edits it. **A permanent warning is wallpaper** —
      the exact failure I'd removed from `assert_tag_not_freetext` three files earlier, and
      reintroduced without noticing.
    - **An exact reconciliation was available the whole time.** The dedupe is *by name*, so
      `dim_breeds` must equal the distinct breed names in raw's latest partition — **exactly**,
      no constant, self-updating, fires on **one** lost breed. That's `assert_no_breed_lost`, and
      it's `error`, not `warn`: losing a breed between raw and gold is a **bug in my code**, not
      drift in the world. Verified by mutation (dedupe by `breed_group`): `expected 627, actual
      26, lost -601` — build stops.

    **The rule this leaves, which generalises past this project:** *if a guard needs a number a
    human must remember to update, look for an exact reconciliation against something the pipeline
    already knows.* Both survivors are **rates**, and that's why they don't rot — a rate stays
    meaningful when the source grows; a count does not.

    **What we gave up, stated honestly:** nothing now reports that the *source changed size* —
    `assert_no_breed_lost` confirms 667 == 667 and stays quiet. That is **out of scope by
    construction**: "changed since yesterday?" requires state, and §1 chose statelessness
    deliberately. A constant is the only stateless substitute and constants rot. The signal
    survives maintenance-free in two places that already exist: `ingest.py` logs the fetched count
    against its ≥90% floor, and `mart_data_coverage.total_breeds` is printed beside every chart.
- **I audited the whole test suite before wiring CI — and cut it from 68 to 35.** This was a
  deliberate stop, taken *because* M5 was next. CI is about to turn "68 tests passing" into a green
  badge on a PR, and a badge is a **claim**. I didn't want to publish a number I hadn't checked, so
  I read all 68 and asked one question of each: **can this test fail?** Not "is it likely to" —
  *can it, at all.* **33 could not.** The full inventory, with the reason for each cut, is in SPEC
  ("CUT at M4 (33) — structurally unfireable"). The shape of it:
  - **4 source `not_null`** — DuckDB's DDL already rejects a null INSERT before dbt runs (verified).
    Testing the database's own constraint with dbt is decoration.
  - **~27 `not_null` on columns that cannot be null by construction** — `count(*)`, `lower(tag)`
    behind a `where tag <> ''`, a sum of CASEs, a column inherited from an already-tested parent.
  - **`unique(mart_size_class_summary.size_class)`** — the model *is* `group by size_class`.
  - **`relationships(stg_breed_temperaments → stg_breeds)`** — the bridge selects **from**
    `stg_breeds`; a child cannot carry a key its parent lacks. (The **gold** bridge keeps its
    `relationships` test: there the two sides reach `stg_breeds` by different paths, so a filter on
    `dim_breeds` genuinely *would* orphan rows. Same test name, opposite verdict — the DAG decides,
    not the label.)

  **Why this is a decision and not a cleanup.** A test that cannot fail is not weak coverage, it is
  **zero coverage that reports as coverage** — it inflates the count, dilutes the suite, and makes
  every green run slightly less informative. It's the same lesson as §3's `warn_error_options`
  ("a dropped test is worse than no test") arriving from the far side: there, a test silently
  *stopped existing* while CI stayed green; here, 33 tests *ran* and always passed while CI stayed
  green. **Both produce a build that reports success while proving nothing** — one by absence, one
  by padding. And it makes the one cheap signal I rely on honest again: SPEC says *watch
  `Found N data tests`*, which only means something if every N is a test that could go red.

  **The number was the point.** "68 tests" reads as rigour until a reviewer notices a third of them
  are incapable of failing — and in a case graded on craft, padding reads worse than a lean suite.
  **35 that can each be made to fail is a stronger claim than 68 that can't.** Every survivor is
  listed in SPEC with the specific failure it catches; the ones I could, I proved by mutation
  (invert the predicate, watch it go red) rather than by argument.

  **What it cost, honestly:** the cuts are justified *by construction* — "`count(*)` is never null",
  "the bridge selects from its parent". That reasoning is sound today and is **not itself tested**.
  If someone later rewrites the bridge to select from `raw` instead of `ref('stg_breeds')`, the
  cut `relationships` test is exactly the one that would have caught it, and its absence is silent.
  Each cut therefore carries its reasoning *at the column* in the YAML, not in a commit message —
  so the next person changing that model reads why the test isn't there before removing the premise
  it rested on.
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

- **Chose:** GitHub, **private + read access for reviewers**. Private because the repo quotes the
  brief and is a worked solution to Heyra's take-home — making it public would put the answer in
  reach of the next candidate, which is Heyra's call to make, not mine. The brief's own wording —
  "submit repo link with **read access**" — points the same way.
- **Why / discipline:** meaningful **incremental commit history** (one commit per milestone, not
  one giant final commit); secrets kept out of the repo (API key in `.env` gitignored locally,
  GitHub Actions secret in CI); a README another engineer could follow.

### Branch protection on `main`, with **no admin bypass** — the deliberate ceremony

**Chose:** a ruleset on `main` requiring a **pull request** with **passing status checks**, force
pushes blocked, and **admin bypass OFF**. So every change — including mine — goes
branch → PR → CI → merge.

**Why, when I'm the only developer:** because **a CI that can be ignored isn't one.** Without this,
a red check leaves the Merge button green: the pipeline *informs* but doesn't *enforce*, which is
half a thing. And a rule the repo owner can bypass is theatre — if I can push past it, it protects
nothing and proves nothing. It has to bind me.

The stronger reason is that **this is a case study, not a hobby repo.** The artifact is meant to be
read as something a team could pick up; "I skipped the guardrail because I'm solo" is a weaker
sentence than "I set it up the way a team would need it". The whole project is graded on judgement
about what a real deployment requires — and this is the cheapest possible demonstration of it: three
clicks, and it makes every other CI claim in this document true rather than aspirational.

**Traded off, honestly:** real ceremony for a solo developer. `/ship` can no longer touch `main`; the
loop becomes branch → `/ship` → PR → watch CI → merge → `git switch main && git pull`. That's five
steps where one used to do, and the local-main-is-stale trap is a genuine papercut. For a POC it is
arguably over-process — I'd accept that criticism, and I'd still take it, because the alternative is
a green badge that means nothing.

**It also fixed a real gap rather than performing one:** `ci.yml` triggers on `pull_request`, so
before this the PR-triggered half of CI would never have fired at all — I'd have been committing
straight to `main` and shipping a workflow that had literally never run against a PR.

#### The settings, and why each is what it is

Ruleset **`main: PR + passing CI required`** (named so the *rejection message* explains itself —
the name is what git prints when it blocks a push; `main` or `Ruleset 1` would teach the next person
nothing). Enforcement: **Active** — `Evaluate` is a dry run that blocks nothing, which would be the
same theatre as no rule at all.

| setting | value | why |
|---|---|---|
| Require a pull request | ✅ | the point |
| **Required approvals** | **0** | **GitHub will not let you approve your own PR.** At 1, with bypass off, I could never merge anything again — the rule would brick the repo. 0 still enforces "a PR must exist and CI must be green"; it just doesn't ask me to rubber-stamp myself |
| Require approval of most recent push | ❌ | *"approved by someone other than the person who pushed it"* — same lockout, for the same reason |
| Require branches up to date | ❌ | forces a rebase onto latest `main` before merge, so CI tests exactly what lands. Correct when `main` moves under you; pure friction as the only contributor. **The first thing I'd turn on for a second developer** |
| Require conversation resolution | ❌ | no conversations on a solo PR |
| Block force pushes | ✅ | `main` was force-pushed three times early on (history rewrites). Fine then, never again |
| Bypass list | **empty** | the whole argument. A rule its author can skip protects nothing |

**Allowed merge method: REBASE ONLY** — and this one follows directly from the commit rule in
CLAUDE.md ("the history reads like the milestones, not like a changelog of an afternoon's edits").
Given a branch with `feat: M5 — CI + cron` and `docs: record M5`:

| method | what lands on `main` | verdict |
|---|---|---|
| Merge commit | both commits **+** `Merge pull request #1 from misoard/m5-ci` | **adds** a commit I didn't write, that records only that a merge occurred. That is the changelog noise the rule exists to prevent |
| Squash | both commits fused into **one** | **removes** commits I did write. The `feat`/`docs` split is deliberate — one logical step each — and squashing undoes it on the way in |
| **Rebase** | both commits, replayed linearly, new parents | **lands exactly what `/ship` crafted.** Nothing added, nothing fused |

Squash earns its keep on branches full of `wip` / `fix typo` / `actually fix it` — it hides mess.
**`/ship` doesn't make mess** (the tests-first loop happens *inside* a commit, never as commits), so
there's nothing to hide and squashing would only destroy structure. Restricting to rebase alone also
removes the choice at merge time, which is the point: a decision made once in settings beats a
decision made at 6pm by whoever is merging.

**Chicken-and-egg, worth knowing:** GitHub's "require status checks" picker only offers checks it has
*already seen run*. The check is the **job's** `name:` (`ingest + dbt build + test`) — not the
workflow's (`CI`), not the filename. So the ruleset goes on first *without* the check, the first PR
runs CI, and the check is added afterwards. A nice accident of ordering: the first PR runs with CI
advisory, and the second with CI as a gate — the difference between "informs" and "enforces",
demonstrated on the same repo half an hour apart.

- **With more time:** PR templates, a CODEOWNERS file, and `dbt build --select state:modified+`
  against a stored manifest so a PR only rebuilds what it touched (irrelevant at 9 models; the
  right answer at 900).

## 5. CI / CD — **GitHub Actions**

- **Chose:** GitHub Actions.
- **Why:** tests + `dbt build` run on every PR (visible green/red status); a scheduled run on a
  daily cron proves the pipeline still works end to end against the live API.

### CI **proves the pipeline; it does not serve it.** The demo runs locally.

- **Chose:** producer and consumer both live on my laptop. The pipeline runs locally
  (`ingest.py` → `dbt build --target prod` → `dogs.duckdb`), the Streamlit dashboard reads that
  local file, and I demo it live. GitHub Actions' only job is to answer **"does this code still
  work?"** — it ingests, builds gold, runs the tests, goes green, and then **throws its warehouse
  away**, because serving was never its job.
- **Why:** this makes the handoff problem vanish rather than solving it. The problem only bites if
  you insist the *cloud* run is the thing that serves the dashboard — then its output dying with the
  VM matters, and you need MotherDuck/S3/artifacts to rescue it. But the brief says a **POC is
  enough** and the demo is live. On my laptop, the data survives. So the honest, simplest resolution
  is to keep both ends somewhere durable — which the laptop already is — and let CI do the one thing
  CI is actually good at: telling me the pipeline is healthy.
- **Stated as a choice, not an oversight.** The output of the scheduled run being discarded is
  deliberate: it is a **health check with a real API call attached**, not a deployment. Cron at
  02:00 UTC still earns its place — it catches the API changing shape, the key expiring, or a test
  starting to fail, on a day when nobody is looking. That is a genuine freshness signal even though
  nothing is published.
- **Follows from statelessness (§1):** since every run rebuilds from the API anyway, a run's
  warehouse has no unique value worth persisting. The two decisions are the same idea applied twice.
### The pipeline lives in a **script**, not in YAML — so the workflows are thin triggers

- **Chose:** `scripts/run_pipeline.sh` defines the pipeline once (resolve the path → `ingest.py`
  → `dbt build --target prod`). `ci.yml` (on PR) and `scheduled.yml` (on cron) each collapse to
  checkout + setup-python + `pip install` + **`./scripts/run_pipeline.sh`** + surface warns.
- **Why not one reusable `workflow_call` workflow, or one file with both triggers:** the usual
  argument for those is "don't define the pipeline twice" — but **that duplication only exists if
  the pipeline lives in YAML**. Once it lives in a script, what's repeated is ~8 lines of checkout
  and pip boilerplate, and `workflow_call` would add a concept a reviewer has to learn — plus break
  the badge, since each badge would then point at a *caller* rather than the job — in order to
  deduplicate `actions/checkout`. That's the tail wagging the dog.
- **The rule: deduplicate in the script, not in the CI system.** The YAML then stays a trigger, the
  pipeline is runnable identically on my laptop and in Actions (same script, same seam), and none of
  it is locked to GitHub Actions — if this ever moved to GitLab or Dagster, the pipeline definition
  moves unchanged and only the trigger is rewritten.
- **Why two workflows and not one file with `on: [pull_request, schedule]`:** they answer genuinely
  different questions — **"does this change work?"** vs **"does the API still look like we think?"**
  — and merging them makes one status check for both. When the cron goes red at 02:00 that is
  precisely the thing I don't want: a red I have to open and read before I know whether the world
  changed or someone's PR is broken. Two triggers, two badges, two reactions.
- **The seam it closes:** `ingest.py --db` and dbt's `profiles.yml` are two separate programs that
  must agree on one DuckDB file, and they run from **different working directories** (dbt must run
  from `dbt/`, so its relative paths mean something different). The script resolves `DBT_DUCKDB_PATH`
  to an **absolute** path once and hands it to both. That is the single fragile joint in the design,
  and it now has exactly one home.
- **A local-only wrinkle, stated:** the script prepends the project `.venv` to `PATH` when one
  exists. dbt needs protobuf>=6 and my conda base pins <4 — they cannot coexist, and I broke my
  environment on this once. CI has no `.venv` (pip installs into setup-python's env), so it falls
  through to `PATH` and the branch never fires there.

### Making `warn` visible: `scripts/annotate_warns.py` — **the milestone's real content**

The severity split (§3) was only half a decision. dbt prints WARN and **exits 0**, so a fired
distributional guard leaves CI **green** and the signal dies in a collapsed log. Five tests are
`severity: warn`; until something surfaces them, the whole classification is **theatre — tests
carefully sorted into a bucket no human ever reads**. So CI parses `target/run_results.json` into
GitHub `::warning::` annotations plus a `$GITHUB_STEP_SUMMARY` table.

- **It exits 0 when it finds warns, deliberately.** Failing here would re-implement `--warn-error`
  and destroy the distinction it exists to serve. A warn is for a human to judge ("real regression
  or legitimate drift?"), not for a robot to block on. `--warn-error` stays off for the same reason
  `warn_error_options` is scoped to `NodeNotFoundOrDisabled` only (§3).
- **A committed Python script, not inline `jq`** — and the reason is the one I've applied all week:
  **a bug in inline jq produces no annotation, which is indistinguishable from no warnings.** The
  mechanism whose entire job is making problems visible would fail *invisibly*. That's the same
  disqualifying shape as a vacuous green or an unfireable test, arriving one level up: a guard that
  can silently stop guarding. A script runs locally against a real or synthetic `run_results.json`,
  so the mechanism is **proven before CI depends on it** — and can be demonstrated on demand.
- **Which is exactly what I did, rather than asserting it.** I forced two real warns
  (`dbt test --vars '{max_unknown_size_class_pct: 0, max_lifespan_null_pct: 1}'`) and watched dbt
  report **`WARN=2` and exit 0** — the failure mode, reproduced. The same run through the annotator
  emits two `::warning::` lines and the summary table, and still exits 0. Also proven: the
  hash-suffixed generic-test id renders readably, and warns still surface when the build is red
  (the step is `if: always()` — a red build is when you most want to know what else fired).
- **Its own failure is loud:** a missing or corrupt `run_results.json` emits `::error::` and exits
  **1**. "I found no warnings" and "I could not look" must never render identically — that would
  rebuild the exact silence this script exists to break.

- **Traded off:** there is no public/hosted dashboard URL, and "daily freshness" is proven rather
  than served. If the explorer had real users, this is exactly the line I'd cross: the cron would
  publish to durable storage and the dashboard would read that.
- **Traded off — every PR spends a real API call.** There is no fixture and no persisted warehouse
  (§1), so `raw.breeds` doesn't exist until `ingest.py` creates it: "install + `dbt build`" alone
  would fail on a missing source. The upside is that **every PR check is a genuine end-to-end run
  from an empty warehouse**, which is the property §1 claims and M5 finally verified. The cost is
  that a fork PR (no access to the secret) 403s, and CI can go red because *the API* is down rather
  than because the code is wrong. At one contributor and one daily job, that's the right trade; with
  outside contributors I'd land a recorded fixture for the PR path and keep the live call on the cron.
- **With more time:** publish the `.duckdb` as a Release asset or push to **MotherDuck**, and point
  a hosted Streamlit at it — that turns the same pipeline into a serving one, with no model changes.
  Also: dbt docs uploaded as an artifact, and an alert on a failed scheduled run (a red cron nobody
  sees is a cron that isn't running).

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
- **Reads the local `dogs.duckdb` (the prod target), demoed live** — not a hosted deploy. CI proves
  the pipeline; the laptop serves it. The reasoning is in §5, and it's a deliberate POC scope call.
- **With more time:** _[hosted deploy on Streamlit Cloud reading MotherDuck; more questions;
  interactivity]_

## Bonus — LLM enrichment **[if fundamentals are solid first]**

- **Feature:** turn free-text `temperament` + `description` into a structured column
  (`energy_level` score or `good_with_kids` flag), folded back into the dbt model as a real column.
  **Not `bred_for` — profiling found it 100% null**, which is why the original framing of this bonus
  had to change.
- **Where it sits — Pattern A: `enrich.py` writes a table, dbt reads it.** It reads `stg_breeds`,
  calls the LLM, and writes `raw.breed_enrichment` (keyed by `breed_id`). `dim_breeds` joins it as
  just another input, declared via `source()` (dbt doesn't build it — Python does).
  Pipeline order: **ingest → `dbt build` staging → `enrich.py` → `dbt build` marts.**
- **Why Pattern A:** the LLM call stays *outside* the warehouse build. dbt never makes a network
  call, so `dbt build` stays deterministic and offline-reproducible; the enrichment is inspectable
  as a table before it reaches gold; and a failed LLM run leaves the previous enrichment in place
  rather than breaking the build. The enrichment is not a special case — it's another table dbt joins.
- **Traded off, stated plainly:** the pipeline is **no longer one `dbt build`** — the runner
  sequences four steps instead of two, and there's a Python step wedged between two dbt invocations.
  That's the price of the separation, and it's worth it: the alternative (a dbt Python model calling
  the LLM mid-build) couples the warehouse build to a rate limit, a bill, and a non-deterministic
  output. Not something to accept for a bonus.
- **LEFT JOIN, never inner.** If enrichment hasn't run, or missed a breed, that breed still appears
  with a NULL column. A bonus must never be able to drop breeds from the core deliverable.
- **Engineering treatment (not magic):** batch all 628 in one pass per run; **cache by `breed_id`**
  so unchanged breeds aren't re-called; record cost & latency; and a **light eval** — `accepted_values`
  on the enum (the LLM's output is untrusted input, so it gets schema-tested like any other source),
  plus a spot-check against a handful of hand-labels.
- **Why this over a flashier bonus:** a small evaluated feature beats a large eyeballed one — and
  it plays to my applied-LLM background (same unstructured→structured pattern as my other work).

---

## What I'd build next given another week
_[3–5 bullets: run-metadata/audit table + alerting; change detection; hosted dashboard; more
marts; snapshots for history; IaC (Terraform) for reproducibility]_
