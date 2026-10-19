"""projects, versions, upload sessions, asset lineage columns

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("assets") as batch_op:
        batch_op.alter_column("job_id", existing_type=sa.String(length=36), nullable=True)
    op.add_column("assets", sa.Column("kind", sa.String(length=20), nullable=False, server_default="generated"))
    op.add_column("assets", sa.Column("source_asset_id", sa.String(length=36), nullable=True))
    op.add_column("assets", sa.Column("stem_source", sa.String(length=20), nullable=True))
    op.add_column("assets", sa.Column("stem_category", sa.String(length=40), nullable=True))
    op.add_column("assets", sa.Column("processing", sa.String(length=120), nullable=True))

    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("active_version_id", sa.String(length=36), nullable=True),
        sa.Column("etag_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_projects_owner_id", "projects", ["owner_id"])

    op.create_table(
        "project_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=80), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("source_job_id", sa.String(length=36), nullable=True),
        sa.Column("source_asset_id", sa.String(length=36), nullable=True),
        sa.Column("parent_version_id", sa.String(length=36), nullable=True),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_project_versions_project_id", "project_versions", ["project_id"])
    op.create_index("ix_project_versions_owner_id", "project_versions", ["owner_id"])

    op.create_table(
        "upload_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=80), nullable=False),
        sa.Column("filename", sa.String(length=300), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=True),
        sa.Column("bytes", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("asset_id", sa.String(length=36), nullable=True),
        sa.Column("error", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_upload_sessions_owner_id", "upload_sessions", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_upload_sessions_owner_id", table_name="upload_sessions")
    op.drop_table("upload_sessions")
    op.drop_index("ix_project_versions_owner_id", table_name="project_versions")
    op.drop_index("ix_project_versions_project_id", table_name="project_versions")
    op.drop_table("project_versions")
    op.drop_index("ix_projects_owner_id", table_name="projects")
    op.drop_table("projects")
    op.drop_column("assets", "processing")
    op.drop_column("assets", "stem_category")
    op.drop_column("assets", "stem_source")
    op.drop_column("assets", "source_asset_id")
    op.drop_column("assets", "kind")
    with op.batch_alter_table("assets") as batch_op:
        batch_op.alter_column("job_id", existing_type=sa.String(length=36), nullable=False)
