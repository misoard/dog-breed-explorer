# CLAUDE.md — Dog Breed Explorer (Heyra data-engineering case)

Persistent context for Claude Code. Read this every session. The detailed schema is in
`SPEC.md`; reasoning/tradeoffs go in `DECISIONS.md`; the milestone plan is in
`ARCHITECTURE_PLAN.md`. When they conflict with this file, flag it — don't silently choose.

## How we work together (important)
- **Build layer by layer. Pause after each milestone so I can review before continuing.** Do NOT
  one-shot the project. I'm being tested on understanding what you built, so this is non-negotiable.
- **Explain your choices as you go** — especially dbt models and how `ref()` / `source()` wire the
  DAG. If I couldn't explain a piece to an interviewer, we're going too fast.
- **Commit incrementally, one commit per meaningful step** (not one giant final commit). The commit
  history should read like the milestones.
- If a decision isn't covered here or in SPEC.md, ask me rather than assuming.

## The stack (decided — don't change without flagging a tradeoff)
- Ingestion: Python + `requests` + `tenacity` (or `dlt` — my call, confirm before switching).
- Warehouse: **DuckDB** (single file, e.g. `dogs.duckdb`). Analytical/OLAP, zero-ops, native JSON.
- Transform / test / docs: **dbt Core** with the `dbt-duckdb` adapter.
- Version control: **git / GitHub**, incremental commits.
- CI/CD + scheduling: **GitHub Actions** (test on PR; cron daily @ 02:00 UTC on main).
- Dashboard: **Streamlit**, thin — reads gold marts only.
- Right-sizing is deliberate: NO Airflow/Kubernetes/managed warehouse for one daily job. If you
  think we need a heavier tool, flag it as a tradeoff and let me decide.

## Architecture (bronze → silver → gold, write/read decoupled)
- **raw / bronze** (`raw.breeds`): untouched API payload + `run_date`, `loaded_at`. Built by ingestion.
- **staging / silver** (dbt): parse, type, clean, dedupe.
- **marts / gold** (dbt): `dim_breeds` + bridge + aggregate marts. **All business logic lives here.**
- **Dashboard** reads gold on demand. It NEVER triggers the pipeline. Keep it thin — no business
  logic in the dashboard.
- The daily source is effectively static; "daily freshness" is a proxy for a real changing source,
  so the point is **idempotency + partial-failure safety**, not new volume.

## Non-negotiable rules
- **Secrets never in the repo.** `/v1/breeds` **requires an API key** — unauthenticated calls return
  **403 Forbidden**. `DOG_API_KEY` lives in a gitignored `.env` (template: `.env.example`), is read
  from the environment, and **must be set as a GitHub Actions secret** or the daily cron fails.
  Never commit it, never log it.
- **Idempotent ingestion:** re-running yields **628 rows, no duplicates**. A partial/failed fetch
  must NOT overwrite last-good data.
- **Business logic in dbt gold, dashboard thin.** Derived columns are explicit, typed, tested —
  never computed on the fly in the dashboard.
- Gitignore: `.env`, `*.duckdb`, dbt `target/`, `__pycache__`. Keep `exploration/` committed.

## Data facts that drive the model (from profiling — see SPEC.md for full schema)
- 628 rows; `id` unique+non-null → PK = `id` (cast INTEGER).
- `weight.metric` / `height.metric` are **kg / cm** (units inferred from imperial:metric ratio,
  not declared — assert this in a test). Mostly **sex-specific ranges** "Male: X-Y; Female: A-B".
  Collapse to a **whole-breed envelope**: `weight_min_kg`=overall min, `weight_max_kg`=overall max,
  store `weight_mid_kg`=(min+max)/2 explicitly; `size_class` buckets from the midpoint. Do NOT
  split male/female into separate columns.
- `'unknown'` string sentinels in a few weight/height rows → convert to NULL **before** casting.
- `life_span` is "X-Y" (no "years" suffix), ~6.4% null → min/max/midpoint.
- `temperament` comma-separated → bridge table, tags **lowercased + trimmed** (casing is inconsistent).
- Duplicate breed "Caucasian Shepherd Dog" (ids 70 & 269) → dedupe in staging.
- Drop dead fields: `species_id` (constant), `bred_for` + `perfect_for` (100% null), `country_codes`
  (== `country_code`). LLM bonus must NOT use `bred_for` (empty) — derive from temperament/description.

## Tests are the contract (declare before/with the models — this is the TDD loop)
Minimum per SPEC.md: `breed_id` unique+not_null; `size_class` accepted_values (incl. 'unknown');
custom weight_min<=max; custom lifespan_min<=max; custom no-'unknown'-sentinel; unit-ratio
plausible; bridge relationships. Iterate models against `dbt build` / `dbt test` until green.

## Dashboard questions — CONFIRMED in M0.5 (answering 2 of 4)
(1) **breeds per weight class**, (2) **size vs life span**. Both read `mart_size_class_summary` /
`mart_size_vs_lifespan`. Narrative states what the data SAYS ("smaller breeds tend to live longer";
13.3 yr toy → 10.6 yr giant), and calls lifespan "midpoint of published range".
- **"Size" = weight, not height** — weight↔life −0.671 vs height↔life −0.503, and the two are
  0.860-coupled, so height adds little. Evidence in `mart_metric_correlation`.
- **Never a dual-axis chart.** Counts and life span render as two charts stacked on a shared
  x-axis. Two y-scales align arbitrarily and fabricate a relationship. See DECISIONS.md §0.
- **size_class boundaries are half-open `[min_kg, max_kg)`** and live ONLY in
  `seeds/size_class_bands.csv` (5/12/25/45). 31 breeds sit exactly on a boundary, so the closed side
  is load-bearing; `pd.cut` defaults to the opposite convention (use `right=False`).
