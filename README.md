# API Drift Radar

**Monitor HTTP APIs, detect JSON schema drift before your consumers do, and manage the incidents it causes.**

API Drift Radar polls the APIs you depend on, learns the shape of their JSON responses, and tells you — with a
severity — when that shape changes: a field disappears, a number becomes a string, an array's items change type.
The first response becomes an approved **baseline**; every later response is compared to it, and the baseline only
changes when a developer explicitly accepts a new one.

![Schema comparison](docs/screenshots/schema-comparison.png)

---

## Contents

- [Problem and motivation](#problem-and-motivation)
- [Features](#features)
- [Architecture](#architecture)
- [Technology choices](#technology-choices)
- [Quick start (Docker)](#quick-start-docker)
- [Local development without Docker](#local-development-without-docker)
- [Environment variables](#environment-variables)
- [Database and migrations](#database-and-migrations)
- [Example API usage](#example-api-usage)
- [Schema-drift demonstration](#schema-drift-demonstration)
- [Testing, linting and builds](#testing-linting-and-builds)
- [CI/CD](#cicd)
- [Security model](#security-model)
- [Known limitations](#known-limitations)
- [Screenshots](#screenshots)
- [Roadmap](#roadmap)

Deeper documentation: [architecture](docs/architecture.md) · [database design](docs/database-design.md) ·
[security & threat model](docs/security.md) · [API usage](docs/api-usage.md) · [demo walkthrough](docs/demo-walkthrough.md)

## Problem and motivation

An endpoint that returns `200 OK` can still break every client that calls it. Yesterday:

```json
{ "user_id": 101, "name": "Alex", "active": true }
```

Today:

```json
{ "user_id": "101", "active": true }
```

Uptime monitors stay green. Your mobile app crashes on `user_id`, and the profile screen shows a blank name.
API Drift Radar reports:

| Severity | Path        | Change        | Baseline | Observed |
| -------- | ----------- | ------------- | -------- | -------- |
| critical | `$.user_id` | type changed  | number   | string   |
| critical | `$.name`    | field removed | string   | —        |

It opens one incident (not one per poll), keeps the approved baseline intact, and lets you either wait for the API to
recover (the incident auto-resolves) or accept the new structure as baseline v2.

## Features

- **Accounts** — registration, login, JWT access tokens, Argon2id password hashing, per-user data isolation.
- **Endpoint management** — name, URL, expected status, interval, timeout, optional request headers; pause/resume;
  delete with cleanup across both databases.
- **Monitoring engine** — distinguishes network failure, timeout, unexpected status, invalid JSON, valid non-JSON and
  successful JSON responses; records status, latency and size. Health and schema compatibility are tracked
  **separately**.
- **Schema inference & drift detection** — nested objects, arrays (incl. empty and mixed), nulls, booleans vs numbers,
  int/float normalisation; 11 change rules mapped to info / warning / critical (table-driven, overridable).
- **Baselines** — first JSON response becomes v1 automatically; later versions only by explicit, confirmed acceptance;
  full version history.
- **Incidents** — drift and availability incidents, deduplicated (one open incident per endpoint and type, enforced by a
  partial unique index), auto-resolved on recovery or baseline acceptance, manual resolution with notes, event history.
- **Scheduled monitoring** — a separate worker process (APScheduler) with bounded concurrency, no overlapping runs,
  restart-safe job reconciliation and single-leader election via a PostgreSQL advisory lock.
- **Manual checks** — run from the API/UI without the worker.
- **Dashboard** — real totals, health, open drift, availability, latency charts, recent incidents and activity.
- **SSRF protection** — connection-level validation of every resolved address (defeats DNS rebinding), no redirects,
  no proxies, size/time limits. See [Security model](#security-model).

## Architecture

```mermaid
flowchart LR
    Browser["React SPA<br/>(TanStack Query)"] -- "/api/v1 (JWT)" --> Nginx["nginx<br/>static + reverse proxy"]
    Nginx --> API["FastAPI app<br/>routes → services → repositories"]
    Worker["Worker process<br/>MonitoringScheduler (APScheduler)"]
    API -- "manual checks" --> Mon["MonitoringService"]
    Worker -- "scheduled checks" --> Mon
    Mon --> Client["SafeHTTPClient<br/>(SSRF-safe transport)"]
    Client -- "GET (validated IP only)" --> Ext[("Monitored APIs")]
    Mon --> PG[("PostgreSQL<br/>users, endpoints, checks,<br/>baselines, incidents, audit")]
    Mon --> Mongo[("MongoDB<br/>snapshots, schemas, diffs")]
    API --> PG
    API --> Mongo
    Worker -. "advisory lock (leader)" .-> PG
```

| Component                                                 | Responsibility                                                                      |
| --------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| `SchemaInferenceEngine` (`monitoring/schema_inference.py`) | JSON value → normalised, value-independent schema; merges array items               |
| `SchemaComparisonEngine` (`monitoring/schema_comparison.py`) | baseline vs observed → classified `SchemaChange`s via a `SeverityPolicy`          |
| `SafeHTTPClient` (`monitoring/http_client.py`)             | the only code that contacts monitored URLs; SSRF-safe network backend, limits       |
| `DestinationPolicy` (`security/ssrf.py`)                   | URL rules, DNS resolution, public-IP validation                                     |
| `MonitoringService` (`services/monitoring_service.py`)     | the full check pipeline shared by API and worker; cross-database consistency        |
| `BaselineService`, `IncidentService`                       | baseline lifecycle; incident open/dedupe/update/resolve                             |
| `ReportingService`                                         | read models: schema view, metrics, dashboard                                        |
| `MonitoringScheduler` (`workers/scheduler.py`)             | reconciles jobs from the DB, bounded thread pool, no overlap                        |
| Repositories                                               | owner-scoped SQL queries; MongoDB `DocumentStore`                                   |

More in [docs/architecture.md](docs/architecture.md).

## Technology choices

| Area        | Choice                                                     | Why                                                                                      |
| ----------- | ---------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| API         | Python 3.12, FastAPI, Pydantic v2                          | typed validation at the boundary, automatic OpenAPI/Swagger                              |
| Relational  | PostgreSQL 16, SQLAlchemy 2, Alembic                       | integrity, partial unique indexes, row locks, advisory locks                             |
| Documents   | MongoDB 7 (PyMongo)                                        | schemaless storage for arbitrary response bodies, schemas and diffs; TTL expiry          |
| HTTP client | httpx + custom httpcore network backend                    | connection pooling plus a hook to validate the *actual* connected IP                     |
| Auth        | PyJWT (HS256), argon2-cffi (Argon2id)                      | standard, well-reviewed primitives                                                       |
| Scheduling  | APScheduler 3 in a separate worker process                 | simple, in-process scheduling with `max_instances`/`coalesce`; no extra broker needed    |
| Frontend    | React 19, TypeScript, Vite, TanStack Query, React Router, Recharts | typed server-state caching and routing; hand-written CSS design tokens (no CSS framework needed) |
| Quality     | pytest, mongomock, Vitest, Testing Library, ruff, oxlint, Prettier | fast, deterministic tests that run with or without real databases               |
| Delivery    | Docker Compose, GitHub Actions                             | one-command local stack; CI against real PostgreSQL and MongoDB service containers      |

## Quick start (Docker)

Requires Docker with Compose v2. No paid services.

```bash
cp .env.example .env
# Fill in POSTGRES_PASSWORD, MONGO_ROOT_PASSWORD and JWT_SECRET, e.g.:
python -c "import secrets; print(secrets.token_urlsafe(48))"

docker compose up --build
```

Compose starts PostgreSQL and MongoDB (with health checks and named volumes), runs `alembic upgrade head` once in the
`migrate` service, then starts the API, the worker and the frontend.

| What                         | URL                                 |
| ---------------------------- | ----------------------------------- |
| Web app                      | <http://localhost:8080>             |
| API (Swagger UI)             | <http://localhost:8000/docs>        |
| OpenAPI JSON / ReDoc         | `/openapi.json`, `/redoc`           |
| Liveness / readiness         | `/healthz`, `/readyz`               |

Then: open the web app → **Create account** → **Add endpoint** with a public JSON URL (for example
`https://jsonplaceholder.typicode.com/users/1`) → **Run check now** → explore the dashboard.

To try drift detection with a controllable upstream, follow [docs/demo-walkthrough.md](docs/demo-walkthrough.md).

## Local development without Docker

Backend (Python 3.12+; PostgreSQL and MongoDB reachable):

```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                     # set DATABASE_URL, MONGO_URL, JWT_SECRET
alembic upgrade head
uvicorn app.main:create_app --factory --reload --port 8000   # API
python -m app.workers.main                                   # worker (second terminal)
```

Frontend (Node 22+; Vite proxies `/api` to `localhost:8000`):

```bash
cd frontend
npm ci
npm run dev        # http://localhost:5173
```

## Environment variables

Backend (`backend/.env.example`; Compose sets these from the root `.env`):

| Variable                         | Default                         | Purpose                                                       |
| -------------------------------- | ------------------------------- | ------------------------------------------------------------- |
| `DATABASE_URL`                   | local PostgreSQL                | SQLAlchemy URL (`postgresql+psycopg://…`)                     |
| `MONGO_URL` / `MONGO_DB`         | `mongodb://localhost:27017` / `driftradar` | MongoDB connection and database                 |
| `JWT_SECRET`                     | **required**, ≥ 32 chars        | token signing key; placeholders are rejected at startup       |
| `JWT_ALGORITHM`                  | `HS256`                         |                                                               |
| `ACCESS_TOKEN_EXPIRE_MINUTES`    | `60`                            | 5–1440                                                        |
| `CORS_ORIGINS`                   | `http://localhost:5173`         | comma-separated allowed browser origins                       |
| `LOG_LEVEL`                      | `INFO`                          |                                                               |
| `LOGIN_RATE_LIMIT_PER_MINUTE`    | `10`                            | per IP+email (login) / per IP (register)                      |
| `MANUAL_CHECK_COOLDOWN_SECONDS`  | `10`                            | minimum gap between manual checks of one endpoint             |
| `MONITOR_MAX_RESPONSE_BYTES`     | `1048576`                       | hard cap on (decompressed) response size                      |
| `MONITOR_MAX_RETRIES`            | `1`                             | retries for connect errors/timeouts only (0–3)                |
| `MONITOR_MAX_CONCURRENCY`        | `5`                             | worker thread-pool size                                       |
| `MONITOR_MIN_INTERVAL_SECONDS`   | `30`                            | smallest allowed schedule interval                            |
| `MONITOR_MAX_TIMEOUT_SECONDS`    | `30`                            | largest allowed per-endpoint timeout                          |
| `MONITOR_ALLOWED_HOSTS`          | empty                           | **demo only**: exact hostnames exempt from the public-IP rule |
| `SNAPSHOT_RETENTION_DAYS`        | `14`                            | TTL for raw response snapshots in MongoDB                     |
| `WORKER_RECONCILE_SECONDS`       | `30`                            | how often the worker re-reads the endpoint schedule           |

Compose-only (root `.env.example`): `POSTGRES_USER/PASSWORD/DB`, `MONGO_ROOT_USER/PASSWORD`.
Frontend (`frontend/.env.example`): `VITE_API_BASE_URL` (default `/api/v1`), `VITE_DEV_API_PROXY`.

## Database and migrations

PostgreSQL holds everything relational; MongoDB holds documents keyed by IDs that PostgreSQL references.

```mermaid
erDiagram
    users ||--o{ endpoints : owns
    endpoints ||--o{ check_results : has
    endpoints ||--o{ baselines : "versions (one current)"
    endpoints ||--o{ incidents : has
    incidents ||--o{ incident_events : history
    baselines |o--o| check_results : "source check"
    check_results }o--o| incidents : "linked"
    users ||--o{ audit_events : performed
```

- Migrations live in `backend/alembic/versions`. Apply with `alembic upgrade head` (Compose's `migrate` service does
  this automatically and idempotently). CI also runs `downgrade base` → `upgrade head` → `alembic check`.
- Key constraints: unique email, unique endpoint name per owner, unique `(endpoint, version)` per baseline, **partial
  unique index** "one current baseline per endpoint", **partial unique index** "one open incident per endpoint+type".
- All timestamps are timezone-aware UTC. Deleting an endpoint cascades in PostgreSQL, then removes its MongoDB documents.

Details, including the cross-database consistency strategy: [docs/database-design.md](docs/database-design.md).

## Example API usage

```bash
API=http://localhost:8000/api/v1
TOKEN=$(curl -s -X POST $API/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"dev@example.com","password":"a-long-password"}' | jq -r .access_token)
AUTH="Authorization: Bearer $TOKEN"

EP=$(curl -s -X POST $API/endpoints -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"name":"Users","url":"https://jsonplaceholder.typicode.com/users/1","interval_seconds":300}' | jq -r .id)

curl -s -X POST $API/endpoints/$EP/checks -H "$AUTH" | jq '{outcome, status_code, latency_ms, schema_status}'
curl -s $API/endpoints/$EP/schema -H "$AUTH" | jq '.changes'
curl -s "$API/incidents?status=open&severity=critical" -H "$AUTH" | jq '.items'
```

Every route, with request/response examples and error formats: [docs/api-usage.md](docs/api-usage.md) or the live
Swagger UI at `/docs`.

## Schema-drift demonstration

A repeatable demo ships with the backend: `demo/mock_api.py` (a controllable upstream, clearly marked as a demo
fixture) and `demo/demo_drift.py` (a script that registers, monitors, flips the upstream to a drifted response,
verifies the incident and baseline preservation, accepts the new baseline and verifies recovery).

```bash
# In .env: MONITOR_ALLOWED_HOSTS=mock-api
docker compose --profile demo up --build -d
docker compose exec api python -m demo.demo_drift --api http://localhost:8000 \
  --mock http://mock-api:8000 --monitored-url http://mock-api:8000/users/1
```

The same scenario runs in the test-suite (`tests/test_e2e_demo.py`). Step-by-step, including the UI flow:
[docs/demo-walkthrough.md](docs/demo-walkthrough.md).

## Testing, linting and builds

```bash
# Backend — uses SQLite + mongomock by default, no services needed
cd backend
pytest
ruff check . && ruff format --check .

# Same suite against real databases (what CI does)
TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/driftradar_test \
TEST_MONGO_URL=mongodb://localhost:27017 pytest

# Frontend
cd frontend
npm run lint && npm run format:check && npm run typecheck && npm test && npm run build
```

Outbound HTTP in tests always goes through `httpx.MockTransport` or a local loopback server; no test touches the
Internet. Test coverage includes: schema inference and comparison (nesting, arrays, empty arrays, nullability,
bool-vs-number, numeric normalisation, severity), SSRF (URL rules, IPv4/IPv6/NAT64/mapped addresses, DNS rebinding at
connect time, redirects, size and time limits), auth (invalid credentials, expired/forged tokens, rate limiting),
cross-user isolation on every route, endpoint CRUD and validation, baseline creation/preservation/acceptance, incident
deduplication/auto-resolution/manual resolution, MongoDB outage behaviour, scheduler reconciliation, pagination and
filtering, and the full demo scenario. Frontend tests cover form validation, auth flows, status display,
loading/error/empty states, the schema-diff table and tree, baseline-acceptance confirmation and incident filtering.

## CI/CD

`.github/workflows/ci.yml` runs on pushes to `main` and on every pull request:

- **backend** — installs pinned dependencies, `ruff check`, `ruff format --check`, migration round-trip +
  `alembic check` on PostgreSQL 16, then `pytest` against PostgreSQL + MongoDB 7 service containers and again against
  SQLite + mongomock.
- **frontend** — `npm ci`, oxlint, Prettier check, `tsc`, Vitest, production build.

Workflow permissions are `contents: read`; actions are pinned to commit SHAs; checkout does not persist credentials;
no secrets are needed (database passwords are throwaway values for ephemeral CI containers). Dependabot keeps actions,
pip, npm and Docker base images updated. There is intentionally no deployment step.

To reproduce CI locally, run the commands in [Testing, linting and builds](#testing-linting-and-builds).

## Security model

User-supplied URLs make this application an SSRF target, so outbound requests are treated as hostile by default:

- Only `http`/`https`; no embedded credentials, backslashes, control characters, numeric/hex IP shorthands, internal
  hostnames (`localhost`, `*.local`, `*.internal`, `metadata.google.internal`…) or ports below 1024 other than 80/443.
- **Connection-level IP validation**: a custom httpcore network backend resolves the hostname, rejects the destination
  if *any* address is loopback, private, link-local, CGNAT, multicast, reserved, unspecified, IPv4-mapped/NAT64/6to4/
  Teredo-embedded, then connects to exactly the validated address. TLS still verifies the certificate for the original
  hostname. This closes DNS-rebinding/TOCTOU gaps; a regression test proves it.
- Redirects are never followed; environment proxies are ignored; TLS verification cannot be disabled.
- Total-time deadline, streamed body with a byte cap (applied after decompression), bounded pool and concurrency,
  bounded retries for idempotent GETs only, minimum intervals, manual-check cooldowns.
- Only the user's configured headers plus a fixed User-Agent are sent — never cookies, app credentials or environment
  data. Forwarding/hop-by-hop headers cannot be configured.
- Argon2id hashing, timing-equalised login, signed expiring JWTs, strict request models (`extra="forbid"` against mass
  assignment), owner-scoped queries everywhere, consistent error envelopes without stack traces, log redaction, CORS
  allow-list, nginx security headers (CSP, `X-Frame-Options`, `nosniff`), non-root containers, databases not published
  to the host.

Full threat model and limitations: [docs/security.md](docs/security.md).

## Known limitations

- **GET only.** The method field exists for extensibility, but other methods are deliberately not supported.
- **Rate limiting is in-process.** Fine for one API replica; multiple replicas need a shared store (e.g. Redis).
  Behind the bundled nginx, the register limit keys on the proxy's IP.
- **Tokens live in `sessionStorage`.** Simple and CSRF-free, but readable by injected scripts; the strict CSP mitigates
  XSS. There are no refresh tokens or server-side revocation; tokens expire after `ACCESS_TOKEN_EXPIRE_MINUTES`.
- **Custom request headers are stored in plaintext** in PostgreSQL (visible only to their owner). Do not store
  production secrets there; encryption at rest is on the roadmap.
- **DNS resolution uses the system resolver** and is not bounded by the request timeout.
- **Schema inference is sample-based**: optional fields that are absent in a sample are indistinguishable from removed
  ones on the first observation, which is why uncertain cases are labelled conservatively (e.g. `null`-only baselines).
- **Metrics** compute p95 over the newest 500 checks of the window and dashboard hourly buckets over at most 5 000
  checks — marked in code with `ponytail:` comments and upgrade paths.
- One scheduler is active at a time (by design); scaling checks horizontally would need sharded scheduling.
- The Docker Compose stack has not yet been executed end to end: Docker was unavailable in the environment where the
  project was built. The same services (API, worker, mock upstream, Vite) were run natively against real PostgreSQL 16
  and MongoDB 7 instead, and CI exercises the backend against both databases.

## Screenshots

Genuine screenshots captured from a running local stack (PostgreSQL 16, MongoDB 7, API, worker, Vite) while running the
demo scenario:

| Dashboard                                         | Endpoint detail with drift                                  |
| ------------------------------------------------- | ----------------------------------------------------------- |
| ![Dashboard](docs/screenshots/dashboard.png)      | ![Endpoint detail](docs/screenshots/endpoint-detail.png)    |
| **Baseline acceptance confirmation**              | **Incident with history**                                   |
| ![Accept baseline](docs/screenshots/accept-baseline.png) | ![Incident](docs/screenshots/incident-detail.png)    |

Mobile layout: [docs/screenshots/dashboard-mobile.png](docs/screenshots/dashboard-mobile.png).

**Adding or refreshing screenshots:** start the stack, run the demo walkthrough so there is real data, then capture
each page at 1400×900 (and 390×844 for mobile) and save PNGs under `docs/screenshots/` with the file names above.
Only use screenshots of the real application with real (demo) data — no mock-ups.

## Roadmap

- Encrypt stored request headers (envelope encryption with a KMS-held key).
- Refresh tokens / HttpOnly cookie sessions with CSRF protection, and token revocation.
- Notifications (email, Slack, webhooks) on incident open/resolve.
- Shared rate limiting and sharded scheduling for multi-replica deployments.
- Per-endpoint severity-policy overrides and ignore rules for known-volatile paths.
- OpenAPI-contract comparison in addition to inferred schemas.
- Additional safe request methods (HEAD; POST with explicit opt-in and no retries).

## License

[MIT](LICENSE)
