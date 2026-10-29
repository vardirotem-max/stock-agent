import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import pandas as pd
import config as C
import broker
from scanner import position_size
from strategy import simulate


def candles(rows):
    idx = pd.date_range("2026-01-05", periods=len(rows), freq="B")
    return pd.DataFrame(rows, index=idx, columns=["Open", "High", "Low", "Close"])


def test_position_size_risk_based():
    # סיכון 0.25% מ-100k = 250$; 5$ סיכון למניה = 50 מניות
    assert position_size(100.0, 95.0) == int(C.ACCOUNT_SIZE * C.RISK_PER_TRADE_PCT / 100 / 5)


def test_position_size_capped_by_notional():
    # סטופ צמוד מאוד: התקרה לפי שווי פוזיציה חלה
    q = position_size(100.0, 99.9)
    assert q * 100.0 <= C.ACCOUNT_SIZE * C.MAX_POSITION_PCT / 100 + 100


def test_position_size_invalid():
    assert position_size(100.0, 100.0) == 0
    assert position_size(100.0, 101.0) == 0


def test_profit_cap_price():
    assert broker.profit_cap_price(100.0, 50) == round(100.0 + C.POSITION_PROFIT_CAP / 50, 2)
    assert broker.profit_cap_price(100.0, 0) is None


def test_simulate_target_hit():
    fut = candles([[100, 101, 99, 100], [100, 111, 100, 110]])
    r = simulate(fut, 100.0, 95.0, 110.0)
    assert r["status"] == "target" and r["r"] > 0


def test_simulate_stop_hit_same_candle_is_stop():
    fut = candles([[100, 111, 94, 100]])
    assert simulate(fut, 100.0, 95.0, 110.0)["status"] == "stopped"


def test_simulate_expires_without_fill():
    fut = candles([[120, 121, 119, 120]] * (C.ORDER_VALID_DAYS + 1))
    assert simulate(fut, 100.0, 95.0, 110.0)["status"] == "expired"


def test_config_sanity():
    assert C.RISK_PER_TRADE_PCT > 0 and C.MAX_OPEN_POSITIONS >= 1
    assert C.DAILY_LOSS_LIMIT > 0 and C.DAILY_PROFIT_TARGET > 0
    assert "SPY" in C.CORE_SYMBOLS
    # הסיכון בדולרים לא גדול מכפול התקרה (יחס סיכוי-סיכון סביר)
    assert C.ACCOUNT_SIZE * C.RISK_PER_TRADE_PCT / 100 <= 2 * C.POSITION_PROFIT_CAP


def test_paper_only():
    assert "paper-api" in broker.BASE


def test_momentum_select_ranks_and_filters():
    import numpy as np, pandas as pd
    from momentum_sleeve import select
    idx = pd.bdate_range("2025-01-01", periods=300)
    up = pd.Series(np.linspace(50, 200, 300), index=idx)      # מומנטום חזק
    mid = pd.Series(np.linspace(50, 100, 300), index=idx)     # מומנטום בינוני
    down = pd.Series(np.linspace(200, 80, 300), index=idx)    # מתחת ל-SMA200
    px = pd.DataFrame({"UP": up, "MID": mid, "DOWN": down})
    vol = pd.DataFrame(1_000_000.0, index=idx, columns=px.columns)
    assert select(px, vol, 2) == ["UP", "MID"]
