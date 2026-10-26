# Demo walkthrough: detecting schema drift end to end

This demo uses a **controlled mock upstream** (`backend/demo/mock_api.py`, a demo fixture — not part of the product)
that serves `GET /users/1` and can be switched between a *stable* and a *drifted* response:

```jsonc
// stable                                             // drifted
{ "user_id": 101, "name": "Alex", "active": true,     { "user_id": "101", "active": true,
  "roles": ["admin"], "profile": {"city": "Oslo"} }     "roles": ["admin"], "profile": {"city": "Oslo", "zip": "0150"} }
```

Expected result after switching: `$.user_id` number → string (**critical**), `$.name` removed (**critical**),
`$.profile.zip` added (**info**).

## Option A — scripted (Docker Compose)

```bash
cp .env.example .env              # fill in the three secrets
# The mock lives on the private Docker network, so exempt exactly that hostname (demo only!):
echo "MONITOR_ALLOWED_HOSTS=mock-api" >> .env

docker compose --profile demo up --build -d
docker compose exec api python -m demo.demo_drift \
  --api http://localhost:8000 --mock http://mock-api:8000 --monitored-url http://mock-api:8000/users/1
```

## Option B — scripted, without Docker

With PostgreSQL and MongoDB running and the migrations applied:

```bash
cd backend
export JWT_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
export MONITOR_ALLOWED_HOSTS=localhost MANUAL_CHECK_COOLDOWN_SECONDS=0   # demo only
uvicorn app.main:create_app --factory --port 8000 &
uvicorn demo.mock_api:app --port 8001 &
python -m demo.demo_drift --api http://localhost:8000 --mock http://localhost:8001 \
  --monitored-url http://localhost:8001/users/1
```

Expected output (captured from a real run against PostgreSQL 16 + MongoDB 7):

```
1. Registered demo-0981c537@example.com
  ok  endpoint registered (201)
2. Upstream returns the stable response
  ok  manual check ran (201)
  ok  first JSON response became baseline v1
3. Upstream changes its response
  ok  manual check ran (201)
  ok  drift detected
  ok  severity classified as critical
  ok  user_id number -> string detected
  ok  missing name field detected
  ok  new nested field reported as info
  ok  approved baseline v1 preserved
  ok  drift incident opened
4. Same drift observed again
  ok  manual check ran (201)
  ok  same incident reused (no duplicate)
  ok  occurrence count is 2
5. Developer explicitly accepts the new schema
  ok  baseline v2 accepted
  ok  incident resolved by baseline acceptance
  ok  manual check ran (201)
  ok  subsequent check is compatible with v2
Demo completed successfully.
```

The script exits non-zero on the first failed expectation. The same scenario runs in the automated test-suite
(`backend/tests/test_e2e_demo.py`).

## Option C — through the web UI

1. Start the stack with the demo profile (Option A, without running the script) and open <http://localhost:8080>.
2. **Create account**.
3. **Add endpoint** → name `Demo users API`, URL `http://mock-api:8000/users/1` → *Add endpoint*.
   (Try `http://169.254.169.254/latest/meta-data/` first to see the SSRF protection reject it.)
4. On the endpoint page click **Run check now** → *schema: baseline created*; the Schema card shows baseline v1.
5. Switch the upstream to the drifted response:
   ```bash
   curl -X POST http://localhost:8001/_control/mode/drifted
   ```
6. **Run check now** again → health stays *healthy*, schema becomes *drifted*, a **critical** incident appears under
   *Open incidents*, and the Schema card lists the three changes. The approved baseline is still v1.
7. Run the check a few more times → still one incident; its "seen N×" counter increases.
8. Click **Compare schemas & manage baseline** → side-by-side trees with changed paths highlighted.
9. Click **Accept as new baseline…** → a confirmation dialog explains what will happen → **Accept as v2**.
10. Open **Incidents** (status: *All*) → the incident is *resolved* with resolution *baseline accepted*; its history
    shows `opened` and `resolved — New baseline v2 accepted`.
11. Switch the upstream back (`…/_control/mode/stable`) and check again: this is now drift *relative to v2*, which
    shows the baseline really changed only when you approved it.

Leave the worker running and the endpoint active to see scheduled checks appear in *Check history* with trigger
`scheduled` (default interval 5 minutes; the first run is jittered 1–30 s after the worker picks it up).
