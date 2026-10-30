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


def cap_by_group(ranked, groups, cap, n):
    """ranked: טיקרים מהחזק לחלש; groups: טיקר->תעשייה (חסר = ייחודי). מחזיר עד n לפי סדר, לא יותר מ-cap מכל תעשייה."""
    out, cnt = [], {}
    for t in ranked:
        g = groups.get(t) or t
        if cnt.get(g, 0) >= cap:
            continue
        cnt[g] = cnt.get(g, 0) + 1
        out.append(t)
        if len(out) >= n:
            break
    return out


def breached(pl, cost, pct):
    return cost > 0 and pl / cost <= -pct / 100


def commit_state(msg):
    os.system('git config user.name stock-bot; git config user.email stock-bot@users.noreply.github.com; '
              f'git add {FILE}; git commit -qm "{msg}"; git pull --rebase -q --autostash; git push -q')


def sell_symbols(syms):
    for sym in syms:
        for o in broker._req("GET", "/v2/orders", params={"status": "open", "limit": 100, "nested": "false"}).json():
            if o["symbol"] == sym:
                broker._req("DELETE", f"/v2/orders/{o['id']}")
        time.sleep(1)
        r = broker._req("DELETE", f"/v2/positions/{sym}")
        print("מכירה", sym, r.status_code)


def kill_if_needed():
    """מפסק: אם הסליל הפסיד MOM_KILL_PCT% מהעלות - סוגר אותו. נקרא מלולאת נעילת הרווח."""
    st = load_state()
    syms = set(st.get("symbols", []))
    if not syms:
        return False
    pos = [p for p in broker._req("GET", "/v2/positions").json() if p["symbol"] in syms]
    cost = sum(abs(float(p["cost_basis"])) for p in pos)
    pl = sum(float(p["unrealized_pl"]) for p in pos)
    if not breached(pl, cost, C.MOM_KILL_PCT):
        return False
    sell_symbols(sorted(syms))
    save_state({"symbols": [], "rebalanced": date.today().isoformat(), "killed": date.today().isoformat()})
    commit_state("momentum sleeve kill switch")
    send_telegram(f"🛑 סליל המומנטום הפסיד {pl / cost * 100:.1f}% מהעלות ({pl:+,.0f}$) ונסגר. עובר למזומן עד האיזון הבא. מסחר דמה בלבד.")
    return True


def earnings_guard(st):
    """יציאה ממניות סליל שדוחן קרוב מאוד (מונע פערי מחיר כמו INTC/TWLO)."""
    import earnings
    out = []
    today = earnings.today_us()
    for sym in st.get("symbols", []):
        ed = earnings.next_earnings(sym)
        if ed is not None and 0 <= (ed - today).days <= C.MOM_EARNINGS_EXIT_DAYS:
            out.append(sym)
    return out


def load_state():
    try:
        return json.load(open(FILE, encoding="utf-8"))
    except Exception:
        return {"symbols": [], "rebalanced": None}


def save_state(st):
    json.dump(st, open(FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def main():
    st = load_state()
    clock0 = broker._req("GET", "/v2/clock").json()
    if clock0.get("is_open") and not DRY and st.get("symbols"):
        if kill_if_needed():
            return
        ex = earnings_guard(st)
        if ex:
            print("יציאה לפני דוחות:", ex)
            sell_symbols(ex)
            st["symbols"] = sorted(set(st["symbols"]) - set(ex))
            save_state(st)
            commit_state("momentum sleeve earnings exit")
            send_telegram(f"📅 סליל מומנטום: נמכרו לפני דוחות רבעוניים: {', '.join(ex)}. מסחר דמה בלבד.")
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
    ranked = select(px, vol, 80)
    import earnings
    groups, ok = {}, []
    today_us = earnings.today_us()
    for t in ranked[:70]:
        try:
            groups[t] = yf.Ticker(t).info.get("industry")
        except Exception:
            groups[t] = None
        ed = earnings.next_earnings(t)
        if ed is not None and 0 <= (ed - today_us).days <= C.MOM_EARNINGS_BLOCK_DAYS:
            print(f"דילוג על {t}: דוח {ed}")
            continue
        ok.append(t)
    target = cap_by_group(ok, groups, C.MOM_PER_INDUSTRY, C.MOM_N)
    if len(target) < C.MOM_N // 2:
        print("מעט מדי מניות עומדות בתנאים - לא מבצעים", target)
        return
    cur = set(st["symbols"])
    drop, add = sorted(cur - set(target)), [t for t in target if t not in cur]
    acc = broker._req("GET", "/v2/account").json()
    eq, cash = float(acc["equity"]), float(acc["cash"])
    posn = {p["symbol"]: p for p in broker._req("GET", "/v2/positions").json()}
    kept_val = sum(float(posn[s]["market_value"]) for s in cur if s in target and s in posn)
    budget = max(0.0, eq * C.MOM_SLEEVE_PCT / 100 - kept_val)
    per = min(budget / max(1, len(add)), eq * C.MOM_SLEEVE_PCT / 100 / C.MOM_N * 1.5)
    print(f"תעשיות: { {t: groups.get(t) for t in target} }")
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
