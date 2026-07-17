-- Gold bridge: one row per (breed, normalised tag). THE brief's "turn the comma-separated
-- temperament list into something queryable" deliverable, in its finished form.
--
-- Thin on purpose, and worth defending rather than hiding: it is stg_breed_temperaments
-- materialized and contracted. Three things it buys that the silver view cannot:
--   1. TABLE, not view -- read repeatedly by humans and by mart_size_class_temperaments;
--      built once instead of re-splitting 627 comma strings on every query.
--   2. CONTRACT -- and a contract on a VIEW is silently ignored (verified: PASS, no warning),
--      so the public interface has to be a table or the promise is theatre.
--   3. LAYER -- silver is internal by convention; gold is what's exposed. Pointing an analyst
--      at main_staging would leak the boundary.
--
-- The parsing, folding, DISTINCT and sentinel exclusion all happened upstream in silver.
-- Nothing is re-derived here: one place to change, one place to test.

select
    breed_id,
    temperament,
    temperament_display
from {{ ref('stg_breed_temperaments') }}
