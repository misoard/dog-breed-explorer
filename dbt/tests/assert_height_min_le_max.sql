-- Same invariant as weight, for height.
--
-- NOT in SPEC's test-file list, but DECISIONS.md §3 says "life_span_min <= life_span_max
-- (and the same for weight/height)". Height is parsed by the identical code path, so
-- leaving it untested would mean the parser is only half-covered. One file per metric so
-- a failure names the metric without needing to read the query.
-- Rows returned = FAIL. Expected: 0.

select
    breed_id,
    breed_name,
    height_raw,
    height_min_cm,
    height_max_cm
from {{ ref('stg_breeds') }}
where height_min_cm > height_max_cm
