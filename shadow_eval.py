"""למידה: בודק מה קרה (5 ימי מסחר) למועמדים ביומן shadow_log.csv, ומשווה מתקבלים מול נדחים.
מייצר learning_report.txt. לא משנה פרמטרים אוטומטית - רק מצביע על מסננים שנראים כמזיקים/מועילים, כשיש מספיק נתונים."""
import csv
import json
import os
from datetime import date, datetime, timedelta

import pandas as pd

import config as C
from shadow import COLS, FILE

HORIZON = 5
MIN_N = 30


def evaluate(rows):
    todo = [r for r in rows if not r["r5"] and r["entry"] and r["stop"]
            and date.fromisoformat(r["date"]) <= date.today() - timedelta(days=HORIZON + 3)]
    if not todo:
        return 0
    import yfinance as yf
    tick = sorted({r["ticker"] for r in todo})
    start = min(r["date"] for r in todo)
    raw = yf.download(tick, start=start, interval="1d", auto_adjust=True, progress=False, group_by="ticker")
    n = 0
    for r in todo:
        try:
            df = raw[r["ticker"]] if len(tick) > 1 else raw
            df = df[["High", "Low", "Close"]].dropna()
            df.index = pd.to_datetime(df.index).tz_localize(None)
            fut = df[df.index > pd.Timestamp(r["date"])].head(HORIZON)
            if len(fut) < HORIZON:
                continue
            entry, stop, tgt = float(r["entry"]), float(r["stop"]), float(r["target"])
            risk = entry - stop
            res, out = None, "time"
            for _, b in fut.iterrows():
                if b["Low"] <= stop:          # שמרני: אם נגעו בשניהם באותו יום - סטופ
                    res, out = -1.0, "stop"
                    break
                if b["High"] >= tgt:
                    res, out = (tgt - entry) / risk, "target"
                    break
            if res is None:
                res = (float(fut["Close"].iloc[-1]) - entry) / risk
            res -= (2 * C.BT_SLIPPAGE_PCT * entry + (C.BT_STOP_SLIPPAGE_PCT * entry if out == "stop" else 0)) / risk
            r["r5"], r["outcome"] = f"{res:.3f}", out
            n += 1
        except Exception:
            continue
    return n


def stat(rs):
    v = [float(x["r5"]) for x in rs if x["r5"]]
    if not v:
        return "אין נתונים עדיין"
    w = sum(1 for x in v if x > 0) / len(v) * 100
    tg = sum(1 for x in rs if x["outcome"] == "target") / len(v) * 100
    st = sum(1 for x in rs if x["outcome"] == "stop") / len(v) * 100
    return f"{len(v)} מקרים | ממוצע {sum(v)/len(v):+.2f}R | חיוביים {w:.0f}% | יעד {tg:.0f}% | סטופ {st:.0f}%"


def avg(rs):
    v = [float(x["r5"]) for x in rs if x["r5"]]
    return (sum(v) / len(v), len(v)) if v else (None, 0)


