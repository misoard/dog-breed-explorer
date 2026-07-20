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

),

freshness as (

    -- "Last refreshed" for the dashboard footer. loaded_at is the wall-clock of the ingestion
    -- that produced the current partition (stg_breeds already filters to the latest run_date),
    -- so max() collapses the one partition to a single timestamp. Read from silver, not raw,
    -- to stay one layer down; it's pipeline metadata, computed in dbt so the app stays thin.
    -- Chose loaded_at (wall-clock) over run_date (the logical partition date) deliberately: on a
    -- nightly-refreshed hosted store it shows real recency and goes visibly stale if the cron
    -- stops -- a viewer-facing freshness signal, complementing the heartbeat that alerts me.
    select max(loaded_at) as last_refreshed_at
    from {{ ref('stg_breeds') }}

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
                        or d.life_span_mid_years is null)                as breeds_excluded_scatter,
    max(f.last_refreshed_at)                                            as last_refreshed_at
from {{ ref('dim_breeds') }} d
cross join tagged_breeds t
cross join freshness f
