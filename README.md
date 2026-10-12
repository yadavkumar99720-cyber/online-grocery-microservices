# Online Grocery Delivery System - Microservices Mini Project (Team 8)

Python 3 + Flask + SQLite + Requests. 6 business microservices + Service Registry + API Gateway.

## Quick start (Windows / Mac / Linux)
```
pip install -r requirements.txt
python start_all.py            # starts all 8 processes. Ctrl+C stops them
```
Open a 2nd terminal:
```
python tests/run_tests.py              # 54 automated API checks  -> docs/TEST_RESULTS.md
python tests/demo_circuit_breaker.py   # kills a service live, shows CLOSED/OPEN/HALF-OPEN
python tests/demo_data_isolation.py    # shows database-per-service
python reset_data.py                   # (services stopped) wipe DBs, back to seed data
```
Client entry point: **http://127.0.0.1:8000** (API Gateway). Registry view: http://127.0.0.1:8500/services

## Ports
registry 8500 · gateway 8000 · customer 5001 · inventory 5002 · order 5003 · payment 5004 · delivery 5005 · notification 5006
(If a port is busy, change it in `common/config.py`.)

## Folder layout
```
common/            shared technical helpers ONLY: circuit_breaker.py, discovery.py, service_client.py, flask_utils.py, config.py
services/<name>/app.py   one folder per service, each with its own data/<name>.db (created on first start)
start_all.py  reset_data.py  requirements.txt
tests/             run_tests.py, demo_circuit_breaker.py, demo_data_isolation.py
docs/              REPORT, API docs, diagrams, Postman collection, test results, demo output
```
Run a single service by hand: start `services/registry/app.py` first, then any other `services/<x>/app.py` (from the project root).

## Requirement -> where it is
| Requirement | Where |
|---|---|
| REST (GET/POST/PUT/DELETE) | every service `app.py` |
| API versioning v1/v2 | `services/order_service/app.py`, routing in `services/gateway/app.py` |
| Service discovery | `services/registry/app.py`, `common/discovery.py` |
| Inter-service communication (>=3) | order-service -> customer, inventory, payment, delivery, notification via `common/service_client.py` |
| Circuit breaker | `common/circuit_breaker.py`, demo `tests/demo_circuit_breaker.py` |
| Database per service / isolation | `services/*/data/*.db`, `tests/demo_data_isolation.py` |
| API gateway | `services/gateway/app.py` |
| Saga + compensation | `place_order()` in `services/order_service/app.py` |
| Fault tolerance | breaker + fallbacks (gateway stale cache, notification skip) |
| Testing & docs | `tests/`, `docs/` |
All data is fake. No real personal or payment data.
