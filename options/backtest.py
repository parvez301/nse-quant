"""Walk-forward monthly-cycle backtest engine for DSRD short strangles.

Cycle anatomy (all data-derived, no calendar assumptions about expiry
weekday): monthly expiries are the expiry dates shared by >= 50 symbols;
a cycle enters on the first Friday after the previous expiry (first trading
day after it when no Friday file exists) and force-exits on the last Tuesday
before its own expiry (last file day before expiry as fallback), so no
position ever rides settlement — avoiding exercise STT by construction.

Accounting: capital is constant (no compounding — conservative and keeps
monthly returns comparable across the window); equity = capital + realized
+ unrealized. Positions are marked at settle; missing contract-days carry
the last known premium forward.
"""
from __future__ import annotations

import datetime
import pathlib
from collections import defaultdict

from options.config import (MARGIN_BUDGET_FRACTION, MAX_POSITIONS,
                            PROFIT_TARGET_REMAINING, SCORE_FLOOR,
                            STOP_MULTIPLIERS)
from options.costs import strangle_entry_costs, strangle_exit_costs
from options.filters import in_blackout, in_earnings_window, load_blackouts
from options.margin import lot_size_estimate, strangle_margin
from options.score import trade_score
from options.sigma import classify_strangle, sigma_bands
from options.strikes import select_strangle
from options.underlying import rsi14, spot_for_symbol
from options.fo_archive import load_day


def _archive_days(archive_root: pathlib.Path, start_iso: str, end_iso: str) -> list[str]:
    days = []
    for day_file in sorted(pathlib.Path(archive_root).glob("*/*.csv.gz")):
        stem = day_file.stem.replace(".csv", "")
        iso = f"{stem[:4]}-{stem[4:6]}-{stem[6:8]}"
        if start_iso <= iso <= end_iso:
            days.append(iso)
    return days


def _load_day_by_symbol(iso_date: str, archive_root: pathlib.Path) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in load_day(datetime.date.fromisoformat(iso_date), archive_root):
        grouped[row["symbol"]].append(row)
    return grouped


def monthly_expiry_dates(archive_root: pathlib.Path, start_iso: str,
                         end_iso: str, min_shared_symbols: int = 50,
                         sample_stride_days: int = 7) -> list[str]:
    """Expiry dates shared by many symbols = the monthly stock expiries.
    Weekly stride sampling is sufficient: every file lists every live expiry."""
    trading_days = _archive_days(archive_root, start_iso, end_iso)
    expiry_symbols: dict[str, set] = defaultdict(set)
    for iso_date in trading_days[::sample_stride_days]:
        for row in load_day(datetime.date.fromisoformat(iso_date), archive_root):
            expiry_symbols[row["expiry"]].add(row["symbol"])
    return sorted(expiry for expiry, symbols in expiry_symbols.items()
                  if len(symbols) >= min_shared_symbols)


def build_cycles(expiry_dates: list[str], trading_days: list[str]) -> list[dict]:
    cycles = []
    for previous_expiry, current_expiry in zip(expiry_dates, expiry_dates[1:]):
        window = [d for d in trading_days if previous_expiry < d < current_expiry]
        if len(window) < 2:  # need an entry day plus at least one marking day
            continue
        fridays = [d for d in window
                   if datetime.date.fromisoformat(d).weekday() == 4]
        entry_date = fridays[0] if fridays else window[0]
        pre_deadline = [d for d in window if d > entry_date]
        if not pre_deadline:
            continue
        tuesdays = [d for d in pre_deadline
                    if datetime.date.fromisoformat(d).weekday() == 1]
        deadline_date = tuesdays[-1] if tuesdays else pre_deadline[-1]
        if deadline_date <= entry_date:
            continue
        cycles.append({"entry_date": entry_date, "deadline_date": deadline_date,
                       "expiry": current_expiry})
    return cycles


