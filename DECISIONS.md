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
giant 58** (625 breeds with a parsed weight, post-dedupe), mean life span **13.3 / 13.2 / 13.0 / 12.2 / 10.6**.

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
  - **A `warn` nobody sees is not a signal — it's a comment.** dbt prints WARN to stdout and exits
    **0**, so CI goes green and the warning dies in a collapsed log. Choosing `warn` severity is
    therefore only half a decision; the other half is *making it visible*. M5's CI parses
    `target/run_results.json` and emits GitHub `::warning::` annotations plus a job-summary table —
    visible on the PR and the run page, **without failing the build**, which is exactly the point of
    warn. Same principle as the red-cron-nobody-sees note in §5. Without this step the entire
    warn/error split is theatre: I'd have carefully classified tests into a bucket that no human
    ever reads.
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
- **Traded off:** there is no public/hosted dashboard URL, and "daily freshness" is proven rather
  than served. If the explorer had real users, this is exactly the line I'd cross: the cron would
  publish to durable storage and the dashboard would read that.
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
