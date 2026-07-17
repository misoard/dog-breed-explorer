-- Silver bridge: one row per (breed, normalised tag). 627 breeds -> ~3,539 rows.
--
-- The comma-separated string turned into something queryable. "Confident, alert, playful"
-- in a single cell cannot be grouped, counted or joined; `LIKE '%playful%'` is a full scan
-- that also matches the wrong rows. The bridge is the standard star-schema many-to-many.
--
-- The naive first pass omitted lower() and went RED on 627 rows before this landed.

with tags as (

    -- unnest ONCE, in its own CTE: two unnest() calls in one select list depend on DuckDB
    -- zipping them rather than crossing them, which is subtle enough to not want to rely on.
    select
        breed_id,
        trim(unnest(string_split(temperament_raw, ','))) as tag
    from {{ ref('stg_breeds') }}
    where temperament_raw is not null

)

-- DISTINCT: absorb a repeated tag rather than fail the daily build over one breed.
-- Folding the casing can CREATE a duplicate that isn't in the source ("Loyal, loyal" ->
-- 'loyal', 'loyal'), so the risk is real and it's ours, not the API's.
--
-- Absorbing silently would be the wrong half of the trade -- so the signal is kept, moved,
-- and softened: assert_source_tag_not_duplicated (WARN) re-derives the split from
-- stg_breeds independently, so this DISTINCT cannot hide a source change from it. Correct
-- numbers AND a visible signal AND a green build.
--
-- Severity moved error -> warn deliberately: once DISTINCT guarantees the grain, a repeated
-- tag is no longer broken data in the warehouse -- it's the source doing something new.
-- That's drift, and DECISIONS.md §3 says drift warns, it doesn't fail the build.
-- assert_tag_unique_per_breed stays an ERROR on this model's OUTPUT, guarding the grain
-- itself against anyone deleting this line.
select distinct
    breed_id,

    -- THE FIX, and the whole reason normalisation lives in silver rather than in whatever
    -- groups on it later: the source ships the same tag in two casings ("Confident" on the
    -- Affenpinscher, "confident" on the Afghan Hound). 66 distinct raw tags -> 46 folded.
    -- Skip this and `GROUP BY temperament` splits 536 intelligent breeds across two rows,
    -- neither of which is the answer, both of which look plausible on a chart.
    lower(tag) as temperament,

    -- Presentation only — NEVER group on this. DuckDB has no initcap(), and sentence case
    -- is the right shape anyway for multi-word tags: "eager to please" -> "Eager to please",
    -- not "Eager To Please".
    upper(substr(lower(tag), 1, 1)) || substr(lower(tag), 2) as temperament_display

from tags

-- Verified: 0 empty tags today (no trailing commas in the source). Kept as a guard because
-- one stray "Playful," would otherwise inject an empty-string tag into every aggregate.
where tag <> ''

  -- THE TEMPERAMENT SENTINEL. This is not a tag, it is the API saying "not applicable" --
  -- and the evidence is on the row itself: breed 536 is "Mongrel", a MIXED breed, whose
  -- weight.metric is the literal string 'unknown' (which we null six lines up in
  -- stg_breeds). Same breed, same meaning, two different spellings of "we don't know".
  -- Treating one as a sentinel and shipping the other as a temperament would be
  -- inconsistent -- so Mongrel now has no weight AND no tags, which is the truth.
  --
  -- Excluded by LITERAL, exactly like 'unknown': only the ONE instance profiling actually
  -- found. NOT "anything over 3 words" -- that would make assert_tag_not_freetext vacuous,
  -- unable to ever fire. A NEW sentence-tag must reach the test so a human sees it. The
  -- test then reads 0 and any non-zero is a real signal, instead of a permanent WARN 1 that
  -- trains everyone to skim past warnings (and past the four warns that matter).
  -- lower(tag), not tag: at this point `tag` is still the raw trimmed string ("Variable
  -- depending on...", capital V) -- the fold happens in the select list above. Comparing the
  -- unfolded value against a lowercase literal is a silent no-op, which is exactly what this
  -- filter was on its first pass. assert_tag_not_freetext staying at WARN 1 is what caught it.
  and lower(tag) <> 'variable depending on ancestry and individual traits'

-- NO `distinct` — deliberate. Verified: no breed repeats a tag, so DISTINCT would be
-- vacuous today AND would make assert_tag_unique_per_breed unable to ever fail. A future
-- "Loyal, loyal" must reach the test so a human sees it. Same rule as nulling only the
-- KNOWN sentinel in stg_breeds: never paper over the class you claim to detect.
