"""Tests for the analytics ETL pure helpers + score export."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))

import nse_export_analytics as mod


# -----------------------------------------------------------------------------
# enrich_prices
# -----------------------------------------------------------------------------

def test_enrich_prices_adds_adv20():
    raw = pd.DataFrame({
        "symbol": ["AAA"] * 30,
        "date": pd.date_range("2024-01-01", periods=30, freq="B"),
        "close": [100.0] * 30,
        "open": [99.0] * 30, "high": [101.0] * 30, "low": [98.0] * 30,
        "volume": [10_000.0] * 30,
        "factor": [1.0] * 30,
    })
    out = mod.enrich_prices(raw)
    assert "adv20" in out.columns
    # min_periods=5: first 4 rows are NaN, rest are 100*10_000 = 1_000_000
    assert out["adv20"].iloc[:4].isna().all()
    assert (out["adv20"].iloc[4:] == 1_000_000.0).all()


def test_enrich_prices_independent_per_symbol():
    raw = pd.DataFrame({
        "symbol": ["AAA"] * 10 + ["BBB"] * 10,
        "date": list(pd.date_range("2024-01-01", periods=10, freq="B")) * 2,
        "close": [100.0] * 10 + [200.0] * 10,
        "open": [99.0] * 20, "high": [101.0] * 20, "low": [98.0] * 20,
        "volume": [10_000.0] * 20,
        "factor": [1.0] * 20,
    })
    out = mod.enrich_prices(raw)
    aaa = out[out["symbol"] == "AAA"]["adv20"].dropna().iloc[-1]
    bbb = out[out["symbol"] == "BBB"]["adv20"].dropna().iloc[-1]
    assert aaa == 1_000_000.0
    assert bbb == 2_000_000.0


# -----------------------------------------------------------------------------
# write_partitioned_by_year
# -----------------------------------------------------------------------------

def test_write_partitioned_by_year_splits_correctly(tmp_path: Path):
    df = pd.DataFrame({
        "date": [pd.Timestamp("2023-12-29"), pd.Timestamp("2024-01-02"),
                 pd.Timestamp("2024-06-15"), pd.Timestamp("2025-03-10")],
        "symbol": ["AAA", "AAA", "BBB", "BBB"],
        "value": [1, 2, 3, 4],
    })
    written = mod.write_partitioned_by_year(df, tmp_path)
    assert set(written.keys()) == {2023, 2024, 2025}
    assert written[2023]["rows"] == 1
    assert written[2024]["rows"] == 2
    assert written[2025]["rows"] == 1

    # Round-trip the 2024 partition and verify contents
    df2024 = pd.read_parquet(tmp_path / "year=2024" / "data.parquet")
    assert sorted(df2024["symbol"].tolist()) == ["AAA", "BBB"]
    assert "year" not in df2024.columns  # year strips out before write


# -----------------------------------------------------------------------------
# export_scores (uses the pure helper above)
# -----------------------------------------------------------------------------

def test_export_scores_partitions_pred(tmp_path: Path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    pred = pd.DataFrame(
        {"score": [0.1, 0.2, 0.3, 0.4]},
        index=pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2024-06-01"), "AAA"),
             (pd.Timestamp("2024-06-01"), "BBB"),
             (pd.Timestamp("2025-01-15"), "AAA"),
             (pd.Timestamp("2025-01-15"), "BBB")],
            names=["datetime", "instrument"],
        ),
    )
    pred.to_pickle(model_dir / "pred.pkl")

    stats = mod.export_scores(model_dir, tmp_path)
    assert stats["rows_total"] == 4
    assert stats["n_symbols"] == 2
    assert set(stats["by_year"].keys()) == {2024, 2025}

    df_2024 = pd.read_parquet(tmp_path / "scores" / "year=2024" / "data.parquet")
    assert set(df_2024.columns) == {"date", "symbol", "score"}


def test_export_scores_aborts_on_missing(tmp_path: Path):
    import pytest
    with pytest.raises(SystemExit):
        mod.export_scores(tmp_path, tmp_path)


def test_build_symbols_index_aggregates_correctly():
    raw = pd.DataFrame({
        "symbol": ["AAA", "AAA", "BBB", "BBB", "BBB"],
        "date": pd.to_datetime([
            "2024-01-01", "2024-01-02",
            "2023-06-01", "2024-01-15", "2024-06-30",
        ]),
    })
    out = mod.build_symbols_index(raw)
    by_sym = {r["symbol"]: r for r in out}
    assert out == sorted(out, key=lambda r: r["symbol"])  # sorted
    assert by_sym["AAA"] == {
        "symbol": "AAA", "first_date": "2024-01-01",
        "last_date": "2024-01-02", "n_bars": 2,
    }
    assert by_sym["BBB"] == {
        "symbol": "BBB", "first_date": "2023-06-01",
        "last_date": "2024-06-30", "n_bars": 3,
    }


def test_export_scores_handles_series_pickle(tmp_path: Path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    series = pd.Series(
        [0.1, 0.2],
        index=pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2024-06-01"), "AAA"),
             (pd.Timestamp("2024-06-02"), "AAA")],
            names=["datetime", "instrument"],
        ),
    )
    series.to_pickle(model_dir / "pred.pkl")

    stats = mod.export_scores(model_dir, tmp_path)
    assert stats["rows_total"] == 2
    df = pd.read_parquet(tmp_path / "scores" / "year=2024" / "data.parquet")
    assert "score" in df.columns


# -----------------------------------------------------------------------------
# Smoke test against real qlib data — only runs when present
# -----------------------------------------------------------------------------

def test_export_prices_against_real_qlib(tmp_path: Path):
    """Only runs if qlib data is present; otherwise skipped silently."""
    qlib_root = Path(__file__).resolve().parent.parent / "data" / "qlib_data" / "in_data"
    if not (qlib_root / "instruments" / "all.txt").exists():
        return  # skip when running outside the repo
    stats = mod.export_prices(str(qlib_root), tmp_path)
    assert stats["rows_total"] > 1000
    assert stats["n_symbols"] > 100
    # Spot-check the most recent partition has adv20 populated
    last_year = max(stats["by_year"].keys())
    df = pd.read_parquet(tmp_path / "prices" / f"year={last_year}" / "data.parquet")
    assert {"date", "symbol", "close", "open", "high", "low",
            "volume", "factor", "adv20"}.issubset(df.columns)
    assert df["adv20"].notna().any()
