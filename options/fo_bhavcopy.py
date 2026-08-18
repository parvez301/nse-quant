"""Parse NSE F&O bhavcopy files into the canonical row schema.

NSE switched formats on 2024-07-08: the modern UDiFF layout carries
underlying price and board lot; the legacy layout does not (those fields
become None and are backfilled from the qlib store downstream). Only stock
derivatives survive parsing — index contracts are out of scope (spec §11).
"""
from __future__ import annotations

import csv
import datetime
import io

UDIFF_CUTOVER_DATE = datetime.date(2024, 7, 8)

_UDIFF_STOCK_TYPES = {"STO", "STF"}
_LEGACY_STOCK_INSTRUMENTS = {"OPTSTK", "FUTSTK"}


def _to_float(raw: str) -> float | None:
    raw = (raw or "").strip()
    try:
        return float(raw)
    except ValueError:
        return None


def _to_int(raw: str) -> int:
    value = _to_float(raw)
    return int(value) if value is not None else 0


def parse_udiff(csv_text: str) -> list[dict]:
    rows = []
    for record in csv.DictReader(io.StringIO(csv_text)):
        if (record.get("FinInstrmTp") or "").strip() not in _UDIFF_STOCK_TYPES:
            continue
        is_future = record["FinInstrmTp"].strip() == "STF"
        lot_size_value = _to_float(record.get("NewBrdLotQty", ""))
        rows.append({
            "date": record["TradDt"].strip(),
            "symbol": record["TckrSymb"].strip(),
            "kind": "FUT" if is_future else record["OptnTp"].strip(),
            "expiry": record["XpryDt"].strip(),
            "strike": 0.0 if is_future else (_to_float(record["StrkPric"]) or 0.0),
            "close": _to_float(record["ClsPric"]) or 0.0,
            "settle": _to_float(record["SttlmPric"]) or 0.0,
            "oi": _to_int(record["OpnIntrst"]),
            "volume": _to_int(record["TtlTradgVol"]),
            "underlying_close": _to_float(record["UndrlygPric"]),
            "lot_size": int(lot_size_value) if lot_size_value else None,
        })
    return rows


def _legacy_date(raw: str) -> str:
    return datetime.datetime.strptime(raw.strip().title(), "%d-%b-%Y").date().isoformat()


def parse_legacy(csv_text: str) -> list[dict]:
    rows = []
    for record in csv.DictReader(io.StringIO(csv_text)):
        if (record.get("INSTRUMENT") or "").strip() not in _LEGACY_STOCK_INSTRUMENTS:
            continue
        is_future = record["INSTRUMENT"].strip() == "FUTSTK"
        rows.append({
            "date": _legacy_date(record["TIMESTAMP"]),
            "symbol": record["SYMBOL"].strip(),
            "kind": "FUT" if is_future else record["OPTION_TYP"].strip(),
            "expiry": _legacy_date(record["EXPIRY_DT"]),
            "strike": 0.0 if is_future else (_to_float(record["STRIKE_PR"]) or 0.0),
            "close": _to_float(record["CLOSE"]) or 0.0,
            "settle": _to_float(record["SETTLE_PR"]) or 0.0,
            "oi": _to_int(record["OPEN_INT"]),
            "volume": _to_int(record["CONTRACTS"]),
            "underlying_close": None,
            "lot_size": None,
        })
    return rows
