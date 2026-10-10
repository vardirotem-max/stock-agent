"""שומר: מתריע בטלגרם אם הריצה היומית לא הצליחה ב-30 השעות האחרונות."""
import datetime as dt
import os
import sys

import requests

from notify import send_telegram


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    r = requests.get(
        f"https://api.github.com/repos/{repo}/actions/workflows/daily.yml/runs",
        headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json"},
        params={"status": "success", "per_page": 5}, timeout=30,
    )
    r.raise_for_status()
    runs = r.json().get("workflow_runs", [])
    now = dt.datetime.now(dt.timezone.utc)
    recent = [x for x in runs if now - dt.datetime.fromisoformat(x["created_at"].replace("Z", "+00:00")) < dt.timedelta(hours=30)]
    if recent:
        print("OK - יש ריצה מוצלחת ב-30 השעות האחרונות")
        return
    send_telegram("🚨 השומר: לא הייתה ריצה יומית מוצלחת ב-30 השעות האחרונות. בדוק ב-GitHub Actions.")
    sys.exit(1)


if __name__ == "__main__":
    main()
