"""Start the whole system with ONE command:   python start_all.py
Press Ctrl+C to stop every service.

Order: registry -> backend services -> gateway.
(You can also start each service by hand in its own terminal - see README.)
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
PID_DIR = ROOT / ".pids"

SERVICES = {   # name -> script
    "registry":             "services/registry/app.py",
    "customer-service":     "services/customer_service/app.py",
    "inventory-service":    "services/inventory_service/app.py",
    "order-service":        "services/order_service/app.py",
    "payment-service":      "services/payment_service/app.py",
    "delivery-service":     "services/delivery_service/app.py",
    "notification-service": "services/notification_service/app.py",
    "gateway":              "services/gateway/app.py",
}
procs = {}


def launch(name, quiet=False):
    """Start one service as a separate OS process (also used by the circuit-breaker demo)."""
    PID_DIR.mkdir(exist_ok=True)
    log = open(PID_DIR / f"{name}.log", "a", buffering=1)
    p = subprocess.Popen([sys.executable, "-u", str(ROOT / SERVICES[name])], cwd=ROOT,
                         stdout=log, stderr=subprocess.STDOUT)
    procs[name] = p
    (PID_DIR / f"{name}.pid").write_text(json.dumps({"pid": p.pid}))
    if not quiet:
        print(f"  started {name:<22} pid={p.pid}")
    return p


def stop(name):
    p = procs.get(name)
    if p and p.poll() is None:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()


def wait_until_ready(timeout=30):
    expected = [n for n in SERVICES if n not in ("registry", "gateway")]
    end = time.time() + timeout
    while time.time() < end:
        try:
            reg = requests.get("http://127.0.0.1:8500/services", timeout=1).json()
            if all(n in reg for n in expected) and requests.get("http://127.0.0.1:8000/", timeout=1).ok:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.5)
    return False


def main():
    print("Starting Online Grocery Delivery microservices...")
    for name in SERVICES:
        launch(name)
        if name == "registry":
            time.sleep(1.5)
    if wait_until_ready():
        print("\nAll services are UP.  API Gateway:  http://127.0.0.1:8000")
        print("Registry view:  http://127.0.0.1:8500/services")
        print("Press Ctrl+C to stop everything.\n")
    else:
        print("Some services did not come up - check .pids/*.log")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        for n in list(procs):
            stop(n)


if __name__ == "__main__":
    main()
