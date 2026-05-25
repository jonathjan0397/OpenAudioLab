from typing import Optional

from app.db.models import AgentNode
from app.db.session import SessionLocal


class AgentRegistry:
    @staticmethod
    def get_agent_by_id(agent_id: str) -> Optional[AgentNode]:
        db = SessionLocal()
        try:
            return db.query(AgentNode).filter(AgentNode.id == agent_id).first()
        finally:
            db.close()

    @staticmethod
    def get_agent_by_token(agent_api_token: str) -> Optional[AgentNode]:
        db = SessionLocal()
        try:
            return db.query(AgentNode).filter(AgentNode.agent_api_token == agent_api_token).first()
        finally:
            db.close()

    @staticmethod
    def get_available_agents() -> list[AgentNode]:
        db = SessionLocal()
        try:
            return db.query(AgentNode).filter(
                AgentNode.status == "idle",
                AgentNode.draining == False,
            ).all()
        finally:
            db.close()

    @staticmethod
    def get_agents_with_capability(capability: str) -> list[AgentNode]:
        db = SessionLocal()
        try:
            agents = db.query(AgentNode).filter(
                AgentNode.status == "idle",
                AgentNode.draining == False,
            ).all()
            result = []
            for a in agents:
                caps = a.capabilities_json or {}
                if caps.get(capability, False):
                    result.append(a)
            return result
        finally:
            db.close()
