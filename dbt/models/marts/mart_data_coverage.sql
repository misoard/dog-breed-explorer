-- Grain: one row. What every chart silently drops, as a fact the dashboard PRINTS.
--
-- A dashboard that says "627 breeds" above a plot drawn from 585 is quietly lying, and no
-- reader could tell. This is one line of SQL that turns an invisible omission into a stated
-- population.
--
-- And it is NOT cosmetic, because the missing data is NOT evenly spread: toy has 29 of 40
-- breeds with a life span (27.5% missing), giant has 58 of 58 (0%). The toy bar rests on 72%
-- of its class and the giant bar on 100% -- a real bias in the headline chart that nothing
-- else surfaces. (The per-class denominators live in mart_size_class_summary; this is the
-- project-wide headline.)
--
-- breeds_plotted_scatter is the number the scatter actually draws -- it needs BOTH metrics.
-- It should equal n_breeds on mart_metric_correlation's weight<->life row (585): the same
-- population reached two different ways, which makes each a check on the other.

with tagged_breeds as (

    -- Counted from the BRIDGE, not from dim_breeds.temperament_raw -- and the difference is
    -- the whole point of the column. Mongrel's temperament_raw is NOT null: it holds the
    -- sentence "Variable depending on ancestry and individual traits", which staging excludes
    -- as a sentinel. Counting the raw string would report 627 breeds "with a temperament" and
    -- silently miss the one breed that has none -- in the very mart whose job is to stop
    -- exactly that kind of quiet over-count.
    select count(distinct breed_id) as n
    from {{ ref('breed_temperaments') }}

)

select
    count(*)                                                             as total_breeds,
    count(d.weight_mid_kg)                                               as breeds_with_weight,
    count(d.life_span_mid_years)                                         as breeds_with_life_span,
    count(*) filter (where d.weight_mid_kg is not null
                       and d.life_span_mid_years is not null)            as breeds_with_both,
    max(t.n)                                                             as breeds_with_temperament,
    count(*) filter (where d.weight_mid_kg is not null
                       and d.life_span_mid_years is not null)            as breeds_plotted_scatter,
    count(*) filter (where d.weight_mid_kg is null
                        or d.life_span_mid_years is null)                as breeds_excluded_scatter
from {{ ref('dim_breeds') }} d
cross join tagged_breeds t
