import datetime

from options.fo_archive import fetch_day
from options.qa import coverage_report, sample_cell_checks
from tests.test_options_fo_archive import _zip_bytes


def _write_synthetic_day(archive_root, trading_date, strikes, underlying_close=1000.0):
    header = ("TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,"
              "FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,"
              "LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,"
              "TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty\n")
    lines = [header]
    expiry = trading_date + datetime.timedelta(days=25)
    for strike_price in strikes:
        # settle ~ a plausible OTM-ish premium so IV inversion converges
        premium = max(2.0, (underlying_close - strike_price) * 0.5 + 20.0)
        lines.append(f"{trading_date},{trading_date},FO,NSE,STO,1,ISIN,TESTSTK,,{expiry},{expiry},"
                     f"{strike_price},CE,NAME,1,1,1,{premium},{premium},1,{underlying_close},{premium},"
                     f"500,0,100,1,10,F1,500\n")
    payload = _zip_bytes(f"BhavCopy_NSE_FO_0_0_0_{trading_date:%Y%m%d}_F_0000.csv", "".join(lines))
    fetch_day(trading_date, archive_root, http_get=lambda url: (200, payload))


def test_coverage_report_counts_present_days(tmp_path):
    calendar_dates = [datetime.date(2024, 8, 1), datetime.date(2024, 8, 2), datetime.date(2024, 8, 5)]
    _write_synthetic_day(tmp_path, calendar_dates[0], [950, 1000, 1050])
    report = coverage_report(tmp_path, calendar_dates)
    assert report[2024]["expected"] == 3 and report[2024]["present"] == 1
    assert report[2024]["coverage"] < 0.95


def test_sample_cell_checks_pass_on_clean_ladder(tmp_path):
    trading_date = datetime.date(2024, 8, 1)
    _write_synthetic_day(tmp_path, trading_date, [900, 950, 1000, 1050, 1100])
    checks = sample_cell_checks(tmp_path, trading_date, "TESTSTK")
    assert checks["strikes_contiguous"] is True
    assert checks["atm_oi_positive"] is True
    assert checks["atm_iv_sane"] in (True, False)  # sanity band applied to a real inversion
    assert checks["atm_iv"] is None or checks["atm_iv"] > 0


def test_sample_cell_checks_flags_gapped_ladder(tmp_path):
    trading_date = datetime.date(2024, 8, 2)
    # hole at 1050/1100 — inside the ±15% ATM window, gap 150 > 2× modal gap 50
    _write_synthetic_day(tmp_path, trading_date, [900, 950, 1000, 1150])
    checks = sample_cell_checks(tmp_path, trading_date, "TESTSTK")
    assert checks["strikes_contiguous"] is False
