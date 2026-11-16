import time
import logging
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED = "CLOSED"        # Normal operation: requests pass through
    OPEN = "OPEN"            # Tripped: requests fail fast without network calls
    HALF_OPEN = "HALF_OPEN"  # Canary mode: testing if dependency recovered


class CircuitBreaker:
    """Three-state finite state machine algorithm for remote service fault tolerance."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

        self.state: CircuitState = CircuitState.CLOSED
        self.failure_count: int = 0
        self.last_state_change: float = time.monotonic()
        self.last_failure_time: Optional[float] = None

    def can_execute(self) -> bool:
        """Determines if a request is allowed through based on the current state."""
        now = time.monotonic()

        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            # Check if cool-off window has elapsed
            if now - self.last_state_change >= self.recovery_timeout:
                logger.info(f"Circuit Breaker [{self.name}]: OPEN -> HALF_OPEN (probing canary request)")
                self.state = CircuitState.HALF_OPEN
                self.last_state_change = now
                return True
            return False

        if self.state == CircuitState.HALF_OPEN:
            # In half-open, allow one probe through
            return True

        return False

    def record_success(self):
        """Records a successful call and resets the circuit to CLOSED."""
        if self.state != CircuitState.CLOSED:
            logger.info(f"Circuit Breaker [{self.name}]: {self.state.value} -> CLOSED (service recovered)")
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_state_change = time.monotonic()

    def record_failure(self):
        """Records a failure and trips to OPEN if the threshold is reached."""
        self.failure_count += 1
        self.last_failure_time = time.monotonic()

        if self.state == CircuitState.HALF_OPEN:
            logger.warning(f"Circuit Breaker [{self.name}]: Canary failed. HALF_OPEN -> OPEN")
            self.state = CircuitState.OPEN
            self.last_state_change = time.monotonic()
        elif self.state == CircuitState.CLOSED and self.failure_count >= self.failure_threshold:
            logger.warning(
                f"Circuit Breaker [{self.name}]: {self.failure_count} consecutive failures. CLOSED -> OPEN"
            )
            self.state = CircuitState.OPEN
            self.last_state_change = time.monotonic()

    def reset(self):
        """Manually resets the circuit breaker to closed state."""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_state_change = time.monotonic()
