-- Grain: size_class (6 rows incl. 'unknown').
--
-- Serves the count bars AND the mean-life-span line AND the numbers table -- one mart per
-- grain. `mart_weight_distribution` was retired into this: two marts keyed on size_class is
-- drift waiting to happen.
--
-- BOTH DENOMINATORS ARE EXPOSED, deliberately: breed_count is every breed in the class;
-- mean_life_span_years averages only those WITH a life span. Those differ a lot and not
-- evenly -- toy is 29 of 40 (27.5% missing), giant is 58 of 58 (0%). So the toy bar rests on
-- 72% of its class and the giant bar on 100%, and nothing on the chart would say so. Exposing
-- both is the difference between a chart and a claim.
--
-- stddev_life_span_years is NOT decoration -- it is the honest half of the headline. The
-- spread GROWS with size (0.68 small -> 1.54 giant: giant breeds are shorter-lived AND less
-- predictable), and the toy->giant gap of 2.7 yr is under 2 sigma of the giant band. The
-- trend is real in the mean and weak per dog. A bare mean line invites the opposite reading,
-- which is the same sin DECISIONS.md §0 refuses on the dual axis.

select
    size_class,

    count(*)                                    as breed_count,
    count(life_span_mid_years)                  as breeds_with_life_span,

    round(avg(life_span_mid_years), 2)          as mean_life_span_years,
    round(median(life_span_mid_years), 2)       as median_life_span_years,
    -- stddev_samp, not _pop: these 627 breeds are a sample of dog breeds, not the population
    round(stddev_samp(life_span_mid_years), 2)  as stddev_life_span_years,
    min(life_span_mid_years)                    as min_life_span_years,
    max(life_span_mid_years)                    as max_life_span_years,

    round(avg(weight_mid_kg), 2)                as mean_weight_kg,
    round(avg(height_mid_cm), 2)                as mean_height_cm

from {{ ref('dim_breeds') }}
group by size_class
