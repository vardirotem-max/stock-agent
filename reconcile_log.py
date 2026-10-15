"""מסנכרן את signals_log.csv מול Alpaca (הוראות שבוטלו, פוזיציות שנסגרו)."""
from scanner import load_log, reconcile_with_broker, save_log

rows = load_log()
for e in reconcile_with_broker(rows):
    print(e)
save_log(rows)
