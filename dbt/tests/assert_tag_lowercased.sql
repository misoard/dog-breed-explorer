-- Every tag must already be folded to lowercase by the time it leaves silver.
--
-- WHY THIS IS THE LOAD-BEARING TEST OF THE BRIDGE: the source ships the SAME tag in two
-- casings -- "Confident" on the Affenpinscher, "confident" on the Afghan Hound. Measured
-- across the real data: 66 distinct raw tags collapse to 46 once folded, and the top
-- offenders are the most common tags in the set:
--     intelligent  -> Intelligent | intelligent   (536 rows)
--     loyal        -> loyal | Loyal               (451 rows)
--     alert        -> alert | Alert               (376 rows)
--
-- Without lower(), `GROUP BY temperament` returns "Intelligent" AND "intelligent" as two
-- separate rows, splitting 536 breeds into two smaller numbers. NEITHER is the answer, and
-- both look perfectly plausible on a chart. That is the failure this prevents: not a crash,
-- a quietly wrong bar.
--
-- EXPECTED RED before the fix: 627 rows (every tag row whose source casing isn't already
-- lowercase). Green once lower() lands.
-- Rows returned = FAIL. Expected after fix: 0.

select
    breed_id,
    temperament
from {{ ref('stg_breed_temperaments') }}
where temperament <> lower(temperament)
   or temperament <> trim(temperament)
