"""M2: fleet-node identity, exclusive-training state machine, supervisor."""

from __future__ import annotations

import pytest

_SEQ = iter(range(1, 10000))


@pytest.fixture(autouse=True)
def _admin_session(client):
    from app.models import User

    client.post("/api/v1/auth/logout")
    email = f"m2admin{next(_SEQ)}@example.com"
    resp = client.post("/api/v1/auth/register",
                       json={"email": email, "username": f"m2a{next(_SEQ)}",
                             "password": "super-secret-1"})
    uid = resp.json()["user"]["id"]
    with client.app.state.db.session() as session:
        session.get(User, uid).role = "admin"
        session.commit()


def _node(client, key=None):
    from app.fleet_nodes import register_node

    key = key or f"node-{next(_SEQ)}"
    with client.app.state.db.session() as session:
        register_node(session, key, instance_id="vi-1", worker_id="w-1")
    return key


def _state(client, key):
    from app.models import FleetNode

    with client.app.state.db.session() as session:
        n = session.get(FleetNode, key)
        return n.state if n else None


def test_state_machine_happy_path(client) -> None:
    from app.fleet_nodes import (activate_training, cleanup_done, drain_complete,
                                 drain_for_training, finish_training)

    key = _node(client)
    assert _state(client, key) == "shared_ready"
    with client.app.state.db.session() as s:
        assert drain_for_training(s, key, "att-1") is True
        assert drain_complete(s, key) is True
        assert activate_training(s, key, "att-1") is True
        assert finish_training(s, key) is True
        assert cleanup_done(s, key) is True
    assert _state(client, key) == "shared_ready"


def test_drain_waits_for_in_flight_jobs(client) -> None:
    from app.fleet_nodes import drain_complete, drain_for_training, set_in_flight

    key = _node(client)
    with client.app.state.db.session() as s:
        set_in_flight(s, key, 2)
        assert drain_for_training(s, key, "att-1") is True
        assert drain_complete(s, key) is False
        assert _state(client, key) == "draining"
        set_in_flight(s, key, 0)
        assert drain_complete(s, key) is True


def test_fresh_start_resets_stale_exclusive_state(client) -> None:
    from app.fleet_nodes import activate_training, drain_complete, drain_for_training, register_node

    key = _node(client)
    with client.app.state.db.session() as s:
        drain_for_training(s, key, "att-old")
        drain_complete(s, key)
        activate_training(s, key, "att-old")
    assert _state(client, key) == "active"
    # A recreated worker process cannot hold the old lease; it must clear it.
    with client.app.state.db.session() as s:
        node = register_node(s, key, worker_id="w-2", reset=True)
    assert node.state == "shared_ready"
    assert node.exclusive_attempt_id is None
    assert node.in_flight_jobs == 0
    assert node.worker_id == "w-2"


def test_activation_race_has_one_winner(client) -> None:
    from app.fleet_nodes import activate_training, drain_complete, drain_for_training

    key = _node(client)
    with client.app.state.db.session() as s:
        drain_for_training(s, key, "att-1")
        drain_complete(s, key)
        first = activate_training(s, key, "att-1")
        second = activate_training(s, key, "att-2")
    assert first is True and second is False
    assert _state(client, key) == "active"


def test_claim_for_training_paths(client) -> None:
    from app.fleet_nodes import claim_for_training

    with client.app.state.db.session() as s:
        assert claim_for_training(s, "unregistered-node", "att-x") is True
    key = _node(client)
    with client.app.state.db.session() as s:
        assert claim_for_training(s, key, "att-1") is True
        assert _state(client, key) == "active"
        assert claim_for_training(s, key, "att-2") is False


def test_supervisor_quarantines_stale_and_reset_releases(client) -> None:
    from datetime import timedelta

    from app.fleet_nodes import (activate_training, drain_complete, drain_for_training,
                                 quarantine, reset_quarantine, supervisor_tick)
    from app.models import FleetNode, utcnow

    key = _node(client)
    with client.app.state.db.session() as s:
        drain_for_training(s, key, "att-1")
        drain_complete(s, key)
        activate_training(s, key, "att-1")
        node = s.get(FleetNode, key)
        node.heartbeat_at = utcnow() - timedelta(seconds=600)
        s.commit()
        assert supervisor_tick(s, 180) == [key]
        assert _state(client, key) == "quarantined"
        assert supervisor_tick(s, 180) == []  # already handled
        assert reset_quarantine(s, key) is True
        assert _state(client, key) == "shared_ready"
    other = _node(client)
    with client.app.state.db.session() as s:
        assert quarantine(s, other.id if hasattr(other, "id") else other, "gpu ecc error")
        assert _state(client, other) == "quarantined"


def test_shared_claim_only_on_ready_nodes(client) -> None:
    from app.fleet_nodes import drain_for_training, shared_claim_allowed

    key = _node(client)
    with client.app.state.db.session() as s:
        assert shared_claim_allowed(s, key) is True
        drain_for_training(s, key, "att-1")
        assert shared_claim_allowed(s, key) is False
        assert shared_claim_allowed(s, "ghost") is False


def test_admin_node_endpoints(client) -> None:
    key = _node(client)
    listed = client.get("/api/v1/admin/gpu-fleet/nodes").json()["nodes"]
    assert any(n["id"] == key for n in listed)
    drain = client.post(f"/api/v1/admin/gpu-fleet/nodes/{key}/drain",
                        json={"attempt_id": "att-9"})
    assert drain.status_code == 200 and drain.json()["state"] == "draining"
    again = client.post(f"/api/v1/admin/gpu-fleet/nodes/{key}/drain", json={})
    assert again.status_code == 409
    q = client.post(f"/api/v1/admin/gpu-fleet/nodes/{key}/quarantine",
                    json={"reason": "smoke test"})
    assert q.status_code == 200 and q.json()["state"] == "quarantined"
    reset = client.post(f"/api/v1/admin/gpu-fleet/nodes/{key}/reset")
    assert reset.status_code == 200 and reset.json()["state"] == "shared_ready"
    missing = client.post("/api/v1/admin/gpu-fleet/nodes/ghost/drain", json={})
    assert missing.status_code == 404
