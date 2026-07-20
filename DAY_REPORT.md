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

---

## Day 2 — 2026-07-17 · M2 (staging) + M3 (marts) + M4 (guards + docs) shipped · M5 (CI/CD) built, deliberately NOT closed

**Shipped:** the dbt scaffold with dev/prod targets, `stg_breeds` and `stg_breed_temperaments`, each
built test-first. **26 tests, all green**, every one of them either failed on real data or was
mutation-checked. Two of the day's findings were *my own documents being wrong* — caught by tests
written before the models they guard.

**Then M3 the same afternoon:** the seed, `dim_breeds`, the bridge, and the five marts — **9 models,
65 data tests, PASS=75 WARN=0 ERROR=0**. M3's own section is below (*"M3 — the milestone where the
docs drifted, not the code"*).

### The headline: a test found a spec error before the model existed

`assert_unit_ratio_plausible` failed on its **first run**, reporting `height = 0.394`.

SPEC said: *"the median **imperial:metric** ratio must stay near 2.205 (weight) / 2.54 (height)."*
That is arithmetically impossible. For **weight**, imperial is the bigger number (7 lb vs 3.2 kg), so
`imperial/metric = 2.205`. For **height**, *metric* is bigger (23 cm vs 9 in) — so the 2.54 is
`metric/imperial`, and imperial:metric is **1/2.54 = 0.394**. I had copied the pair "2.205 / 2.54"
out of my own exploration notes without noticing the exploration computed the two in **opposite
directions**.

**Why it matters beyond the fix:** this is the single best evidence for the contract-first order.
The test was written from the data; it caught the spec written from the same data; and it did so
*before `stg_breeds` existed*. No amount of me performing red-green adds to that — and the git
history proves it independently: SPEC declared these tests in a commit that predates the dbt project
entirely.

### The tests-as-contract claim is only as good as its artifact

The loop is **me**: write test → run `dbt build` → read failure → fix → re-run. Nothing enforces the
order, and I could skip the red and nobody could tell from the artifacts. Worth being honest about.

**What the red actually buys is not the fix — it's proof the test can detect.** A test green on its
first run might be green because the data is clean, or because I typo'd a column and it selects
nothing. So:
- **`stg_breeds`**: naive first pass → `assert_metric_parsed` **FAIL 4**, `unique(breed_name)`
  **FAIL 1** → fixed → green.
- **`stg_breed_temperaments`**: no `lower()` → `assert_tag_lowercased` **FAIL 627** → fixed → green.
- **The vacuous greens got mutation-checked** (invert the predicate, confirm it fires): weight/height/
  life-span min≤max → FAIL 625/587/625; the grain test → FAIL 3538. No test is green-but-unproven.

**`unique(breed_id)` passed throughout and is blind to the duplicate breed** — ids 70 and 269 are
perfectly distinct. Only `unique(breed_name)` sees it. That test wasn't in SPEC; it is now.

### The nastiest find: dbt silently drops tests

A test whose `ref()` doesn't resolve is **dropped with a warning and exit 0**. Typo a model name, or
rename one and miss a test file, and **the test stops existing while CI stays green**. A test that
silently doesn't run is worse than no test: you believe you're covered.

**Fix, in `dbt_project.yml` so it protects every run rather than just CI:**
```yaml
flags: {warn_error_options: {error: [NodeNotFoundOrDisabled]}}
```
**Scoped to that one event deliberately** — a blanket `--warn-error` would escalate our
`severity: warn` *tests* too and destroy the warn/error split. Verified both: typo'd ref → exit 2;
warn-severity test → exit 0. The line it draws: **a broken wire is an error; unexpected data is a
warning.** Corollary: watch `Found N data tests` (now **26**) — it's the cheap check that nothing
vanished.

### We broke my conda TensorFlow stack, and the venv was the answer all along

Installing dbt into miniconda **base** broke my TensorFlow. dbt-core needs `protobuf>=6`; TF needs
`<4` — **they cannot coexist**, so protobuf went 3.x → 6.33.6 and `import tensorflow` died. Same
install timestamp on both `dist-info` folders; no ambiguity about the cause.

Fixed: removed the 19 dbt packages from base, restored `protobuf==3.19.6`, verified TF imports. The
project now lives in **`.venv`**, which is exactly what CI does (`pip install -r requirements.txt`
into a clean env) — so "works locally" and "works in CI" became the same claim. We also turned up a
**pre-existing** conflict that predates this: base's streamlit needs `protobuf>=3.20`, TensorFlow
needs `<3.20`; no version satisfies both, so base runs one or the other.

**Lesson:** don't install into an environment we didn't create — use the project venv. (The sandbox
blocked a `~/.ssh/config` edit for the same reason, and was right to.)

### Reversed mid-milestone: absorb the problem, keep the signal

I built the bridge with **no `DISTINCT`** and an `error` test, reasoning "a duplicated tag is a grain
violation." Challenged with *"one breed shouldn't make everything fail"* — and that's correct:

- `DISTINCT` alone → correct numbers, **silence** when the source changes.
- No `DISTINCT` + error → loud, but **one odd breed fails the unattended daily cron**, and the fix
  would probably *be* to add `DISTINCT`.
- **`DISTINCT` + a `warn` test that re-derives the split from `stg_breeds`** ← chosen. Correct
  numbers, green build, visible signal.

**The severity followed the design, not my instinct.** "Grain violation → error" was only true
*while it could reach the mart*. Once `DISTINCT` guarantees the grain, a repeated source tag is the
source doing something new — **drift → warn**, which is what my own severity rule already said. I was
defending against a problem the fix had already solved.

