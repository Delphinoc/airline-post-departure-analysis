"""Demand forecasting and event analysis for US domestic airline passengers.

Uses BTS monthly domestic enplanements (FRED series ENPLANED, Jan 2010 - Jun 2026) to:
  1. check and reconcile the series against the T-100 segment passengers used in the
     post-departure review,
  2. decompose demand into trend and seasonality (STL),
  3. backtest seasonal-naive vs SARIMA forecasts on two hold-out years (2019 and Jul 2025 - Jun 2026),
  4. measure event effects: Easter timing (March vs April) and the Nov 2025 FAA flight cuts.

Usage:
    python src/demand_forecast.py
"""
from pathlib import Path
import itertools
import warnings

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from dateutil.easter import easter
from statsmodels.tsa.seasonal import STL
from statsmodels.tsa.statespace.sarimax import SARIMAX

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "reference" / "bts_domestic_enplanements_monthly.csv"
RECON = ROOT / "outputs" / "reconciliation_load_factor.csv"
OUT = ROOT / "outputs"
CHARTS = OUT / "charts"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Pandemic months are masked (treated as missing) so they do not distort the model.
# The Kalman filter in SARIMAX bridges the gap; the window runs to the Omicron wave (Feb 2022).
COVID_START, COVID_END = "2020-03-01", "2022-02-01"
BLUE, GREY, RED, AMBER = "#1f6feb", "#9aa5b1", "#d1242f", "#bf8700"


# ---------------------------------------------------------------- data
def load_series():
    df = pd.read_csv(DATA, parse_dates=["date"])
    s = df.set_index("date")["enplanements_thousands"].asfreq("MS")
    return s


def data_checks(s):
    expected = pd.date_range(s.index.min(), s.index.max(), freq="MS")
    checks = [
        ("Months in series", len(s), len(s) == 198),
        ("Missing months", len(expected.difference(s.index)), len(expected.difference(s.index)) == 0),
        ("Null values", int(s.isna().sum()), s.isna().sum() == 0),
        ("Non-positive values", int((s <= 0).sum()), (s <= 0).sum() == 0),
        ("Duplicate dates", int(s.index.duplicated().sum()), s.index.duplicated().sum() == 0),
    ]
    return pd.DataFrame(checks, columns=["check", "value", "passed"])


def reconcile_with_t100(s):
    """Compare BTS enplanements with passengers summed from the T-100 segment rows (Jan-Jul 2024)."""
    t100 = pd.read_csv(RECON)
    t100["date"] = pd.to_datetime(dict(year=t100.year, month=t100.month, day=1))
    r = t100[["date", "segment_passengers_m"]].copy()
    r["bts_enplanements_m"] = r["date"].map(s / 1000).round(2)
    r["diff_pct"] = ((r["segment_passengers_m"] / r["bts_enplanements_m"] - 1) * 100).round(2)
    r["within_1_5pct"] = r["diff_pct"].abs() <= 1.5
    return r


# ---------------------------------------------------------------- features
def easter_regressor(index):
    """+share in March, -share in April: share of the 8 days up to Easter Sunday that fall in March."""
    x = pd.Series(0.0, index=index)
    for year in sorted(set(index.year)):
        e = pd.Timestamp(easter(year))
        window = pd.date_range(e - pd.Timedelta(days=7), e)
        share = (window.month == 3).mean()
        for month, sign in ((3, 1), (4, -1)):
            ts = pd.Timestamp(year=year, month=month, day=1)
            if ts in x.index:
                x[ts] = sign * share
    return x.rename("easter_march_shift")


def model_input(s):
    y = np.log(s.astype(float)).copy()
    y[COVID_START:COVID_END] = np.nan
    return y


# ---------------------------------------------------------------- models
def fit_sarima(y, exog=None, order=(0, 1, 1), seasonal=(0, 1, 1, 12)):
    return SARIMAX(y, exog=exog, order=order, seasonal_order=seasonal,
                   enforce_stationarity=False, enforce_invertibility=False).fit(disp=False)


def select_order(y, exog):
    """Small AIC grid on the training window only."""
    best = None
    for p, q, P, Q in itertools.product([0, 1, 2], [0, 1, 2], [0, 1], [0, 1]):
        if P == 0 and Q == 0:
            continue
        try:
            res = fit_sarima(y, exog, (p, 1, q), (P, 1, Q, 12))
        except Exception:
            continue
        if best is None or res.aic < best[0]:
            best = (res.aic, (p, 1, q), (P, 1, Q, 12))
    return best[1], best[2]


def mape(actual, forecast):
    return float((np.abs(forecast - actual) / actual).mean() * 100)


