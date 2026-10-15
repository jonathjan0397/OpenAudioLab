"""artist profiles, datasets, training runs, evaluations, rights

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "artist_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("style_json", sa.JSON(), nullable=False),
        sa.Column("singer_json", sa.JSON(), nullable=False),
        sa.Column("sharing_policy", sa.String(length=20), nullable=False),
        sa.Column("active_version_id", sa.String(length=36), nullable=True),
        sa.Column("etag_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_artist_profiles_owner_id", "artist_profiles", ["owner_id"])

    op.create_table(
        "rights_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=80), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=True),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column("declaration", sa.String(length=500), nullable=False),
        sa.Column("declared_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rights_records_owner_id", "rights_records", ["owner_id"])
    op.create_index("ix_rights_records_profile_id", "rights_records", ["profile_id"])

    op.create_table(
        "datasets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=80), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_datasets_owner_id", "datasets", ["owner_id"])
    op.create_index("ix_datasets_profile_id", "datasets", ["profile_id"])

    op.create_table(
        "dataset_tracks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("dataset_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=80), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("lyrics", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=20), nullable=True),
        sa.Column("labels_json", sa.JSON(), nullable=False),
        sa.Column("split", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dataset_tracks_dataset_id", "dataset_tracks", ["dataset_id"])
    op.create_index("ix_dataset_tracks_owner_id", "dataset_tracks", ["owner_id"])

    op.create_table(
        "dataset_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("dataset_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=80), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("frozen_sha256", sa.String(length=64), nullable=False),
        sa.Column("split_json", sa.JSON(), nullable=False),
        sa.Column("report_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dataset_versions_dataset_id", "dataset_versions", ["dataset_id"])
    op.create_index("ix_dataset_versions_owner_id", "dataset_versions", ["owner_id"])

    op.create_table(
        "artist_profile_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=80), nullable=False),
        sa.Column("mechanism", sa.String(length=40), nullable=False),
        sa.Column("base_model_id", sa.String(length=80), nullable=False),
        sa.Column("base_revision", sa.String(length=120), nullable=False),
        sa.Column("recipe_revision", sa.String(length=120), nullable=False),
        sa.Column("dataset_version_id", sa.String(length=36), nullable=True),
        sa.Column("artifacts_json", sa.JSON(), nullable=False),
        sa.Column("evaluation_status", sa.String(length=20), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_artist_profile_versions_profile_id", "artist_profile_versions", ["profile_id"])
    op.create_index("ix_artist_profile_versions_owner_id", "artist_profile_versions", ["owner_id"])

    op.create_table(
        "training_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("profile_version_id", sa.String(length=36), nullable=True),
        sa.Column("budget_json", sa.JSON(), nullable=False),
        sa.Column("hyperparams_json", sa.JSON(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("metrics_json", sa.JSON(), nullable=True),
        sa.Column("worker_id", sa.String(length=120), nullable=True),
        sa.Column("hardware", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_training_runs_job_id", "training_runs", ["job_id"])

    op.create_table(
        "evaluations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("profile_version_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("prompts_json", sa.JSON(), nullable=False),
        sa.Column("measurements_json", sa.JSON(), nullable=True),
        sa.Column("review", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evaluations_profile_version_id", "evaluations", ["profile_version_id"])
    op.create_index("ix_evaluations_job_id", "evaluations", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_evaluations_job_id", table_name="evaluations")
    op.drop_index("ix_evaluations_profile_version_id", table_name="evaluations")
    op.drop_table("evaluations")
    op.drop_index("ix_training_runs_job_id", table_name="training_runs")
    op.drop_table("training_runs")
    op.drop_index("ix_artist_profile_versions_owner_id", table_name="artist_profile_versions")
    op.drop_index("ix_artist_profile_versions_profile_id", table_name="artist_profile_versions")
    op.drop_table("artist_profile_versions")
    op.drop_index("ix_dataset_versions_owner_id", table_name="dataset_versions")
    op.drop_index("ix_dataset_versions_dataset_id", table_name="dataset_versions")
    op.drop_table("dataset_versions")
    op.drop_index("ix_dataset_tracks_owner_id", table_name="dataset_tracks")
    op.drop_index("ix_dataset_tracks_dataset_id", table_name="dataset_tracks")
    op.drop_table("dataset_tracks")
    op.drop_index("ix_datasets_profile_id", table_name="datasets")
    op.drop_index("ix_datasets_owner_id", table_name="datasets")
    op.drop_table("datasets")
    op.drop_index("ix_rights_records_profile_id", table_name="rights_records")
    op.drop_index("ix_rights_records_owner_id", table_name="rights_records")
    op.drop_table("rights_records")
    op.drop_index("ix_artist_profiles_owner_id", table_name="artist_profiles")
    op.drop_table("artist_profiles")
