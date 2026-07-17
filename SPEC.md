# SPEC — Filled from the real data profile (628 rows, 17 fields)

Supersedes the bracketed template. Every decision here is grounded in PROFILE_REPORT.md.
Business logic lives in dbt gold; the dashboard stays thin.

## Key facts from profiling that drive the design
- **628 rows**, `id` unique + non-null → **PK = `id`** (cast to INTEGER).
- **weight/height are mostly sex-specific ranges** (430/628 metric weight) → the parser's
  *common* case is `"Male: X-Y; Female: A-B"`, not the simple `"X-Y"`. A naive split fails on 2/3.
- **`'unknown'` string sentinels** in 2 weight + 2 height rows → convert to NULL *before* casting,
  or they silently poison numeric parsing.
- **`life_span` is just `"X-Y"`** (no "years" suffix, unlike the brief's claim), 6.4% null.
- **Duplicate breed:** "Caucasian Shepherd Dog" on ids 70 and 269 → conscious dedupe decision.
- **temperament casing:** 66 tags → 46 lowercased (**45 after the sentinel is excluded**) →
  normalise before grouping. 627 tag rows carry uppercase — a model without `lower()` fails loudly.
- **Dead fields:** `species_id` (constant), `bred_for` + `perfect_for` (100% null) → drop.
  `country_code` == `country_codes` → keep one.
- **LLM bonus must NOT use `bred_for`** (empty). Derive from `temperament`/`description` instead.

## Warehouse layers (DuckDB `dogs.duckdb`)
| Layer | Object | Built by | Notes |
|---|---|---|---|
| bronze/raw | `raw.breeds` | ingestion | untouched payload + `run_date`, `loaded_at` |
| silver | `stg_breeds` | dbt | parsed, typed, sentinels→null, deduped |
| silver | `stg_breed_temperaments` | dbt | one row per (breed, normalised tag) |
| gold | `dim_breeds` | dbt | clean + derived (size_class, midpoints) |
| gold | `breed_temperaments` | dbt | bridge, exposed for querying |
| gold | `mart_size_class_summary` | dbt | grain: size_class — counts + mean life span (retires `mart_weight_distribution`) |
| gold | `mart_size_vs_lifespan` | dbt | grain: breed — scatter-ready (weight + life span only) |
| gold | `mart_metric_correlation` | dbt | grain: (metric_a, metric_b) — 3 rows + `n_breeds` |
| gold | `mart_size_class_temperaments` | dbt | grain: (size_class, temperament) — count + % within class |
| gold | `mart_data_coverage` | dbt | one row — what each chart drops (627 total, 585 plotted) |
| seed | `size_class_bands` | dbt seed | the ONLY home of the bucket boundaries |

## Materialization & schemas

| layer | schema | materialized | why |
|---|---|---|---|
| raw/bronze | `raw` | (ingestion, not dbt) | written by `ingest.py` |
| staging/silver | `main_staging` | **view** | cheap, always consistent with raw; nothing reads it but marts |
| marts/gold | `main_marts` | **table** | the dashboard reads these — materialize once at build, not per page load |
| seed | `main` | table (dbt default) | seeds are tables by definition |

Views for staging, tables for marts is the dbt convention, and it earns itself here: staging is a
parse-and-type pass with exactly one consumer (marts), so a view costs nothing and can never be
stale. Marts are read repeatedly by a dashboard, so they get built once — the read path never
re-executes the parser. Set in `dbt_project.yml`, not per model:

```yaml
models:
  dog_breed_explorer:
    staging:
      +materialized: view
      +schema: staging      # -> main_staging
    marts:
      +materialized: table
      +schema: marts        # -> main_marts
```

Note dbt **concatenates** custom schemas onto the target schema by default (`main` + `staging` =
`main_staging`), which is why the config says `staging`, not `main_staging`.

### A dropped test is worse than no test — `warn_error_options` (built in M2)

```yaml
flags:
  warn_error_options:
    error:
      - NodeNotFoundOrDisabled
```

**dbt DROPS a test whose `ref()` doesn't resolve, with only a warning and exit 0.** Typo a model
name, or rename one and miss a test file, and that test simply stops existing — CI stays green and
you believe you're covered. Verified: a typo'd ref → warning, exit 0; with this flag → **exit 2**.

**Scoped to that one event, deliberately.** A blanket `--warn-error` would also escalate our
`severity: warn` *tests* (`assert_metric_shape_known`, `assert_source_tag_not_duplicated`, the three
distributional guards) into build failures, destroying the warn/error split on purpose. Verified:
with the flag, a warn-severity test still exits 0.

The line it draws, worth stating plainly: **a broken wire is an error; unexpected data is a warning.**
One means the pipeline is lying about its coverage; the other means the world changed.

**Corollary — watch `Found N data tests`.** It is the only cheap check that nothing silently
vanished. Post-M2 it must read **26**.

### Source freshness (built in M2)

`_sources.yml` declares `loaded_at_field: loaded_at` (the column ingestion writes) with
`warn_after: {count: 36, period: hour}`. A daily cron means >36h without a run **is** a missed run.
Surfaced by `dbt source freshness`, a separate command from `dbt build` — **warn only**: a stale
local file is a signal for me, not a reason to fail a build.

## dbt targets: **dev and prod, parameterized** (a scored requirement — build it)

The brief scores "parameterize so it can run against both a dev and a prod target." This is the
deliverable, stated concretely so it can't get lost: **one `profiles.yml`, two targets, identical
model code**. The only difference between dev and prod is *which database file dbt writes to* —
never the SQL. If a model ever needs to know its target, that's a smell.

```yaml
# dbt/profiles.yml
dog_breed_explorer:
  target: dev                     # dev is the default: an unqualified `dbt build` cannot
  outputs:                        # touch the serving copy by accident
    dev:
      type: duckdb
      path: "{{ env_var('DBT_DUCKDB_PATH', '../dogs_dev.duckdb') }}"
      threads: 4
    prod:
      type: duckdb
      path: "{{ env_var('DBT_DUCKDB_PATH', '../dogs.duckdb') }}"
      threads: 4
```

| target | who runs it | database | lifetime |
|---|---|---|---|
| **dev** | me, iterating on models | `dogs_dev.duckdb` | scratch — delete it any time |
| **prod** | the CI/scheduled workflow, **and** my local demo build | `dogs.duckdb` | discarded with the VM in CI; durable on my laptop, where the dashboard reads it |

```bash
# dev — iterate without touching the serving copy
python ingestion/ingest.py --db dogs_dev.duckdb
dbt build --target dev

# prod — the CI workflow, and the local build the dashboard reads
python ingestion/ingest.py --db dogs.duckdb
dbt build --target prod
```

**`prod` means "the production-shaped build", not "the cloud."** Per DECISIONS.md §5, CI proves the
pipeline and discards its warehouse; the laptop's prod build is what the dashboard reads. Same
target, same code, two lifetimes.

**The coupling to watch:** ingestion writes the file dbt then reads, so `ingest.py --db` and the dbt
target must point at the **same file**. They are two separate programs agreeing on a path — the one
genuinely fragile seam in this design. `DBT_DUCKDB_PATH` exists so CI can set both from one
environment variable rather than repeating a literal path in two workflow steps.

`profiles.yml` lives in the repo (committed — it holds no secrets, only paths). `DOG_API_KEY` is the
only secret and never appears here.

## stg_breeds — target columns
| Column | Type | Derivation |
|---|---|---|
| breed_id | INTEGER | CAST(id) — PK |
| breed_name | VARCHAR | name (trimmed) |
| life_span_min_years | INTEGER | split `life_span` on '-', part 1; null if missing/unparseable |
| life_span_max_years | INTEGER | split part 2 |
| life_span_mid_years | DOUBLE | (min+max)/2.0 |
| weight_min_kg | DOUBLE | parse `weight.metric` (see parser below); overall MIN across sexes |
| weight_max_kg | DOUBLE | overall MAX across sexes |
| height_min_cm | DOUBLE | parse `height.metric` same way |
| height_max_cm | DOUBLE | " |
| breed_group | VARCHAR | breed_group (26 distinct; keep) |
| origin | VARCHAR | origin |
| country_code | VARCHAR | country_code (drop the redundant country_codes) |
| description | VARCHAR | description (for LLM bonus) |
| temperament_raw | VARCHAR | keep raw string for reference/enrichment |
| image_url | VARCHAR | image.url (nullable, 14.3% null) |
| loaded_at | TIMESTAMP | from raw |
| weight_raw | VARCHAR | `weight.metric` after `'unknown'`→NULL — **the string the parser was handed** |
| height_raw | VARCHAR | `height.metric` after `'unknown'`→NULL |
| life_span_raw | VARCHAR | `life_span` after `''`→NULL |
| n_missing_fields | INTEGER | count of null/empty fields on the raw row — **dedupe tiebreak only** |

The three `*_raw` columns are not cosmetic: `assert_metric_parsed` needs them to ask *"you were
handed a string — where's the number?"* without re-deriving what a sentinel is. Free (staging is
a view) and they make every parse traceable back to its input.

