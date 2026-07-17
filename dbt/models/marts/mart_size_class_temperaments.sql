-- Grain: (size_class, temperament).
--
-- What makes TEMPERAMENT -- one of the three fields the brief names -- a headline fact rather
-- than a bridge table nobody opens. "Characteristic" means nothing cleverer than MOST
-- FREQUENT WITHIN THE GROUP: a GROUP BY + COUNT over two tables that already exist.
--
-- pct_of_class IS THE POINT. Raw counts favour big classes -- 220 medium breeds out-count 40
-- toy breeds on every tag purely by existing -- so the classes aren't comparable until you
-- normalise within them. "72% of giant breeds are calm" is a fact; "18 giant breeds are calm"
-- is a fact about how many giant breeds there are.
--
-- Note what this deliberately is NOT: no lift, no baseline, no leave-one-out. Dividing by the
-- group size is ARITHMETIC; comparing against a baseline is INFERENCE. That distinction is
-- exactly the line between this mart (ships) and mart_temperament_pair_lift (specified in
-- DECISIONS.md §3, not built) -- descriptive fact -> gold, inferential cleverness -> DECISIONS.
--
-- Both numerator AND denominator are kept, same rule as mart_size_class_summary: a percentage
-- whose denominator you can't see isn't checkable.
--
-- TOP-N IS NOT HERE, on purpose: gold holds every (class, tag) pair and the dashboard takes
-- the top 3-5. Bake the cut in and you can't change it without a rebuild.
--
-- The denominator is breeds_in_class from dim_breeds -- NOT the count of breeds in the bridge.
-- They differ: Mongrel has a size_class but no temperament (its tag is a sentinel). Using the
-- bridge's own population would quietly inflate every percentage in the 'unknown' class.

with class_sizes as (

    select
        size_class,
        count(*) as breeds_in_class
    from {{ ref('dim_breeds') }}
    group by size_class

), tagged as (

    select
        d.size_class,
        t.temperament,
        count(distinct t.breed_id) as breed_count
    from {{ ref('breed_temperaments') }} t
    join {{ ref('dim_breeds') }} d on d.breed_id = t.breed_id
    group by d.size_class, t.temperament

)

select
    t.size_class,
    t.temperament,
    t.breed_count,
    c.breeds_in_class,
    round(100.0 * t.breed_count / c.breeds_in_class, 1) as pct_of_class
from tagged t
join class_sizes c on c.size_class = t.size_class
