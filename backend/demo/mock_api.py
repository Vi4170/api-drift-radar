"""DEMO FIXTURE - a controllable fake upstream API for the schema-drift walkthrough.

    GET  /users/1               the monitored endpoint
    POST /_control/mode/{mode}  switch between "stable" and "drifted" responses
    GET  /_control/mode         current mode

Run: uvicorn demo.mock_api:app --port 8001
"""

from typing import Literal

from fastapi import FastAPI

RESPONSES = {
    "stable": {
        "user_id": 101,
        "name": "Alex",
        "active": True,
        "roles": ["admin"],
        "profile": {"city": "Oslo"},
    },
    "drifted": {
        "user_id": "101",
        "active": True,
        "roles": ["admin"],
        "profile": {"city": "Oslo", "zip": "0150"},
    },
}

app = FastAPI(title="Drift Radar demo upstream")
state = {"mode": "stable"}


@app.get("/users/1")
def user() -> dict:
    return RESPONSES[state["mode"]]


@app.get("/_control/mode")
def get_mode() -> dict:
    return state


@app.post("/_control/mode/{mode}")
def set_mode(mode: Literal["stable", "drifted"]) -> dict:
    state["mode"] = mode
    return state
