# DECISIONS.md

The Dog API is a small, static, deliberately messy reference dataset, so the engineering challenge is
**craft, not volume**: clean parsing, a legible model, and a reliable idempotent pipeline. My guiding
principle throughout is **right-sizing** — the smallest stack that does the job well and that I can
fully explain, rather than the heaviest set of managed services. Since this is a data engineering study case, I've deliberately put most attention towards data reliability: clean and reliable data is the key to make all downstream tasks work. Therefore, I insisted on: 
- **the data pipeline**: the bronze to gold tables splitting.
- **observability**: for me observability is crucial for data reliability. Without it there is no way to track failures over days.
- **alert channel**: it was presented in the brief as an additional bonus feature, but for me it is essential because it catches failures upstream dbt - at ingest, a failed or not running scheduled cron...
- **storage durability**: without over-engineering it, I wanted the scheduled cron to persist data because this is the first step for observability and durability.
- **atomicity**: A dbt test that fails leaves a bad table in place and only skips downstream. We end up with an intermediate state that must not be promoted to prod data. That's why I decided *for the scheduled cron* to run dbt tests on a shadow schema and then swap it to prod data on **full** success. This ensures that all gold data shown in the live dashboard pass **all tests**.
I designed the architecture first organized in milestones and used Claude Code as the implementer 
against it, so every choice below is mine to defend. One paragraph per layer: what I chose, why over 
the alternative, what I traded off. 

## 1. Extraction & ingestion — hand-rolled Python (`requests` + `tenacity`)

