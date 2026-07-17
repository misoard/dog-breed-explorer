-- Every breed in raw's latest partition reaches gold, except the ones the dedupe
-- deliberately collapsed. EXACT arithmetic, no tolerance, no constant to maintain.
--
-- The dedupe is BY NAME (`partition by breed_name`), so the reconciliation is simply:
--     dim_breeds rows == distinct breed NAMES in raw's latest partition
-- 628 raw rows -> 627 distinct names -> 627 in dim_breeds. Any other number means the
-- pipeline lost a breed somewhere between raw and gold, and nothing else would notice:
-- unique() and not_null() pass happily on fewer rows, and every count downstream stays
-- self-consistent. mart_data_coverage would confidently report the wrong total.
--
-- REPLACES assert_row_count_stable (627 +/-5%, warn), which was worse at the job I
-- justified it with. Measured: the +/-5% band was BLIND to losing 1, 5 or 31 breeds -- it
-- only woke at 32. This fires on one.
--
-- It also removes that test's self-destruction: `expected_breed_count` was a hand-maintained
-- constant, so an API that grew to 667 would WARN every single run until someone edited it
-- -- a permanent warning, i.e. wallpaper, i.e. the exact failure mode we'd removed from
-- assert_tag_not_freetext three files earlier. This has no constant, so it cannot rot.
--
-- severity: ERROR (default), and that's a change of kind, not just degree: losing a breed
-- between raw and gold is a BUG in our code, not drift in the world. Drift warns; bugs fail.
--
-- WHAT IT DELIBERATELY DOES NOT DO: tell you the SOURCE changed size. It will confirm
-- 667 == 667 and stay silent. That is correct and out of scope by construction -- "did the
-- count change since YESTERDAY?" needs state, and the pipeline is deliberately stateless
-- (DECISIONS.md §1). The only stateless substitute is a constant, which rots. The
-- source-size signal survives maintenance-free in two places instead: ingest.py logs the
-- fetched count against its floor, and mart_data_coverage.total_breeds is printed on the
-- dashboard beside every chart.
--
-- Rows returned = FAIL. Expected: 0.

with raw_latest as (

    -- distinct NAMES, not rows: this is exactly what the dedupe is contracted to leave
    select count(distinct payload->>'name') as expected_breeds
    from {{ source('raw', 'breeds') }}
    where run_date = (select max(run_date) from {{ source('raw', 'breeds') }})

), gold as (

    select count(*) as actual_breeds
    from {{ ref('dim_breeds') }}

)

-- cross join of two single-row CTEs -> one row carrying both counts, so they can be compared
select
    expected_breeds,
    actual_breeds,
    actual_breeds - expected_breeds as lost   -- signed: negative = dropped, positive = fanned out
from raw_latest, gold
where actual_breeds != expected_breeds
