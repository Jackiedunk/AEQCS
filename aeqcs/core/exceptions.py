"""Domain exceptions used to enforce AEQCS invariants."""


class AEQCSError(Exception):
    """Base exception for AEQCS."""


class LookAheadViolation(AEQCSError):
    """Raised when a query can see data beyond the decision timestamp."""


class GateBypassError(AEQCSError):
    """Raised when code attempts to mutate authoritative state outside the gate."""


class RateLimitExceeded(AEQCSError):
    """Raised when a data source token bucket is empty."""


class ConfigurationError(AEQCSError):
    """Raised when runtime configuration is invalid."""
