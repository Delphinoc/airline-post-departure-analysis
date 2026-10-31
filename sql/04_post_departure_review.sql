-- 04_post_departure_review.sql
-- Post-departure review: compare each route's actual monthly load factor with what we
-- would have expected, given (a) how that route normally performs and (b) seasonality.
--
-- expected_lf(route, m) = route baseline from the OTHER months (leave-one-out, de-seasonalised)
--                         x carrier seasonal index for month m
-- variance_pp           = actual_lf - expected_lf, in percentage points

-- 1. Carrier-route-month facts (sums across aircraft types)
CREATE OR REPLACE TABLE route_month AS
SELECT carrier, carrier_name, route, origin, dest, month,
       SUM(dep_scheduled) AS dep_scheduled,
       SUM(dep_performed) AS dep_performed,
       SUM(seats)         AS seats,
       SUM(passengers)    AS passengers,
       SUM(passengers) / SUM(seats) AS actual_lf
FROM clean_segments
WHERE seats > 0 AND origin <> dest
GROUP BY ALL;

-- 2. Materiality: routes flown every month in the data, at least 60 departures (~2 a day) each month
CREATE OR REPLACE TABLE core_routes AS
SELECT carrier, route
FROM route_month
GROUP BY 1, 2
HAVING COUNT(DISTINCT month) = (SELECT COUNT(DISTINCT month) FROM route_month)
   AND MIN(dep_performed) >= 60;

-- 3. Carrier seasonal index: carrier network LF in month m / carrier LF across all months
CREATE OR REPLACE TABLE carrier_season AS
WITH cm AS (
    SELECT carrier, month, SUM(passengers) / SUM(seats) AS carrier_month_lf
    FROM route_month GROUP BY 1, 2
), ca AS (
    SELECT carrier, SUM(passengers) / SUM(seats) AS carrier_lf
    FROM route_month GROUP BY 1
)
SELECT cm.carrier, cm.month, cm.carrier_month_lf, ca.carrier_lf,
       cm.carrier_month_lf / ca.carrier_lf AS season_idx
FROM cm JOIN ca USING (carrier);

-- 4. Expected vs actual for every core route-month
CREATE OR REPLACE TABLE post_departure AS
WITH base AS (
    SELECT r.*, s.season_idx
    FROM route_month r
    JOIN core_routes USING (carrier, route)
    JOIN carrier_season s USING (carrier, month)
), loo AS (
    SELECT a.carrier, a.route, a.month,
           -- de-seasonalised passengers in the other months / seats in the other months
           SUM(b.passengers / b.season_idx) / SUM(b.seats) AS baseline_lf
    FROM base a
    JOIN base b ON a.carrier = b.carrier AND a.route = b.route AND a.month <> b.month
    GROUP BY 1, 2, 3
)
SELECT base.carrier, base.carrier_name, base.route, base.origin, base.dest, base.month,
       base.dep_scheduled, base.dep_performed, base.seats, base.passengers,
       base.dep_performed / NULLIF(base.dep_scheduled, 0) AS completion_rate,
       base.actual_lf,
       loo.baseline_lf * base.season_idx                AS expected_lf,
       100 * (base.actual_lf - loo.baseline_lf * base.season_idx) AS variance_pp
FROM base JOIN loo USING (carrier, route, month);

-- 5. Route-level summary for the review
CREATE OR REPLACE TABLE route_review AS
SELECT carrier, carrier_name, route,
       SUM(dep_performed)                    AS departures,
       SUM(passengers)                       AS passengers,
       SUM(passengers) / SUM(seats)          AS avg_lf,
       SUM(dep_performed) / SUM(dep_scheduled) AS completion_rate,
       AVG(variance_pp)                      AS mean_variance_pp,
       MIN(variance_pp)                      AS worst_month_variance_pp,
       ARG_MIN(month, variance_pp)           AS worst_month,
       COUNT(*) FILTER (WHERE variance_pp <= -5) AS months_under_5pp,
       COUNT(*) FILTER (WHERE actual_lf >= 0.95) AS months_lf_95plus,
       CASE
           WHEN COUNT(*) FILTER (WHERE variance_pp <= -5) >= 3 THEN 'Underperforming vs expected'
           WHEN COUNT(*) FILTER (WHERE actual_lf >= 0.95) >= 3 THEN 'Spill risk (consistently full)'
           WHEN SUM(passengers) / SUM(seats) < 0.70             THEN 'Excess capacity (LF < 70%)'
           ELSE 'On track'
       END AS review_flag
FROM post_departure
GROUP BY 1, 2, 3;
