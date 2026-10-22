"""Model Lab M3: voice segments, identity embeddings, singer groups

Revision ID: 0041
Revises: 0040
Create Date: 2026-10-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0041"
down_revision: Union[str, None] = "0040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ml_voice_segments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("recording_id", sa.String(36), nullable=False),
        sa.Column("crop_start", sa.Float(), nullable=False),
        sa.Column("crop_end", sa.Float(), nullable=False),
        sa.Column("quality_json", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(12), nullable=False, server_default="candidate"),
        sa.Column("group_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_mlvs_recording", "ml_voice_segments", ["recording_id"])
    op.create_index("ix_mlvs_group", "ml_voice_segments", ["group_id"])
    op.create_table(
        "ml_embedding_vectors",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("segment_id", sa.String(36), nullable=False),
        sa.Column("model", sa.String(40), nullable=False),
        sa.Column("vector_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_mlev_segment", "ml_embedding_vectors", ["segment_id"])
    op.create_index("ix_mlev_model", "ml_embedding_vectors", ["model"])
    op.create_table(
        "ml_voice_groups",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("embedding_model", sa.String(40), nullable=False),
        sa.Column("centroid_json", sa.JSON(), nullable=False),
        sa.Column("member_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("state", sa.String(12), nullable=False, server_default="suggested"),
        sa.Column("merged_into", sa.String(36), nullable=True),
        sa.Column("reviewed_by", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    for t in ("ml_voice_groups", "ml_embedding_vectors", "ml_voice_segments"):
        op.drop_table(t)
