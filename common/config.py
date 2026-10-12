"""Central configuration (ports and URLs). Override with environment variables if needed."""
import os

HOST = "127.0.0.1"

REGISTRY_PORT = int(os.getenv("REGISTRY_PORT", 8500))
GATEWAY_PORT = int(os.getenv("GATEWAY_PORT", 8000))

# service-name -> port.  NOTE: services never use these ports to talk to each other.
# They ask the Service Registry for the address of a *service name*.
SERVICE_PORTS = {
    "customer-service": 5001,
    "inventory-service": 5002,
    "order-service": 5003,
    "payment-service": 5004,
    "delivery-service": 5005,
    "notification-service": 5006,
}

REGISTRY_URL = os.getenv("REGISTRY_URL", f"http://{HOST}:{REGISTRY_PORT}")

# Service registry settings
HEARTBEAT_INTERVAL = 3      # seconds between heartbeats sent by a service
INSTANCE_TTL = 9            # registry drops an instance if no heartbeat for this long

# Circuit breaker settings
CB_FAILURE_THRESHOLD = 3    # consecutive failures before the circuit OPENS
CB_RECOVERY_TIMEOUT = 10    # seconds the circuit stays OPEN before trying HALF_OPEN
HTTP_TIMEOUT = 3            # seconds per inter-service HTTP call
