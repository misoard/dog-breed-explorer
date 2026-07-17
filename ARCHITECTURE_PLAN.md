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
│  │  │  └─ stg_breed_temperaments.sql  # split + lower + DISTINCT; excludes the tag sentinel
│  │  └─ marts/
│  │     ├─ _marts.yml           # tests + docs for marts
│  │     ├─ dim_breeds.sql       # clean + derived (size_class, midpoints, life_span_range)
│  │     ├─ breed_temperaments.sql       # bridge (breed_id, normalised tag)
│  │     ├─ mart_size_class_summary.sql  # grain: size_class — counts + mean life span
│  │     ├─ mart_size_vs_lifespan.sql    # grain: breed — scatter-ready (no height: no reader)
│  │     ├─ mart_metric_correlation.sql  # grain: (metric_a, metric_b) — 3 rows + n_breeds
│  │     ├─ mart_size_class_temperaments.sql  # grain: (size_class, tag) — count + % of class
│  │     └─ mart_data_coverage.sql       # one row — 627 total / 585 plotted / what's dropped
│  │                                     # (mart_size_scaling_fit CUT — an isometry exponent is
│  │                                     #  not a "fact about dog breeds"; see DECISIONS.md §0)
│  └─ tests/                     # custom SQL tests (return rows = fail)
│     ├─ assert_weight_min_le_max.sql        # error — invariants          [M2 ✓]
│     ├─ assert_height_min_le_max.sql        # error — same, for height    [M2 ✓]
│     ├─ assert_lifespan_min_le_max.sql      # error                       [M2 ✓]
│     ├─ assert_metric_parsed.sql            # error — a string we didn't understand
│     │                                      #   (supersedes assert_no_unknown_sentinel) [M2 ✓]
│     ├─ assert_metric_shape_known.sql       # warn  — the notation-change flag [M2 ✓]
│     ├─ assert_unit_ratio_plausible.sql     # error — units inferred; parses INDEPENDENTLY
│     │                                      #   of the model, on purpose  [M2 ✓]
│     ├─ assert_tag_lowercased.sql           # error — the bridge's genuine red (627) [M2 ✓]
│     ├─ assert_tag_unique_per_breed.sql     # error — the (breed,tag) grain [M2 ✓]
│     ├─ assert_source_tag_not_duplicated.sql # warn — source dup the DISTINCT absorbed [M2 ✓]
│     ├─ assert_tag_not_freetext.sql         # warn  — sentence-as-tag; expects 0 [M2 ✓]
│     ├─ assert_pct_of_class_sane.sql        # error — catches a bridge-join fan-out
│     ├─ assert_size_class_bands_cover.sql   # error — seed contiguous, no gaps/overlaps [M3]
│     ├─ assert_no_breed_unbanded.sql        # error — a real weight always finds a band [M3]
│     ├─ assert_weight_mid_plausible.sql     # error — magnitude; SPEC test 6 [M3]
│     ├─ assert_lifespan_plausible.sql       # error — magnitude; months-for-years [M3]
│     ├─ assert_unknown_bucket_small.sql     # warn  — distributional guards [M4]
│     ├─ assert_no_breed_lost.sql            # error — raw→gold exact reconciliation [M4]
│     │                                      #   (replaced assert_row_count_stable: a ±5% band
│     │                                      #    blind below 32 breeds, needing a constant that rots)
│     └─ assert_lifespan_null_rate_stable.sql # warn — [M4]
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
- [x] **DONE — Scaffold + the dev/prod targets** (`dbt_project.yml`, `profiles.yml`). Both connect
      (`dbt debug` green on each). **dev is the default** so a bare `dbt build` can't touch the
      serving copy; prod takes a deliberate `--target prod`. Materialization/schema set per LAYER in
      `dbt_project.yml` (staging=view→`main_staging`, marts=table→`main_marts`; dbt *concatenates*
      the custom schema, so `staging` not `main_staging`). **Run dbt from `dbt/`, via `.venv`.**
      *(Scored: "parameterize for dev and prod" — was in the folder tree but no milestone owned it.)*
- [x] **DONE — `flags.warn_error_options.error: [NodeNotFoundOrDisabled]`** in `dbt_project.yml`.
      dbt DROPS a test whose `ref()` doesn't resolve, with only a warning and exit 0 — a test that
      silently doesn't run is worse than no test. Scoped to that one event on purpose: blanket
      `--warn-error` would escalate our `severity: warn` tests too and destroy the warn/error split.
      Verified: typo'd ref → exit 2; warn-severity test → exit 0.
