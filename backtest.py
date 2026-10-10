"""בדיקת עבר של האסטרטגיה על S&P 500 (5 שנים). הרצה: python backtest.py"""
import numpy as np
import pandas as pd

import config as C
from data import download, get_sp500
from strategy import add_indicators, compute_signals, simulate


def main():
    tickers = get_sp500()
    raw = download(tickers + ["SPY"], period="5y")
    data = {t: add_indicators(d) for t, d in raw.items()}
    spy = data.pop("SPY")
    regime = spy["Close"] > spy["sma200"]

    sigs, cands = {}, []
    for t, df in data.items():
        s = compute_signals(df)
        sigs[t] = s
        for i in np.flatnonzero(s["sig"].to_numpy()):
            if i >= len(s) - 1:
                continue
            d = s.index[i]
            if C.USE_MARKET_FILTER and not bool(regime.get(d, False)):
                continue
            m = s["mom"].iloc[i]
            cands.append((d, t, float(m) if pd.notna(m) else -1.0, int(i)))

    if not cands:
        print("לא נמצאו סיגנלים.")
        return
    cdf = pd.DataFrame(cands, columns=["date", "ticker", "mom", "i"])
    cdf = cdf.sort_values(["date", "mom"], ascending=[True, False])
    cdf = cdf.groupby("date").head(C.MAX_SIGNALS_PER_DAY)

    trades = []
    for t, g in cdf.groupby("ticker"):
        s = sigs[t]
        busy_until = None
        for row in g.sort_values("date").itertuples():
            if busy_until is not None and row.date <= busy_until:
                continue
            sig = s.iloc[row.i]
            future = s.iloc[row.i + 1 :]
            res = simulate(future, float(sig["entry"]), float(sig["stop"]), float(sig["target"]))
            if res["status"] in ("pending", "open"):
                break
            if res["status"] == "expired":
                busy_until = future.index[min(C.ORDER_VALID_DAYS, len(future)) - 1]
            else:
                busy_until = res["exit_date"]
            trades.append({"ticker": t, "signal_date": row.date, **res})

    tdf = pd.DataFrame(trades)
    filled = tdf[tdf["status"].isin(["target", "stopped", "timeout"])].copy()
    n_exp = int((tdf["status"] == "expired").sum())
    r = filled["r"]
    wins, losses = r[r > 0], r[r <= 0]
    pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else float("inf")
    curve = filled.sort_values("exit_date")["r"].cumsum()
    max_dd = (curve - curve.cummax()).min()

    print("=" * 40)
    print(f"סיגנלים שהתמלאו: {len(filled)} | הוראות שפגו: {n_exp}")
    print(f"יעד: {(filled.status == 'target').sum()} | סטופ: {(filled.status == 'stopped').sum()} | timeout: {(filled.status == 'timeout').sum()}")
    print(f"אחוז הצלחה: {len(wins) / len(filled) * 100:.1f}%")
    print(f"ממוצע לעסקה (expectancy): {r.mean():+.3f}R")
    print(f"Profit factor: {pf:.2f}")
    print(f"סה\"כ: {r.sum():+.1f}R | משיכה מקסימלית (בסכום R): {max_dd:.1f}R")
    print("=" * 40)
    print("שים לב: הבדיקה על המרכיבים הנוכחיים של S&P 500 (survivorship bias),")
    print("בלי עמלות/החלקות, ובלי מגבלת פוזיציות במקביל. התוצאות אופטימיות מהמציאות.")
    filled.to_csv("backtest_trades.csv", index=False)


if __name__ == "__main__":
    main()
