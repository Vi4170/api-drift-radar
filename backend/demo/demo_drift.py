"""Repeatable end-to-end schema-drift demonstration against a running stack.

    python -m demo.demo_drift --api http://localhost:8000 --mock http://localhost:8001 \
        --monitored-url http://mock-api:8000/users/1

Steps: register -> add endpoint -> stable check (baseline v1) -> drift -> incident opened,
baseline preserved -> repeat check (deduplicated) -> explicit acceptance -> incident resolved,
baseline v2 -> next check compatible. Exits non-zero if any expectation fails.
"""

import argparse
import sys
import uuid
from collections.abc import Callable

import httpx

API = "/api/v1"


class DemoFailure(AssertionError):
    pass


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise DemoFailure(message)
    print(f"  ok  {message}")


def run_demo(api: httpx.Client, set_mode: Callable[[str], None], monitored_url: str) -> dict:
    email = f"demo-{uuid.uuid4().hex[:8]}@example.com"
    token = api.post(f"{API}/auth/register", json={"email": email, "password": "demo-password-123"}).json()
    auth = {"Authorization": f"Bearer {token['access_token']}"}
    print(f"1. Registered {email}")

    created = api.post(
        f"{API}/endpoints",
        headers=auth,
        json={"name": "Demo users API", "url": monitored_url, "interval_seconds": 300},
    )
    expect(created.status_code == 201, f"endpoint registered ({created.status_code})")
    endpoint = created.json()
    base = f"{API}/endpoints/{endpoint['id']}"

    def check() -> dict:
        response = api.post(f"{base}/checks", headers=auth)
        expect(response.status_code == 201, f"manual check ran ({response.status_code})")
        return response.json()

    print("2. Upstream returns the stable response")
    set_mode("stable")
    first = check()
    expect(first["schema_status"] == "baseline_created", "first JSON response became baseline v1")

    print("3. Upstream changes its response")
    set_mode("drifted")
    drift = check()
    expect(drift["schema_status"] == "drifted", "drift detected")
    expect(drift["drift_severity"] == "critical", "severity classified as critical")
    view = api.get(f"{base}/schema", headers=auth).json()
    paths = {(c["path"], c["kind"], c["severity"]) for c in view["changes"]}
    expect(("$.user_id", "type_changed", "critical") in paths, "user_id number -> string detected")
    expect(("$.name", "field_removed", "critical") in paths, "missing name field detected")
    expect(("$.profile.zip", "field_added", "info") in paths, "new nested field reported as info")
    expect(view["baseline"]["version"] == 1, "approved baseline v1 preserved")

    incident = api.get(f"{API}/incidents/{drift['incident_id']}", headers=auth).json()
    expect(incident["status"] == "open" and incident["type"] == "schema_drift", "drift incident opened")

    print("4. Same drift observed again")
    again = check()
    expect(again["incident_id"] == drift["incident_id"], "same incident reused (no duplicate)")
    incidents = api.get(f"{API}/incidents", params={"type": "schema_drift"}, headers=auth).json()
    expect(
        incidents["total"] == 1 and incidents["items"][0]["occurrence_count"] == 2, "occurrence count is 2"
    )

    print("5. Developer explicitly accepts the new schema")
    accepted = api.post(f"{base}/baseline", headers=auth, json={"check_id": again["id"]})
    expect(accepted.status_code == 201 and accepted.json()["version"] == 2, "baseline v2 accepted")
    incident = api.get(f"{API}/incidents/{drift['incident_id']}", headers=auth).json()
    expect(incident["resolution"] == "baseline_accepted", "incident resolved by baseline acceptance")

    final = check()
    expect(final["schema_status"] == "compatible", "subsequent check is compatible with v2")
    print("Demo completed successfully.")
    return {"endpoint_id": endpoint["id"], "incident_id": drift["incident_id"]}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--mock", default="http://localhost:8001", help="mock API as reachable from here")
    parser.add_argument(
        "--monitored-url",
        default="http://mock-api:8000/users/1",
        help="mock API URL as reachable from the backend",
    )
    args = parser.parse_args()
    with (
        httpx.Client(base_url=args.api, timeout=30) as api,
        httpx.Client(base_url=args.mock, timeout=10) as mock,
    ):
        try:
            run_demo(
                api, lambda mode: mock.post(f"/_control/mode/{mode}").raise_for_status(), args.monitored_url
            )
        except DemoFailure as exc:
            print(f"  FAIL {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
