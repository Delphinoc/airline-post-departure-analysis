-- 03_reconciliation.sql
-- Reconcile the load factor computed from segment rows against the figure BTS publishes.
-- BTS domestic load factor = revenue passenger-miles / available seat-miles (RPM / ASM).
-- {published_csv} holds BTS's published monthly values (via FRED series LOADFACTORD).

CREATE OR REPLACE TABLE published_lf AS
SELECT * FROM read_csv_auto('{published_csv}', header = true);

CREATE OR REPLACE TABLE recon_load_factor AS
WITH computed AS (
    SELECT year, month,
           SUM(passengers * distance_mi) / 1e9 AS rpm_bn,
           SUM(seats * distance_mi) / 1e9      AS asm_bn,
           100 * SUM(passengers * distance_mi) / SUM(seats * distance_mi) AS computed_lf_pct,
           SUM(passengers) / 1e6               AS segment_passengers_m
    FROM clean_segments
    GROUP BY 1, 2
)
SELECT c.year, c.month,
       ROUND(c.rpm_bn, 2)          AS rpm_bn,
       ROUND(c.asm_bn, 2)          AS asm_bn,
       ROUND(c.computed_lf_pct, 2) AS computed_lf_pct,
       p.published_lf_pct,
       ROUND(c.computed_lf_pct - p.published_lf_pct, 2) AS diff_pp,
       ABS(ROUND(c.computed_lf_pct, 1) - p.published_lf_pct) <= 0.1 AS within_tolerance,
       ROUND(c.segment_passengers_m, 2) AS segment_passengers_m
FROM computed c
LEFT JOIN published_lf p USING (year, month)
ORDER BY c.year, c.month;
