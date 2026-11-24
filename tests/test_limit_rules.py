"""历史涨跌停价规则引擎纯逻辑测试（不联网）。"""
from wmshare.limit import (
    band_at,
    board_of,
    build_rows,
    cent,
    ipo_len,
    is_st_name,
    merge_bars,
    st_segments,
)


def _bar(day, close, pct, factor=1.0, high=None, low=None):
    return {
        "date": day,
        "close": close,
        "high": close if high is None else high,
        "low": close if low is None else low,
        "percent": pct,
        "factor": factor,
    }


def test_board_of():
    assert board_of("600519") == "main"
    assert board_of("000001") == "main"
    assert board_of("002594") == "main"
    assert board_of("300750") == "gem"
    assert board_of("301001") == "gem"
    assert board_of("688981") == "star"
    assert board_of("920001") == "bse"
    assert board_of("430047") == "bse"
    assert board_of("830799") == "bse"
    assert board_of("900901") == "main"
    assert board_of("200001") == "main"
    assert board_of("60051") == ""
    assert board_of("AAPL") == ""


def test_band_at_main():
    assert band_at("600519", "1996-12-15") == (None, "unbounded")
    assert band_at("600519", "1996-12-16") == (0.10, "main10")
    assert band_at("600519", "2024-01-01", True) == (0.05, "main5")
    assert band_at("600519", "2026-05-05", True) == (0.05, "main5")
    assert band_at("600519", "2026-05-06", True) == (0.10, "main10")
    assert band_at("000001", "2010-01-01", False) == (0.10, "main10")


def test_band_at_gem():
    assert band_at("300750", "2020-08-23") == (0.10, "gem10")
    assert band_at("300750", "2020-08-23", True) == (0.05, "gem5")
    assert band_at("300750", "2020-08-24") == (0.20, "gem20")
    assert band_at("300750", "2020-08-24", True) == (0.20, "gem20")
    assert band_at("301001", "2010-01-01") == (0.10, "gem10")


def test_band_at_star_bse():
    assert band_at("688981", "2019-07-22", True) == (0.20, "star20")
    assert band_at("920001", "2020-07-26") == (None, "unbounded")
    assert band_at("920001", "2020-07-27") == (0.30, "bse30")
    assert band_at("830799", "2024-01-01", True) == (0.30, "bse30")


def test_is_st_name():
    assert is_st_name("ST天龙")
    assert is_st_name("*ST天龙")
    assert is_st_name("S*ST前锋")
    assert is_st_name("SST前锋")
    assert is_st_name("*欣泰")
    assert is_st_name("*金亚")
    assert is_st_name("G*ST玉源")
    assert not is_st_name("天龙光电")
    assert not is_st_name("")


def test_ipo_len():
    assert ipo_len("688981", "2020-07-16") == 5
    assert ipo_len("300750", "2020-08-23") == 1
    assert ipo_len("300750", "2020-08-24") == 5
    assert ipo_len("600519", "2023-04-09") == 1
    assert ipo_len("600519", "2023-04-10") == 5
    assert ipo_len("920001", "2024-01-01") == 1
    assert ipo_len("600519", "2001-08-27") == 1


def test_cent():
    assert cent(10.005) == 10.01
    assert cent(10.994) == 10.99
    assert cent(10.995) == 11.00
    assert cent(9.5) == 9.5
    assert cent(None) is None
    assert cent(float("nan")) is None
    assert cent(float("inf")) is None


def test_merge_bars():
    nr = [{"date": "2024-01-02", "close": 10.0, "high": 10.1,
           "low": 9.9, "percent": 0.01}]
    out = merge_bars(nr, [{"date": "2024-01-02", "close": 20.0}])
    assert out[0]["factor"] == 2.0
    assert out[0]["high"] == 10.1
    out2 = merge_bars(nr, [])
    assert out2[0]["factor"] is None
    assert merge_bars([], []) == []


def test_st_segments_before_first():
    segs = st_segments([
        {"name": "ST测试", "start_date": "2010-01-01", "end_date": "2012-12-31"},
        {"name": "测试股份", "start_date": "2013-01-01", "end_date": ""},
    ])
    bars = [_bar("2009-12-31", 10.0, 0.0),
            _bar("2011-01-01", 10.0, 0.0),
            _bar("2013-01-02", 10.0, 0.0)]
    rows = build_rows("600000", bars, segs, first_is_listing=False)
    assert rows[0]["is_st"] is False and rows[0]["name"] == ""
    assert rows[0]["rule"] == "main10"
    assert rows[1]["is_st"] is True and rows[1]["rule"] == "main5"
    assert rows[2]["is_st"] is False and rows[2]["rule"] == "main10"


