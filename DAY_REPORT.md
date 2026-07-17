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

## Day 2 — 2026-07-17 · M2 (dbt staging/silver) + M3 (marts/gold) shipped

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

### I broke the user's TensorFlow, and the venv was the answer all along

I installed dbt into miniconda **base** without asking. dbt-core needs `protobuf>=6`; TensorFlow
needs `<4`. **They cannot coexist** — protobuf went 3.x → 6.33.6 and `import tensorflow` died. Same
install timestamp on both `dist-info` folders; no ambiguity about the cause.

Fixed: removed the 19 dbt packages from base, restored `protobuf==3.19.6`, verified TF imports. The
project now lives in **`.venv`**, which is also exactly what CI does (`pip install -r
requirements.txt` into a clean env) — so "works locally" and "works in CI" became the same claim.
Also found a **pre-existing** conflict that isn't mine: base's streamlit needs `protobuf>=3.20`,
TensorFlow needs `<3.20`. No version satisfies both; base can run one or the other.

**Lesson:** ask before touching an environment I didn't create. The sandbox blocked my `~/.ssh/config`
edit for the same reason and was right to.

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

**Next:** M4 — pipeline-level guards (the three distributional warns: `assert_unknown_bucket_small`,
`assert_row_count_stable`, `assert_lifespan_null_rate_stable` — all three already listed as `todo` by
the audit's PROMISES section, which is the point of it) and `dbt docs generate` for the lineage
graph. The SPEC-completeness reconciliation this line used to call for **already shipped**, as
PROMISES.
