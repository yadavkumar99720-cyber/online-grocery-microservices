"""CUSTOMER SERVICE (port 5001) - owns  data/customer.db  (table: customers).

REST:  GET/POST /api/v1/customers      GET/PUT/DELETE /api/v1/customers/<id>
All data is FAKE (no real personal data).
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from flask import jsonify, request  # noqa: E402

from common import config, discovery  # noqa: E402
from common.flask_utils import make_app, open_db, quiet_werkzeug, rows  # noqa: E402

NAME = "customer-service"
PORT = config.SERVICE_PORTS[NAME]
DB_FILE = Path(__file__).resolve().parent / "data" / "customer.db"
app = make_app(NAME)


def db():
    return open_db(DB_FILE)


def init_db():
    conn = db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            phone TEXT,
            address TEXT NOT NULL,
            pincode TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP);""")
    if conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO customers(name,email,phone,address,pincode) VALUES (?,?,?,?,?)", [
                ("Asha Demo", "asha@example.com", "9000000001", "12 Green Street, Hyderabad", "500001"),
                ("Ravi Demo", "ravi@example.com", "9000000002", "45 Lake View Road, Hyderabad", "500032"),
                ("Meera Demo", "meera@example.com", "9000000003", "7 Hill Colony, Remote Village", "999001"),
            ])
    conn.close()


REQUIRED = ("name", "email", "address", "pincode")


@app.get("/api/v1/customers")
def list_customers():
    conn = db()
    try:
        return jsonify(rows(conn.execute("SELECT * FROM customers ORDER BY id")))
    finally:
        conn.close()


@app.get("/api/v1/customers/<int:cid>")
def get_customer(cid):
    conn = db()
    try:
        r = conn.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()
        return (jsonify(dict(r)), 200) if r else (jsonify({"error": "customer not found"}), 404)
    finally:
        conn.close()


@app.post("/api/v1/customers")
def create_customer():
    d = request.get_json(silent=True) or {}
    missing = [f for f in REQUIRED if not str(d.get(f, "")).strip()]
    if missing:
        return jsonify({"error": f"missing fields: {', '.join(missing)}"}), 400
    conn = db()
    try:
        cur = conn.execute("INSERT INTO customers(name,email,phone,address,pincode) VALUES (?,?,?,?,?)",
                           (d["name"], d["email"], d.get("phone"), d["address"], d["pincode"]))
        r = conn.execute("SELECT * FROM customers WHERE id=?", (cur.lastrowid,)).fetchone()
        return jsonify(dict(r)), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "email already registered"}), 409
    finally:
        conn.close()


@app.put("/api/v1/customers/<int:cid>")
def update_customer(cid):
    d = request.get_json(silent=True) or {}
    conn = db()
    try:
        r = conn.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()
        if not r:
            return jsonify({"error": "customer not found"}), 404
        new = {k: d.get(k, r[k]) for k in ("name", "email", "phone", "address", "pincode")}
        try:
            conn.execute("UPDATE customers SET name=?,email=?,phone=?,address=?,pincode=? WHERE id=?",
                         (*new.values(), cid))
        except sqlite3.IntegrityError:
            return jsonify({"error": "email already registered"}), 409
        return jsonify(dict(conn.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()))
    finally:
        conn.close()


@app.delete("/api/v1/customers/<int:cid>")
def delete_customer(cid):
    conn = db()
    try:
        cur = conn.execute("DELETE FROM customers WHERE id=?", (cid,))
        if cur.rowcount == 0:
            return jsonify({"error": "customer not found"}), 404
        return jsonify({"deleted": cid})
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    quiet_werkzeug()
    discovery.register_with_registry(NAME, PORT)
    print(f"{NAME} running on port {PORT}", flush=True)
    app.run(host=config.HOST, port=PORT, threaded=True)
