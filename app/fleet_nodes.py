"""Durable fleet-node identity and the exclusive-training state machine.

A node is a physical GPU box identified by a durable `node_key` that survives
Vast instance churn. Shared inference and exclusive training compete for the
same box; every state change is a conditional UPDATE so the claim-vs-
reservation race has exactly one winner even under PostgreSQL concurrency.

States: shared_ready -> draining -> training_reserved -> active -> cleanup ->
shared_ready. Any state can fall to quarantined (supervisor or admin);
quarantined returns only through an explicit reset.
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .models import FleetNode, utcnow

NODE_STATES = ("shared_ready", "draining", "training_reserved", "active",
               "cleanup", "quarantined")


class NodeError(ValueError):
    pass


def register_node(session: Session, node_key: str, *, instance_id: str | None = None,
                  worker_id: str | None = None) -> FleetNode:
    node = session.get(FleetNode, node_key)
    if node is None:
        node = FleetNode(id=node_key, instance_id=instance_id, worker_id=worker_id,
                         heartbeat_at=utcnow())
        session.add(node)
    else:
        if instance_id is not None:
            node.instance_id = instance_id
        if worker_id is not None:
            node.worker_id = worker_id
        node.heartbeat_at = utcnow()
    session.commit()
    return node


def node_view(node: FleetNode | None) -> dict | None:
    if node is None:
        return None
    return {"id": node.id, "instance_id": node.instance_id, "worker_id": node.worker_id,
            "state": node.state, "exclusive_attempt_id": node.exclusive_attempt_id,
            "in_flight_jobs": node.in_flight_jobs, "last_error": node.last_error,
            "heartbeat_at": node.heartbeat_at.isoformat() if node.heartbeat_at else None}


def _transition(session: Session, node_key: str, *, source: tuple[str, ...],
                target: str, **fields) -> bool:
    """Atomic conditional transition; returns False if the node moved under us."""
    values = {"state": target, "updated_at": utcnow(), **fields}
    result = session.execute(
        update(FleetNode)
        .where(FleetNode.id == node_key, FleetNode.state.in_(source))
        .values(**values))
    session.commit()
    return result.rowcount == 1


def drain_for_training(session: Session, node_key: str, attempt_id: str) -> bool:
    """shared_ready -> draining. Losers of the race return False."""
    return _transition(session, node_key, source=("shared_ready",),
                       target="draining", exclusive_attempt_id=attempt_id,
                       last_error=None)


def drain_complete(session: Session, node_key: str) -> bool:
    """draining -> training_reserved, but only with zero in-flight jobs."""
    node = session.get(FleetNode, node_key)
    if node is None or node.in_flight_jobs > 0:
        return False
    return _transition(session, node_key, source=("draining",),
                       target="training_reserved")


def activate_training(session: Session, node_key: str, attempt_id: str) -> bool:
    """training_reserved -> active: the exclusive claim. Exactly one winner."""
    return _transition(session, node_key, source=("training_reserved",),
                       target="active", exclusive_attempt_id=attempt_id)


def claim_for_training(session: Session, node_key: str, attempt_id: str) -> bool:
    """Exclusive claim for the worker.

    No node record -> True (node not under the fleet contract yet).
    shared_ready -> self-reserve through draining/training_reserved.
    training_reserved -> activate. Anything else loses the race.
    """
    node = session.get(FleetNode, node_key)
    if node is None:
        return True
    if node.state == "shared_ready":
        if not drain_for_training(session, node_key, attempt_id):
            return False
        if not drain_complete(session, node_key):
            return False
    return activate_training(session, node_key, attempt_id)


def finish_training(session: Session, node_key: str) -> bool:
    return _transition(session, node_key, source=("active",), target="cleanup")


def cleanup_done(session: Session, node_key: str) -> bool:
    """cleanup -> shared_ready, releasing the exclusive hold."""
    return _transition(session, node_key, source=("cleanup",), target="shared_ready",
                       exclusive_attempt_id=None, last_error=None)


def quarantine(session: Session, node_key: str, reason: str) -> bool:
    node = session.get(FleetNode, node_key)
    if node is None or node.state == "quarantined":
        return False
    return _transition(session, node_key, source=tuple(NODE_STATES[:-1]),
                       target="quarantined", last_error=reason[:280])


def reset_quarantine(session: Session, node_key: str) -> bool:
    return _transition(session, node_key, source=("quarantined",),
                       target="shared_ready", exclusive_attempt_id=None,
                       last_error=None)


def shared_claim_allowed(session: Session, node_key: str) -> bool:
    """Shared inference may only land on a fully ready node."""
    node = session.get(FleetNode, node_key)
    return node is not None and node.state == "shared_ready"


def set_in_flight(session: Session, node_key: str, count: int) -> None:
    node = session.get(FleetNode, node_key)
    if node is not None:
        node.in_flight_jobs = max(0, int(count))
        node.heartbeat_at = utcnow()
        session.commit()


def heartbeat_node(session: Session, node_key: str) -> None:
    node = session.get(FleetNode, node_key)
    if node is not None:
        node.heartbeat_at = utcnow()
        session.commit()


def supervisor_tick(session: Session, stale_seconds: float) -> list[str]:
    """Quarantine any node mid-training whose heartbeat went stale.

    shared_ready nodes are exempt (an idle box with no worker is not a
    training hazard); quarantined nodes are already handled.
    """
    from datetime import timedelta

    cutoff = utcnow() - timedelta(seconds=max(1.0, stale_seconds))
    stale_states = ("draining", "training_reserved", "active", "cleanup")
    stale = session.execute(
        select(FleetNode).where(FleetNode.state.in_(stale_states),
                                (FleetNode.heartbeat_at.is_(None))
                                | (FleetNode.heartbeat_at < cutoff))
    ).scalars().all()
    quarantined: list[str] = []
    for node in stale:
        if quarantine(session, node.id, "supervisor: stale heartbeat"):
            quarantined.append(node.id)
    return quarantined
