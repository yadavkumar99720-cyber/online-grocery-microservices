"""Circuit Breaker pattern: CLOSED -> OPEN -> HALF_OPEN -> CLOSED.

CLOSED     : calls go through normally. Consecutive failures are counted.
OPEN       : after `failure_threshold` consecutive failures calls are rejected
             immediately (fail fast) - the broken service is not hammered.
HALF_OPEN  : after `recovery_timeout` seconds ONE trial call is allowed.
             success -> CLOSED, failure -> OPEN again.
"""
import threading
import time

CLOSED, OPEN, HALF_OPEN = "CLOSED", "OPEN", "HALF_OPEN"


class CircuitOpenError(Exception):
    """Raised when a call is rejected because the circuit is OPEN."""


class CircuitBreaker:
    def __init__(self, name, failure_threshold=3, recovery_timeout=10):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._state = CLOSED
        self._failures = 0
        self._opened_at = 0.0
        self._trial_in_progress = False
        self._lock = threading.Lock()
        self.transitions = []          # history of state changes (for demo/testing)

    # ------------------------------------------------------------------ helpers
    def _set_state(self, new_state):
        if new_state != self._state:
            self.transitions.append((time.strftime("%H:%M:%S"), self._state, new_state))
            print(f"[CircuitBreaker:{self.name}] {self._state} -> {new_state}", flush=True)
            self._state = new_state

    @property
    def state(self):
        with self._lock:
            if self._state == OPEN and time.time() - self._opened_at >= self.recovery_timeout:
                self._set_state(HALF_OPEN)
            return self._state

    @property
    def failures(self):
        return self._failures

    def snapshot(self):
        return {"state": self.state, "consecutive_failures": self._failures,
                "failure_threshold": self.failure_threshold,
                "recovery_timeout_s": self.recovery_timeout,
                "history": [list(t) for t in self.transitions[-10:]]}

    # --------------------------------------------------------------------- call
    def call(self, func, *args, **kwargs):
        with self._lock:
            if self._state == OPEN and time.time() - self._opened_at >= self.recovery_timeout:
                self._set_state(HALF_OPEN)
            if self._state == OPEN:
                raise CircuitOpenError(f"circuit for '{self.name}' is OPEN")
            if self._state == HALF_OPEN:
                if self._trial_in_progress:
                    raise CircuitOpenError(f"circuit for '{self.name}' is HALF_OPEN (trial running)")
                self._trial_in_progress = True
        try:
            result = func(*args, **kwargs)
        except Exception:
            self._on_failure()
            raise
        self._on_success()
        return result

    def _on_success(self):
        with self._lock:
            self._failures = 0
            self._trial_in_progress = False
            self._set_state(CLOSED)

    def _on_failure(self):
        with self._lock:
            self._failures += 1
            self._trial_in_progress = False
            if self._state == HALF_OPEN or self._failures >= self.failure_threshold:
                self._opened_at = time.time()
                self._set_state(OPEN)
