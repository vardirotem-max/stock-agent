"""מריץ את מחזור הרווח בלולאה (כל 60 שניות) עד סגירת השוק, ושומר מצב ולוג לריפו כל כמה דקות."""
import subprocess, sys, time, broker


def sh(*a):
    return subprocess.run(a, capture_output=True, text=True)


def persist(snap):
    if snap:
        sh(sys.executable, "snapshot.py")
    files = ["signals_log.csv", "state.json", "profit_lock_report.txt"] + (["dashboard_data.json"] if snap else [])
    sh("git", "config", "user.name", "stock-bot")
    sh("git", "config", "user.email", "stock-bot@users.noreply.github.com")
    sh("git", "add", *files)
    if sh("git", "diff", "--cached", "--quiet").returncode == 0:
        return
    sh("git", "commit", "-m", "profit loop state")
    for _ in range(3):
        sh("git", "pull", "--rebase", "--autostash", "-q")
        if sh("git", "push", "-q").returncode == 0:
            return
        sh("git", "rebase", "--abort")
    print("push נכשל - ממשיכים")


end = time.time() + 5.5 * 3600
i = 0
while time.time() < end:
    clock = broker._req("GET", "/v2/clock").json()
    if not clock.get("is_open"):
        print("השוק סגור - יוצא"); break
    sh("git", "fetch", "-q", "origin", "main")
    sh("git", "checkout", "origin/main", "--", "momentum_sleeve.json")  # רשימת הסליל עדכנית לפני כל מחזור
    subprocess.run([sys.executable, "profit_lock.py"])
    i += 1
    if i % 5 == 0:
        persist(True)
    time.sleep(60)
persist(True)
