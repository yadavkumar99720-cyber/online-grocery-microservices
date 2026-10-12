"""Client side of Service Discovery.

* register_with_registry()  - a service announces itself and keeps sending heartbeats.
* resolve(name)             - turn a service NAME (e.g. "payment-service") into a URL
                              by asking the Service Registry. No URL is hard-coded.
"""
import threading
import time

import requests

from common import config

_cache = {}   # last known URL per service (used only if the registry itself is unreachable)


class DiscoveryError(Exception):
    pass


def register_with_registry(name, port):
    url = f"http://{config.HOST}:{port}"

    def loop():
        registered = False
        while True:
            try:
                if not registered:
                    r = requests.post(f"{config.REGISTRY_URL}/register",
                                      json={"name": name, "url": url}, timeout=2)
                    registered = r.status_code in (200, 201)
                    if registered:
                        print(f"[discovery] {name} registered at {url}", flush=True)
                else:
                    r = requests.post(f"{config.REGISTRY_URL}/heartbeat",
                                      json={"name": name, "url": url}, timeout=2)
                    if r.status_code == 404:        # registry restarted and forgot us
                        registered = False
                        continue
            except requests.RequestException:
                registered = False                   # registry down -> retry later
            time.sleep(config.HEARTBEAT_INTERVAL)

    threading.Thread(target=loop, daemon=True, name=f"heartbeat-{name}").start()


def resolve(name):
    """Return base URL of a healthy instance of service `name`."""
    try:
        r = requests.get(f"{config.REGISTRY_URL}/services/{name}/instance", timeout=2)
    except requests.RequestException:
        if name in _cache:                       # registry unreachable: use last known address
            return _cache[name]
        raise DiscoveryError("service registry unreachable")
    if r.status_code == 200:
        _cache[name] = r.json()["url"]
        return _cache[name]
    _cache.pop(name, None)
    raise DiscoveryError(f"no healthy instance of '{name}' registered")
