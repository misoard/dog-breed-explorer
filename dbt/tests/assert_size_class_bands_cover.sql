-- The seed's bands must be contiguous and non-overlapping: every band's max_kg must equal
-- the next band's min_kg, and every band must have min < max.
--
-- WHY THE SEED GETS TESTED LIKE DATA: because it IS data. The boundaries live here and
-- nowhere else, which is the whole point -- but that also means a typo here silently
-- mis-buckets breeds with nothing else to catch it:
--   a GAP    (…12,24 / 25,45…)  -> a breed at 24.5 kg matches NO band -> silently 'unknown'
--   an OVERLAP (…12,26 / 25,45…) -> a breed at 25.5 kg matches TWO bands -> the join FANS OUT
--                                   and that breed is counted twice in every size aggregate
-- Neither raises an error. Both look plausible on a chart. This is the only thing standing
-- between a one-character edit and a quietly wrong dashboard.
--
-- assert_no_breed_unbanded catches the gap case from the other side (a real weight that
-- finds no band); unique(dim_breeds.breed_id) catches the overlap. This test catches both
-- at the source, where the fix actually is.
--
-- Rows returned = FAIL. Expected: 0.

with bands as (

    select
        label,
        min_kg,
        max_kg,
        lead(label)  over (order by min_kg) as next_label,
        lead(min_kg) over (order by min_kg) as next_min_kg
    from {{ ref('size_class_bands') }}

)

-- a band that is inverted or empty
select
    label,
    min_kg,
    max_kg,
    'min_kg >= max_kg — band is inverted or empty' as problem
from bands
where min_kg >= max_kg

union all

-- a gap or an overlap between consecutive bands
select
    label,
    min_kg,
    max_kg,
    'max_kg (' || max_kg || ') != next band ' || next_label || ' min_kg (' || next_min_kg || ')' as problem
from bands
where next_min_kg is not null
  and max_kg != next_min_kg
