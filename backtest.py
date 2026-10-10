"""בדיקת עבר (5 שנים, S&P 500) כולל תקרת פוזיציות והחלקות. הרצה: python backtest.py"""
import os

import numpy as np
import pandas as pd

import config as C
from data import download, get_sp500
from notify import send_telegram
from strategy import add_indicators, compute_signals, simulate


def stats(df, col):
    r = df[col]
    if r.empty:
        return None
    wins, losses = r[r > 0], r[r <= 0]
    pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else float("inf")
    curve = df.sort_values("exit_date")[col].cumsum()
    return {
        "n": len(r), "win": len(wins) / len(r) * 100, "exp": r.mean(), "pf": pf,
        "sum": r.sum(), "dd": (curve - curve.cummax()).min(),
    }


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
    cdf = cdf.sort_values(["date", "mom"], ascending=[True, False]).groupby("date").head(C.MAX_SIGNALS_PER_DAY)

    busy_until, active, trades = {}, [], []
    skipped_cap = expired = unfinished = 0
    for row in cdf.sort_values(["date", "mom"], ascending=[True, False]).itertuples():
        t, d = row.ticker, row.date
        if t in busy_until and d <= busy_until[t]:
            continue
        s = sigs[t]
        sig = s.iloc[row.i]
        future = s.iloc[row.i + 1:]
        res = simulate(future, float(sig["entry"]), float(sig["stop"]), float(sig["target"]))
        st = res["status"]
        if st == "pending":
            continue
        if st == "expired":
            end = future.index[min(C.ORDER_VALID_DAYS, len(future)) - 1]
        elif st == "open":
            end = future.index[-1]
        else:
            end = res["exit_date"]
        if sum(1 for a, b in active if a <= d <= b) >= C.MAX_OPEN_POSITIONS:
            skipped_cap += 1
            continue
        active.append((d, end))
        busy_until[t] = end
        if st == "expired":
            expired += 1
            continue
        if st == "open":
            unfinished += 1
            continue
        fill, risk = res["fill_price"], float(sig["entry"]) - float(sig["stop"])
        cost = 2 * C.BT_SLIPPAGE_PCT * fill + (C.BT_STOP_SLIPPAGE_PCT * fill if st == "stopped" else 0)
        trades.append({
            "ticker": t, "signal_date": d, "status": st, "fill_date": res["fill_date"],
            "exit_date": res["exit_date"], "r_gross": res["r"], "r_net": res["r"] - cost / risk,
        })

    tdf = pd.DataFrame(trades)
    if tdf.empty:
        print("אין עסקאות סגורות.")
        return
    g, n = stats(tdf, "r_gross"), stats(tdf, "r_net")
    hold = (pd.to_datetime(tdf["exit_date"]) - pd.to_datetime(tdf["fill_date"])).dt.days.mean()
    first, last = pd.to_datetime(tdf["fill_date"]).min(), pd.to_datetime(tdf["exit_date"]).max()
    spy_ret = (spy["Close"].asof(last) / spy["Close"].asof(first) - 1) * 100
    approx = n["sum"] * C.RISK_PER_TRADE_PCT  # סיכון 0.5% לעסקה, בלי ריבית דריבית

    L = [f"📊 בקטסט S&P 500 — {first:%d.%m.%Y} עד {last:%d.%m.%Y}", f"תקרת פוזיציות: {C.MAX_OPEN_POSITIONS}", ""]
    L.append(f"עסקאות סגורות: {n['n']} | הוראות שפגו: {expired} | נדחו בגלל התקרה: {skipped_cap}")
    L.append(f"יעד: {(tdf.status == 'target').sum()} | סטופ: {(tdf.status == 'stopped').sum()} | timeout: {(tdf.status == 'timeout').sum()}")
    L.append(f"ממוצע ימי החזקה: {hold:.1f}")
    L.append("")
    L.append(f"לפני החלקות: הצלחה {g['win']:.0f}% | ממוצע {g['exp']:+.3f}R | PF {g['pf']:.2f} | סה\"כ {g['sum']:+.0f}R")
    L.append(f"אחרי החלקות: הצלחה {n['win']:.0f}% | ממוצע {n['exp']:+.3f}R | PF {n['pf']:.2f} | סה\"כ {n['sum']:+.0f}R")
    L.append(f"משיכה מקסימלית (סכום R, אחרי החלקות): {n['dd']:.1f}R")
    L.append("")
    L.append(f"הערכה גסה: סיכון {C.RISK_PER_TRADE_PCT}% לעסקה ≈ {approx:+.0f}% סך הכל (בלי ריבית דריבית), מול SPY באותה תקופה {spy_ret:+.0f}%")
    L.append("")
    tdf["year"] = pd.to_datetime(tdf["exit_date"]).dt.year
    L.append("לפי שנה (אחרי החלקות):")
    for y, part in tdf.groupby("year"):
        s_ = stats(part, "r_net")
        L.append(f"{y}: {s_['n']} עסקאות | הצלחה {s_['win']:.0f}% | ממוצע {s_['exp']:+.2f}R | סה\"כ {s_['sum']:+.0f}R")
    L += ["", "מגבלות: המדד הנוכחי בלבד (survivorship bias), בלי פילטר אנליסטים/דוחות (אין נתוני עבר אמינים),",
          "החלקות מוערכות. תוצאות עבר אינן תחזית."]
    text = "\n".join(L)
    print(text)
    with open("backtest_report.txt", "w", encoding="utf-8") as f:
        f.write(text + "\n")
    tdf.drop(columns=["year"]).to_csv("backtest_trades.csv", index=False)
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        send_telegram(text)


if __name__ == "__main__":
    main()
