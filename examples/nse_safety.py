#!/usr/bin/env python3
"""Safety rails for the NSE production stack.

Three primitives that the daily runner + paper trader use to fail safely:

  1. HALT flag        — outputs/HALT     touch this to pause everything
                        also auto-set when daily P&L breach occurs
  2. notify(message)  — macOS Notification Center + outputs/alerts.log + cron.log
  3. require_data_quality()  — aborts if today's data is incomplete

Subcommands (CLI use):
  python examples/nse_safety.py status            # is HALT set? what's the equity status?
  python examples/nse_safety.py halt "reason"     # set HALT
  python examples/nse_safety.py resume            # clear HALT
  python examples/nse_safety.py check_pnl         # run after mark; sets HALT if breached
  python examples/nse_safety.py check_data        # run after refresh; aborts if data is bad
  python examples/nse_safety.py notify "message"  # manual notification
"""
import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd


HALT_PATH = Path("outputs/HALT")
ALERT_LOG = Path("outputs/alerts.log")

# Loss limits — tune these to your risk tolerance
DAILY_LOSS_LIMIT = -0.05         # -5% in one day = HALT
DRAWDOWN_LIMIT   = -0.20         # -20% from peak = HALT
DATA_FRESHNESS_PCT = 0.80        # require >=80% of universe to have a bar for "today"
DATA_FRESHNESS_DAYS = 3          # data is "fresh" if last bar is within N days


# ---------------------------------------------------------------------------
# Halt / resume
# ---------------------------------------------------------------------------

def is_halted() -> tuple[bool, str | None]:
    if HALT_PATH.exists():
        return True, HALT_PATH.read_text().strip()
    return False, None


def set_halt(reason: str):
    HALT_PATH.parent.mkdir(parents=True, exist_ok=True)
    msg = f"HALTED at {datetime.now().isoformat(timespec='seconds')}\nReason: {reason}\n"
    HALT_PATH.write_text(msg)
    notify(f"⛔ Kronos HALTED — {reason}")
    print(msg)


def clear_halt():
    if HALT_PATH.exists():
        HALT_PATH.unlink()
        notify("✅ Kronos resumed (HALT cleared)")
        print("HALT cleared.")
    else:
        print("Not halted.")


# ---------------------------------------------------------------------------
# Notify (macOS osascript + log file)
# ---------------------------------------------------------------------------

def notify(message: str):
    ALERT_LOG.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().isoformat(timespec="seconds")
    with open(ALERT_LOG, "a") as f:
        f.write(f"[{ts}] {message}\n")

    snsTopicArn = os.environ.get("SNS_TOPIC_ARN")
    if snsTopicArn:
        try:
            import boto3
            boto3.client("sns").publish(
                TopicArn=snsTopicArn,
                Subject=f"[NSE] {message[:90]}",
                Message=message,
            )
        except Exception as exc:
            print(f"[notify] SNS publish failed: {exc}")
    else:
        # Local: macOS Notification Center; silent fallback elsewhere
        safe = message.replace('"', "'").replace("\\", "")
        cmd = f'osascript -e \'display notification "{safe}" with title "Kronos NSE"\''
        try:
            os.system(cmd + " 2>/dev/null")
        except Exception:
            pass

    print(f"[notify] {message}")


# ---------------------------------------------------------------------------
# P&L kill switch
# ---------------------------------------------------------------------------

def check_pnl(equity_path: str = "outputs/paper_equity.csv") -> bool:
    """Returns True if pnl is OK; False (and sets HALT) if breached."""
    p = Path(equity_path)
    if not p.exists():
        return True

    df = pd.read_csv(p)
    if len(df) < 2:
        return True

    df = df.sort_values("date").reset_index(drop=True)
    today_eq = float(df["total_equity"].iloc[-1])
    yest_eq = float(df["total_equity"].iloc[-2])
    daily_ret = today_eq / yest_eq - 1

    peak = df["total_equity"].cummax().iloc[-1]
    drawdown = today_eq / peak - 1

    breached = []
    if daily_ret <= DAILY_LOSS_LIMIT:
        breached.append(f"Daily loss {daily_ret:+.2%} <= limit {DAILY_LOSS_LIMIT:+.2%}")
    if drawdown <= DRAWDOWN_LIMIT:
        breached.append(f"Drawdown {drawdown:+.2%} <= limit {DRAWDOWN_LIMIT:+.2%}")

    if breached:
        reason = "; ".join(breached)
        set_halt(f"P&L breach: {reason}")
        return False

    print(f"[pnl] daily {daily_ret:+.2%}  dd {drawdown:+.2%}  ok")
    return True


