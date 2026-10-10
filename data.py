import io
import os

import pandas as pd
import requests
import yfinance as yf


def get_sp500():
    """רשימת S&P 500 מוויקיפדיה. אם נכשל - קובץ tickers.txt (טיקר בכל שורה)."""
    try:
        r = requests.get(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=30,
        )
        r.raise_for_status()
        table = pd.read_html(io.StringIO(r.text))[0]
        return sorted(table["Symbol"].str.replace(".", "-", regex=False).tolist())
    except Exception as e:
        print(f"Wikipedia failed: {e}")
        if os.path.exists("tickers.txt"):
            with open("tickers.txt", encoding="utf-8") as f:
                return [x.strip() for x in f if x.strip()]
        raise


def download(tickers, period="2y", chunk=100):
    """מוריד נתונים יומיים. מחזיר dict של ticker -> DataFrame (OHLCV)."""
    out = {}
    for i in range(0, len(tickers), chunk):
        part = tickers[i : i + chunk]
        try:
            raw = yf.download(
                part, period=period, interval="1d", group_by="ticker",
                auto_adjust=True, threads=True, progress=False,
            )
        except Exception as e:
            print(f"download failed for chunk {i}: {e}")
            continue
        for t in part:
            try:
                df = raw[t][["Open", "High", "Low", "Close", "Volume"]].dropna()
            except KeyError:
                continue
            if len(df) < 230:
                continue
            df.index = pd.to_datetime(df.index).tz_localize(None)
            out[t] = df
    return out
