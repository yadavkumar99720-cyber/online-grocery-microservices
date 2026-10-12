"""NOTIFICATION SERVICE (port 5006) - owns  data/notification.db  (table: notifications).
Simulated SMS/e-mail: messages are only stored. It is NON-CRITICAL: if it is down,
orders still succeed (the order-service uses a fallback).

REST:  POST /api/v1/notifications   GET /api/v1/notifications
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from flask import jsonify, request  # noqa: E402

from common import config, discovery  # noqa: E402
from common.flask_utils import make_app, open_db, quiet_werkzeug, rows  # noqa: E402

NAME = "notification-service"
PORT = config.SERVICE_PORTS[NAME]
DB_FILE = Path(__file__).resolve().parent / "data" / "notification.db"
app = make_app(NAME)


def db():
    return open_db(DB_FILE)


def init_db():
    conn = db()
    conn.execute("""CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER, order_id INTEGER,
        message TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    conn.close()


@app.post("/api/v1/notifications")
def send():
    d = request.get_json(silent=True) or {}
    if not d.get("message"):
        return jsonify({"error": "message is required"}), 400
    conn = db()
    try:
        cur = conn.execute("INSERT INTO notifications(customer_id,order_id,message) VALUES (?,?,?)",
                           (d.get("customer_id"), d.get("order_id"), d["message"]))
        return jsonify({"id": cur.lastrowid, "status": "SENT"}), 201
    finally:
        conn.close()


@app.get("/api/v1/notifications")
def list_all():
    conn = db()
    try:
        return jsonify(rows(conn.execute("SELECT * FROM notifications ORDER BY id DESC LIMIT 50")))
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    quiet_werkzeug()
    discovery.register_with_registry(NAME, PORT)
    print(f"{NAME} running on port {PORT}", flush=True)
    app.run(host=config.HOST, port=PORT, threaded=True)
