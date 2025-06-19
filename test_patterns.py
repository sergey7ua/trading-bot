import pytest
import pandas as pd
import requests_mock
from trading_bot import is_bullish_engulfing, is_bearish_engulfing, is_hammer, is_shooting_star, analyze, get_klines

def test_bullish_engulfing():
    assert is_bullish_engulfing(1.0, 0.9, 0.89, 1.1) == True
    assert is_bullish_engulfing(1.0, 1.1, 1.0, 1.0) == False

def test_bearish_engulfing():
    assert is_bearish_engulfing(1.0, 1.1, 1.12, 0.9) == True
    assert is_bearish_engulfing(1.0, 0.9, 1.0, 1.0) == False

def test_hammer():
    assert is_hammer(1.0, 1.01, 1.015, 0.97) == True
    assert is_hammer(1.0, 1.01, 1.05, 0.99) == False

def test_shooting_star():
    assert is_shooting_star(1.0, 1.01, 1.04, 0.995) == True
    assert is_shooting_star(1.0, 1.01, 1.02, 0.95) == False

def test_analyze_buy_signal():
    df = pd.DataFrame({
        'open': [1.0, 0.9, 0.89],
        'close': [0.9, 1.1, 1.0],
        'high': [1.0, 1.15, 1.05],
        'low': [0.85, 0.88, 0.97],
        'volume': [100, 150, 200]
    })
    signal = analyze(df)
    assert signal == "BUY"

def test_analyze_no_signal():
    df = pd.DataFrame({
        'open': [1.0, 1.0, 1.0],
        'close': [1.0, 1.0, 1.0],
        'high': [1.05, 1.05, 1.05],
        'low': [0.95, 0.95, 0.95],
        'volume': [100, 100, 100]
    })
    signal = analyze(df)
    assert signal is None

def test_get_klines():
    with requests_mock.Mocker() as m:
        m.get(
            "https://api.twelvedata.com/time_series",
            json={
                "values": [
                    {"open": "1.0", "high": "1.05", "low": "0.95", "close": "1.0", "volume": "100"},
                    {"open": "1.0", "high": "1.05", "low": "0.95", "close": "1.0", "volume": "100"}
                ]
            },
            headers={'X-RateLimit-Remaining': '10'}
        )
        df = get_klines("EUR/USD", "1min", 2)
        assert len(df) == 2
        assert df["close"].iloc[-1] == 1.0