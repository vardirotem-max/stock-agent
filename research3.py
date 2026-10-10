"""מחקר אסטרטגיות בסיכון גבוה: קרנות ממונפות (3x) עם פילטר מגמה ורוטציה, מול SPY.
חלק א: קרנות ממונפות אמיתיות (2011 ואילך). חלק ב': מבחן לחץ - ממונפות 3x מדומות על QQQ מ-1999 ועל SPY מ-1993.
לא משנה את הבוט החי."""
import os

import numpy as np
import pandas as pd
import yfinance as yf

from notify import send_telegram

COST = 0.0005
SPLIT = pd.Timestamp("2020-01-01")
RF = 0.02  # ריבית מדומה לחלק ב'
REAL = {"TQQQ": "QQQ", "UPRO": "SPY", "SOXL": "SOXX", "TECL": "XLK"}  # ממונפת -> מדד בסיס לאות המגמה


def dl(tickers, start):
    px = yf.download(tickers, start=start, interval="1d", auto_adjust=True, progress=False)["Close"]
    px.index = pd.to_datetime(px.index).tz_localize(None)
    return px.dropna(how="all")


def trend_ret(asset_ret, signal_px, cash_ret, window=200):
    """מחזיק את הנכס כשהמדד מעל ממוצע 200 (אות של אתמול), אחרת מזומן. עלות על כל מעבר."""
    on = (signal_px > signal_px.rolling(window).mean()).shift(1)
    valid = on.notna()
    on = on.fillna(False).astype(float)
    r = on * asset_ret + (1 - on) * cash_ret - on.diff().abs().fillna(0) * COST
    return r[valid]


def rotation_ret(px, lev, base, cash, months=6, top_n=1):
    """חודשי: הנכסים הממונפים עם המומנטום הגבוה ביותר שהמדד שלהם מעל ממוצע 200; אחרת מזומן."""
    look = int(months * 21)
    sma = {b: px[b].rolling(200).mean() for b in set(base.values())}
    me = px.groupby([px.index.year, px.index.month]).tail(1).index
    w = pd.DataFrame(np.nan, index=px.index, columns=lev + [cash])
    for d in me:
        i = px.index.get_loc(d)
        if i < max(look, 200):
            continue
        sc = {t: px[t].iloc[i] / px[t].iloc[i - look] - 1 for t in lev if pd.notna(px[t].iloc[i]) and pd.notna(px[t].iloc[i - look])
              and px[base[t]].iloc[i] > sma[base[t]].iloc[i]}
        pick = [t for t, s in sorted(sc.items(), key=lambda kv: -kv[1]) if s > 0][:top_n]
        row = pd.Series(0.0, index=w.columns)
        for t in pick:
            row[t] = 1.0 / top_n
        row[cash] = 1.0 - row.sum()
        w.loc[d] = row
    w = w.ffill().shift(1).dropna(how="all").fillna(0.0)
    rets = px[lev + [cash]].pct_change().fillna(0.0).loc[w.index]
    return (w * rets).sum(axis=1) - w.diff().abs().sum(axis=1).fillna(0) * COST


def metrics(r):
    r = r.dropna()
    if len(r) < 120:
        return None
    eq = (1 + r).cumprod()
    yrs = len(r) / 252
    yearly = (1 + r).groupby(r.index.year).prod() - 1
    return {"cagr": (eq.iloc[-1] ** (1 / yrs) - 1) * 100, "dd": ((eq / eq.cummax()) - 1).min() * 100,
            "sharpe": r.mean() / r.std() * np.sqrt(252) if r.std() else 0.0, "worst": yearly.min() * 100}


def fmt(m):
    return "—" if m is None else f"שנתית {m['cagr']:+.0f}% | משיכה {m['dd']:.0f}% | שארפ {m['sharpe']:.2f} | שנה גרועה {m['worst']:+.0f}%"


def synth3x(ret, lev=3.0, er=0.0095):
    return lev * ret - (lev - 1) * RF / 252 - er / 252


def split_report(name, r, lo, hi=None):
    r = r[r.index >= lo]
    if hi is not None:
        r = r[r.index < hi]
    return metrics(r)


