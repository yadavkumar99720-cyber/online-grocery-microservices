"""PAYMENT SERVICE (port 5004) - owns  data/payment.db  (table: payments).

Simulated payments only - NO real card data. Test tokens:
    tok_visa      -> always succeeds
    tok_decline   -> always declined (used to demo the Saga compensation)
Any amount above 20000 is also declined (limit rule).

REST:  POST /api/v1/payments   GET /api/v1/payments   GET /api/v1/payments/<id>
       POST /api/v1/payments/<id>/refund   (COMPENSATING ACTION)
       DELETE /api/v1/payments/<id>        (only for FAILED records)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from flask import jsonify, request  # noqa: E402

from common import config, discovery  # noqa: E402
from common.flask_utils import make_app, open_db, quiet_werkzeug, rows  # noqa: E402

NAME = "payment-service"
PORT = config.SERVICE_PORTS[NAME]
DB_FILE = Path(__file__).resolve().parent / "data" / "payment.db"
app = make_app(NAME)
AMOUNT_LIMIT = 20000


def db():
    return open_db(DB_FILE)


def init_db():
    conn = db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            method TEXT NOT NULL,
            status TEXT NOT NULL,          -- SUCCESS | FAILED | REFUNDED
            failure_reason TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP);""")
    conn.close()


@app.post("/api/v1/payments")
def create_payment():
    d = request.get_json(silent=True) or {}
    if not isinstance(d.get("order_id"), int) or not isinstance(d.get("amount"), (int, float)) \
            or d["amount"] <= 0:
        return jsonify({"error": "order_id (int) and amount (> 0) are required"}), 400
    method, token = d.get("method", "CARD"), d.get("token", "tok_visa")
    conn = db()
    try:
        prev = conn.execute("SELECT * FROM payments WHERE order_id=? AND status='SUCCESS'",
                            (d["order_id"],)).fetchone()
        if prev:                                           # idempotent: do not charge twice
            return jsonify(dict(prev)), 200
        reason = None
        if token == "tok_decline":
            reason = "card declined by issuer (test token)"
        elif d["amount"] > AMOUNT_LIMIT:
            reason = f"amount exceeds limit of {AMOUNT_LIMIT}"
        status = "FAILED" if reason else "SUCCESS"
        cur = conn.execute("INSERT INTO payments(order_id,amount,method,status,failure_reason) "
                           "VALUES (?,?,?,?,?)", (d["order_id"], d["amount"], method, status, reason))
        rec = dict(conn.execute("SELECT * FROM payments WHERE id=?", (cur.lastrowid,)).fetchone())
        if reason:
            return jsonify({"error": f"payment failed: {reason}", **rec}), 402
        return jsonify(rec), 201
    finally:
        conn.close()


@app.get("/api/v1/payments")
def list_payments():
    conn = db()
    try:
        if request.args.get("order_id"):
            return jsonify(rows(conn.execute("SELECT * FROM payments WHERE order_id=?",
                                             (request.args["order_id"],))))
        return jsonify(rows(conn.execute("SELECT * FROM payments ORDER BY id")))
    finally:
        conn.close()


@app.get("/api/v1/payments/<int:pid>")
def get_payment(pid):
    conn = db()
    try:
        r = conn.execute("SELECT * FROM payments WHERE id=?", (pid,)).fetchone()
        return (jsonify(dict(r)), 200) if r else (jsonify({"error": "payment not found"}), 404)
    finally:
        conn.close()


@app.post("/api/v1/payments/<int:pid>/refund")
def refund_payment(pid):
    """COMPENSATING ACTION for the 'process payment' saga step. Idempotent."""
    conn = db()
    try:
        r = conn.execute("SELECT * FROM payments WHERE id=?", (pid,)).fetchone()
        if not r:
            return jsonify({"error": "payment not found"}), 404
        if r["status"] == "FAILED":
            return jsonify({"error": "cannot refund a failed payment"}), 409
        conn.execute("UPDATE payments SET status='REFUNDED' WHERE id=?", (pid,))
        return jsonify(dict(conn.execute("SELECT * FROM payments WHERE id=?", (pid,)).fetchone()))
    finally:
        conn.close()


@app.delete("/api/v1/payments/<int:pid>")
def delete_payment(pid):
    conn = db()
    try:
        r = conn.execute("SELECT status FROM payments WHERE id=?", (pid,)).fetchone()
        if not r:
            return jsonify({"error": "payment not found"}), 404
        if r["status"] != "FAILED":
            return jsonify({"error": "only FAILED payment records can be deleted"}), 409
        conn.execute("DELETE FROM payments WHERE id=?", (pid,))
        return jsonify({"deleted": pid})
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    quiet_werkzeug()
    discovery.register_with_registry(NAME, PORT)
    print(f"{NAME} running on port {PORT}", flush=True)
    app.run(host=config.HOST, port=PORT, threaded=True)