def backtest(s, train_end, test_start, test_end, label):
    y = model_input(s)
    x = easter_regressor(s.index)
    y_tr, x_tr = y[:train_end], x[:train_end]
    test_idx = s[test_start:test_end].index
    actual = s[test_idx]

    preds = {}
    # Seasonal naive: same month last year
    preds["Seasonal naive"] = s.shift(12)[test_idx]

    # Airline model SARIMA(0,1,1)(0,1,1)12 on log passengers
    res = fit_sarima(y_tr)
    preds["SARIMA airline model"] = np.exp(res.get_forecast(len(test_idx)).predicted_mean.values)

    # AIC-selected SARIMAX with Easter regressor
    order, seas = select_order(y_tr, x_tr)
    resx = fit_sarima(y_tr, x_tr, order, seas)
    fc = resx.get_forecast(len(test_idx), exog=x[test_idx])
    preds[f"SARIMAX{order}{seas[:3]} + Easter"] = np.exp(fc.predicted_mean.values)
    ci = np.exp(fc.conf_int(alpha=0.05).values)

    rows = []
    for name, p in preds.items():
        p = np.asarray(p, dtype=float)
        rows.append(dict(holdout=label, model=name, mape_pct=round(mape(actual.values, p), 2),
                         bias_pct=round(float(((p - actual.values) / actual.values).mean() * 100), 2)))
    detail = pd.DataFrame({"date": test_idx, "actual": actual.values})
    for name, p in preds.items():
        detail[name] = np.round(np.asarray(p, dtype=float), 0)
    detail["best_lo95"], detail["best_hi95"] = np.round(ci[:, 0]), np.round(ci[:, 1])
    detail.insert(0, "holdout", label)
    return pd.DataFrame(rows), detail, (order, seas)


def one_step_errors(s, train_end, order, seas):
    """Fix parameters estimated on data up to train_end, then produce one-step-ahead forecasts
    for every later month (each forecast only uses data available the month before)."""
    y, x = model_input(s), easter_regressor(s.index)
    params = fit_sarima(y[:train_end], x[:train_end], order, seas).params
    full = SARIMAX(y, exog=x, order=order, seasonal_order=seas,
                   enforce_stationarity=False, enforce_invertibility=False).filter(params)
    pred = full.get_prediction()
    after = s.index > pd.Timestamp(train_end)
    mean = np.exp(pred.predicted_mean[after])
    ci = np.exp(pred.conf_int(alpha=0.05)[after])
    df = pd.DataFrame({"actual": s[after], "forecast_1step": mean.round(0),
                       "lo95": ci.iloc[:, 0].round(0), "hi95": ci.iloc[:, 1].round(0)})
    df["error_pct"] = ((df["actual"] / df["forecast_1step"] - 1) * 100).round(2)
    df["outside_95pi"] = (df["actual"] < df["lo95"]) | (df["actual"] > df["hi95"])
    return df, params


# ---------------------------------------------------------------- charts
def style(ax):
    ax.spines[["top", "right"]].set_visible(False)


def chart_seasonality(idx):
    fig, ax = plt.subplots(figsize=(8, 4.2))
    colors = [RED if v == idx.max() else AMBER if v == idx.min() else BLUE for v in idx.values]
    ax.bar(MONTHS, (idx.values - 1) * 100, color=colors)
    ax.axhline(0, color="#57606a", lw=0.8)
    for i, v in enumerate(idx.values):
        ax.text(i, (v - 1) * 100 + (0.6 if v >= 1 else -1.6), f"{(v - 1) * 100:+.0f}%", ha="center", fontsize=8)
    ax.set_ylim((idx.min() - 1) * 100 - 3, (idx.max() - 1) * 100 + 3)
    ax.set_ylabel("Demand vs average month (%)")
    ax.set_title("Seasonal demand index, US domestic passengers (STL, 2010-2019)")
    style(ax)
    fig.tight_layout()
    fig.savefig(CHARTS / "04_seasonal_index.png", dpi=150)
    plt.close(fig)


def chart_holdout(s, detail, best_col):
    d = detail[detail.holdout == "Jul 2025 - Jun 2026"]
    hist = s["2023-01-01":]
    fig, ax = plt.subplots(figsize=(9, 4.4))
    ax.plot(hist.index, hist / 1000, color=GREY, lw=2, label="Actual")
    ax.plot(d.date, d[best_col] / 1000, color=BLUE, lw=2, ls="--", label="Forecast (made Jun 2025)")
    ax.fill_between(d.date, d.best_lo95 / 1000, d.best_hi95 / 1000, color=BLUE, alpha=0.12, label="95% interval")
    ax.axvline(pd.Timestamp("2025-06-15"), color="#57606a", lw=0.8, ls=":")
    nov = pd.Timestamp("2025-11-01")
    ax.annotate("Nov 2025: FAA flight cuts\n(government shutdown)", xy=(nov, s[nov] / 1000),
                xytext=(nov - pd.Timedelta(days=330), 61.5), fontsize=8, color=RED,
                arrowprops=dict(arrowstyle="->", color=RED))
    ax.set_ylabel("Passengers (millions)")
    ax.set_title("12-month hold-out: forecast vs actual domestic passengers")
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    style(ax)
    fig.tight_layout()
    fig.savefig(CHARTS / "05_forecast_holdout.png", dpi=150)
    plt.close(fig)


