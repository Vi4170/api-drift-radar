"""Runs the exact demo scenario (demo/demo_drift.py) in-process: real API routes, real services,
the demo mock upstream served through the monitor's HTTP client."""

import httpx
from fastapi.testclient import TestClient

from demo import mock_api
from demo.demo_drift import run_demo
from tests.conftest import Upstream

MONITORED = "https://mock-upstream.example.com/users/1"


def test_demo_scenario(client: TestClient, upstream: Upstream) -> None:
    mock = TestClient(mock_api.app)
    upstream.respond(MONITORED, lambda req: httpx.Response(200, json=mock.get("/users/1").json()))

    def set_mode(mode: str) -> None:
        mock.post(f"/_control/mode/{mode}").raise_for_status()

    try:
        result = run_demo(client, set_mode, MONITORED)
    finally:
        set_mode("stable")
    assert result["incident_id"]
