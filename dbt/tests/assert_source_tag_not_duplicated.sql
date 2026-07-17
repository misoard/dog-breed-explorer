{{ config(severity='warn') }}

-- Did the SOURCE ship a breed the same tag twice (once case-folded)?
--
-- THE POINT OF THIS TEST: stg_breed_temperaments uses `select distinct`, so a repeated tag
-- is absorbed -- the numbers stay correct and one odd breed never fails the daily build.
-- But absorbing SILENTLY would mean the source could change and nobody would ever know.
-- This is the other half of that trade: absorb the problem, keep the signal.
--
-- IT RE-DERIVES THE SPLIT FROM stg_breeds RATHER THAN READING THE BRIDGE, on purpose.
-- Reading stg_breed_temperaments would be pointless: the DISTINCT has already removed the
-- thing we're looking for, so the test would be structurally incapable of ever firing.
-- Same reasoning as assert_unit_ratio_plausible parsing independently instead of reusing
-- the model's parser: a test downstream of the fix cannot see what the fix hid.
--
-- WHY warn, not error: once DISTINCT guarantees the grain, a duplicated source tag is not
-- broken data in the warehouse -- it is the source doing something new. That is drift, and
-- drift warns (DECISIONS.md §3). The grain itself is still guarded at ERROR by
-- assert_tag_unique_per_breed on the model's output.
--
-- Note the duplicate need not exist in the source verbatim: OUR case-folding can create it
-- ("Loyal, loyal" -> 'loyal','loyal'), which is why this looks at the folded value.
--
-- Rows returned = WARN. Expected: 0 (verified: no breed repeats a tag today).

with source_tags as (

    select
        breed_id,
        lower(trim(unnest(string_split(temperament_raw, ',')))) as tag
    from {{ ref('stg_breeds') }}
    where temperament_raw is not null

)

select
    breed_id,
    tag,
    count(*) as n_occurrences
from source_tags
where tag <> ''
group by breed_id, tag
having count(*) > 1