def chart_one_step(os_df):
    fig, ax = plt.subplots(figsize=(9, 4.2))
    colors = [RED if o else BLUE for o in os_df["outside_95pi"]]
    ax.bar(os_df.index.strftime("%b %y"), os_df["error_pct"], color=colors)
    ax.axhline(0, color="#57606a", lw=0.8)
    for i, (d, row) in enumerate(os_df.iterrows()):
        if row["outside_95pi"]:
            ax.text(i, row["error_pct"] - 0.35, "FAA flight cuts" if d == pd.Timestamp("2025-11-01") else "",
                    ha="center", va="top", fontsize=8, color=RED)
    ax.set_ylim(os_df["error_pct"].min() - 1.2, os_df["error_pct"].max() + 0.6)
    ax.set_ylabel("Actual vs one-step forecast (%)")
    ax.set_title("One-step-ahead forecast errors (red = outside 95% interval)")
    ax.tick_params(axis="x", labelsize=8)
    style(ax)
    fig.tight_layout()
    fig.savefig(CHARTS / "06_one_step_errors.png", dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------- main
def main():
    CHARTS.mkdir(parents=True, exist_ok=True)
    s = load_series()

    checks = data_checks(s)
    assert checks["passed"].all(), checks
    recon = reconcile_with_t100(s)
    assert recon["within_1_5pct"].all(), "Enplanements no longer reconcile with T-100 segment passengers"

    # Seasonality from the clean pre-pandemic decade
    pre = np.log(s[:"2019-12-01"].astype(float))
    stl = STL(pre, period=12, robust=True).fit()
    seas = np.exp(stl.seasonal.groupby(stl.seasonal.index.month).mean())
    seas = seas / seas.mean()
    seas.index = MONTHS
    chart_seasonality(seas)

    # Backtests
    acc19, det19, _ = backtest(s, "2018-12-01", "2019-01-01", "2019-12-01", "2019")
    acc25, det25, (order, sorder) = backtest(s, "2025-06-01", "2025-07-01", "2026-06-01", "Jul 2025 - Jun 2026")
    acc = pd.concat([acc19, acc25], ignore_index=True)
    detail = pd.concat([det19, det25], ignore_index=True)
    best_col = [c for c in det25.columns if "Easter" in c][0]
    chart_holdout(s, detail, best_col)

    # Event effects
    os_df, params = one_step_errors(s, "2025-06-01", order, sorder)
    chart_one_step(os_df)
    beta = params["easter_march_shift"]
    nov = os_df.loc["2025-11-01"]
    oct_ = os_df.loc["2025-10-01"]
    yoy = lambda d: (s[d] / s[pd.Timestamp(d) - pd.DateOffset(years=1)] - 1) * 100
    events = pd.DataFrame([
        dict(event="Peak season (July) vs average month", metric="seasonal index",
             value_pct=round((seas["Jul"] - 1) * 100, 1)),
        dict(event="Trough (February) vs average month", metric="seasonal index",
             value_pct=round((seas["Feb"] - 1) * 100, 1)),
        dict(event="Easter falls in March: March demand shift", metric="SARIMAX coefficient",
             value_pct=round((np.exp(beta) - 1) * 100, 1)),
        dict(event="Nov 2025 FAA flight cuts: actual vs one-step forecast", metric="forecast gap",
             value_pct=float(nov.error_pct)),
        dict(event="Nov 2025 year-on-year", metric="YoY change", value_pct=round(yoy("2025-11-01"), 1)),
        dict(event="Oct 2025 (control month) actual vs one-step forecast", metric="forecast gap",
             value_pct=float(oct_.error_pct)),
        dict(event="Oct 2025 year-on-year", metric="YoY change", value_pct=round(yoy("2025-10-01"), 1)),
    ])

    checks.to_csv(OUT / "demand_data_checks.csv", index=False)
    recon.to_csv(OUT / "demand_reconciliation_t100.csv", index=False)
    seas.rename("seasonal_index").round(4).to_frame().to_csv(OUT / "demand_seasonal_index.csv", index_label="month")
    acc.to_csv(OUT / "demand_model_accuracy.csv", index=False)
    detail.to_csv(OUT / "demand_forecast_holdout.csv", index=False)
    os_df.to_csv(OUT / "demand_one_step_forecasts.csv", index_label="date")
    events.to_csv(OUT / "demand_event_effects.csv", index=False)

    print("Data checks:\n", checks.to_string(index=False))
    print("\nReconciliation with T-100 segment passengers:\n", recon.to_string(index=False))
    print(f"\nSelected model: SARIMAX{order}{sorder}")
    print("\nHold-out accuracy:\n", acc.to_string(index=False))
    print("\nOne-step-ahead forecasts:\n", os_df.to_string())
    print(f"\nOne-step MAPE: {os_df['error_pct'].abs().mean():.2f}%")
    print("\nEvent effects:\n", events.to_string(index=False))


if __name__ == "__main__":
    main()
