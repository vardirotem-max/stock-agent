"""מחקר וריאציות: בדיקה שיטתית של שינויים באסטרטגיה עם חלוקה לבנייה (עד 2024) ולבדיקה (2025 ואילך).
לא משנה את הבוט החי. מטרה: לראות אם יש וריאציה שמחזיקה גם מחוץ למדגם."""
import os

import numpy as np
import pandas as pd

import config as C
from data import download, get_sp500
from notify import send_telegram
from strategy import add_indicators, compute_signals, simulate

SPLIT = pd.Timestamp("2025-01-01")


def breakout_signals(df):
    c = df["Close"]
    prior_high = c.shift(1).rolling(20).max()
    vol_ok = df["Volume"] > 1.5 * df["Volume"].rolling(20).mean()
    stop = c - 2.0 * df["atr"]
    risk = c - stop
    risk_pct = risk / c
    cond = (
        (c >= C.MIN_PRICE) & (df["dollar_vol"] >= C.MIN_DOLLAR_VOLUME)
        & (c > prior_high) & vol_ok & (c > df["sma50"]) & (df["sma50"] > df["sma200"])
        & (risk_pct >= C.MIN_RISK_PCT) & (risk_pct <= C.MAX_RISK_PCT)
    )
    out = df.copy()
    out["sig"] = cond.astype(bool)
    out["entry"], out["stop"] = c, stop
    out["target"] = c + C.RR * risk
    return out


