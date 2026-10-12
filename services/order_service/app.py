"""ORDER SERVICE + SAGA ORCHESTRATOR (port 5003).
Owns  data/order.db  (tables: orders, order_items, saga_log).

It never reads another service's database. It only calls their REST APIs through
common.service_client (Service Discovery + Circuit Breaker).

API versions
  v1  flat order JSON, plain list                       POST/GET /api/v1/orders ...
  v2  envelope {data, meta}, items + saga trace + links, paging & filtering

SAGA  "Place Order"  (orchestration)
  0  validate customer            (read only, no compensation needed)
  1  RESERVE_STOCK     inventory-service   compensation -> release stock
  2  PROCESS_PAYMENT   payment-service     compensation -> refund payment
  3  ARRANGE_DELIVERY  delivery-service    compensation -> cancel delivery
  4  CONFIRM_ORDER     inventory commit + order status CONFIRMED
  If a step fails, completed steps are compensated in REVERSE order and the
  order ends as CANCELLED.  Notification is best-effort (fallback if down).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from flask import jsonify, request  # noqa: E402

from common import config, discovery  # noqa: E402
from common.flask_utils import make_app, open_db, quiet_werkzeug, rows  # noqa: E402
from common.service_client import ServiceUnavailable, call  # noqa: E402

NAME = "order-service"
PORT = config.SERVICE_PORTS[NAME]
DB_FILE = Path(__file__).resolve().parent / "data" / "order.db"
app = make_app(NAME)


def db():
    return open_db(DB_FILE)


def init_db():
    conn = db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,          -- reference only (no foreign key across services)
            customer_name TEXT,
            delivery_address TEXT,
            pincode TEXT,
            total_amount REAL DEFAULT 0,
            payment_method TEXT,
            payment_id INTEGER,
            delivery_id INTEGER,
            status TEXT NOT NULL,   -- PENDING | CONFIRMED | CANCELLED | CANCELLATION_PENDING
            failure_reason TEXT,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            product_name TEXT, unit_price REAL, quantity INTEGER);
        CREATE TABLE IF NOT EXISTS saga_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            step TEXT NOT NULL,
            status TEXT NOT NULL,   -- STARTED | COMPLETED | FAILED | COMPENSATED | COMPENSATION_FAILED | SKIPPED
            detail TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP);""")
    conn.close()


# ------------------------------------------------------------------- helpers
def log(order_id, step, status, detail=""):
    conn = db()
    conn.execute("INSERT INTO saga_log(order_id,step,status,detail) VALUES (?,?,?,?)",
                 (order_id, step, status, str(detail)[:300]))
    conn.close()
    print(f"[saga] order={order_id} {step:<17} {status:<20} {str(detail)[:90]}", flush=True)


def set_order(order_id, **fields):
    fields["updated_at"] = "CURRENT_TIMESTAMP"
    sets = ", ".join(f"{k}=CURRENT_TIMESTAMP" if v == "CURRENT_TIMESTAMP" else f"{k}=?"
                     for k, v in fields.items())
    vals = [v for v in fields.values() if v != "CURRENT_TIMESTAMP"]
    conn = db()
    conn.execute(f"UPDATE orders SET {sets} WHERE id=?", (*vals, order_id))
    conn.close()


class SagaFailure(Exception):
    def __init__(self, step, reason, http_status):
        super().__init__(reason)
        self.step, self.reason, self.http_status = step, reason, http_status


def remote(order_id, step, service, method, path, ok_codes=(200, 201), **kw):
    """Call a service for a saga step; translate every problem into SagaFailure."""
    try:
        code, body = call(service, method, path, **kw)
    except ServiceUnavailable as exc:
        raise SagaFailure(step, f"{service} unavailable ({exc.reason})", 503)
    if code not in ok_codes:
        raise SagaFailure(step, f"{service}: {body.get('error', body)}", code)
    return body


def notify(order_id, customer_id, message):
    """Best-effort notification. Circuit breaker + fallback: never fails the order."""
    try:
        call("notification-service", "POST", "/api/v1/notifications",
             json={"order_id": order_id, "customer_id": customer_id, "message": message})
        log(order_id, "NOTIFY_CUSTOMER", "COMPLETED", message)
    except ServiceUnavailable as exc:
        log(order_id, "NOTIFY_CUSTOMER", "SKIPPED",
            f"fallback: notification-service down ({exc.circuit_state}); order not affected")


