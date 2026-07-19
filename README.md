# 🐕 Dog Breed Explorer

[![CI](https://github.com/misoard/dog-breed-explorer/actions/workflows/ci.yml/badge.svg)](https://github.com/misoard/dog-breed-explorer/actions/workflows/ci.yml)

A right-sized daily data pipeline and a thin analytics dashboard over [TheDogAPI](https://thedogapi.com)'s
**627 dog breeds**. Bronze → silver → gold in **DuckDB + dbt**, scheduled by **GitHub Actions**, read
by a **Streamlit** dashboard. It runs end to end on a laptop off a single DuckDB file — the deliberate
scope for a POC — with an **optional M9 cloud path** (Elementary observability + a MotherDuck-backed
hosted dashboard) layered on top without changing a line of model SQL.

> **Where to start:** [`DECISIONS.md`](DECISIONS.md) is the reasoning record — the tool choices, the
> tradeoffs, and what I'd build next. It is the most important file here. This README is the tour and
> how to run it.

---

## What it answers

The brief suggests four questions and asks for at least two. This dashboard answers **two of them**, and
adds a temperament angle of its own, in the dashboard's own words:

- **How are breeds distributed across weight classes?**
- **Which breeds have the longest predicted life span? Does size cost life span?**
- **How does temperament shift with size?**

The first two come from the brief; the third is ours. "Size" is weight throughout, with the
correlation evidence for that choice shown on the page.

---

## Quickstart

**Prerequisites:** Python 3.11+, and a free [TheDogAPI key](https://thedogapi.com/signup)
(`/v1/breeds` returns **403** without one).

```bash
# 1. environment
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then paste your key: DOG_API_KEY=...

# 2. build the warehouse: ingest -> dbt build -> tests (a few seconds)
./scripts/run_pipeline.sh     # writes ./dogs.duckdb (the prod target)

# 3. run the dashboard
streamlit run dashboard/app.py   # opens http://localhost:8501
```

The pipeline and the dashboard both run locally against one file (`dogs.duckdb`). The dashboard is
**thin** — it reads the gold marts and renders; it never triggers the pipeline.

---

## Architecture

Write and read paths are decoupled: the **pipeline** builds gold; the **dashboard** reads whatever
gold currently holds, at any time. **One env var (`DBT_DUCKDB_PATH`) picks where gold lands** — a
local file, or MotherDuck — with no change to a line of model SQL.

```
  WRITE (automated)                                          READ (on demand, thin)
  Dog API ─ingest→ RAW ──dbt──> STAGING ──dbt──> GOLD          Streamlit dashboard
                   bronze       silver          marts          (reads gold, renders 3 Qs,
                   (untouched   (parse, type,   (dim + marts,    never triggers the pipeline)
                    JSON, by     dedupe,         all business
                    run_date)    →null)          logic here)
                          + Elementary observability (test/run health)
                                     │
        one env var (DBT_DUCKDB_PATH) selects where GOLD + observability are written:
          • local  ./dogs.duckdb        ← laptop demo build, and CI PR builds (ephemeral)
          • cloud  md:dogs  (MotherDuck) ← the 02:00 cron; DURABLE, accumulates night over night
                                     │                          the dashboard reads gold:
                                     ▼                            • locally → ./dogs.duckdb
                          gold + observability                    • hosted  → md:dogs  (next step)
  The cron writes MotherDuck; CI PR builds stay local, so a PR never clobbers served data.
```

| Layer | Choice | Why (one line) |
|---|---|---|
| Ingestion | Python + `requests` + `tenacity` | one endpoint; idempotent, raw preserved, retry on transient failure |
| Warehouse | **DuckDB** (local file) → **MotherDuck** (hosted, same engine) | analytical/OLAP, zero-ops, native JSON; the cron persists to MotherDuck so gold survives the VM |
| Transform / test | **dbt Core** + `dbt-duckdb` | SELECT models, `ref()` DAG, 39 tests, contracts, dev/prod targets |
| Observability | **Elementary** (dbt package) | captures every test/run result durably; day-over-day health once in MotherDuck |
| CI/CD + schedule | **GitHub Actions** | tests + build on every PR; daily cron @ 02:00 UTC |
| Dashboard | **Streamlit** + Altair | thin reader of gold marts (local file, or MotherDuck when hosted) |

**Right-sized on purpose:** no Airflow for one daily job, and DuckDB — local, or the same engine
hosted on MotherDuck's free tier — rather than a heavy managed warehouse (Snowflake/BigQuery). The
reasoning for every choice, and where it was traded off, is in [`DECISIONS.md`](DECISIONS.md).

**Targets — same models, only the output path differs** (one seam, the `DBT_DUCKDB_PATH` env var):

| target | command | writes to | used by |
|---|---|---|---|
| `dev` (default) | `dbt build` | `dogs_dev.duckdb` | me, iterating on models — a bare build can't touch the serving copy |
| `prod` | `./scripts/run_pipeline.sh` | `dogs.duckdb` (local file) | the local demo the dashboard reads, and CI PR builds (ephemeral) |
| `prod` → cloud | `DBT_DUCKDB_PATH=md:dogs ./scripts/run_pipeline.sh` | `md:dogs` (MotherDuck) | the 02:00 cron — durable, what the hosted dashboard reads |

`dev` is the default precisely so reaching the serving copy (`--target prod`, or the script) is a
deliberate act. The `md:` path just swaps the connection string — same SQL, same targets.

---

## The dashboard — what the data says

*(A live Streamlit app; the charts below are exported from it.)*

### 1. How are breeds distributed across weight classes?

![Breeds per weight class](docs/img/01_distribution.png)

**Most breeds are mid-sized:** 220 medium + 203 large of 627; toy (40) and giant (58) are the tails.
The weight bands (kg) are frozen in a dbt seed and shown under each bar, so "medium" has a definition.

### 2. Which breeds live longest? Does size cost life span?

![Weight vs life span, every breed](docs/img/02_scatter.png)

**Smaller breeds tend to live longer — but it is a large-and-giant effect, not a smooth slope.** Mean
life span is flat across toy→medium (13.3 → 13.0 yr), then drops for large (12.2) and giant (10.6).

![Mean life span with ±1σ](docs/img/03_mean_lifespan.png)

**And it is real in the mean, weak for any individual dog.** The ±1σ bars widen with size (0.68 → 1.54)
and the bands overlap heavily, so a giant *tends* to live less than a toy, but plenty don't. "Life
span" is the **midpoint of each breed's published range**, not a prediction.

The five **longest-lived** breeds are *identical* on every life-span number — all a published **12–18
years** — so they can't be ranked against each other; they are listed alphabetically, and what differs
between them is size, not lifespan:

| breed | size class | weight (kg) | published life span |
|---|---|---|---|
| Denmark Feist | small | 11.5 | 12–18 |
| Koolie | medium | 19.5 | 12–18 |
| Miniature Fox Terrier | toy | 4.2 | 12–18 |
| Rat Terrier | small | 7.5 | 12–18 |
| Silken Windhound | medium | 17.0 | 12–18 |

**Why weight, not height:** weight predicts life span more strongly (−0.67 vs −0.50), and height is
0.86-coupled to weight, so it adds little once weight is in. That is what "size" means here.

### 3. How does temperament shift with size?

![Temperament by size class](docs/img/04_temperament.png)

**Temperament shifts systematically with size:** small breeds skew **playful and alert**, giant breeds
**protective and calm** (energetic peaks in the middle) — the bright cells fall on a diagonal. Values
are the % of breeds in each class; the near-universal tags (intelligent, loyal) are set aside on
purpose so they don't drown the distinctive signal.

### Honesty in the numbers

Every chart states **its own** population: of 627 breeds, 625 have a weight, 587 a life span, 626 a
temperament; the scatter plots the **585** with both. Coverage is uneven by class (toy 29/40 vs giant
58/58), which the dashboard shows rather than hides. Reasoning behind these choices is in
[`DECISIONS.md` §0](DECISIONS.md) and the panel contract in [`DASHBOARD.md`](DASHBOARD.md).

---

## Repo layout

```
dog-breed-explorer/
├─ ingestion/ingest.py        # fetch + retry + land raw into DuckDB, partitioned by run_date
├─ dbt/                       # the dbt project
│  ├─ models/staging/         # stg_breeds (the parser), stg_breed_temperaments
│  ├─ models/marts/           # dim_breeds, the temperament bridge, 5 marts (+ contracts)
│  ├─ seeds/                  # size_class_bands + dashboard_temperament_tags (the ONLY home of those constants)
│  └─ tests/                  # custom SQL tests (return rows = fail)
├─ dashboard/app.py           # Streamlit; reads gold marts; thin
├─ scripts/run_pipeline.sh    # the pipeline in one place (ingest -> dbt build); CI and local both call it
├─ .github/workflows/         # ci.yml (on PR) + scheduled.yml (cron)
├─ exploration/               # M0 profiling + a throwaway explorer (kept as evidence I looked first)
├─ DECISIONS.md               # the reasoning record  ← start here
├─ SPEC.md                    # schema, the parser, the 39 tests
├─ DASHBOARD.md               # the dashboard contract (panels, charts, honesty rules)
└─ ARCHITECTURE_PLAN.md       # the milestone plan
```

---

## Testing & CI

- **39 dbt tests**, split by role: **18 error** (hard invariants), **6 warn** (drift / source-change
  signals, surfaced but non-fatal), **8 regression guards** (can't fail today, each guards a plausible
  refactor), **7 seed-integrity** (the CSV seeds tested like data). Each verified capable of failing;
  **contracts** on the 6 marts the dashboard reads. Full breakdown in [`SPEC.md`](SPEC.md).
- **On every pull request**, GitHub Actions runs the whole pipeline **from an empty warehouse**
  (ingest → `dbt build` → tests) and reports green/red — the badge at the top.
- **A daily cron @ 02:00 UTC** re-runs it against the live API as a health check. By default it
  discards its warehouse — CI *proves* the pipeline, the laptop *serves* the demo; with the M9 cloud
  path the cron *also* serves, building into MotherDuck while PR builds stay local (so a PR can't
  clobber served data). A deliberate scope call, [`DECISIONS.md` §5](DECISIONS.md).

*(The badge shows "no status" to anyone without repo access — the repo is private; reviewers with read
access see the real state.)*

---

## Observability & cloud serving (M9, optional stretch)

The local pipeline is complete on its own; M9 adds two things on top, both **opt-in and off the
default path**:

- **Observability — [Elementary](https://www.elementary-data.com/).** The project's one external dbt
  package, added for *observability infra, not test logic* (DECISIONS §3). An automatic on-run-end
  hook captures every test result (status, timing, the warn/error split for all 39 tests) into
  `main_elementary` tables on each `dbt build`; `./scripts/observability_report.sh` renders an HTML
  health dashboard from them (regenerable, not committed — same rule as the dbt docs graph).
- **Cloud serving — [MotherDuck](https://motherduck.com).** The single durable-storage unlock. The
  **cron** (only) sets `DBT_DUCKDB_PATH=md:dogs`, so it builds gold + Elementary into hosted DuckDB
  that persists past the VM — while CI PR builds stay local/ephemeral, so a PR never clobbers served
  data. The dashboard reads that store when `DOGS_DB=md:dogs` is set (else the local file). **Zero
  model SQL changed** — only the connection string. Deploying `app.py` on Streamlit Community Cloud
  with the token as a platform secret turns the delivery into a live **link**.

```bash
# build/serve the CLOUD store (needs MOTHERDUCK_TOKEN in .env):
DBT_DUCKDB_PATH=md:dogs ./scripts/run_pipeline.sh    # cron does this nightly
DOGS_DB=md:dogs streamlit run dashboard/app.py        # dashboard reads the cloud
./scripts/observability_report.sh md:dogs             # observability report from the cloud
```

<!-- HOSTED LINK: added here once the Streamlit Community Cloud deploy is live. -->

---

## Secrets

`DOG_API_KEY` is the primary secret — locally in a gitignored `.env` (template: `.env.example`), in CI
a GitHub Actions secret. **`MOTHERDUCK_TOKEN`** is a second, **optional** secret, needed only for the
M9 cloud path (same handling: `.env` locally, an Actions secret for the cron). Both are read from the
environment, never committed, never logged.

---

## Next, given more time

Recorded in [`DECISIONS.md` → "What I'd build next"](DECISIONS.md). The keystone — durable storage —
is **now built (M9 Part B)**, which delivered the observability trend view and hosted serving above.
Still future: **SCD-2 snapshots** for full change history, **incremental** models at scale, **IaC**
(Terraform the ruleset + secrets), an **alert** on a failed cron, and the **LLM enrichment** bonus
(specified, not built).
