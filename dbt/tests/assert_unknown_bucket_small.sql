{{ config(severity='warn') }}

-- The 'unknown' size class must stay under 1% of dim_breeds. Observed: 2/627 = 0.32%.
--
-- THE HIGHEST-VALUE GUARD OF THE THREE, because it defends a CHOSEN DELIVERABLE. If the
-- weight parse degrades -- a new sentinel, a notation change, the field going null -- breeds
-- fall into 'unknown' and the weight-distribution chart (dashboard question 1) is visibly
-- wrong, while EVERY hard test still passes: min <= max holds on the rows that parsed, the PK
-- is unique, nothing is a NULL where a NULL isn't allowed. The pipeline reports success and
-- the dashboard quietly renders a bar chart missing a third of its data.
--
-- That is the failure mode this whole category exists for: data that degrades without
-- breaking any invariant. Valid, passing, and visible only to whoever wonders why a bar looks
-- short.
--
-- WHY warn, not error: 'unknown' growing might be a real regression OR the API legitimately
-- adding breeds whose weight it doesn't know. A human must judge which. Auto-failing the
-- daily build on the second case is worse than surfacing the first loudly.
-- (dbt's warn_if/error_if would give a graduated band -- warn at 1%, error at 25% -- if a
-- catastrophic threshold is ever wanted. Not today: three guards wired properly beat ten
-- half-wired.)
--
-- NOTE (M5): a warn nobody sees is not a signal. This is inert until CI parses
-- run_results.json into ::warning:: annotations. That step is what makes the severity choice
-- mean anything.
--
-- Rows returned = WARN. Expected: 0.

with counts as (

    select
        count(*)                                              as total_breeds,
        count(*) filter (where size_class = 'unknown')        as unknown_breeds
    from {{ ref('dim_breeds') }}

)

select
    unknown_breeds,
    total_breeds,
    round(100.0 * unknown_breeds / total_breeds, 2) as unknown_pct,
    {{ var('max_unknown_size_class_pct') }}        as max_allowed_pct
from counts
where 100.0 * unknown_breeds / total_breeds > {{ var('max_unknown_size_class_pct') }}
