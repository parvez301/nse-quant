#!/usr/bin/env python3
"""THE JUDGE — walk-forward evaluation of the DSRD short-strangle strategy.

Pre-registered protocol (spec §7): the stop-loss variant is chosen by Sharpe
on 2019–2022 cycles only; the verdict comes exclusively from 2023→present.
PASS requires ALL of: CAGR > 7% (FD), Sharpe >= NIFTY buy-and-hold, max
drawdown < 30%, COVID-cycle equity floor > 60% of capital (tuning window,
reported alongside), monthly-excess t-stat > 2. Exit code 0 = PASS,
1 = FAIL/ERROR. A FAIL verdict stops the project per spec.

Usage:
  .venv/bin/python examples/nse_options_backtest.py            # full judgment
  .venv/bin/python examples/nse_options_backtest.py --quick    # integration smoke
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from options.backtest import run_backtest, summary_stats  # noqa: E402
from options.config import JUDGE_CAPITAL, STOP_MULTIPLIERS  # noqa: E402
from options.underlying import AdjustedCloseStore  # noqa: E402

TUNING_START, TUNING_END = "2019-01-01", "2022-12-31"
JUDGED_START = "2023-01-01"
RISK_FREE_ANNUAL = 0.07


def _sharpe_of_monthly(monthly_returns: list[float]) -> float | None:
    if len(monthly_returns) < 2:
        return None
    risk_free_monthly = RISK_FREE_ANNUAL / 12.0
    excess = [r - risk_free_monthly for r in monthly_returns]
    mean_excess = sum(excess) / len(excess)
    std_excess = math.sqrt(sum((e - mean_excess) ** 2 for e in excess) / (len(excess) - 1))
    return mean_excess / std_excess * math.sqrt(12.0) if std_excess > 0 else 0.0


def nifty_monthly_sharpe(start_iso: str, end_iso: str,
                         cache_path: pathlib.Path) -> float | None:
    """NIFTY buy-and-hold Sharpe from yfinance ^NSEI, JSON-cached. Returns
    None when neither download nor cache is available — never fabricates."""
    monthly_closes: dict[str, float] | None = None
    try:
        import yfinance
        frame = yfinance.download("^NSEI", start=start_iso, end=end_iso,
                                  progress=False, auto_adjust=True)
        if len(frame):
            closes = frame["Close"] if "Close" in frame else frame.iloc[:, 0]
            monthly_closes = {}
            for timestamp, value in closes.itertuples():
                monthly_closes[str(timestamp)[:7]] = float(value)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(monthly_closes))
    except Exception:
        monthly_closes = None
    if monthly_closes is None and cache_path.exists():
        monthly_closes = json.loads(cache_path.read_text())
    if not monthly_closes:
        return None
    months = sorted(monthly_closes)
    returns = [monthly_closes[b] / monthly_closes[a] - 1.0
               for a, b in zip(months, months[1:])]
    return _sharpe_of_monthly(returns)


def evaluate_criteria(judged_stats: dict, covid_floor_fraction: float | None,
                      nifty_sharpe: float | None) -> dict:
    criteria = {
        "cagr_beats_fd_7pct": {
            "value": judged_stats.get("cagr"),
            "threshold": 0.07,
            "passed": (judged_stats.get("cagr") or -1) > 0.07,
        },
        "sharpe_beats_nifty": {
            "value": judged_stats.get("sharpe"), "threshold": nifty_sharpe,
            "passed": ("unavailable" if nifty_sharpe is None
                       else (judged_stats.get("sharpe") or -99) >= nifty_sharpe),
        },
        "max_drawdown_below_30pct": {
            "value": judged_stats.get("max_drawdown"), "threshold": 0.30,
            "passed": (judged_stats.get("max_drawdown") or 1.0) < 0.30,
        },
        "covid_2020_equity_floor_above_60pct": {
            "value": covid_floor_fraction, "threshold": 0.60,
            "passed": (covid_floor_fraction or 0.0) > 0.60,
        },
        "monthly_excess_tstat_above_2": {
            "value": judged_stats.get("t_stat_excess"), "threshold": 2.0,
            "passed": (judged_stats.get("t_stat_excess") or -99) > 2.0,
        },
    }
    if judged_stats.get("n_months", 0) < 12:
        verdict = "ERROR"  # too little judged evidence to grade at all
    elif all(entry["passed"] is True for entry in criteria.values()):
        verdict = "PASS"
    else:
        verdict = "FAIL"
    return {"verdict": verdict, "criteria": criteria}


def _per_year_table(monthly_returns: dict[str, float]) -> dict[str, float]:
    per_year: dict[str, float] = {}
    for month_key, month_return in monthly_returns.items():
        year_key = month_key[:4]
        per_year[year_key] = (1.0 + per_year.get(year_key, 0.0)) * (1.0 + month_return) - 1.0
    return per_year


def _symbol_attribution(trades: list[dict], top_n: int = 10) -> dict:
    per_symbol: dict[str, float] = {}
    for trade in trades:
        per_symbol[trade["symbol"]] = per_symbol.get(trade["symbol"], 0.0) + trade["net_pnl"]
    ranked = sorted(per_symbol.items(), key=lambda item: item[1], reverse=True)
    return {"best": ranked[:top_n], "worst": ranked[-top_n:][::-1]}


def run_judgment(archive_root: pathlib.Path, qlib_root: pathlib.Path,
                 output_dir: pathlib.Path, end_iso: str) -> dict:
    close_store = AdjustedCloseStore(qlib_root)
    blackouts_path = REPO_ROOT / "data" / "options_blackouts.yaml"

    print("== tuning 2019-2022: stop-loss grid ==", flush=True)
    tuning_results = {}
    for stop_key in STOP_MULTIPLIERS:
        result = run_backtest(archive_root, close_store, TUNING_START, TUNING_END,
                              stop_key=stop_key, use_earnings_filter=True,
                              capital=JUDGE_CAPITAL, blackouts_path=blackouts_path)
        stats = summary_stats(result)
        tuning_results[stop_key] = {"result": result, "stats": stats}
        print(f"  stop {stop_key:6}: trades={stats.get('n_trades', 0):4} "
              f"sharpe={stats.get('sharpe', float('nan')):.2f} "
              f"total={stats.get('total_return', 0):+.1%}", flush=True)

    selected_stop = max(tuning_results,
                        key=lambda key: tuning_results[key]["stats"].get("sharpe") or -99)
    selected_tuning = tuning_results[selected_stop]
    covid_curve = [(iso, equity) for iso, equity in
                   selected_tuning["result"]["equity_curve"]
                   if "2020-02-01" <= iso <= "2020-04-30"]
    covid_floor_fraction = (min(equity for _, equity in covid_curve) / JUDGE_CAPITAL
                            if covid_curve else None)
    print(f"selected stop: {selected_stop} | covid floor: {covid_floor_fraction}", flush=True)

    print("== judged window 2023 -> present ==", flush=True)
    judged = run_backtest(archive_root, close_store, JUDGED_START, end_iso,
                          stop_key=selected_stop, use_earnings_filter=True,
                          capital=JUDGE_CAPITAL, blackouts_path=blackouts_path)
    judged_stats = summary_stats(judged)
    judged_no_earnings = run_backtest(archive_root, close_store, JUDGED_START, end_iso,
                                      stop_key=selected_stop, use_earnings_filter=False,
                                      capital=JUDGE_CAPITAL, blackouts_path=blackouts_path)
    judged_no_earnings_stats = summary_stats(judged_no_earnings)

    nifty_sharpe = nifty_monthly_sharpe(JUDGED_START, end_iso,
                                        output_dir / "nsei_monthly.json")
    verdict = evaluate_criteria(judged_stats, covid_floor_fraction, nifty_sharpe)

    median_margin = judged_stats.get("median_margin")
    finding_zero = {
        "median_trade_margin": median_margin,
        "one_lakh_supports_a_single_strangle": (median_margin is not None
                                                and median_margin <= 70_000.0),
        "note": "spec amended: judge capital Rs5L; the doc's Rs1L cannot margin "
                "a typical stock strangle if this flag is false",
    }

    headline = {
        "generated_at": datetime.date.today().isoformat(),
        "verdict": verdict["verdict"], "criteria": verdict["criteria"],
        "selected_stop": selected_stop,
        "judged_stats": judged_stats,
        "judged_no_earnings_stats": judged_no_earnings_stats,
        "tuning_stats": {key: value["stats"] for key, value in tuning_results.items()},
        "covid_floor_fraction": covid_floor_fraction,
        "nifty_sharpe_judged_window": nifty_sharpe,
        "finding_0_capital_feasibility": finding_zero,
        "per_year_judged": _per_year_table(judged["monthly_returns"]),
        "config": judged["config"],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "headline.json").write_text(json.dumps(headline, indent=2, default=str))
    _write_report(output_dir, headline, judged)
    _write_csvs(output_dir, judged)
    print(f"\nJUDGE VERDICT: {verdict['verdict']}", flush=True)
    return headline


def _write_report(output_dir: pathlib.Path, headline: dict, judged: dict) -> None:
    lines = ["# DSRD Short-Strangle — Judge Report", "",
             f"**Verdict: {headline['verdict']}** (judged window "
             f"{judged['config']['start']} → {judged['config']['end']}, "
             f"stop {headline['selected_stop']}, earnings filter ON, "
             f"capital ₹{judged['config']['capital']:,.0f})", "", "## Criteria", ""]
    for name, entry in headline["criteria"].items():
        status = {True: "PASS", False: "FAIL"}.get(entry["passed"], str(entry["passed"]))
        value = entry["value"]
        rendered_value = f"{value:.4f}" if isinstance(value, float) else str(value)
        lines.append(f"- `{name}`: {status} (value {rendered_value}, "
                     f"threshold {entry['threshold']})")
    lines += ["", "## Judged stats", ""]
    for key, value in sorted(headline["judged_stats"].items()):
        lines.append(f"- {key}: {value:.4f}" if isinstance(value, float)
                     else f"- {key}: {value}")
    lines += ["", "## Per-year returns (judged)", ""]
    for year, year_return in sorted(headline["per_year_judged"].items()):
        lines.append(f"- {year}: {year_return:+.1%}")
    lines += ["", "## Variant: earnings filter OFF", ""]
    for key in ("total_return", "sharpe", "max_drawdown", "n_trades", "win_rate"):
        value = headline["judged_no_earnings_stats"].get(key)
        lines.append(f"- {key}: {value:.4f}" if isinstance(value, float)
                     else f"- {key}: {value}")
    attribution = _symbol_attribution(judged["trades"])
    lines += ["", "## Symbol attribution (judged, net P&L)", "", "Best:"]
    lines += [f"- {symbol}: ₹{pnl:,.0f}" for symbol, pnl in attribution["best"]]
    lines += ["", "Worst:"]
    lines += [f"- {symbol}: ₹{pnl:,.0f}" for symbol, pnl in attribution["worst"]]
    lines += ["", "## Finding #0 — capital feasibility", "",
              f"- median trade margin: ₹{headline['finding_0_capital_feasibility']['median_trade_margin']:,.0f}"
              if headline["finding_0_capital_feasibility"]["median_trade_margin"] else
              "- no trades to measure",
              f"- ₹1L supports a single strangle: "
              f"{headline['finding_0_capital_feasibility']['one_lakh_supports_a_single_strangle']}"]
    (output_dir / "report.md").write_text("\n".join(lines) + "\n")


def _write_csvs(output_dir: pathlib.Path, judged: dict) -> None:
    import csv
    with open(output_dir / "equity_judged.csv", "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "equity"])
        writer.writerows(judged["equity_curve"])
    trades = judged["trades"]
    if trades:
        with open(output_dir / "trades_judged.csv", "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(trades[0].keys()))
            writer.writeheader()
            writer.writerows(trades)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", default="data/fo_bhavcopy", type=pathlib.Path)
    parser.add_argument("--qlib-root", default="data/qlib_data/in_data", type=pathlib.Path)
    parser.add_argument("--out", default="outputs/options/judge", type=pathlib.Path)
    parser.add_argument("--end", default=datetime.date.today().isoformat())
    parser.add_argument("--quick", action="store_true",
                        help="integration smoke: one stop, 6 months, no verdict file")
    arguments = parser.parse_args()

    if arguments.quick:
        close_store = AdjustedCloseStore(arguments.qlib_root)
        result = run_backtest(arguments.archive_root, close_store,
                              "2024-01-01", "2024-06-30", stop_key="1:1",
                              use_earnings_filter=True, capital=JUDGE_CAPITAL,
                              blackouts_path=REPO_ROOT / "data" / "options_blackouts.yaml")
        stats = summary_stats(result)
        print(json.dumps(stats, indent=2, default=str))
        print(f"trades: {len(result['trades'])} cycles: {result['config']['cycles']}")
        return 0

    headline = run_judgment(arguments.archive_root, arguments.qlib_root,
                            arguments.out, arguments.end)
    return 0 if headline["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
