-- A breed with a REAL weight must always find a band.
--
-- Catches a seed whose ranges don't reach: a gap, or a `giant` ceiling too low. Symptom
-- without this test: the breed silently lands in 'unknown', the weight-distribution chart
-- quietly loses it, and nothing errors -- the exact "valid, passing, and visible only to
-- whoever notices half the chart is empty" failure the guards exist for.
--
-- The null case is EXCLUDED on purpose: weight_mid_kg IS NULL -> 'unknown' is the DESIGNED
-- path (the 2 sentinel breeds, Langqing and Mongrel). That branch is guarded instead by
-- assert_unknown_bucket_small (warn, <=1%) in M4. This test only asks: "we had a number --
-- did the seed cover it?"
--
-- Rows returned = FAIL. Expected: 0.

select
    breed_id,
    breed_name,
    weight_mid_kg,
    size_class
from {{ ref('dim_breeds') }}
where weight_mid_kg is not null
  and size_class = 'unknown'
