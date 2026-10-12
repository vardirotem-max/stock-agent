"""מחזור רווח יומי: נעילת רווח וכניסה מחדש.

רץ כל 10 דקות בשעות המסחר. נקודת בסיס = שווי הסגירה הקודמת (ובכל מחזור: שווי אחרי הסגירה).
1. הרווח מנקודת הבסיס הגיע ל-DAILY_PROFIT_TARGET: סוגרים הכל, מבטלים הוראות, ופותחים 4 פוזיציות חדשות (open_now).
2. הפסד מנקודת הבסיס הגיע ל-DAILY_LOSS_LIMIT: סוגרים הכל ועוצרים עד מחר.
3. בשעה האחרונה לא נפתחות פוזיציות חדשות. כשהשוק סגור הבוט לא עושה כלום ומחר מתחיל מחדש.
DRY=1: מדפיס בלבד. FORCE_TEST=1 (עם DRY): מדמה שהיעד הושג.
"""
import os
import sys
import time
import traceback
from datetime import datetime

import broker
import config as C
import open_now
import state as st
from notify import send_telegram
from scanner import OPEN, load_log, reconcile_actuals, save_log

DRY = os.getenv("DRY") == "1"
FORCE = os.getenv("FORCE_TEST") == "1"
L = []


def out(s):
    print(s)
    L.append(s)


def minutes_to_close(clock):
    t = datetime.fromisoformat(clock["timestamp"])
    c = datetime.fromisoformat(clock["next_close"])
    return (c - t).total_seconds() / 60


def liquidate(day_log_note):
    """מבטל הכל, מוכר הכל, ומעדכן את הלוג. מחזיר (סימבולים שנסגרו, מספר הוראות שבוטלו)."""
    pos = broker._req("GET", "/v2/positions").json()
    orders = broker._req("GET", "/v2/orders", params={"status": "open", "limit": 200, "nested": "false"}).json()
    r = broker._req("DELETE", "/v2/positions", params={"cancel_orders": "true"})
    out(f"סגירת פוזיציות: HTTP {r.status_code}")
    if r.status_code not in (200, 207):
        send_telegram(f"⚠️ {day_log_note}: סגירת הפוזיציות נכשלה (HTTP {r.status_code}) {r.text[:150]}")
        sys.exit(1)
    time.sleep(8)
    left = broker._req("GET", "/v2/positions").json()
    if left:
        send_telegram(f"⚠️ {day_log_note}: נשארו {len(left)} פוזיציות פתוחות ({', '.join(p['symbol'] for p in left)}). בדוק ב-Alpaca.")
    rows = load_log()
    for row in rows:
        oid = row.get("order_id") or ""
        if row["status"] not in OPEN or oid in ("", "skipped"):
            continue
        try:
            o = broker.get_order(oid)
        except Exception as e:
            out(f"לוג {row['ticker']}: {e}")
            continue
        row["status"] = "timeout" if o.get("filled_avg_price") else "expired"
        row["broker_done"] = "1"
    reconcile_actuals(rows)
    save_log(rows)
    return pos, len(orders)


def celebrate(gain, lock, pos_closed, n, after, last_eq):
    """הודעת החגיגה בטלגרם בסיום כל מחזור שהגיע ליעד."""
    day_total = float(after["equity"]) - last_eq
    lines = [f"🎉🥳 יאללה! הגענו ליעד הרווח! (מחזור {lock['cycles']})", "",
             f"💰 רווח במחזור הזה: +{gain:,.2f}$ (היעד היה {C.DAILY_PROFIT_TARGET:,.0f}$)"]
    if pos_closed:
        lines += ["", "🏁 הפוזיציות שנסגרו:"]
        for p in sorted(pos_closed, key=lambda x: float(x["unrealized_pl"]), reverse=True):
            u, pc = float(p["unrealized_pl"]), float(p["unrealized_plpc"]) * 100
            lines.append(f"{'🟢' if u >= 0 else '🔴'} {p['symbol']}: {u:+,.2f}$ ({pc:+.1f}%)")
    lines += ["", f"📈 שווי החשבון: {lock['baseline']:,.2f}$ | מזומן {float(after['cash']):,.2f}$",
              f"📅 רווח מצטבר היום: {day_total:+,.2f}$", f"🔁 מחזורים היום: {lock['cycles']}/{C.DAILY_MAX_CYCLES}"]
    if n:
        lines.append(f"(בוטלו {n} הוראות פתוחות)")
    lines += ["", "🔎 מחפש 4 פוזיציות חדשות לסיבוב הבא..." if lock["reentry"]
              else f"🛑 הגענו למקסימום {C.DAILY_MAX_CYCLES} מחזורים היום. נחגוג ונמשיך מחר בפתיחת השוק!",
              "", "מסחר דמה בלבד. לא ייעוץ השקעות."]
    return "\n".join(lines)


