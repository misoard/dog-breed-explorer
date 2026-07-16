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
│  ├─ raw_breeds.json            # saved payload — GITIGNORED (regenerable source data, not code)
│  └─ sample_breeds.json         # a few representative records
│
├─ ingestion/
│  └─ ingest.py                  # M1: fetch + retry + land raw into DuckDB, partitioned by run_date
│
├─ dbt/                          # the dbt project (M2–M4)
│  ├─ dbt_project.yml
│  ├─ profiles.yml               # dev + prod DuckDB targets (parameterized) — built in M2
│  ├─ seeds/
│  │  └─ size_class_bands.csv    # the ONLY home of the 5/12/25/45 boundaries (SPEC)
│  ├─ models/
│  │  ├─ staging/
│  │  │  ├─ _sources.yml         # declares raw.breeds as a dbt source
│  │  │  ├─ _staging.yml         # tests + docs for staging
│  │  │  ├─ stg_breeds.sql       # latest run_date only; parse life_span/weight/height,
│  │  │  │                       #   sentinels→null, type, dedupe
│  │  │  └─ stg_breed_temperaments.sql  # split + normalise (lowercase) tags
│  │  └─ marts/
│  │     ├─ _marts.yml           # tests + docs for marts
│  │     ├─ dim_breeds.sql       # clean + derived (size_class, midpoints, life_span_range)
│  │     ├─ breed_temperaments.sql       # bridge (breed_id, normalised tag)
│  │     ├─ mart_size_class_summary.sql  # grain: size_class — counts + mean life span
│  │     ├─ mart_size_vs_lifespan.sql    # grain: breed — scatter-ready (no height: no reader)
│  │     ├─ mart_metric_correlation.sql  # grain: (metric_a, metric_b) — 3 rows + n_breeds
│  │     └─ mart_size_class_temperaments.sql  # grain: (size_class, tag) — count + % of class
│  │                                     # (mart_size_scaling_fit CUT — an isometry exponent is
│  │                                     #  not a "fact about dog breeds"; see DECISIONS.md §0)
│  └─ tests/                     # custom SQL tests (return rows = fail)
│     ├─ assert_weight_min_le_max.sql        # error — invariants
│     ├─ assert_lifespan_min_le_max.sql      # error
│     ├─ assert_no_unknown_sentinel.sql      # error — guards FUTURE runs
│     ├─ assert_size_class_bands_cover.sql   # error — seed contiguous, no gaps/overlaps
│     ├─ assert_no_breed_unbanded.sql        # error — a real weight always finds a band
│     ├─ assert_unit_ratio_plausible.sql     # error — units inferred, not declared
│     ├─ assert_tag_not_freetext.sql         # warn  — sentence-as-tag
│     ├─ assert_unknown_bucket_small.sql     # warn  — distributional guards (M4)
│     ├─ assert_row_count_stable.sql         # warn
│     └─ assert_lifespan_null_rate_stable.sql # warn
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

