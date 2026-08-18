import datetime

from options.fo_bhavcopy import parse_udiff, parse_legacy, UDIFF_CUTOVER_DATE

# Column subset + order as served by NSE UDiFF files (extra columns in real
# files are ignored because parsing is by header name, not position).
UDIFF_SAMPLE = """TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty
2024-08-01,2024-08-01,FO,NSE,STO,67310,INE002A01018,RELIANCE,,2024-08-29,2024-08-29,3300,CE,RELIANCE24AUG3300CE,45.2,52,41,47.65,47.65,44.1,3111.85,47.65,125750,4500,1834,60.61,912,F1,250
2024-08-01,2024-08-01,FO,NSE,STO,67311,INE002A01018,RELIANCE,,2024-08-29,2024-08-29,2900,PE,RELIANCE24AUG2900PE,22.1,25,19.5,21.3,21.3,23.9,3111.85,21.3,98500,-1250,922,26.9,455,F1,250
2024-08-01,2024-08-01,FO,NSE,STF,52175,INE002A01018,RELIANCE,,2024-08-29,2024-08-29,,,RELIANCEFUT,3120,3140,3095,3118.4,3118.4,3105,3111.85,3118.4,10112750,52250,18223,5683.1,40112,F1,250
2024-08-01,2024-08-01,FO,NSE,IDO,41210,,NIFTY,,2024-08-08,2024-08-08,25000,CE,NIFTY24AUG25000CE,120,140,95,101.2,101.2,131,24950.1,101.2,5000000,10,90000,4501,100000,F1,25
"""

LEGACY_SAMPLE = """INSTRUMENT,SYMBOL,EXPIRY_DT,STRIKE_PR,OPTION_TYP,OPEN,HIGH,LOW,CLOSE,SETTLE_PR,CONTRACTS,VAL_INLAKH,OPEN_INT,CHG_IN_OI,TIMESTAMP,
OPTSTK,RELIANCE,27-FEB-2020,1500.00,CE,28.00,31.50,22.10,25.85,25.85,1834,412.20,1257500,45000,03-FEB-2020,
OPTSTK,RELIANCE,27-FEB-2020,1340.00,PE,18.20,20.00,15.10,16.55,16.55,922,127.90,985000,-12500,03-FEB-2020,
FUTSTK,RELIANCE,27-FEB-2020,0.00,XX,1425.00,1441.00,1408.10,1420.55,1420.55,18223,15683.10,10112750,52250,03-FEB-2020,
OPTIDX,NIFTY,27-FEB-2020,12000.00,CE,150.00,160.00,120.00,131.00,131.00,90000,45010.00,5000000,10,03-FEB-2020,
"""


def test_udiff_parses_stock_contracts_and_drops_index():
    rows = parse_udiff(UDIFF_SAMPLE)
    assert len(rows) == 3  # NIFTY (IDO) dropped
    assert {row["symbol"] for row in rows} == {"RELIANCE"}


def test_udiff_canonical_option_row():
    call_row = next(r for r in parse_udiff(UDIFF_SAMPLE) if r["kind"] == "CE")
    assert call_row == {
        "date": "2024-08-01", "symbol": "RELIANCE", "kind": "CE",
        "expiry": "2024-08-29", "strike": 3300.0, "close": 47.65,
        "settle": 47.65, "oi": 125750, "volume": 1834,
        "underlying_close": 3111.85, "lot_size": 250,
    }


def test_udiff_future_row_has_zero_strike():
    future_row = next(r for r in parse_udiff(UDIFF_SAMPLE) if r["kind"] == "FUT")
    assert future_row["strike"] == 0.0
    assert future_row["settle"] == 3118.4


def test_legacy_parses_stock_contracts_and_drops_index():
    rows = parse_legacy(LEGACY_SAMPLE)
    assert len(rows) == 3
    assert {row["kind"] for row in rows} == {"CE", "PE", "FUT"}


def test_legacy_canonical_option_row_no_underlying_or_lot():
    call_row = next(r for r in parse_legacy(LEGACY_SAMPLE) if r["kind"] == "CE")
    assert call_row == {
        "date": "2020-02-03", "symbol": "RELIANCE", "kind": "CE",
        "expiry": "2020-02-27", "strike": 1500.0, "close": 25.85,
        "settle": 25.85, "oi": 1257500, "volume": 1834,
        "underlying_close": None, "lot_size": None,
    }


def test_cutover_constant():
    assert UDIFF_CUTOVER_DATE == datetime.date(2024, 7, 8)
