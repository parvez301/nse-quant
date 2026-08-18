import datetime
import io
import json
import zipfile

from options.fo_archive import fetch_day, load_day, url_candidates
from tests.test_options_fo_bhavcopy import UDIFF_SAMPLE, LEGACY_SAMPLE


def _zip_bytes(inner_name: str, text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(inner_name, text)
    return buffer.getvalue()


def test_url_candidates_order_flips_at_cutover():
    before = url_candidates(datetime.date(2020, 2, 3))
    after = url_candidates(datetime.date(2024, 8, 1))
    assert "DERIVATIVES/2020/FEB/fo03FEB2020bhav.csv.zip" in before[0]
    assert "BhavCopy_NSE_FO_0_0_0_20240801_F_0000.csv.zip" in after[0]
    assert len(before) == len(after) == 2


def test_fetch_day_writes_canonical_gz_and_is_idempotent(tmp_path):
    def fake_http_get(url):
        return 200, _zip_bytes("BhavCopy_NSE_FO_0_0_0_20240801_F_0000.csv", UDIFF_SAMPLE)

    trading_date = datetime.date(2024, 8, 1)
    assert fetch_day(trading_date, tmp_path, http_get=fake_http_get) == "written"
    assert fetch_day(trading_date, tmp_path, http_get=fake_http_get) == "cached"
    rows = load_day(trading_date, tmp_path)
    assert len(rows) == 3 and rows[0]["symbol"] == "RELIANCE"
    assert rows[0]["oi"] == 125750  # ints survive the gz round-trip


def test_fetch_day_legacy_format(tmp_path):
    def fake_http_get(url):
        if "DERIVATIVES" in url:
            return 200, _zip_bytes("fo03FEB2020bhav.csv", LEGACY_SAMPLE)
        return 404, b""

    assert fetch_day(datetime.date(2020, 2, 3), tmp_path, http_get=fake_http_get) == "written"
    assert len(load_day(datetime.date(2020, 2, 3), tmp_path)) == 3


def test_fetch_day_records_gap_on_double_404_then_clears(tmp_path):
    trading_date = datetime.date(2024, 8, 15)  # holiday-like: 404 everywhere
    assert fetch_day(trading_date, tmp_path, http_get=lambda url: (404, b"")) == "no_file"
    ledger = json.loads((tmp_path / "gaps.json").read_text())
    assert ledger["2024-08-15"] == "no_file"
    # a later successful fetch clears the ledger entry
    ok_get = lambda url: (200, _zip_bytes("BhavCopy_NSE_FO_0_0_0_20240815_F_0000.csv", UDIFF_SAMPLE))
    assert fetch_day(trading_date, tmp_path, http_get=ok_get) == "written"
    assert "2024-08-15" not in json.loads((tmp_path / "gaps.json").read_text())