def main():
    if not broker.enabled():
        sys.exit("אין מפתחות Alpaca")
    clock = broker._req("GET", "/v2/clock").json()
    if not clock.get("is_open"):
        out("השוק סגור.")
        return
    day = clock["timestamp"][:10]
    left_min = minutes_to_close(clock)
    state = st.load()
    acc = broker._req("GET", "/v2/account").json()
    equity, last_eq = float(acc["equity"]), float(acc["last_equity"])

    lock = state.get("lock") or {}
    if lock.get("day") != day:  # יום חדש: מתחילים מחדש מהסגירה הקודמת
        lock = {"day": day, "baseline": last_eq, "cycles": 0, "reentry": False, "closed": [], "stopped": False}
    gain = equity - lock["baseline"]
    out(f"{day}: שווי {equity:,.2f}$, בסיס {lock['baseline']:,.2f}$, רווח מהבסיס {gain:+,.2f}$ (יעד +{C.DAILY_PROFIT_TARGET:,.0f}$, "
        f"הפסד מקס' -{C.DAILY_LOSS_LIMIT:,.0f}$) | מחזור {lock['cycles']}/{C.DAILY_MAX_CYCLES} | נותרו {left_min:.0f} דק' לסגירה")
    if lock.get("stopped"):
        out("נעצר להיום.")
        return

    def save():
        if not DRY:
            state["lock"] = lock
            st.save(state)

    # כניסה מחדש שממתינה (לא נמצאו מועמדים קודם, או שהריצה נקטעה)
    if lock["reentry"] and not (DRY and FORCE):
        return reenter(lock, left_min, save)

    if gain <= -C.DAILY_LOSS_LIMIT and not (DRY and FORCE):
        out("הגבלת הפסד יומי הופעלה.")
        if DRY:
            return
        pos_closed, n = liquidate("הגבלת הפסד יומי")
        syms = [p["symbol"] for p in pos_closed]
        lock["stopped"] = True
        save()
        after = float(broker._req("GET", "/v2/account").json()["equity"])
        send_telegram(f"🛑 הגבלת הפסד יומי: החשבון ירד {gain:+,.2f}$ מנקודת הבסיס. נסגרו {len(syms)} פוזיציות ובוטלו {n} הוראות.\n"
                      f"שווי: {after:,.2f}$. הבוט עוצר להיום וימשיך מחר בפתיחת השוק.\nמסחר דמה בלבד.")
        return

    if gain < C.DAILY_PROFIT_TARGET and not (DRY and FORCE):
        out("היעד לא הושג.")
        save()
        return

    pos = broker._req("GET", "/v2/positions").json()
    out(f"יעד הושג. פוזיציות לסגירה: {len(pos)} ({', '.join(p['symbol'] for p in pos)})")
    if DRY:
        out("DRY: לא נסגר דבר. בדיקת כניסה מחדש (בלי הוראות):")
        placed = open_now.main(n_new=4, exclude={p["symbol"] for p in pos})
        out(f"DRY: היו נשלחות {placed} הוראות חדשות. פירוט ב-open_now_report.txt")
        return

    pos_closed, n = liquidate("נעילת רווח")
    syms = [p["symbol"] for p in pos_closed]
    after = broker._req("GET", "/v2/account").json()
    lock["baseline"] = float(after["equity"])
    lock["cycles"] += 1
    lock["closed"] = sorted(set(lock["closed"]) | set(syms))
    lock["reentry"] = lock["cycles"] < C.DAILY_MAX_CYCLES
    lock["stopped"] = not lock["reentry"]
    save()
    send_telegram(celebrate(gain, lock, pos_closed, n, after, last_eq))
    if lock["reentry"]:
        reenter(lock, left_min, save)


def reenter(lock, left_min, save):
    if left_min < C.NO_NEW_ENTRY_MIN_BEFORE_CLOSE:
        lock["reentry"] = False
        save()
        out("פחות משעה לסגירה: לא נפתחות פוזיציות חדשות היום.")
        send_telegram("⏰ נשארה פחות משעה לסגירת המסחר, לא נפתחו פוזיציות חדשות. הבוט ממשיך מחר בפתיחת השוק.")
        return
    placed = open_now.main(n_new=4, exclude=set(lock["closed"]))
    out(f"כניסה מחדש: נשלחו {placed} הוראות")
    if placed > 0:
        lock["reentry"] = False
        save()
    else:
        out("לא נמצאו מועמדים. ננסה שוב בריצה הבאה.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        out("שגיאה:\n" + traceback.format_exc())
        send_telegram("⚠️ מחזור הרווח היומי: שגיאה בהרצה, ראה את ה-Actions.")
        sys.exit(1)
    finally:
        open("profit_lock_report.txt", "w", encoding="utf-8").write("\n".join(L) + "\n")