def run_compensations(order_id, undo_steps):
    """undo_steps: list of (step_name, function) in the order they were completed."""
    all_ok = True
    for step, fn in reversed(undo_steps):
        try:
            fn()
            log(order_id, step, "COMPENSATED", "undo successful")
        except (SagaFailure, ServiceUnavailable) as exc:
            all_ok = False
            log(order_id, step, "COMPENSATION_FAILED", getattr(exc, "reason", exc))
    return all_ok


def comp_release(order_id):
    return lambda: remote(order_id, "RESERVE_STOCK", "inventory-service", "POST",
                          "/api/v1/inventory/release", json={"order_ref": order_id})


def comp_refund(order_id, payment_id):
    return lambda: remote(order_id, "PROCESS_PAYMENT", "payment-service", "POST",
                          f"/api/v1/payments/{payment_id}/refund")


def comp_cancel_delivery(order_id, delivery_id):
    return lambda: remote(order_id, "ARRANGE_DELIVERY", "delivery-service", "POST",
                          f"/api/v1/deliveries/{delivery_id}/cancel")


# ------------------------------------------------------------------- the SAGA
def place_order(customer_id, items, method, token, address_override, pincode_override):
    # --- step 0: validate customer (read only)
    try:
        code, cust = call("customer-service", "GET", f"/api/v1/customers/{customer_id}")
    except ServiceUnavailable as exc:
        return None, SagaFailure("VALIDATE_CUSTOMER", f"customer-service unavailable ({exc.reason})", 503)
    if code != 200:
        return None, SagaFailure("VALIDATE_CUSTOMER", cust.get("error", "customer not found"), code)

    address = address_override or cust["address"]
    pincode = pincode_override or cust["pincode"]
    conn = db()
    cur = conn.execute("""INSERT INTO orders(customer_id,customer_name,delivery_address,pincode,
                          payment_method,status) VALUES (?,?,?,?,?,'PENDING')""",
                       (customer_id, cust["name"], address, pincode, method))
    order_id = cur.lastrowid
    conn.close()
    log(order_id, "CREATE_ORDER", "COMPLETED", f"order {order_id} created as PENDING")

    undo = []
    try:
        # --- step 1: reserve stock
        log(order_id, "RESERVE_STOCK", "STARTED", "inventory-service")
        res = remote(order_id, "RESERVE_STOCK", "inventory-service", "POST",
                     "/api/v1/inventory/reserve", json={"order_ref": order_id, "items": items})
        undo.append(("RESERVE_STOCK", comp_release(order_id)))
        total = res["total"]
        conn = db()
        for l in res["lines"]:
            conn.execute("INSERT INTO order_items(order_id,product_id,product_name,unit_price,quantity)"
                         " VALUES (?,?,?,?,?)", (order_id, l["product_id"], l["product_name"],
                                                 l["unit_price"], l["quantity"]))
        conn.close()
        set_order(order_id, total_amount=total)
        log(order_id, "RESERVE_STOCK", "COMPLETED", f"{len(res['lines'])} line(s), total {total}")

        # --- step 2: payment
        log(order_id, "PROCESS_PAYMENT", "STARTED", f"payment-service amount={total}")
        pay = remote(order_id, "PROCESS_PAYMENT", "payment-service", "POST", "/api/v1/payments",
                     json={"order_id": order_id, "amount": total, "method": method, "token": token})
        undo.append(("PROCESS_PAYMENT", comp_refund(order_id, pay["id"])))
        set_order(order_id, payment_id=pay["id"])
        log(order_id, "PROCESS_PAYMENT", "COMPLETED", f"payment {pay['id']} SUCCESS")

        # --- step 3: delivery
        log(order_id, "ARRANGE_DELIVERY", "STARTED", "delivery-service")
        dlv = remote(order_id, "ARRANGE_DELIVERY", "delivery-service", "POST", "/api/v1/deliveries",
                     json={"order_id": order_id, "address": address, "pincode": pincode})
        undo.append(("ARRANGE_DELIVERY", comp_cancel_delivery(order_id, dlv["id"])))
        set_order(order_id, delivery_id=dlv["id"])
        log(order_id, "ARRANGE_DELIVERY", "COMPLETED", f"delivery {dlv['id']} agent {dlv['agent_id']}")

        # --- step 4: confirm
        remote(order_id, "CONFIRM_ORDER", "inventory-service", "POST",
               "/api/v1/inventory/commit", json={"order_ref": order_id})
        set_order(order_id, status="CONFIRMED")
        log(order_id, "CONFIRM_ORDER", "COMPLETED", "order CONFIRMED")
        notify(order_id, customer_id, f"Order #{order_id} confirmed. Total {total}.")
        return order_id, None

    except SagaFailure as fail:
        log(order_id, fail.step, "FAILED", fail.reason)
        ok = run_compensations(order_id, undo)
        set_order(order_id, status="CANCELLED" if ok else "CANCELLATION_PENDING",
                  failure_reason=f"{fail.step}: {fail.reason}")
        notify(order_id, customer_id, f"Order #{order_id} could not be completed: {fail.reason}")
        return order_id, fail