The warn **re-derives the split independently** because **a test downstream of the fix cannot see
what the fix hid** — the same reason `assert_unit_ratio_plausible` refuses to reuse the model's
parser (*a test that shares the implementation's code agrees with it by construction*). Simulated it
end-to-end on a throwaway warehouse: inject `"Loyal, loyal"` → `WARN 1` naming the breed, `loyal`
once not twice, `exit 0`. **The cron survives, and you still find out.**

### The sentinel hiding as a temperament

`assert_tag_not_freetext` was going to `WARN 1` **forever** on breed 536's tag
`"Variable depending on ancestry and individual traits"`. Challenged with *"why does it exist then?"*
— fair: **a warning that never clears is wallpaper**, and it trains you to skim past the four warns
that matter.

The data gave the better answer. Breed 536 is **Mongrel** — a *mixed breed* — and its
`weight.metric` is the literal string `'unknown'`, which we already null. **Two spellings of "not
applicable" on the same row.** The sentence isn't free text leaking in, it's a **sentinel**. So it's
excluded by literal in staging, exactly like `'unknown'`: Mongrel now has no weight *and* no tags,
which is the truth. The test reads **0**, so any future sentence-tag is a real signal.

**And it immediately caught a bug in its own fix.** My first exclusion filter compared the *unfolded*
`tag` (`'Variable...'`) against a lowercase literal — a silent no-op. The only reason I noticed:
`WARN 1` stubbornly refused to clear. **Had I kept "accept the permanent warn", that 1 would have
been expected, I'd have skimmed past it, and shipped a filter that does nothing.** The no-permanent-
warns principle paid for itself within a minute of being adopted.

### Smaller things worth keeping

- **A constraint on a view is silently ignored** — `PASS`, no warning (verified). So dbt contracts
  mean something only on tables. Decided for M3: contract the **5 marts the dashboard reads** +
  `breed_temperaments` (the brief's "queryable" deliverable — its reader is a human with SQL, also
  outside the DAG), but **not `dim_breeds`** (18 columns, read only via `ref()` → already
  DAG-protected). **The rule: contract where dbt's knowledge ends**, not "contract gold".
- **A unique constraint rejects, it doesn't dedupe.** It fails the whole build — the same outcome as
  a test, with a worse message and no offending rows to inspect.
- The parser is **shape-blind and that's the point**: `"12 years - 13 years"` → 12/13 and `"3-5kg"`
  → 3/5 work with no branching. Its ceiling: a regex sees numbers, not meaning —
  `"3.5 kg (7.7 lb)"` → 3.5/7.7 and `"2 years 6 months"` → 2/6 are **silently wrong** and pass every
  invariant. Only `assert_metric_shape_known` (warn) catches that class.
- **The dedupe is visible in the tag counts**: id 70 (kept) has `alert`, id 269 (dropped) had
  `loyal` → `loyal` 451 → 450, `alert` unchanged. A staging decision propagating into gold exactly as
  predicted — and why the tiebreak must stay deterministic.
- `run dbt from dbt/` (it auto-finds `./profiles.yml`; from the repo root it falls back to `~/.dbt/`
  and fails with a misleading "not found"). **M5's workflow needs `working-directory: dbt`.**

### Still open

- **The whole warn design rests on M5 surfacing warnings.** Five tests are `severity: warn`; dbt
  prints them to stdout and exits 0, so **CI goes green and they die in a collapsed log**. Until CI
  parses `run_results.json` into `::warning::` annotations, "absorb the problem, keep the signal"
  quietly becomes "absorb the problem". This is the highest-value item in M5.
- Nothing tests the **latest-`run_date` filter** — with one partition locally, no test can see it.

---

## M3 — the milestone where the docs drifted, not the code

**Shipped:** `size_class_bands` (seed) → `dim_breeds` (627) → `breed_temperaments` (3,538) → the
five marts. **9 models, 65 data tests, PASS=75, zero warns, zero errors.** Six contracts enforced
(the 5 marts + the bridge), `dim_breeds` deliberately uncontracted.

The honest headline: **M3's code came out clean, and its *documentation* was the thing that was
broken.** Every model matched its contract. The M3 close-out found four defects — all four in the
docs, three of them in claims I'd written myself. The tests-first loop worked; the doc-keeping
didn't. Worth stating plainly because it's the opposite of the failure I expected.

### What I got wrong: I wrote down a fix I never made

`dim_breeds.sql` carries a comment explaining that `life_span_mid_years` belongs in gold, not
staging — a midpoint is a derived *opinion* (`(min+max)/2` is a RULE, not a fact the API stated), so
all three midpoints belong on the same side of the silver/gold line. Good reasoning. It ends:
*"SPEC's stg column list corrected."*

**It wasn't.** SPEC still listed `life_span_mid_years` as a `stg_breeds` column, and omitted it from
`dim_breeds` entirely. I had written the justification for a change and then narrated the follow-up
as though I'd done it. The code was right; the comment was a small lie about the world outside it.

Caught only by opening SPEC and looking — no test can see this, because **a comment claiming a doc
was updated is unfalsifiable from inside the warehouse**. The live pipeline settled it: the column
is in `dim_breeds`, absent from `stg_breeds`. SPEC now says so, with the reasoning moved into it.

Lesson I'd rather not have learned this way: *"and I updated X"* in a comment is a claim, and claims
in comments never get tested. Either make the edit in the same breath or don't write the sentence.

### The number sweep that missed the prose

Day 2's dedupe changed the gold-grain numbers, and commit `6c3c112` — *"recompute every gold-grain
number post-dedupe"* — was supposed to chase them all down. It fixed **SPEC's correlation table**
(−0.670 / −0.502 / 0.860, correct against the warehouse today). It missed **four citations in
prose**: SPEC ×2, CLAUDE.md ×1, and the ones in this file.

The pattern is worth naming: the sweep fixed the numbers where you *look them up* and missed the
numbers where you *argue with them*. A correlation in a table looks like data and gets checked; the
same correlation inside "weight↔life −0.671 vs height↔life −0.503, so size means weight" reads like
a sentence, and sentences don't look like they need recomputing. They're the ones that end up in the
debrief.

Corrected to live values (−0.670 / −0.502) in SPEC and CLAUDE.md. **Left alone in this file's Day 1
section on purpose** — −0.671 is what I believed pre-dedupe, and DECISIONS §1 already records the
correction. Rewriting yesterday's narrative to match today's numbers would be falsifying the path
this file exists to preserve.

**Why nothing caught it:** `scripts/audit.py` cross-checks every figure in `LIVE_NUMBERS` against the
docs that quote it — but `LIVE_NUMBERS` is **row counts only**. The correlations, the per-class
coverage, and the σ values are cited across five docs and watched by nothing. The audit reported
"ok" on all nine numbers while four wrong ones sat in the same files. A guard that watches nine
numbers and reports green is *actively misleading* about the ninety it doesn't watch. **Highest-value
M4 item: put the correlations and per-class coverage in `LIVE_NUMBERS`.**

> **Closed same day.** `audit.py` now watches **25 figures** (correlations, per-class counts, σ, the
> n's), gained a **PROMISES** section that reconciles every test *named in the docs* against what's
> *built on disk* — the exact gap `assert_lifespan_plausible` hid in for two milestones — and, best
> of the three, a **BLIND SPOTS** section that prints what it does *not* check and states outright
> that green means "the figures I watch agree", **not** "the docs are correct". A guard that
> advertises its own edges is the only kind whose green is worth anything.

### A test DECISIONS ordered and SPEC forgot to list

DECISIONS §3 asked for "range checks on weight **and life span**". SPEC's test list only ever
carried the weight half (test 6). So `assert_lifespan_plausible` was a **documented test that never
got built** — invisible, because nothing reconciles "tests DECISIONS asked for" against "tests SPEC
lists".

Found by asking what actually catches a life span in **months** — the realistic source change,
"120-180" instead of "10-15". The answer was *nothing*: min ≤ max holds, a number was produced, the
shape `"X-Y"` is one we know. Every existing test stays green while the whole chart is wrong by 12×.
Built it, [4, 25], green.

**And I was wrong about its sibling, too.** I'd claimed `assert_weight_mid_plausible` would catch
mixed-unit strings. It doesn't: `"3.5 kg (7.7 lb)"` → mid 5.6, comfortably inside [0.5, 100]. A
magnitude check only sees errors big enough to leave the range — which is *why*
`assert_metric_shape_known` has to exist separately, and why "the range check will catch it" is a
comfortable lie. Both tests now say so in their own headers, including what they miss. Bounds are
set from biology, **not fitted** to trap the hypothetical string — tightening them to catch one
example would be reverse-engineering the test to the answer.

### Smaller things

- **Plan said giant 59/59, warehouse says 58/58.** CLAUDE.md and SPEC both already said 58/58; the
  plan was the odd one out. Fixed against the warehouse. Toy **29/40** vs giant **58/58** stands —
  the uneven coverage that goes next to the headline bars is real.
- **`mart_size_vs_lifespan` keeps all 627 rows, nulls included** — deliberate, and the model says so.
  Filtering to 585 there would hide the 42 from the one mart whose job is per-breed honesty. The
  dashboard drops them; `mart_data_coverage` states them.
- **`Found N data tests` had to move.** SPEC froze it at "post-M2 it must read 26" — true, and dead
  the moment M3 added models. A watched number needs a *current* expected value or it stops being
  watched. Now: post-M3, **9 models / 65 data tests**.
- **The cut stayed cut.** `mart_size_scaling_fit` verified absent from disk *and* warehouse.

### The second close-out: I made the exact mistake I'd just finished diagnosing

The upgraded audit went green — 25 figures, all agreeing. The judgment pass then found **four more
wrong numbers it couldn't see**, and the first one was mine.

I had written, one screen earlier, that the Day-2 sweep *"fixed the numbers where you look them up
and missed the numbers where you argue with them."* Then I fixed `59/59 → 58/58` in the plan by
grepping for `59/59` — and **missed `giant has 59 of 59` in SPEC**, four lines from a table I'd
already checked, because my pattern matched the slashes and the prose spelled it "of". I diagnosed
the failure mode in one paragraph and re-committed it in the next. The lesson isn't "grep harder";
it's that **I searched for the shape I expected the error to have.** The fix that works is to grep
the *bare* number (`59`) and read every hit, which is what found it the second time.

Worse, the audit was **green while SPEC said 59 of 58**. It watches `size_class giant = 58` and
found "58" cited in SPEC — in the table on line 435. A wrong 59 elsewhere in the same file is
invisible to it. That's not a bug; it's the BLIND SPOTS section being *right*: *"whether a number is
quoted in the RIGHT PLACE"* is precisely what it says it can't check, and here that limitation had
teeth.

### The dedupe reached further than anyone swept

`DECISIONS.md`'s temperament-lift finding — the one that justified **cutting** the lift mart — still
carried pre-dedupe numbers: **59% of giants `calm + protective`, ×14.6, n=59**. Live: **60.3%
(35/58), ×14.9, n=58**.

The cause is verified, not assumed: the duplicate Caucasian Shepherd Dog (ids 70 & 269) is itself a
**giant** (61 kg), so dedupe took the giant band 59 → 58 and moved every giant statistic. That also
explains why my recomputation reproduced the **toy** figures *exactly* (60%, ×6.1) and the 4%
baseline — the bands the dupe never touched. Three of four figures matching is what makes the
reimplementation trustworthy enough to correct the fourth; had toy moved too, my SQL would have been
the suspect, not the docs.

Conclusions unchanged — leave-one-out still sharpens giant (**×6.5 → ×14.9**, was ×6.4 → ×14.6), the
vocabulary still contains no "aggressive" (verified: 0 rows), the claim is still about editorial copy
rather than behaviour. Exactly the pattern §1 recorded for the correlations: *the counts were all one
out, the conclusions were fine.* It just reached one document further than the sweep did.

**A bug in my own fix, caught before it shipped:** I first computed the lift as **×15.1** by rounding
the two percentages and *then* dividing (60.3/4.0). Recomputing from the raw integers gives
**14.93 → ×14.9**. Rounding before dividing is a real error, not a display choice, and I'd have
written it into DECISIONS as confidently as the number it replaced.

**Left deliberately un-"fixed":** §3's `pd.cut` anecdote says the SQL prototype got *"59 giants where
the pandas explorer said 57"*. That is **true history** — pre-dedupe, and the 59-vs-57 *gap* is the
entire finding about half-open bands. Editing it to 58 would falsify the story to satisfy a grep.
But sitting three paragraphs from "n=58 giants" it now reads as a contradiction, so it's marked
`(pre-dedupe)` with the reason. Correct history, current data, no apparent conflict.

### Still open

- **The audit can't see rounded citations.** It reports `mean life toy = 13.34` and `giant = 10.61`
  as *"not quoted in any doc (fine if it's not a claim)"* — but they **are** claims: CLAUDE.md,
  SPEC and DECISIONS all quote them as **13.3** and **10.6**, correctly rounded. So two real claims
  sit outside the guard, and a wrong 13.3 would draw no flag. The honest reading of "23 of 25 found"
  is *"23 matched literally"*, not *"2 are uncited"*. Worth a rounding-tolerant match, since the
  docs will always round and the warehouse never will.
- **Nothing reconciles DECISIONS' *prose findings* against the warehouse.** PROMISES now covers
  tests; the lift numbers above show the same class of drift in analysis prose, and those figures
  come from a **cut** analysis no model recomputes — so nothing but a human re-running ad-hoc SQL
  will ever catch them. The medium/large signatures (`×2.0`, `×2.4`) are **not re-verified** — that
  needs the full pair search, and the dupe moved their baseline by one row in ~570, which cannot
  move a one-decimal figure. Stated rather than silently assumed.
- ~~**`dogs.duckdb` (prod) contains only `raw`**~~ — **closed during M3's close-out.** It held only
  `raw` when I first looked and the full gold layer twenty minutes later: `dbt build --target prod`
  had been run. Prod now matches dev exactly (627 / 585 / 42), so M6's demo has a warehouse to read.
  **The two-target design is doing its job, verified rather than assumed:** `DBT_DUCKDB_PATH` is
  unset, so dev and prod resolved to their own files and the prod build did not disturb
  `dogs_dev.duckdb`. Both were built from the same 2026-07-16 ingest — the one partition raw holds.
- Both M2 items stand: **warns still die in a collapsed log until M5**, and nothing tests the
  latest-`run_date` filter.

---

## M4 — the guard that would have passed for the wrong reason

**Shipped:** the distributional guards, `dbt docs generate` — and then a **test audit that deleted a
third of the suite**. The count went **65 → 68 → 35**, and the last move is the one worth reading:
`PASS=45 WARN=0 ERROR=0`. Live: `unknown` **2/627 = 0.32%** (≤1), life-span nulls **40/627 = 6.38%**
(≤10), and `assert_no_breed_lost` reconciling **627 == 627** exactly.

M4 was supposed to be "add three guards and generate the docs". It turned into the milestone where
**two of the three guards I'd just written didn't survive contact with the question "can this
actually fail?"** — one was rebuilt from scratch as an exact reconciliation, and 33 tests across the
project were deleted outright.

**The finding, and it's the whole milestone:** `assert_row_count_stable` compares `dim_breeds`
against `expected_breed_count`. That var is **627**. The plan's own M4 checklist specified
**"row count 628 ±5%"**, and DECISIONS §3 described the guard as *"row count ~628"*.

627 sits **~1 breed inside** a 628-based tolerance ([597, 659]). So had the guard been built to the
spec as written, it would have gone **green forever while comparing against a number the pipeline
never produces** — passing for the wrong reason, and passing *convincingly*. The margin that hid it
is smaller than the rounding on the tolerance itself.

This is the fourth milestone in a row where **628 (raw) and 627 (gold) got mixed**, and it keeps
landing in the same place: any figure computed before the Caucasian Shepherd dedupe. The rule
CLAUDE.md already states — *628 is raw; `dim_breeds` is 627; never mix them* — is apparently not
something you can absorb once. It has to be checked every time a doc quotes a count.

**A guard that passes for the wrong reason is worse than no guard.** No guard is a known gap; a
green one is a *belief*. This is the same lesson as M2's "a dropped test is worse than no test",
arriving from the opposite direction: there, the test vanished and CI stayed green; here, the test
runs and stays green. Both end at a build that reports success while proving nothing.

### `vars`, not a seed — the same line drawn twice

The four thresholds now live in `dbt_project.yml` under `vars:`, one home, never inline in SQL —
same principle as the size bands in a seed: *a constant in two files will eventually disagree with
itself.* But **they are not a seed, deliberately**, and the distinction is worth stating:

- The size bands are **data** — a fact about dogs (a 45 kg dog is giant). They're joined to
  `dim_breeds`, and they're **tested** (`assert_size_class_bands_cover`).
- The thresholds are **config** — an expectation about a *run*. Nothing joins them; they're only
  compared against. A seed for them would be a one-row, four-column table no model reads.

`vars` also makes them overridable per invocation (`--vars '{expected_breed_count: 700}'`), which is
right for a threshold and wrong for a fact about dogs. The test: **would a reviewer argue with it?**
About 45 kg, yes — that's a claim about the world, so it's data and it gets tested. About "warn if
the count moves 5%", no — that's an operational preference, so it's config.

**Tolerance is not the observed value.** `max_lifespan_null_pct: 10` against an observed 6.38% is
headroom on purpose. The guard's job is to catch the rate *moving*, not to assert today's number —
set it to 6.4 and it fires on the first legitimate breed the API can't date, and a guard that cries
wolf gets muted, which is the same as deleting it.

### Auditing the tests *because* CI was next — 68 → 35

I stopped before M5 and read all 68 tests. The trigger was specific: **CI is about to turn "68 tests
passing" into a green badge on a PR, and a badge is a claim.** I didn't want to publish a number I
hadn't checked. So one question per test, and deliberately not "is this likely to fail?" but **"can
this fail, at all?"**

**33 could not.** Not weak tests — *incapable* ones. Four were `not_null` on source columns DuckDB's
own DDL already rejects nulls for (verified: the INSERT fails before dbt runs). ~27 were `not_null`
on things that cannot be null by construction: `count(*)`, `lower(tag)` behind a `where tag <> ''`,
a sum of CASEs. One was `unique` on a column the model produces with `group by`. One was
`relationships` from the silver bridge to `stg_breeds` — the bridge *selects from* `stg_breeds`, so
a child cannot carry a key its parent lacks.

**The subtlety I nearly got wrong:** the *gold* bridge has the same `relationships` test, and it
**stays**. There the two sides reach `stg_breeds` by different paths, so a filter on `dim_breeds`
genuinely would orphan rows. Same test, same name, opposite verdict — because "can it fire?" is a
question about the **DAG**, not about the test. I'd assumed the answer was a property of the test
and would have cut both.

**Why it's a decision, not a tidy-up.** A test that cannot fail is not weak coverage — it's **zero
coverage that reports as coverage**. It's `warn_error_options` from the far side: there a test
silently *stopped existing* while CI stayed green; here 33 tests *ran*, always passed, and CI stayed
green. Both give you a build that reports success while proving nothing — one by absence, one by
padding. And it rescues the one cheap signal I actually rely on: SPEC says *watch `Found N data
tests`*, which is only meaningful if every N could go red.

**What it cost, and I'd rather write it down than discover it later:** every cut is justified *by
construction* — "`count(*)` is never null", "the bridge selects from its parent". That reasoning is
true today and **is not itself tested**. Rewrite the bridge to select from `raw` instead of
`ref('stg_breeds')` and the cut `relationships` test is precisely the one that would have caught it;
its absence is silent. So each cut carries its reasoning **at the column in the YAML**, not in a
commit message — the next person to touch that model reads why the test isn't there before removing
the premise it rested on.

**The honest framing:** "68 tests" reads as rigour until someone notices a third can't fail, and in
a case graded on craft, padding reads worse than a lean suite. **35 that can each be made to fail
beats 68 that can't.**

### The check I automated instead of doing

*"Verify the M2/M3 invariants are complete against SPEC's list (nothing silently skipped)"* was a
box asking me to eyeball two lists and tick. That's exactly the check that already failed once —
`assert_lifespan_plausible` sat promised-in-DECISIONS and unlisted-in-SPEC for two milestones
because a human compared the lists and saw what they expected.

It's now `audit.py`'s **PROMISES** section: every test named in any doc, reconciled against what's
on disk. **18 ok, one tombstone, zero todo.** A box that says "verify X" is a box that will be
ticked from memory eventually; a script that prints X is one that can't be.

### Smaller things

- **`dbt docs generate` ran green** — `catalog.json` + a 1.8 MB `index.html`, all 9 models and 68
  tests, verified by reading the catalog rather than trusting the timestamp. But **`target/` is
  gitignored**, so the lineage graph is regenerable-on-demand (`dbt docs generate && dbt docs
  serve`), *not* committed. That's consistent with §5 — the laptop serves the demo — but it means
  "capture the lineage graph for the debrief" is satisfied by a live demo, not an artifact in the
  repo. If the debrief needs a static image, that's M8 polish. Flagged rather than silently ticked.
- **The audit was green while the plan said 628**, again. It watches `dim_breeds rows = 627` and
  found "627" cited in ARCHITECTURE_PLAN — in a *different sentence*. Third milestone, third time
  BLIND SPOTS' *"whether a number is quoted in the RIGHT PLACE"* had teeth. The tool is honest about
  this; I just have to keep reading the docs it can't.
- **Ticking M2's boxes late found a comment arguing against its own file.** Going back to tick M2 —
  shipped two commits ago — `stg_breed_temperaments.sql` still ended with *"NO `distinct` —
  deliberate… a future 'Loyal, loyal' must reach the test"*, **thirty lines below the `select
  distinct` it forbids**, and directly contradicting the header block that explains why DISTINCT is
  there. The reversal ("absorb the problem, keep the signal") updated the code, the tests, SPEC,
  DECISIONS and this file — and left its own trailer standing. The plan's M2 checklist still
  specified "No `DISTINCT`" too, so the box was **unticked because it was untickable**: the item as
  written described a model we deliberately don't have. Both corrected; the box now records the
  reversal instead of the abandoned design.
  This is the **second** comment found asserting something untrue (after M3's *"SPEC's stg column
  list corrected"*, which hadn't been). Same shape both times: the reasoning gets written, the
  decision gets reversed, and the *prose* is the last thing anyone updates — because no test reads
  it. A stale comment is worse than no comment: it's a confident argument for the wrong design,
  sitting inside the right one, and the next reader can't tell which is current.
- **Two more numbers, same dedupe:** the bridge model's header said **~3,539 rows** (live **3,538**
  — the sentinel exclusion) and DECISIONS §3 said `intelligent` **535** (live **536**; SPEC and
  DECISIONS §4 both already said 536). Fixed. `dbt build` re-run after the comment edits:
  **PASS=78**, bridge still 3,538 — confirming comment-only, as claimed.

### Still open

- **The warns are still inert.** Both surviving guards are `severity: warn`, so dbt prints them and
  exits 0 — CI goes green and they die in a collapsed log. Every design choice above ("invariants
  error, anomalies warn") is a bet on **M5** parsing `run_results.json` into `::warning::`
  annotations. Until then this milestone's output is decoration, and
  `assert_unknown_bucket_small`'s own header says so. Highest-value item in M5, unchanged.
- **The two surviving guards have never fired.** `assert_no_breed_lost` earned its place by mutation
  (dedupe by `breed_group` → `expected 627, actual 26, lost -601`, build stops) — that one is proven
  *behaviour*. The other two are not: I haven't forced a run where `unknown` balloons or the null
  rate spikes. Their thresholds are verified as *arithmetic*, not as behaviour, and the audit that
  cut 33 tests for being unfireable pointedly did **not** prove these two can fire. They can — the
  predicate is a live comparison against a real column — but "can in principle" is exactly the
  standard I just rejected for everything else. Worth doing to my own two.
- **The 33 cuts rest on untested reasoning.** Each is sound *by construction* and annotated at the
  column, but nothing enforces the premise. Change the bridge to select from `raw` and the cut
  `relationships` test is the one you'd want back — silently.
- Both M2 items stand: nothing tests the latest-`run_date` filter, and the audit still can't see
  rounded citations (`13.34` vs the docs' `13.3`).

**Next:** M5 — CI on PR + the 02:00 UTC cron, `DOG_API_KEY` as an Actions secret, `working-directory:
dbt` on every dbt step, and the one that makes M4 mean anything: **parse `run_results.json` into
GitHub annotations so a warn is visible without failing the build.**

---

## M5 — the milestone that cannot be verified before it ships

### Claude proposed the DRY answer; the better one was to move the duplication

I asked how to express CI-on-PR and the 02:00 cron, since they run the same four steps. Claude
recommended a reusable `workflow_call` workflow called by both — the textbook don't-repeat-yourself
answer, and it framed the alternative as costing "~35 duplicated lines".

That framing was the bug. **The 35 lines only exist if the pipeline lives in YAML.** Put it in
`scripts/run_pipeline.sh` and each workflow collapses to checkout + setup-python + pip install +
one line, and what's "duplicated" is eight lines of boilerplate. `workflow_call` would then be
adding a concept a reviewer must learn — and breaking the badge, since each badge points at a
*caller* rather than the job — in order to deduplicate `actions/checkout`. Tail, dog.

**The rule I'd state in the debrief: deduplicate in the script, not in the CI system.** The payoff
isn't tidiness — it's that the pipeline is now runnable *identically* on my laptop and in Actions
(same script, same seam, same path resolution), and none of it is locked to GitHub. If this moved to
GitLab or Dagster tomorrow, the pipeline definition moves unchanged and only the trigger is
rewritten. Two workflows also stay two *status checks*, which matters at 02:00: a red cron and a
broken PR fail for different reasons and want different reactions, and merging them into one file
with two triggers would make me open the log to find out which I'm looking at.

### The warn design was theatre for four days. I made it fire.

M4 shipped five `severity: warn` tests and DAY_REPORT's own "Still open" said the warns were
**inert**: dbt prints WARN and exits **0**, so CI goes green and the signal dies in a collapsed log.

Rather than assert the fix, I reproduced the failure. Forcing two guards —
`dbt test --vars '{max_unknown_size_class_pct: 0, max_lifespan_null_pct: 1}'` — gives **`WARN=2` and
exit code 0**. Green build, two fired guards, nothing to see. That is the whole problem, on demand,
in one command.

Then the same `run_results.json` through `scripts/annotate_warns.py`: two `::warning::` annotations,
a summary table, **exit 0**. Exit 0 is the design, not an oversight — failing there would
re-implement `--warn-error` and destroy the split M4 spent a milestone building. A warn is for a
human to judge; a robot blocking on it is the thing I explicitly refused.

**This also closed an M4 open item I'd written down and would otherwise have carried to submission.**
M4's "Still open" admitted the two surviving guards had **never fired** — their thresholds were
verified as arithmetic, not as behaviour, and I noted that the same audit which cut 33 tests for
being unfireable had pointedly not proven these two *could* fire. They both fired today. The bar I
set for other people's tests now applies to my own.

### Why the annotator is a script and not four lines of `jq`

The tempting version is inline `jq` in the YAML: no new file, no Python. It's disqualified by its
failure mode. **A bug in inline jq produces no annotation — which is indistinguishable from no
warnings.** The mechanism whose entire job is making problems visible would fail *invisibly*, and
only inside Actions, where I can't run it. That is the same shape as a vacuous green and an
unfireable test, arriving one level up: a guard that can silently stop guarding.

So it's a script I can run against a real or synthetic `run_results.json` — and I did, including the
cases the live suite can't produce on demand: a hash-suffixed generic-test id (renders readably), a
warn alongside an outright failure (still surfaces — the step is `if: always()`, because a red build
is exactly when you want to know what *else* fired), and an embedded newline in dbt's message.

Its own failure is loud by construction: a missing or corrupt `run_results.json` emits `::error::`
and **exits 1**. "I found no warnings" and "I could not look" must never render identically —
that would rebuild the exact silence the script exists to break.

### The Day 1 acceptance check, finally closed — and it had been an argument, not a result

§1 has claimed since Day 1 that "a fresh, empty warehouse is a supported starting point". M1 only
ever tested the **ingestion** half against an empty file; "the rest rebuilds fine" was reasoning.
Against a warehouse that did not exist, `DBT_DUCKDB_PATH=/tmp/fresh.duckdb ./scripts/run_pipeline.sh`
reproduced **every** published number from nothing: 628 raw in 1 partition → 627 `dim_breeds` →
3,538 bridge rows → coverage 627/585/42, toy 29/40 vs giant 58/58, `PASS=45 WARN=0 ERROR=0`.

Ten minutes, and it retires the load-bearing assumption under both §1 (statelessness) and §5 (CI
proves the pipeline). The alternative was finding out at 02:00 on the first cron.

### The close-out caught a box that could never be met

M5's first item said "visible status/**badge**". There is no `README.md` in this repo — the badge had
nowhere to live. It's an M6/M8 deliverable that the M5 checklist had quietly annexed on Day 1, and
nobody notices a half-true box until something forces a line-by-line read. Amended: status check
here, badge with the README. (Same close-out also found the plan promising "all four warns" above a
list of five. A miscount, not a design change.)

### What I got wrong

- **I let Claude frame the CI question as a DRY problem and nearly took the DRY answer.** The right
  move wasn't picking between the options offered — it was rejecting the premise that the pipeline
  belongs in YAML at all. Worth remembering that a well-argued recommendation can still be answering
  the wrong question.
- **I'd have ticked M5 on "the files exist".** Every instinct at close-out was to call written YAML
  a finished milestone. It's the same unproven green I've spent two days eliminating — just wearing
  a different hat, because YAML *feels* like configuration rather than code.

### The chicken-and-egg, stated rather than dissolved

**M5 cannot be verified before it ships.** A workflow file has no local test: the trigger, the
secret, and GitHub's rendering of `::warning::` are only exercised by a real run, and a real run
needs a PR — the very ship the milestone gate is supposed to precede. So the code ships with three
of four boxes **open**, and they close after the first Actions run.

*(Sharpened at ship time: I'd written "needs a push", and then protected `main` — so `main` now takes
no pushes at all and the only route to a run is branch → PR → CI → merge. The ceremony makes the
chicken-and-egg **worse**, and better: worse because M5 now can't close without a merged PR; better
because `ci.yml`'s `on: pull_request` half finally has a PR to fire against. Before the ruleset I'd
have been committing to `main` and shipping a trigger that had literally never run.)*

I chose that over the tidy alternative (tick on "the file parses, and the pipeline it calls is
proven"). Both readings are defensible; one of them is the unproven green again. The gate correctly
reports **NOT ready**, I'm overriding it knowingly, and the override is written down here rather
than hidden by a box I talked myself into ticking.

### Still open

- **The workflows have never run.** `run_pipeline.sh` is proven (empty warehouse, green,
  every number) and `annotate_warns.py` is proven (two real warns through it). The **triggers** are
  not: `pull_request`/`schedule` firing, the secret resolving, `${{ github.workspace }}` landing
  where I think, and `::warning::` actually rendering on a PR. **The first PR is the real test.**
- **`DOG_API_KEY` as a secret is ticked on my word alone** — nothing in the repo can check it, and
  neither the audit nor the agent can see repo settings. If the first run 403s, that box is the
  first suspect.
- **A fork PR will 403.** No fixture, no persisted warehouse (§1), so `raw.breeds` doesn't exist
  until `ingest.py` creates it — which means every PR spends a real API call and CI can go red
  because *the API* is down rather than because the code is wrong. Right trade at one contributor;
  with outside contributors I'd record a fixture for the PR path and keep the live call on the cron.
- **Nothing alerts on a red cron.** It's visible only on the Actions page — a red cron nobody sees
  is a cron that isn't running (§5). Alerting stays a "with more time" item, now with a workflow
  that can actually go red to justify it.
- **CI installs streamlit + pandas it never uses** (~30s a run). Splitting requirements is real
  scope for a small win; noted, not done.
- Carried from M4: the 33 cuts still rest on untested reasoning; nothing tests the
  latest-`run_date` filter; the audit still can't see rounded citations (`13.34` vs `13.3`).

**Next:** open the PR, watch the first CI run, close M5's three open boxes on the evidence — then M6
(Streamlit reading the local prod build) + the README, where the badge lands.

## M6 — the dashboard, and the two rules that kept catching the first drafts

The dashboard was where the spec-first habit paid off, and where we made the most reversals — most of
them caught by the two rules I'd enforced all week (**thin**, **honest**) turned back on our own first
attempts. I wrote `DASHBOARD.md` in full — panels, the single mart each reads, chart types, the honesty
shown beside each — before a line of Streamlit, and surfaced the genuine open choices (layout,
interactivity, palette) as questions instead of assuming them. It paid off: every reversal below
happened at the *design* layer, in the spec or the live app, never as a rebuild of finished code.

### The reversals, and what forced each
- **Radar → heatmap.** We nearly shipped a temperament chart whose headline finding — "the shape
  rotates as size increases" — I could *move or erase just by reordering the spokes*. Same sin as the
  dual axis, one layer over. A heatmap says the same thing but can't be tuned by ordering.
- **Sequential blue scatter → distinct colours.** The spec I'd written said "size is ordinal, so one
  blue ramp, never categorical," and we built it that way. In the dense cloud five blue shades were
  indistinguishable — my own rule cost real legibility. Going to fix it, the dataviz validator
  *rejected* every cohesive "stay in blue" palette we tried (a cohesive-cool set can't clear
  colour-blind separation — proven, not argued), which is what turned distinct hues from a preference
  into a requirement: on a scatter where x already carries the size order, colour is free to carry
  identity. We overrode the spec and wrote the override down.
- **Hardcoded numbers → read from gold.** I caught Claude baking `−0.67` and `13.3→10.6` into the
  captions as literals — the exact thin-layer sin I'd been policing in the pipeline, resurfacing in the
  read layer: a daily refresh would move the coefficient and the prose would lie while the chart
  updated. Now every number on the page reads from the marts at render time.
- **`CLASS_ORDER` from the seed.** The size-band *boundaries* were single-sourced from the seed; the
  label *order* wasn't. We first parked that as a "with more time" note, then decided that was a
  cop-out and pulled the order straight from the seed the app already loads.

### What we got wrong (and caught)
- **Scope creep.** Asked to make the scatter colours distinguishable, Claude *also* recoloured the
  distribution histogram — which I was happy with. Reverted. A scoped request is a scoped request.
- **The longest-lived table shipped midpoint-only first** — five identical `15.0` rows with no visible
  reason they were "the top." The fix was a small *additive* gold column (project `life_span_min/max`
  from `dim_breeds` into the mart), not app-side cleverness — a new need became tested gold. It also
  forced the honest ordering call: the five are identical on every life-span number (all `12–18`), so
  there's no ranking to make — list them alphabetically and say so.
- **A stale count nearly shipped.** The README said "35 tests" (the M4 figure); M6's dashboard seed had
  already taken it to **39** (`PASS` 45→50: 9 models + 2 seeds + 39 tests). The milestone audit caught
  it — without that check I'd have shipped a README that undercounted its own suite.

### Still open
- **M7 (LLM bonus)** and **M8 (polish/submit)** — not started.
- **Observability** (run-metadata → an audit table, Elementary) is in DECISIONS "what I'd build next,"
  not built — and it shares the durable-storage prerequisite I deferred at M5, so it'd land alongside a
  hosted dashboard.
- The dashboard is **local-only** by design (not in CI). The README screenshots are chart *exports*; we
  tried a full-page Playwright capture and reverted it as not worth a 93 MB browser for a POC.

## M9 (Part A) — observability, the local half: one package, and the discipline of stopping there

The brief offers an observability bonus ("extended tests wired to an alert channel"), and it also says
in as many words that it is **not scoring production polish** — a laptop DuckDB pipeline is a complete
answer. Those two sentences set the whole shape of this milestone: do the high-ROI local half, prove
it, write down exactly how the cloud half follows, and **stop before touching prod's storage** so a
half-finished integration never reads worse than a crisp "here's how I'd do it." Debrief prep outranks
this; a stretch that eats it is a net loss.

### The one idea, and why it's one package and not a hand-rolled audit table
The DECISIONS "what I'd build next" already argued the shape: GitHub gives compute + scheduling for
free, so **the only deferred piece is durable storage**, and observability splits cleanly along it.
*Point-in-time* health — did this run's tests pass, how long did each take — is stateless-doable, and
we already had `annotate_warns.py` doing part of it. *Trends* — is the null rate creeping over a week —
need yesterday, which the stateless pipeline (§1) and the warehouse-discarding CI (§5) deliberately
don't keep. Part A builds the point-in-time half properly. I'd planned to hand-roll an
`audit.pipeline_runs` table; Elementary does exactly that and ships a report, so reaching for it is the
same call as reaching for dbt_utils in production — **infra, not test logic.** That distinction is the
whole defence of adding the project's *first* external dbt package after four milestones of writing
every test by hand: it captures the results of the 39 assertions I already own, it doesn't add a 40th I
can't explain.

### The guard I was most worried about held
The failure mode a package can quietly introduce is a **dropped test** — the same "looks like coverage,
isn't" sin the whole suite is built to avoid. So the acceptance check wasn't "did it install," it was
"did the registered data-test count survive." It did: `Found 39 models, 39 data tests` — the model
count jumped 9 → 39 (our 9 + Elementary's 30 in their own `main_elementary` schema), and **the data
tests stayed exactly 39**. Build `PASS=82 WARN=0 ERROR=0`, `audit.py` green. Better than counting:
Elementary's own tables show it captured all 39 results **with the warn/error severity preserved**
(`assert_lifespan_null_rate_stable`, `assert_metric_shape_known` land as `warn`, the rest `ERROR`) —
the exact split this project fought for, now queryable instead of scrolling a log.

### What I got wrong (and caught)
- **I misdiagnosed a commit error as a thread race — and my "fix" disproved itself.** The check that
  earned its keep: a cold-warehouse prod run (the CI condition) threw **11 `DuckDB adapter: Commit
  failed ... Tried to commit transaction on connection X, but it does not have one open!`** tracebacks.
  My first read was the textbook one — DuckDB is single-writer, dbt runs `threads: 4`, Elementary's ~30
  new models raised the concurrency, so I set `threads: 1`. Re-ran: **still exactly 11.** Threading had
  nothing to do with it. I reverted the threads change rather than ship a fix that fixed nothing (a
  misattributed config is worse than none). The real cause is an **upstream** dbt-duckdb ⨯ Elementary
  transaction-handling bug (Elementary #1712, dbt-core #11966): Elementary's on-run-end artifact upload
  calls `commit` outside dbt's transaction; the write itself succeeds (DuckDB auto-commits), so the node
  still lands `OK`. **It is log noise, not a failure**, and I proved that where it counts: exit 0,
  `Done. PASS=82 WARN=0 ERROR=0`, and `run_results.json` is **43 success + 39 pass, zero error/warn** —
  so dbt's authoritative accounting is clean and the CI PR annotations (which read `run_results.json`,
  not stdout) are untouched. Cold build = 11 lines, warm = 3 (proportional to how many incremental
  models actually write). I chose to **document it, not silence it**: raising the adapter's log level
  would bury genuine errors too — the exact "signal killed to look tidy" trade this project refuses.
  The honest cost of adding the package on DuckDB, written down.
- **`--project-dir` pointed edr at the wrong dbt project.** First run of the report script died with
  "No dbt_project.yml found at `<repo>/dbt_project.yml`" — I'd passed our project dir, but `edr` renders
  from its *own* bundled dbt project and only needs `--profiles-dir` to reach the warehouse. Removed the
  flag; it rendered. A reminder that the CLI is a *reader* of the store, not a runner of our models.
- **The edr profile schema is `main_elementary`, not `main`.** Elementary's `+schema: elementary`
  concatenates onto the `main` target the same way our staging/marts schemas do — so the tables live in
  `main_elementary`, and the `elementary` connection profile the CLI needs has to name that schema
  exactly. Same concatenation gotcha documented for our own layers, one more place.

### The two "don't over-engineer" calls
- **A separate `.venv-edr`, not the pipeline venv.** `edr` is only a reader of the duckdb file; it
  shares none of the pipeline's runtime. Given this project has *already* been bitten by a
  protobuf/TensorFlow version clash, letting the report tool pin versions inside the pipeline `.venv`
  was a risk with no upside. It gets its own venv, bootstrapped by the script on first run — so the
  whole thing still runs from the repo, just not from the same interpreter.
- **The 5.6 MB report is regenerable, not committed.** Same rule as the dbt docs lineage graph (§5):
  the permanent, reviewable change is the *wiring* — `packages.yml`, the pinned `package-lock.yml`, the
  `elementary:` block — which is ~20 lines and diffs cleanly. The generated HTML is a `.gitignore` line
  and a `scripts/observability_report.sh` away, exactly like the demo the laptop serves.

### Still open (Part B — a review checkpoint, not a thing to barrel through)
Part B changes prod's storage target (MotherDuck: `path: "md:dogs"`) and adds a credential
(`MOTHERDUCK_TOKEN`) — that's the durable-storage unlock the whole "what I'd build next" hinges on, and
it turns this same local report into a day-over-day trend for free. Deliberately **not started**: it's
a real change to the served stack and a new secret, so it waits for review, per how we work.

## M9 (Part B) — durable storage: the one change that unlocks the rest, done in three connection strings

Reviewed Part A, then chose to keep going. Part B is the move DECISIONS "what I'd build next" is
organised around: **the only genuinely deferred piece of the whole architecture is persistence
between runs.** GitHub already gives compute + scheduling for free; add a durable store and history,
observability trends, and hosted serving all fall out of it. This is that store.

### The design call: I did NOT do what the brief literally said
The brief says "point the **prod** target at MotherDuck." I didn't — I pointed only the **cron** at
it, via the env-var seam that already existed. Reasoning: converting the prod target would make
*every* prod build cloud, including every CI PR run — so each PR would need the token and would
**overwrite the shared served gold** just to prove a code change. That destroys §5's cleanest
property ("CI proves, something else serves"). Instead: `ci.yml` PR builds stay local + throwaway
(prove), and only `scheduled.yml` sets `DBT_DUCKDB_PATH=md:dogs` (serve). The result is *sharper*
than the brief's version — proving and serving stay different jobs on different triggers, and a PR
can never clobber last night's data. This is the kind of place the "it's my architecture to defend"
framing earns out: the brief is a starting point, not a spec to follow off a cliff.

### Why it was nearly free — and the one place it wasn't
The `DBT_DUCKDB_PATH` seam built back in M5 (one env var, shared by ingest.py and dbt) already
accepts an `md:` path — dbt-duckdb routes it to MotherDuck natively. So the pipeline change was
**three lines** in `run_pipeline.sh`, not a rewrite: source `.env` (dbt reads the token from the
shell, not just ingest.py); *don't* absolutise a connection string into `$REPO_ROOT/md:dogs`; and the
one thing that genuinely surprised me —

- **MotherDuck doesn't auto-create the database on attach.** First cloud run died at
  `duckdb.connect("md:dogs")` with `no database named 'dogs' found`. `md:dogs` *attaches* an existing
  database; it doesn't make one. Fix: a one-time `CREATE DATABASE IF NOT EXISTS "dogs"` against bare
  `md:` before either writer connects — placed in `run_pipeline.sh`, the single choke point both
  ingest.py and dbt pass through, so neither program grows its own md: special-case. Idempotent, so
  it's free on every subsequent night.

### Proven live from the laptop, not asserted
The whole cloud path, end to end: `DBT_DUCKDB_PATH=md:dogs ./scripts/run_pipeline.sh` → 628 breeds
ingested to MotherDuck → `Found 39 models, 39 data tests` → `PASS=82 WARN=0 ERROR=0` **in the cloud**.
Then a plain `duckdb.connect('md:dogs')` reader (which is all the dashboard is) returned the published
numbers *exactly* — `dim_breeds` 627, bridge 3538, coverage 585·42, giant 58, corr −0.67. The
dashboard's new `DOGS_DB` seam resolved to `md:dogs` and pulled 585/42 from the cloud; the Elementary
report regenerated against `dogs.main_elementary`. Zero model SQL changed — the brief's "materialization
is a deployment decision" made concrete: the same models, a different connection string, and the POC
became a served stack. (The benign Elementary commit-noise from Part A rides along on the cloud build
too — same story: green, `run_results` clean.)

### An unplanned bonus: §1's deferred history is now partly real
Statelessness (§1) deferred *change-history* because holding many daily partitions meant bolting on
persistence. The cron writing to MotherDuck means `raw.breeds` now **accumulates a partition per
night in the cloud** — the durable raw history §1 said it would take durable storage to justify. It's
not SCD-2 yet (that's still the snapshot work), but "what did the API return last Tuesday" is now
answerable where it wasn't. Elementary's tables accumulate the same way — that's the trend view.

### Still open — the part that's genuinely mine to click, not the agent's to claim
Two steps live outside the repo, so they stay unticked on the same honesty rule as M5's triggers:
1. Add `MOTHERDUCK_TOKEN` as a **GitHub Actions secret** (like `DOG_API_KEY`) — until then the next
   *scheduled* run will fail (PR CI is unaffected — it never touches the cloud).
2. Deploy `app.py` on **Streamlit Community Cloud** with `MOTHERDUCK_TOKEN` + `DOGS_DB=md:dogs` as
   platform secrets → the public link. The *code* is done and the cloud read is verified; a hosted URL
   is only proven by a real deployment, which is mine to do.

## M9 (Part C) — the dead man's switch: a run that never happened

A live incident drove this one: one morning the scheduled cron simply wasn't in the Actions list. Not
red, not cancelled — *absent*. That exposed a real hole in "how do I know the last run passed?": the
Actions page can only show runs that **started**, so a run GitHub silently **drops** (best-effort cron
does this under load) leaves no trace at all, and neither does the 60-day auto-disable of an idle
scheduled workflow. Passive monitoring can't see a non-event. First instinct was to move the schedule
off the top of the hour (`:17`) to dodge congestion — reverted, because it doesn't buy reliability at
all: GitHub cron is best-effort at *every* minute, so the honest fix is **detecting** a miss, not
picking a lucky slot.

### The fix and the four things that make it correct, not just present
A **dead man's switch** (Healthchecks.io) inverts the logic: the job pings a monitor, and the *monitor*
pages *me* if the expected daily ping doesn't arrive. The subtleties are what make it real:
- **Success-gating is load-bearing.** The success ping fires **only** on a fully-green run (`if:
  success()`), never `if: always()`. Ping unconditionally and a failed run reports "alive" — you've
  built a switch that *lies*, a green monitor over a broken pipeline. Three signals — `/start` (first
  step, so duration is measured), the bare success URL (last step, gated), and `/fail` (in the
  `if: failure()` step) — give missing-run detection *and* duration *and* an explicit fail, same effort
  as one.
- **The ping URL is a secret** (`HEALTHCHECKS_URL`), never in the YAML — anyone holding it can forge a
  healthy ping and keep the monitor falsely green. Same discipline as `DOG_API_KEY` / `MOTHERDUCK_TOKEN`.
- **Wide grace on purpose.** GitHub cron is routinely 15-30 min late (normal, not a miss). A tight
  window would cry wolf, a flaky page gets muted, and a muted alert is no alert — the "wallpaper" rule
  (§3) applied to paging. Grace a few hours.
- **It's inert until wired.** Every ping step is gated on `env.HEALTHCHECKS_URL != ''`, so it ships
  harmless and turns on when I create the check and add the secret.

That closes the gap `scheduled.yml` had flagged honestly for milestones ("a red cron nobody sees isn't
running") — and now covers the strictly-worse case it *hadn't*: a cron nobody sees because it never ran.
Left for later: Elementary's `edr monitor` to page on a *specific failing test* rather than a failed run.

## M10 — atomic gold updates: the one that made "Last refreshed" honest

Adding the freshness caption exposed a deeper bug I'd have shipped without noticing: **the timestamp
could lie.** dbt materializes a model and *then* tests it, so a failed test leaves the bad table live
(only *downstream* is skipped); and building straight into `md:dogs` (the M9 plan) leaves it torn on a
mid-build crash. So the dashboard could show a fresh "Last refreshed" over a mix of new and stale gold —
the freshness column and honesty were only half-built.

### The pattern, and the one thing I refused to regress
Write-Audit-Publish is the textbook fix, but the naive version (build to a throwaway local file,
republish everything) would **drop the two things I'd just called essential** — the durable `raw`
history and the Elementary trends, both of which accumulate in `md:dogs`. So the design splits by write
pattern: `raw` (partition append) and `main_elementary` (hook append) keep landing in `md:dogs` every
run — a *failed* run still records itself there, which is observability working — and **only the gold
marts**, which are full-replaced, get the shadow-schema swap. The cron builds gold into `main_marts_next`
(a `marts_schema` dbt var), tests it, and `publish_motherduck.py` swaps it into live `main_marts` in one
transaction, only on full green.

### Verify-first, because the mechanism was an unknown
I didn't wire anything until the load-bearing question was settled. `ALTER SCHEMA … RENAME` — the
obvious swap — turned out to be **unimplemented in DuckDB** (verified, not assumed). The working
primitive is a transactional `CREATE OR REPLACE TABLE … AS SELECT *` per table, which I proved atomic
first on local DuckDB and then **on MotherDuck itself** (throwaway `md:` db, forced a failure mid-swap,
asserted the live schema was byte-identical — full rollback). Only then Steps 1-5.

### The proof that it works, end to end
On a throwaway `md:wap_e2e`: a **success** run built the shadow, swapped 7 tables into live gold
(627 breeds), dropped the shadow. An **injected-failure** run (a temp always-failing test) exited
non-zero at Phase A → Phase B skipped → **live "Last refreshed" unchanged while raw's `loaded_at`
advanced.** That last line is the whole point made concrete: raw re-ingested, gold did *not*, so the
timestamp reflects the last *successful* publish and can never show fresh-over-stale. `dogs` was never
touched. The publish list is discovered from the shadow schema via `information_schema` (scoped to the
connected db + base tables), so adding a mart tomorrow flows through with no code change.

### Refinement — atomicity is a property of the destination, not the caller
The first cut put WAP in the *workflow* (a shadow env var + a separate Phase B step), which meant a
hand-run `DBT_DUCKDB_PATH=md:dogs ./run_pipeline.sh` — the exact command I'd use to seed or refresh the
cloud by hand — **bypassed the atomic swap** and wrote gold straight to live. That's a footgun: the
protection belonged to the cron, not to "writing to `md:dogs`." So I moved WAP *into* `run_pipeline.sh`:
an `md:` destination builds into the shadow and swaps internally, a local file builds direct. Now every
path to the cloud is atomic, and `scheduled.yml` collapses to one "Run the pipeline" step. Verifying it
also caught a bug the first cut shipped: the `--vars` **array** form, empty on the local branch, is an
"unbound variable" under `set -u` on **macOS's bash 3.2** — CI's bash 5.x tolerated it, so it passed CI
but a local `./run_pipeline.sh` would have died. Two explicit build branches, no array, fixed both.
