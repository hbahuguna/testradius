"""add_featureflag_table

Revision ID: 23456789abcd
Revises: 58dcec3e4d4e
Create Date: 2026-05-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "23456789abcd"
down_revision: Union[str, Sequence[str], None] = "58dcec3e4d4e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "featureflag",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("flag_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"],),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "flag_name"),
    )
    op.create_index("ix_featureflag_project_flag", "featureflag", ["project_id", "flag_name"])


def downgrade() -> None:
    op.drop_index("ix_featureflag_project_flag")
    op.drop_table("featureflag")