**`n_missing_fields`** exists for exactly one job: ordering the dedupe. It is the count of
null/empty values across the source fields on that raw row:

```sql
(case when payload->>'description' is null or trim(payload->>'description') = '' then 1 else 0 end +
 case when payload->>'origin'      is null or trim(payload->>'origin')      = '' then 1 else 0 end +
 ... one term per source field ...) as n_missing_fields
```

**Verified against the real dupe, and it does NOT decide it:** ids 70 and 269 each have **exactly 2
empty fields of 17**, and both have an image. They tie — so the rule falls through to `breed_id` and
**70 wins**. The tiebreak isn't decoration, it's the thing that actually resolves this case, and it
must be deterministic or the bridge contents change between runs (the two rows carry *different*
temperaments: 70 has `alert`, 269 has `loyal`). `n_missing_fields` stays in the rule because a
future duplicate may not be tied.

**Dropped with reason:** `species_id` (constant=2), `bred_for` (100% null), `perfect_for`
(100% null), `country_codes` (== country_code), `reference_image_id` (redundant with image),
`history` (long free text, no analytical use — keep only if a dashboard needs it).

## The metric range parser (the crux — handles 3 shapes)
Input examples: `"3.2-4.5"`, `"Male: 25-30; Female: 20-25"`, `"unknown"`.
1. If value == 'unknown' (case-insensitive) → NULL, NULL.
2. Extract ALL numbers with a regex (`\d+\.?\d*`). This naturally handles both simple and
   sex-specific forms, because it just grabs every number present.
