{{ config(severity='warn') }}

-- A temperament is a TAG, not a sentence. Flag anything over ~3 words.
--
-- Profiling found this literal tag in the source:
--     "variable depending on ancestry and individual traits"   (1 breed)
-- That is free text leaking into what is supposed to be a controlled vocabulary. It is not
-- wrong data exactly -- it parses, it's non-null, it's unique per breed -- it's just not a
-- temperament, and it would sit in the dashboard's tag list looking absurd.
--
-- Catches the CLASS, not that one instance: any future sentence-as-tag trips it too.
--
-- WHY warn: the source is entitled to its own vocabulary and a long tag is not broken data.
-- A human should look and decide whether to filter it, not have the build fail. Follows
-- SPEC's rule: invariants error, "this looks off" warns.
--
-- EXPECTED: 0 rows. The one known instance is excluded in stg_breed_temperaments as a
-- SENTINEL, not hidden: breed 536 is "Mongrel", a mixed breed whose weight.metric is the
-- literal 'unknown'. Same row, same meaning -- so the sentence gets the same treatment the
-- string does, and Mongrel carries no temperament rather than a fake one.
--
-- That baselining is what makes this test WORK. Left un-excluded it would WARN 1 forever,
-- and its only signal would be 1 -> 2 -- a change nobody notices. A warning that never
-- clears is wallpaper: it trains people to skim past warnings, including the four that
-- matter (shape_known + the three distributional guards). At 0, any non-zero is real.
--
-- Rows returned = WARN. Expected: 0.

select
    breed_id,
    temperament,
    length(temperament) - length(replace(temperament, ' ', '')) + 1 as n_words
from {{ ref('stg_breed_temperaments') }}
where length(temperament) - length(replace(temperament, ' ', '')) + 1 > 3
