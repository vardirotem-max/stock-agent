"""מחקר 5: אסטרטגיות מניות בודדות (מומנטום חוצה-מניות, קרבה לשיא, פריצות נפח, נמוך-תנודתיות) מול הפולבק הקיים.
בנייה: עד 2019 | בדיקה: 2020 ואילך. היקום: מרכיבי S&P 500 הנוכחיים (survivorship bias - לכן משווים גם לממוצע שווה של היקום עצמו).
לא משנה את הבוט החי."""
import numpy as np
import pandas as pd
import yfinance as yf

from data import get_sp500
from strategy import add_indicators, compute_signals

START, SPLIT = "2009-01-01", pd.Timestamp("2020-01-01")
COST = 0.0005  # לכל כיוון, על המחזור
TOPN = 20


def load(tickers):
    out = []
    for i in range(0, len(tickers), 100):
        part = tickers[i:i + 100]
        try:
            d = yf.download(part, start=START, interval="1d", auto_adjust=True, progress=False, group_by="column")
        except Exception as e:
            print("chunk fail", e)
            continue
        out.append(d)
    px = pd.concat([o["Close"] for o in out], axis=1)
    vol = pd.concat([o["Volume"] for o in out], axis=1)
    hi = pd.concat([o["High"] for o in out], axis=1)
    lo = pd.concat([o["Low"] for o in out], axis=1)
    op = pd.concat([o["Open"] for o in out], axis=1)
    for x in (px, vol, hi, lo, op):
        x.index = pd.to_datetime(x.index).tz_localize(None)
    px = px.loc[:, ~px.columns.duplicated()]
    return px, vol.loc[:, px.columns], hi.loc[:, px.columns], lo.loc[:, px.columns], op.loc[:, px.columns]


def perf(r):
    r = r.dropna()
    if len(r) < 50:
        return "n/a"
    yrs = len(r) / 252
    tot = (1 + r).prod()
    cagr = tot ** (1 / yrs) - 1
    curve = (1 + r).cumprod()
    dd = (curve / curve.cummax() - 1).min()
    sh = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0
    return f"שנתי {cagr*100:+.1f}% | משיכה {dd*100:.0f}% | שארפ {sh:.2f}"


def rebalance_strategy(px, score_fn, spy_filter=False, spy=None):
    me = px.groupby([px.index.year, px.index.month]).tail(1).index
    w = pd.DataFrame(np.nan, index=px.index, columns=px.columns)
    sma = spy.rolling(200).mean()
    for d in me:
        i = px.index.get_loc(d)
        if i < 260:
            continue
        s = score_fn(px, i).dropna()
        s = s[px.iloc[i][s.index].notna()]
        row = pd.Series(0.0, index=px.columns)
        if spy_filter and not (spy.iloc[i] > sma.iloc[i]):
            w.loc[d] = row
            continue
        pick = s.sort_values(ascending=False).head(TOPN).index
        row[pick] = 1.0 / TOPN
        w.loc[d] = row
    w = w.ffill().shift(1)
    rets = px.pct_change().fillna(0.0)
    r = (w.fillna(0.0) * rets).sum(axis=1)
    turn = w.fillna(0.0).diff().abs().sum(axis=1).fillna(0.0)
    r = r - turn * COST
    return r[w.notna().any(axis=1)]


def event_study(px, hi, lo, vol, spy, horizon=10):
    """תשואה קדימה של 10 ימים אחרי סיגנל (כניסה בסגירה, כמו קירוב), פחות הממוצע הלא-מותנה."""
    fwd = px.shift(-horizon) / px - 1
    res = {}
    allm = fwd.stack().mean()
    # פריצת 55 יום עם נפח
    hi55 = px.rolling(55).max().shift(1)
    vavg = vol.rolling(50).mean()
    sma200 = px.rolling(200).mean()
    brk = (px > hi55) & (vol > 1.5 * vavg) & (px > sma200)
    # פולבק (הסיגנל הקיים)
    pb = pd.DataFrame(False, index=px.index, columns=px.columns)
    for t in px.columns:
        try:
            df = pd.DataFrame({"Open": px[t], "High": hi[t], "Low": lo[t], "Close": px[t], "Volume": vol[t]}).dropna()
            if len(df) < 260:
                continue
            s = compute_signals(add_indicators(df))
            pb.loc[s.index, t] = s["sig"].values
        except Exception:
            continue
    # קרבה לשיא 52 שבועות + מגמה
    near = (px >= 0.95 * px.rolling(252).max()) & (px > sma200)
    # נמוך-תנודתיות לא כאירוע
    for name, mask in (("פריצת 55 יום + נפח x1.5", brk), ("פולבק קיים", pb), ("קרוב לשיא 52 שבועות", near)):
        for per, sel in (("בנייה", px.index < SPLIT), ("בדיקה", px.index >= SPLIT)):
            m = mask.loc[sel]
            f = fwd.loc[sel]
            base = f.stack().mean()
            ev = f[m].stack()
            res[(name, per)] = (len(ev), ev.mean() * 100, (ev.mean() - base) * 100, (ev > 0).mean() * 100)
    return res