3. `min = min(all numbers)`, `max = max(all numbers)`. For `"Male: 25-30; Female: 20-25"` that
   yields min=20, max=30 — the breed's full envelope across sexes. For `"3.2-4.5"` → 3.2, 4.5.
4. If no numbers found → NULL, NULL (don't crash).
> Design note to state: I collapse male/female into one overall min–max envelope rather than
> keeping separate columns, because a "Dog Breed Explorer" wants a breed-level weight, not a
> sex-split. Keeping male/female separate is a "with more time" option.

## dim_breeds — added derived columns
| Column | Type | Derivation |
|---|---|---|
| (all stg columns) | | |
| weight_mid_kg | DOUBLE | (weight_min_kg + weight_max_kg)/2 |
| height_mid_cm | DOUBLE | (height_min_cm + height_max_cm)/2 — same explicit rule as weight |
| life_span_range_years | INTEGER | max - min |
| size_class | VARCHAR | from weight_mid_kg — seed join, see below |

**size_class buckets — FROZEN (confirmed in M0.5 against the real distribution; rationale in
DECISIONS.md §0).** The boundaries are **data, not code**: they live in the seed
`seeds/size_class_bands.csv` and exist nowhere else.

```
label,min_kg,max_kg
toy,0,5
small,5,12
medium,12,25
large,25,45
giant,45,999
```

**Intervals are half-open `[min_kg, max_kg)`** — lower bound inclusive, upper exclusive. The literal
join predicate, so there is no room for interpretation:

```sql
weight_mid_kg >= min_kg AND weight_mid_kg < max_kg
```

Consequences, stated so nobody re-derives them: a breed at **exactly 45.0 kg is `giant`** (not
large); at exactly **25.0 kg is `large`** (not medium); at exactly **5.0 kg is `small`** (not toy).
This is not pedantry — **31 breeds (5%) sit exactly on a boundary**, 23 of them on 25 kg. Note
`pd.cut` defaults to the *opposite* convention (right-closed), which is exactly how the exploration
app and a SQL prototype came to disagree by 2 breeds; any Python that reproduces these numbers must
pass `right=False`.

**`unknown` is NOT a band and is NOT in the seed.** The seed holds only the five real ranges; a
label with no range has no business in a range table. The null case is handled explicitly in the
model, *before* the join:

```sql
CASE WHEN weight_mid_kg IS NULL THEN 'unknown' ELSE <range join> END
```

That keeps the seed honest (ranges only) and makes "where does the null live" a deliberate decision
rather than a fallback. Affects exactly **2 breeds** — Langqing (518) and Mongrel (536), the
`'unknown'` weight sentinels. Expected distribution: **toy 40 · small 104 · medium 220 · large 203 ·
giant 58 · unknown 2 = 627** — **post-dedupe** (the Caucasian Shepherd removed from `giant`).
Raw holds 628; `dim_breeds` holds **627**. Every count below is post-dedupe.

## breed_temperaments (bridge)
| Column | Type | Notes |
|---|---|---|
| breed_id | INTEGER | FK → dim_breeds |
| temperament | VARCHAR | **lowercased + trimmed** tag (group on this) |
| temperament_display | VARCHAR | sentence-cased for the dashboard. **Never group on this** |

Built by splitting `temperament_raw` on ',', trimming, lowercasing. **Verified: 3,538 rows · 45
distinct tags · 626 of 627 breeds · 5.6 tags/breed.**

**The temperament sentinel (decided in M2).** Breed 536 "Mongrel" carries one tag:
`"Variable depending on ancestry and individual traits"`. That is not a temperament — it is the
API saying *not applicable*, and the evidence is on the row itself: **the same breed's
`weight.metric` is the literal string `'unknown'`**, which we already null. Two spellings of "we
don't know" on one row; treating one as a sentinel and shipping the other as a real tag would be
incoherent. **It is excluded in `stg_breed_temperaments` by literal**, exactly like `'unknown'` —
only the ONE instance profiling found, never "anything over 3 words" (that would make
`assert_tag_not_freetext` vacuous). So Mongrel has no weight AND no tags, which is the truth, and
the test reads **0** instead of warning forever about a row we'd already decided to accept.
Consequence, stated: **breeds_with_temperament = 626, not 627.**

**`select distinct` — and why the severity moved.** Case-folding can *create* a duplicate that
isn't in the source (`"Loyal, loyal"` → `'loyal','loyal'`), so the risk is ours, not the API's.
The bridge absorbs it with `distinct` rather than failing the daily cron over one breed. Absorbing
*silently* would be the wrong half of the trade, so the signal moves to
`assert_source_tag_not_duplicated` (**warn**), which re-derives the split from `stg_breeds` —
**a test downstream of the fix cannot see what the fix hid.** Once `distinct` guarantees the grain,
a repeated source tag is drift, not broken data → warn, per the severity rule below.

## The duplicate-breed decision
Caucasian Shepherd Dog appears on ids 70 and 269 (same origin, genuine dupe).
**Decision:** dedupe in staging — keep the row with the more complete data (fewer nulls / has an
image); if tied, keep the lower id. Document in DECISIONS.md. Rationale: a user browsing the
explorer should not see the same breed twice; `id` stays the PK but the duplicate is a data-quality
artifact, not two breeds.

## Tests (declare BEFORE finalising models = the TDD contract)
1. `dim_breeds.breed_id`: `unique`, `not_null`.
2. `dim_breeds.size_class`: `accepted_values` = **the five seed labels + `'unknown'`**
   [toy, small, medium, large, giant, unknown]. The seed supplies the five; `unknown` is the
   model's explicit null branch and is deliberately not in the seed (it has no range).
2b. custom `assert_size_class_bands_cover`: the seed's ranges must be contiguous and
   non-overlapping (`max_kg` of each band == `min_kg` of the next). A gap or an overlap in the seed
   would silently mis-bucket or drop breeds — the seed is data, so it gets tested like data.
2c. custom `assert_no_breed_unbanded`: no row has `weight_mid_kg IS NOT NULL AND size_class =
   'unknown'` — i.e. a real weight always finds a band. Catches a seed range that doesn't reach.
3. custom `assert_weight_min_le_max`: rows where `weight_min_kg > weight_max_kg` → must be empty.
4. custom `assert_lifespan_min_le_max`: rows where `life_span_min_years > life_span_max_years` → empty.
5. custom **`assert_metric_parsed`**: rows in stg where a raw metric string was present but produced
   no number → empty. **Supersedes the old `assert_no_unknown_sentinel`**, which only looked for the
   literal `'unknown'`. This is the general form — "we had a string and didn't understand it" —
   so it catches `'unknown'`, `'N/A'`, `''`, and every sentinel the API invents next:
   ```sql
   select * from {{ ref('stg_breeds') }}
   where (weight_raw    is not null and weight_min_kg       is null)
      or (height_raw    is not null and height_min_cm       is null)
      or (life_span_raw is not null and life_span_min_years is null)
   ```
5b. custom **`assert_metric_shape_known`** (**warn**) — **the notation-change flag.** The raw metric
   string must match one of the three profiled shapes (each with an optional unit suffix):
   `X-Y` · `Male: X-Y; Female: A-B` · bare `X`. Anything else means the source changed how it writes
   measurements.
   **Why this test has to exist separately:** the parser extracts *every number and takes min/max*,
   which is deliberately shape-blind — that's its strength (`"12 years - 13 years"` → 12/13 and
   `"3-5kg"` → 3/5 both work for free, verified). But it is also its ceiling: **a regex sees numbers,
   not meaning.** `"3.5 kg (7.7 lb)"` parses to 3.5/7.7 — mixing units — and `"2 years 6 months"` to
   2/6 instead of 2.5. Both are *silently wrong*: `min <= max` holds, the PK is fine, nothing else
   fires. Only a shape check catches them.
   **Why `warn`, not `error`:** unlike the unit ratio (where a switch to lbs means every number is
   guaranteed wrong), a new notation *might* parse perfectly — erroring would block a good run.
   Warn puts a human in front of it. Follows the rule: invariants error, "the world changed" warns.
