# DAY_REPORT — Dog Breed Explorer

What I discovered each day: what worked, what broke, and how I resolved it. The *narrative* of the
build. Distinct from its neighbours on purpose:

| file | answers |
|---|---|
| **DAY_REPORT.md** (this) | *what happened, and what I learned* — including paths I abandoned |
| DECISIONS.md | *what I chose, and why* — the settled position, per layer |
| SPEC.md | *what it must look like* — schema, parser, tests |
| ARCHITECTURE_PLAN.md | *what I'm building next* — milestones |

A decision that got reversed lives here **with its reasoning intact**; DECISIONS.md carries only
where it landed. Both matter: the debrief asks "which decisions were made, and why", and a reversal
I can explain is stronger evidence of thinking than a choice that was never tested.

---

## Day 1 — 2026-07-16 · M0, M0.5, M1 shipped

**Shipped:** M0 (profiling + SPEC), M0.5 (exploratory viz → questions + buckets frozen), M1
(idempotent ingestion). Six commits, history reads like the milestones.

### Exploration paid off — and the case's questions turned out to be real

Profiling gave structure (628 rows, 17 fields, null rates, format variants); it could not tell me
which questions had *interesting answers*. I decided to quickly explore the data with a dashboard. 
The throwaway Streamlit explorer did, and it confirmed the case study's suggested questions were 
worth answering rather than busywork:

- **Size vs life span is a genuine signal** — weight↔life span **−0.671**, and it survives
  aggregation: **13.3 yr (toy) → 10.6 yr (giant)**.
- **"Size" means weight, not height.** Height↔life is only −0.503, and height↔weight is 0.860 — so
  height adds almost nothing once weight is in. That's now a *tested mart* (`mart_metric_correlation`),
  not an assertion in a slide.
- **The buckets are data-informed, then frozen** — 5/12/25/45 kg, dragged live against the real
  distribution rather than guessed.

**The sharpest find:** **31 breeds (5%) sit exactly on a bucket boundary**, 23 of them on 25 kg. So
the interval convention is load-bearing, not pedantry — and `pd.cut` defaults to the *opposite*
(right-closed) convention, which is exactly how the explorer and a SQL prototype came to disagree by
2 breeds. That's why the boundaries live only in a seed and the join predicate is written literally
in SPEC (`>= min_kg AND < max_kg`).

**Deliberately left aside** (specified, not built — reasoning in DECISIONS.md §0/§3):

- **Temperament-pair lift by size band.** Interesting and can be found in exploration/, 
but it answers a question nobody asked, and the honest version needs leave-one-out lift + 
7 tests to not lie. Specified in §3 so the thinking
  survives; not built.
- **Male/female as separate columns.** A product feature the breed-level questions don't need.
- **Height as the size axis.** The correlation mart is the evidence for dropping it.

### The history story: designed, then reversed

I first designed raw to **accumulate** one 628-row partition per `run_date` — keep the history,
track long-term change. It survived exactly as long as it took to ask *where does this run?*

GitHub Actions gives every run a fresh VM: `dogs.duckdb` does not survive it. To keep the history I'd
have had to bolt persistence (MotherDuck, S3, an Actions cache) onto the pipeline **purely to protect
a history I couldn't name a use for** — on a near-static source, storing 628 identical rows a day to
record that nothing changed. Of course it becomes interesting to keep an history on the long term 
range to keep track of any change and see how evolve data distributions if new breeds are added. 

**Resolution: the pipeline is stateless. The API is the source of truth.** Every run re-fetches and
rebuilds; a fresh empty warehouse is a *supported starting point*, not a problem to engineer around.
Dropping the requirement removed the problem instead of solving it.

**Worth keeping in mind for a real product:** this is only right *because* the source is static and
nobody has asked "what did this breed look like last month?". The moment someone does, the answer is
durable storage (MotherDuck/S3) **plus an SCD-2 / dbt snapshot** that appends only when a breed
actually *changes* — not a full daily copy. That's the scale answer, and it's the first thing I'd add.

**What it cost, honestly:** with no prior partition, the completeness check has no last-good count to
compare against and falls back to a **fixed 628 baseline**. It still catches a truncated pull, but
the floor no longer tracks reality. A persistent warehouse is what makes that floor self-updating.

### The gap: the cron builds gold onto a VM that then evaporates

