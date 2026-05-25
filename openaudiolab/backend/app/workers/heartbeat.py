from datetime import datetime, timedelta, timezone

from app.db.models import AgentNode
from app.db.session import SessionLocal

HEARTBEAT_TIMEOUT_MINUTES = 5


class HeartbeatMonitor:
    @staticmethod
    def check_stale_agents() -> list[str]:
        db = SessionLocal()
        try:
            threshold = datetime.now(timezone.utc) - timedelta(minutes=HEARTBEAT_TIMEOUT_MINUTES)
            stale_agents = db.query(AgentNode).filter(
                AgentNode.status != "offline",
                AgentNode.last_heartbeat_at < threshold,
            ).all()

            stale_ids = []
            for agent in stale_agents:
                agent.status = "offline"
                stale_ids.append(agent.id)

            if stale_ids:
                db.commit()

            return stale_ids
        finally:
            db.close()

    @staticmethod
    def is_agent_alive(agent_id: str) -> bool:
        db = SessionLocal()
        try:
            agent = db.query(AgentNode).filter(AgentNode.id == agent_id).first()
            if not agent:
                return False
            if not agent.last_heartbeat_at:
                return False
            threshold = datetime.now(timezone.utc) - timedelta(minutes=HEARTBEAT_TIMEOUT_MINUTES)
            return agent.last_heartbeat_at >= threshold
        finally:
            db.close()
