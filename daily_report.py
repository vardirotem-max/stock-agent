"""דוח יומי לטלגרם (20:00 שעון ישראל): יתרה, רווח/הפסד יומי ופוזיציות פתוחות בחשבון הדמה."""
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import broker
from notify import send_telegram

IL = ZoneInfo("Asia/Jerusalem")


def money(x, sign=False):
    return f"{x:+,.2f}$" if sign else f"{x:,.2f}$"


def arrow(x):
    return "🟢" if x > 0 else ("🔴" if x < 0 else "⚪")


def main():
    now = datetime.now(IL)
    # ההרצה מתוזמנת פעמיים ביום (שעון קיץ/חורף); שולחים רק כשהשעה בישראל היא 20
    if os.getenv("FORCE") != "1" and now.hour != 20:
        print(f"עכשיו {now:%H:%M} בישראל - לא 20:00, לא שולח")
        return
    if not broker.enabled():
        print("אין מפתחות Alpaca")
        sys.exit(1)

    acc = broker._req("GET", "/v2/account")
    pos = broker._req("GET", "/v2/positions")
    orders = broker._req("GET", "/v2/orders", params={"status": "open", "limit": 100, "nested": "false"})
    clock = broker._req("GET", "/v2/clock")
    if not (acc.ok and pos.ok and orders.ok):
        msg = f"⚠️ הדוח היומי נכשל: account {acc.status_code}, positions {pos.status_code}, orders {orders.status_code}"
        print(msg)
        send_telegram(msg)
        sys.exit(1)

    a = acc.json()
    equity, last_eq, cash = float(a["equity"]), float(a["last_equity"]), float(a["cash"])
    day_pl = equity - last_eq
    day_pct = day_pl / last_eq * 100 if last_eq else 0.0
    market_open = clock.json().get("is_open") if clock.ok else None

    lines = [f"📅 דוח יומי — {now:%d.%m.%Y %H:%M} (חשבון דמה)", ""]
    lines.append(f"💰 שווי החשבון: {money(equity)}")
    lines.append(f"💵 מזומן פנוי: {money(cash)}")
    lines.append(f"{arrow(day_pl)} רווח/הפסד יומי: {money(day_pl, True)} ({day_pct:+.2f}%)")
    if market_open is False:
        lines.append("ℹ️ השוק סגור כרגע; השינוי היומי הוא מאז הסגירה האחרונה.")

    positions = sorted(pos.json(), key=lambda p: float(p["unrealized_pl"]), reverse=True)
    lines.append("")
    if positions:
        total_unreal = sum(float(p["unrealized_pl"]) for p in positions)
        lines.append(f"📂 פוזיציות פתוחות ({len(positions)}) — רווח/הפסד כולל: {money(total_unreal, True)}")
        for p in positions:
            upl, plpc = float(p["unrealized_pl"]), float(p["unrealized_plpc"]) * 100
            intraday = float(p.get("unrealized_intraday_pl") or 0)
            lines.append(
                f"{arrow(upl)} {p['symbol']}: {float(p['qty']):g} מניות | כניסה {float(p['avg_entry_price']):.2f} "
                f"| עכשיו {float(p['current_price']):.2f} | {money(upl, True)} ({plpc:+.1f}%) | היום {money(intraday, True)}"
            )
    else:
        lines.append("📂 אין פוזיציות פתוחות.")

    buys = [o for o in orders.json() if o["side"] == "buy" and o["type"] == "limit"]
    if buys:
        lines.append("")
        lines.append(f"⏳ הוראות קנייה ממתינות ({len(buys)}):")
        for o in buys:
            lines.append(f"• {o['symbol']}: {o['qty']} מניות בלימיט {float(o['limit_price']):.2f}")

    lines += ["", "מסחר דמה בלבד. לא ייעוץ השקעות."]
    text = "\n".join(lines)
    print(text)
    with open("daily_report.txt", "w", encoding="utf-8") as f:
        f.write(text + "\n")
    send_telegram(text)


if __name__ == "__main__":
    main()