def main():
    L = ["🔬 אסטרטגיות בסיכון גבוה (קרנות ממונפות), אחרי עלויות", ""]
    # ---- חלק א: ממונפות אמיתיות
    px = dl(list(REAL) + list(set(REAL.values())) + ["SPY", "SHY"], "2010-06-01")
    px = px.dropna(subset=["SPY", "SHY"])
    cash = px["SHY"].pct_change().fillna(0.0)
    strat = {"SPY — החזקה פשוטה": px["SPY"].pct_change().fillna(0.0)}
    for lev, b in REAL.items():
        strat[f"{lev} — החזקה פשוטה"] = px[lev].pct_change().fillna(0.0)
        strat[f"{lev} — רק כש-{b} מעל ממוצע 200"] = trend_ret(px[lev].pct_change().fillna(0.0), px[b], cash)
    lev_list = list(REAL)
    for n in (1, 2):
        strat[f"רוטציה חודשית (מומנטום 6 חודשים), {n} נכסים ממונפים"] = rotation_ret(px, lev_list, REAL, "SHY", 6, n)
    start = max(s.dropna().index[0] for s in strat.values())
    start = max(start, pd.Timestamp("2011-06-01"))
    L += [f"חלק א — קרנות אמיתיות. נתונים מ-{start:%m.%Y}. בנייה: עד 2019 | בדיקה: 2020 ואילך", ""]
    base_tr, base_te = split_report("", strat["SPY — החזקה פשוטה"], start, SPLIT), split_report("", strat["SPY — החזקה פשוטה"], SPLIT)
    winners = []
    for name, r in strat.items():
        a, b = split_report(name, r, start, SPLIT), split_report(name, r, SPLIT)
        L += [name, f"  בנייה: {fmt(a)}", f"  בדיקה: {fmt(b)}"]
        if "החזקה פשוטה" not in name and a and b and a["cagr"] > base_tr["cagr"] and b["cagr"] > base_te["cagr"]:
            winners.append((name, a, b))
    # ---- חלק ב: מבחן לחץ מדומה
    q = dl(["QQQ", "SPY"], "1993-01-01")
    L += ["", "חלק ב — מבחן לחץ: ממונפות 3x מדומות (קירוב: 3 × תשואה יומית פחות עלות מימון ודמי ניהול), כולל קריסת 2000 ו-2008", ""]
    stress = []
    for und, lo in (("QQQ", pd.Timestamp("1999-06-01")), ("SPY", pd.Timestamp("1993-06-01"))):
        ur = q[und].pct_change().dropna()
        r3 = synth3x(ur)
        cash_r = pd.Series(RF / 252, index=ur.index)
        for name, r in ((f"{und} 3x — החזקה פשוטה", r3), (f"{und} 3x — רק מעל ממוצע 200", trend_ret(r3, q[und], cash_r)),
                        (f"{und} — החזקה פשוטה (ללא מינוף)", ur)):
            m = split_report(name, r, lo)
            L += [name, f"  {fmt(m)}"]
            if "רק מעל" in name:
                stress.append((name, m))
    L += ["", "סיכום:"]
    if winners:
        for name, a, b in winners:
            L.append(f"• {name}: מנצחת את SPY בתשואה שנתית בשתי התקופות ({a['cagr']:+.0f}% / {b['cagr']:+.0f}%), משיכה {a['dd']:.0f}% / {b['dd']:.0f}%")
    else:
        L.append("• אף אסטרטגיה ממונפת לא ניצחה את SPY בתשואה בשתי התקופות.")
    for name, m in stress:
        L.append(f"• מבחן לחץ — {name}: משיכה מקסימלית {m['dd']:.0f}%, שנה גרועה {m['worst']:+.0f}%")
    L += ["", "אזהרות: ממונפות מאבדות ערך בשווקים תנודתיים; 2011-2026 היו שנים טובות במיוחד לשוק; נבדקו ~12 אסטרטגיות (סיכוי להתאמה מקרית).",
          "מסחר דמה בלבד. תוצאות עבר אינן תחזית."]
    text = "\n".join(L)
    print(text)
    with open("research3_report.txt", "w", encoding="utf-8") as f:
        f.write(text + "\n")
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        send_telegram(text[:3900])


if __name__ == "__main__":
    main()
