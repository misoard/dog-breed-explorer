{{ config(severity='warn') }}

-- Life span must be present for >=90% of breeds. Observed null rate: 40/627 = 6.4%.
--
-- Catches life_span degrading -- the field going empty, a notation the parser stops
-- understanding, a source change that nulls it. Every hard invariant stays green while this
-- happens: the rows that DO parse still satisfy min <= max, the PK is fine, nothing errors.
-- The mean-life-span line (dashboard question 2) just quietly rests on less and less data.
--
-- It measures the null rate on dim_breeds' OUTPUT, not on the raw field, so it fires whether
-- the cause is the API or our own parser. assert_metric_parsed catches "a string we didn't
-- understand" per row; this catches the aggregate consequence when that happens at scale.
--
-- WHY warn: the source is allowed to not know a breed's life span. 6.4% is already normal
-- here. The signal is the RATE MOVING, and only a human can say whether it moved for a good
-- reason.
--
-- WORTH KNOWING (DECISIONS.md §0): the nulls are NOT evenly spread -- toy is 29/40 (27.5%
-- missing), giant is 58/58 (0%). This project-wide rate can therefore look healthy while one
-- class is badly hollowed out. The per-class denominators in mart_size_class_summary are what
-- expose that; this test is the coarse net, not the fine one. Stated so nobody mistakes a
-- green here for "the life-span data is fine everywhere".
--
-- Rows returned = WARN. Expected: 0.

with counts as (

    select
        count(*)                                        as total_breeds,
        count(*) filter (where life_span_mid_years is null) as null_breeds
    from {{ ref('dim_breeds') }}

)

select
    null_breeds,
    total_breeds,
    round(100.0 * null_breeds / total_breeds, 2) as null_pct,
    {{ var('max_lifespan_null_pct') }}          as max_allowed_pct
from counts
where 100.0 * null_breeds / total_breeds > {{ var('max_lifespan_null_pct') }}