class StranglePosition:
    def __init__(self, symbol: str, strangle: dict, lot_size: int, margin: float,
                 score: float, grade: str, entry_date: str, entry_costs: float,
                 entry_spot: float | None = None, rsi_at_entry: float | None = None):
        self.symbol = symbol
        self.call_row = strangle["call_row"]
        self.put_row = strangle["put_row"]
        self.entry_premium_per_share = strangle["entry_premium_per_share"]
        self.call_delta = strangle.get("call_delta")
        self.put_delta = strangle.get("put_delta")
        self.call_iv = strangle.get("call_iv")
        self.put_iv = strangle.get("put_iv")
        self.entry_spot = entry_spot
        self.rsi_at_entry = rsi_at_entry
        self.lot_size = lot_size
        self.margin = margin
        self.score = score
        self.grade = grade
        self.entry_date = entry_date
        self.entry_costs = entry_costs
        self.current_call = self.call_row["settle"]
        self.current_put = self.put_row["settle"]
        self.breached = False

    def mark(self, symbol_day_rows: list[dict]) -> None:
        for row in symbol_day_rows:
            if (row["kind"] == "CE" and row["expiry"] == self.call_row["expiry"]
                    and row["strike"] == self.call_row["strike"] and row["settle"]):
                self.current_call = row["settle"]
            elif (row["kind"] == "PE" and row["expiry"] == self.put_row["expiry"]
                    and row["strike"] == self.put_row["strike"] and row["settle"]):
                self.current_put = row["settle"]
        spot_now = spot_for_symbol(symbol_day_rows)
        if spot_now and (spot_now >= self.call_row["strike"]
                         or spot_now <= self.put_row["strike"]):
            self.breached = True

    @property
    def combined_premium_per_share(self) -> float:
        return self.current_call + self.current_put

    def unrealized_pnl(self) -> float:
        return (self.entry_premium_per_share - self.combined_premium_per_share) * self.lot_size

    def check_exit(self, stop_multiplier: float | None) -> str | None:
        if self.combined_premium_per_share <= PROFIT_TARGET_REMAINING * self.entry_premium_per_share:
            return "target"
        if (stop_multiplier is not None
                and self.combined_premium_per_share >= stop_multiplier * self.entry_premium_per_share):
            return "stop"
        return None

    def close(self, exit_date: str, reason: str) -> dict:
        stressed = reason == "stop"
        exit_costs = strangle_exit_costs(
            self.current_call * self.lot_size, self.current_put * self.lot_size,
            self.current_call, self.current_put, self.lot_size, stressed=stressed)
        gross_pnl = self.unrealized_pnl()
        return {
            "symbol": self.symbol, "entry_date": self.entry_date,
            "exit_date": exit_date, "exit_reason": reason,
            "call_strike": self.call_row["strike"], "put_strike": self.put_row["strike"],
            "entry_premium_per_share": self.entry_premium_per_share,
            "exit_premium_per_share": self.combined_premium_per_share,
            "lot_size": self.lot_size, "margin": self.margin,
            "premium_collected": self.entry_premium_per_share * self.lot_size,
            "entry_costs": self.entry_costs, "exit_costs": exit_costs,
            "gross_pnl": gross_pnl, "net_pnl": gross_pnl - self.entry_costs - exit_costs,
            "score": self.score, "grade": self.grade, "breached": self.breached,
            "entry_spot": self.entry_spot, "rsi_at_entry": self.rsi_at_entry,
            "call_delta": self.call_delta, "put_delta": self.put_delta,
            "call_iv": self.call_iv, "put_iv": self.put_iv,
            "expiry": self.call_row["expiry"],
        }


