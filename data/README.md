# Data

## Raw data (not committed: ~79 MB)

`raw/T_T100_SEGMENT_ALL_CARRIER.csv` — BTS T-100 Segment (All Carriers), January–July 2024.

Download it either way:

1. **BTS TranStats** (official): https://www.transtats.bts.gov → Air Carrier Statistics (Form 41 Traffic) – All Carriers → *T-100 Segment (All Carriers)*. Select year 2024, months Jan–Jul, all fields, and download as CSV.
2. **Public mirror** used when building this project: `data/T_T100_SEGMENT_ALL_CARRIER.csv` in https://github.com/admacpherson/T-100-Aviation-Data

Save it as `data/raw/T_T100_SEGMENT_ALL_CARRIER.csv`.

## Reference data (committed)

`reference/bts_published_domestic_load_factor.csv` — BTS's published monthly domestic load factor for scheduled passenger flights (not seasonally adjusted), from FRED series `LOADFACTORD`: https://fred.stlouisfed.org/series/LOADFACTORD. Used only for reconciliation.

`reference/bts_domestic_enplanements_monthly.csv` — BTS monthly domestic enplanements (US air carriers, scheduled passenger flights, not seasonally adjusted, thousands), Jan 2010 – Jun 2026, from FRED series `ENPLANED`: https://fred.stlouisfed.org/series/ENPLANED (retrieved Oct 2026). Used by `src/demand_forecast.py`.
