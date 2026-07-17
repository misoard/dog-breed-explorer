{{ config(severity='warn') }}

-- THE NOTATION-CHANGE FLAG. The raw string must match one of the three shapes profiling
-- found, each with an optional unit suffix:
--     "3.2-4.5"                     range
--     "50"                          bare value
--     "male: 50-77; female: 41-64"  sex-specific (either sex may be a bare value)
--
-- WHY THIS EXISTS SEPARATELY FROM assert_metric_parsed:
-- the parser extracts EVERY number and takes min/max, which is deliberately shape-blind.
-- That is its strength — "12 years - 13 years" -> 12/13 and "3-5kg" -> 3/5 both work for
-- free (verified). It is also its ceiling: a regex sees numbers, not meaning.
--     "3.5 kg (7.7 lb)"   -> 3.5 / 7.7   mixed units, silently wrong
--     "2 years 6 months"  -> 2 / 6       should be 2.5, silently wrong
-- Both pass every other test: min <= max holds, a number was produced, the PK is fine.
-- Only a SHAPE check catches them, which is why number-checking cannot substitute.
--
-- WHY warn, NOT error: unlike a unit switch (where every number is guaranteed wrong), a
-- new notation MIGHT parse perfectly well. Erroring would block a good run over a
-- cosmetic source change; warning puts a human in front of it before it becomes 2/6.
-- Follows SPEC's rule: invariants error, "the world changed" warns.
-- NOTE (M5): a warn nobody sees is not a signal — CI must surface this via
-- ::warning:: annotations, or the severity choice is theatre.
--
-- Rows returned = WARN. Expected: 0.

{% set num = '[0-9]+(\\.[0-9]+)?' %}
{% set sex_part = '(male|female)\\s*:\\s*' ~ num ~ '(\\s*-\\s*' ~ num ~ ')?' %}
{% set known = '^\\s*(' ~ num ~ '\\s*-\\s*' ~ num          ~ '|'
                        ~ num                              ~ '|'
                        ~ sex_part ~ '(\\s*;\\s*' ~ sex_part ~ ')*'
                ~ ')\\s*[a-z]*\\s*$' %}

select breed_id, breed_name, metric, raw_value
from (
    select breed_id, breed_name, 'weight'    as metric, weight_raw    as raw_value from {{ ref('stg_breeds') }}
    union all
    select breed_id, breed_name, 'height'    as metric, height_raw    as raw_value from {{ ref('stg_breeds') }}
    union all
    select breed_id, breed_name, 'life_span' as metric, life_span_raw as raw_value from {{ ref('stg_breeds') }}
)
where raw_value is not null
  and not regexp_matches(raw_value, '{{ known }}')
