"""Initial local project store."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    tables = {
        "projects": [("name", sa.String(), False), ("created_at", sa.String(), False)],
        "recordings": [
            ("project_id", sa.String(), False),
            ("filename", sa.String(), False),
            ("sha256", sa.String(), False),
            ("original_path", sa.String(), False),
            ("metadata_json", sa.JSON(), False),
            ("current_run_id", sa.String(), True),
            ("revision", sa.Integer(), False),
            ("created_at", sa.String(), False),
        ],
        "runs": [
            ("recording_id", sa.String(), False),
            ("mode", sa.String(), False),
            ("language", sa.String(), False),
            ("kind", sa.String(), False),
            ("status", sa.String(), False),
            ("stage", sa.String(), False),
            ("progress", sa.Float(), False),
            ("error", sa.String(), True),
            ("settings", sa.JSON(), False),
            ("raw_rows", sa.JSON(), False),
            ("details", sa.JSON(), False),
            ("created_at", sa.String(), False),
            ("updated_at", sa.String(), False),
        ],
        "speakers": [
            ("project_id", sa.String(), False),
            ("name", sa.String(), False),
            ("notes", sa.String(), False),
        ],
        "samples": [
            ("speaker_id", sa.String(), False),
            ("recording_id", sa.String(), False),
            ("start_ms", sa.Integer(), False),
            ("end_ms", sa.Integer(), False),
            ("embedding", sa.JSON(), False),
            ("model_revision", sa.String(), True),
            ("confirmed", sa.Boolean(), False),
        ],
        "corrections": [
            ("recording_id", sa.String(), False),
            ("revision", sa.Integer(), False),
            ("actions", sa.JSON(), False),
            ("active", sa.Boolean(), False),
            ("explanation", sa.String(), False),
            ("created_at", sa.String(), False),
        ],
        "proposals": [
            ("recording_id", sa.String(), False),
            ("base_revision", sa.Integer(), False),
            ("actions", sa.JSON(), False),
            ("explanation", sa.String(), False),
            ("clarification", sa.String(), True),
            ("applied", sa.Boolean(), False),
            ("created_at", sa.String(), False),
        ],
    }
    for name, columns in tables.items():
        op.create_table(
            name,
            sa.Column("id", sa.String(), primary_key=True),
            *[sa.Column(column, kind, nullable=nullable) for column, kind, nullable in columns],
        )
    for table, column in (
        ("recordings", "project_id"),
        ("runs", "recording_id"),
        ("speakers", "project_id"),
        ("samples", "speaker_id"),
        ("samples", "recording_id"),
        ("corrections", "recording_id"),
        ("proposals", "recording_id"),
    ):
        op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade():
    for table in ("proposals", "corrections", "samples", "speakers", "runs", "recordings", "projects"):
        op.drop_table(table)
