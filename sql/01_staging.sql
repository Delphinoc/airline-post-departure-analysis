-- 01_staging.sql
-- Load the raw BTS T-100 Segment (All Carriers) extract and build the analysis scope.
-- {raw_csv} is substituted by src/run_pipeline.py.

CREATE OR REPLACE TABLE raw_segments AS
SELECT * FROM read_csv_auto('{raw_csv}', header = true);

-- Scope: US carriers (DATA_SOURCE = 'DU'), scheduled passenger service (CLASS = 'F'),
-- passenger-configured aircraft (AIRCRAFT_CONFIG = 1), both ends in the United States.
-- This is the same scope BTS uses for its published domestic load factor.
CREATE OR REPLACE TABLE stg_segments AS
SELECT
    YEAR                         AS year,
    MONTH                        AS month,
    QUARTER                      AS quarter,
    UNIQUE_CARRIER               AS carrier,
    UNIQUE_CARRIER_NAME          AS carrier_name,
    ORIGIN                       AS origin,
    DEST                         AS dest,
    ORIGIN || '-' || DEST        AS route,
    AIRCRAFT_TYPE                AS aircraft_type,
    DISTANCE                     AS distance_mi,
    COALESCE(DEPARTURES_SCHEDULED, 0) AS dep_scheduled,
    COALESCE(DEPARTURES_PERFORMED, 0) AS dep_performed,
    COALESCE(SEATS, 0)           AS seats,
    COALESCE(PASSENGERS, 0)      AS passengers
FROM raw_segments
WHERE DATA_SOURCE = 'DU'
  AND CLASS = 'F'
  AND AIRCRAFT_CONFIG = 1
  AND ORIGIN_COUNTRY_NAME = 'United States'
  AND DEST_COUNTRY_NAME = 'United States';