- [x] **DONE — `_sources.yml`** → raw.breeds, + 4 not_null tests + `source freshness` (warn @36h,
      off the `loaded_at` M1 writes — a daily cron means >36h is a missed run).
- [x] **DONE — `stg_breeds.sql`** + its contract, green. Parser = extract EVERY number, take
      min/max (shape-blind: `X-Y`, `Male:…;Female:…`, and `"12 years - 13 years"`/`"3-5kg"` all work
      with no branching). `'unknown'`→NULL **before** casting. Deduped the Caucasian Shepherd
      (`qualify row_number() over (partition by breed_name order by n_missing_fields, breed_id) = 1`
      — the rows TIE at 2 empty fields, so `breed_id` decides → id 70 survives).
      **Verified:** raw 628 → stg **627**; weight parsed **625**; life_span **587**; Leonberger
      `'male: 50-77; female: 41-64'` → **41.0/77.0** envelope. `PASS=17 WARN=0 ERROR=0`.
      **The loop ran for real:** naive first pass → `assert_metric_parsed` **FAIL 4** (Langqing +
      Mongrel, weight AND height = 'unknown'), `unique(breed_name)` **FAIL 1** (Caucasian ×2) →
      fixed → green. `unique(breed_id)` passed throughout: it *cannot* see that dupe (ids 70/269
      are distinct), which is why the name test exists.
      **It also caught SPEC being wrong:** `assert_unit_ratio_plausible` failed on its first run —
      "imperial:metric ≈ 2.54 (height)" is impossible; height's 2.54 is *metric/imperial* (cm > in),
      only weight's 2.205 runs imperial/metric. Test now measures each in its own direction.
      **Mutation-checked** the vacuous greens (inverted predicate → FAIL 625/587/625), so no test
      is green-but-unproven.