def test_build_rows_st5_and_basis():
    bars = [
        _bar("2024-01-02", 10.0, 0.0),
        _bar("2024-01-03", 10.5, 0.05),
        _bar("2024-01-04", 11.03, 0.0505),
    ]
    segs = st_segments([{"name": "ST测试", "start_date": "2024-01-01", "end_date": ""}])
    rows = build_rows("600000", bars, segs, first_is_listing=False)
    assert [r["rule"] for r in rows] == ["main5", "main5", "main5"]
    assert rows[0]["basis"] == 10.0
    assert rows[1]["basis"] == 10.0
    assert rows[1]["limit_up"] == 10.5
    assert rows[1]["limit_down"] == 9.5
    assert rows[2]["basis"] == 10.5
    assert rows[2]["limit_up"] == 11.03
    assert rows[2]["is_st"] is True and rows[2]["name"] == "ST测试"


def test_build_rows_ex_rights():
    # 除权日因子从 1 跳到 1.02：参考前收 = 10/1.02 = 9.80，而不是 10.00
    bars = [
        _bar("2024-01-02", 10.0, 0.0, factor=1.0),
        _bar("2024-01-03", 9.9, -0.01, factor=1.02),
    ]
    rows = build_rows("600000", bars, [], first_is_listing=False)
    assert rows[1]["basis"] == 9.80
    assert rows[1]["limit_up"] == 10.78
    assert rows[1]["limit_down"] == 8.82


def test_build_rows_ipo():
    bars = [_bar(f"2024-01-{i:02d}", 15.0, 0.0) for i in range(1, 6)]
    bars.append(_bar("2024-01-08", 16.0, 16.0 / 15.0 - 1))
    rows = build_rows("688981", bars, [], first_is_listing=True)
    assert [r["rule"] for r in rows[:5]] == ["ipo"] * 5
    assert rows[5]["rule"] == "star20"
    assert rows[0]["basis"] is None and rows[0]["limit_up"] is None
    assert rows[5]["basis"] == 15.0
    assert rows[5]["limit_up"] == 18.0
    assert rows[5]["limit_down"] == 12.0


def test_build_rows_factor_noise_uses_percent():
    # 非除权日因子比值有 ~1e-6 噪声：192.23 会被算成 192.22（±1 分）。
    # 口径：比值未跳变时用 close/(1+percent)，与当日快照一致。
    bars = [
        _bar("2020-08-21", 192.23, 0.0202, factor=7.8576),
        _bar("2020-08-24", 202.01, 0.0509, factor=7.857601),
    ]
    rows = build_rows("300750", bars, [], first_is_listing=False)
    assert rows[1]["basis"] == 192.23
    assert rows[1]["limit_up"] == 230.68
    assert rows[1]["limit_down"] == 153.78


def test_build_rows_st_cutoff_2026():
    # 主板 ST 2026-05-06 起 5% → 10%
    bars = [_bar("2026-05-05", 10.0, 0.0), _bar("2026-05-06", 10.0, 0.0)]
    segs = st_segments([{"name": "*ST测试", "start_date": "2026-01-01",
                         "end_date": ""}])
    rows = build_rows("600000", bars, segs, first_is_listing=False)
    assert [r["rule"] for r in rows] == ["main5", "main10"]
    assert [r["band"] for r in rows] == [0.05, 0.10]


def test_build_rows_unbounded_no_price():
    bars = [
        _bar("2024-01-02", 10.0, 0.0),
        _bar("2024-01-03", 12.5, 0.25),
        _bar("2024-01-04", 0.0, None),
    ]
    rows = build_rows("600000", bars, [], first_is_listing=False)
    assert rows[1]["rule"] == "unbounded" and rows[1]["limit_up"] is None
    assert rows[1]["band"] == 0.10
    assert rows[2]["rule"] == "no_price" and rows[2]["limit_up"] is None


def test_build_rows_pre_1996():
    bars = [_bar("1996-12-13", 10.0, 0.0), _bar("1996-12-16", 10.2, 0.02)]
    rows = build_rows("600000", bars, [], first_is_listing=False)
    assert rows[0]["rule"] == "unbounded" and rows[0]["band"] is None
    assert rows[1]["rule"] == "main10" and rows[1]["band"] == 0.10
    assert rows[1]["basis"] == 10.0


def test_build_rows_empty():
    assert build_rows("600000", [], [], False) == []