# ------------------------------------------------------------------ serializers
def get_order_row(oid):
    conn = db()
    try:
        r = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def items_of(oid):
    conn = db()
    try:
        return rows(conn.execute("SELECT product_id,product_name,unit_price,quantity "
                                 "FROM order_items WHERE order_id=?", (oid,)))
    finally:
        conn.close()


def steps_of(oid):
    conn = db()
    try:
        return rows(conn.execute("SELECT step,status,detail,created_at FROM saga_log "
                                 "WHERE order_id=? ORDER BY id", (oid,)))
    finally:
        conn.close()


def v1(o):
    return o


def v2(o):
    oid = o["id"]
    return {"order_id": oid, "status": o["status"], "failure_reason": o["failure_reason"],
            "customer": {"id": o["customer_id"], "name": o["customer_name"]},
            "delivery": {"address": o["delivery_address"], "pincode": o["pincode"],
                         "delivery_id": o["delivery_id"]},
            "payment": {"payment_id": o["payment_id"], "method": o["payment_method"],
                        "amount": o["total_amount"]},
            "items": items_of(oid), "saga_steps": steps_of(oid),
            "notes": o["notes"], "created_at": o["created_at"], "updated_at": o["updated_at"],
            "links": {"self": f"/api/v2/orders/{oid}", "cancel": f"DELETE /api/v2/orders/{oid}"}}


# -------------------------------------------------------------------- endpoints
def _create(version):
    d = request.get_json(silent=True) or {}
    items = d.get("items")
    if not isinstance(d.get("customer_id"), int) or not isinstance(items, list) or not items:
        return jsonify({"error": "customer_id (int) and a non-empty items list are required"}), 400
    order_id, fail = place_order(d["customer_id"], items, d.get("payment_method", "CARD"),
                                 d.get("payment_token", "tok_visa"),
                                 d.get("delivery_address"), d.get("pincode"))
    if order_id is None:                       # failed before an order existed
        # 503 from a DEPENDENCY is reported as 424 Failed Dependency, so the gateway does not
        # mistake a business/saga failure for "order-service itself is down".
        return jsonify({"error": fail.reason, "failed_step": fail.step}), \
            (424 if fail.http_status == 503 else fail.http_status)
    o = get_order_row(order_id)
    if version == "v1":
        body, code = v1(o), 201
        if fail:
            body = {**o, "failed_step": fail.step}
    else:
        body = {"data": v2(o), "meta": {"api_version": "v2", "saga_succeeded": fail is None}}
        code = 201
    if fail:
        code = 424 if fail.http_status == 503 else (fail.http_status if fail.http_status in (402, 404, 409) else 409)
    return jsonify(body), code


@app.post("/api/v1/orders")
def create_v1():
    return _create("v1")


@app.post("/api/v2/orders")
def create_v2():
    return _create("v2")


@app.get("/api/v1/orders")
def list_v1():
    sql, args = "SELECT * FROM orders WHERE 1=1", []
    if request.args.get("customer_id"):
        sql += " AND customer_id=?"
        args.append(request.args["customer_id"])
    conn = db()
    try:
        return jsonify(rows(conn.execute(sql + " ORDER BY id", args)))
    finally:
        conn.close()


