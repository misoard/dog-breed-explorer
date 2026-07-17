-- Gold. One row per breed: staging's facts + the derived columns.
--
-- The silver/gold line: staging makes the data CORRECT (parse, type, dedupe). THIS is where
-- the opinions live -- that 25.0 kg is `large` and not `medium` is a judgment call, not a
-- fact about the API. If Heyra disagreed with the bands, only this file changes; if the API
-- changed its weight format, only staging does.
--
-- The naive first pass used `<= b.max_kg` -- the natural, inclusive reading of a range -- and
-- did not build at all: "More than one row returned by a subquery used as an expression".
-- 31 breeds sit EXACTLY on a boundary, so each matched TWO bands.

with breeds as (

    select * from {{ ref('stg_breeds') }}

), derived as (

    select
        *,
        -- Explicit derived columns, NOT artifacts of the parser's regex. Keeping min/max/mid
        -- as separate typed columns is what makes the midpoint RULE visible and testable --
        -- and it matters: envelope-midpoint vs mean-of-per-sex-midpoints diverge for ~65% of
        -- sex-specific breeds, enough to flip a breed's class near a boundary.
        (weight_min_kg + weight_max_kg) / 2.0                as weight_mid_kg,
        (height_min_cm + height_max_cm) / 2.0                as height_mid_cm,

        -- SPEC puts life_span_mid_years in STAGING and the other two midpoints in GOLD.
        -- That's inconsistent with its own silver/gold line: a midpoint is a derived
        -- opinion ((min+max)/2 is a RULE, not a fact the API stated), so all three belong
        -- on the same side. Kept here with its siblings; SPEC's stg column list corrected.
        (life_span_min_years + life_span_max_years) / 2.0    as life_span_mid_years,
        life_span_max_years - life_span_min_years            as life_span_range_years
    from breeds

)

select
    d.*,

    -- FIX #2: the null branch comes FIRST, before the join is even attempted.
    -- Not a fallthrough -- a deliberate label. It has to be explicit because `NULL >= 0` is
    -- NULL, not false: a null weight would match no band and the subquery would return NULL
    -- silently. 'unknown' being a VALUE (never a NULL) is what lets not_null(size_class)
    -- guard this branch at all. Affects exactly 2 breeds: Langqing (518), Mongrel (536).
    case
        when d.weight_mid_kg is null then 'unknown'
        else (
            -- FIX #1: HALF-OPEN [min_kg, max_kg) -- lower inclusive, upper EXCLUSIVE.
            -- `>=` and `<`, never `<=`. 31 breeds (5%) sit exactly on a boundary, 23 of them
            -- on 25 kg, so the closed side is load-bearing: 45.0 is giant, 25.0 is large,
            -- 5.0 is small. pd.cut defaults to the OPPOSITE convention (use right=False).
            --
            -- A scalar subquery, not a LEFT JOIN, on purpose: if the seed ever overlaps, this
            -- form CANNOT return two rows -- it errors at build time. A join would silently
            -- duplicate the breed and leave unique(breed_id) as the only thing between that
            -- and a double-counted chart. Verified: `<=` here didn't fail a test, it refused
            -- to build.
            select b.label
            from {{ ref('size_class_bands') }} b
            where d.weight_mid_kg >= b.min_kg
              and d.weight_mid_kg <  b.max_kg
        )
    end as size_class

from derived d
