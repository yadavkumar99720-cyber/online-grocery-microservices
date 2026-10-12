# Presentation outline (10-12 slides) and viva Q&A

## Slides
1 Title, team, roles · 2 Problem statement · 3 Why microservices · 4 Architecture diagram · 5 Services & their databases · 6 REST API list + versioning (v1 vs v2) · 7 Service discovery (registry, heartbeat, TTL) · 8 API Gateway (routing, versions, fallback) · 9 Saga diagram (`docs/saga.png`) + compensation · 10 Circuit breaker states (`docs/cb.png`) + demo results · 11 Test results (54/54) · 12 Conclusion / future work. Then LIVE DEMO.

## Likely viva questions
- **Why not a monolith?** Independent deployment, own data, failure isolation; each service here is a separate process with its own DB.
- **How does a service find another?** Asks registry for the *name*; instances send heartbeats every 3 s; no heartbeat for 9 s = removed.
- **What is the Saga here? Orchestration or choreography?** Orchestration - order-service coordinates reserve -> pay -> deliver -> confirm; on failure runs compensations in reverse (refund, cancel delivery, release stock).
- **Why not a distributed DB transaction?** Each service has its own DB; no shared transaction, so use eventual consistency with compensations.
- **Circuit breaker states?** CLOSED normal; 3 consecutive failures -> OPEN (fail fast); after 10 s HALF_OPEN lets one trial; success -> CLOSED, failure -> OPEN.
- **Which errors trip the breaker?** Connection errors, timeouts, HTTP 5xx. Business errors (402, 409) do not. That is why order-service reports a dependency outage as 424, not 503.
- **How is data isolation enforced?** Separate .db per service in its own folder; order stores only IDs; other data is fetched via REST; no service code references another .db.
- **Difference v1/v2?** See API_DOCUMENTATION.md.
- **What if notification-service dies?** Fallback: skipped and logged; order still CONFIRMED (non-critical dependency).
- **Idempotency?** reserve/release/payment/delivery are idempotent per order id so retries are safe.
- **Limitations / future work?** Orchestrator itself is not crash-recoverable (a persisted saga log exists but no auto-resume); SQLite -> PostgreSQL; message queue (RabbitMQ/Kafka) for async events; Docker; authentication; distributed tracing.