6. range check: `weight_mid_kg` between ~0.5 and ~100 when not null.
7. `breed_temperaments`: `relationships` breed_id → `dim_breeds`, plus custom
   **`assert_tag_unique_per_breed`** — `unique` on the COMBINATION (breed_id, temperament), so it
   must be a singular test (dbt's built-in `unique` is single-column; dbt_utils isn't worth a
   dependency for one test). With `distinct` in the model this guards the **grain** — it fires if
   anyone deletes that line or a join fans out — while the *source* side is covered by 7c.
7b. custom `assert_tag_lowercased` (**error**): no tag differs from its own `lower()`/`trim()`.
   **The genuine red of M2's bridge: 627 rows failed before `lower()` landed.** Without it,
   `GROUP BY temperament` splits `intelligent` (536 breeds) across two casings — two plausible,
   both wrong.
7c. custom **`assert_source_tag_not_duplicated`** (**warn**): re-derives the split from
   `stg_breeds` to see duplicates the bridge's `distinct` already absorbed. Reading the bridge
   would be structurally incapable of firing.
7d. custom `assert_tag_not_freetext` (**warn**): flag any tag longer than ~3 words. **Expected 0** —
   the one known instance is excluded as a sentinel (see the bridge section), which is what makes
   this a signal rather than a permanent WARN 1 nobody reads. Threshold `>3` sits in an empty gap:
   the vocabulary is 44 one-word tags + `'eager to please'` (3 words); the sentinel was 7.