# ---------------------------------------------------------------------------
# Data quality gate
# ---------------------------------------------------------------------------

def check_data(qlib_provider: str = "data/qlib_data/in_data") -> bool:
    """Returns True if data is OK; False if it looks incomplete/stale."""
    import qlib
    from qlib.data import D

    qlib.init(provider_uri=os.path.expanduser(qlib_provider), region="cn")
    cal = D.calendar(start_time="2024-01-01")
    if len(cal) == 0:
        notify("❌ Data quality: empty calendar")
        return False

    last_date = cal[-1]
    days_since = (pd.Timestamp.today() - last_date).days
    if days_since > DATA_FRESHNESS_DAYS:
        notify(f"⚠ Data stale: last bar is {last_date.date()} ({days_since} days ago)")
        return False

    instruments = D.list_instruments(D.instruments(market="all"), as_list=True)
    sample = [s for s in instruments if s not in ("NIFTY50", "SENSEX")]
    if not sample:
        notify("❌ Data quality: empty instrument list")
        return False

    df = D.features(sample, ["$close"], start_time=str(last_date.date()), end_time=str(last_date.date()))
    if df.empty:
        notify(f"❌ Data quality: no closes returned for {last_date.date()}")
        return False

    coverage = df["$close"].dropna().shape[0] / len(sample)
    if coverage < DATA_FRESHNESS_PCT:
        notify(f"⚠ Data quality: only {coverage:.0%} of stocks have a bar for {last_date.date()} "
               f"(need >= {DATA_FRESHNESS_PCT:.0%})")
        return False

    print(f"[data] last_date={last_date.date()}  coverage={coverage:.1%}  ok")
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_status(args):
    halted, reason = is_halted()
    if halted:
        print(f"⛔ HALTED")
        print(f"   {reason}")
    else:
        print("✅ Running")
    eq = Path("outputs/paper_equity.csv")
    if eq.exists():
        df = pd.read_csv(eq)
        if len(df):
            row = df.iloc[-1]
            peak = df["total_equity"].cummax().iloc[-1]
            dd = float(row["total_equity"]) / peak - 1
            print(f"   last equity: ₹{row['total_equity']:,.0f} on {row['date']}  drawdown={dd:+.2%}")


def cmd_halt(args):
    set_halt(args.reason)


def cmd_resume(args):
    clear_halt()


def cmd_check_pnl(args):
    ok = check_pnl(args.equity_log)
    sys.exit(0 if ok else 1)


def cmd_check_data(args):
    ok = check_data(args.qlib_provider)
    sys.exit(0 if ok else 1)


def cmd_notify(args):
    notify(args.message)


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("status"); sp.set_defaults(fn=cmd_status)

    sp = sub.add_parser("halt")
    sp.add_argument("reason")
    sp.set_defaults(fn=cmd_halt)

    sp = sub.add_parser("resume"); sp.set_defaults(fn=cmd_resume)

    sp = sub.add_parser("check_pnl")
    sp.add_argument("--equity_log", default="outputs/paper_equity.csv")
    sp.set_defaults(fn=cmd_check_pnl)

    sp = sub.add_parser("check_data")
    sp.add_argument("--qlib_provider", default="data/qlib_data/in_data")
    sp.set_defaults(fn=cmd_check_data)

    sp = sub.add_parser("notify")
    sp.add_argument("message")
    sp.set_defaults(fn=cmd_notify)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
