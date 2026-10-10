"""מחקר סוג אסטרטגיה אחר: רוטציית מומנטום חודשית על קרנות סל (ETF), מול החזקת SPY.
קרנות סל אינן סובלות מ-survivorship bias של מניות בודדות. הפרמטרים מצומצמים בכוונה כדי לא להתאים לעבר.
לא משנה את הבוט החי."""
import os

import numpy as np
import pandas as pd
import yfinance as yf

from notify import send_telegram

RISK = ["SPY", "QQQ", "IWM", "EFA", "EEM", "GLD", "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU"]
CASH = "SHY"      # תחליף למזומן (אג"ח קצר)
COST = 0.0005     # 0.05% לכל כיוון, על כל שינוי משקל
SPLIT = pd.Timestamp("2020-01-01")
START = "2008-01-01"


def load():
    px = yf.download(RISK + [CASH, "IEF"], start=START, interval="1d", auto_adjust=True, progress=False)["Close"]
    px.index = pd.to_datetime(px.index).tz_localize(None)
    return px.dropna(how="all")


def weights_trend(px):
    """SPY כשהוא מעל ממוצע 200, אחרת SHY. מתעדכן בסוף כל חודש."""
    sma = px["SPY"].rolling(200).mean()
    w = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    ok = (px["SPY"] > sma)
    w["SPY"], w[CASH] = ok.astype(float), (~ok).astype(float)
    return w.where(px["SPY"].notna() & sma.notna())


def weights_momentum(px, months, top_n):
    sma200 = px.rolling(200).mean()
    me = px.groupby([px.index.year, px.index.month]).tail(1).index  # סוף כל חודש מסחר
    w = pd.DataFrame(np.nan, index=px.index, columns=px.columns)
    look = int(round(months * 21))
    for d in me:
        i = px.index.get_loc(d)
        if i < max(look, 200):
            continue
        score = px[RISK].iloc[i] / px[RISK].iloc[i - look] - 1
        elig = score[(score > 0) & (px[RISK].iloc[i] > sma200[RISK].iloc[i])].dropna()
        pick = elig.sort_values(ascending=False).head(top_n).index
        row = pd.Series(0.0, index=px.columns)
        for t in pick:
            row[t] = 1.0 / top_n
        row[CASH] = 1.0 - row.sum()
        w.loc[d] = row
    return w.ffill()


def backtest(px, w):
    rets = px.pct_change().fillna(0.0)
    w = w.reindex(px.index).shift(1).dropna(how="all").fillna(0.0)   # החלטה בסוף חודש, פעולה ביום המסחר הבא
    r = (w * rets.loc[w.index]).sum(axis=1)
    turnover = w.diff().abs().sum(axis=1).fillna(0.0)
    return r - turnover * COST


def metrics(r):
    r = r.dropna()
    if len(r) < 60:
        return None
    eq = (1 + r).cumprod()
    yrs = len(r) / 252
    return {"cagr": (eq.iloc[-1] ** (1 / yrs) - 1) * 100, "dd": ((eq / eq.cummax()) - 1).min() * 100,
            "sharpe": r.mean() / r.std() * np.sqrt(252) if r.std() else 0.0, "total": (eq.iloc[-1] - 1) * 100}


def fmt(m):
    return "—" if m is None else f"תשואה שנתית {m['cagr']:+.1f}% | משיכה {m['dd']:.0f}% | שארפ {m['sharpe']:.2f}"


def main():
    px = load()
    spy = px["SPY"].pct_change().fillna(0.0)
    strategies = {"SPY — החזקה פשוטה": spy, "SPY מעל ממוצע 200, אחרת אג\"ח קצר": backtest(px, weights_trend(px))}
    for months in (3, 6, 12):
        for n in (1, 3, 5):
            strategies[f"רוטציית מומנטום {months} חודשים, {n} נכסים"] = backtest(px, weights_momentum(px, months, n))

    start = max(s.dropna().index[0] for s in strategies.values() if len(s.dropna()))
    L = ["🔬 רוטציית מומנטום על קרנות סל (אחרי עלויות)", f"נתונים מ-{start:%m.%Y}. בנייה: עד 2019 | בדיקה: 2020 ואילך (כולל קורונה, ירידות 2022)", ""]
    base_tr = metrics(spy[(spy.index >= start) & (spy.index < SPLIT)])
    base_te = metrics(spy[spy.index >= SPLIT])
    rows, passing = [], []
    for name, r in strategies.items():
        r = r[r.index >= start]
        a, b = metrics(r[r.index < SPLIT]), metrics(r[r.index >= SPLIT])
        rows.append(f"{name}\n  בנייה: {fmt(a)}\n  בדיקה: {fmt(b)}")
        if name.startswith("רוטציית") or name.startswith("SPY מעל"):
            if a and b and a["sharpe"] > base_tr["sharpe"] and b["sharpe"] > base_te["sharpe"] and b["dd"] > base_te["dd"]:
                passing.append(name)
    L += rows
    L += ["", "מנצחת את SPY ביחס תשואה-סיכון (שארפ גבוה יותר) ובמשיכה קטנה יותר, גם בבנייה וגם בבדיקה:",
          ("  " + "\n  ".join(passing)) if passing else "  אף אסטרטגיה לא עברה את שני התנאים."]
    ok_ret = [n for n, r in strategies.items() if n != "SPY — החזקה פשוטה" and metrics(r[r.index >= SPLIT]) and base_te
              and metrics(r[r.index >= SPLIT])["cagr"] > base_te["cagr"] and metrics(r[(r.index >= start) & (r.index < SPLIT)])["cagr"] > base_tr["cagr"]]
    L.append("מנצחות את SPY גם בתשואה שנתית גולמית בשתי התקופות: " + (", ".join(ok_ret) if ok_ret else "אין"))
    L += ["", f"נבדקו {len(strategies) - 1} אסטרטגיות — סביר שאחת תיראה טוב במקרה. הנכסים נבחרו בדיעבד.",
          "תוצאות עבר אינן תחזית. מסחר דמה בלבד."]
    text = "\n".join(L)
    print(text)
    with open("research2_report.txt", "w", encoding="utf-8") as f:
        f.write(text + "\n")
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        send_telegram(text[:3900])


if __name__ == "__main__":
    main()