def _entry_candidates(cycle: dict, archive_root: pathlib.Path, close_store,
                      blackout_ranges, use_earnings_filter: bool,
                      universe: set[str] | None = None) -> list[dict]:
    entry_date = datetime.date.fromisoformat(cycle["entry_date"])
    expiry_date = datetime.date.fromisoformat(cycle["expiry"])
    if in_blackout(entry_date, expiry_date, blackout_ranges):
        return []
    earnings_clear = not in_earnings_window(entry_date, expiry_date)
    if use_earnings_filter and not earnings_clear:
        return []
    by_symbol = _load_day_by_symbol(cycle["entry_date"], archive_root)
    raw_candidates = []
    for symbol, symbol_rows in by_symbol.items():
        if universe is not None and symbol not in universe:
            continue
        spot = spot_for_symbol(symbol_rows)
        if not spot:
            continue
        strangle = select_strangle(symbol_rows, spot, cycle["expiry"], entry_date)
        if strangle is None:
            continue
        known_lot = next((row["lot_size"] for row in symbol_rows if row["lot_size"]), None)
        lot_size = lot_size_estimate(known_lot, spot)
        average_iv = 0.5 * (strangle["call_iv"] + strangle["put_iv"])
        days_to_expiry = (expiry_date - entry_date).days
        bands = sigma_bands(spot, average_iv, days_to_expiry)
        grade = classify_strangle(bands, strangle["call_row"]["strike"],
                                  strangle["put_row"]["strike"])
        if grade == "reject":
            continue
        closes = close_store.closes_upto(symbol, cycle["entry_date"]) if close_store else []
        raw_candidates.append({
            "symbol": symbol, "spot": spot, "strangle": strangle,
            "lot_size": lot_size, "grade": grade,
            "rsi": rsi14(closes),
            "liquidity_raw": strangle["call_row"]["oi"] + strangle["put_row"]["oi"],
            "earnings_clear": earnings_clear,
            "margin": strangle_margin(spot, strangle["call_row"]["strike"],
                                      strangle["put_row"]["strike"], lot_size),
        })
    liquidity_sorted = sorted(c["liquidity_raw"] for c in raw_candidates)
    for candidate in raw_candidates:
        if len(liquidity_sorted) > 1:
            rank_position = liquidity_sorted.index(candidate["liquidity_raw"])
            candidate["liquidity_rank"] = rank_position / (len(liquidity_sorted) - 1)
        else:
            candidate["liquidity_rank"] = 1.0
        candidate["score"] = trade_score(
            candidate["liquidity_rank"], candidate["rsi"],
            candidate["strangle"]["call_delta"], candidate["strangle"]["put_delta"],
            candidate["grade"], candidate["earnings_clear"])
    return sorted(raw_candidates, key=lambda c: c["score"], reverse=True)


def run_cycle(cycle: dict, archive_root: pathlib.Path, close_store,
              blackout_ranges, stop_multiplier: float | None,
              use_earnings_filter: bool, capital: float,
              score_floor: float = SCORE_FLOOR,
              universe: set[str] | None = None) -> list[dict]:
    candidates = _entry_candidates(cycle, archive_root, close_store,
                                   blackout_ranges, use_earnings_filter,
                                   universe=universe)
    margin_budget = MARGIN_BUDGET_FRACTION * capital
    positions: list[StranglePosition] = []
    margin_used = 0.0
    for candidate in candidates:
        if len(positions) >= MAX_POSITIONS:
            break
        if candidate["score"] < score_floor:
            continue
        if margin_used + candidate["margin"] > margin_budget:
            continue
        strangle = candidate["strangle"]
        entry_costs = strangle_entry_costs(
            strangle["call_row"]["settle"] * candidate["lot_size"],
            strangle["put_row"]["settle"] * candidate["lot_size"],
            strangle["call_row"]["settle"], strangle["put_row"]["settle"],
            candidate["lot_size"])
        positions.append(StranglePosition(
            candidate["symbol"], strangle, candidate["lot_size"],
            candidate["margin"], candidate["score"], candidate["grade"],
            cycle["entry_date"], entry_costs,
            entry_spot=candidate["spot"], rsi_at_entry=candidate["rsi"]))
        margin_used += candidate["margin"]

    trades: list[dict] = []
    if not positions:
        return trades
    marking_days = [d for d in _archive_days(archive_root, cycle["entry_date"],
                                             cycle["deadline_date"])
                    if d > cycle["entry_date"]]
    for iso_date in marking_days:
        if not positions:
            break
        by_symbol = _load_day_by_symbol(iso_date, archive_root)
        still_open: list[StranglePosition] = []
        for position in positions:
            position.mark(by_symbol.get(position.symbol, []))
            exit_reason = position.check_exit(stop_multiplier)
            if iso_date == cycle["deadline_date"] and exit_reason is None:
                exit_reason = "time"
            if exit_reason:
                trades.append(position.close(iso_date, exit_reason))
            else:
                still_open.append(position)
        positions = still_open
    for position in positions:  # archive gap on deadline day — close at last mark
        trades.append(position.close(cycle["deadline_date"], "time"))
    return trades