8. **`unique` on `stg_breeds.breed_name`** — THE test that catches the Caucasian Shepherd duplicate.
   `unique(breed_id)` **cannot**: ids 70 and 269 are perfectly distinct. Went red on exactly 1 row
   before the dedupe landed. (Supersedes the vaguer "row count == distinct breeds after dedup".)
8b. `assert_height_min_le_max` — the same invariant as weight, for height. Not in the original list;
   height runs the identical code path, so omitting it left the parser half-covered.
9. custom `assert_unit_ratio_plausible`: units are inferred, not declared, so this is the tripwire
   for a silent source unit change (e.g. metric quietly becoming pounds — every number stays valid,
   every other test passes, the whole dashboard is wrong by 2.2×).
   **"Near" is not a spec — the literal bounds, ±5%:**
   | metric | ratio | accept if median is in | observed |
   |---|---|---|---|
   | weight | lb/kg = 2.205 | **[2.095, 2.315]** | **2.200** ✓ |
   | height | in/cm = 2.54 | **[2.413, 2.667]** | **2.542** ✓ |
   Computed as `median(imperial_min / metric_min)` over rows where both parse and `metric_min > 0`.
   Median, not mean, so a single bad row can't drag it. `severity: error` — a unit switch is not
   drift, it is broken data.
9b. `mart_size_class_temperaments`: `unique` on the combination **(size_class, temperament)** — the
   grain; a duplicate would double-count a tag and inflate `pct_of_class`. `not_null` on all three
   keys. `accepted_values` on `size_class` (same six labels). Plus custom
   **`assert_pct_of_class_sane`**: `pct_of_class` must be `> 0` and `<= 100`, and `breed_count <=
   breeds_in_class` — a tag cannot be held by more breeds than exist in the class. That inequality is
   the load-bearing one: it's what fails if the join fans out, which is the realistic bug in a mart
   built from a bridge.

