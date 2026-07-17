-- "We were handed a string and produced no number" = we did not understand it.
--
-- SUPERSEDES assert_no_unknown_sentinel (SPEC test 5), which only looked for the literal
-- 'unknown'. This is the general form, so it catches 'unknown', 'N/A', 'varies', '?', and
-- whatever the API invents next — the whole class rather than the one instance profiling
-- happened to find. A sentinel that reaches here un-nulled poisons the numeric parse
-- silently: the breed just quietly loses its weight.
--
-- The *_raw columns are the strings the parser was actually given (trimmed, lowercased,
-- known sentinels already nulled). So a non-null raw with a null number means the parser
-- was handed something real and came back empty-handed.
--
-- EXPECTED RED before the fix: 2 rows (Langqing 518, Mongrel 536 — weight.metric =
-- 'unknown'), because the naive model doesn't null the sentinel. Green once
-- nullif(lower(trim(...)), 'unknown') lands.
-- Rows returned = FAIL. Expected after fix: 0.

select breed_id, breed_name, 'weight' as metric, weight_raw as raw_value
from {{ ref('stg_breeds') }}
where weight_raw is not null and weight_min_kg is null

union all

select breed_id, breed_name, 'height' as metric, height_raw as raw_value
from {{ ref('stg_breeds') }}
where height_raw is not null and height_min_cm is null

union all

select breed_id, breed_name, 'life_span' as metric, life_span_raw as raw_value
from {{ ref('stg_breeds') }}
where life_span_raw is not null and life_span_min_years is null
