-- A breed cannot live fewer years at its maximum than at its minimum.
--
-- Catches a parsing bug on "10-12": the classic failure is splitting on the wrong
-- separator or reversing the parts.
-- Rows returned = FAIL. Expected: 0.

select
    breed_id,
    breed_name,
    life_span_raw,
    life_span_min_years,
    life_span_max_years
from {{ ref('stg_breeds') }}
where life_span_min_years > life_span_max_years
