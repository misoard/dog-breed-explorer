-- Grain: (metric_a, metric_b) — 3 rows.
--
-- This mart IS the evidence for a modeling decision: the case asks about "size" without
-- defining it, and this is where I define it as WEIGHT. weight~life -0.670 vs height~life
-- -0.502, and because weight and height are 0.860-coupled, height adds almost nothing once
-- weight is in -- its -0.502 is largely borrowed. Stated in DECISIONS.md §0; computed here.
--
-- Computed by dbt at PIPELINE time, never in the dashboard: corr(x, y) is a plain SQL
-- aggregate, so the number quoted in the narrative is built, tested and reproducible rather
-- than a df.corr() recomputed live by the read layer. Same "logic lives in gold" line drawn
-- everywhere else.
--
-- PAIRWISE population, and n_breeds is a column BECAUSE OF IT: a correlation without its
-- population is not a fact. Each row uses every breed where ITS OWN two metrics are non-null
-- -- not only breeds with all three. That choice moves the numbers, so it is stated rather
-- than left implicit:
--     pair                 pairwise (n)      listwise (n=585)
--     weight <-> life      -0.670 (585)      -0.670
--     height <-> life      -0.502 (585)      -0.502
--     height <-> weight     0.860 (625)       0.851
-- The height<->weight row is the one that moves: 40 breeds have a weight and height but no
-- life span, and listwise would throw them away for no reason.

with breeds as (

    select * from {{ ref('dim_breeds') }}

)

select
    'weight_mid_kg' as metric_a,
    'life_span_mid_years' as metric_b,
    round(corr(weight_mid_kg, life_span_mid_years), 3) as correlation,
    count(*) as n_breeds
from breeds
where weight_mid_kg is not null and life_span_mid_years is not null

union all

select
    'height_mid_cm',
    'life_span_mid_years',
    round(corr(height_mid_cm, life_span_mid_years), 3),
    count(*)
from breeds
where height_mid_cm is not null and life_span_mid_years is not null

union all

select
    'height_mid_cm',
    'weight_mid_kg',
    round(corr(height_mid_cm, weight_mid_kg), 3),
    count(*)
from breeds
where height_mid_cm is not null and weight_mid_kg is not null
