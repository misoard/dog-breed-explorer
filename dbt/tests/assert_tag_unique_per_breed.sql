-- The bridge's GRAIN: one row per (breed, tag). A breed must not carry the same tag twice.
--
-- LOAD-BEARING, not decoration. A duplicated tag double-counts that breed in
-- mart_size_class_temperaments, inflating pct_of_class -- and nothing else would notice:
-- the counts stay plausible, nothing is null, no type breaks. It is also the upstream
-- assumption mart_temperament_pair_lift would rest on if it's ever built (DECISIONS.md §3).
--
-- Written as a singular test because the grain is a COMBINATION, and dbt's built-in
-- `unique` only covers a single column. dbt_utils.unique_combination_of_columns would do
-- this, but the package isn't worth a dependency for one test.
--
-- THE MODEL NOW USES `DISTINCT`, so this test guards the GRAIN ITSELF rather than the
-- source: it fails if anyone deletes that line, or if a future join/CTE fans the bridge out.
-- It is not vacuous just because it can't fail on today's data -- it is a regression guard
-- on the model's contract, and it's the assumption every temperament aggregate rests on.
--
-- The SOURCE side is covered separately by assert_source_tag_not_duplicated (WARN), which
-- re-derives the split from stg_breeds so the DISTINCT can't hide a source change from it.
-- Two tests, two jobs: this one says "the grain is intact", that one says "the source
-- changed". Absorb the problem, keep the signal.
--
-- Rows returned = FAIL. Expected: 0.

select
    breed_id,
    temperament,
    count(*) as n_rows
from {{ ref('stg_breed_temperaments') }}
group by breed_id, temperament
having count(*) > 1