**Chose** `ingestion/ingest.py` — `requests` for one GET, `tenacity` for retry/backoff, DuckDB's
Python API for the write — **over `dlt`**. This is one endpoint returning one JSON array; dlt's
schema-evolution and incremental-state machinery would add a dependency and its own abstractions
between me and the only two properties that matter here — idempotency and partial-failure safety; dlt wins the moment a second and third source appear. Raw lands **verbatim** (JSON +
`run_date` + `loaded_at`) so a bad parse never means a re-fetch; the `id`-string → INTEGER cast is
deferred to staging. Raw is **partitioned by `run_date`** (the brief's ask), and that partition is
the mechanism of idempotency: each run **DELETE+INSERTs the day's partition in one transaction**, so
a re-run replaces rather than appends and a crash rolls back to last-good — and `stg_breeds` filters
to `max(run_date)`.
Retries hit only transient errors (timeouts / 429 / 5xx); a **403 fails fast** (retrying a bad key
just delays the real message), and every fetch is validated for structure, PK-uniqueness and
completeness (**≥90% of a reference count**, not equality — 629 breeds would be *real data*, not an
error) before it touches the warehouse. The pipeline is stateless in its
**processing**: every run full-refreshes silver/gold from the API as the source of truth, no run
depending on a prior run — which is what makes CI's empty warehouse a supported start. What *output*
persists is a separate choice: CI discards it, and the cron now persists to hosted DuckDB, so
`raw.breeds` accumulates one durable partition a night — full-refresh processing, durable output, and
`stg_breeds` filtering to `max(run_date)` keeps every run behaving identically regardless. **With more time:** dbt **SCD-2** snapshots that version a breed's row only when it actually changes — *data*
change-history, distinct from *incremental* rebuilds (a scale lever, not history).

## 2. Database & warehouse — DuckDB (local) + MotherDuck (the same engine, hosted)

**Chose** DuckDB (embedded, single `dogs.duckdb` file) **over Postgres/BigQuery/Snowflake**. The
workload is **analytical (OLAP)** — scan-and-aggregate, not transactional row lookups — so a
column-oriented engine is the right fit; DuckDB adds zero infrastructure, reads JSON natively
(trivial ingestion), and is the modern default for local analytics. Part of *why* it's the right
choice is that the **same engine has a hosted form — MotherDuck** — so going durable/shared later (the
cron, below) cost a **connection string, not a re-platform**; the alternatives would have meant a
migration. The bronze → silver → gold
layers are **schemas, not folders**, so the boundary is enforced by the warehouse rather than by
convention:

| schema | layer | holds | written by | materialized |
|---|---|---|---|---|
| `raw` | bronze | `breeds` — verbatim JSON + `run_date`, `loaded_at` | `ingest.py` (never dbt) | table |
| `main` | seeds | `size_class_bands`, `dashboard_temperament_tags` | `dbt seed` | table |
| `main_staging` | silver | `stg_breeds`, `stg_breed_temperaments` | dbt | **view** |
| `main_marts` | gold | `dim_breeds`, the bridge, 5 marts | dbt | **table** |

*(A sixth schema, `main_elementary`, appears once the observability package is installed — it holds
run/test metadata written by Elementary's on-run-end hook, not breed data, and is owned by the package
rather than modeled by us. It's metadata *about* the pipeline, deliberately outside the bronze→silver→
gold contract; see §3 and "What I'd build next".)*

**Staging is views, marts are tables**, set once per layer in `dbt_project.yml`: a view is the
parser re-executed on read — free at 627 rows and *never stale* by construction — while marts are
read repeatedly by the dashboard, so they pay the parse once and are scanned many times. The rule
and its crossover are explicit (flip to a table at scale when `reads × parse_cost > storage +
rebuild_cost` - I tested it with x1000 rows and this is where going from view to table pays off),
and the flip is one line of config with no SQL touched. **The hosted shared copy is now in place** — the cron
builds into **MotherDuck** (`md:dogs`, hosted DuckDB), the *same* dbt code with only the connection
string changed: it is what makes Elementary's trends and
the hosted dashboard possible, and it is the prerequisite for turning to **incremental** ("only
reprocess what changed") at scale (see the last section). Local file and cloud now coexist:
`dev`/local-`prod` write files, the cron writes `md:dogs` and ensure atomicity for gold tables, one env var (`DBT_DUCKDB_PATH`) selects
which — no SQL knows the difference. Important point there worth stopping: atomicity. I realized after building the pipeline that a failed dbt test leaves the table in place. Therefore, some gold tables can reflect old data (those dependind on the *failed* table upstream), and other updated data. So I decided to update gold data (read by the dashboard from MotherDuck) ONLY IF all tests pass. The mechanism: a SHADOW schema (`main_marts_next`) instead of the live one, run all tests against it, and only then atomically swap it into `main_marts`.  

## 3. Transformation & modeling — dbt Core

**Chose** dbt Core with the `dbt-duckdb` adapter: transformations as version-controlled SELECTs,
automatic DAG ordering via `ref()`, built-in tests, generated docs/lineage, and dev/prod targets
that differ **only** in the output path. I modeled **one object per job the dashboard actually has**
— `dim_breeds` (internal building block), the `breed_temperaments` **bridge** (the brief's "turn the
comma list into something queryable" deliverable), and five gold marts — rather than a mart per
question (over-modeling) or one fat table (under-modeling). All business logic lives in gold: the
messy fields are parsed into typed min/max/**midpoint** columns (`life_span` "12-15", sex-specific
weight/height ranges collapsed to a whole-breed envelope), `'unknown'` sentinels nulled *before*
casting, `temperament` exploded into a lowercased+trimmed bridge (66→46 tags once case-folded), and
the duplicate "Caucasian Shepherd Dog" deduped in staging (628 raw → **627** gold). This results from an exploratory phase (see exploration/ foler and the subsequent report PROFILE_REPORT.md). **39 tests**
carry the contract, split by severity on purpose: hard invariants (min ≤ max, PK unique) are
**error** (18), distributional/drift guards are **warn** (6) -- a null-rate or source-size change is
a *human* judgment, not a build failure, so CI annotates them and stays green --, regression guards,
unfireable today but guard a name refactor (8), seed integrity (7). Each was proven capable of
failing by mutation, after I audited a bloated suite down from 68 (a third couldn't fail — "coverage
that reports as coverage"), and the two most load-bearing (`assert_unit_ratio_plausible`,
`assert_no_breed_lost`) **re-derive their answer from `source('raw')` rather than reuse the model's
parser**, so they can't agree with a bug by construction. **Contracts** sit on the 6 marts the
dashboard reads — exactly where the DAG's knowledge ends. **Traded off:** hand-written singular
tests over `dbt_utils`, deliberate for a case graded on *understanding* dbt (in production I'd lean
on the package for the boilerplate). **The one deliberate exception:** the Elementary dbt
package — the project's *first* external package, added for **observability infrastructure, not test
logic**. It writes no assertion I couldn't defend; it *captures the results of the 39 I already
wrote* (status, timing, the warn/error split) into `main_elementary` tables via an automatic
on-run-end hook, and renders a health report. 

## 4. Version control — GitHub

**Chose** GitHub, **private with read access for reviewers** (the repo is a worked solution to
Heyra's take-home — making it public is Heyra's call, and the brief itself says "read access"). The
discipline is a **meaningful incremental history** — one commit per milestone (M0 · M1 · M2…), not
one giant final commit — with secrets kept out of the repo and a README another engineer could
follow. **One deliberate deviation, flagged so it reads as chosen not overlooked:** I commit
`dbt/profiles.yml`, which convention gitignores, because it carries only paths through `env_var()` —
the secrets stay in the environment (`DOG_API_KEY` never appears there), so version-controlling the
connection wiring is safe and makes the dev/prod split legible. I put a **ruleset on `main`
requiring a PR + passing CI, force pushes blocked, admin bypass OFF** — so every change, including
mine, goes branch → PR → CI → merge. The point: **a CI that can be ignored isn't one**; this is the
cheapest possible demonstration of setting things up the way a *team* would need. **Traded off,
honestly:** real ceremony for a solo developer (five steps where one used to do, and a
stale-local-main papercut) — arguably over-process for a POC, but I'd still take it over a green
badge that means nothing. **With more time:** a CODEOWNERS file, PR templates, and "require branches
up to date" (the first thing I'd switch on for a second contributor).

## 5. CI / CD — GitHub Actions

**Chose** GitHub Actions: tests + `dbt build` on **every PR** (visible green/red badge), plus a step
that surfaces dbt `warn`s as annotations without failing the build. The defining call is that **CI
proves the pipeline; the laptop and the cron serve it** — a PR build ingests, builds gold,
tests, goes green and then *throws its warehouse away*, because serving was never a PR's job; the
live Streamlit demo reads the local `dogs.duckdb`. This kept the cloud-handoff problem out of the
*proving* path entirely, following directly from the statelessness of §1 (every run rebuilds from the
API, so a PR's warehouse has no unique value worth persisting).
The pipeline itself lives in **`scripts/run_pipeline.sh`, not in YAML** because the workflow is
called from three entry points: my local laptop, the CI and the scheduled cron — so the workflows
are thin triggers, the same script runs identically on my laptop, in CI and in the scheduled cron,
and nothing is locked to GitHub Actions. **Traded off:** every
PR spends a real API call (no fixture) — the upside is that each check is a genuine end-to-end run
from an empty warehouse. **The serving half is built without abandoning that thesis:** rather than
*convert* the prod target, I kept the split and pointed only the **cron** at hosted DuckDB
(`DBT_DUCKDB_PATH=md:dogs`), so **PR builds still prove against a throwaway local warehouse while the
02:00 cron serves** — writing gold + the observability run-history to a durable store the hosted
dashboard reads. Proving and serving stay different jobs on different triggers, so a PR can never
overwrite last night's served data. It was a one-line change because the pipeline is stateless (§1) —
only the output **path** moved (a file → an `md:` connection string), no model SQL touched.

## 6. Orchestration & scheduling — GitHub Actions cron (not Airflow)

**Chose** the cron scheduler built into GitHub Actions, **daily at 02:00 UTC**, over Airflow /
Dagster / Prefect. This is **one daily job**: standing up a managed orchestrator for a single
scheduled task is operational overhead I can't justify. Actions cron runs it reliably and unattended.
**Whether the last run passed or failed is answered at two levels.** At a glance: the run status
(green/red + logs, and the README badge). Durably and with history: an **observability layer** built on
the **Elementary** dbt package (the one allowed dependency, §3). Its automatic on-run-end hook records
every test/run result — status, timing, the warn/error split for all 39 tests — into `main_elementary`
tables, and **one command renders a health report** from them: `./scripts/observability_report.sh`
reads the **local** `dogs_dev.duckdb` (my own builds), while `./scripts/observability_report.sh md:dogs`
reads **MotherDuck** — the cron's cloud data — so I can check whether last night's scheduled pipeline
went green and watch trends accumulate night over night (`raw.breeds` and the Elementary tables both
persist there, §1/§2). It shows *which* test failed and *for how long*, not just that something did
(`loaded_at` shows data freshness alongside). But looking is a pull, and the hardest failure to catch
is a run that **never happened** — GitHub cron is best-effort and silently *drops* runs (and
auto-disables a scheduled workflow after 60 days of repo inactivity), which the Actions page
structurally cannot show, since it only lists runs that *started*. So the cron carries a **dead man's
switch**: it pings Healthchecks.io on **start / success / fail**, and the monitor alarms if the daily
**success** ping doesn't arrive. The success ping is **success-gated** on purpose — pinging
unconditionally would let a failed run report "alive" and keep the monitor green while broken, a switch
that lies. Grace is **wide** (a few hours), because GitHub cron is routinely 15-30 min late and a tight
window would cry wolf — a flaky page gets muted, which is the "wallpaper" rule (§3) applied to alerting.
The ping URL is a secret (`HEALTHCHECKS_URL`), same discipline as `DOG_API_KEY` / `MOTHERDUCK_TOKEN`.
**With more time:** Elementary's `edr monitor` to push a *specific failing test* (not just a failed run)
to Slack, and Dagster only if the DAG outgrew a handful of steps or needed richer backfills — not
before, and the difference is the whole point.

## 7. Dashboard & visualization — Streamlit, thin, spec-first

**Chose** a thin **Streamlit** app (charts in **Altair**) reading the gold marts from the local prod
`dogs.duckdb`, demoed live (delivery is a PDF/screenshots, not a hosted URL — §5). Before any of it
I **profiled the source** (`exploration/`) and let that drive the model: `id` confirmed as PK, units
inferred from the imperial/metric ratio (median 2.20 lb/kg, 2.54 cm/in — nothing in the payload
declares them, so it became a test), and the **`size_class` bands frozen at 5 / 12 / 25 / 45 kg in a
dbt seed** (data-*informed* by k-means, then held constant — a recomputed cut would let a breed
change class without its weight changing) with a load-bearing **half-open `[min, max)`** convention,
since 31 breeds sit exactly on a boundary. The app is genuinely **thin** — it computes *no* fact;
every number (correlations, means, σ, coverage denominators) is read from the marts at render time,
and app-side work is only selecting rows already in a mart (filter / top-N) and drawing chart
geometry. It answers **two of the brief's four questions plus a temperament angle of our own**, as a
narrative of what the data *says*: most breeds are mid-sized; **smaller breeds tend to live longer,
but it's a large-and-giant effect** (mean life span 13.3 → **10.6** yr), **real in the mean and weak
per dog** (±1σ bars widen 0.68 → 1.54 and overlap heavily); temperament shifts systematically with
size. "Size" is **weight**, not height (weight predicts life span more strongly, −0.67 vs −0.50, and
the two are 0.86-coupled). The visualization rules are **honesty rules**: never a dual-axis chart
(two y-scales fabricate a relationship — stack two charts on one x-axis instead), a heatmap not a
radar (no axis-order artifact), the ±1σ band ships *with* every mean, and **every chart prints its
own population** — coverage is *uneven* (toy 29/40 vs giant 58/58), so a bare "627" beside a plot
drawn from 585 would quietly lie. **Delivery — I went live** rather than stop at PDF/screenshots:
the app is deployed on **Streamlit Community Cloud** reading gold from **MotherDuck** (the same cloud
store the cron refreshes on a green run), so the deliverable is an actual **link** —
**https://dog-breed-explorer-case-study.streamlit.app/**. One env var does it: `app.py` reads `md:dogs`
when `DOGS_DB=md:dogs` is set (hosted) and the local `dogs.duckdb` otherwise (the local demo,
unchanged), with no model change and the token kept as a platform secret, never in the repo or on the
page. **Traded off:** a deliberately un-clever native app (no bespoke CSS) that reads plain but stays
thin and stable. **Cut, recorded not built:** the
`weight ~ height²·⁰⁷` isometry finding and a trait-pair lift analysis — an exponent is *not a fact
about a dog*, which is the line I hold (**descriptive facts about breeds → gold; inferential
cleverness → the reasoning record**). **With more time:** the LLM enrichment bonus below and the
breed cards (last optional item of milestone 6).

---

## What I'd build next given another week

**The keystone — durable storage — is now in place:** the cron persists to **MotherDuck** (hosted
DuckDB, **zero SQL change**, just a connection string `md:dogs` in place of the local `.duckdb` — §2/§5),
which is what already made the **observability trend view** (§6) and the **hosted dashboard** (§7) real.
(S3 or a Release asset would also work; **GitHub artifacts wouldn't** — retention-capped, meant for
build outputs, not a store you'd trust. The cost is **operational, not financial**: a 2 MB database
sits inside MotherDuck's free tier for one daily job.) With that in hand, the genuinely-future items:

- **Change history → the scaling path.** dbt **snapshots (SCD-2)** in `snapshots/` (`strategy='check'`
  since the API gives no `updated_at` — it compares column values to detect change, the analytics-side
  equivalent of CDC). A row is versioned only when a breed actually changes — the "what did this breed
  look like last month?" question §1 defers. This is also what unlocks **incremental models** at
  scale: "only reprocess what changed" needs a change signal and a prior state to diff against, i.e.
  history. At 627 rows full-refresh wins (simpler, idempotent for free); the moment a rebuild is
  measured in minutes or dollars, snapshots + incremental are the answer.
- **The LLM cost story — where the money actually goes.** *(The brief asks for "a short paragraph on
  what this pipeline would cost to run daily at real scale.")* The pipeline compute is ~free — DuckDB
  rebuilds 627 rows in a second. **The bill is the LLM enrichment.** First run: 628 calls (batched),
  one-time, fine. But re-calling the model **daily for byte-identical rows** is the entire ongoing
  cost — real dollars and latency for zero new information. The fix is change-detection: hash each
  breed, call the LLM **only on change** (≈0/day on a near-static source), which is precisely the
  "cache by `breed_id`" in the enrichment spec — and it needs history. **So the expensive
  *computation*, not the data, is what makes persistence pay for itself.** At real scale the money is:
  LLM tokens (dominant, controlled by the cache), then hosted storage/compute (cents), then Actions
  minutes (free tier). Everything non-LLM stays negligible; the whole cost question is "how often do I
  re-run the model," and history is the lever.

Then the two that don't depend on storage:
- **IaC:** Terraform the repo ruleset, Actions secrets, and the MotherDuck storage, so the whole
  stack is reproducible from the repo rather than from the settings pages I clicked once.
- **LLM enrichment (the bonus feature itself):** `energy_level` / `good_with_kids` from temperament +
  description via **Pattern A** — `enrich.py` reads `stg_breeds`, calls the LLM, writes
  `raw.breed_enrichment`, and `dim_breeds` **LEFT JOIN**s it via `source()`, so dbt never makes a
  network call and a failed enrichment can't drop a breed. Batched, cached by `breed_id`, and
  schema-tested like any other untrusted source.
