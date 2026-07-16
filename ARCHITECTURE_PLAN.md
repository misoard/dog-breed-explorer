# Architecture Plan — Dog Breed Explorer (Heyra Data Engineer Case)

This is **my** plan. Claude Code implements against it, layer by layer, and I review each
milestone before moving on. The commit history should mirror these milestones.

## The stack (right-sized, every choice defensible)

| Layer | Tool | One-line justification |
|---|---|---|
| Ingestion | `dlt` **or** Python + `requests` + `tenacity` | idempotent, preserves raw payload, retry on transient failure |
| Warehouse | **DuckDB** | analytical (OLAP) workload, zero-ops, native JSON |
| Transform/model/test | **dbt Core** (`dbt-duckdb`) | SELECT-based models, `ref()` DAG, tests, docs, dev/prod targets |
| Version control | **GitHub** | incremental commits, secrets out of repo |
| CI/CD | **GitHub Actions** | test+build on PR, scheduled run on merge |
| Orchestration | **Actions cron @ 02:00 UTC** | one daily job — Airflow would be overkill (deliberate) |
| Dashboard | **Streamlit** (or Evidence.dev) | thin reader of gold marts; export PDF/screenshots |
| Bonus | LLM enrichment | free-text → structured column, evaluated |

## The data flow (decoupled write vs read paths)

```
        WRITE PATH (daily, automated)                         READ PATH (on demand)
   ┌─────────────────────────────────────────┐          ┌────────────────────────┐
   │ Dog API                                  │          │ Dashboard (Streamlit)  │
   │   │  (fetch, retry, validate complete)   │          │   reads gold marts,    │
   │   ▼                                      │          │   renders 2+ questions │
   │ RAW / bronze  (payload untouched,        │          └───────────▲────────────┘
   │   │            partitioned by run_date)  │                      │
   │   ▼   ── dbt ──                          │                      │
   │ STAGING / silver (parsed, typed, deduped)│                      │
   │   │                                      │                      │
   │   ▼                                      │                      │
   │ MARTS / gold (dim_breeds + aggregates)   │──────────────────────┘
   └─────────────────────────────────────────┘
   Scheduled by GitHub Actions cron @ 02:00 UTC.  Dashboard never triggers the pipeline.
```

Key point to articulate in the debrief: the **pipeline** builds the gold layer daily; the
**dashboard** reads whatever gold currently holds, at any time. Two independent cadences.

## Repo / folder structure

```
dog-breed-explorer/
├─ README.md                     # setup + dashboard narrative (what the data SAYS) + CI badge
├─ DECISIONS.md                  # the 35% file — one paragraph per layer, filled as I build
├─ SPEC.md                       # the concrete schema + parser + tests (filled from real data)
├─ CLAUDE.md                     # persistent context for Claude Code (distilled rules)
├─ .gitignore                    # .env, *.duckdb, dbt target/, __pycache__
├─ .env.example                  # DOG_API_KEY=...   (real .env gitignored)
├─ pyproject.toml / requirements.txt
│
├─ exploration/                  # M0 + M0.5 — throwaway analysis, NOT pipeline code
│  ├─ profile_breeds.py          # M0: profiling script
│  ├─ PROFILE_REPORT.md          # M0: the findings (done)
│  ├─ explore_app.py             # M0.5: throwaway Streamlit explorer (rough-parse + eyeball)
│  ├─ raw_breeds.json            # saved payload (dev fixture)
│  └─ sample_breeds.json         # a few representative records
│
├─ ingestion/
│  └─ ingest.py                  # M1: fetch + retry + land raw into DuckDB, partitioned by run_date
│
├─ dbt/                          # the dbt project (M2–M4)
│  ├─ dbt_project.yml
│  ├─ profiles.yml               # dev + prod DuckDB targets (parameterized)
│  ├─ models/
│  │  ├─ staging/
│  │  │  ├─ _sources.yml         # declares raw.breeds as a dbt source
│  │  │  ├─ _staging.yml         # tests + docs for staging
│  │  │  ├─ stg_breeds.sql       # parse life_span/weight/height, sentinels→null, type, dedupe
│  │  │  └─ stg_breed_temperaments.sql  # split + normalise (lowercase) tags
│  │  └─ marts/
│  │     ├─ _marts.yml           # tests + docs for marts
│  │     ├─ dim_breeds.sql       # clean + derived (size_class, midpoints, life_span_range)
│  │     ├─ breed_temperaments.sql       # bridge (breed_id, normalised tag)
│  │     ├─ mart_size_class_summary.sql # grain: size_class — counts + mean life span
│  │     └─ mart_size_vs_lifespan.sql    # pre-agg for dashboard Q
│  └─ tests/                     # custom SQL tests (return rows = fail)
│     ├─ assert_lifespan_min_le_max.sql
│     ├─ assert_weight_min_le_max.sql
│     └─ assert_no_unknown_sentinel.sql
│
├─ dashboard/
│  └─ app.py                     # M6: Streamlit; reads gold marts; renders 2+ questions (thin)
│
├─ enrichment/                   # M7 BONUS (only if fundamentals solid)
│  └─ enrich.py                  # LLM: temperament/description -> structured column
│
└─ .github/
   └─ workflows/
      ├─ ci.yml                  # on PR: install, dbt build, dbt test (visible status/badge)
      └─ scheduled.yml           # cron 02:00 UTC: ingest -> dbt build

Committed for transparency: exploration/ (shows I profiled first). Gitignored: .env, the
.duckdb file, dbt target/. Schema details live in SPEC.md; reasoning in DECISIONS.md.
```

