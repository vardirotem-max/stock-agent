import csv
import os
import sys
from datetime import timedelta

import pandas as pd

import analysts
import broker
import earnings
import config as C
from data import download, get_sp500
from notify import send_telegram
from strategy import add_indicators, compute_signals, simulate

LOG = "signals_log.csv"
FIELDS = [
    "signal_date", "ticker", "entry", "stop", "target", "shares", "status",
    "fill_date", "fill_price", "exit_date", "exit_price", "r", "order_id", "broker_done",
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


def broker_sync(rows):
    """משקף את הלוג מול חשבון הדמה ב-Alpaca. אידמפוטנטי: בטוח להריץ כמה פעמים."""
    if not broker.enabled():
        return []
    ev = []
    for r in rows:
        t, oid = r["ticker"], r.get("order_id") or ""
        try:
            if r["status"] == "pending" and not oid:
                qty = int(float(r.get("shares") or 0))
                if qty < 1:
                    r["order_id"] = "skipped"
                    ev.append(f"⚠️ {t}: כמות 0 - לא נשלחה הוראה")
                    continue
                r["order_id"] = broker.place_bracket(
                    t, qty, float(r["entry"]), float(r["stop"]), float(r["target"]),
                    client_id=f"{r['signal_date']}-{t}",
                )
                ev.append(f"📨 {t}: נשלחה הוראה לחשבון הדמה ({qty} מניות)")
            elif oid not in ("", "skipped") and not r.get("broker_done"):
                if r["status"] == "expired":
                    broker.cancel(oid)
                    r["broker_done"] = "1"
                elif r["status"] == "timeout":
                    broker.close(t, oid)
                    r["broker_done"] = "1"
                    ev.append(f"🔒 {t}: הפוזיציה נסגרה בחשבון הדמה")
        except Exception as e:
            ev.append(f"⚠️ {t}: שגיאת Alpaca: {str(e)[:100]}")
            print("alpaca error", t, e)
    return ev


def safe_audit():
    if not broker.enabled():
        return []
    try:
        problems, _ = broker.audit()
        return problems
    except Exception as e:
        print("audit failed", e)
        return []


def expected_session(now_utc):
    """תאריך יום המסחר האחרון שצריך להיות זמין (לפי שעון ניו יורק, אחרי 17:00)."""
    et = now_utc.tz_convert("America/New_York")
    d = et.date()
    if et.hour < 17:
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def cross_check(data, last_date):
    """משווה מחיר סגירה של Yahoo מול Alpaca (מקור שני). מחזיר (אזהרות, מספר אימותים)."""
    if not broker.enabled():
        return [], 0
    refs = [t for t in ("AAPL", "MSFT", "JPM") if t in data]
    try:
        snap = broker.snapshots(refs)
    except Exception as e:
        print("cross-check unavailable", e)
        return [], 0
    warns, ok = [], 0
    for t in refs:
        bar = (snap.get(t) or {}).get("dailyBar")
        if not bar or str(bar.get("t", ""))[:10] != fmt_date(last_date):
            continue
        y, a = float(data[t]["Close"].iloc[-1]), float(bar["c"])
        if abs(y - a) / a > C.DATA_CROSSCHECK_TOLERANCE:
            warns.append(f"⚠️ אי-התאמה בנתונים: {t} ב-Yahoo {y:.2f} מול Alpaca {a:.2f}")
        else:
            ok += 1
    return warns, ok


def write_report(lines):
    with open("last_run.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def build_message(date_str, regime_ok, new, events, stats, data_note=""):
    lines = [f"📊 סורק סווינג — {date_str}"]
    if data_note:
        lines.append(data_note)
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
        if C.USE_ANALYST_FILTER:
            lines.append(analysts.describe(s.get("analyst"), s["close"]))
        if C.USE_EARNINGS_FILTER:
            lines.append(earnings.describe(s.get("earnings")))
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
    expected = expected_session(pd.Timestamp.now("UTC"))
    if last_date.date() < expected:
        send_telegram(
            f"⚠️ אין עדיין נתוני מסחר של {expected} (נר אחרון {fmt_date(last_date)}). "
            "חג בבורסה או עיכוב במקור הנתונים. לא בוצעה סריקה."
        )
        return
    warns, ok_n = cross_check(data, last_date)
    if warns:
        send_telegram("\n".join(warns) + "\nלא בוצעה סריקה עד שהנתונים יתאמו.")
        sys.exit(1)
    data_note = f"✅ נתוני השוק אומתו מול מקור שני ({ok_n}/3)" if ok_n >= 2 else ""
    last_str = fmt_date(last_date)

    rows = load_log()
    events = update_outcomes(rows, data)

    if any(r["signal_date"] == last_str for r in rows):
        print(f"{last_str} כבר נסרק. מעדכן לוג בלבד.")
        events += broker_sync(rows)
        events += safe_audit()
        save_log(rows)
        write_report([
            f"run_utc={pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M}", f"last_bar={last_str}", "mode=already_scanned",
            f"crosscheck_ok={ok_n}/3", f"events={len(events)}", *events,
        ])
        if events:
            extra = stats_line(rows)
            send_telegram("🔄 עדכון\n" + "\n".join(events) + (f"\n\n{extra}" if extra else ""))
        return

    regime_ok = True
    if C.USE_MARKET_FILTER and spy is not None:
        regime_ok = bool(spy["Close"].iloc[-1] > spy["sma200"].iloc[-1])

    new = []
    busy = {r["ticker"] for r in rows if r["status"] in OPEN}
    limit = max(0, min(C.MAX_SIGNALS_PER_DAY, C.MAX_OPEN_POSITIONS - len(busy)))
    if regime_ok and limit == 0:
        data_note = (data_note + "\n" if data_note else "") + f"⏸ תקרת פוזיציות: {len(busy)}/{C.MAX_OPEN_POSITIONS} — אין סיגנלים חדשים עד שיתפנה מקום"
    info = {"cands": 0, "checked": 0, "no_data": 0, "rejected": 0, "earn_blocked": 0, "earn_no_data": 0}
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
        info["cands"] = len(cands)
        cands.sort(key=lambda x: x["mom"], reverse=True)
        pool = cands[: C.ANALYST_CHECK_TOP] if C.USE_ANALYST_FILTER else cands[: C.MAX_SIGNALS_PER_DAY]
        if limit == 0:
            pool = []
        new = []
        for c in pool:
            if C.USE_ANALYST_FILTER:
                a = analysts.get_analyst(c["ticker"])
                info["checked"] += 1
                if a is None or a["n"] < C.ANALYST_MIN_OPINIONS:
                    info["no_data"] += 1
                if not analysts.passes(a, c["close"]):
                    info["rejected"] += 1
                    continue
                c["analyst"] = a
            if C.USE_EARNINGS_FILTER:
                ed = earnings.next_earnings(c["ticker"])
                if ed is None:
                    info["earn_no_data"] += 1
                if earnings.blocked(ed):
                    info["earn_blocked"] += 1
                    continue
                c["earnings"] = ed
            new.append(c)
            if len(new) >= limit:
                break
        for s in new:
            s["shares"] = position_size(s["entry"], s["stop"])
            rows.append({
                "signal_date": last_str, "ticker": s["ticker"], "entry": s["entry"],
                "stop": s["stop"], "target": s["target"], "shares": s["shares"],
                "status": "pending",
            })

    events += broker_sync(rows)
    events += safe_audit()
    save_log(rows)
    write_report([
        f"run_utc={pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M}", f"last_bar={last_str}", "mode=full_scan",
        f"crosscheck_ok={ok_n}/3", f"regime_ok={regime_ok}", f"technical_candidates={info['cands']}",
        f"analyst_checked={info['checked']}", f"analyst_no_data={info['no_data']}",
        f"analyst_rejected={info['rejected']}", f"earnings_blocked={info['earn_blocked']}",
        f"earnings_no_data={info['earn_no_data']}", f"open_slots_used={len(busy)}/{C.MAX_OPEN_POSITIONS}",
        f"signals_sent={len(new)}", *events,
    ])
    send_telegram(build_message(last_str, regime_ok, new, events, stats_line(rows), data_note))


if __name__ == "__main__":
    main()
