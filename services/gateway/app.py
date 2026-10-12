"""API GATEWAY - the single entry point for clients (port 8000).

  Client -> http://127.0.0.1:8000/api/<version>/<resource>/...  -> backend service

* Routing by resource name using Service Discovery (no hard-coded backend URLs).
* API versioning: only the versions listed in ROUTES are accepted
  (orders: v1 + v2, everything else: v1).
* Circuit breaker + graceful errors: if a backend is down the client gets a clean
  503 JSON message instead of a crash.
* Fallback: GET /products responses are cached; if inventory-service is down the
  last good response is returned with header  X-Fallback: stale-cache.
"""
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import requests  # noqa: E402
from flask import jsonify, request  # noqa: E402

from common import config, service_client  # noqa: E402
from common.flask_utils import make_app, quiet_werkzeug  # noqa: E402
from common.service_client import ServiceUnavailable  # noqa: E402

app = make_app("api-gateway")

# resource -> (backend service name, supported API versions)
ROUTES = {
    "customers":     ("customer-service",     ["v1"]),
    "products":      ("inventory-service",    ["v1"]),
    "inventory":     ("inventory-service",    ["v1"]),
    "orders":        ("order-service",        ["v1", "v2"]),
    "payments":      ("payment-service",      ["v1"]),
    "deliveries":    ("delivery-service",     ["v1"]),
    "notifications": ("notification-service", ["v1"]),
}
_cache = {}   # path+query -> (status, body)  : fallback for GET /products


@app.get("/")
def index():
    return jsonify({
        "service": "Online Grocery Delivery - API Gateway",
        "usage": "/api/<version>/<resource>",
        "routes": {k: {"service": v[0], "versions": v[1]} for k, v in ROUTES.items()},
        "status": "/api/status"})


@app.get("/api/status")
def status():
    """Platform status: what the registry knows + circuit breaker states seen by the gateway."""
    try:
        reg = requests.get(f"{config.REGISTRY_URL}/services", timeout=2).json()
    except requests.RequestException:
        reg = {"error": "registry unreachable"}
    return jsonify({"registry": reg, "gateway_circuit_breakers": service_client.all_breaker_states()})


@app.route("/api/<version>/<resource>", defaults={"rest": ""},
           methods=["GET", "POST", "PUT", "DELETE"])
@app.route("/api/<version>/<resource>/<path:rest>", methods=["GET", "POST", "PUT", "DELETE"])
def proxy(version, resource, rest):
    if resource not in ROUTES:
        return jsonify({"error": f"unknown resource '{resource}'",
                        "available": sorted(ROUTES)}), 404
    service, versions = ROUTES[resource]
    if version not in versions:
        return jsonify({"error": f"API version '{version}' is not supported for '{resource}'",
                        "supported_versions": versions}), 404

    path = f"/api/{version}/{resource}" + (f"/{rest}" if rest else "")
    req_id = request.headers.get("X-Request-ID", str(uuid.uuid4())[:8])
    started = time.time()
    cache_key = f"{path}?{request.query_string.decode()}"
    try:
        code, body = service_client.call(
            service, request.method, path,
            json=request.get_json(silent=True) if request.method in ("POST", "PUT") else None,
            params=request.args.to_dict(), headers={"X-Request-ID": req_id})
        if request.method == "GET" and resource == "products" and code == 200:
            _cache[cache_key] = (code, body)
        resp = jsonify(body)
        resp.status_code = code
    except ServiceUnavailable as exc:
        if request.method == "GET" and cache_key in _cache:          # graceful fallback
            code, body = _cache[cache_key]
            resp = jsonify(body)
            resp.status_code = code
            resp.headers["X-Fallback"] = "stale-cache"
        else:
            resp = jsonify({"error": "service temporarily unavailable",
                            "service": exc.service, "reason": exc.reason,
                            "circuit_state": exc.circuit_state,
                            "message": "Please try again shortly."})
            resp.status_code = 503
    resp.headers["X-Request-ID"] = req_id
    resp.headers["X-Routed-To"] = service
    print(f"[gateway] {req_id} {request.method} {path} -> {service} "
          f"{resp.status_code} {int((time.time() - started) * 1000)}ms", flush=True)
    return resp


if __name__ == "__main__":
    quiet_werkzeug()
    print(f"API Gateway running on http://{config.HOST}:{config.GATEWAY_PORT}", flush=True)
    app.run(host=config.HOST, port=config.GATEWAY_PORT, threaded=True)
