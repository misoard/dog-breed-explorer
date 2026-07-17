-- Grain: breed. One row per breed, ready to scatter.
--
-- Kept even though mart_size_class_summary already carries the means, because the means HIDE
-- the spread: overall correlation is -0.670, but WITHIN any single band it's only ~-0.1 to
-- -0.4. The honest reading -- "knowing a dog's size class tells you a lot; knowing one giant
-- outweighs another tells you little" -- is only visible per breed. A bar chart alone
-- oversells -0.670.
--
-- NO height_mid_cm. Its only readers were the height-vs-weight view and mart_size_scaling_fit,
-- both cut (an isometry exponent is not a fact about a dog -- DECISIONS.md §0). Height remains
-- a breed fact in dim_breeds and as mean_height_cm in the summary; it just has no reader here,
-- and a column with no consumer is untested surface that rots.
--
-- Rows with a null weight or life span are KEPT, not filtered: the dashboard needs to know
-- what it's dropping, and mart_data_coverage states it. Filtering here would hide 42 breeds
-- from a mart whose whole job is per-breed honesty.

select
    breed_id,
    breed_name,
    size_class,
    weight_mid_kg,
    life_span_mid_years
from {{ ref('dim_breeds') }}
