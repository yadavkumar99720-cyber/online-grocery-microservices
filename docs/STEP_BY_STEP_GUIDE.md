# Step-by-step: how to do, run and demonstrate this project

## 0. Platform / tools to choose (as suggested in your instruction sheet)
| Need | Choose | Why |
|---|---|---|
| Language | **Python 3.10+** | suggested by faculty, simplest |
| Framework | **Flask** | tiny, one file per service |
| Database | **SQLite** | no installation; a .db file per service = "database per service" |
| HTTP client | **requests** | calls between services |
| Editor | **VS Code** (or Spyder/Anaconda) | both allowed |
| API testing | **Postman** | import `docs/Postman_Collection.json` |
| Version control | **Git + GitHub** | one repo, each member commits their own service |
No Docker/Kubernetes/Java needed. Works on Windows, Mac and Linux.

## 1. One-time setup
1. Install Python from python.org (tick "Add Python to PATH"), install VS Code, install Postman.
2. Unzip the project. Open the folder in VS Code (File > Open Folder).
3. Open terminal (Ctrl+`) and run: `pip install -r requirements.txt`

## 2. Run it
1. `python start_all.py` - wait for "All services are UP".
2. Open http://127.0.0.1:8000/api/v1/products in a browser - you are calling the **gateway**.
3. Open http://127.0.0.1:8500/services - this is **service discovery** (all services listed).

## 3. Demonstrate each rubric item (follow this order in the final demo)
| # | Show | How |
|---|---|---|
| 1 | Problem + architecture | `docs/architecture.png`, explain 6 services |
| 2 | REST | Postman folders 2 and 3 (GET/POST/PUT/DELETE) |
| 3 | Gateway | every Postman call uses port 8000 only |
| 4 | Service discovery | registry page; stop+start a service, it re-appears. Code: `common/discovery.py` |
| 5 | Inter-service communication | place an order; terminal logs show `[saga]` lines calling customer, inventory, payment, delivery |
| 6 | API versioning | Postman folder 4: same order via `/api/v1/orders/1` vs `/api/v2/orders/1` |
| 7 | Database per service + isolation | `python tests/demo_data_isolation.py`; open the .db files in each `services/*/data/` |
| 8 | Saga success | POST /api/v1/orders then GET /api/v1/orders/1/saga |
| 9 | Saga compensation | Postman folder 5: `tok_decline` (stock released) and pincode `999111` (payment refunded + stock released) |
| 10 | Circuit breaker | `python tests/demo_circuit_breaker.py` (live kill, OPEN, HALF-OPEN, CLOSED) |
| 11 | Fault tolerance | in that demo products/customers keep working while payment is dead; notification down = order still confirmed |
| 12 | Testing | `python tests/run_tests.py` -> 54/54; show `docs/TEST_RESULTS.md` |

## 4. Team split (5 students) - each person owns files AND must understand all
| Student | Role | Owns |
|---|---|---|
| 1 | Microservice Dev 1 | `customer_service`, `delivery_service` (REST + DB) |
| 2 | Microservice Dev 2 | `inventory_service`, `notification_service` (REST + DB) |
| 3 | Communication Dev | `payment_service`, `registry`, `common/discovery.py`, `common/service_client.py` |
| 4 | Resilience/Saga Dev | `common/circuit_breaker.py`, `order_service` saga + compensation |
| 5 | Integration/Gateway Dev | `gateway`, versioning, `tests/`, `docs/`, Postman, report |
Use GitHub: one repo, each member commits their own folders (git add / commit / push) so contribution shows in history.

## 5. Milestones mapped to the project
1 problem + services (docs/REPORT) -> 2 architecture, APIs, DBs -> 3 core services -> 4 registry + v1/v2 -> 5 DB isolation -> 6 gateway + breaker -> 7 saga -> 8 tests, report, PPT, demo.

## 6. Before submission
- Read every file once; you must explain it in viva (see `docs/PRESENTATION_AND_VIVA.md`).
- Add your team names to `docs/Project_Report.docx` (cover page) and take your own Postman screenshots.
- Run `python reset_data.py`, start again, rehearse the demo twice.

## 7. Troubleshooting
- "Address already in use": an old run is still alive; close the terminal/stop Python processes or change ports in `common/config.py`.
- Gateway returns 503 right after start: wait ~5 s for services to register.
- Windows firewall popup: click Allow (localhost only).