## The messy fields (where 25% of the score lives — do these carefully)

- `life_span` "10 - 12 years" → `life_span_min_years` INT, `life_span_max_years` INT, midpoint
- `weight` metric "6 - 13" → `weight_min_kg` FLOAT, `weight_max_kg` FLOAT (handle single value + null)
- `temperament` "Playful, Curious, ..." → **bridge table** `breed_temperaments(breed_id, temperament)` so it's queryable
- `size_class` derived from weight midpoint → toy/small/medium/large/giant (define boundaries)
- sparse fields → NULL, never crash

## Milestones (= commits; review each before moving on)

**M0 — Design & explore (Day 1)**
- [ ] Finalize this plan + DECISIONS.md skeleton committed.
- [ ] Fetch sample from API; profile fields (null rate, distinct values, format variants).
      Record findings in DECISIONS.md §3.
- [x] **DONE — profiling complete** (628 rows, 17 fields). Findings in exploration/PROFILE_REPORT.md.
- [x] **DONE — SPEC.md written** from the real data (schema, parser, dedup, tests). SPEC.md is now
      the authoritative build document (it replaced the old DETAILED_SPEC_template.md).
      (Don't design the schema before seeing the data — the spec is an M0 *output*.)
- [ ] Learn dbt hands-on — **NOT a separate repo.** Preferred: learn on the real project by
      studying each model Claude builds (ask it to explain `ref()`/`source()`, modify + re-run).
      Only if dbt isn't clicking: 20–30 min in a disposable local scratch folder (e.g. /tmp/dbt-learn,
      never committed) to feel models + `ref()` + a test on trivial data, then delete it.
- [ ] Write CLAUDE.md (distilled rules) + commit the repo skeleton.

**M0.5 — Exploratory viz: choose the questions, validate assumptions (½ day, throwaway)**
> Rationale: I can't choose which questions have interesting answers, or confirm my size_class
> buckets, without SEEING the data — profiling gives structure, not distribution. This pass looks
> before committing. It also prototypes the parser early, de-risking the hardest piece (M2).
- [ ] `exploration/explore_app.py`: a **throwaway Streamlit explorer** (~40 lines, no polish) that
      rough-parses weight/height/life_span from raw_breeds.json (prototypes the parser) and shows,
      on one page: the size-vs-lifespan scatter, a size_class bar chart with **adjustable bucket
      boundaries**, the weight quantiles, and temperament frequencies. Interactive so I can eyeball
      and tweak buckets live.