- [x] **DONE — `stg_breed_temperaments.sql`**: split comma list, **lowercase+trim** each tag (casing
      fix). Contract first: `unique(breed_id, temperament)` (custom — no dbt_utils), not_null both,
      `relationships` → stg_breeds, **`assert_tag_lowercased`** (error — the genuine red: **627 tag
      rows carry uppercase**, so a model without `lower()` fails loudly), `assert_tag_not_freetext`
      (warn).
      **Verified:** **3,538 rows**, 627 breeds → **626 with a tag** (Mongrel's sentinel excluded),
      66 raw tags → 46 folded → **45** after the sentinel. `intelligent` **536**, `loyal` **450**.
      All five tests green in `PASS=45` (post-audit suite).
      **REVERSED mid-milestone — this line said "No `DISTINCT`, let the test catch a future dup".**
      It now ships **`select distinct` + `assert_source_tag_not_duplicated` (warn)** that re-derives
      the split from `stg_breeds` independently. Reason: folding the casing can *create* a dup that
      isn't in the source (`"Loyal, loyal"`), so no-DISTINCT+error would fail the unattended cron
      over one breed, and the fix would *be* DISTINCT. Once DISTINCT guarantees the grain, a
      repeated source tag is drift, not broken data → **warn**, per our own severity rule.
      `assert_tag_unique_per_breed` stays **error** on the model's *output*, guarding the grain
      against anyone deleting that line. Path + reasoning in DAY_REPORT ("Reversed mid-milestone");
      landed position in DECISIONS §3.
- [x] Commit per meaningful step. This is the hardest piece — understand the parser line by line.
      → Two commits, each a working step: `80741db` (scaffold + dev/prod targets + `stg_breeds`
      green against its contract) and `5e70c90` (the bridge). The tests-first loop ran *inside*
      each, never as `wip:` commits — a model and its contract land together.

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
> describe the finished pipeline (a null RATE across all breeds) and can't be asserted against a half-built DAG.

**M3 — dbt marts/gold (Day 3 pm)** — build to SPEC.md · same interleaved test loop as M2
- [x] The `size_class_bands` **seed first** — `dim_breeds` joins it, so it exists before the model
      that needs it. Boundaries live ONLY there. Tests: `assert_size_class_bands_cover` (contiguous,
      no gaps/overlaps).
      → `seeds/size_class_bands.csv`, 5 rows (0/5/12/25/45/999); `assert_size_class_bands_cover` +
      `assert_no_breed_unbanded` green. Half-open `[min, max)` in the join (`>= min_kg AND < max_kg`).
- [x] `dim_breeds` (clean typed + derived: weight_mid_kg, size_class, life_span_range).
      Tests with it: unique+not_null(breed_id), accepted_values(size_class incl. 'unknown'),
      `assert_no_breed_unbanded`, weight_mid range check.
      → **627 rows** (post-dedupe). Derived: `weight_mid_kg`, `height_mid_cm`, `life_span_mid_years`,
      `life_span_range_years`, `size_class`. Range checks green: `assert_weight_mid_plausible`
      [0.5, 100] + `assert_lifespan_plausible` [4, 25] (the life-span half DECISIONS §3 asked for
      and SPEC never listed — built here). `size_class = 'unknown'` = 2 of 627 (0.3%).
- [x] `breed_temperaments` bridge (normalised tag). Tests with it: relationships → dim_breeds,
      **unique on (breed_id, temperament)** (load-bearing — a dup tag double-counts every
      aggregate), `assert_tag_not_freetext` (warn).
      → **3,538 rows**, 45 distinct tags, 626 breeds with a tag. `relationships` +
      `assert_tag_unique_per_breed` + `assert_tag_lowercased` green; `assert_tag_not_freetext` warn = 0.
- [x] The marts for the chosen questions (names canonical in SPEC.md): `mart_size_class_summary`
      (size_class grain), `mart_size_vs_lifespan` (breed grain — **no `height_mid_cm`**, its only
      readers were cut), `mart_metric_correlation` (**pairwise** population, carries `n_breeds`).
      → 6 / 627 / 3 rows respectively. `mart_size_vs_lifespan` has no `height_mid_cm` (verified) and
      **keeps null rows on purpose** — the 42 excluded are the dashboard's to drop, and
      `mart_data_coverage` states them. Correlations live: weight↔life **−0.670** (585),
      height↔life **−0.502** (585), height↔weight **0.860** (625).
- [x] `mart_size_class_temperaments` — grain (size_class, temperament); `GROUP BY` + `COUNT` over
      `ref('breed_temperaments')` × `ref('dim_breeds')`, plus **`pct_of_class`** (count / breeds in
      class) so big classes don't win on raw counts alone. Top-N stays in the dashboard, not gold.
      Tests with it: unique(size_class, temperament), `assert_pct_of_class_sane`
      (`breed_count <= breeds_in_class`, pct in (0,100]) — the inequality is what catches a
      fan-out in the bridge join.
      → **134 rows**. `assert_pct_of_class_sane` green (no fan-out). No lift, no baseline — top-N
      left to the dashboard, as specified.
- [x] `mart_data_coverage` — one row: what every chart drops (**627** total, **585** plotted, 42
      excluded; **626** with a temperament — Mongrel's tag is a sentinel).
      The dashboard prints it beside each chart. Life-span coverage is **uneven by class** (toy
      29/40 vs giant 58/58), which is a real bias in the headline chart — so `breeds_with_life_span`
      goes next to the bars too.
      → 1 row, verified live: total 627 · weight 625 · life span 587 · both 585 · temperament 626 ·
      plotted 585 · excluded 42. Per-class coverage confirmed toy **29/40** vs giant **58/58**
      (the plan said 59/59 — corrected against the warehouse).
- [x] **CUT: `mart_size_scaling_fit`** and the height-vs-weight curve. An isometry exponent is not a
      fact about a dog breed — the rule is *descriptive fact → gold, inferential cleverness →
      DECISIONS.md §0*. Don't rebuild it.
      → Verified absent: no table matching `%scaling%` in the warehouse, no model on disk. Stayed cut.
- [x] **`contract: {enforced: true}` on the models the DAG can't protect** — the 5 marts the
      dashboard reads (`mart_size_class_summary`, `mart_size_vs_lifespan`,
      `mart_size_class_temperaments`, `mart_metric_correlation`, `mart_data_coverage`) **+
      `breed_temperaments`** (the brief's "queryable" deliverable — its reader is a human with SQL,
      also outside the DAG; only 3 columns). **NOT `dim_breeds`** (~18 columns, read only via
      `ref()` → already DAG-protected) and NOT staging (**a constraint on a view is silently
      ignored — verified**). Rationale + the cost in DECISIONS.md §3.
      → Verified in `models/marts/_marts.yml`: **6 enforced** (`breed_temperaments` + the 5 marts),
      `dim_breeds` deliberately not. Exactly the intended split.
- [x] Business logic lives HERE, not in the dashboard.
      → Parsing in staging, midpoints/banding/aggregates in gold. The seed is the only home of the
      boundaries; `pct_of_class` is computed in the mart, not the dashboard. No dashboard exists yet
      (M6) — this is re-checked when one does.

**M4 — Pipeline-level guards + docs (Day 3 pm)**
> **The per-model TDD loop already ran in M2/M3** — the hard invariants were declared *with* their
> models and are green before M4 starts. What's left here is only what could NOT interleave: guards
> that describe the *finished* pipeline, and the docs that need the whole DAG to exist.
- [x] **Distributional guards (`severity: warn`) — TWO, not three.** `unknown` bucket ≤1% (live
      **2/627 = 0.32%**) and life-span null rate ≤10% (live **40/627 = 6.38%**). Rationale in
      DECISIONS.md §3: invariants error, anomalies warn — data can degrade without breaking any
      invariant, and legitimate drift shouldn't auto-fail the build. **Both are RATES**, which is
      why neither needs a constant: a rate stays meaningful when the source grows.
      Thresholds are **two `vars` in `dbt_project.yml`**, one home, documented in SPEC.
- [x] **`assert_no_breed_lost` (error) — replaces the third guard.** `dim_breeds` rows must EXACTLY
      equal the distinct breed *names* in raw's latest partition (628 raw → 627 names → 627 gold).
      **Why the ±5% row-count band was cut, after first "fixing" its constant from 628 → 627:**
      measured blind at losing 1/5/31 breeds (woke only at 32); `expected_breed_count` was
      hand-maintained, so an API growing to 667 would WARN *every run* forever = wallpaper, the
      exact failure removed from `assert_tag_not_freetext`; and losing a breed is a **bug**, not
      drift → error, not warn. Verified: dedupe by `breed_group` → `expected 627, actual 26,
      lost -601`, build stops. Test count **65 → 68**, then the M4 test audit cut 33
      unfireable tests → **35**. `PASS=45 WARN=0 ERROR=0`.
- [x] Verify the M2/M3 invariants are complete against SPEC's list (nothing silently skipped).
      → Automated instead of eyeballed: `audit.py`'s **PROMISES** section reconciles every test
      *named in any doc* against what's *built on disk*. Reports **18 ok**, two tombstones
      (`assert_no_unknown_sentinel` and `assert_row_count_stable`, both superseded), zero `todo`.
      Went further than the box asked: every surviving test was also checked for whether it *can
      fail* — 33 could not, and were cut (DECISIONS §3, "I audited the whole test suite").
      This is the check that would have caught `assert_lifespan_plausible` (promised in DECISIONS §3,
      unlisted in SPEC, unbuilt for two milestones).
- [x] `dbt docs generate` → capture the lineage graph for the debrief.
      → Ran green: `target/catalog.json` + `target/index.html` (1.8 MB, all 9 models + 35 tests).
      **Caveat:** `target/` is gitignored, so the graph is *regenerable on demand*
      (`dbt docs generate && dbt docs serve`), not committed. Consistent with DECISIONS §5 — the
      laptop serves the demo. A static screenshot for the debrief is M8 polish, not M4.

**M5 — CI/CD + schedule (Day 4 am)**
- [ ] GitHub Actions: on PR → install + `dbt build` + tests (visible status/badge). Runs
      **`--target prod`**; `DBT_DUCKDB_PATH` sets ingest.py's `--db` and the dbt target from ONE
      env var (they must agree on a path — SPEC "dbt targets").
- [ ] Cron @ 02:00 UTC: ingest → `dbt build --target prod` → tests → **discard the warehouse**.
      **CI proves the pipeline; it does not serve it** (DECISIONS.md §5) — the run is a health check
      with a real API call attached, which is what catches the API changing shape or the key
      expiring. Not a deployment; say so out loud rather than letting it look like an oversight.
- [ ] **`DOG_API_KEY` as an Actions secret** — the cron 403s without it. Nothing else is secret.
- [ ] **Make `warn` visible, or it isn't a signal.** dbt prints WARN to stdout and exits 0 — so CI
      goes green and the warning dies in a collapsed log. Parse `target/run_results.json` and emit
      GitHub `::warning::` annotations + a `$GITHUB_STEP_SUMMARY` table, so warns show on the PR and
      the run page **without failing the build** (which would defeat the point of warn severity).
      Same principle as "a red cron nobody sees is a cron that isn't running" (DECISIONS.md §5).
      Applies to all four warns: `assert_metric_shape_known`, `assert_tag_not_freetext`,
      `assert_source_tag_not_duplicated`, `assert_unknown_bucket_small`,
      `assert_lifespan_null_rate_stable`.

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

**M8 — Polish & submit (Day 5, ≥24h before Wed 11am → submit by Tue 11am)**
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
