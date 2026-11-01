"""Baseline schema created by the original single-user application.

This revision exists so existing databases can be stamped at the baseline and
then upgraded. New databases get the same schema from this migration.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "type", name="uq_category_name_type"),
    )

    op.create_table(
        "expenses",
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
        sa.CheckConstraint("amount_paise > 0", name="ck_expense_amount_positive"),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_expenses_expense_date", "expenses", ["expense_date"])
    op.create_index(
        "ix_expenses_category_date", "expenses", ["category_id", "expense_date"]
    )

    op.create_table(
        "income",
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
        sa.CheckConstraint("amount_paise > 0", name="ck_income_amount_positive"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_income_income_date", "income", ["income_date"])

    op.create_table(
        "budgets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("monthly_limit_paise", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "monthly_limit_paise > 0", name="ck_budget_limit_positive"
        ),
        sa.CheckConstraint("month >= 1 AND month <= 12", name="ck_budget_month_valid"),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "category_id", "month", "year", name="uq_budget_category_month_year"
        ),
    )

    op.create_table(
        "recurring_transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=250), nullable=False),
        sa.Column("amount_paise", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("frequency", sa.String(length=20), nullable=False),
        sa.Column("next_due_date", sa.Date(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.CheckConstraint("amount_paise > 0", name="ck_recurring_amount_positive"),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "agent_conversations",
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_conversations_session", "agent_conversations", ["session_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_agent_conversations_session", table_name="agent_conversations")
    op.drop_table("agent_conversations")
    op.drop_table("recurring_transactions")
    op.drop_table("budgets")
    op.drop_index("ix_income_income_date", table_name="income")
    op.drop_table("income")
    op.drop_index("ix_expenses_category_date", table_name="expenses")
    op.drop_index("ix_expenses_expense_date", table_name="expenses")
    op.drop_table("expenses")
    op.drop_table("categories")
