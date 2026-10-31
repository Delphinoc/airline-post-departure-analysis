"""Run the full post-departure analysis pipeline.

Usage:
    python src/run_pipeline.py --raw data/raw/T_T100_SEGMENT_ALL_CARRIER.csv
"""
import argparse
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = ROOT / "sql"
OUT = ROOT / "outputs"
PUBLISHED = ROOT / "data" / "reference" / "bts_published_domestic_load_factor.csv"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def run_sql(con, name, **params):
    sql = (SQL_DIR / name).read_text()
    for key, value in params.items():
        sql = sql.replace("{" + key + "}", str(value))
    con.execute(sql)


def export(con, table, filename, order=""):
    df = con.sql(f"SELECT * FROM {table} {order}").df()
    df.to_csv(OUT / filename, index=False)
    return df


def charts(recon, pdr, review):
    (OUT / "charts").mkdir(parents=True, exist_ok=True)

    # 1. Reconciliation: computed vs published load factor
    fig, ax = plt.subplots(figsize=(8, 4.2))
    labels = [MONTHS[m - 1] for m in recon["month"]]
    ax.plot(labels, recon["published_lf_pct"], marker="o", lw=2.5, color="#9aa5b1", label="BTS published")
    ax.plot(labels, recon["computed_lf_pct"], marker="x", lw=1.5, ls="--", color="#1f6feb", label="Computed from T-100 rows")
    ax.set_ylabel("Domestic load factor (%)")
    ax.set_title("Reconciliation: computed vs published load factor, 2024")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(OUT / "charts" / "01_reconciliation.png", dpi=150)
    plt.close(fig)

    # 2. Distribution of monthly variance vs expected
    fig, ax = plt.subplots(figsize=(8, 4.2))
    ax.hist(pdr["variance_pp"].clip(-20, 20), bins=80, color="#1f6feb")
    ax.axvline(-5, color="#d1242f", ls="--", lw=1)
    ax.text(-5.4, ax.get_ylim()[1] * 0.9, "-5pp review threshold", ha="right", color="#d1242f", fontsize=9)
    ax.set_xlabel("Actual minus expected load factor (pp, clipped at +/-20)")
    ax.set_ylabel("Route-months")
    ax.set_title("How far each route-month landed from its expected load factor")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT / "charts" / "02_variance_distribution.png", dpi=150)
    plt.close(fig)

    # 3. Review flags by carrier (top carriers by departures)
    top = review.groupby("carrier_name")["departures"].sum().nlargest(8).index
    ct = (review[review["carrier_name"].isin(top)]
          .pivot_table(index="carrier_name", columns="review_flag", values="route", aggfunc="count", fill_value=0))
    order = [c for c in ["On track", "Underperforming vs expected", "Spill risk (consistently full)",
                         "Excess capacity (LF < 70%)"] if c in ct.columns]
    ct = ct[order]
    ct = ct.loc[ct.sum(axis=1).sort_values().index]
    colors = {"On track": "#c9d1d9", "Underperforming vs expected": "#d1242f",
              "Spill risk (consistently full)": "#1f6feb", "Excess capacity (LF < 70%)": "#bf8700"}
    fig, ax = plt.subplots(figsize=(8, 4.6))
    left = None
    for col in order:
        ax.barh(ct.index, ct[col], left=left, color=colors[col], label=col)
        left = ct[col] if left is None else left + ct[col]
    ax.set_xlabel("Core routes")
    ax.set_title("Post-departure review flags by carrier (top 8 by departures)")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    fig.tight_layout()
    fig.savefig(OUT / "charts" / "03_flags_by_carrier.png", dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", required=True, help="Path to T_T100_SEGMENT_ALL_CARRIER.csv")
    parser.add_argument("--db", default=str(ROOT / "t100.duckdb"))
    args = parser.parse_args()

    OUT.mkdir(exist_ok=True)
    con = duckdb.connect(args.db)

    run_sql(con, "01_staging.sql", raw_csv=Path(args.raw).resolve().as_posix())
    run_sql(con, "02_data_quality_checks.sql")
    run_sql(con, "03_reconciliation.sql", published_csv=PUBLISHED.as_posix())
    run_sql(con, "04_post_departure_review.sql")

    dq = export(con, "dq_results", "data_quality_results.csv")
    recon = export(con, "recon_load_factor", "reconciliation_load_factor.csv")
    pdr = export(con, "post_departure", "post_departure_route_months.csv", "ORDER BY variance_pp")
    review = export(con, "route_review", "route_review.csv", "ORDER BY review_flag, mean_variance_pp")
    charts(recon, pdr, review)

    # Pipeline assertions: fail loudly if the data no longer reconciles
    assert recon["within_tolerance"].all(), "Computed load factor drifted from BTS published figure"
    assert (pdr["expected_lf"] > 0).all(), "Expected load factor must be positive"

    rows = con.sql("SELECT (SELECT COUNT(*) FROM stg_segments), (SELECT COUNT(*) FROM clean_segments)").fetchall()[0]
    print(f"Staged rows: {rows[0]:,} | clean rows: {rows[1]:,}")
    print("\nData-quality checks:\n", dq[["check_name", "severity", "failing_rows"]].to_string(index=False))
    print("\nReconciliation:\n", recon[["month", "computed_lf_pct", "published_lf_pct", "diff_pp"]].to_string(index=False))
    print(f"\nCore routes reviewed: {len(review):,} ({len(pdr):,} route-months)")
    print(review["review_flag"].value_counts().to_string())


if __name__ == "__main__":
    main()
