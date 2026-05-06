"""Tests for T+1 settlement modelling in nse_paper_trade.

Focus on the pure function `release_matured_settlements` and the
end-to-end behaviour of `cmd_execute` with sells/buys interleaved.
We mock qlib + price lookups so the test is fast and offline.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))

import nse_paper_trade as mod


# -----------------------------------------------------------------------------
# Pure function tests
# -----------------------------------------------------------------------------

def test_release_matured_empty():
    pending, released = mod.release_matured_settlements(
        pd.DataFrame(columns=["settlement_date", "amount"]),
        as_of="2026-04-25",
    )
    assert pending.empty
    assert released == 0.0


def test_release_matured_releases_only_settled():
    pending = pd.DataFrame([
        {"settlement_date": "2026-04-23", "amount": 100.0},  # matured
        {"settlement_date": "2026-04-24", "amount": 200.0},  # matured (== as_of)
        {"settlement_date": "2026-04-25", "amount": 300.0},  # still pending
        {"settlement_date": "2026-04-26", "amount": 400.0},  # still pending
    ])
    still_pending, released = mod.release_matured_settlements(pending, as_of="2026-04-24")
    assert released == 300.0
    assert len(still_pending) == 2
    assert set(still_pending["settlement_date"]) == {"2026-04-25", "2026-04-26"}


def test_release_matured_none_input():
    pending, released = mod.release_matured_settlements(None, as_of="2026-04-25")
    assert pending.empty
    assert released == 0.0


# -----------------------------------------------------------------------------
# End-to-end test: SELL queues to pending, does NOT bloat same-day BUY budget
# -----------------------------------------------------------------------------

def _write_decision(dirpath: Path, date: str, buys: list[dict], sells: list[dict]):
    dirpath.mkdir(parents=True, exist_ok=True)
    payload = {"date": date, "actions": {"BUY": buys, "SELL": sells}}
    (dirpath / f"{date}.json").write_text(json.dumps(payload))


def test_cmd_execute_sell_proceeds_unavailable_same_day(tmp_path: Path):
    """If we SELL ₹100k on day T, that ₹100k must NOT be available to BUY
    on day T — it's locked until T+1."""
    decisions = tmp_path / "dec"
    portfolio_path = tmp_path / "portfolio.csv"
    log_path = tmp_path / "trades.csv"
    equity_path = tmp_path / "equity.csv"
    pending_path = tmp_path / "pending.csv"

    # Pre-existing portfolio: 100 shares of OLD at ₹1000 = ₹100k value
    pd.DataFrame([{
        "symbol": "OLD", "shares": 100, "avg_price": 1000.0, "bought_on": "2026-04-20",
    }]).to_csv(portfolio_path, index=False)

    # Decision: sell OLD, buy NEW
    _write_decision(decisions, "2026-04-24",
                    buys=[{"symbol": "NEW", "rank": 1}],
                    sells=[{"symbol": "OLD"}])

    fake_prices = pd.Series({"OLD": 1000.0, "NEW": 500.0}, name="close")

    args = SimpleNamespace(
        date="2026-04-24",
        decisions_dir=str(decisions),
        portfolio=str(portfolio_path),
        trade_log=str(log_path),
        equity_log=str(equity_path),
        pending_settlement=str(pending_path),
        qlib_provider="ignored",
        starting_cash=0.0,  # zero free cash — only the locked sell proceeds exist
        buy_cost=0.0,
        sell_cost=0.0,
        settlement_lag_days=1,
    )

    with patch.object(mod, "close_price", return_value=fake_prices), \
         patch.object(mod, "next_trading_day", return_value="2026-04-25"), \
         patch.object(mod, "mark_portfolio_and_log") as mock_mark:
        mod.cmd_execute(args)

    # OLD was sold; pending file must hold the ₹100k receivable
    pending = pd.read_csv(pending_path)
    assert len(pending) == 1
    assert pending["settlement_date"].iloc[0] == "2026-04-25"
    assert abs(pending["amount"].iloc[0] - 100_000.0) < 0.01

    # No BUY should have happened — there was no settled cash today
    portfolio = pd.read_csv(portfolio_path)
    assert "OLD" not in portfolio["symbol"].tolist()  # sold
    assert "NEW" not in portfolio["symbol"].tolist()  # not bought (no cash)

    # mark-to-market now receives settled cash and pending separately so the
    # next execute() can read each without double-counting the receivables.
    settled_cash = mock_mark.call_args.args[1]
    pending_passed = mock_mark.call_args.kwargs["pending_value"]
    assert abs(settled_cash - 0.0) < 0.01
    assert abs(pending_passed - 100_000.0) < 0.01


