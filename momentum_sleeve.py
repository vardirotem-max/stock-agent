"""סליל מומנטום: מחזיק את MOM_N מניות S&P 500 עם מומנטום 12-1 הגבוה ביותר (מעל SMA200), שווה משקל, מאוזן אחת לחודש.
כל מניה עם סטופ הגנה GTC. מוחרג מנעילת הרווח/התקרה/הביקורת (דרך momentum_sleeve.json). מסחר דמה בלבד.
DRY=1 מדפיס בלי לסחור. FORCE=1 מתעלם ממרווח האיזון."""
import json
import math
import os
import time
from datetime import date, datetime

import pandas as pd

import broker
import config as C
from notify import send_telegram

FILE = "momentum_sleeve.json"
DRY = os.getenv("DRY", "") == "1"
FORCE = os.getenv("FORCE", "") == "1"


def select(px, vol, n=20):
    """px/vol: DataFrame של סגירות ונפח יומיים (עמודה לכל מניה). מחזיר רשימת טיקרים לפי מומנטום 12-1."""
    if len(px) < 260:
        return []
    last = px.iloc[-1]
    mom = px.iloc[-22] / px.iloc[-253] - 1
    sma200 = px.iloc[-200:].mean()
    dv = (px * vol).iloc[-20:].mean()
    ok = (last > sma200) & (last >= C.MIN_PRICE) & (dv >= C.MIN_DOLLAR_VOLUME) & mom.notna()
    return list(mom[ok].sort_values(ascending=False).head(n).index)


def load_state():
    try:
        return json.load(open(FILE, encoding="utf-8"))
    except Exception:
        return {"symbols": [], "rebalanced": None}


def save_state(st):
    json.dump(st, open(FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def main():
    st = load_state()
    if st["rebalanced"] and not FORCE:
        days = (date.today() - date.fromisoformat(st["rebalanced"])).days
        if days < C.MOM_REBAL_DAYS:
            print(f"איזון אחרון לפני {days} ימים - אין צורך (מינימום {C.MOM_REBAL_DAYS}).")
            return
    clock = broker._req("GET", "/v2/clock").json()
    if not clock.get("is_open") and not DRY:
        print("השוק סגור - לא סוחרים. יופעל שוב ביום מסחר.")
        return

    import yfinance as yf
    from data import get_sp500
    raw = yf.download(get_sp500(), period="14mo", interval="1d", auto_adjust=True, progress=False)
    px, vol = raw["Close"], raw["Volume"]
    px.index = pd.to_datetime(px.index).tz_localize(None)
    target = select(px, vol, C.MOM_N)
    if len(target) < C.MOM_N // 2:
        print("מעט מדי מניות עומדות בתנאים - לא מבצעים", target)
        return
    cur = set(st["symbols"])
    drop, add = sorted(cur - set(target)), [t for t in target if t not in cur]
    acc = broker._req("GET", "/v2/account").json()
    eq, cash = float(acc["equity"]), float(acc["cash"])
    per = eq * C.MOM_SLEEVE_PCT / 100 / C.MOM_N
    print(f"יעד: {target}\nלמכור: {drop}\nלקנות: {add}\nסכום למניה ~{per:,.0f}$ | מזומן {cash:,.0f}$")
    if DRY:
        return

    # רשימה מעודכנת נשמרת לפני הביצוע כדי שנעילת הרווח לא תיגע במניות הסליל
    save_state({"symbols": sorted(cur | set(add)), "rebalanced": st["rebalanced"]})
    os.system('git config user.name stock-bot; git config user.email stock-bot@users.noreply.github.com; '
              f'git add {FILE}; git commit -qm "momentum sleeve list (pre)"; git pull --rebase -q; git push -q')

    for sym in drop:
        for o in broker._req("GET", "/v2/orders", params={"status": "open", "limit": 100, "nested": "false"}).json():
            if o["symbol"] == sym:
                broker._req("DELETE", f"/v2/orders/{o['id']}")
        time.sleep(1)
        r = broker._req("DELETE", f"/v2/positions/{sym}")
        print("מכירה", sym, r.status_code)
    snaps = broker.snapshots(add) if add else {}
    bought = {}
    for sym in add:
        p = float(((snaps.get(sym) or {}).get("latestTrade") or {}).get("p") or 0)
        if p <= 0:
            continue
        qty = min(math.floor(per / p), math.floor(cash * 0.9 / p))
        if qty < 1:
            print("דילוג", sym, "(יקר מדי / אין מזומן)")
            continue
        r = broker._req("POST", "/v2/orders", json={"symbol": sym, "qty": str(qty), "side": "buy", "type": "market", "time_in_force": "day"})
        print("קנייה", sym, qty, r.status_code)
        if r.ok:
            bought[sym] = p
            cash -= qty * p
    time.sleep(15)
    pos = {p["symbol"]: p for p in broker._req("GET", "/v2/positions").json()}
    held = set(cur - set(drop))
    for sym, p in bought.items():
        if sym not in pos:
            print("לא מולא", sym)
            continue
        held.add(sym)
        q = int(float(pos[sym]["qty"]))
        stop = round(p * (1 - C.MOM_STOP_PCT / 100), 2)
        s = broker._req("POST", "/v2/orders", json={"symbol": sym, "qty": str(q), "side": "sell", "type": "stop", "stop_price": str(stop), "time_in_force": "gtc"})
        print("סטופ", sym, s.status_code)
    save_state({"symbols": sorted(held), "rebalanced": date.today().isoformat()})
    send_telegram(f"📈 סליל מומנטום אוזן: נוספו {len(bought)}, נמכרו {len(drop)}, סה\"כ {len(held)} מניות. מסחר דמה בלבד.")


if __name__ == "__main__":
    main()
