# API usage

Base path: `/api/v1`. Interactive docs: `http://localhost:8000/docs` (Swagger UI) and `/redoc`. All bodies are JSON.
All routes except registration, login and the health probes require `Authorization: Bearer <access_token>`.

## Errors

Every error uses the same envelope:

```json
{ "error": { "code": "validation_error", "message": "Request validation failed",
             "details": [{ "loc": ["body", "interval_seconds"], "msg": "Input should be greater than or equal to 30", "type": "greater_than_equal" }] } }
```

| Status | `code`                        | When                                                            |
| ------ | ----------------------------- | --------------------------------------------------------------- |
| 401    | `unauthenticated`             | missing/invalid/expired token, bad credentials                  |
| 404    | `not_found`                   | resource missing **or owned by another user**                   |
| 409    | `conflict`                    | duplicate email/name, already-resolved incident, same baseline  |
| 422    | `validation_error`, `unsafe_url` | invalid input; URL rejected by the SSRF policy               |
| 429    | `rate_limited`                | login/registration/manual-check limits                          |
| 500    | `internal_error`              | unexpected server error (no details exposed)                    |

## Authentication

```http
POST /api/v1/auth/register     {"email": "dev@example.com", "password": "a-long-password"}   → 201
POST /api/v1/auth/login        {"email": "dev@example.com", "password": "a-long-password"}   → 200
GET  /api/v1/auth/me                                                                          → 200
```

```json
{ "access_token": "eyJhbGciOi...", "token_type": "bearer", "expires_in": 3600 }
```

## Endpoints

```http
GET    /api/v1/endpoints?search=&health=&schema_status=&is_active=&page=1&page_size=20
POST   /api/v1/endpoints
GET    /api/v1/endpoints/{id}
PATCH  /api/v1/endpoints/{id}          partial update; {"is_active": false} pauses scheduling
DELETE /api/v1/endpoints/{id}          204; removes checks, baselines, incidents and documents
```

Create request (only `name` and `url` are required):

```json
{
  "name": "Users API",
  "url": "https://api.example.com/v1/users/1",
  "method": "GET",
  "expected_status": 200,
  "interval_seconds": 300,
  "timeout_seconds": 10,
  "headers": { "X-Api-Version": "2" },
  "is_active": true
}
```

Response (abridged):

```json
{
  "id": "4c0e…", "name": "Users API", "url": "https://api.example.com/v1/users/1", "method": "GET",
  "expected_status": 200, "interval_seconds": 300, "timeout_seconds": 10.0, "is_active": true,
  "health_status": "healthy", "schema_status": "drifted", "last_checked_at": "2026-10-26T11:48:21Z",
  "last_status_code": 200, "last_latency_ms": 84.2, "last_outcome": "success_json",
  "open_incident_count": 1, "baseline_version": 1
}
```

Filters: `health` ∈ `unknown|healthy|unhealthy`; `schema_status` ∈ `unknown|baseline_created|compatible|drifted|unavailable|not_applicable`.

## Checks, schema and baselines

```http
POST /api/v1/endpoints/{id}/checks                         run a manual check now → CheckResult (201)
GET  /api/v1/endpoints/{id}/checks?outcome=&healthy=&since=&page=&page_size=
GET  /api/v1/endpoints/{id}/schema                         baseline + latest schema + classified changes
GET  /api/v1/endpoints/{id}/baselines                      version history, newest first
POST /api/v1/endpoints/{id}/baseline  {"check_id": "…"}    accept that check's schema as the new baseline (201)
GET  /api/v1/endpoints/{id}/metrics?window_hours=24        availability, avg/p95 latency, latency series
```

`CheckResult`:

```json
{
  "id": "a1b2…", "endpoint_id": "4c0e…", "checked_at": "2026-10-26T11:48:21Z", "trigger": "manual",
  "outcome": "success_json", "is_healthy": true, "status_code": 200, "latency_ms": 84.2,
  "response_size_bytes": 88, "content_type": "application/json", "error_message": null,
  "schema_status": "drifted", "schema_hash": "45cbe6…", "drift_severity": "critical", "change_count": 3,
  "baseline_id": "…", "incident_id": "…", "snapshot_id": "a1b2…"
}
```

`outcome` ∈ `success_json | success_non_json | invalid_json | unexpected_status | timeout | network_error | blocked | response_too_large`.

`GET /schema` response:

```json
{
  "baseline": { "version": 1, "schema_hash": "23e173…", "approved_by_id": null, "json_schema": { "type": "object", "…": "…" } },
  "latest_schema_hash": "45cbe6…",
  "latest_schema": { "type": "object", "…": "…" },
  "latest_check_id": "a1b2…",
  "latest_is_json": true,
  "comparison_available": true,
  "max_severity": "critical",
  "changes": [
    { "path": "$.user_id", "kind": "type_changed", "rule": "type_changed.incompatible", "severity": "critical",
      "old": "number", "new": "string", "description": "Type changed from number to string" },
    { "path": "$.name", "kind": "field_removed", "rule": "field_removed.required", "severity": "critical",
      "old": "string", "new": null, "description": "Previously observed field is missing" }
  ]
}
```

Accepting a baseline requires a successful JSON check of that endpoint whose schema differs from the current
baseline; it resolves the open drift incident with `resolution = "baseline_accepted"`.

## Incidents and dashboard

```http
GET  /api/v1/incidents?status=open&severity=critical&type=schema_drift&endpoint_id=…&page=1&page_size=20
GET  /api/v1/incidents/{id}                          incident + event history + schema changes
POST /api/v1/incidents/{id}/resolve  {"note": "…"}   manual resolution (409 if already resolved)
GET  /api/v1/dashboard/summary
```

Dashboard summary fields: `total_endpoints`, `active_endpoints`, `healthy_endpoints`, `unhealthy_endpoints`,
`unknown_endpoints`, `endpoints_with_open_drift`, `open_incidents_by_severity`, `checks_last_24h`,
`availability_24h_percent`, `avg_latency_24h_ms`, `recent_incidents[]`, `recent_checks[]`, `latency_series[]`
(hourly buckets for the last 24 h).

## Health probes

```http
GET /healthz   → {"status": "ok"}                                     liveness
GET /readyz    → {"status": "ok", "postgres": true, "mongodb": true}  503 + "degraded" if a database is down
```

## curl walkthrough

```bash
API=http://localhost:8000/api/v1
TOKEN=$(curl -s -X POST $API/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"dev@example.com","password":"a-long-password"}' | jq -r .access_token)
AUTH="Authorization: Bearer $TOKEN"

# list drifted endpoints
curl -s "$API/endpoints?schema_status=drifted" -H "$AUTH" | jq '.items[] | {name, open_incident_count}'

# accept the latest schema of an endpoint after reviewing it
CHECK=$(curl -s $API/endpoints/$EP/schema -H "$AUTH" | jq -r .latest_check_id)
curl -s -X POST $API/endpoints/$EP/baseline -H "$AUTH" -H 'Content-Type: application/json' \
  -d "{\"check_id\":\"$CHECK\"}" | jq '{version, approved_at}'
```