def main():
    tk = get_sp500()
    px, vol, hi, lo, op = load(tk + ["SPY"])
    spy = px.pop("SPY")
    vol, hi, lo = vol.drop(columns="SPY"), hi.drop(columns="SPY"), lo.drop(columns="SPY")
    px = px.dropna(axis=1, thresh=500)
    vol, hi, lo = vol[px.columns], hi[px.columns], lo[px.columns]
    L = [f"🔬 מחקר 5 — אסטרטגיות מניות S&P 500 ({px.shape[1]} מניות, מ-{px.index[0]:%Y-%m})",
         "בנייה: עד 2019 | בדיקה: 2020+ | עלות 0.05% לכל כיוון | יחס: החזקת {0} מניות שוות משקל, איזון חודשי".format(TOPN),
         "אזהרה: היקום = מרכיבי המדד הנוכחי (survivorship bias מנפח תוצאות). ההשוואה ההוגנת היא מול 'ממוצע שווה של כל היקום'.", ""]

    spy_r = spy.pct_change().fillna(0.0)
    ew = px.pct_change().mean(axis=1).fillna(0.0)

    def mom(a, b):
        return lambda p, i: p.iloc[i - b] / p.iloc[i - a] - 1

    def near_high(p, i):
        return p.iloc[i] / p.iloc[i - 252:i + 1].max()

    def lowvol(p, i):
        return -p.pct_change().iloc[i - 60:i + 1].std()

    def mom_trend(p, i):
        s = p.iloc[i - 21] / p.iloc[i - 252] - 1
        ok = p.iloc[i] > p.iloc[i - 199:i + 1].mean()
        return s.where(ok)

    strategies = {
        "SPY החזקה פשוטה": spy_r,
        "ממוצע שווה של כל היקום": ew,
        "מומנטום 12-1 (טופ 20)": rebalance_strategy(px, mom(252, 21), spy=spy),
        "מומנטום 6-1 (טופ 20)": rebalance_strategy(px, mom(126, 21), spy=spy),
        "מומנטום 12-1 + פילטר SPY>SMA200": rebalance_strategy(px, mom(252, 21), True, spy),
        "קרבה לשיא 52 שבועות (טופ 20)": rebalance_strategy(px, near_high, spy=spy),
        "קרבה לשיא + פילטר SPY": rebalance_strategy(px, near_high, True, spy),
        "נמוך-תנודתיות (טופ 20)": rebalance_strategy(px, lowvol, spy=spy),
        "מומנטום 12-1 מעל SMA200": rebalance_strategy(px, mom_trend, spy=spy),
    }
    L.append("— אסטרטגיות איזון חודשי —")
    wins = []
    for name, r in strategies.items():
        a, b = r[r.index < SPLIT], r[r.index >= SPLIT]
        L.append(name)
        L.append("  בנייה: " + perf(a))
        L.append("  בדיקה: " + perf(b))
        if name not in ("SPY החזקה פשוטה", "ממוצע שווה של כל היקום"):
            ex_b = (b - ew.reindex(b.index)).mean() * 252 * 100
            ex_a = (a - ew.reindex(a.index)).mean() * 252 * 100
            L.append(f"  עודף שנתי מעל ממוצע היקום: בנייה {ex_a:+.1f}% | בדיקה {ex_b:+.1f}%")
            if ex_a > 0 and ex_b > 0:
                wins.append(name)
    L.append("")
    L.append("חיוביות מעל ממוצע היקום בשתי התקופות: " + (", ".join(wins) if wins else "אין"))
    L.append("")
    L.append("— מחקר אירועים: תשואה ממוצעת ל-10 ימי מסחר אחרי סיגנל (עודף = מעל ממוצע כל ימי-המניה) —")
    for (name, per), (n, m, ex, w) in event_study(px, hi, lo, vol, spy).items():
        L.append(f"{name} | {per}: {n} אירועים | ממוצע {m:+.2f}% | עודף {ex:+.2f}% | חיוביים {w:.0f}%")
    L += ["", "מגבלות: survivorship bias, אירועים חופפים (לא עצמאיים), לא כולל סטופים. נבדקו ~9 וריאציות - ייתכן שאחת תיראה טובה במקרה.",
          "מסחר דמה בלבד."]
    text = "\n".join(L)
    print(text)
    open("research5_report.txt", "w", encoding="utf-8").write(text + "\n")


if __name__ == "__main__":
    main()
