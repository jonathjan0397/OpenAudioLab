"""UAIS: Universal Artist Identity System schema (hard replace of experimental training tables)

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-21

The pre-UAIS training data was experimental (no customers); the old tables are
dropped, not migrated.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DROPPED = (
    "evaluations",
    "training_runs",
    "artist_profile_versions",
    "dataset_versions",
    "dataset_tracks",
    "datasets",
    "rights_records",
)


def upgrade() -> None:
    for table in _DROPPED:
        op.drop_table(table)

    op.drop_column("artist_profiles", "active_version_id")
    op.add_column(
        "artist_profiles",
        sa.Column("default_voice_profile_id", sa.String(length=36), nullable=True),
    )
    op.drop_column("loras", "profile_version_id")
    op.add_column("loras", sa.Column("adapter_id", sa.String(length=36), nullable=True))
    op.add_column("vast_instances", sa.Column("dph", sa.Float(), nullable=True))

    op.create_table(
        "voice_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("artist_profile_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=80), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("dataset_version_id", sa.String(length=36), nullable=True),
        sa.Column("identity_json", sa.JSON(), nullable=False),
        sa.Column("description_json", sa.JSON(), nullable=False),
        sa.Column("performance_json", sa.JSON(), nullable=False),
        sa.Column("embeddings_json", sa.JSON(), nullable=False),
        sa.Column("analysis_model", sa.String(length=80), nullable=True),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artist_profile_id", "version_number", name="uq_voiceprofile_artist_version"),
    )
    op.create_index("ix_voice_profiles_artist_profile_id", "voice_profiles", ["artist_profile_id"])
    op.create_index("ix_voice_profiles_owner_id", "voice_profiles", ["owner_id"])

    op.create_table(
        "voice_datasets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("artist_profile_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("latest_version_number", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_voice_datasets_artist_profile_id", "voice_datasets", ["artist_profile_id"])
    op.create_index("ix_voice_datasets_owner_id", "voice_datasets", ["owner_id"])

    op.create_table(
        "voice_recordings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("dataset_id", sa.String(length=36), nullable=False),
        sa.Column("artist_profile_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=80), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("filename", sa.String(length=300), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("sample_rate", sa.Integer(), nullable=True),
        sa.Column("channels", sa.Integer(), nullable=True),
        sa.Column("qc_json", sa.JSON(), nullable=False),
        sa.Column("consent_json", sa.JSON(), nullable=False),
        sa.Column("vocal_asset_id", sa.String(length=36), nullable=True),
        sa.Column("separation_json", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_voice_recordings_dataset_id", "voice_recordings", ["dataset_id"])
    op.create_index("ix_voice_recordings_artist_profile_id", "voice_recordings", ["artist_profile_id"])
    op.create_index("ix_voice_recordings_owner_id", "voice_recordings", ["owner_id"])

    op.create_table(
        "voice_dataset_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("dataset_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=80), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("frozen_sha256", sa.String(length=64), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("report_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_id", "version_number", name="uq_voicedsv_dataset_version"),
    )
    op.create_index("ix_voice_dataset_versions_dataset_id", "voice_dataset_versions", ["dataset_id"])
    op.create_index("ix_voice_dataset_versions_owner_id", "voice_dataset_versions", ["owner_id"])

    op.create_table(
        "voice_adapters",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("artist_profile_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=80), nullable=False),
        sa.Column("voice_profile_id", sa.String(length=36), nullable=True),
        sa.Column("dataset_version_id", sa.String(length=36), nullable=True),
        sa.Column("model_selection", sa.String(length=80), nullable=False),
        sa.Column("engine_model", sa.String(length=120), nullable=False),
        sa.Column("base_revision", sa.String(length=120), nullable=False),
        sa.Column("adapter_format", sa.String(length=30), nullable=False),
        sa.Column("architecture_json", sa.JSON(), nullable=False),
        sa.Column("training_config_json", sa.JSON(), nullable=False),
        sa.Column("training_job_id", sa.String(length=36), nullable=True),
        sa.Column("storage_prefix", sa.String(length=500), nullable=False),
        sa.Column("files_json", sa.JSON(), nullable=False),
        sa.Column("adapter_sha256", sa.String(length=64), nullable=True),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=True),
        sa.Column("validation_json", sa.JSON(), nullable=True),
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("limitations_json", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=60), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_voice_adapters_artist_profile_id", "voice_adapters", ["artist_profile_id"])
    op.create_index("ix_voice_adapters_owner_id", "voice_adapters", ["owner_id"])

    op.create_table(
        "voice_analyses",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("artist_profile_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=80), nullable=False),
        sa.Column("dataset_version_id", sa.String(length=36), nullable=True),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("embedding_model", sa.String(length=80), nullable=False),
        sa.Column("input_type", sa.String(length=20), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_voice_analyses_artist_profile_id", "voice_analyses", ["artist_profile_id"])
    op.create_index("ix_voice_analyses_owner_id", "voice_analyses", ["owner_id"])
    op.create_index("ix_voice_analyses_job_id", "voice_analyses", ["job_id"])


def downgrade() -> None:
    for table in (
        "voice_analyses",
        "voice_adapters",
        "voice_dataset_versions",
        "voice_recordings",
        "voice_datasets",
        "voice_profiles",
    ):
        op.drop_table(table)
    op.drop_column("vast_instances", "dph")
    op.drop_column("loras", "adapter_id")
    op.add_column("loras", sa.Column("profile_version_id", sa.String(length=36), nullable=True))
    op.drop_column("artist_profiles", "default_voice_profile_id")
    op.add_column("artist_profiles", sa.Column("active_version_id", sa.String(length=36), nullable=True))
    for table in _DROPPED:
        op.create_table(
            table,
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
