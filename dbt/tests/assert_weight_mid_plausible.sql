-- A dog's midpoint weight must be within the bounds of a dog: ~0.5 kg to ~100 kg.
--
-- SPEC test 6. A MAGNITUDE check, and that is all it is.
--
-- WHAT IT ACTUALLY CATCHES: a unit switch. If metric silently became pounds, the Mastiff
-- goes 88.5 -> 195.1 and trips the ceiling. assert_unit_ratio_plausible catches that at the
-- source by comparing to the imperial twin; this catches it here, from a different
-- direction, on the derived column the dashboard actually buckets. Two independent nets for
-- the same failure is deliberate: units are inferred, not declared, so they get belt AND
-- braces.
--
-- WHAT IT DOES *NOT* CATCH -- worth writing down, because I claimed otherwise and was wrong:
--   "3.5 kg (7.7 lb)"  -> 3.5/7.7 -> mid 5.6   comfortably inside [0.5, 100]. NOT caught.
--   "2 years 6 months" -> that is a LIFE SPAN. This test reads weight_mid_kg and never
--                        looks at it. NOT caught, not even close.
-- Compound/mixed-unit strings are assert_metric_shape_known's job (verified: both fail the
-- shape match). A magnitude check only sees errors big enough to leave the range -- which is
-- exactly why the shape check has to exist separately, and why "the range check will catch
-- it" is a comfortable lie.
--
-- Bounds from the real data (verified): min 1.0 kg (Chihuahua), max 88.5 kg (Mastiff).
-- 0.5-100 leaves room for a genuinely new tiny or giant breed without going so wide it
-- stops catching anything.
--
-- Rows returned = FAIL. Expected: 0.

select
    breed_id,
    breed_name,
    weight_raw,
    weight_min_kg,
    weight_max_kg,
    weight_mid_kg
from {{ ref('dim_breeds') }}
where weight_mid_kg is not null
  and (weight_mid_kg < 0.5 or weight_mid_kg > 100)
