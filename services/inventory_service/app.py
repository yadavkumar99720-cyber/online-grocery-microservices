"""INVENTORY SERVICE = product catalogue + stock (port 5002).
Owns  data/inventory.db  (tables: products, reservations).

REST:   GET/POST /api/v1/products     GET/PUT/DELETE /api/v1/products/<id>
Saga:   POST /api/v1/inventory/reserve   (step    - reserve stock for an order)
        POST /api/v1/inventory/commit    (step    - confirm the reservation)
        POST /api/v1/inventory/release   (COMPENSATION - give stock back)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from flask import jsonify, request  # noqa: E402

from common import config, discovery  # noqa: E402
from common.flask_utils import make_app, open_db, quiet_werkzeug, rows  # noqa: E402

NAME = "inventory-service"
PORT = config.SERVICE_PORTS[NAME]
DB_FILE = Path(__file__).resolve().parent / "data" / "inventory.db"
app = make_app(NAME)


def db():
    return open_db(DB_FILE)


def init_db():
    conn = db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            unit TEXT NOT NULL DEFAULT 'pc',
            price REAL NOT NULL CHECK (price >= 0),
            stock INTEGER NOT NULL CHECK (stock >= 0));
        CREATE TABLE IF NOT EXISTS reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_ref INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            status TEXT NOT NULL,             -- RESERVED | COMMITTED | RELEASED
            created_at TEXT DEFAULT CURRENT_TIMESTAMP);""")
    if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        conn.executemany("INSERT INTO products(name,category,unit,price,stock) VALUES (?,?,?,?,?)", [
            ("Basmati Rice", "Grains", "1 kg", 95.0, 100),
            ("Toor Dal", "Pulses", "1 kg", 140.0, 80),
            ("Whole Wheat Atta", "Grains", "5 kg", 260.0, 60),
            ("Full Cream Milk", "Dairy", "1 L", 62.0, 50),
            ("Farm Eggs", "Dairy", "12 pcs", 84.0, 40),
            ("Tomato", "Vegetables", "1 kg", 30.0, 120),
            ("Onion", "Vegetables", "1 kg", 35.0, 150),
            ("Banana", "Fruits", "1 dozen", 55.0, 70),
            ("Sunflower Oil", "Groceries", "1 L", 150.0, 45),
            ("Tea Powder", "Beverages", "250 g", 120.0, 3),   # tiny stock -> easy to demo "out of stock"
        ])
    conn.close()


# ------------------------------------------------------------------ products CRUD
@app.get("/api/v1/products")
def list_products():
    sql, args = "SELECT * FROM products WHERE 1=1", []
    if request.args.get("category"):
        sql += " AND category=?"
        args.append(request.args["category"])
    if request.args.get("q"):
        sql += " AND name LIKE ?"
        args.append(f"%{request.args['q']}%")
    conn = db()
    try:
        return jsonify(rows(conn.execute(sql + " ORDER BY id", args)))
    finally:
        conn.close()


@app.get("/api/v1/products/<int:pid>")
def get_product(pid):
    conn = db()
    try:
        r = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
        return (jsonify(dict(r)), 200) if r else (jsonify({"error": "product not found"}), 404)
    finally:
        conn.close()


def _valid_product(d, partial=False):
    for f in ("name", "category", "price", "stock"):
        if not partial and f not in d:
            return f"missing field: {f}"
    if "price" in d and (not isinstance(d["price"], (int, float)) or d["price"] < 0):
        return "price must be a non-negative number"
    if "stock" in d and (not isinstance(d["stock"], int) or d["stock"] < 0):
        return "stock must be a non-negative integer"
    return None


@app.post("/api/v1/products")
def create_product():
    d = request.get_json(silent=True) or {}
    err = _valid_product(d)
    if err:
        return jsonify({"error": err}), 400
    conn = db()
    try:
        cur = conn.execute("INSERT INTO products(name,category,unit,price,stock) VALUES (?,?,?,?,?)",
                           (d["name"], d["category"], d.get("unit", "pc"), d["price"], d["stock"]))
        return jsonify(dict(conn.execute("SELECT * FROM products WHERE id=?",
                                         (cur.lastrowid,)).fetchone())), 201
    finally:
        conn.close()


@app.put("/api/v1/products/<int:pid>")
def update_product(pid):
    d = request.get_json(silent=True) or {}
    err = _valid_product(d, partial=True)
    if err:
        return jsonify({"error": err}), 400
    conn = db()
    try:
        r = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
        if not r:
            return jsonify({"error": "product not found"}), 404
        n = {k: d.get(k, r[k]) for k in ("name", "category", "unit", "price", "stock")}
        conn.execute("UPDATE products SET name=?,category=?,unit=?,price=?,stock=? WHERE id=?",
                     (*n.values(), pid))
        return jsonify(dict(conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()))
    finally:
        conn.close()


