"""SERVICE REGISTRY (Service Discovery server) - port 8500.

Services register themselves (POST /register) and send heartbeats.
An instance whose heartbeat is older than INSTANCE_TTL seconds is treated as dead.
Clients look services up by NAME:   GET /services/<name>/instance
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from flask import jsonify, request  # noqa: E402

from common import config  # noqa: E402
from common.flask_utils import make_app, quiet_werkzeug  # noqa: E402

app = make_app("service-registry")
_registry = {}          # name -> {url: last_seen}
_rr = {}                # round-robin counters
_lock = threading.Lock()


def _alive(name):
    now = time.time()
    return sorted(u for u, seen in _registry.get(name, {}).items()
                  if now - seen <= config.INSTANCE_TTL)


@app.post("/register")
def register():
    d = request.get_json(silent=True) or {}
    if not d.get("name") or not d.get("url"):
        return jsonify({"error": "name and url are required"}), 400
    with _lock:
        _registry.setdefault(d["name"], {})[d["url"]] = time.time()
    return jsonify({"registered": d["name"], "url": d["url"]}), 201


@app.post("/heartbeat")
def heartbeat():
    d = request.get_json(silent=True) or {}
    with _lock:
        if d.get("url") not in _registry.get(d.get("name"), {}):
            return jsonify({"error": "unknown instance, please register"}), 404
        _registry[d["name"]][d["url"]] = time.time()
    return jsonify({"status": "ok"})


@app.post("/deregister")
def deregister():
    d = request.get_json(silent=True) or {}
    with _lock:
        _registry.get(d.get("name"), {}).pop(d.get("url"), None)
    return jsonify({"status": "deregistered"})


@app.get("/services")
def list_services():
    now = time.time()
    with _lock:
        out = {n: [{"url": u, "healthy": now - s <= config.INSTANCE_TTL,
                    "last_heartbeat_s_ago": round(now - s, 1)} for u, s in inst.items()]
               for n, inst in _registry.items()}
    return jsonify(out)


@app.get("/services/<name>")
def get_service(name):
    with _lock:
        urls = _alive(name)
    if not urls:
        return jsonify({"error": f"no healthy instance of '{name}'"}), 404
    return jsonify({"name": name, "instances": urls})


@app.get("/services/<name>/instance")
def get_instance(name):
    with _lock:
        urls = _alive(name)
        if not urls:
            return jsonify({"error": f"no healthy instance of '{name}'"}), 404
        i = _rr.get(name, 0)
        _rr[name] = i + 1
    return jsonify({"name": name, "url": urls[i % len(urls)]})


if __name__ == "__main__":
    quiet_werkzeug()
    print(f"Service Registry running on http://{config.HOST}:{config.REGISTRY_PORT}", flush=True)
    app.run(host=config.HOST, port=config.REGISTRY_PORT, threaded=True)
