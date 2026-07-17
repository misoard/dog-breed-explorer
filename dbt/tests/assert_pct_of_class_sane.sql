-- A tag cannot be held by more breeds than exist in the class.
--
-- THE FAN-OUT TRIPWIRE, and the reason it's arithmetic rather than a judgment call:
-- mart_size_class_temperaments joins the bridge to dim_breeds on breed_id. If EITHER side
-- ever carries a duplicate key, the join multiplies rows:
--     bridge: (70,'calm')      dim: 70 -> giant
--                                   70 -> giant     <- dedupe regressed
--     join -> (70,'calm',giant) TWICE -> breed_count = 2 for ONE breed
-- With 58 giants, `calm` could report 59+ and pct_of_class could exceed 100%. Nothing else
-- would notice: no nulls, no type errors, every count still plausible on a chart.
--
-- `breed_count <= breeds_in_class` is impossible to violate unless the join fanned out, which
-- is what makes it a tripwire rather than a heuristic. This is THE realistic bug in a mart
-- built from a bridge, and it's guarded by inequality, not by hoping.
--
-- pct in (0, 100] is the same check restated for the reader: a tag held by zero breeds
-- shouldn't produce a row at all, and >100% is arithmetically impossible.
--
-- Rows returned = FAIL. Expected: 0.

select
    size_class,
    temperament,
    breed_count,
    breeds_in_class,
    pct_of_class
from {{ ref('mart_size_class_temperaments') }}
where breed_count > breeds_in_class
   or pct_of_class <= 0
   or pct_of_class > 100