def sleeve_section():
    L = []
    try:
        import broker
        if not os.path.exists("momentum_sleeve.json"):
            return ["סליל מומנטום: עדיין לא נבנה (ייבנה בסבב הקרוב)."]
        st = json.load(open("momentum_sleeve.json", encoding="utf-8"))
        syms, since = set(st.get("symbols", [])), st.get("rebalanced")
        if not syms or not since:
            return ["סליל מומנטום: עדיין לא נבנה."]
        pos = [p for p in broker._req("GET", "/v2/positions").json() if p["symbol"] in syms]
        cost = sum(abs(float(p["cost_basis"])) for p in pos)
        pl = sum(float(p["unrealized_pl"]) for p in pos)
        import yfinance as yf
        spy = yf.download("SPY", start=since, interval="1d", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
        spy_ret = (spy.iloc[-1] / spy.iloc[0] - 1) * 100 if len(spy) > 1 else 0.0
        mine = pl / cost * 100 if cost else 0.0
        L.append(f"סליל מומנטום (מאז {since}): {len(pos)} מניות | השקעה {cost:,.0f}$ | רווח לא ממומש {pl:+,.0f}$ ({mine:+.2f}%) | SPY באותה תקופה {spy_ret:+.2f}% | הפרש {mine - spy_ret:+.2f}%")
    except Exception as e:
        L.append(f"סליל מומנטום: לא ניתן לחשב ({str(e)[:80]})")
    return L


def main():
    rows = []
    if os.path.exists(FILE):
        with open(FILE, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        n = evaluate(rows)
        with open(FILE, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLS)
            w.writeheader()
            w.writerows(rows)
    else:
        n = 0
    L = [f"🧠 דוח למידה — {date.today():%d.%m.%Y}", f"ביומן {len(rows)} מועמדים, נבדקו עכשיו {n} חדשים (תוצאה תוך {HORIZON} ימי מסחר, יעד/סטופ כפי שנקבעו)", ""]
    kinds = {"accepted": "התקבלו ונשלחו", "not_picked": "עברו הכל אך לא נבחרו (אין מקום)", "rej_analyst": "נדחו: קונצנזוס אנליסטים",
             "rej_target": "נדחו: יעד אנליסטים נמוך מהיעד שלנו", "rej_earnings": "נדחו: דוחות קרובים", "rej_sector": "נדחו: תקרת סקטור"}
    acc = [r for r in rows if r["kind"] == "accepted"]
    for k, name in kinds.items():
        L.append(f"{name}: " + stat([r for r in rows if r["kind"] == k]))
    L.append("")
    a_avg, a_n = avg(acc)
    flags = []
    for k in ("rej_analyst", "rej_target", "rej_earnings", "rej_sector", "not_picked"):
        m, c = avg([r for r in rows if r["kind"] == k])
        if m is not None and c >= MIN_N and a_n >= MIN_N:
            if m > (a_avg or 0) + 0.10:
                flags.append(f"• '{kinds[k]}' דווקא הניבו יותר ({m:+.2f}R מול {a_avg:+.2f}R): שווה להקל את המסנן הזה.")
            elif m < (a_avg or 0) - 0.10:
                flags.append(f"• '{kinds[k]}' אכן גרועים יותר ({m:+.2f}R מול {a_avg:+.2f}R): המסנן מועיל, להשאיר.")
    L.append("מסקנות (רק עם 30+ מקרים בכל צד):")
    L += flags or ["• אין עדיין מספיק נתונים למסקנה. ממשיכים לצבור."]
    L.append("")
    # פילוח המתקבלים לפי מאפיינים
    def bucket(name, fn):
        g = {}
        for r in acc:
            if r["r5"]:
                g.setdefault(fn(r), []).append(r)
        if g:
            L.append(name + ": " + " | ".join(f"{k}: {avg(v)[0]:+.2f}R ({len(v)})" for k, v in sorted(g.items())))
    bucket("לפי שכבה (1=חמורה)", lambda r: r["tier"])
    bucket("לפי RSI", lambda r: "≤40" if float(r["rsi"]) <= 40 else ("41-48" if float(r["rsi"]) <= 48 else ">48"))
    bucket("לפי שינוי SPY ביום הכניסה", lambda r: "שלילי" if r["spy_chg_pct"] and float(r["spy_chg_pct"]) < 0 else "חיובי")
    bucket("לפי סקטור", lambda r: r["sector"] or "?")
    L.append("")
    L += sleeve_section()
    L += ["", "תוצאות עבר אינן תחזית; מדגם קטן. מסחר דמה בלבד."]
    text = "\n".join(L)
    print(text)
    open("learning_report.txt", "w", encoding="utf-8").write(text + "\n")
    if os.getenv("SEND") == "1" or datetime.now().weekday() == 4 and os.getenv("TELEGRAM_BOT_TOKEN"):
        from notify import send_telegram
        send_telegram(text)


if __name__ == "__main__":
    main()
