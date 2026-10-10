"""מחקר מסחר יומי: פריצת טווח הפתיחה (Opening Range Breakout), נרות 5 דקות מ-Alpaca (פיד IEX).
כניסה בפריצה של טווח N הדקות הראשונות, סטופ בצד הנגדי של הטווח, יעד k×סיכון, יציאה בסגירה אם אין. פוזיציה אחת ליום לסימבול.
לא משנה את הבוט החי."""
import os

import numpy as np
import pandas as pd
import requests

from notify import send_telegram

SYMBOLS = ["SPY", "QQQ", "TSLA", "NVDA", "AMD", "AAPL", "TQQQ", "SOXL"]
FETCH_FROM, EVAL_FROM, SPLIT = "2022-01-01", pd.Timestamp("2023-01-01"), pd.Timestamp("2025-01-01")
SLIP, STOP_SLIP = 0.0002, 0.0003  # החלקה לכל כיוון, ותוספת כשהסטופ מופעל
NY = "America/New_York"


def fetch(sym):
    h = {"APCA-API-KEY-ID": os.environ["ALPACA_KEY_ID"], "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET_KEY"]}
    rows, token = [], None
    while True:
        p = {"symbols": sym, "timeframe": "5Min", "start": f"{FETCH_FROM}T00:00:00Z", "limit": 10000, "feed": "iex", "adjustment": "split"}
        if token:
            p["page_token"] = token
        r = requests.get("https://data.alpaca.markets/v2/stocks/bars", headers=h, params=p, timeout=60)
        r.raise_for_status()
        j = r.json()
        rows += j.get("bars", {}).get(sym, [])
        token = j.get("next_page_token")
        if not token:
            break
    df = pd.DataFrame(rows).rename(columns={"t": "ts", "o": "o", "h": "h", "l": "l", "c": "c", "v": "v"})
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(NY)
    df = df.set_index("ts").sort_index()
    t = df.index.time
    return df[(t >= pd.Timestamp("09:30").time()) & (t <= pd.Timestamp("15:55").time())]


def days_of(df):
    daily_close = df["c"].groupby(df.index.date).last()
    sma = daily_close.rolling(200).mean()
    up = (daily_close > sma).shift(1)  # מגמה לפי הסגירה של אתמול
    for d, g in df.groupby(df.index.date):
        if len(g) >= 60:
            yield d, g, up.get(d)


def orb(g, n_bars, k, trend_only, up):
    o, h, l, c = (g[x].to_numpy() for x in ("o", "h", "l", "c"))
    hi, lo = h[:n_bars].max(), l[:n_bars].min()
    side = entry = None
    for i in range(n_bars, len(g) - 1):
        if h[i] > hi and l[i] < lo:
            return None
        if h[i] > hi:
            side, entry = 1, max(hi, o[i])
        elif l[i] < lo:
            side, entry = -1, min(lo, o[i])
        if side:
            break
    if side is None:
        return None
    if trend_only and ((side == 1 and up is not True) or (side == -1 and up is not False)):
        return None
    stop = lo if side == 1 else hi
    risk = abs(entry - stop)
    if risk / entry < 0.001 or risk / entry > 0.03:
        return None
    target = entry + side * k * risk
    exit_px, kind = c[-1], "close"
    for j in range(i + 1, len(g)):
        if (side == 1 and l[j] <= stop) or (side == -1 and h[j] >= stop):
            exit_px, kind = (min(stop, o[j]) if side == 1 else max(stop, o[j])), "stop"
            break
        if (side == 1 and h[j] >= target) or (side == -1 and l[j] <= target):
            exit_px, kind = target, "target"
            break
    gross = side * (exit_px - entry) / risk
    cost = (2 * SLIP * entry + (STOP_SLIP * entry if kind == "stop" else 0)) / risk
    return {"r": gross - cost, "kind": kind}


def stats(rs):
    rs = pd.Series(rs)
    if rs.empty:
        return None
    w, l_ = rs[rs > 0].sum(), abs(rs[rs <= 0].sum())
    return {"n": len(rs), "win": (rs > 0).mean() * 100, "exp": rs.mean(), "pf": w / l_ if l_ else float("inf"), "sum": rs.sum()}


def fmt(s):
    return "אין עסקאות" if s is None else f"{s['n']} עסקאות | הצלחה {s['win']:.0f}% | ממוצע {s['exp']:+.3f}R | PF {s['pf']:.2f} | סה\"כ {s['sum']:+.0f}R"


def main(fetch_fn=fetch):
    data = {}
    for s in SYMBOLS:
        try:
            data[s] = fetch_fn(s)
            print(s, len(data[s]), "bars")
        except Exception as e:
            print("fetch failed", s, e)
    variants = [
        ("טווח 15 דקות, יעד 1R", 3, 1.0, False), ("טווח 15 דקות, יעד 2R", 3, 2.0, False),
        ("טווח 30 דקות, יעד 1R", 6, 1.0, False), ("טווח 30 דקות, יעד 2R", 6, 2.0, False),
        ("טווח 30 דקות, יעד 2R, רק בכיוון המגמה היומית", 6, 2.0, True),
        ("טווח 15 דקות, יעד 2R, רק בכיוון המגמה היומית", 3, 2.0, True),
    ]
    L = ["🔬 מסחר יומי — פריצת טווח הפתיחה (5 דקות, נתוני IEX, אחרי החלקות)",
         f"סימבולים: {', '.join(data)} | בנייה: 2023-2024 | בדיקה: 2025 ואילך", ""]
    good = []
    for name, nb, k, tr in variants:
        res = []
        for s, df in data.items():
            for d, g, up in days_of(df):
                if pd.Timestamp(d) < EVAL_FROM:
                    continue
                t = orb(g, nb, k, tr, up)
                if t:
                    res.append((pd.Timestamp(d), s, t["r"]))
        a = stats([r for d, s, r in res if d < SPLIT])
        b = stats([r for d, s, r in res if d >= SPLIT])
        L += [name, f"  בנייה: {fmt(a)}", f"  בדיקה: {fmt(b)}"]
        if a and b and a["exp"] > 0.03 and b["exp"] > 0.03:
            good.append(name)
    L += ["", "וריאציות עם ממוצע חיובי (מעל 0.03R) גם בבנייה וגם בבדיקה: " + (", ".join(good) if good else "אין"),
          "", "מגבלות: נרות IEX מייצגים חלק קטן מהנפח (מחירים קרובים אך לא זהים לבורסות כולן), ייתכנו נרות חסרים; החלקות מוערכות;",
          "מסחר יומי בפועל סובל מהחלקות גדולות יותר בפריצות; נבדקו 6 וריאציות. תוצאות עבר אינן תחזית. מסחר דמה בלבד."]
    text = "\n".join(L)
    print(text)
    with open("research4_report.txt", "w", encoding="utf-8") as f:
        f.write(text + "\n")
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        send_telegram(text[:3900])


if __name__ == "__main__":
    main()
