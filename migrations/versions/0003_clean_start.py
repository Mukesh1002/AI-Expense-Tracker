"""Clean start: remove legacy financial data and require an owner.

This revision deletes every expense, income and AI conversation row, keeps the
reusable category and user tables, and makes ``user_id`` non-nullable. It does
not backfill ownership and does not assign legacy rows to any user.

Because a non-nullable owner cannot be set to NULL, the owner foreign keys are
recreated with ``ON DELETE CASCADE``: deleting a user removes that user's
financial records. The existing category foreign keys and all indexes are kept.

The downgrade only relaxes the NOT NULL constraint and restores the original
``ON DELETE SET NULL`` owner action; deleted rows cannot be restored from this
migration.

Revision ID: 0003_clean_start
Revises: 0002_multiuser_auth
Create Date: 2026-11-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_clean_start"
down_revision: Union[str, None] = "0002_multiuser_auth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OWNED_TABLES = ("expenses", "income", "agent_conversations")


def _expenses_table(ondelete: str) -> sa.Table:
    return sa.Table(
        "expenses",
        sa.MetaData(),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("amount_paise", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=250), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("payment_method", sa.String(length=40), nullable=True),
        sa.Column("expense_date", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
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
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("amount_paise > 0", name="ck_expense_amount_positive"),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete=ondelete),
        sa.Index("ix_expenses_expense_date", "expense_date"),
        sa.Index("ix_expenses_category_date", "category_id", "expense_date"),
        sa.Index("ix_expenses_user_id", "user_id"),
    )


def _income_table(ondelete: str) -> sa.Table:
    return sa.Table(
        "income",
        sa.MetaData(),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("amount_paise", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("income_date", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("amount_paise > 0", name="ck_income_amount_positive"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete=ondelete),
        sa.Index("ix_income_income_date", "income_date"),
        sa.Index("ix_income_user_id", "user_id"),
    )


def _conversations_table(ondelete: str) -> sa.Table:
    return sa.Table(
        "agent_conversations",
        sa.MetaData(),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=100), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete=ondelete),
        sa.Index("ix_agent_conversations_session", "session_id"),
        sa.Index("ix_agent_conversations_user_id", "user_id"),
    )


TABLES = {
    "expenses": _expenses_table,
    "income": _income_table,
    "agent_conversations": _conversations_table,
}


def _replace_owner_foreign_key(table_name: str, ondelete: str) -> None:
    """Drop and recreate the user_id FK for non-SQLite databases."""
    bind = op.get_bind()
    for fk in sa.inspect(bind).get_foreign_keys(table_name):
        if fk.get("constrained_columns") == ["user_id"]:
            if fk.get("name"):
                op.drop_constraint(fk["name"], table_name, type_="foreignkey")
            break
    op.create_foreign_key(
        f"fk_{table_name}_user_id",
        table_name,
        "users",
        ["user_id"],
        ["id"],
        ondelete=ondelete,
    )


def _rebuild_with_owner_constraint(nullable: bool, ondelete: str) -> None:
    bind = op.get_bind()
    for table_name in OWNED_TABLES:
        table = TABLES[table_name](ondelete)
        if bind.dialect.name == "sqlite":
            # SQLite cannot ALTER COLUMN directly. Batch mode rebuilds the
            # table from the explicit definition above, preserving the CHECK
            # constraints, foreign keys and indexes. The tables are empty
            # after the cleanup below.
            with op.batch_alter_table(table_name, copy_from=table) as batch:
                batch.alter_column(
                    "user_id",
                    existing_type=sa.Integer(),
                    existing_nullable=not nullable,
                    nullable=nullable,
                )
        else:
            _replace_owner_foreign_key(table_name, ondelete)
            op.alter_column(
                table_name,
                "user_id",
                existing_type=sa.Integer(),
                existing_nullable=not nullable,
                nullable=nullable,
            )


def upgrade() -> None:
    # Delete child financial records first, then chat history. Categories and
    # users are intentionally untouched.
    op.execute("DELETE FROM expenses")
    op.execute("DELETE FROM income")
    op.execute("DELETE FROM agent_conversations")

    _rebuild_with_owner_constraint(nullable=False, ondelete="CASCADE")


def downgrade() -> None:
    _rebuild_with_owner_constraint(nullable=True, ondelete="SET NULL")
