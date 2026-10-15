"""מנטר בשעות המסחר: מתריע אם לולאת נעילת הרווח לא פעילה, או אם יש פוזיציה בלי הגנה."""
import datetime as dt
import os

import requests

import broker
from notify import send_telegram


def runs(workflow):
    r = requests.get(
        f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/actions/workflows/{workflow}/runs",
        headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json"},
        params={"per_page": 10}, timeout=30)
    r.raise_for_status()
    return r.json().get("workflow_runs", [])


def main():
    clock = broker._req("GET", "/v2/clock").json()
    if not clock.get("is_open"):
        print("השוק סגור - אין מה לנטר")
        return
    now = dt.datetime.now(dt.timezone.utc)
    alerts = []
    ok = False
    for x in runs("profit_lock.yml"):
        t = dt.datetime.fromisoformat(x["created_at"].replace("Z", "+00:00"))
        if x["status"] in ("in_progress", "queued") or now - t < dt.timedelta(minutes=25):
            ok = True
            break
    if not ok:
        alerts.append("⚠️ נעילת הרווח היומית לא רצה ב-25 הדקות האחרונות בזמן שהשוק פתוח. הפעל ידנית 'Daily profit cycle' עם loop=1.")
    try:
        problems, n = broker.audit()
        alerts += problems
    except Exception as e:
        alerts.append(f"⚠️ בדיקת ההגנה נכשלה: {str(e)[:100]}")
    if alerts:
        send_telegram("🛡 מנטר\n" + "\n".join(alerts))
        print("\n".join(alerts))
    else:
        print("הכל תקין")


if __name__ == "__main__":
    main()
