import csv
import os
import sys

import pandas as pd

import config as C
from data import download, get_sp500
from notify import send_telegram
from strategy import add_indicators, compute_signals, simulate

LOG = "signals_log.csv"
FIELDS = [
    "signal_date", "ticker", "entry", "stop", "target", "shares", "status",
    "fill_date", "fill_price", "exit_date", "exit_price", "r",
]
OPEN = ("pending", "open")
FILLED_CLOSED = ("target", "stopped", "timeout")


def load_log():
    if not os.path.exists(LOG):
        return []
    with open(LOG, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_log(rows):
    with open(LOG, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def fmt_date(ts):
    return ts.strftime("%Y-%m-%d")


def update_outcomes(rows, data):
    """מעדכן עסקאות פתוחות לפי הנרות החדשים. מחזיר רשימת הודעות אירועים."""
    events = []
    for r in rows:
        if r["status"] not in OPEN:
            continue
        df = data.get(r["ticker"])
        if df is None:
            continue
        future = df[df.index > pd.Timestamp(r["signal_date"])]
        res = simulate(future, float(r["entry"]), float(r["stop"]), float(r["target"]))
        prev, new = r["status"], res["status"]
        r["status"] = new
        if "fill_price" in res:
            r["fill_price"] = round(float(res["fill_price"]), 2)
            r["fill_date"] = fmt_date(res["fill_date"])
        if "exit_price" in res:
            r["exit_price"] = round(float(res["exit_price"]), 2)
            r["exit_date"] = fmt_date(res["exit_date"])
            r["r"] = round(float(res["r"]), 2)

        if new == prev:
            continue
        t = r["ticker"]
        if new == "target":
            events.append(f"🎯 {t}: הגיע ליעד ({float(r['r']):+.1f}R)")
        elif new == "stopped":
            events.append(f"🛑 {t}: הסטופ הופעל ({float(r['r']):+.1f}R)")
        elif new == "timeout":
            events.append(f"⏱ {t}: נסגר אחרי {C.MAX_HOLD_DAYS} ימים ({float(r['r']):+.1f}R)")
        elif new == "expired":
            events.append(f"⌛ {t}: ההוראה פגה בלי מילוי")
        elif new == "open":
            events.append(f"✅ {t}: הלימיט התמלא ב-{r['fill_price']}")
    return events


def stats_line(rows):
    rs = [float(r["r"]) for r in rows if r["status"] in FILLED_CLOSED and r.get("r")]
    if not rs:
        return ""
    wins = sum(1 for x in rs if x > 0)
    return f"📈 היסטוריית הבוט: {len(rs)} עסקאות סגורות | הצלחה {wins / len(rs) * 100:.0f}% | ממוצע {sum(rs) / len(rs):+.2f}R"


def position_size(entry, stop):
    per_share = entry - stop
    if per_share <= 0:
        return 0
    by_risk = int(C.ACCOUNT_SIZE * C.RISK_PER_TRADE_PCT / 100 / per_share)
    by_cap = int(C.ACCOUNT_SIZE * C.MAX_POSITION_PCT / 100 / entry)
    return max(0, min(by_risk, by_cap))


def build_message(date_str, regime_ok, new, events, stats):
    lines = [f"📊 סורק סווינג — {date_str}"]
    if not regime_ok:
        lines.append("⚠️ SPY מתחת לממוצע 200 — אין סיגנלים חדשים (פילטר שוק)")
    elif not new:
        lines.append("אין סיגנלים חדשים היום.")
    for i, s in enumerate(new, 1):
        lines += [
            "",
            f"{i}) {s['ticker']}  (סגירה {s['close']:.2f})",
            f"🟢 Buy Limit: {s['entry']:.2f}",
            f"🔴 Stop: {s['stop']:.2f}",
            f"🎯 Target: {s['target']:.2f}",
            f"סיכון {s['risk_pct'] * 100:.1f}% | RSI {s['rsi']:.0f} | כמות מוצעת: {s['shares']}",
        ]
    if new:
        lines += ["", f"ההוראות תקפות ל-{C.ORDER_VALID_DAYS} ימי מסחר. אחרי מילוי - הצב סטופ ויעד."]
    if events:
        lines += ["", "עדכונים:"] + events
    if stats:
        lines += ["", stats]
    lines += ["", "לא ייעוץ השקעות. בדוק לפני ביצוע."]
    return "\n".join(lines)


def main():
    tickers = get_sp500()
    raw = download(tickers + ["SPY"])
    data = {t: add_indicators(d) for t, d in raw.items()}
    spy = data.pop("SPY", None)
    if not data:
        send_telegram("⚠️ הסורק נכשל: לא התקבלו נתונים.")
        sys.exit(1)

    last_date = max(d.index[-1] for d in data.values())
    age = (pd.Timestamp.now("UTC").tz_localize(None) - last_date).days
    if age > 5:
        send_telegram(f"⚠️ הנתונים ישנים (נר אחרון {fmt_date(last_date)}). בדוק את מקור הנתונים.")
        sys.exit(1)
    last_str = fmt_date(last_date)

    rows = load_log()
    events = update_outcomes(rows, data)

    if any(r["signal_date"] == last_str for r in rows):
        print(f"{last_str} כבר נסרק. מעדכן לוג בלבד.")
        save_log(rows)
        return

    regime_ok = True
    if C.USE_MARKET_FILTER and spy is not None:
        regime_ok = bool(spy["Close"].iloc[-1] > spy["sma200"].iloc[-1])

    new = []
    if regime_ok:
        busy = {r["ticker"] for r in rows if r["status"] in OPEN}
        cands = []
        for t, df in data.items():
            if t in busy or df.index[-1] != last_date:
                continue
            last = compute_signals(df).iloc[-1]
            if last["sig"]:
                cands.append({
                    "ticker": t, "close": float(last["Close"]), "entry": float(last["entry"]),
                    "stop": float(last["stop"]), "target": float(last["target"]),
                    "risk_pct": float(last["risk_pct"]), "rsi": float(last["rsi"]),
                    "mom": float(last["mom"]) if pd.notna(last["mom"]) else -1.0,
                })
        cands.sort(key=lambda x: x["mom"], reverse=True)
        new = cands[: C.MAX_SIGNALS_PER_DAY]
        for s in new:
            s["shares"] = position_size(s["entry"], s["stop"])
            rows.append({
                "signal_date": last_str, "ticker": s["ticker"], "entry": s["entry"],
                "stop": s["stop"], "target": s["target"], "shares": s["shares"],
                "status": "pending",
            })

    save_log(rows)
    send_telegram(build_message(last_str, regime_ok, new, events, stats_line(rows)))


if __name__ == "__main__":
    main()
