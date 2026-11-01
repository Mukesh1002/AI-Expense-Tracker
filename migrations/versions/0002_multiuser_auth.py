"""Add Google OIDC users and nullable ownership columns.

This revision is additive only. Existing expenses, income and conversation
rows keep their data and receive NULL user_id values. No ownership backfill is
performed here; that is a separate reviewed migration.

Revision ID: 0002_multiuser_auth
Revises: 0001_initial_schema
Create Date: 2026-11-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_multiuser_auth"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_user_id(table_name: str) -> None:
    """Add a nullable owner column without rebuilding the table on SQLite.

    Alembic's SQLite dialect cannot ALTER constraints with op.add_column, and a
    batch rebuild risks dropping reflected CHECK constraints. SQLite supports
    an inline REFERENCES clause on ADD COLUMN, which preserves all existing
    data, indexes and constraints.
    """
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute(
            f"ALTER TABLE {table_name} ADD COLUMN user_id INTEGER "
            "REFERENCES users (id) ON DELETE SET NULL"
        )
    else:
        op.add_column(
            table_name,
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    op.create_index(f"ix_{table_name}_user_id", table_name, ["user_id"])


def _drop_user_id(table_name: str) -> None:
    op.drop_index(f"ix_{table_name}_user_id", table_name=table_name)
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute(f"ALTER TABLE {table_name} DROP COLUMN user_id")
    else:
        op.drop_column(table_name, "user_id")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("google_sub", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("given_name", sa.String(length=255), nullable=True),
        sa.Column("family_name", sa.String(length=255), nullable=True),
        sa.Column("picture_url", sa.String(length=1024), nullable=True),
        sa.Column("locale", sa.String(length=20), nullable=True),
        sa.Column("email_verified", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("google_sub", name="uq_users_google_sub"),
    )

    _add_user_id("expenses")
    _add_user_id("income")
    _add_user_id("agent_conversations")


def downgrade() -> None:
    _drop_user_id("agent_conversations")
    _drop_user_id("income")
    _drop_user_id("expenses")
    op.drop_table("users")
