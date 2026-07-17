-- A dog breed's midpoint life span must be biologically possible: ~4 to ~25 years.
--
-- The life-span twin of assert_weight_mid_plausible, and it has the same single job: catch a
-- UNIT error. The realistic one here is the source switching to MONTHS -- "120-180" instead
-- of "10-15" -> midpoint 150 -> caught, loudly. Every other test would stay green: min <= max
-- holds, a number was produced, the shape "X-Y" is one we know. Only magnitude sees it.
--
-- DECISIONS.md §3 specified "range checks on weight/life span"; SPEC's test list only ever
-- carried the weight half, so this was a documented test that never got built. Found by
-- asking what actually catches a compound value -- the answer being "not the range check".
--
-- WHAT IT DOES NOT CATCH, stated plainly: "2 years 6 months" -> 2/6 -> midpoint 4.0, which
-- sits inside these bounds. That is assert_metric_shape_known's job (verified: it warns).
-- The bounds are set from biology, NOT fitted to catch one hypothetical string -- tightening
-- them to 5 just to trap that example would be reverse-engineering the test to the answer.
--
-- Bounds vs the real data (verified): observed midpoints run 6.5 (Dogue de Bordeaux, "5-8")
-- to 15.0 (Silken Windhound, "12-18"). [4, 25] leaves genuine headroom for a new breed at
-- either extreme while still catching months-for-years by a factor of 6.
--
-- Rows returned = FAIL. Expected: 0.

select
    breed_id,
    breed_name,
    life_span_raw,
    life_span_min_years,
    life_span_max_years,
    (life_span_min_years + life_span_max_years) / 2.0 as life_span_mid_years
from {{ ref('dim_breeds') }}
where life_span_min_years is not null
  and (
        (life_span_min_years + life_span_max_years) / 2.0 < 4
     or (life_span_min_years + life_span_max_years) / 2.0 > 25
  )
