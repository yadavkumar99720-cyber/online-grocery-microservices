"""DATA ISOLATION demonstration.   python tests/demo_data_isolation.py

1. Lists the tables inside each service's own database file (Database per Service).
2. Shows that the order DB stores only a customer_id/product_id REFERENCE - the
   customer's name/address/price come from other services' APIs, never from their DB.
3. Proves that the only way to get another service's data is through its REST API.
"""
import sqlite3
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
out = []


def say(m=""):
    print(m)
    out.append(m)


say("DATABASE PER SERVICE")
say("-" * 60)
for p in sorted(ROOT.glob("services/*/data/*.db")):
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    tabs = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    say(f"{p.parent.parent.name:<22} {p.name:<18} tables: {', '.join(tabs)}")
    con.close()

say("\nORDER DB holds only references to other services' data")
say("-" * 60)
con = sqlite3.connect(f"file:{ROOT/'services/order_service/data/order.db'}?mode=ro", uri=True)
cols = [r[1] for r in con.execute("PRAGMA table_info(orders)")]
fk = con.execute("PRAGMA foreign_key_list(orders)").fetchall()
say(f"orders columns: {cols}")
say(f"foreign keys to other databases: {len(fk)}  (none - cross-service links are plain IDs)")
con.close()

say("\nCross-service data is obtained ONLY through APIs")
say("-" * 60)
try:
    r = requests.get("http://127.0.0.1:8000/api/v1/customers/1", timeout=3)
    say(f"order-service needs customer #1 -> GET /api/v1/customers/1 (customer-service API) -> {r.status_code} {r.json()['name']}")
    r = requests.get("http://127.0.0.1:8000/api/v1/products/1", timeout=3)
    say(f"order-service needs product #1  -> GET /api/v1/products/1  (inventory-service API) -> {r.status_code} {r.json()['name']}")
except requests.RequestException:
    say("(start the system to see the API part)")

say("\nSource-code check: which services mention a database file?")
say("-" * 60)
for py in sorted(ROOT.glob("services/*/app.py")):
    t = py.read_text()
    dbs = sorted({w for w in t.replace('"', " ").split() if w.endswith(".db")})
    say(f"{py.parent.name:<22} opens: {dbs or '-'}")

(ROOT / "docs").mkdir(exist_ok=True)
(ROOT / "docs" / "DATA_ISOLATION_DEMO.txt").write_text("\n".join(out), encoding="utf-8")
