from enum import StrEnum


class CheckOutcome(StrEnum):
    SUCCESS_JSON = "success_json"
    SUCCESS_NON_JSON = "success_non_json"
    INVALID_JSON = "invalid_json"
    UNEXPECTED_STATUS = "unexpected_status"
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    BLOCKED = "blocked"  # destination rejected by the SSRF policy at connect time
    RESPONSE_TOO_LARGE = "response_too_large"


class HealthStatus(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"


class SchemaStatus(StrEnum):
    UNKNOWN = "unknown"  # never compared
    BASELINE_CREATED = "baseline_created"
    COMPATIBLE = "compatible"
    DRIFTED = "drifted"
    UNAVAILABLE = "unavailable"  # comparison could not be performed (e.g. document store down)
    NOT_APPLICABLE = "not_applicable"  # no JSON body to compare (failure or non-JSON response)


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return {"info": 1, "warning": 2, "critical": 3}[self.value]


class IncidentType(StrEnum):
    SCHEMA_DRIFT = "schema_drift"
    AVAILABILITY = "availability"


class IncidentStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class CheckTrigger(StrEnum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"