- [ ] **Decide the final ≥2 dashboard questions** based on which show a clear signal.
      (Leaning: size-vs-lifespan + weight-class distribution.)
- [ ] **Confirm/adjust the size_class bucket boundaries in SPEC.md** against the real weight
      distribution (drag them in the explorer, read the quantiles). Record final boundaries +
      reasoning in DECISIONS.md.
- [ ] Throwaway — NOT the production dashboard (M6, which reads the dbt gold marts). Screenshot
      anything useful into DECISIONS.md, then delete the app. Half a day max; if I'm styling, stop.

**M1 — Ingestion (Day 2)**
- [ ] Fetch all breeds, retry+backoff, land RAW into DuckDB partitioned by run_date, payload untouched.
- [ ] Idempotent: re-running yields same row count (no duplicates). Validate completeness before promote.
- [ ] Commit: "feat: idempotent ingestion of Dog API into raw layer".

**M2 — dbt staging/silver (Day 3 am)** — build to SPEC.md
- [ ] `_sources.yml` → raw.breeds. `stg_breeds.sql`: the metric range parser (handles simple
      `X-Y`, sex-specific `Male:…;Female:…`, and `'unknown'`→NULL), type everything, drop dead
      fields (species_id, bred_for, perfect_for, country_codes), **dedupe the Caucasian Shepherd**.
- [ ] `stg_breed_temperaments.sql`: split comma list, **lowercase+trim** each tag (casing fix).
- [ ] Commit per meaningful step. This is the hardest piece — understand the parser line by line.