Committed for transparency: exploration/ code + reports (shows I profiled first). Gitignored: .env,
the .duckdb file, dbt target/, and exploration/raw_breeds.json (source data, regenerable by running
the ingestion). Schema details live in SPEC.md; reasoning in DECISIONS.md.
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
- [x] **KEPT, not deleted** (supersedes the original "delete the app" line, which contradicted
      CLAUDE.md's "keep `exploration/` committed"). It stays in `exploration/` as evidence I profiled
      and looked before designing — the M0.5 findings are what froze the buckets and picked the two
      questions. It is still **throwaway in status**: NOT the production dashboard (M6 reads the dbt
      gold marts), never wired into the pipeline, and its rough in-app parse is not the real parser.

**M1 — Ingestion (Day 2)**
- [x] **DONE** — `ingestion/ingest.py`: fetch all breeds, retry+backoff, land RAW into DuckDB
      partitioned by run_date, payload untouched (verbatim JSON).
- [x] **DONE** — Idempotent per run_date: re-running replaces that day's partition → 628 rows, no
      duplicates. Completeness validated (≥90% of last-good partition) before promote; a truncated
      pull, a bad key and a missing key all exit 1 leaving last-good data intact.
- [x] **DONE** — **stateless**: no state between runs; each run re-fetches and rebuilds, so CI's
      empty VM is a supported start. run_date still partitions raw (idempotency + the case study
      asks for it). Locally partitions accumulate as a side effect, so **`stg_breeds` must filter to
      the latest run_date** — M2's first obligation. Reverses the earlier accumulate-history
      design; rationale + what I'd do with durable storage in DECISIONS.md §1.
- [x] **RESOLVED — CI proves, laptop serves.** Statelessness settled *history*; *handoff* is settled
      by scope: the pipeline runs locally and the dashboard reads the local `dogs.duckdb`, demoed
      live. GitHub Actions only answers "does the code still work?" and discards its warehouse. The
      handoff problem disappears because producer and consumer are both on durable hardware.
      Deliberate POC scope, not an oversight — DECISIONS.md §5.
- [x] Commit: "feat: idempotent ingestion of Dog API into raw layer".

**M2 — dbt staging/silver (Day 3 am)** — build to SPEC.md
- [ ] **Scaffold + the dev/prod targets** (`dbt_project.yml`, `profiles.yml`). Not optional and not
      deferrable to M5: `dbt build` resolves a profile before it compiles anything, so the two
      targets exist from dbt's first run. **dev is the default** (`dogs_dev.duckdb`), prod is
      `dogs.duckdb`. M5 doesn't create the split — it only picks `--target prod`. Schema + the
      ingest.py/dbt shared-path seam are in SPEC.md ("dbt targets"). *(Scored: "parameterize so it
      can run against both a dev and a prod target" — it was in the folder tree but no milestone
      owned it.)*
- [ ] `_sources.yml` → raw.breeds (**and `stg_breeds` filters to the latest `run_date`** — see
      CLAUDE.md/DECISIONS.md §1; without it, a second local run double-counts every breed).
- [ ] `stg_breeds.sql`: the metric range parser (handles simple
      `X-Y`, sex-specific `Male:…;Female:…`, and `'unknown'`→NULL), type everything, drop dead
      fields (species_id, bred_for, perfect_for, country_codes), **dedupe the Caucasian Shepherd**.
- [ ] `stg_breed_temperaments.sql`: split comma list, **lowercase+trim** each tag (casing fix).
- [ ] Commit per meaningful step. This is the hardest piece — understand the parser line by line.

> **The TDD loop runs INSIDE M2 and M3 — one model + its tests is one unit of work.** For each
> model: declare its tests first → stub the model → watch real assertions fail → fix → `dbt build`
> until green → commit → next model. Do NOT build M2+M3 and test at M4; a contract written after
> the model is a description, not a contract. This aligns the plan with CLAUDE.md ("declare
> before/with the models"), which M4 previously contradicted.
>
> **Honest mechanics (don't overclaim red-green):** `dbt test` on a model that doesn't exist yet
> *errors* ("model not found") rather than failing an assertion — so the loop is **contract-first,
> then iterate to green**, with a stub producing the first genuine red. That is TDD in spirit, and
> defensible; claiming a textbook red-green cycle for dbt is not.
>
> Per-model invariants interleave here. The three **distributional guards stay in M4** — they
> describe the finished pipeline ("628 ±5%") and can't be asserted against a half-built DAG.

**M3 — dbt marts/gold (Day 3 pm)** — build to SPEC.md · same interleaved test loop as M2
- [ ] The `size_class_bands` **seed first** — `dim_breeds` joins it, so it exists before the model
      that needs it. Boundaries live ONLY there. Tests: `assert_size_class_bands_cover` (contiguous,
      no gaps/overlaps).
- [ ] `dim_breeds` (clean typed + derived: weight_mid_kg, size_class, life_span_range).
      Tests with it: unique+not_null(breed_id), accepted_values(size_class incl. 'unknown'),
      `assert_no_breed_unbanded`, weight_mid range check.
- [ ] `breed_temperaments` bridge (normalised tag). Tests with it: relationships → dim_breeds,
      **unique on (breed_id, temperament)** (load-bearing — a dup tag double-counts every
      aggregate), `assert_tag_not_freetext` (warn).
- [ ] The marts for the chosen questions (names canonical in SPEC.md): `mart_size_class_summary`
      (size_class grain), `mart_size_vs_lifespan` (breed grain — **no `height_mid_cm`**, its only
      readers were cut), `mart_metric_correlation` (**pairwise** population, carries `n_breeds`).
- [ ] `mart_size_class_temperaments` — grain (size_class, temperament); `GROUP BY` + `COUNT` over
      `ref('breed_temperaments')` × `ref('dim_breeds')`, plus **`pct_of_class`** (count / breeds in
      class) so big classes don't win on raw counts alone. Top-N stays in the dashboard, not gold.
      Tests with it: unique(size_class, temperament), `assert_pct_of_class_sane`
      (`breed_count <= breeds_in_class`, pct in (0,100]) — the inequality is what catches a
      fan-out in the bridge join.
- [ ] **CUT: `mart_size_scaling_fit`** and the height-vs-weight curve. An isometry exponent is not a
      fact about a dog breed — the rule is *descriptive fact → gold, inferential cleverness →
      DECISIONS.md §0*. Don't rebuild it.
- [ ] Business logic lives HERE, not in the dashboard.

**M4 — Pipeline-level guards + docs (Day 3 pm)**
> **The per-model TDD loop already ran in M2/M3** — the hard invariants were declared *with* their
> models and are green before M4 starts. What's left here is only what could NOT interleave: guards
> that describe the *finished* pipeline, and the docs that need the whole DAG to exist.
- [ ] **Distributional guards (`severity: warn`)** — three, no more: `unknown` bucket ≤1% (now
      0.3%); row count 628 ±5%; life-span null rate ≤10% (now 6.4%). Rationale in DECISIONS.md §3:
      invariants error, anomalies warn — data can degrade without breaking any invariant, and
      legitimate drift shouldn't auto-fail the build.
- [ ] Verify the M2/M3 invariants are complete against SPEC's list (nothing silently skipped).
- [ ] `dbt docs generate` → capture the lineage graph for the debrief.

**M5 — CI/CD + schedule (Day 4 am)**
- [ ] GitHub Actions: on PR → install + `dbt build` + tests (visible status/badge). Runs
      **`--target prod`**; `DBT_DUCKDB_PATH` sets ingest.py's `--db` and the dbt target from ONE
      env var (they must agree on a path — SPEC "dbt targets").
- [ ] Cron @ 02:00 UTC: ingest → `dbt build --target prod` → tests → **discard the warehouse**.
      **CI proves the pipeline; it does not serve it** (DECISIONS.md §5) — the run is a health check
      with a real API call attached, which is what catches the API changing shape or the key
      expiring. Not a deployment; say so out loud rather than letting it look like an oversight.
- [ ] **`DOG_API_KEY` as an Actions secret** — the cron 403s without it. Nothing else is secret.

**M6 — Dashboard + narrative (Day 4 pm)**
- [ ] Streamlit reads the gold marts from the **local `dogs.duckdb`** (the prod target build) and is
      demoed live — not hosted. Thin: no logic, no parsing, no `pd.cut`. Answers ≥2 questions.
- [ ] README narrative: what the data SAYS. Export PDF/screenshots.

**M7 — LLM bonus (Day 4 pm, only if M0–M6 solid)**
- [ ] Enrichment from **temperament + description** (NOT bred_for — it's 100% null per profiling)
      → energy_level or good_with_kids column, folded into dim_breeds.
- [ ] **Pattern A — enrich.py writes a table, dbt reads it.** `enrich.py` reads `stg_breeds`, calls
      the LLM, writes `raw.breed_enrichment` (keyed by breed_id). `dim_breeds` joins it via
      `source()` — dbt doesn't build it, Python does. New pipeline order:
      **ingest → `dbt build` staging → `enrich.py` → `dbt build` marts** (two dbt invocations with a
      Python step between). Cost: the pipeline is no longer one `dbt build`. Benefit: dbt never makes
      a network call, so the build stays deterministic; enrichment is inspectable before gold; a
      failed LLM run leaves the last enrichment in place. Rejected: a dbt Python model calling the
      LLM mid-build.
- [ ] **LEFT JOIN, never inner** — a missing enrichment must not drop a breed from dim_breeds.
- [ ] Batch all 628 in one pass, cache by breed_id, prompt + cost/latency note + light eval
      (`accepted_values` on the enum — LLM output is untrusted input — plus a few hand-labels).

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
