-- Silver. One row per breed, parsed and typed, deduped. Faithful to the source: no
-- size_class, no midpoints, no business rules -- those are gold's (dim_breeds).
--
-- Two defects were left in deliberately on the first pass so the contract could prove it
-- detects them, and both went red on real data before this fix landed:
--   assert_metric_parsed        FAIL 4  -> Langqing/Mongrel, weight AND height = 'unknown'
--   unique(stg_breeds.breed_name) FAIL 1 -> Caucasian Shepherd Dog x2 (ids 70, 269)
-- unique(breed_id) passed throughout -- it cannot see that duplicate, which is exactly why
-- the name test exists.

{% set num = '[0-9]+(\\.[0-9]+)?' %}

with latest as (

    -- Raw accumulates one partition per run_date (locally; in CI there's only ever one).
    -- Without this filter every downstream count doubles on day two. See DECISIONS.md §1.
    select *
    from {{ source('raw', 'breeds') }}
    where run_date = (select max(run_date) from {{ source('raw', 'breeds') }})

), cleaned as (

    select
        -- The API sends id as a STRING ("id":"1"). The cast is a staging decision;
        -- raw keeps the payload verbatim so the evidence survives.
        cast(payload->>'id' as integer) as breed_id,
        trim(payload->>'name')          as breed_name,

        -- FIX #1: null the sentinel BEFORE any numeric work, or 'unknown' silently
        -- poisons the parse. Note what is deliberately NOT done here: this nulls only the
        -- ONE sentinel profiling actually found. It does not null "anything that yields no
        -- numbers" -- that would make assert_metric_parsed vacuous, unable to ever fail.
        -- A new sentinel ('N/A', 'varies') must survive to here so the test can catch it.
        nullif(lower(trim(payload->'weight'->>'metric')), 'unknown') as weight_raw,
        nullif(lower(trim(payload->'height'->>'metric')), 'unknown') as height_raw,
        nullif(trim(payload->>'life_span'), '')                      as life_span_raw,

        nullif(trim(payload->>'breed_group'), '')  as breed_group,
        nullif(trim(payload->>'origin'), '')       as origin,
        nullif(trim(payload->>'country_code'), '') as country_code,
        nullif(trim(payload->>'description'), '')  as description,
        nullif(trim(payload->>'temperament'), '')  as temperament_raw,
        payload->'image'->>'url'                   as image_url,

        -- Dedupe tiebreak only. Every breed scores >= 2 because bred_for and perfect_for
        -- are 100% null across the whole source (profiling) -- which is exactly why the
        -- Caucasian pair ties at 2 and breed_id is what actually decides.
        (   case when trim(coalesce(payload->>'description', ''))        = '' then 1 else 0 end
          + case when trim(coalesce(payload->>'history', ''))            = '' then 1 else 0 end
          + case when trim(coalesce(payload->>'origin', ''))             = '' then 1 else 0 end
          + case when trim(coalesce(payload->>'country_code', ''))       = '' then 1 else 0 end
          + case when trim(coalesce(payload->>'breed_group', ''))        = '' then 1 else 0 end
          + case when trim(coalesce(payload->>'temperament', ''))        = '' then 1 else 0 end
          + case when trim(coalesce(payload->>'life_span', ''))          = '' then 1 else 0 end
          + case when trim(coalesce(payload->>'bred_for', ''))           = '' then 1 else 0 end
          + case when trim(coalesce(payload->>'reference_image_id', '')) = '' then 1 else 0 end
          + case when trim(coalesce(payload->'weight'->>'metric', ''))   = '' then 1 else 0 end
          + case when trim(coalesce(payload->'height'->>'metric', ''))   = '' then 1 else 0 end
        ) as n_missing_fields,

        loaded_at
    from latest

), extracted as (

    -- THE PARSER. Pull EVERY number out of the string, once, into a list. Shape-blind on
    -- purpose: "3.2-4.5" -> [3.2, 4.5] and "male: 50-77; female: 41-64" -> [50,77,41,64]
    -- need no branching, because the regex only ever sees numbers. Its ceiling is that a
    -- regex sees numbers, not meaning -- which is assert_metric_shape_known's whole job.
    select
        *,
        list_transform(regexp_extract_all(weight_raw,    '{{ num }}'), x -> cast(x as double)) as weight_nums,
        list_transform(regexp_extract_all(height_raw,    '{{ num }}'), x -> cast(x as double)) as height_nums,
        list_transform(regexp_extract_all(life_span_raw, '{{ num }}'), x -> cast(x as double)) as life_span_nums
    from cleaned

)

select
    breed_id,
    breed_name,

    weight_raw,
    height_raw,
    life_span_raw,

    -- min/max off the extracted list = the whole-breed envelope across sexes.
    -- list_min([]) is NULL, so an unparseable string degrades to NULL instead of crashing.
    list_min(weight_nums)                     as weight_min_kg,
    list_max(weight_nums)                     as weight_max_kg,
    list_min(height_nums)                     as height_min_cm,
    list_max(height_nums)                     as height_max_cm,
    cast(list_min(life_span_nums) as integer) as life_span_min_years,
    cast(list_max(life_span_nums) as integer) as life_span_max_years,

    breed_group,
    origin,
    country_code,
    description,
    temperament_raw,
    image_url,
    n_missing_fields,
    loaded_at

from extracted

-- FIX #2: dedupe. "Caucasian Shepherd Dog" is one breed on two ids (70 and 269) -- a
-- data-quality artifact, not two breeds. A user browsing an explorer must not see it twice.
--
-- Partition by NAME, not id: the ids are distinct, which is precisely why unique(breed_id)
-- is blind to this and unique(breed_name) is the test that catches it.
--
-- The ordering is the decision:
--   n_missing_fields -> keep the more complete row.  Verified: it does NOT decide this
--                       case. Both rows have exactly 2 empty fields, so they TIE.
--   breed_id         -> the tiebreak that actually resolves it. Lower id wins -> 70.
-- This must stay deterministic: the two rows carry DIFFERENT temperaments (70 has 'alert',
-- 269 has 'loyal'), so a non-deterministic pick would silently change the bridge -- and
-- mart_size_class_temperaments with it -- between runs.
qualify row_number() over (
    partition by breed_name
    order by n_missing_fields, breed_id
) = 1