def run_backtest(archive_root: pathlib.Path, close_store, start_iso: str,
                 end_iso: str, stop_key: str, use_earnings_filter: bool,
                 capital: float, blackouts_path: pathlib.Path,
                 expiry_dates: list[str] | None = None,
                 score_floor: float = SCORE_FLOOR,
                 universe: set[str] | None = None) -> dict:
    stop_multiplier = STOP_MULTIPLIERS[stop_key]
    blackout_ranges = load_blackouts(blackouts_path)
    trading_days = _archive_days(archive_root, start_iso, end_iso)
    if expiry_dates is None:
        expiry_dates = monthly_expiry_dates(archive_root, start_iso, end_iso)
    cycles = build_cycles(expiry_dates, trading_days)
    all_trades: list[dict] = []
    for cycle in cycles:
        all_trades.extend(run_cycle(cycle, archive_root, close_store,
                                    blackout_ranges, stop_multiplier,
                                    use_earnings_filter, capital, score_floor,
                                    universe=universe))
    equity_curve = _equity_curve(all_trades, trading_days, capital)
    return {"trades": all_trades, "equity_curve": equity_curve,
            "monthly_returns": _monthly_returns(equity_curve),
            "config": {"stop": stop_key, "earnings_filter": use_earnings_filter,
                       "capital": capital, "start": start_iso, "end": end_iso,
                       "cycles": len(cycles), "score_floor": score_floor}}


def _equity_curve(trades: list[dict], trading_days: list[str],
                  capital: float) -> list[tuple[str, float]]:
    realized_by_date: dict[str, float] = defaultdict(float)
    for trade in trades:
        realized_by_date[trade["exit_date"]] += trade["net_pnl"]
    curve, cumulative = [], 0.0
    for iso_date in trading_days:
        cumulative += realized_by_date.get(iso_date, 0.0)
        curve.append((iso_date, capital + cumulative))
    return curve


def _monthly_returns(equity_curve: list[tuple[str, float]]) -> dict[str, float]:
    month_last: dict[str, float] = {}
    for iso_date, equity in equity_curve:
        month_last[iso_date[:7]] = equity
    months = sorted(month_last)
    returns = {}
    for previous_month, current_month in zip(months, months[1:]):
        base = month_last[previous_month]
        returns[current_month] = (month_last[current_month] / base - 1.0) if base > 0 else 0.0
    return returns


def summary_stats(result: dict, risk_free_annual: float = 0.07) -> dict:
    import math
    monthly = list(result["monthly_returns"].values())
    trades = result["trades"]
    curve = [equity for _, equity in result["equity_curve"]]
    capital = result["config"]["capital"]
    stats: dict = {"n_months": len(monthly), "n_trades": len(trades)}
    if curve:
        stats["total_return"] = curve[-1] / capital - 1.0
        peak, max_drawdown = curve[0], 0.0
        for equity in curve:
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
        stats["max_drawdown"] = max_drawdown
        stats["equity_floor_fraction"] = min(curve) / capital
    if monthly:
        stats["cagr"] = (1.0 + stats["total_return"]) ** (12.0 / len(monthly)) - 1.0
        mean_monthly = sum(monthly) / len(monthly)
        stats["mean_monthly_return"] = mean_monthly
        risk_free_monthly = risk_free_annual / 12.0
        excess = [r - risk_free_monthly for r in monthly]
        mean_excess = sum(excess) / len(excess)
        if len(excess) > 1:
            std_excess = math.sqrt(sum((e - mean_excess) ** 2 for e in excess)
                                   / (len(excess) - 1))
            stats["sharpe"] = (mean_excess / std_excess * math.sqrt(12.0)
                               if std_excess > 0 else 0.0)
            stats["t_stat_excess"] = (mean_excess / (std_excess / math.sqrt(len(excess)))
                                      if std_excess > 0 else 0.0)
            downside = [min(0.0, e) for e in excess]
            downside_std = math.sqrt(sum(d ** 2 for d in downside) / len(downside))
            stats["sortino"] = (mean_excess / downside_std * math.sqrt(12.0)
                                if downside_std > 0 else float("inf"))
    if trades:
        wins = [t["net_pnl"] for t in trades if t["net_pnl"] > 0]
        losses = [t["net_pnl"] for t in trades if t["net_pnl"] < 0]
        stats["win_rate"] = len(wins) / len(trades)
        stats["profit_factor"] = (sum(wins) / abs(sum(losses))
                                  if losses else float("inf"))
        stats["breach_rate"] = sum(1 for t in trades if t["breached"]) / len(trades)
        stats["median_margin"] = sorted(t["margin"] for t in trades)[len(trades) // 2]
    return stats