def simulate_open(future, entry, stop, target):
    """כניסה בפתיחת היום הבא (הוראת שוק), ואז סטופ/יעד/timeout. מחמיר: סטופ לפני יעד באותו נר."""
    if len(future) < 2:
        return {"status": "pending"}
    o, h, l, cl = (future[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    idx = future.index
    fill = o[0]
    risk = entry - stop
    if fill <= stop or risk <= 0:
        return {"status": "expired"}
    for i in range(len(future)):
        ref = fill if i == 0 else o[i]
        done = lambda st_, px: {"status": st_, "fill_price": fill, "fill_date": idx[0], "exit_price": px, "exit_date": idx[i], "r": (px - fill) / risk}
        if l[i] <= stop:
            return done("stopped", min(stop, ref))
        if h[i] >= target:
            return done("target", max(target, ref))
        if i >= C.MAX_HOLD_DAYS:
            return done("timeout", cl[i])
    return {"status": "open"}


def run(data, regime, sigfn, sim, overrides):
    saved = {k: getattr(C, k) for k in overrides}
    for k, v in overrides.items():
        setattr(C, k, v)
    try:
        sigs, cands = {}, []
        for t, df in data.items():
            s = sigfn(df)
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
            return pd.DataFrame()
        cdf = pd.DataFrame(cands, columns=["date", "ticker", "mom", "i"]).sort_values(["date", "mom"], ascending=[True, False])
        cdf = cdf.groupby("date").head(C.MAX_SIGNALS_PER_DAY)
        busy_until, active, trades = {}, [], []
        for row in cdf.itertuples():
            t, d = row.ticker, row.date
            if t in busy_until and d <= busy_until[t]:
                continue
            s = sigs[t]
            sig = s.iloc[row.i]
            future = s.iloc[row.i + 1:]
            res = sim(future, float(sig["entry"]), float(sig["stop"]), float(sig["target"]))
            st_ = res["status"]
            if st_ == "pending":
                continue
            end = future.index[min(C.ORDER_VALID_DAYS, len(future)) - 1] if st_ == "expired" else (future.index[-1] if st_ == "open" else res["exit_date"])
            if sum(1 for a, b in active if a <= d <= b) >= C.MAX_OPEN_POSITIONS:
                continue
            active.append((d, end))
            busy_until[t] = end
            if st_ in ("expired", "open"):
                continue
            fill, risk = res["fill_price"], float(sig["entry"]) - float(sig["stop"])
            cost = 2 * C.BT_SLIPPAGE_PCT * fill + (C.BT_STOP_SLIPPAGE_PCT * fill if st_ == "stopped" else 0)
            trades.append({"signal_date": d, "exit_date": res["exit_date"], "r": res["r"] - cost / risk})
        return pd.DataFrame(trades)
    finally:
        for k, v in saved.items():
            setattr(C, k, v)


def summ(df):
    if df is None or df.empty:
        return None
    r = df["r"]
    w, l = r[r > 0].sum(), abs(r[r <= 0].sum())
    return {"n": len(r), "exp": r.mean(), "pf": w / l if l else float("inf"), "sum": r.sum()}


def fmt(s):
    return "אין עסקאות" if s is None else f"{s['n']} עסקאות | {s['exp']:+.2f}R | PF {s['pf']:.2f}"


def main():
    raw = download(get_sp500() + ["SPY"], period="5y")
    data = {t: add_indicators(d) for t, d in raw.items()}
    spy = data.pop("SPY")
    regime = spy["Close"] > spy["sma200"]

    variants = [
        ("בסיס (הבוט הנוכחי)", compute_signals, simulate, {}),
        ("יחס סיכוי-סיכון 1.5", compute_signals, simulate, {"RR": 1.5}),
        ("יחס סיכוי-סיכון 3", compute_signals, simulate, {"RR": 3.0}),
        ("סטופ 1.0 ATR", compute_signals, simulate, {"STOP_ATR": 1.0}),
        ("סטופ 2.5 ATR", compute_signals, simulate, {"STOP_ATR": 2.5, "MAX_RISK_PCT": 0.12}),
        ("RSI מקסימלי 40", compute_signals, simulate, {"RSI_MAX": 40}),
        ("RSI מקסימלי 55", compute_signals, simulate, {"RSI_MAX": 55}),
        ("בלי פילטר שוק (SPY)", compute_signals, simulate, {"USE_MARKET_FILTER": False}),
        ("פריצה 20 יום, יחס 2", breakout_signals, simulate_open, {"RR": 2.0}),
        ("פריצה 20 יום, יחס 3", breakout_signals, simulate_open, {"RR": 3.0}),
    ]
    L = ["🔬 מחקר וריאציות (עסקאות אחרי החלקות, תקרה 15)", f"בנייה: עד 2024 | בדיקה מחוץ למדגם: 2025 ואילך", ""]
    passing = []
    for name, sf, sm, ov in variants:
        tr = run(data, regime, sf, sm, ov)
        if tr.empty:
            L.append(f"{name}\n  אין עסקאות")
            continue
        tr_train, tr_test = tr[tr["signal_date"] < SPLIT], tr[tr["signal_date"] >= SPLIT]
        a, b = summ(tr_train), summ(tr_test)
        L.append(f"{name}\n  בנייה: {fmt(a)}\n  בדיקה: {fmt(b)}")
        if a and b and a["exp"] > 0.05 and b["exp"] > 0.05 and a["n"] >= 100 and b["n"] >= 100:
            passing.append(name)

    def bench(mask_start, mask_end):
        s = spy[(spy.index >= mask_start) & (spy.index < mask_end)]["Close"]
        return (s.iloc[-1] / s.iloc[0] - 1) * 100 if len(s) > 1 else float("nan")

    def trend(mask_start, mask_end):
        pos = (spy["Close"] > spy["sma200"]).shift(1).fillna(False)
        r = (spy["Close"].pct_change() * pos)[(spy.index >= mask_start) & (spy.index < mask_end)]
        return ((1 + r).prod() - 1) * 100

    t0 = pd.Timestamp("2022-12-01")
    L += ["", "השוואה (SPY):",
          f"  החזקה פשוטה: בנייה {bench(t0, SPLIT):+.0f}% | בדיקה {bench(SPLIT, pd.Timestamp('2100-01-01')):+.0f}%",
          f"  החזקה רק מעל ממוצע 200: בנייה {trend(t0, SPLIT):+.0f}% | בדיקה {trend(SPLIT, pd.Timestamp('2100-01-01')):+.0f}%", ""]
    if passing:
        L.append("וריאציות עם ממוצע חיובי (מעל 0.05R, 100+ עסקאות) גם בבנייה וגם בבדיקה: " + ", ".join(passing))
        L.append("זהירות: נבדקו 10 וריאציות, ולכן סביר שאחת תיראה טוב במקרה. לא לשנות את הבוט בלי אימות נוסף.")
    else:
        L.append("אף וריאציה לא עברה גם בבנייה וגם בבדיקה (ממוצע מעל 0.05R, 100+ עסקאות).")
    L += ["", "מגבלות: המדד הנוכחי בלבד (survivorship bias), בלי פילטר אנליסטים/דוחות, תוצאות עבר אינן תחזית."]
    text = "\n".join(L)
    print(text)
    with open("research_report.txt", "w", encoding="utf-8") as f:
        f.write(text + "\n")
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        send_telegram(text)


if __name__ == "__main__":
    main()