def test_cmd_execute_pending_releases_next_day(tmp_path: Path):
    """A pending receivable from yesterday becomes spendable cash today."""
    decisions = tmp_path / "dec"
    portfolio_path = tmp_path / "portfolio.csv"
    log_path = tmp_path / "trades.csv"
    equity_path = tmp_path / "equity.csv"
    pending_path = tmp_path / "pending.csv"

    # Pre-existing pending: ₹100k matures on 2026-04-25
    pd.DataFrame([{
        "settlement_date": "2026-04-25", "amount": 100_000.0,
    }]).to_csv(pending_path, index=False)

    # Empty portfolio
    pd.DataFrame(columns=["symbol", "shares", "avg_price", "bought_on"]).to_csv(
        portfolio_path, index=False
    )

    # Decision on 2026-04-25: buy NEW, no sells
    _write_decision(decisions, "2026-04-25",
                    buys=[{"symbol": "NEW", "rank": 1}],
                    sells=[])

    fake_prices = pd.Series({"NEW": 500.0}, name="close")

    args = SimpleNamespace(
        date="2026-04-25",
        decisions_dir=str(decisions),
        portfolio=str(portfolio_path),
        trade_log=str(log_path),
        equity_log=str(equity_path),
        pending_settlement=str(pending_path),
        qlib_provider="ignored",
        starting_cash=0.0,
        buy_cost=0.0,
        sell_cost=0.0,
        settlement_lag_days=1,
    )

    with patch.object(mod, "close_price", return_value=fake_prices), \
         patch.object(mod, "next_trading_day", return_value="2026-04-26"), \
         patch.object(mod, "mark_portfolio_and_log"):
        mod.cmd_execute(args)

    # Pending file now empty (matured & released)
    pending = pd.read_csv(pending_path)
    assert pending.empty

    # NEW was bought using the released cash (95% deployed equally)
    portfolio = pd.read_csv(portfolio_path)
    assert "NEW" in portfolio["symbol"].tolist()
    new = portfolio[portfolio["symbol"] == "NEW"].iloc[0]
    # 95% of 100k = 95k / ₹500 = 190 shares
    assert int(new["shares"]) == 190


def test_cmd_execute_no_double_count_across_days(tmp_path: Path):
    """Day1 SELL ₹100k → pending. Day2 pending matures + a BUY happens.
    Day2 must see exactly ₹100k of available cash, not ₹200k. The bug being
    guarded: equity CSV's `cash` column was previously written as
    settled+pending, then read back AND the matured rows were added again
    from the pending CSV, double-counting receivables."""
    decisions = tmp_path / "dec"
    portfolio_path = tmp_path / "portfolio.csv"
    log_path = tmp_path / "trades.csv"
    equity_path = tmp_path / "equity.csv"
    pending_path = tmp_path / "pending.csv"

    pd.DataFrame([{
        "symbol": "OLD", "shares": 100, "avg_price": 1000.0, "bought_on": "2026-04-20",
    }]).to_csv(portfolio_path, index=False)

    _write_decision(decisions, "2026-04-24",
                    buys=[],
                    sells=[{"symbol": "OLD"}])

    common = dict(
        decisions_dir=str(decisions),
        portfolio=str(portfolio_path),
        trade_log=str(log_path),
        equity_log=str(equity_path),
        pending_settlement=str(pending_path),
        qlib_provider="ignored",
        starting_cash=0.0,
        buy_cost=0.0,
        sell_cost=0.0,
        settlement_lag_days=1,
    )

    fake_close_day1 = pd.Series({"OLD": 1000.0}, name="close")
    fake_close_day2 = pd.Series({"NEW": 500.0}, name="close")

    args_day1 = SimpleNamespace(date="2026-04-24", **common)
    with patch.object(mod, "close_price", return_value=fake_close_day1), \
         patch.object(mod, "next_trading_day", return_value="2026-04-25"):
        mod.cmd_execute(args_day1)

    eq = pd.read_csv(equity_path)
    assert len(eq) == 1
    assert abs(eq["total_equity"].iloc[0] - 100_000.0) < 1.0

    _write_decision(decisions, "2026-04-25",
                    buys=[{"symbol": "NEW", "rank": 1}],
                    sells=[])
    args_day2 = SimpleNamespace(date="2026-04-25", **common)
    with patch.object(mod, "close_price", return_value=fake_close_day2), \
         patch.object(mod, "next_trading_day", return_value="2026-04-26"):
        mod.cmd_execute(args_day2)

    portfolio = pd.read_csv(portfolio_path)
    assert "NEW" in portfolio["symbol"].tolist()
    new = portfolio[portfolio["symbol"] == "NEW"].iloc[0]
    # ₹100k * 0.95 = ₹95k → 190 shares @ ₹500. Double-count would yield 380.
    assert int(new["shares"]) == 190, (
        f"Expected 190 shares (₹100k available); got {int(new['shares'])} "
        f"— pending receivable likely double-counted with last row's cash"
    )

    eq = pd.read_csv(equity_path)
    day2 = eq[eq["date"] == "2026-04-25"].iloc[0]
    # Equity should still be ~₹100k: ₹5k leftover cash + ₹95k position. No ratchet.
    assert abs(day2["total_equity"] - 100_000.0) < 100.0, (
        f"Equity ratcheted to ₹{day2['total_equity']:,.0f} from ₹100k base — "
        f"settled cash + pending double-counted"
    )