Statelessness settled *history*. It did **not** settle *handoff* — and that took a second pass to
see. If the scheduled run builds the gold layer and the VM is destroyed, **the dashboard has nothing
to read.** The architecture commits to decoupled write/read ("the dashboard NEVER triggers the
pipeline"), so "the dashboard rebuilds it" isn't available either.

**Resolution: CI proves the pipeline; the laptop serves it.** Producer and consumer both live on
durable hardware — mine. The pipeline runs locally end to end (`ingest.py` → `dbt build --target
prod` → `dogs.duckdb`), Streamlit reads that local file, and I demo it live. GitHub Actions' only
job is to answer *"does this code still work?"* — it ingests, builds, tests, goes green, and throws
its warehouse away, because serving was never its job.

The problem only bites if you insist the *cloud* run is the thing that serves the dashboard. The
brief says a POC is enough and the demo is live, so it doesn't have to be.

**The thing to verify, not assume:** run the full pipeline end to end against an empty warehouse and
confirm it works with no persistence — the CI path, exercised locally. Partially done at M1 (a fresh
`--db` file ingests 628 clean), but the dbt half doesn't exist yet, so this is an **M5 acceptance
check, not a closed item.**

**Say it out loud as a choice.** A scheduled run that discards its output looks like an oversight
unless framed: it's a **health check with a real API call attached** — it catches the API changing
shape, the key expiring, or a test starting to fail on a day nobody is looking. That's a genuine
freshness signal even though nothing is published. What I'd cross the line for: real users → the
cron publishes to durable storage and a hosted dashboard reads it. No model changes.

### The TDD loop was in the wrong milestone

Noticed while reading the plan: **M4 was "Tests + docs ← the TDD loop lives here"**, which meant
building M2+M3 and *then* writing the tests. That is not TDD — a contract written after the model is
a **description**. Worse, three docs disagreed: CLAUDE.md said "declare before/with the models",
RECAP_NOTES said "the loop is at M4, but write expectations early", the plan said M4.

**Resolution: the loop moved inside M2/M3** — one model *and its tests* is one unit of work
(declare tests → stub → red → fix → green → commit → next). Not really a scope change: it makes the
plan agree with what CLAUDE.md always said.

**M4 didn't disappear, it got honest.** Not everything can interleave: the three **distributional
guards** ("628 ±5%", `unknown` ≤1%, null rate ≤10%) describe the *finished* pipeline and can't be
asserted against a half-built DAG. So M4 = the guards + `dbt docs generate` + the lineage graph.

**Mechanical caveat I want to state accurately rather than overclaim:** dbt has no clean red-green —
testing a model that doesn't exist *errors* ("model not found") instead of failing an assertion. So
it's **contract-first, then iterate to green**, with a stub producing the first real red. TDD in
spirit, not mechanics. Claiming a textbook cycle would be hollow the second anyone poked it.

### Audit: gaps between the plan and SPEC/DECISIONS

Reading the plan against the specs surfaced deliverables **specified but owned by no milestone** —
the failure mode where a scored requirement quietly never gets built:

- **`profiles.yml` / dev+prod targets** — in the folder tree and the stack table, in *no* checklist.
  The brief explicitly scores "parameterize so it can run against both a dev and a prod target".
  → Now owned by **M2**, by necessity: `dbt build` resolves a profile before compiling anything, so
  the split exists from dbt's first run. M5 only *picks* `--target prod`.
- **The folder tree had drifted from its own checklists** — no `seeds/` directory at all (the seed is
  the ONLY home of the bucket boundaries), 2 marts missing, 7 of 10 custom tests missing. Fixed.
- **M5/M6 predated the day's decisions** — no `--target prod`, no `DBT_DUCKDB_PATH`, and M5 still
  said the cron "deploys". Fixed.
- **M0.5 said "delete the app"** while CLAUDE.md said "keep `exploration/` committed". Resolved:
  kept as evidence of process, still throwaway in status.

**Still unspecified — decide before/at M2, or I'm guessing:**
- **Materialization**: view or table? dbt-duckdb defaults to *view*; convention is staging=view,
  marts=table. Nothing says so.
- **Schema naming**: `main`? `main_staging` / `main_marts`? SPEC names objects, never schemas.
- **Where `enrich.py` sits in the DAG** (M7 bonus): it folds a column *into* `dim_breeds`, so it must
  run *between* staging and marts. Unspecified.

### Smaller things worth remembering

- **The API returns `id` as a string** (`"id":"1"`), not a number — so `CAST(id AS INTEGER)` is a
  staging *decision*, and raw keeping the payload verbatim is what preserves the evidence.
- **A 403 must fail fast, not retry.** Retrying a bad key 5 times just delays the real message.
  Retry only what a retry can fix: timeouts, 429, 5xx.
- **Completeness must be a tolerance, not equality.** `count == 628` cannot tell "the API broke and
  sent 300" from "a new breed was recognised, 629". Equality would fail the job for being *right*.
- **`git filter-branch` deletes the working-tree file too.** Purging the brief from history also
  removed it from disk (and `gc --prune=now` took the blob). Recovered by re-adding; the lesson is to
  copy the file out *first*. It is now gitignored by name — deliberately **not** a `*.pdf` glob,
  which would have swallowed the M6 dashboard PDF export.
- **Repo is private.** The docs quote the brief and the repo is a worked solution to Heyra's
  take-home; making it public would put the answer in reach of the next candidate. The brief's own
  wording — "submit repo link with **read access**" — points the same way.

### Where M1 landed

628 breeds → `raw.breeds` (verbatim JSON + `breed_id` + `run_date` + `loaded_at`). Verified rather
than assumed: two runs → 628 rows / 628 distinct ids / 1 partition; bad key, missing key and a
truncated 300-breed pull all exit 1 with last-good data intact; 629 breeds accepted; 3 runs across 2
days → 1256 rows in raw, latest snapshot 628.

**Next:** M2 — dbt scaffold + `profiles.yml` (dev/prod), `source()` → `stg_breeds` filtered to the
latest `run_date`, then the parser, tests-first, one model at a time.