### Severity: invariants ERROR, distributional guards WARN

Tests 1–9 above are **hard invariants** — logically broken data (min > max, duplicate PK, a
surviving sentinel). They are `severity: error`: broken data must not ship.

The three below are **distributional guards** — they encode "this run looks like a normal run", not
logic. They are **`severity: warn`**, deliberately. A null-rate spike or a row-count jump might be a
real regression *or* legitimate drift (the API genuinely adds 40 breeds). Auto-failing the build on
legitimate growth is worse than surfacing it loudly for a human to judge. Use dbt's `warn_if` /
`error_if` if a catastrophic band is wanted (e.g. warn at 5% deviation, error at 25%).

10. custom `assert_unknown_bucket_small` (**warn**): `size_class = 'unknown'` must be **≤ 1%** of
    `dim_breeds` (expected: 2 of 627 = 0.3%). **The highest-value guard of the three** — it directly
    defends a chosen deliverable: if `unknown` balloons, the weight-distribution chart is visibly
    wrong while every hard test still passes.
11. custom `assert_row_count_stable` (**warn**): `dim_breeds` row count within **±5%** of the
    expected **~627** (dim_breeds, post-dedupe — NOT raw's 628).
12. custom `assert_lifespan_null_rate_stable` (**warn**): `life_span_mid_years` null rate **≤ ~10%**
    (observed: 6.4%).

**Why these exist at all:** every test 1–9 is a hard invariant, so the data can *degrade without
breaking any of them*. A run returning 300 nulls, or `""` in place of `"unknown"`, is perfectly
valid — min ≤ max holds, the PK is still unique — it is simply **wrong**. CI goes green and the
dashboard silently shows garbage. That is the nastiest failure mode: valid, passing, and visible
only to whoever notices half the chart is empty. These three turn a silent source regression into a
visible signal — the same job `assert_unit_ratio_plausible` already does for units.

## Marts for the dashboard (business logic upstream, dashboard thin)

**One mart per grain.** `mart_weight_distribution` is **retired** — it was counts-only at
`size_class` grain, and `mart_size_class_summary` supersedes it at that same grain. Two marts keyed
on `size_class` is drift waiting to happen.

- **`mart_size_class_summary`** — grain: **size_class** (6 rows incl. `unknown`).
  `size_class, breed_count, breeds_with_life_span, mean_life_span_years, median_life_span_years,
  **stddev_life_span_years**, **min_life_span_years**, **max_life_span_years**, mean_weight_kg,
  mean_height_cm`.
  Serves the count bars **and** the mean-life-span line **and** the numbers table. `breed_count`
  counts all breeds in the class; `mean_life_span_years` averages only those with a life span
  (6.4% null), so **both denominators are exposed** rather than one being silently implied.

  **`stddev_life_span_years` is not decoration — it is the honest half of the headline claim.**
  Measured (`stddev_samp`, so the 6 rows are directly plottable as ±1σ error bars on the same chart
  the mean line already feeds — no extra mart, that's the payoff of one-mart-per-grain):

  | size_class | n | with_life_span | mean | **std** | range |
  |---|---|---|---|---|---|
  | toy | 40 | **29** | 13.3 | **0.86** | 11.0–15.0 |
  | small | 104 | **86** | 13.2 | **0.68** | 11.0–15.0 |
  | medium | 220 | 212 | 13.0 | **0.77** | 9.0–15.0 |
  | large | 203 | 200 | 12.2 | **1.03** | 8.5–14.5 |
  | giant | 58 | 58 | 10.6 | **1.54** | 6.5–13.5 |

  Two things the mean alone hides, both worth saying in the narrative: **the spread grows with size**
  (0.68 → 1.54 — giant breeds are shorter-lived *and* less predictable), and the toy→giant gap
  (2.7 yr) is **under 2σ of the giant band**, so the distributions overlap heavily. The trend is real
  in the mean and weak per-dog. Without the std, the chart oversells −0.671 exactly the way §0 says
  the bar chart would.
- **`mart_size_vs_lifespan`** — grain: **breed** (one row per breed, ready to scatter).
  `breed_id, breed_name, size_class, weight_mid_kg, life_span_mid_years`.
  **No `height_mid_cm`** — its only consumers were the height-vs-weight view and the scaling fit,
  both cut. Height remains a breed fact in `dim_breeds` and `mart_size_class_summary`; it just has
  no reader here. A column with no consumer is a column that rots.
- **`mart_metric_correlation`** — grain: **(metric_a, metric_b)**, 3 rows.
  `metric_a, metric_b, correlation, n_breeds`. Three lines of SQL (`corr(x, y)` is a DuckDB
  aggregate). The number quoted in the narrative is computed by dbt, tested and reproducible —
  not a `df.corr()` in the dashboard.
- **`mart_size_class_temperaments`** — grain: **(size_class, temperament)**.
  `size_class, temperament, breed_count, breeds_in_class, pct_of_class`.
  For each size class, how often each temperament tag appears. "Characteristic" here means nothing
  cleverer than **most frequent within the group** — a `GROUP BY size_class, temperament` with a
  `COUNT`, joining two tables that already exist (`ref('breed_temperaments')` → `ref('dim_breeds')`).
  **The one subtlety, and it's the reason `pct_of_class` exists:** raw counts favour big classes —
  220 medium breeds will out-count 40 toy breeds on every tag, purely because there are more of
  them. So the dashboard reads **`pct_of_class` = breed_count / breeds_in_class**, which makes
  classes comparable ("72% of giant breeds are calm"). That is normalising **within** a group, not
  computing association — no lift, no baseline, no leave-one-out. It stays on the *descriptive fact*
  side of the line, which is exactly why it ships and `mart_temperament_pair_lift` doesn't.
  Both `breed_count` and `breeds_in_class` are kept, so the denominator is visible rather than
  implied — the same rule `mart_size_class_summary` follows.
  **Top-N is presentation, not gold:** the mart holds every (class, tag) pair; the dashboard takes
  the top 3–5. Bake the cut into the model and you can't change it without a rebuild.
- **`mart_data_coverage`** — grain: **one row**. `total_breeds, breeds_with_weight,
  breeds_with_life_span, breeds_with_both, breeds_with_temperament, breeds_plotted_scatter`.
  **What every chart silently drops, stated as a fact the dashboard prints.** Measured today:

  | | breeds |
  |---|---|
  | total (post-dedupe) | **627** |
  | no weight | 2 → `size_class = 'unknown'` |
  | no life span | **40** → excluded from every life-span mean |
  | **scatter needs both → dropped** | **42 → 585 plotted** |
  | no temperament | **1** (Mongrel — its tag is a sentinel, excluded) → bridge covers **626** of 627, 3,538 rows |

  **Why this is not cosmetic:** the missing life spans are *not evenly spread*. **Toy has 29 of 40**
  (27.5% missing); **giant has 59 of 59** (0%). So the toy bar at 13.3 yr rests on 72% of toy breeds
  and the giant bar on 100% — a real bias in the headline chart that no reader could detect. A
  dashboard that says "627 breeds" while plotting 585 is quietly lying. Reading `n_breeds = 585` off
  `mart_metric_correlation` gives the same number, which is a good consistency check on both.
- (optional) `mart_top_temperaments`: tag → breed count, from the bridge. Largely subsumed by
  `mart_size_class_temperaments` — only build it if an overall (non-size-split) tag ranking is
  wanted.

**Cut: `mart_size_scaling_fit`** (was: isometry exponent `k`, `weight ~ height^k`, k=2.07/R²=0.864).
A real finding, and the wrong deliverable: the brief asks for "a curated analytics layer exposing
facts about dog breeds (life span, size class, temperament, and so on)", and a log-log regression
exponent is data-science cleverness, not a fact about a dog. It goes in DECISIONS.md as an explored
finding, not in gold. `mart_metric_correlation` **stays** — correlations with life span are the
evidence for "size = weight" and are legible enough to show.

**Population convention for `mart_metric_correlation`: PAIRWISE.**
Each row uses every breed where *its own* two metrics are non-null — not only breeds with all three.
This is why `n_breeds` is a column: **a correlation without its population is not a fact.** Pairwise
vs listwise is not cosmetic — it moves the numbers:

| pair | pairwise (SPEC, n) | listwise |
|---|---|---|
| weight ↔ life span | **−0.670** (585) | −0.670 |
| height ↔ life span | **−0.502** (585) | −0.502 |
| height ↔ weight | **0.860** (625) | 0.851 |

## Dashboard questions (CONFIRMED in M0.5 — answering 3 of the 4)
1. **How are breeds distributed across weight classes?** → count bars from
   `mart_size_class_summary`.
2. **Is there a relationship between size and life span?** → mean-life-span line **with ±1σ error
   bars** (`stddev_life_span_years`, same 6 rows) from `mart_size_class_summary` + per-breed scatter
   from `mart_size_vs_lifespan`, with the correlations from `mart_metric_correlation` as the stated
   evidence. The std is **required, not optional**: without it the chart claims a precision the data
   doesn't have (giant σ=1.54 vs a 2.7 yr toy→giant gap — the bands overlap).

**Every chart states its population, from `mart_data_coverage`** — "585 of 627 breeds; 42 excluded
for missing weight or life span". Never print 627 next to a chart drawn from 585. Note especially
that life-span coverage is **uneven by class** (toy 29/40 vs giant 58/58), so the per-class
denominator (`breeds_with_life_span`) belongs next to the bars too.
3. **Which temperaments are characteristic of each size class?** → top 3–5 tags per class by
   `pct_of_class` from `mart_size_class_temperaments`, as a horizontal bar or small table:
   `Giant: calm 72% · protective 61% · loyal 55%` / `Toy: alert 68% · playful 63%`.
   Narrative: *"temperament varies systematically with size — giant breeds skew calm and protective,
   toy breeds alert and playful."* This is what puts **temperament** — one of the three fields the
   brief names — on the dashboard as a headline fact rather than only a bridge table nobody looks at.

**"Size" is defined as weight**, not height, and the correlation mart is the evidence: weight↔life
−0.671 vs height↔life −0.503, and height↔weight 0.860 means height adds little once weight is in.
Stated in DECISIONS.md §0. The correlation numbers **render on the dashboard** (they're about life
span, which is the question) — but as numbers, not as a fitted curve.

**Chart rule: the two questions render as two charts stacked on a shared x-axis, NEVER one
dual-axis plot.** Two y-scales align arbitrarily and fabricate a relationship. See DECISIONS.md §0.

**Cut from the dashboard:** the height-vs-weight scatter and its fitted isometry curve. See the
`mart_size_scaling_fit` note above — a regression exponent is not a fact about a dog breed.

## LLM bonus (if fundamentals solid) — REVISED given profiling
`bred_for` is empty, so derive instead: an **`energy_level`** (low/medium/high) or
**`good_with_kids`** flag from `temperament_raw` + `description` + `breed_group`. Batch all 628 in
one pass per run, cache by breed_id so unchanged breeds aren't re-called, and eval on a handful of
hand-labelled breeds + a schema/enum validity check. Fold back as a real column in dim_breeds.

### How enrichment joins the DAG — **Pattern A: enrich writes a table, dbt reads it**

`enrich.py` reads `stg_breeds` from DuckDB, calls the LLM, and writes
**`raw.breed_enrichment`** (keyed by `breed_id`). `dim_breeds` then joins it like any other input.
The enrichment is not a special case — it's just another table dbt reads.

```
ingest.py  →  dbt build --select staging  →  enrich.py  →  dbt build --select marts
   (E+L)              (T, silver)            (LLM, Python)        (T, gold)
```

Two dbt invocations with a Python step between them. The cost is stated plainly: **the pipeline is
no longer one `dbt build`**, and the run script has to sequence four steps instead of two. That's
the price of keeping the LLM call outside the warehouse, and it buys real separation — dbt never
makes a network call, the enrichment is inspectable as a table before it reaches gold, and a failed
LLM run leaves the previous enrichment in place instead of breaking the build.

- **Declared as a `source()`**, not a `ref()` — dbt doesn't build it, Python does. It goes in
  `_sources.yml` beside `raw.breeds`.
- **LEFT JOIN in `dim_breeds`**, never inner: if enrichment hasn't run, or missed a breed, that
  breed still appears with a NULL enrichment column. The bonus must not be able to drop breeds from
  the core deliverable.
- **Tests:** `accepted_values` on the enum (the LLM's output is untrusted input — this is the
  schema/enum validity check), `relationships` back to `dim_breeds`, `unique` on `breed_id`.
- **Alternative rejected:** a dbt Python model calling the LLM inside the build. It couples the
  warehouse build to a network call with a rate limit and a bill, and makes `dbt build`
  non-deterministic. Not worth it for a bonus.
