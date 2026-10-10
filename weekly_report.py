"""סיכום שבועי לטלגרם: ביצועי החשבון מול SPY (שבוע ומאז ההתחלה) וסטטיסטיקת הבוט."""
import csv
import os
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd
import yfinance as yf

import broker
import state as st
from notify import send_telegram


def pct(a, b):
    return (a / b - 1) * 100 if b else 0.0


def main():
    if not broker.enabled():
        print("אין מפתחות Alpaca")
        sys.exit(1)
    h = broker.portfolio_history("all")
    pts = [(datetime.fromtimestamp(t, timezone.utc), e) for t, e in zip(h["timestamp"], h["equity"]) if e]
    if len(pts) < 1:
        send_telegram("📈 סיכום שבועי: עדיין אין היסטוריית חשבון.")
        return
    now_eq = broker.equity() or pts[-1][1]
    start_dt, start_eq = pts[0]
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    wk = [p for p in pts if p[0] <= week_ago]
    wk_dt, wk_eq = wk[-1] if wk else (start_dt, start_eq)

    spy = yf.download("SPY", period="2y", interval="1d", auto_adjust=True, progress=False)["Close"]
    spy = spy.squeeze()
    spy.index = pd.to_datetime(spy.index).tz_localize(None)

    def spy_ret(since):
        s0 = spy.asof(pd.Timestamp(since).tz_localize(None).normalize())
        return pct(float(spy.iloc[-1]), float(s0)) if pd.notna(s0) else None

    acc_wk, acc_all = pct(now_eq, wk_eq), pct(now_eq, start_eq)
    s_wk, s_all = spy_ret(wk_dt), spy_ret(start_dt)

    def cmp(acc, sp):
        return f"{acc:+.2f}% | SPY {sp:+.2f}% | הפרש {acc - sp:+.2f}%" if sp is not None else f"{acc:+.2f}%"

    lines = [f"📈 סיכום שבועי — {datetime.now():%d.%m.%Y} (חשבון דמה)", ""]
    lines.append(f"💰 שווי החשבון: {now_eq:,.2f}$")
    lines.append(f"שבוע אחרון: {cmp(acc_wk, s_wk)}")
    lines.append(f"מאז {start_dt:%d.%m.%Y}: {cmp(acc_all, s_all)}")
    s = st.load()
    peak = float(s.get("peak_equity") or 0)
    if peak:
        lines.append(f"📉 ירידה מהשיא: {max(0.0, (peak - now_eq) / peak * 100):.1f}%" + (" ⛔ מושהה" if s.get("paused") else ""))

    rows = []
    if os.path.exists("signals_log.csv"):
        with open("signals_log.csv", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    closed = [r for r in rows if r["status"] in ("target", "stopped", "timeout") and r.get("r")]
    lines.append("")
    if closed:
        rs = [float(r["r"]) for r in closed]
        act = sum(1 for r in closed if r.get("actual_r"))
        lines.append(f"🤖 עסקאות סגורות: {len(rs)} | הצלחה {sum(x > 0 for x in rs) / len(rs) * 100:.0f}% | ממוצע {sum(rs) / len(rs):+.2f}R | סה\"כ {sum(rs):+.1f}R (לפי מילוי בפועל: {act})")
    else:
        lines.append("🤖 עדיין אין עסקאות סגורות.")
    lines.append(f"פתוחות: {sum(r['status'] == 'open' for r in rows)} | ממתינות למילוי: {sum(r['status'] == 'pending' for r in rows)}")
    if len(pts) < 10:
        lines += ["", "ℹ️ יש פחות מ-10 ימי נתונים בחשבון, ולכן ההשוואה עדיין לא מייצגת."]
    lines += ["", "מסחר דמה בלבד. תוצאות עבר אינן תחזית."]
    text = "\n".join(lines)
    print(text)
    with open("weekly_report.txt", "w", encoding="utf-8") as f:
        f.write(text + "\n")
    send_telegram(text)


if __name__ == "__main__":
    main()
