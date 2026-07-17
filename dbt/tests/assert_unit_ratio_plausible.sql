-- THE UNIT TRIPWIRE. The API declares its units NOWHERE. "metric = kg/cm" is an
-- INFERENCE I made by dividing imperial by metric and finding 2.205 (lb/kg) and 2.54
-- (in/cm). This test is the only thing standing between that inference and a silent
-- source change.
--
-- The failure it guards is the nastiest kind: if metric quietly became pounds, every
-- number stays valid — min <= max holds, the PK is unique, nothing is null, every other
-- test goes green — and the entire dashboard is wrong by 2.2x. Nobody would notice
-- except by wondering why Chihuahuas weigh 5 kg.
--
-- READS THE SOURCE, AND PARSES INDEPENDENTLY, ON PURPOSE:
-- it does NOT ref() stg_breeds and does NOT reuse the model's parser. A test that shares
-- the implementation's code cannot catch a bug in that code — it would agree with the
-- parser by construction. This takes only the FIRST number of each string (simpler and
-- sufficient for a ratio), so it is a genuine second opinion.
--
-- Median, not mean: one bad row must not drag the verdict.
-- severity: error (default) — a unit switch is not drift, it is broken data.
--
-- Observed: weight 2.200, height 2.542. Rows returned = FAIL. Expected: 0.

-- THE RATIO DIRECTIONS DIFFER, AND THAT IS NOT A TYPO:
--   weight: imperial is the BIGGER number (7 lb vs 3.2 kg)  -> imperial/metric = 2.205 lb/kg
--   height: metric   is the BIGGER number (23 cm vs 9 in)   -> metric/imperial = 2.54  cm/in
-- Asserting both as "imperial:metric near 2.205 / 2.54" (as SPEC originally said) is
-- arithmetically impossible: height in that direction is 1/2.54 = 0.394. This test caught
-- that on its first run against real data -- the spec was wrong, not the parser.

{% set num = '[0-9]+(\\.[0-9]+)?' %}
{% set weight_lo, weight_hi = 2.095, 2.315 %}   {# 2.205 lb/kg  +/-5%, imperial/metric #}
{% set height_lo, height_hi = 2.413, 2.667 %}   {# 2.54  cm/in  +/-5%, metric/imperial #}

with latest as (

    select *
    from {{ source('raw', 'breeds') }}
    where run_date = (select max(run_date) from {{ source('raw', 'breeds') }})

), pairs as (

    select
        'weight' as metric,
        try_cast(regexp_extract(payload->'weight'->>'imperial', '{{ num }}') as double) as imperial_first,
        try_cast(regexp_extract(payload->'weight'->>'metric',   '{{ num }}') as double) as metric_first
    from latest

    union all

    select
        'height' as metric,
        try_cast(regexp_extract(payload->'height'->>'imperial', '{{ num }}') as double) as imperial_first,
        try_cast(regexp_extract(payload->'height'->>'metric',   '{{ num }}') as double) as metric_first
    from latest

), ratios as (

    select
        metric,
        -- each metric measured in the direction where the ratio is > 1, so the expected
        -- constant is the familiar unit conversion rather than its reciprocal
        median(case when metric = 'weight' then imperial_first / metric_first
                    else                        metric_first   / imperial_first end) as median_ratio,
        count(*) as n_breeds
    from pairs
    where imperial_first is not null
      and metric_first is not null
      and metric_first   > 0
      and imperial_first > 0
    group by metric

)

select metric, median_ratio, n_breeds
from ratios
where (metric = 'weight' and (median_ratio < {{ weight_lo }} or median_ratio > {{ weight_hi }}))
   or (metric = 'height' and (median_ratio < {{ height_lo }} or median_ratio > {{ height_hi }}))
