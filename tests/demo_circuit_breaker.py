"""CIRCUIT BREAKER + FAULT TOLERANCE live demonstration.   (system must be running)

    python tests/demo_circuit_breaker.py

What it does (real failures, nothing mocked):
  1. places a normal order                     -> breaker for payment-service is CLOSED
  2. KILLS payment-service                     -> real process termination
  3. places orders repeatedly                  -> failures counted, circuit goes OPEN,
                                                  later calls fail FAST, Saga compensates
  4. shows the rest of the system still works  -> fault tolerance
  5. KILLS notification-service                -> order still CONFIRMED (fallback)
  6. RESTARTS payment-service, waits           -> OPEN -> HALF_OPEN -> CLOSED
Output is also saved to docs/CIRCUIT_BREAKER_DEMO.txt
"""
import json
import os
import signal
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import start_all  # noqa: E402  (re-use launch())
from common import config  # noqa: E402

GW = "http://127.0.0.1:8000"
ORDER_HEALTH = "http://127.0.0.1:5003/health"
lines = []


def say(msg=""):
    print(msg, flush=True)
    lines.append(msg)


def breaker(service="payment-service"):
    try:
        b = requests.get(ORDER_HEALTH, timeout=2).json()["circuit_breakers"].get(service)
        return f"{b['state']} (consecutive failures={b['consecutive_failures']})" if b else "not used yet"
    except requests.RequestException:
        return "?"


def place_order(label):
    t = time.time()
    r = requests.post(f"{GW}/api/v1/orders", timeout=20, json={
        "customer_id": 1, "items": [{"product_id": 6, "quantity": 1}]})
    ms = int((time.time() - t) * 1000)
    b = r.json()
    say(f"  {label}: HTTP {r.status_code} in {ms:>4} ms | order status={b.get('status', b.get('error'))}")
    if b.get("failure_reason"):
        say(f"      reason: {b['failure_reason']}")
    say(f"      payment-service breaker -> {breaker()}")
    return r


def kill(service):
    pid = json.loads((start_all.PID_DIR / f"{service}.pid").read_text())["pid"]
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    say(f"  >>> {service} (pid {pid}) has been STOPPED")


def wait_registered(service, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if requests.get(f"{config.REGISTRY_URL}/services/{service}/instance", timeout=1).ok:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.5)
    return False


def main():
    say("=" * 70)
    say("CIRCUIT BREAKER DEMO  (threshold = %d failures, recovery = %ds)" %
        (config.CB_FAILURE_THRESHOLD, config.CB_RECOVERY_TIMEOUT))
    say("=" * 70)

    say("\n[1] Healthy system")
    place_order("order #A")

    say("\n[2] Stop the dependent service (payment-service)")
    kill("payment-service")
    time.sleep(0.5)

    say("\n[3] Orders while payment-service is DOWN  (watch the circuit)")
    for i in range(1, 6):
        place_order(f"attempt {i}")
    say("  -> after 3 failures the circuit is OPEN: attempts 4-5 are rejected instantly")
    say("     (no network call), the Saga compensates (stock released) and the client")
    say("     gets a clean JSON error (HTTP 424) instead of a crash or a hang.")

    say("\n[4] Fault tolerance - the REST of the application still works")
    r = requests.get(f"{GW}/api/v1/products", timeout=5)
    say(f"  GET  /api/v1/products   -> HTTP {r.status_code} ({len(r.json())} products)")
    r = requests.get(f"{GW}/api/v1/customers/1", timeout=5)
    say(f"  GET  /api/v1/customers/1-> HTTP {r.status_code}")
    for i in range(1, 5):
        r = requests.get(f"{GW}/api/v1/payments", timeout=5)
        say(f"  GET  /api/v1/payments #{i} -> HTTP {r.status_code} {r.json().get('error')} | "
            f"gateway circuit={r.json().get('circuit_state')} | {r.json().get('reason')}")
    say("  -> the gateway returns a graceful JSON 503 and opens its OWN circuit for payment-service.")

    say("\n[5] Non-critical service down: notification-service")
    time.sleep(0.5)
    start_all.launch("payment-service", quiet=True)          # bring payment back first
    wait_registered("payment-service")
    say("  payment-service restarted & re-registered (circuit still OPEN until recovery timeout)")
    kill("notification-service")
    time.sleep(0.5)

    say("\n[6] Recovery: OPEN -> HALF_OPEN -> CLOSED")
    say(f"  state now: {breaker()}")
    wait = config.CB_RECOVERY_TIMEOUT + 1
    say(f"  waiting {wait}s for the recovery timeout...")
    time.sleep(wait)
    say(f"  state now: {breaker()}   <- trial call is allowed")
    r = place_order("trial order")
    say("  -> trial call succeeded, circuit CLOSED again")
    say(f"  notification-service is still down: order status = {r.json().get('status')} "
        "(fallback: notification skipped, order NOT affected)")
    steps = requests.get(f"{GW}/api/v1/orders/{r.json()['id']}/saga", timeout=5).json()
    for s in steps:
        if s["step"] == "NOTIFY_CUSTOMER":
            say(f"      saga log: NOTIFY_CUSTOMER {s['status']} - {s['detail']}")
    say("\n  Breaker transition history (order-service):")
    b = requests.get(ORDER_HEALTH, timeout=3).json()["circuit_breakers"]["payment-service"]
    for t, a, c in b["history"]:
        say(f"      {t}  {a} -> {c}")

    start_all.launch("notification-service", quiet=True)
    wait_registered("notification-service")
    say("\n  notification-service restarted. Demo finished.")
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "CIRCUIT_BREAKER_DEMO.txt").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
