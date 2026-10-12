"""DELIVERY SERVICE (port 5005) - owns  data/delivery.db  (tables: agents, deliveries).

Business rule used to demo a Saga failure AFTER payment succeeded:
    pincodes starting with '999' are NOT serviceable -> HTTP 409.

REST:  POST /api/v1/deliveries   GET /api/v1/deliveries   GET /api/v1/deliveries/<id>
       PUT /api/v1/deliveries/<id>/status
       POST /api/v1/deliveries/<id>/cancel   (COMPENSATING ACTION)
       GET/POST /api/v1/deliveries/agents
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from flask import jsonify, request  # noqa: E402

from common import config, discovery  # noqa: E402
from common.flask_utils import make_app, open_db, quiet_werkzeug, rows  # noqa: E402

NAME = "delivery-service"
PORT = config.SERVICE_PORTS[NAME]
DB_FILE = Path(__file__).resolve().parent / "data" / "delivery.db"
app = make_app(NAME)
STATUSES = ("ASSIGNED", "OUT_FOR_DELIVERY", "DELIVERED", "CANCELLED")


def db():
    return open_db(DB_FILE)


def init_db():
    conn = db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS agents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            available INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS deliveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            agent_id INTEGER,
            address TEXT NOT NULL,
            pincode TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP);""")
    if conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0] == 0:
        conn.executemany("INSERT INTO agents(name) VALUES (?)",
                         [("Agent Kiran",), ("Agent Sana",), ("Agent Vikram",)])
    conn.close()


@app.post("/api/v1/deliveries")
def create_delivery():
    d = request.get_json(silent=True) or {}
    if not isinstance(d.get("order_id"), int) or not d.get("address") or not d.get("pincode"):
        return jsonify({"error": "order_id, address and pincode are required"}), 400
    conn = db()
    try:
        prev = conn.execute("SELECT * FROM deliveries WHERE order_id=? AND status!='CANCELLED'",
                            (d["order_id"],)).fetchone()
        if prev:                                                    # idempotent
            return jsonify(dict(prev)), 200
        if str(d["pincode"]).startswith("999"):
            return jsonify({"error": f"pincode {d['pincode']} is not serviceable"}), 409
        agent = conn.execute("""SELECT a.id FROM agents a
                                LEFT JOIN deliveries x ON x.agent_id=a.id
                                     AND x.status IN ('ASSIGNED','OUT_FOR_DELIVERY')
                                WHERE a.available=1 GROUP BY a.id
                                ORDER BY COUNT(x.id), a.id LIMIT 1""").fetchone()
        if not agent:
            return jsonify({"error": "no delivery agent available"}), 409
        cur = conn.execute("INSERT INTO deliveries(order_id,agent_id,address,pincode,status) "
                           "VALUES (?,?,?,?, 'ASSIGNED')",
                           (d["order_id"], agent["id"], d["address"], d["pincode"]))
        return jsonify(dict(conn.execute("SELECT * FROM deliveries WHERE id=?",
                                         (cur.lastrowid,)).fetchone())), 201
    finally:
        conn.close()


@app.get("/api/v1/deliveries")
def list_deliveries():
    conn = db()
    try:
        if request.args.get("order_id"):
            return jsonify(rows(conn.execute("SELECT * FROM deliveries WHERE order_id=?",
                                             (request.args["order_id"],))))
        return jsonify(rows(conn.execute("SELECT * FROM deliveries ORDER BY id")))
    finally:
        conn.close()


@app.get("/api/v1/deliveries/agents")
def list_agents():
    conn = db()
    try:
        return jsonify(rows(conn.execute("SELECT * FROM agents ORDER BY id")))
    finally:
        conn.close()


@app.post("/api/v1/deliveries/agents")
def add_agent():
    d = request.get_json(silent=True) or {}
    if not d.get("name"):
        return jsonify({"error": "name is required"}), 400
    conn = db()
    try:
        cur = conn.execute("INSERT INTO agents(name) VALUES (?)", (d["name"],))
        return jsonify({"id": cur.lastrowid, "name": d["name"], "available": 1}), 201
    finally:
        conn.close()


@app.get("/api/v1/deliveries/<int:did>")
def get_delivery(did):
    conn = db()
    try:
        r = conn.execute("SELECT * FROM deliveries WHERE id=?", (did,)).fetchone()
        return (jsonify(dict(r)), 200) if r else (jsonify({"error": "delivery not found"}), 404)
    finally:
        conn.close()


@app.put("/api/v1/deliveries/<int:did>/status")
def update_status(did):
    st = (request.get_json(silent=True) or {}).get("status")
    if st not in STATUSES:
        return jsonify({"error": f"status must be one of {STATUSES}"}), 400
    conn = db()
    try:
        if not conn.execute("SELECT 1 FROM deliveries WHERE id=?", (did,)).fetchone():
            return jsonify({"error": "delivery not found"}), 404
        conn.execute("UPDATE deliveries SET status=? WHERE id=?", (st, did))
        return jsonify(dict(conn.execute("SELECT * FROM deliveries WHERE id=?", (did,)).fetchone()))
    finally:
        conn.close()


@app.post("/api/v1/deliveries/<int:did>/cancel")
def cancel_delivery(did):
    """COMPENSATING ACTION for the 'arrange delivery' saga step. Idempotent."""
    conn = db()
    try:
        r = conn.execute("SELECT * FROM deliveries WHERE id=?", (did,)).fetchone()
        if not r:
            return jsonify({"error": "delivery not found"}), 404
        if r["status"] == "DELIVERED":
            return jsonify({"error": "already delivered, cannot cancel"}), 409
        conn.execute("UPDATE deliveries SET status='CANCELLED' WHERE id=?", (did,))
        return jsonify(dict(conn.execute("SELECT * FROM deliveries WHERE id=?", (did,)).fetchone()))
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    quiet_werkzeug()
    discovery.register_with_registry(NAME, PORT)
    print(f"{NAME} running on port {PORT}", flush=True)
    app.run(host=config.HOST, port=PORT, threaded=True)
