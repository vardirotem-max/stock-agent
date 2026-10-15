"""ליבת SPY: קונה SPY ל-CORE_PCT% מהשווי עם סטופ הגנה GTC, אם אין עדיין."""
import os, math
import broker, config as C
from notify import send_telegram

DRY = os.getenv("DRY", "") == "1"


def main():
    acc = broker._req("GET", "/v2/account").json()
    eq, cash = float(acc["equity"]), float(acc["cash"])
    pos = {p["symbol"]: p for p in broker._req("GET", "/v2/positions").json()}
    for sym in C.CORE_SYMBOLS:
        snap = broker.snapshots([sym]).get(sym) or {}
        px = float((snap.get("latestTrade") or {}).get("p") or 0)
        if px <= 0:
            print("אין מחיר", sym); continue
        want = math.floor(eq * C.CORE_PCT / 100 / px)
        have = float(pos[sym]["qty"]) if sym in pos else 0
        add = min(want - have, math.floor(cash * 0.95 / px))
        print(f"{sym}: מחיר {px}, יעד {want}, יש {have:g}, לקנות {add:g}")
        if add < 1 or DRY:
            continue
        r = broker._req("POST", "/v2/orders", json={"symbol": sym, "qty": str(int(add)), "side": "buy", "type": "market", "time_in_force": "day"})
        print("קנייה", r.status_code, r.text[:200])
        if not r.ok:
            continue
        import time; time.sleep(5)
        p = broker._req("GET", f"/v2/positions/{sym}")
        q = int(float(p.json()["qty"])) if p.ok else int(add)
        stop = round(px * (1 - C.CORE_STOP_PCT / 100), 2)
        s = broker._req("POST", "/v2/orders", json={"symbol": sym, "qty": str(q), "side": "sell", "type": "stop", "stop_price": str(stop), "time_in_force": "gtc"})
        print("סטופ", s.status_code, s.text[:200])
        send_telegram(f"🧱 ליבת {sym}: נקנו {int(add)} מניות ב~{px}, סטופ הגנה {stop}. מסחר דמה בלבד.")


if __name__ == "__main__":
    main()
