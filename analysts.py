"""המלצות אנליסטים מ-Yahoo Finance (דרך yfinance). מקור לא רשמי - משמש כפילטר, לא כטריגר."""
import time

import yfinance as yf

import config as C


def get_analyst(ticker):
    """מחזיר dict עם קונצנזוס או None אם אין נתונים / שגיאה."""
    try:
        info = yf.Ticker(ticker).info
        mean = info.get("recommendationMean")
        n = info.get("numberOfAnalystOpinions")
        if mean is None or n is None:
            return None
        tp = info.get("targetMeanPrice")
        time.sleep(0.4)
        return {
            "mean": float(mean),
            "n": int(n),
            "target": float(tp) if tp else None,
            "key": info.get("recommendationKey") or "",
        }
    except Exception as e:
        print(f"analyst data failed for {ticker}: {e}")
        return None


def passes(a, close):
    if a is None or a["n"] < C.ANALYST_MIN_OPINIONS:
        return not C.REQUIRE_ANALYST_DATA
    if a["mean"] > C.ANALYST_MAX_MEAN:
        return False
    if a["target"] is not None and a["target"] < close * (1 + C.ANALYST_MIN_UPSIDE):
        return False
    return True


def describe(a, close):
    if a is None or a["n"] < C.ANALYST_MIN_OPINIONS:
        return "אנליסטים: אין מספיק נתונים"
    s = f"אנליסטים: {a['key']} ({a['mean']:.1f}/5, {a['n']} אנליסטים)"
    if a["target"]:
        s += f" | יעד ממוצע {a['target']:.0f} ({(a['target'] / close - 1) * 100:+.0f}%)"
    return s
