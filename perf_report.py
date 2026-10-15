"""דוח ביצועים אמיתי מתוך signals_log.csv: הצלחה, תוחלת, רווח בדולרים, החלקת כניסה, לפי סוג יציאה."""
import csv
import json
import os

from notify import send_telegram

CLOSED = ("stopped", "target", "timeout")


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def main():
    rows = list(csv.DictReader(open("signals_log.csv", encoding="utf-8")))
    tr = []
    for r in rows:
        if r["status"] not in CLOSED:
            continue
        R = num(r.get("actual_r")) if num(r.get("actual_r")) is not None else num(r.get("r"))
        if R is None:
            continue
        entry, stop, sh = num(r["entry"]), num(r["stop"]), num(r["shares"]) or 0
        risk_usd = sh * (entry - stop) if entry and stop else 0
        fill = num(r.get("actual_fill"))
        tr.append({"ticker": r["ticker"], "status": r["status"], "R": R, "usd": R * risk_usd,
                   "slip": (fill - entry) / entry * 100 if fill and entry else None,
                   "date": r.get("exit_date") or r.get("signal_date")})
    L = ["📈 דוח ביצועים (חשבון דמה, מהלוג)", ""]
    if not tr:
        L.append("אין עדיין עסקאות סגורות.")
    else:
        n = len(tr)
        wins = [t for t in tr if t["R"] > 0]
        tot_r, tot_usd = sum(t["R"] for t in tr), sum(t["usd"] for t in tr)
        L.append(f"עסקאות סגורות: {n} | הצלחה {len(wins)/n*100:.0f}% | תוחלת {tot_r/n:+.2f}R | סה\"כ {tot_r:+.1f}R ≈ {tot_usd:+,.0f}$")
        gw = sum(t["R"] for t in wins)
        gl = -sum(t["R"] for t in tr if t["R"] <= 0)
        L.append(f"Profit factor: {gw/gl:.2f}" if gl else "Profit factor: ללא הפסדים")
        L.append("")
        names = {"target": "הגיעו ליעד", "stopped": "סטופ", "timeout": "נסגרו ידנית/נעילה/זמן"}
        for k in CLOSED:
            part = [t for t in tr if t["status"] == k]
            if part:
                L.append(f"{names[k]}: {len(part)} | ממוצע {sum(t['R'] for t in part)/len(part):+.2f}R | {sum(t['usd'] for t in part):+,.0f}$")
        sl = [t["slip"] for t in tr if t["slip"] is not None]
        if sl:
            L.append("")
            L.append(f"החלקת כניסה ממוצעת: {sum(sl)/len(sl):+.3f}% (שלילי = קנינו מתחת למחיר המתוכנן)")
        L.append("")
        best = sorted(tr, key=lambda t: -t["usd"])[:3]
        worst = sorted(tr, key=lambda t: t["usd"])[:3]
        L.append("הכי רווחיות: " + ", ".join(f"{t['ticker']} {t['usd']:+,.0f}$" for t in best))
        L.append("הכי מפסידות: " + ", ".join(f"{t['ticker']} {t['usd']:+,.0f}$" for t in worst))
        L += ["", f"הערה: מדגם של {n} עסקאות קטן מדי למסקנות סטטיסטיות."]
    text = "\n".join(L)
    print(text)
    open("perf_report.txt", "w", encoding="utf-8").write(text + "\n")
    json.dump(tr[-40:], open("trades_closed.json", "w", encoding="utf-8"), ensure_ascii=False)
    if os.getenv("SEND") == "1":
        send_telegram(text)


if __name__ == "__main__":
    main()