@app.get("/api/v2/orders")
def list_v2():
    try:
        page = max(int(request.args.get("page", 1)), 1)
        per = min(max(int(request.args.get("per_page", 10)), 1), 100)
    except ValueError:
        return jsonify({"error": "page and per_page must be integers"}), 400
    where, args = "WHERE 1=1", []
    for f in ("status", "customer_id"):
        if request.args.get(f):
            where += f" AND {f}=?"
            args.append(request.args[f])
    conn = db()
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM orders {where}", args).fetchone()[0]
        data = rows(conn.execute(f"SELECT * FROM orders {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                                 (*args, per, (page - 1) * per)))
    finally:
        conn.close()
    return jsonify({"data": [v2(o) for o in data],
                    "meta": {"api_version": "v2", "page": page, "per_page": per, "total": total}})


@app.get("/api/v1/orders/<int:oid>")
def get_v1(oid):
    o = get_order_row(oid)
    return (jsonify(v1(o)), 200) if o else (jsonify({"error": "order not found"}), 404)


@app.get("/api/v2/orders/<int:oid>")
def get_v2(oid):
    o = get_order_row(oid)
    if not o:
        return jsonify({"error": "order not found"}), 404
    return jsonify({"data": v2(o), "meta": {"api_version": "v2"}})


def _update(oid, version):
    o = get_order_row(oid)
    if not o:
        return jsonify({"error": "order not found"}), 404
    if o["status"] not in ("PENDING", "CONFIRMED"):
        return jsonify({"error": f"order is {o['status']} and cannot be modified"}), 409
    notes = (request.get_json(silent=True) or {}).get("notes")
    if notes is None:
        return jsonify({"error": "only 'notes' can be updated"}), 400
    set_order(oid, notes=notes)
    o = get_order_row(oid)
    return jsonify(v1(o) if version == "v1" else {"data": v2(o), "meta": {"api_version": "v2"}})


@app.put("/api/v1/orders/<int:oid>")
def update_v1(oid):
    return _update(oid, "v1")


@app.put("/api/v2/orders/<int:oid>")
def update_v2(oid):
    return _update(oid, "v2")


def _cancel(oid, version):
    """Customer cancels a CONFIRMED order -> same compensating actions as the saga."""
    o = get_order_row(oid)
    if not o:
        return jsonify({"error": "order not found"}), 404
    if o["status"] != "CONFIRMED":
        return jsonify({"error": f"only CONFIRMED orders can be cancelled (current: {o['status']})"}), 409
    log(oid, "CANCEL_ORDER", "STARTED", "customer requested cancellation")
    undo = [("RESERVE_STOCK", comp_release(oid)),
            ("PROCESS_PAYMENT", comp_refund(oid, o["payment_id"])),
            ("ARRANGE_DELIVERY", comp_cancel_delivery(oid, o["delivery_id"]))]
    ok = run_compensations(oid, undo)
    set_order(oid, status="CANCELLED" if ok else "CANCELLATION_PENDING",
              failure_reason="cancelled by customer" if ok else "cancellation incomplete - retry")
    notify(oid, o["customer_id"], f"Order #{oid} cancelled.")
    o = get_order_row(oid)
    body = v1(o) if version == "v1" else {"data": v2(o), "meta": {"api_version": "v2"}}
    return jsonify(body), 200 if ok else 424


@app.delete("/api/v1/orders/<int:oid>")
def cancel_v1(oid):
    return _cancel(oid, "v1")


@app.delete("/api/v2/orders/<int:oid>")
def cancel_v2(oid):
    return _cancel(oid, "v2")


@app.get("/api/v1/orders/<int:oid>/saga")
def saga_trace(oid):
    if not get_order_row(oid):
        return jsonify({"error": "order not found"}), 404
    return jsonify(steps_of(oid))


if __name__ == "__main__":
    init_db()
    quiet_werkzeug()
    discovery.register_with_registry(NAME, PORT)
    print(f"{NAME} running on port {PORT}", flush=True)
    app.run(host=config.HOST, port=PORT, threaded=True)
