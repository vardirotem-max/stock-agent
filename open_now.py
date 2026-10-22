"""פתיחת פוזיציות חדשות עכשיו, בזמן שהשוק פתוח (חשבון דמה). DRY=1 מדפיס בלבד ולא שולח הוראות.

שלבים: מגמה ונזילות מהנרות היומיים -> מחיר חי מ-Alpaca -> תנאי כניסה על המחיר החי ->
קונצנזוס אנליסטים (כולל יעד המחיר של האנליסטים מעל היעד שלנו) -> דוחות רבעוניים -> הוראות bracket.
"""
import os
import sys
import time

import pandas as pd

import analysts
import broker
import config as C
import earnings
import state as st
from data import download, get_sp500
from notify import send_telegram
from scanner import load_log, position_size, save_log
from strategy import add_indicators

N_NEW = int(os.getenv("N_NEW", "4"))
ENV_EXCLUDE = {x.strip().upper() for x in os.getenv("EXCLUDE", "").split(",") if x.strip()}
DRY = os.getenv("DRY") == "1"
L = []


def out(s=""):
    print(s)
    L.append(s)


def _dt_now(tz):
    import datetime as dt
    return dt.datetime.now(tz)


def weekly_pl(acc):
    """רווח/הפסד מתחילת השבוע: שווי נוכחי פחות שווי הסגירה האחרונה לפני יום שני הנוכחי."""
    try:
        import datetime as dt
        h = broker.portfolio_history("1M")
        today = dt.datetime.now(dt.timezone.utc).date()
        monday = today - dt.timedelta(days=today.weekday())
        prev = [e for t, e in zip(h["timestamp"], h["equity"])
                if e and dt.datetime.fromtimestamp(t, dt.timezone.utc).date() < monday]
        return float(acc["equity"]) - prev[-1] if prev else None
    except Exception as e:
        out(f"שבועי: {e}")
        return None


