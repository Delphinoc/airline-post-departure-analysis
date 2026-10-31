# Airline Post-Departure Performance Analysis

A post-departure review of US domestic airline routes using public BTS T-100 Segment data (Jan–Jul 2024): reconcile the data against official figures, check its integrity, then compare each route's **actual** monthly load factor with what was **expected** and flag routes that need a revenue-management review.

**Stack:** SQL (DuckDB) · Python (pandas, matplotlib)

## Key results

| | |
|---|---|
| Data | 314k T-100 segment rows → 196,535 rows in scope (US carriers, scheduled passenger service, domestic) |
| Reconciliation | Computed domestic load factor matches BTS's published figure within **0.04 pp in all 7 months** |
| Data-integrity checks | **11 checks**; 0 rows needed exclusion; 5 flag types investigated and explained (see below) |
| Post-departure review | **2,447 core routes** (35 carriers, 17,129 route-months, 58% of passengers in scope) |
| Flags | **80** underperforming vs expected · **10** spill risk (≥95% full in 3+ months) · **181** excess capacity (avg LF < 70%) |

### 1. Reconciliation against published figures

Before analysing routes, I rebuilt BTS's headline domestic load factor (revenue passenger-miles ÷ available seat-miles) from the raw segment rows and compared it with the published monthly series. Every month agrees within 0.04 percentage points, so the scope filters (carrier type, service class, aircraft configuration, domestic endpoints) match BTS's definition.

![Reconciliation](outputs/charts/01_reconciliation.png)

### 2. Data-integrity checks

| Check | Rows | Outcome |
|---|---:|---|
| Null keys, exact duplicates, passengers without seats, seats without departures, quarter/month mismatch | 0 | Clean |
| Inconsistent distance for the same airport pair | 0 | Clean |
| Passengers exceed seats (row LF > 100%) | 10 | Flagged; mostly 1–2 passengers over on single flights (likely non-revenue / jump-seat reporting) |
| Departures performed on an aircraft type with 0 scheduled | 13,886 | **Explained:** BTS reports one row per aircraft type, so equipment swaps look like unscheduled flights. Resolves when summed to route level |
| Route-months performing more departures than scheduled (after summing types) | 9,286 | Flagged; overall completion is still 99.5% |
| Implausible seats per departure | 321 | First version (< 9 seats) flagged 6,390 rows; review showed genuine 4–8 seat commuter aircraft (Alaska, Hawaii, Caribbean), so the floor was revised to < 2 |
| Origin equals destination | 1,655 | Flagged (sightseeing / return-to-origin); excluded from route analysis |

### 3. Post-departure review: actual vs expected

For every core route (flown all 7 months, ≥ 60 departures each month):

- **Expected LF** for a month = the route's own load factor in the *other* six months (leave-one-out, with seasonality removed) × the carrier's seasonal index for that month.
- **Variance** = actual − expected, in percentage points. Half of all route-months land within about ±3 pp of expected.

![Variance](outputs/charts/02_variance_distribution.png)

Routes are then flagged:

| Flag | Rule | Routes | Share of passengers |
|---|---|---:|---:|
| Underperforming vs expected | ≥ 5 pp below expected in 3+ months | 80 | 2.2% |
| Spill risk | LF ≥ 95% in 3+ months | 10 | 0.5% |
| Excess capacity | Average LF < 70% | 181 | 3.1% |
| On track | — | 2,176 | 94.2% |

![Flags by carrier](outputs/charts/03_flags_by_carrier.png)

**What stands out**
- **Spill risk is concentrated at American Airlines' Phoenix routes** (PHX–CLT, PHX–JFK, PHX–EWR, PHX–BOS, PHX–DCA), averaging 92–94% full. Consistently full flights suggest demand is being turned away, which points to higher fares in the top booking classes or bigger aircraft.
- **Southwest has the most excess-capacity routes**, including Hawaii inter-island flying (HNL–OGG at ~41% LF).
- **Ski and leisure routes show the limits of a carrier-level seasonal index:** SkyWest ASE–DEN fell 40 pp below expected in May, when the ski season ends. A route-level seasonal baseline (needs prior-year data) would fix this.

Full results: [`outputs/route_review.csv`](outputs/route_review.csv) and [`outputs/post_departure_route_months.csv`](outputs/post_departure_route_months.csv).

## How to run

```bash
pip install -r requirements.txt
# download the data first (see data/README.md)
python src/run_pipeline.py --raw data/raw/T_T100_SEGMENT_ALL_CARRIER.csv
```

The pipeline runs the four SQL files in order, writes CSVs and charts to `outputs/`, and **fails if the reconciliation drifts** beyond 0.1 pp of the published figure.

```
sql/01_staging.sql               scope the raw extract to BTS's domestic definition
sql/02_data_quality_checks.sql   11 integrity checks + clean table
sql/03_reconciliation.sql        computed vs published load factor
sql/04_post_departure_review.sql expected vs actual, route flags
src/run_pipeline.py              orchestration, exports, charts, assertions
```

## Limitations

- **"Expected" is a statistical baseline, not an airline forecast.** Airlines compare against their own booking forecasts; public data has none.
- **Segment data has no fares**, so this measures load factor, not revenue or yield.
- **Seven months only**, so seasonality is estimated at carrier level; route-level seasonality (ski, spring break) needs prior-year data.
- US domestic market only; used as a public proxy for an airline network.

## Data sources

- US DOT Bureau of Transportation Statistics, *T-100 Segment (All Carriers)*, Jan–Jul 2024, via TranStats.
- BTS published domestic load factor, scheduled passenger flights, not seasonally adjusted (FRED series `LOADFACTORD`).