@app.delete("/api/v1/products/<int:pid>")
def delete_product(pid):
    conn = db()
    try:
        cur = conn.execute("DELETE FROM products WHERE id=?", (pid,))
        if cur.rowcount == 0:
            return jsonify({"error": "product not found"}), 404
        return jsonify({"deleted": pid})
    finally:
        conn.close()


# ---------------------------------------------------------------- saga endpoints
@app.post("/api/v1/inventory/reserve")
def reserve():
    """All-or-nothing reservation. Idempotent per order_ref."""
    d = request.get_json(silent=True) or {}
    order_ref, items = d.get("order_ref"), d.get("items")
    if order_ref is None or not isinstance(items, list) or not items:
        return jsonify({"error": "order_ref and a non-empty items list are required"}), 400
    wanted = {}
    for it in items:
        pid, qty = it.get("product_id"), it.get("quantity")
        if not isinstance(pid, int) or not isinstance(qty, int) or qty <= 0:
            return jsonify({"error": "each item needs integer product_id and quantity > 0"}), 400
        wanted[pid] = wanted.get(pid, 0) + qty

    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = rows(conn.execute(
            "SELECT * FROM reservations WHERE order_ref=? AND status IN ('RESERVED','COMMITTED')",
            (order_ref,)))
        if existing:                                   # idempotent retry
            conn.execute("ROLLBACK")
            return jsonify(_reservation_body(order_ref, existing)), 200
        lines = []
        for pid, qty in wanted.items():
            p = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
            if not p:
                conn.execute("ROLLBACK")
                return jsonify({"error": f"product {pid} not found"}), 404
            if p["stock"] < qty:
                conn.execute("ROLLBACK")
                return jsonify({"error": f"insufficient stock for '{p['name']}'",
                                "product_id": pid, "available": p["stock"],
                                "requested": qty}), 409
            lines.append((p, qty))
        for p, qty in lines:
            conn.execute("UPDATE products SET stock = stock - ? WHERE id=?", (qty, p["id"]))
            conn.execute("""INSERT INTO reservations(order_ref,product_id,product_name,quantity,
                            unit_price,status) VALUES (?,?,?,?,?,'RESERVED')""",
                         (order_ref, p["id"], p["name"], qty, p["price"]))
        conn.execute("COMMIT")
        res = rows(conn.execute("SELECT * FROM reservations WHERE order_ref=? AND status='RESERVED'",
                                (order_ref,)))
        return jsonify(_reservation_body(order_ref, res)), 201
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()


def _reservation_body(order_ref, res):
    lines = [{"product_id": r["product_id"], "product_name": r["product_name"],
              "quantity": r["quantity"], "unit_price": r["unit_price"],
              "line_total": round(r["quantity"] * r["unit_price"], 2)} for r in res]
    return {"order_ref": order_ref, "status": res[0]["status"], "lines": lines,
            "total": round(sum(l["line_total"] for l in lines), 2)}


@app.post("/api/v1/inventory/commit")
def commit():
    d = request.get_json(silent=True) or {}
    conn = db()
    try:
        cur = conn.execute("UPDATE reservations SET status='COMMITTED' "
                           "WHERE order_ref=? AND status='RESERVED'", (d.get("order_ref"),))
        if cur.rowcount == 0:
            return jsonify({"error": "no active reservation for this order"}), 404
        return jsonify({"order_ref": d.get("order_ref"), "status": "COMMITTED"})
    finally:
        conn.close()


@app.post("/api/v1/inventory/release")
def release():
    """COMPENSATING ACTION: return reserved/committed stock to the shelf. Idempotent."""
    d = request.get_json(silent=True) or {}
    ref = d.get("order_ref")
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        res = rows(conn.execute("SELECT * FROM reservations WHERE order_ref=? "
                                "AND status IN ('RESERVED','COMMITTED')", (ref,)))
        for r in res:
            conn.execute("UPDATE products SET stock = stock + ? WHERE id=?",
                         (r["quantity"], r["product_id"]))
        conn.execute("UPDATE reservations SET status='RELEASED' WHERE order_ref=? "
                     "AND status IN ('RESERVED','COMMITTED')", (ref,))
        conn.execute("COMMIT")
        return jsonify({"order_ref": ref, "status": "RELEASED", "lines_released": len(res)})
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()


@app.get("/api/v1/inventory/reservations/<int:order_ref>")
def get_reservations(order_ref):
    conn = db()
    try:
        return jsonify(rows(conn.execute("SELECT * FROM reservations WHERE order_ref=?", (order_ref,))))
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    quiet_werkzeug()
    discovery.register_with_registry(NAME, PORT)
    print(f"{NAME} running on port {PORT}", flush=True)
    app.run(host=config.HOST, port=PORT, threaded=True)
