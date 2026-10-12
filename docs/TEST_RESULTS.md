# API Test Results (automated)

Run date: 2026-10-12 12:13:36  
Command: `python tests/run_tests.py`  
**Result: 54/54 checks passed**

| # | Area | Test | Result | Evidence |
|---|------|------|--------|----------|
| 1 | Service Discovery | all 6 services registered in registry | PASS | ['customer-service', 'delivery-service', 'inventory-service', 'notification-service', 'order-service', 'payment-service'] |
| 2 | Service Discovery | every registered instance is healthy | PASS |  |
| 3 | Service Discovery | gateway /api/status exposes registry + breaker states | PASS |  |
| 4 | API Gateway | GET /api/v1/products via gateway -> 200 | PASS |  |
| 5 | API Gateway | gateway adds X-Routed-To header | PASS |  |
| 6 | API Gateway | unknown resource -> 404 | PASS |  |
| 7 | API Gateway | unsupported version (customers v2) -> 404 with supported_versions | PASS |  |
| 8 | REST | POST customer -> 201 | PASS |  |
| 9 | REST | POST duplicate email -> 409 | PASS |  |
| 10 | REST | POST missing fields -> 400 | PASS |  |
| 11 | REST | GET customer -> 200 | PASS |  |
| 12 | REST | PUT customer updates name | PASS |  |
| 13 | REST | GET unknown customer -> 404 | PASS |  |
| 14 | REST | POST product -> 201 | PASS |  |
| 15 | REST | POST invalid price -> 400 | PASS |  |
| 16 | REST | PUT product updates stock | PASS |  |
| 17 | REST | GET products?category= filter works | PASS |  |
| 18 | REST | DELETE product -> 200 | PASS |  |
| 19 | REST | deleted product -> 404 | PASS |  |
| 20 | Saga success | POST /api/v1/orders -> 201 CONFIRMED | PASS | CONFIRMED |
| 21 | Saga success | total = 2*95 + 62 = 252 | PASS | 252.0 |
| 22 | Saga success | inventory-service stock reduced | PASS |  |
| 23 | Saga success | payment-service has SUCCESS payment | PASS |  |
| 24 | Saga success | delivery-service has ASSIGNED delivery with agent | PASS |  |
| 25 | Saga success | saga steps in order | PASS | ['CREATE_ORDER', 'RESERVE_STOCK', 'PROCESS_PAYMENT', 'ARRANGE_DELIVERY', 'CONFIRM_ORDER', 'NOTIFY_CUSTOMER'] |
| 26 | Saga success | notification-service recorded a message | PASS |  |
| 27 | Saga fail-payment | returns 402 and order CANCELLED | PASS | 402 CANCELLED |
| 28 | Saga fail-payment | stock reservation RELEASED (compensated) | PASS | 98 -> 98 |
| 29 | Saga fail-payment | no delivery was created | PASS |  |
| 30 | Saga fail-payment | saga log: PROCESS_PAYMENT FAILED + RESERVE_STOCK COMPENSATED | PASS |  |
| 31 | Saga fail-delivery | returns 409 and order CANCELLED | PASS | 409 CANCELLED |
| 32 | Saga fail-delivery | payment was REFUNDED (compensated) | PASS | ['REFUNDED'] |
| 33 | Saga fail-delivery | stock released (compensated) | PASS |  |
| 34 | Saga fail-delivery | compensation runs in REVERSE order | PASS | ['PROCESS_PAYMENT', 'RESERVE_STOCK'] |
| 35 | Saga fail-stock | returns 409 and order CANCELLED | PASS |  |
| 36 | Saga fail-stock | no payment was attempted | PASS |  |
| 37 | Saga fail-stock | unknown customer -> 404, no order created | PASS |  |
| 38 | REST | POST order with empty items -> 400 | PASS |  |
| 39 | Versioning | v1 returns a flat order object | PASS |  |
| 40 | Versioning | v2 returns {data, meta} with items + saga_steps | PASS |  |
| 41 | Versioning | v2 nests customer/payment/delivery | PASS |  |
| 42 | Versioning | v2 list supports paging + filter | PASS |  |
| 43 | Versioning | v1 list is a plain array | PASS |  |
| 44 | Versioning | POST /api/v2/orders -> 201 with saga_succeeded meta | PASS |  |
| 45 | REST | PUT order notes -> 200 | PASS |  |
| 46 | REST | DELETE (cancel) confirmed order -> CANCELLED | PASS |  |
| 47 | REST | cancel refunded payment | PASS |  |
| 48 | REST | cancel cancelled delivery | PASS |  |
| 49 | REST | cancel restocked items | PASS |  |
| 50 | REST | cancelling again -> 409 | PASS |  |
| 51 | Data isolation | 6 separate database files exist (one per service) | PASS | ['customer_service', 'delivery_service', 'inventory_service', 'notification_service', 'order_service', 'payment_service'] |
| 52 | Data isolation | order DB has no products/customers/payments tables | PASS | ['order_items', 'orders', 'saga_log'] |
| 53 | Data isolation | no table name is duplicated across service DBs | PASS |  |
| 54 | Data isolation | static scan: no service code opens another service's .db file | PASS | [] |
