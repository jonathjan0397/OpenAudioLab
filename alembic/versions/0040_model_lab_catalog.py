"""Model Lab M2: catalog, claims, tag registry, lanes, provider cache

Revision ID: 0040
Revises: 0039
Create Date: 2026-10-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0040"
down_revision: Union[str, None] = "0039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LANES = [
    ("country_americana", "Country/Americana", "roots"),
    ("folk_acoustic", "Folk/Acoustic roots", "roots"),
    ("pop", "Pop", "popular"),
    ("rock", "Rock", "popular"),
    ("punk_alternative", "Punk/Alternative", "popular"),
    ("metal", "Metal", "popular"),
    ("blues", "Blues", "african_american"),
    ("jazz", "Jazz", "african_american"),
    ("rnb_soul", "R&B/Soul", "african_american"),
    ("funk_disco", "Funk/Disco", "african_american"),
    ("hiphop_rap", "Hip hop/Rap", "african_american"),
    ("electronic_club", "Electronic club music", "electronic"),
    ("ambient_downtempo", "Ambient/Downtempo", "electronic"),
    ("gospel_worship", "Gospel/Worship/Spiritual", "vocal_tradition"),
    ("classical_concert", "Classical/Concert music", "concert"),
    ("film_scoring", "Film/Game/Dramatic scoring", "concert"),
    ("reggae_ska", "Reggae/Ska/Dancehall", "caribbean"),
    ("latin_caribbean", "Latin/Caribbean traditions", "caribbean"),
    ("brazilian", "Brazilian traditions", "caribbean"),
    ("african", "African regional/contemporary", "regional"),
    ("south_asian", "South Asian traditions", "regional"),
    ("east_southeast_asian", "East/Southeast Asian traditions", "regional"),
    ("middle_east_north_africa", "Middle Eastern/North African", "regional"),
    ("musical_theatre", "Musical theatre/Ensemble vocals", "vocal_tradition"),
]


def upgrade() -> None:
    op.create_table(
        "ml_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, unique=True),
        sa.Column("kind", sa.String(20), nullable=False, server_default="directory"),
        sa.Column("path", sa.String(500), nullable=True),
        sa.Column("agreement_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="restricted"),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "ml_recordings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column("path", sa.String(700), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("sample_rate", sa.Integer(), nullable=True),
        sa.Column("channels", sa.Integer(), nullable=True),
        sa.Column("format", sa.String(20), nullable=True),
        sa.Column("probe_json", sa.JSON(), nullable=True),
        sa.Column("vocal_status", sa.String(12), nullable=False, server_default="unknown"),
        sa.Column("review_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("families_json", sa.JSON(), nullable=False),
        sa.Column("title", sa.String(300), nullable=True),
        sa.Column("artist", sa.String(300), nullable=True),
        sa.Column("genre_raw", sa.String(300), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("decade", sa.String(8), nullable=True),
        sa.Column("classification", sa.String(16), nullable=False, server_default="new"),
        sa.Column("identify_status", sa.String(24), nullable=False, server_default="unidentified"),
        sa.Column("review_status", sa.String(16), nullable=False, server_default="unreviewed"),
        sa.Column("dataset_eligible", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_id", "sha256", name="uq_ml_rec_source_sha"),
    )
    op.create_index("ix_ml_rec_source", "ml_recordings", ["source_id"])
    op.create_index("ix_ml_rec_sha", "ml_recordings", ["sha256"])
    op.create_table(
        "ml_import_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="running"),
        sa.Column("cursor_json", sa.JSON(), nullable=False),
        sa.Column("counts_json", sa.JSON(), nullable=False),
        sa.Column("scanned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.String(300), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_mlb_source", "ml_import_batches", ["source_id"])
    op.create_table(
        "ml_metadata_claims",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("recording_id", sa.String(36), nullable=False),
        sa.Column("field", sa.String(60), nullable=False),
        sa.Column("value", sa.String(500), nullable=False),
        sa.Column("provenance", sa.String(20), nullable=False),
        sa.Column("provider", sa.String(40), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("status", sa.String(12), nullable=False, server_default="suggested"),
        sa.Column("reviewed_by", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_mlc_recording", "ml_metadata_claims", ["recording_id"])
    op.create_table(
        "ml_tag_terms",
        sa.Column("id", sa.String(120), primary_key=True),
        sa.Column("namespace", sa.String(30), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("definition", sa.String(500), nullable=True),
        sa.Column("aliases_json", sa.JSON(), nullable=False),
        sa.Column("relations_json", sa.JSON(), nullable=False),
        sa.Column("caption_text", sa.String(200), nullable=True),
        sa.Column("visible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_mlt_namespace", "ml_tag_terms", ["namespace"])
    op.create_table(
        "ml_tag_assignments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("recording_id", sa.String(36), nullable=False),
        sa.Column("term_id", sa.String(120), nullable=False),
        sa.Column("level", sa.String(12), nullable=False, server_default="recording"),
        sa.Column("crop_start", sa.Float(), nullable=True),
        sa.Column("crop_end", sa.Float(), nullable=True),
        sa.Column("provenance", sa.String(20), nullable=False, server_default="curator"),
        sa.Column("confidence_basis", sa.String(120), nullable=True),
        sa.Column("status", sa.String(12), nullable=False, server_default="suggested"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_mla_recording", "ml_tag_assignments", ["recording_id"])
    op.create_index("ix_mla_term", "ml_tag_assignments", ["term_id"])
    op.create_table(
        "ml_lanes",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("group_name", sa.String(60), nullable=False),
        sa.Column("description", sa.String(300), nullable=True),
    )
    op.create_table(
        "ml_provider_cache",
        sa.Column("key", sa.String(200), primary_key=True),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("body_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_mpc_provider", "ml_provider_cache", ["provider"])
    lanes = sa.table("ml_lanes", sa.column("id", sa.String), sa.column("name", sa.String),
                     sa.column("group_name", sa.String))
    op.bulk_insert(lanes, [{"id": i, "name": n, "group_name": g} for i, n, g in LANES])


def downgrade() -> None:
    for t in ("ml_provider_cache", "ml_lanes", "ml_tag_assignments", "ml_tag_terms",
              "ml_metadata_claims", "ml_import_batches", "ml_recordings", "ml_sources"):
        op.drop_table(t)
