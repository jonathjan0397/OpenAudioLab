from datetime import datetime, timezone
from typing import Optional

from app.core.security import generate_secure_token, validate_password
from app.db.models import SystemSetting, User
from app.db.session import SessionLocal


class SetupService:
    @staticmethod
    def is_setup_complete() -> bool:
        db = SessionLocal()
        try:
            setting = db.query(SystemSetting).filter(SystemSetting.key == "setup_completed").first()
            return setting is not None and setting.value_json.get("completed") is True
        finally:
            db.close()

    @staticmethod
    def get_setup_status() -> dict:
        db = SessionLocal()
        try:
            setup_completed = False
            setup_completed_at = None
            initial_admin_created = False

            setting = db.query(SystemSetting).filter(SystemSetting.key == "setup_completed").first()
            if setting and setting.value_json.get("completed"):
                setup_completed = True
                setup_completed_at = setting.value_json.get("completed_at")

            admin_count = db.query(User).filter(User.is_admin == True).count()
            initial_admin_created = admin_count > 0

            return {
                "setup_completed": setup_completed,
                "setup_completed_at": setup_completed_at,
                "initial_admin_created": initial_admin_created,
                "admin_count": admin_count,
            }
        finally:
            db.close()

    @staticmethod
    def initialize_setup(
        admin_email: str,
        admin_password: str,
        site_name: str,
        public_backend_url: str,
        storage_provider: str,
        default_retention_days: int,
        enable_cpu_test_mode: bool,
        enable_cloud_agents: bool,
    ) -> tuple[bool, dict]:
        if SetupService.is_setup_complete():
            return False, {"error": "Setup has already been completed"}

        errors = validate_password(admin_password)
        if errors:
            return False, {"errors": errors}

        db = SessionLocal()
        try:
            from app.core.security import hash_password

            admin_user = User(
                email=admin_email,
                password_hash=hash_password(admin_password),
                is_admin=True,
            )
            db.add(admin_user)

            now = datetime.now(timezone.utc).isoformat()

            setup_setting = SystemSetting(
                key="setup_completed",
                value_json={"completed": True, "completed_at": now},
            )
            db.add(setup_setting)

            db.add(SystemSetting(key="site_name", value_json={"value": site_name}))
            db.add(SystemSetting(key="public_backend_url", value_json={"value": public_backend_url}))
            db.add(SystemSetting(key="storage_provider", value_json={"value": storage_provider}))
            db.add(SystemSetting(key="default_retention_days", value_json={"value": default_retention_days}))
            db.add(SystemSetting(key="enable_cpu_test_mode", value_json={"value": enable_cpu_test_mode}))
            db.add(SystemSetting(key="enable_cloud_agents", value_json={"value": enable_cloud_agents}))

            agent_token = generate_secure_token(48)
            db.add(SystemSetting(key="agent_registration_token", value_json={"value": agent_token, "created_at": now}))

            db.commit()

            return True, {
                "message": "Setup completed successfully",
                "agent_registration_token": agent_token,
                "setup_completed_at": now,
            }
        except Exception as e:
            db.rollback()
            return False, {"error": str(e)}
        finally:
            db.close()

    @staticmethod
    def get_setting(key: str) -> Optional[dict]:
        db = SessionLocal()
        try:
            setting = db.query(SystemSetting).filter(SystemSetting.key == key).first()
            return setting.value_json if setting else None
        finally:
            db.close()

    @staticmethod
    def update_setting(key: str, value: dict) -> bool:
        db = SessionLocal()
        try:
            setting = db.query(SystemSetting).filter(SystemSetting.key == key).first()
            if setting:
                setting.value_json = value
                setting.updated_at = datetime.now(timezone.utc)
                db.commit()
                return True
            return False
        finally:
            db.close()
