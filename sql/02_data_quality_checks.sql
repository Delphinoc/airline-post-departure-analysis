-- 02_data_quality_checks.sql
-- Row-level data-integrity checks on the staged scope.
-- severity = 'exclude' -> failing rows are removed before route analysis
-- severity = 'flag'    -> rows are kept but surfaced for review

CREATE OR REPLACE TABLE dq_results AS
WITH total AS (SELECT COUNT(*) AS n FROM stg_segments)

SELECT 'null_keys' AS check_name, 'exclude' AS severity,
       'Carrier, origin, destination or month is missing' AS description,
       COUNT(*) AS failing_rows
FROM stg_segments
WHERE carrier IS NULL OR origin IS NULL OR dest IS NULL OR month IS NULL

UNION ALL
SELECT 'exact_duplicates', 'exclude',
       'Fully identical rows (double-loaded records)',
       (SELECT COUNT(*) FROM stg_segments) - (SELECT COUNT(*) FROM (SELECT DISTINCT * FROM stg_segments))

UNION ALL
SELECT 'passengers_without_seats', 'exclude',
       'Passengers reported but zero seats',
       COUNT(*) FROM stg_segments WHERE passengers > 0 AND seats = 0

UNION ALL
SELECT 'seats_without_departures', 'exclude',
       'Seats reported but zero departures performed',
       COUNT(*) FROM stg_segments WHERE seats > 0 AND dep_performed = 0

UNION ALL
SELECT 'passengers_exceed_seats', 'flag',
       'Row-level load factor above 100%',
       COUNT(*) FROM stg_segments WHERE passengers > seats AND seats > 0

UNION ALL
-- Explained: BTS reports one row per aircraft type, so a flight scheduled on type A but
-- flown on type B shows 0 scheduled / 1 performed on the type-B row. Resolves at route level.
SELECT 'aircraft_swap_rows', 'flag',
       'Departures performed on an aircraft type with zero scheduled (equipment swap)',
       COUNT(*) FROM stg_segments WHERE dep_scheduled = 0 AND dep_performed > 0

UNION ALL
-- The real test: after summing across aircraft types, does a route-month still fly more than scheduled?
SELECT 'route_month_performed_exceeds_scheduled', 'flag',
       'Route-months (all aircraft types) with more departures performed than scheduled',
       COUNT(*) FROM (
    SELECT carrier, route, month FROM stg_segments GROUP BY ALL
    HAVING SUM(dep_performed) > SUM(dep_scheduled))

UNION ALL
-- First version used < 9 seats and flagged 6,390 rows; review showed these are genuine
-- 4-8 seat commuter aircraft (Alaska, Hawaii, Caribbean), so the floor was lowered to < 2.
SELECT 'implausible_seats_per_departure', 'flag',
       'Average seats per departure below 2 or above 550',
       COUNT(*) FROM stg_segments
WHERE dep_performed > 0 AND (seats / dep_performed < 2 OR seats / dep_performed > 550)

UNION ALL
SELECT 'origin_equals_destination', 'flag',
       'Segment starts and ends at the same airport (sightseeing / return-to-origin)',
       COUNT(*) FROM stg_segments WHERE origin = dest

UNION ALL
SELECT 'inconsistent_route_distance', 'flag',
       'Rows on an airport pair reported with more than one distance',
       COUNT(*) FROM stg_segments s
WHERE (s.origin, s.dest) IN (
    SELECT origin, dest FROM stg_segments GROUP BY 1, 2 HAVING COUNT(DISTINCT distance_mi) > 1)

UNION ALL
SELECT 'quarter_month_mismatch', 'exclude',
       'Quarter field disagrees with month',
       COUNT(*) FROM stg_segments WHERE quarter <> CAST(CEIL(month / 3.0) AS INTEGER);

-- Clean table used downstream: drop 'exclude' failures, de-duplicate.
CREATE OR REPLACE TABLE clean_segments AS
SELECT DISTINCT *
FROM stg_segments
WHERE carrier IS NOT NULL AND origin IS NOT NULL AND dest IS NOT NULL AND month IS NOT NULL
  AND NOT (passengers > 0 AND seats = 0)
  AND NOT (seats > 0 AND dep_performed = 0)
  AND quarter = CAST(CEIL(month / 3.0) AS INTEGER);
