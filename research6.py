"""מחקר 6: (א) האם חסימת דוחות 14 יום מוצדקת? (ב) האם הרחבת היקום (S&P 400/600) מוסיפה עסקאות בלי לפגוע בתוחלת?
משתמש באסטרטגיית הפולבק הקיימת ובפרמטרי config (RR נקבע ב-RR_OVERRIDE). בנייה עד 2022 | בדיקה 2023+.
פילטר האנליסטים אינו ניתן לבדיקה היסטורית (אין נתוני עבר)."""
import io
import time

import numpy as np
import pandas as pd
import requests
import yfinance as yf

import config as C
from data import download, get_sp500
from strategy import add_indicators, compute_signals, simulate

SPLIT = pd.Timestamp("2023-01-01")


def wiki(page):
    r = requests.get(f"https://en.wikipedia.org/wiki/{page}", headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    for t in pd.read_html(io.StringIO(r.text)):
        for col in ("Symbol", "Ticker symbol", "Ticker"):
            if col in t.columns and len(t) > 300:
                return sorted(t[col].astype(str).str.replace(".", "-", regex=False).tolist())
    return []


def trades_for(tickers, label):
    raw = download(tickers + ["SPY"], period="8y")
    data = {t: add_indicators(d) for t, d in raw.items()}
    spy = data.pop("SPY")
    regime = spy["Close"] > spy["sma200"]
    rows = []
    for t, df in data.items():
        s = compute_signals(df)
        busy = None
        for i in np.flatnonzero(s["sig"].to_numpy()):
            if i >= len(s) - 1:
                continue
            d = s.index[i]
            if not bool(regime.get(d, False)):
                continue
            if busy is not None and d <= busy:
                continue
            sig = s.iloc[i]
            fut = s.iloc[i + 1:]
            res = simulate(fut, float(sig["entry"]), float(sig["stop"]), float(sig["target"]))
            st = res["status"]
            if st in ("pending", "expired", "open"):
                continue
            busy = res["exit_date"]
            risk = float(sig["entry"]) - float(sig["stop"])
            fill = res["fill_price"]
            cost = 2 * C.BT_SLIPPAGE_PCT * fill + (C.BT_STOP_SLIPPAGE_PCT * fill if st == "stopped" else 0)
            rows.append({"ticker": t, "signal": d, "fill": res["fill_date"], "status": st, "r": res["r"] - cost / risk})
    df = pd.DataFrame(rows)
    df["universe"] = label
    return df, len(data)


def st(df):
    if df.empty:
        return "אין עסקאות"
    r = df["r"]
    w, l = r[r > 0].sum(), abs(r[r <= 0].sum())
    return f"{len(r)} עסקאות | הצלחה {(r > 0).mean()*100:.0f}% | ממוצע {r.mean():+.3f}R | PF {(w / l if l else 9.99):.2f}"


def earnings_hist(tickers):
    out = {}
    for t in tickers:
        try:
            ed = yf.Ticker(t).get_earnings_dates(limit=40)
            if ed is not None and len(ed):
                out[t] = sorted(pd.to_datetime(ed.index).tz_localize(None).normalize().unique())
        except Exception:
            pass
        time.sleep(0.25)
    return out


def main():
    L = [f"🔬 מחקר 6 — פולבק קיים (RR {C.RR}, סטופ {C.STOP_ATR} ATR, RSI≤{C.RSI_MAX}), 8 שנים, אחרי החלקות", ""]
    sp, n_sp = trades_for(get_sp500(), "S&P 500")
    L.append(f"יקום S&P 500 ({n_sp} מניות): " + st(sp))
    extra = []
    for page, name in (("List_of_S%26P_400_companies", "S&P 400"), ("List_of_S%26P_600_companies", "S&P 600")):
        try:
            tk = wiki(page)
            df, n = trades_for(tk, name)
            L.append(f"יקום {name} ({n} מניות): " + st(df))
            for per, m in (("בנייה", df["signal"] < SPLIT), ("בדיקה", df["signal"] >= SPLIT)):
                L.append(f"   {per}: " + st(df[m]))
            extra.append(df)
        except Exception as e:
            L.append(f"{name}: נכשל ({e})")
    for per, m in (("בנייה", sp["signal"] < SPLIT), ("בדיקה", sp["signal"] >= SPLIT)):
        L.append(f"   S&P 500 {per}: " + st(sp[m]))
    yrs = (sp["signal"].max() - sp["signal"].min()).days / 365
    L.append(f"קצב עסקאות בשנה (S&P 500): {len(sp)/yrs:.0f}" + "".join(f" | {e['universe'].iloc[0]}: {len(e)/yrs:.0f}" for e in extra if len(e)))
    L.append("")

    # --- השפעת דוחות ---
    allt = pd.concat([sp] + extra, ignore_index=True)
    sample = sorted(allt["ticker"].unique())
    L.append(f"— השפעת דוחות רבעוניים ({len(sample)} מניות עם עסקאות; תאריכי עבר מ-Yahoo, עד ~10 שנים אחורה) —")
    eh = earnings_hist(sample)
    L.append(f"נמצאו תאריכי דוחות ל-{len(eh)} מניות")
    gaps = []
    for r in allt.itertuples():
        e = eh.get(r.ticker)
        if not e:
            gaps.append(np.nan)
            continue
        after = [x for x in e if x >= pd.Timestamp(r.fill).normalize()]
        # המרחק בימים מהכניסה לדוח הבא (אם הדוח נפל בתוך החזקת העסקה או אחריה)
        gaps.append((after[0] - pd.Timestamp(r.fill).normalize()).days if after else np.nan)
    allt["gap"] = gaps
    k = allt.dropna(subset=["gap"])
    L.append(f"עסקאות עם נתון דוח: {len(k)} מתוך {len(allt)}")
    bins = [(0, 7), (8, 10), (11, 14), (15, 28), (29, 999)]
    for lo, hi in bins:
        L.append(f"דוח בעוד {lo}-{hi} ימים מהכניסה: " + st(k[(k["gap"] >= lo) & (k["gap"] <= hi)]))
    for per, m in (("בנייה", k["signal"] < SPLIT), ("בדיקה", k["signal"] >= SPLIT)):
        kk = k[m]
        L.append(f"  {per}: דוח ≤14 ימים: " + st(kk[kk["gap"] <= 14]) + " || אחרת: " + st(kk[kk["gap"] > 14]))
        L.append(f"  {per}: דוח ≤10 ימים: " + st(kk[kk["gap"] <= 10]) + " || אחרת: " + st(kk[kk["gap"] > 10]))
    L += ["", "פירוש: אם 'דוח ≤14' גרוע מ'אחרת' בשתי התקופות - החסימה מוצדקת. אם דומה - אפשר להקל ולקבל יותר עסקאות.",
          "מגבלות: survivorship bias, רשימות מדד נוכחיות, תאריכי דוח מ-Yahoo עלולים להיות חלקיים. מסחר דמה בלבד."]
    text = "\n".join(L)
    print(text)
    open("research6_report.txt", "w", encoding="utf-8").write(text + "\n")


if __name__ == "__main__":
    main()
