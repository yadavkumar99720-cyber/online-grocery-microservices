"""Inter-service HTTP client = Service Discovery + Circuit Breaker + timeout.

    status, body = call("payment-service", "POST", "/api/v1/payments", json={...})

* The target is a SERVICE NAME; the URL comes from the registry.
* Each target service has its own CircuitBreaker.
* HTTP 4xx (business errors such as "payment declined") are returned normally
  and do NOT trip the breaker. Connection errors, timeouts and HTTP 5xx do.
* When the dependency is down / circuit is open `ServiceUnavailable` is raised
  so the caller can run a fallback or a compensating action.
"""
import requests

from common import config, discovery
from common.circuit_breaker import CircuitBreaker, CircuitOpenError

_breakers = {}


class ServiceUnavailable(Exception):
    def __init__(self, service, reason, circuit_state):
        super().__init__(f"{service} unavailable: {reason}")
        self.service = service
        self.reason = reason
        self.circuit_state = circuit_state


class _RemoteServerError(Exception):
    pass


def get_breaker(service):
    if service not in _breakers:
        _breakers[service] = CircuitBreaker(service, config.CB_FAILURE_THRESHOLD,
                                            config.CB_RECOVERY_TIMEOUT)
    return _breakers[service]


def all_breaker_states():
    return {name: b.snapshot() for name, b in _breakers.items()}


def call(service, method, path, json=None, params=None, headers=None, timeout=None):
    breaker = get_breaker(service)

    def _do():
        base = discovery.resolve(service)                       # SERVICE DISCOVERY
        resp = requests.request(method, base + path, json=json, params=params,
                                headers=headers, timeout=timeout or config.HTTP_TIMEOUT)
        if resp.status_code >= 500:
            raise _RemoteServerError(f"HTTP {resp.status_code}")
        return resp

    try:
        resp = breaker.call(_do)                                # CIRCUIT BREAKER
    except CircuitOpenError:
        raise ServiceUnavailable(service, "circuit breaker is OPEN (failing fast)", breaker.state)
    except requests.ConnectionError:
        raise ServiceUnavailable(service, "connection refused - service is down", breaker.state)
    except requests.Timeout:
        raise ServiceUnavailable(service, "request timed out", breaker.state)
    except (discovery.DiscoveryError, requests.RequestException, _RemoteServerError) as exc:
        raise ServiceUnavailable(service, str(exc) or type(exc).__name__, breaker.state)

    try:
        body = resp.json()
    except ValueError:
        body = {"raw": resp.text}
    return resp.status_code, body
