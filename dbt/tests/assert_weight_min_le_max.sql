-- A breed cannot weigh more at its minimum than at its maximum.
--
-- Catches: the envelope collapsed the wrong way round (min/max swapped), or the parser
-- read a sex-specific range as two independent ranges and crossed them.
-- Rows returned = FAIL. Expected: 0.

select
    breed_id,
    breed_name,
    weight_raw,
    weight_min_kg,
    weight_max_kg
from {{ ref('stg_breeds') }}
where weight_min_kg > weight_max_kg