def main(n_new=None, exclude=()):
    L.clear()
    if not broker.enabled():
        sys.exit("אין מפתחות Alpaca")
    clock = broker._req("GET", "/v2/clock").json()
    if not clock.get("is_open"):
        out("השוק סגור - לא שולח הוראות.")
        return finish()
    acc0 = broker._req("GET", "/v2/account").json()
    day_pl = float(acc0["equity"]) - float(acc0["last_equity"])
    if day_pl <= -C.NEW_ENTRY_MAX_DAY_LOSS:
        out(f"היום החשבון כבר {day_pl:+,.2f}$ (מגבלה -{C.NEW_ENTRY_MAX_DAY_LOSS:,.0f}$): לא פותח פוזיציות חדשות.")
        return finish()
    # לא נכנסים בדקות הראשונות של המסחר (מחירים תנודתיים, פערים)
    from zoneinfo import ZoneInfo
    et = _dt_now(ZoneInfo("America/New_York"))
    since_open = et.hour * 60 + et.minute - (9 * 60 + 30)
    if 0 <= since_open < C.NO_ENTRY_FIRST_MINUTES:
        out(f"עברו רק {since_open} דקות מפתיחת המסחר (מינימום {C.NO_ENTRY_FIRST_MINUTES}): לא פותח פוזיציות עדיין.")
        return finish()
    # מגבלת הפסד שבועית
    wk = weekly_pl(acc0)
    if wk is not None and wk <= -C.WEEKLY_LOSS_LIMIT:
        out(f"הפסד שבועי {wk:+,.2f}$ (מגבלה -{C.WEEKLY_LOSS_LIMIT:,.0f}$): לא פותח פוזיציות חדשות.")
        return finish()
    state = st.load()
    if state.get("paused"):
        out("הבוט מושהה - לא שולח הוראות.")
        return finish()

    # פוזיציות והוראות קיימות (מקור אמת: Alpaca)
    pos = {p["symbol"] for p in broker._req("GET", "/v2/positions").json()}
    open_orders = broker._req("GET", "/v2/orders", params={"status": "open", "limit": 200, "nested": "false"}).json()
    pending = {o["symbol"] for o in open_orders if o["side"] == "buy"}
    # מרווח בין כניסות: לא נכנסים שוב למניה שנמכרה בשעות האחרונות (חוסך עלות החלקה)
    import datetime as _dt
    since = (_dt.datetime.utcnow() - _dt.timedelta(hours=C.REENTRY_COOLDOWN_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = broker._req("GET", "/v2/orders", params={"status": "closed", "after": since, "limit": 500, "direction": "desc"})
    recent_sold = {o["symbol"] for o in (r.json() if r.ok else []) if o["side"] == "sell" and float(o.get("filled_qty") or 0) > 0}
    busy = pos | pending | set(exclude) | ENV_EXCLUDE | recent_sold
    slots = C.MAX_OPEN_POSITIONS - len(pos | pending)
    want = min(n_new or N_NEW, slots)
    out(f"פוזיציות פתוחות {len(pos)}, הוראות קנייה ממתינות {len(pending)}, מקומות פנויים {slots}, מבקש {want}")
    if want <= 0:
        return finish()

    raw = download(get_sp500() + ["SPY"])
    data = {t: add_indicators(d) for t, d in raw.items()}
    spy = data.pop("SPY")
    today = pd.Timestamp.now("America/New_York").tz_localize(None).normalize()
    spy_ok = bool(spy["Close"].iloc[-1] > spy["sma200"].iloc[-1]) if len(spy) else True
    out(f"פילטר שוק: SPY {'מעל' if spy_ok else 'מתחת'} ל-SMA200")
    if C.USE_MARKET_FILTER and not spy_ok:
        out("שוק בלתי מתאים - לא נפתחות פוזיציות.")
        return finish()
    try:
        sp = broker.snapshots(["SPY"])["SPY"]
        spy_chg = sp["latestTrade"]["p"] / sp["prevDailyBar"]["c"] - 1
        out(f"SPY היום: {spy_chg * 100:+.2f}%")
        if spy_chg <= -0.015:
            out("השוק כולו יורד חזק (SPY -1.5% ומטה) - לא פותח פוזיציות חדשות.")
            return finish()
    except Exception as e:
        out(f"בדיקת SPY נכשלה ({e}) - ממשיך.")

    # שלב 1: מגמה ונזילות לפי הנרות השלמים (בלי נר היום)
    pre = []
    for t, df in data.items():
        if t in busy or "-" in t:  # סימבולים עם מקף (BRK-B) לא נתמכים אחיד ב-Alpaca
            continue
        d = df[df.index < today]
        if len(d) < 210:
            continue
        r = d.iloc[-1]
        if (r["Close"] >= C.MIN_PRICE and r["dollar_vol"] >= C.MIN_DOLLAR_VOLUME and r["Close"] > r["sma200"]
                and r["sma50"] > r["sma200"] and r["sma200_up"] and r["rsi"] <= 66 and r["Close"] <= r["sma20"] * 1.07):
            pre.append(t)
    out(f"אחרי מגמה ונזילות: {len(pre)} מניות")

    # שלב 2: מחיר חי ובדיקת תנאי כניסה עליו
    snaps = {}
    for i in range(0, len(pre), 100):
        snaps.update(broker.snapshots(pre[i:i + 100]))
    cands = []
    for t in pre:
        s = snaps.get(t) or {}
        live = (s.get("latestTrade") or {}).get("p")
        prev = (s.get("prevDailyBar") or {}).get("c")
        if not live or not prev:
            continue
        d = data[t][data[t].index < today]
        yday = float(d["Close"].iloc[-1])
        if abs(prev / yday - 1) > C.DATA_CROSSCHECK_TOLERANCE:
            continue  # פער בין המקורות: לא סומכים
        chg = live / prev - 1
        if chg < -0.04 or chg > 0.03:
            continue  # נפילה חדה (חדשות?) או ריצה שכבר קרתה
        row = pd.DataFrame({"Open": [live], "High": [live], "Low": [live], "Close": [live], "Volume": [d["Volume"].iloc[-1]]},
                           index=[today])
        e = add_indicators(pd.concat([d[["Open", "High", "Low", "Close", "Volume"]], row])).iloc[-1]
        atr = float(e["atr"])
        entry = round(live * (1 + C.ENTRY_PREMIUM), 2)  # לימיט צמוד לשוק: מתמלא מיד
        stop = round(entry - C.STOP_ATR * atr, 2)
        risk = entry - stop
        rp = risk / entry
        if not (C.MIN_RISK_PCT <= rp <= C.MAX_RISK_PCT):
            continue
        near20 = live <= e["sma20"] * 1.01
        strict = near20 and e["rsi"] <= C.RSI_MAX and live >= e["sma50"] * C.MIN_VS_SMA50
        relaxed = live <= e["sma20"] * 1.03 and e["rsi"] <= 55 and live >= e["sma50"] * 0.98
        if not (strict or relaxed):
            continue
        cands.append({"ticker": t, "live": live, "entry": entry, "stop": stop, "target": round(entry + C.RR * risk, 2),
                      "rsi": float(e["rsi"]), "mom": float(e["mom"]) if pd.notna(e["mom"]) else -1.0,
                      "tier": 1 if strict else 2, "chg": chg})
    out(f"עומדות בתנאי כניסה על המחיר החי: {len(cands)} (חמורות: {sum(c['tier'] == 1 for c in cands)})")
    cands.sort(key=lambda c: (c["tier"], -c["mom"]))

    # שלב 3: אנליסטים ודוחות
    chosen, rejected = [], []
    for c in cands[:40]:
        a = analysts.get_analyst(c["ticker"])
        if a is None or a["n"] < C.ANALYST_MIN_OPINIONS:
            rejected.append(f"{c['ticker']}: אין מספיק אנליסטים")
            continue
        if not analysts.passes(a, c["entry"]):
            rejected.append(f"{c['ticker']}: קונצנזוס/יעד אנליסטים לא מספיק ({analysts.describe(a, c['entry'])})")
            continue
        if not a["target"] or a["target"] < c["target"]:
            rejected.append(f"{c['ticker']}: יעד האנליסטים {a['target']} נמוך מהיעד שלנו {c['target']}")
            continue
        ed = earnings.next_earnings(c["ticker"])
        if earnings.blocked(ed):
            rejected.append(f"{c['ticker']}: {earnings.describe(ed)} - חסום")
            continue
        c["analyst"], c["earn"] = a, ed
        c["score"] = (a["target"] / c["entry"] - 1) * 100 - a["mean"] * 3 + c["mom"] * 10
        chosen.append(c)
        if len(chosen) >= 12:
            break
    chosen.sort(key=lambda c: (c["tier"], -c["score"]))
    # פיזור: לא יותר מ-2 מניות מאותו סקטור, כדי שלא ייפלו כולן יחד
    picked, per_sector = [], {}
    for c in chosen:
        sec = c["analyst"].get("sector") or c["ticker"]
        if per_sector.get(sec, 0) >= 2:
            out(f"  דילוג על {c['ticker']}: כבר 2 מניות מסקטור {sec}")
            continue
        per_sector[sec] = per_sector.get(sec, 0) + 1
        picked.append(c)
        if len(picked) >= want:
            break
    chosen = picked
    out("")
    out(f"נדחו אחרי בדיקת אנליסטים/דוחות ({len(rejected)}):")
    for r in rejected:
        out("  - " + r)
    out("")
    if not chosen:
        out("לא נמצאה מניה שעוברת את כל הבדיקות. לא נשלחו הוראות.")
        return finish()

    rows = load_log()
    placed = 0
    msg = [f"⚡ פתיחת פוזיציות עכשיו (השוק פתוח) — {len(chosen)} מניות", ""]
    for c in chosen:
        qty = position_size(c["entry"], c["stop"])
        c["qty"] = qty
        capp = broker.profit_cap_price(c["entry"], qty)
        if capp is not None:
            c["target"] = max(min(c["target"], capp), round(c["entry"] + 0.01, 2))
        out(f"{c['ticker']}: חי {c['live']:.2f} | כניסה {c['entry']} סטופ {c['stop']} יעד {c['target']} | {qty} מניות | "
            f"שכבה {c['tier']} RSI {c['rsi']:.0f} | {analysts.describe(c['analyst'], c['entry'])} | {earnings.describe(c['earn'])}")
        if qty < 1:
            continue
        placed += 1
        oid = "DRY"
        if not DRY:
            oid = broker.place_bracket(c["ticker"], qty, c["entry"], c["stop"], c["target"],
                                       client_id=f"now-{today:%Y%m%d}-{c['ticker']}-{int(time.time())}")
            rows.append({"signal_date": f"{today:%Y-%m-%d}", "ticker": c["ticker"], "entry": c["entry"], "stop": c["stop"],
                         "target": c["target"], "shares": qty, "status": "pending", "order_id": oid, "source": "now"})
        msg.append(f"{'🧪' if DRY else '📨'} {c['ticker']}: {qty} מניות | כניסה {c['entry']} | סטופ {c['stop']} | יעד {c['target']}\n"
                   f"   {analysts.describe(c['analyst'], c['entry'])}\n   {earnings.describe(c['earn'])}")
    msg.append("\nמסחר דמה בלבד. לא ייעוץ השקעות.")
    if not DRY:
        save_log(rows)
        send_telegram("\n".join(msg))
    finish()
    return placed


def finish():
    open("open_now_report.txt", "w", encoding="utf-8").write("\n".join(L) + "\n")
    return 0


if __name__ == "__main__":
    import traceback
    try:
        main()
    except Exception:
        out("שגיאה:\n" + traceback.format_exc())
        finish()
        sys.exit(1)
