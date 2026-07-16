# CLAUDE.md — Dog Breed Explorer (Heyra data-engineering case)

Persistent context for Claude Code. Read this every session. The detailed schema is in
`SPEC.md`; reasoning/tradeoffs go in `DECISIONS.md`; the milestone plan is in
`ARCHITECTURE_PLAN.md`. When they conflict with this file, flag it — don't silently choose.

## How we work together (important)
- **Build layer by layer. Pause after each milestone so I can review before continuing.** Do NOT
  one-shot the project. I'm being tested on understanding what you built, so this is non-negotiable.
- **Explain your choices as you go** — especially dbt models and how `ref()` / `source()` wire the
  DAG. If I couldn't explain a piece to an interviewer, we're going too fast.
- **NEVER `git add`, `git commit`, or `git push` on your own initiative** — not even "just one small
  commit", not even when a milestone is obviously finished. **I ship, from chat, with `/ship`**,
  once I've reviewed the work myself. Rationale: a commit you made for me is a milestone I didn't
  read, which defeats the entire point of building layer by layer. Finish the work, tell me it's
  done, and stop. Waiting is the correct behaviour, not a failure to act.
- **When I run `/ship`, these rules apply** (they're in `.claude/skills/ship/SKILL.md` too):
  - One commit = **one logical, working step**; the subject explains it in **one sentence**. The
    history reads like the milestones (M0 · M1 · M2…), not like a changelog of an afternoon's edits.
    A fixup for a bug introduced minutes ago is **not its own commit** — fold it in. The tests-first
    loop happens *inside* a commit, never as commits (no `wip: parser red`): a model and its tests
    are one unit, so they land together.
  - **Commit messages are NOT documentation.** Reasoning → DECISIONS.md · narrative + reversals →
    DAY_REPORT.md · schema → SPEC.md. The message says *what changed* and points at those files; it
    never duplicates them. _(Learned the hard way: M0–M1 produced 10 commits — 8 of them one
    afternoon of doc churn — with 17–31-line essay messages, for 2 real milestones. Squashed to 4.)_
  - **Secrets never reach the agent.** The SSH key passphrase lives in the **macOS Keychain**
    (`ssh-add --apple-use-keychain`), never in `.env`, a file, an env var, or a skill. `/ship` runs
    `git push` and ssh-agent authenticates — the skill handles no credential at all.
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
- **Stateless — the API is the source of truth.** Every run re-fetches and rebuilds; no state
  survives between runs. `run_date` partitions raw for idempotency (DELETE+INSERT of the day's
  partition), NOT to build a history — that was tried and reversed (DECISIONS.md §1). A fresh empty
  warehouse is a supported start. Locally the file persists, so partitions accumulate as a side
  effect → **`stg_breeds` MUST filter to the latest `run_date`**.
- **CI proves the pipeline; the laptop serves it.** Actions ingests, builds, tests, goes green, and
  discards its warehouse. The Streamlit demo reads the local `dogs.duckdb`, live. Deliberate POC
  scope (DECISIONS.md §5) — don't "fix" it by adding S3/MotherDuck/artifact persistence.
- **Two dbt targets, same code (scored):** `dev` → `dogs_dev.duckdb` (iterating), `prod` →
  `dogs.duckdb` (CI + the local demo build the dashboard reads). Only the path differs — never the
  SQL. `ingest.py --db` must point at the same file as the target. Schema in SPEC.md.

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

## Dashboard questions — CONFIRMED in M0.5 (answering 3 of 4)
(1) **breeds per weight class**, (2) **size vs life span**, (3) **characteristic temperaments per
size class**. Read `mart_size_class_summary` / `mart_size_vs_lifespan` /
`mart_size_class_temperaments` (+ `mart_metric_correlation` numbers as the size=weight evidence).
Narrative states what the data SAYS ("smaller breeds tend to live longer"; 13.3 yr toy → 10.6 yr
giant; "temperament varies systematically with size"), and calls lifespan "midpoint of published
range".
- **Q3 is a `GROUP BY size_class, temperament` + `COUNT`, plus `pct_of_class`** (count / breeds in
  class) — raw counts favour big classes. Normalising within a group is arithmetic; comparing to a
  baseline is inference. **No lift, no baseline** — that's the line. Top-N is the dashboard's job,
  not gold's.
- **CUT — do not build:** `mart_size_scaling_fit` (isometry exponent k) and the height-vs-weight
  curve. An exponent is not a "fact about dog breeds". Rule: **descriptive fact → gold, inferential
  cleverness → DECISIONS.md §0.** `mart_metric_correlation` stays (it's about life span).
  `height_mid_cm` is NOT in `mart_size_vs_lifespan` — no reader. Height stays a fact in `dim_breeds`
  + `mean_height_cm` in `mart_size_class_summary`.

## dbt mechanics (decided — SPEC.md is canonical)
- **staging = view in `main_staging`; marts = table in `main_marts`**; set in `dbt_project.yml`
  (`+schema: staging` concatenates onto `main`), never per model. Views for a parse pass with one
  consumer; tables for what a dashboard reads repeatedly.
- **LLM bonus = Pattern A:** `enrich.py` reads `stg_breeds` → LLM → writes `raw.breed_enrichment`;
  `dim_breeds` **LEFT JOIN**s it via `source()`. Order: ingest → dbt staging → enrich → dbt marts.
  dbt never makes a network call.
- **"Size" = weight, not height** — weight↔life −0.671 vs height↔life −0.503, and the two are
  0.860-coupled, so height adds little. Evidence in `mart_metric_correlation`.
- **Never a dual-axis chart.** Counts and life span render as two charts stacked on a shared
  x-axis. Two y-scales align arbitrarily and fabricate a relationship. See DECISIONS.md §0.
- **size_class boundaries are half-open `[min_kg, max_kg)`** and live ONLY in
  `seeds/size_class_bands.csv` (5/12/25/45). 31 breeds sit exactly on a boundary, so the closed side
  is load-bearing; `pd.cut` defaults to the opposite convention (use `right=False`).
