"""מריץ את מחזור הרווח בלולאה (כל 60 שניות) עד סגירת השוק - במקום להסתמך על cron של GitHub."""
import subprocess, sys, time, broker

end = time.time() + 5.5 * 3600
while time.time() < end:
    clock = broker._req("GET", "/v2/clock").json()
    if not clock.get("is_open"):
        print("השוק סגור - יוצא"); break
    subprocess.run([sys.executable, "profit_lock.py"])
    time.sleep(60)
