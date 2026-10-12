# REST API Documentation

All requests go through the **API Gateway**: `http://127.0.0.1:8000`. Format: `/api/<version>/<resource>`.
Import `docs/Postman_Collection.json` into Postman to try every endpoint.

| Resource | Backend service | Versions |
|---|---|---|
| customers | customer-service | v1 |
| products, inventory | inventory-service | v1 |
| orders | order-service | **v1, v2** |
| payments | payment-service | v1 |
| deliveries | delivery-service | v1 |
| notifications | notification-service | v1 |

## Customers (customer.db)
| Method | Endpoint | Description | Codes |
|---|---|---|---|
| GET | /api/v1/customers | list | 200 |
| GET | /api/v1/customers/{id} | one | 200, 404 |
| POST | /api/v1/customers | create `{name,email,address,pincode,phone?}` | 201, 400, 409 |
| PUT | /api/v1/customers/{id} | update | 200, 404, 409 |
| DELETE | /api/v1/customers/{id} | delete | 200, 404 |

## Products & Inventory (inventory.db)
| Method | Endpoint | Description |
|---|---|---|
| GET | /api/v1/products?category=&q= | list / filter / search |
| GET / PUT / DELETE | /api/v1/products/{id} | read / update / delete |
| POST | /api/v1/products | create `{name,category,price,stock,unit?}` |
| POST | /api/v1/inventory/reserve | **Saga step** - all-or-nothing stock reservation (409 if insufficient) |
| POST | /api/v1/inventory/commit | **Saga step** - confirm reservation |
| POST | /api/v1/inventory/release | **Compensation** - give stock back (idempotent) |

## Orders (order.db) - API versioning
| Method | Endpoint | Description |
|---|---|---|
| POST | /api/v1/orders , /api/v2/orders | place order = run the Saga. Body: `{customer_id, items:[{product_id,quantity}], payment_token?, payment_method?, delivery_address?, pincode?}` |
| GET | /api/v1/orders , /api/v2/orders | list |
| GET | /api/v1/orders/{id} , /api/v2/orders/{id} | one |
| PUT | /api/v1/orders/{id} , /api/v2/orders/{id} | update `notes` |
| DELETE | /api/v1/orders/{id} , /api/v2/orders/{id} | cancel a CONFIRMED order (refund + cancel delivery + restock) |
| GET | /api/v1/orders/{id}/saga | saga step log |

Status codes of POST: 201 confirmed, 402 payment declined, 404 customer/product not found, 409 business failure (no stock, unserviceable pincode), 424 a dependent service is down. Failed orders end as `CANCELLED` with `failure_reason`.

### Difference between v1 and v2
| | v1 | v2 |
|---|---|---|
| Response shape | flat object | `{ "data": {...}, "meta": {...} }` |
| Order detail | ids only | nested `customer`, `delivery`, `payment`, `items[]`, `saga_steps[]`, `links` |
| List | plain array, `?customer_id=` | paged `?page=&per_page=`, filters `status`, `customer_id`, `meta.total` |

## Payments (payment.db) - simulated, no real card data
POST /api/v1/payments (token `tok_visa` = success, `tok_decline` = declined; amount > 20000 declined) · GET list / by id / `?order_id=` · POST /api/v1/payments/{id}/refund (**compensation**) · DELETE (FAILED records only)

## Deliveries (delivery.db)
POST /api/v1/deliveries (pincode starting `999` -> 409 not serviceable) · GET list / by id / `?order_id=` · PUT /api/v1/deliveries/{id}/status · POST /api/v1/deliveries/{id}/cancel (**compensation**) · GET/POST /api/v1/deliveries/agents

## Notifications (notification.db)
POST /api/v1/notifications · GET /api/v1/notifications

## Infrastructure endpoints
Registry (:8500): POST /register, POST /heartbeat, POST /deregister, GET /services, GET /services/{name}/instance · Every service: GET /health (shows its circuit breaker states) · Gateway: GET /api/status