**M3 — dbt marts/gold (Day 3 pm)** — build to SPEC.md
- [ ] `dim_breeds` (clean typed + derived: weight_mid_kg, size_class, life_span_range).
- [ ] `breed_temperaments` bridge (normalised tag).
- [ ] The marts for the chosen questions (names canonical in SPEC.md): `mart_size_class_summary`
      (size_class grain), `mart_size_vs_lifespan` (breed grain), `mart_metric_correlation`,
      `mart_size_scaling_fit`. Plus the `size_class_bands` seed — boundaries live ONLY there.
      (Add `mart_top_temperaments` only if that's a chosen 3rd question.)
- [ ] Business logic lives HERE, not in the dashboard.

**M4 — Tests + docs (Day 3 pm)**  ← the TDD loop lives here (declare tests as the contract FIRST)
- [ ] **Hard invariants (`severity: error`)** per SPEC.md: unique+not_null(breed_id);
      accepted_values(size_class incl. 'unknown'); custom weight_min<=max; custom lifespan_min<=max;
      **custom no-'unknown'-sentinel** (guards future runs); range check on weight_mid;
      relationships + unique(breed_id, temperament) on the bridge; unit-ratio plausible; seed bands
      contiguous.
- [ ] **Distributional guards (`severity: warn`)** — three, no more: `unknown` bucket ≤1% (now
      0.3%); row count 628 ±5%; life-span null rate ≤10% (now 6.4%). Rationale in DECISIONS.md §3:
      invariants error, anomalies warn — data can degrade without breaking any invariant, and
      legitimate drift shouldn't auto-fail the build.
- [ ] `dbt docs generate` → capture the lineage graph for the debrief.

**M5 — CI/CD + schedule (Day 4 am)**
- [ ] GitHub Actions: on PR → install + `dbt build` + tests (visible status/badge).
- [ ] On merge → scheduled cron @ 02:00 UTC runs the full pipeline. Secrets in Actions.

**M6 — Dashboard + narrative (Day 4 pm)**
- [ ] Streamlit reads gold marts, answers ≥2 questions. Thin.
- [ ] README narrative: what the data SAYS. Export PDF/screenshots.

**M7 — LLM bonus (Day 4 pm, only if M0–M6 solid)**
- [ ] Enrichment from **temperament + description** (NOT bred_for — it's 100% null per profiling)
      → energy_level or good_with_kids column, folded into dim_breeds.
- [ ] Batch all 628 in one pass, cache by breed_id, prompt + cost/latency note + light eval.

**M8 — Polish & submit (Day 5, ≥24h before Tue 11am → submit by Mon 11am)**
- [ ] Finish DECISIONS.md incl. "what I'd do next".
- [ ] Rehearse: walk any dbt model, explain `ref()` + the lineage graph, one decision I'm proud of + one I'd change.
- [ ] Submit repo link with read access.

---

## M0.5 prompt — throwaway interactive explorer (paste now, reads saved raw_breeds.json)

> I've profiled the Dog API data (628 rows; see exploration/PROFILE_REPORT.md) and I now want a
> quick, **throwaway interactive Streamlit explorer** to eyeball the data, decide which dashboard
> questions have interesting answers, and settle my size buckets. This is DISPOSABLE scratch — NOT
> the production dashboard (that's a later milestone, built from the dbt gold layer). Keep it
> minimal: ~40 lines, one page, no theming, no tabs, no captions. Don't build dbt or ingestion.
>
> Read the already-saved `exploration/raw_breeds.json`. Write `exploration/explore_app.py` (a
> Streamlit app) that:
> 1. Rough-parses the messy metric fields inline (this also prototypes my real parser): `weight.metric`
>    and `height.metric` come in three shapes — simple `"3.2-4.5"`, sex-specific
>    `"Male: 25-30; Female: 20-25"`, and literal `"unknown"`. Extract ALL numbers per value, take
>    overall min/max; `"unknown"` → null. `life_span` is `"X-Y"` (no units), ~6.4% null.
> 2. On one page, shows just enough to DECIDE:
>    - a scatter of weight-midpoint vs life-span-midpoint (is there a visible relationship?),
>    - a bar chart of breeds per size_class, with the **bucket boundaries as adjustable number
>      inputs** (default toy<5, small 5-10, medium 10-25, large 25-45, giant>45 kg) so I can drag
>      them and watch the distribution re-bucket live,
>    - the printed weight **quantiles** (so I can sanity-check the buckets against reality),
>    - a simple table of temperament tag frequencies (lowercased).
> 3. That's it. No styling, no extra widgets. I'll run it, click around for ~20 min, decide my two
>    questions + final buckets, screenshot anything useful into DECISIONS.md, then delete the app.
>
> Stop after it runs. Remind me this is throwaway and the production dashboard will read the dbt
> gold marts, not this rough in-app parse.

## M1 kickoff prompt — ingestion (paste after M0.5, once questions are locked)

> I'm building the Heyra "Dog Breed Explorer" data-engineering case. I've designed the
> architecture (see ARCHITECTURE_PLAN.md, SPEC.md, CLAUDE.md) and I want you to implement it
> **layer by layer, pausing after each milestone so I can review** — do NOT one-shot it. I'm being
> tested on understanding every piece, so explain your choices as you go, especially the dbt models
> and how `ref()` wires them.
>
> Stack (decided — don't change without flagging a tradeoff): ingestion = [dlt / Python+requests+
> tenacity — my choice]; warehouse = DuckDB; transform/test/docs = dbt Core with dbt-duckdb; CI/CD
> + daily 02:00 UTC = GitHub Actions; dashboard = Streamlit; git with incremental commits per milestone.
>
> Source: https://api.thedogapi.com/v1/breeds — **an API key IS required**. Unauthenticated calls
> return **403 Forbidden**; the 628 breeds only came back once the key was sent as an `x-api-key`
> header. The key lives in a gitignored `.env` as `DOG_API_KEY` (see `.env.example`), is read from
> the environment by the ingestion job, and **must be added to GitHub Actions secrets** or the daily
> cron will fail. Never commit it; never log it.
>
> **Milestone 1 (ingestion) only:** fetch all breeds with retry+backoff, land the raw untouched
> payload into a DuckDB raw layer partitioned by run_date (with a loaded_at timestamp), make re-runs
> idempotent (re-running yields 628 rows, no duplicates), and validate the response is complete
> (expect ~628) before promoting — a partial/failed fetch must NOT overwrite last-good data. Stop
> when M1 works so I can review. Then we'll do the dbt layers to SPEC.md.
