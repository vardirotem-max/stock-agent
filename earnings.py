"""תאריך הדוח הרבעוני הבא מ-Yahoo Finance (דרך yfinance). מקור לא רשמי - משמש כפילטר סיכון."""
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

import yfinance as yf

import config as C


def today_us():
    return datetime.now(ZoneInfo("America/New_York")).date()


def _to_date(x):
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    try:
        return datetime.fromisoformat(str(x)[:10]).date()
    except Exception:
        return None


def next_earnings(ticker, today=None):
    """התאריך הקרוב ביותר שלא עבר, או None אם אין נתון."""
    today = today or today_us()
    try:
        cal = yf.Ticker(ticker).calendar
        raw = cal.get("Earnings Date") if isinstance(cal, dict) else None
        if raw is None:
            return None
        dates = [d for d in (_to_date(x) for x in (raw if isinstance(raw, (list, tuple)) else [raw])) if d]
        future = sorted(d for d in dates if d >= today)
        time.sleep(0.3)
        return future[0] if future else None
    except Exception as e:
        print(f"earnings lookup failed for {ticker}: {e}")
        return None


def blocked(ed, today=None):
    if ed is None:
        return C.REQUIRE_EARNINGS_DATA
    today = today or today_us()
    return 0 <= (ed - today).days <= C.EARNINGS_BLOCK_DAYS


def describe(ed, today=None):
    if ed is None:
        return "דוח רבעוני: תאריך לא ידוע"
    today = today or today_us()
    return f"דוח רבעוני: {ed:%d.%m} (בעוד {(ed - today).days} ימים)"


if __name__ == "__main__":  # בדיקה עצמית של מקור הנתונים על מניות כלליות
    out = []
    for t in ("AAPL", "MSFT", "JPM"):
        ed = next_earnings(t)
        out.append(f"{t}: {describe(ed)} | חסום={blocked(ed)}")
    print("\n".join(out))
    open("earnings_selftest.txt", "w", encoding="utf-8").write("\n".join(out) + "\n")
