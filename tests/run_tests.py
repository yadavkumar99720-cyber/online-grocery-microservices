"""Automated API tests.  Start the system first (python start_all.py), then:

        python tests/run_tests.py

Every request goes through the API GATEWAY (http://127.0.0.1:8000), exactly like a client.
Results are printed and saved to docs/TEST_RESULTS.md (attach it to your report).
"""
import re
import sqlite3
import sys
import time
import uuid
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
GW = "http://127.0.0.1:8000"
REG = "http://127.0.0.1:8500"
results = []


def check(group, name, condition, detail=""):
    results.append((group, name, bool(condition), detail))
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


def api(method, path, **kw):
    r = requests.request(method, GW + path, timeout=15, **kw)
    try:
        return r.status_code, r.json(), r
    except ValueError:
        return r.status_code, {}, r


def stock(pid):
    return api("GET", f"/api/v1/products/{pid}")[1]["stock"]


def section(title):
    print(f"\n=== {title} ===")


def order_body(cid, items, **extra):
    return {"customer_id": cid, "items": items, **extra}


def main():
    try:
        requests.get(GW + "/", timeout=3)
    except requests.RequestException:
        sys.exit("Gateway not reachable. Run  python start_all.py  first.")

    # ------------------------------------------------------------------
    section("1. Service Discovery")
    reg = requests.get(REG + "/services").json()
    names = {"customer-service", "inventory-service", "order-service",
             "payment-service", "delivery-service", "notification-service"}
    check("Service Discovery", "all 6 services registered in registry", names <= set(reg), sorted(reg))
    check("Service Discovery", "every registered instance is healthy",
          all(i["healthy"] for n in names for i in reg[n]))
    code, body, _ = api("GET", "/api/status")
    check("Service Discovery", "gateway /api/status exposes registry + breaker states",
          code == 200 and "registry" in body)

    # ------------------------------------------------------------------
    section("2. API Gateway & routing")
    code, body, r = api("GET", "/api/v1/products")
    check("API Gateway", "GET /api/v1/products via gateway -> 200", code == 200 and len(body) >= 10)
    check("API Gateway", "gateway adds X-Routed-To header", r.headers.get("X-Routed-To") == "inventory-service")
    check("API Gateway", "unknown resource -> 404", api("GET", "/api/v1/foo")[0] == 404)
    code, body, _ = api("GET", "/api/v2/customers")
    check("API Gateway", "unsupported version (customers v2) -> 404 with supported_versions",
          code == 404 and body.get("supported_versions") == ["v1"])

    # ------------------------------------------------------------------
    section("3. REST - Customers (GET/POST/PUT/DELETE)")
    email = f"test-{uuid.uuid4().hex[:6]}@example.com"
    code, cust, _ = api("POST", "/api/v1/customers", json={
        "name": "Test User", "email": email, "address": "1 Test Lane", "pincode": "500081"})
    check("REST", "POST customer -> 201", code == 201 and cust.get("id"))
    cid = cust["id"]
    check("REST", "POST duplicate email -> 409",
          api("POST", "/api/v1/customers", json={"name": "x", "email": email, "address": "a", "pincode": "1"})[0] == 409)
    check("REST", "POST missing fields -> 400", api("POST", "/api/v1/customers", json={"name": "x"})[0] == 400)
    check("REST", "GET customer -> 200", api("GET", f"/api/v1/customers/{cid}")[0] == 200)
    code, upd, _ = api("PUT", f"/api/v1/customers/{cid}", json={"name": "Renamed User"})
    check("REST", "PUT customer updates name", code == 200 and upd["name"] == "Renamed User")
    check("REST", "GET unknown customer -> 404", api("GET", "/api/v1/customers/99999")[0] == 404)

    section("4. REST - Products (GET/POST/PUT/DELETE)")
    code, prod, _ = api("POST", "/api/v1/products", json={"name": "Test Jam", "category": "Spreads",
                                                           "price": 99.5, "stock": 5})
    check("REST", "POST product -> 201", code == 201)
    pid = prod["id"]
    check("REST", "POST invalid price -> 400",
          api("POST", "/api/v1/products", json={"name": "x", "category": "y", "price": -1, "stock": 1})[0] == 400)
    code, upd, _ = api("PUT", f"/api/v1/products/{pid}", json={"stock": 8})
    check("REST", "PUT product updates stock", code == 200 and upd["stock"] == 8)
    check("REST", "GET products?category= filter works",
          all(p["category"] == "Dairy" for p in api("GET", "/api/v1/products?category=Dairy")[1]))
    check("REST", "DELETE product -> 200", api("DELETE", f"/api/v1/products/{pid}")[0] == 200)
    check("REST", "deleted product -> 404", api("GET", f"/api/v1/products/{pid}")[0] == 404)

    # ------------------------------------------------------------------
    section("5. SAGA - success path (3+ services)")
    s_rice, s_milk = stock(1), stock(4)
    code, o, _ = api("POST", "/api/v1/orders", json=order_body(
        cid, [{"product_id": 1, "quantity": 2}, {"product_id": 4, "quantity": 1}]))
    check("Saga success", "POST /api/v1/orders -> 201 CONFIRMED", code == 201 and o["status"] == "CONFIRMED", o.get("status"))
    check("Saga success", "total = 2*95 + 62 = 252", o["total_amount"] == 252.0, o["total_amount"])
    check("Saga success", "inventory-service stock reduced", stock(1) == s_rice - 2 and stock(4) == s_milk - 1)
    pay = api("GET", f"/api/v1/payments/{o['payment_id']}")[1]
    check("Saga success", "payment-service has SUCCESS payment", pay["status"] == "SUCCESS" and pay["order_id"] == o["id"])
    dlv = api("GET", f"/api/v1/deliveries/{o['delivery_id']}")[1]
    check("Saga success", "delivery-service has ASSIGNED delivery with agent", dlv["status"] == "ASSIGNED" and dlv["agent_id"])
    steps = [s["step"] for s in api("GET", f"/api/v1/orders/{o['id']}/saga")[1] if s["status"] == "COMPLETED"]
    check("Saga success", "saga steps in order", steps[:5] == ["CREATE_ORDER", "RESERVE_STOCK", "PROCESS_PAYMENT",
                                                              "ARRANGE_DELIVERY", "CONFIRM_ORDER"], steps)
    good_order = o["id"]
    time.sleep(0.5)
    notes = api("GET", "/api/v1/notifications")[1]
    check("Saga success", "notification-service recorded a message", any(n["order_id"] == good_order for n in notes))

    # ------------------------------------------------------------------
    section("6. SAGA - failure: payment declined (compensation)")
    s_rice = stock(1)
    code, o, _ = api("POST", "/api/v1/orders", json=order_body(
        cid, [{"product_id": 1, "quantity": 3}], payment_token="tok_decline"))
    check("Saga fail-payment", "returns 402 and order CANCELLED", code == 402 and o["status"] == "CANCELLED", f"{code} {o.get('status')}")
    check("Saga fail-payment", "stock reservation RELEASED (compensated)", stock(1) == s_rice, f"{s_rice} -> {stock(1)}")
    check("Saga fail-payment", "no delivery was created", api("GET", f"/api/v1/deliveries?order_id={o['id']}")[1] == [])
    sg = {(s["step"], s["status"]) for s in api("GET", f"/api/v1/orders/{o['id']}/saga")[1]}
    check("Saga fail-payment", "saga log: PROCESS_PAYMENT FAILED + RESERVE_STOCK COMPENSATED",
          ("PROCESS_PAYMENT", "FAILED") in sg and ("RESERVE_STOCK", "COMPENSATED") in sg)

    section("7. SAGA - failure: unserviceable pincode AFTER payment (3-service compensation)")
    s_rice = stock(1)
    code, o, _ = api("POST", "/api/v1/orders", json=order_body(
        cid, [{"product_id": 1, "quantity": 4}], pincode="999111"))
    check("Saga fail-delivery", "returns 409 and order CANCELLED", code == 409 and o["status"] == "CANCELLED", f"{code} {o.get('status')}")
    pays = api("GET", f"/api/v1/payments?order_id={o['id']}")[1]
    check("Saga fail-delivery", "payment was REFUNDED (compensated)", len(pays) == 1 and pays[0]["status"] == "REFUNDED", [p["status"] for p in pays])
    check("Saga fail-delivery", "stock released (compensated)", stock(1) == s_rice)
    log_ = api("GET", f"/api/v1/orders/{o['id']}/saga")[1]
    comp = [s["step"] for s in log_ if s["status"] == "COMPENSATED"]
    check("Saga fail-delivery", "compensation runs in REVERSE order", comp == ["PROCESS_PAYMENT", "RESERVE_STOCK"], comp)

    section("8. SAGA - failure: insufficient stock")
    code, o, _ = api("POST", "/api/v1/orders", json=order_body(cid, [{"product_id": 10, "quantity": 50}]))
    check("Saga fail-stock", "returns 409 and order CANCELLED", code == 409 and o["status"] == "CANCELLED")
    check("Saga fail-stock", "no payment was attempted", api("GET", f"/api/v1/payments?order_id={o['id']}")[1] == [])
    code, o, _ = api("POST", "/api/v1/orders", json=order_body(99999, [{"product_id": 1, "quantity": 1}]))
    check("Saga fail-stock", "unknown customer -> 404, no order created", code == 404)
    check("REST", "POST order with empty items -> 400", api("POST", "/api/v1/orders", json={"customer_id": cid, "items": []})[0] == 400)

    # ------------------------------------------------------------------
    section("9. API versioning (v1 vs v2)")
    code1, v1, _ = api("GET", f"/api/v1/orders/{good_order}")
    code2, v2, _ = api("GET", f"/api/v2/orders/{good_order}")
    check("Versioning", "v1 returns a flat order object", code1 == 200 and v1.get("status") == "CONFIRMED" and "data" not in v1)
    check("Versioning", "v2 returns {data, meta} with items + saga_steps",
          code2 == 200 and v2["meta"]["api_version"] == "v2" and v2["data"]["items"] and v2["data"]["saga_steps"])
    check("Versioning", "v2 nests customer/payment/delivery",
          v2["data"]["customer"]["id"] == cid and v2["data"]["payment"]["amount"] == 252.0)
    code, lst, _ = api("GET", "/api/v2/orders?page=1&per_page=2&status=CONFIRMED")
    check("Versioning", "v2 list supports paging + filter", code == 200 and lst["meta"]["per_page"] == 2
          and len(lst["data"]) <= 2 and all(x["status"] == "CONFIRMED" for x in lst["data"]))
    code, lst1, _ = api("GET", "/api/v1/orders")
    check("Versioning", "v1 list is a plain array", code == 200 and isinstance(lst1, list))
    code, o2, _ = api("POST", "/api/v2/orders", json=order_body(cid, [{"product_id": 6, "quantity": 1}]))
    check("Versioning", "POST /api/v2/orders -> 201 with saga_succeeded meta", code == 201 and o2["meta"]["saga_succeeded"] is True)
    v2_order = o2["data"]["order_id"]

    # ------------------------------------------------------------------
    section("10. REST - update (PUT) and cancel (DELETE) an order")
    code, u, _ = api("PUT", f"/api/v1/orders/{good_order}", json={"notes": "Leave at the door"})
    check("REST", "PUT order notes -> 200", code == 200 and u["notes"] == "Leave at the door")
    s_rice = stock(1)
    code, c, _ = api("DELETE", f"/api/v1/orders/{good_order}")
    check("REST", "DELETE (cancel) confirmed order -> CANCELLED", code == 200 and c["status"] == "CANCELLED")
    check("REST", "cancel refunded payment", api("GET", f"/api/v1/payments/{c['payment_id']}")[1]["status"] == "REFUNDED")
    check("REST", "cancel cancelled delivery", api("GET", f"/api/v1/deliveries/{c['delivery_id']}")[1]["status"] == "CANCELLED")
    check("REST", "cancel restocked items", stock(1) == s_rice + 2)
    check("REST", "cancelling again -> 409", api("DELETE", f"/api/v1/orders/{good_order}")[0] == 409)
    api("DELETE", f"/api/v2/orders/{v2_order}")
    api("DELETE", f"/api/v1/customers/{cid}")

    # ------------------------------------------------------------------
    section("11. Database per service & data isolation")
    dbs = {p.parent.parent.name: p for p in ROOT.glob("services/*/data/*.db")}
    check("Data isolation", "6 separate database files exist (one per service)", len(dbs) == 6, sorted(dbs))
    tables = {}
    for svc, p in dbs.items():
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        tables[svc] = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        con.close()
    check("Data isolation", "order DB has no products/customers/payments tables",
          not (tables["order_service"] & {"products", "customers", "payments", "deliveries"}), sorted(tables["order_service"]))
    all_tables = [t for ts in tables.values() for t in ts]
    check("Data isolation", "no table name is duplicated across service DBs", len(all_tables) == len(set(all_tables)))
    bad = []
    for py in ROOT.glob("services/*/app.py"):
        svc, txt = py.parent.name, py.read_text()
        for other in dbs:
            if other != svc and re.search(rf"{other}[\\/]data|\b{dbs[other].name}\b", txt):
                bad.append((svc, other))
    check("Data isolation", "static scan: no service code opens another service's .db file", not bad, bad)

    # ------------------------------------------------------------------
    passed = sum(1 for r in results if r[2])
    print(f"\nRESULT: {passed}/{len(results)} checks passed")
    out = ROOT / "docs" / "TEST_RESULTS.md"
    with open(out, "w") as f:
        f.write("# API Test Results (automated)\n\n")
        f.write(f"Run date: {time.strftime('%Y-%m-%d %H:%M:%S')}  \nCommand: `python tests/run_tests.py`  \n")
        f.write(f"**Result: {passed}/{len(results)} checks passed**\n\n")
        f.write("| # | Area | Test | Result | Evidence |\n|---|------|------|--------|----------|\n")
        for i, (g, n, ok, d) in enumerate(results, 1):
            f.write(f"| {i} | {g} | {n} | {'PASS' if ok else 'FAIL'} | {str(d).replace('|', '/')} |\n")
    print(f"Saved {out}")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
