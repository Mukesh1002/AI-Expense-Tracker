from datetime import date, datetime
from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index,
    Integer, String, Text, UniqueConstraint, func
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("name", "type", name="uq_category_name_type"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="EXPENSE")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    expenses: Mapped[list["Expense"]] = relationship(back_populates="category")
    budgets: Mapped[list["Budget"]] = relationship(back_populates="category")

class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        CheckConstraint("amount_paise > 0", name="ck_expense_amount_positive"),
        Index("ix_expenses_expense_date", "expense_date"),
        Index("ix_expenses_category_date", "category_id", "expense_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(250), nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    payment_method: Mapped[str | None] = mapped_column(String(40), nullable=True)
    expense_date: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="MANUAL")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    category: Mapped[Category] = relationship(back_populates="expenses")

class Income(Base):
    __tablename__ = "income"
    __table_args__ = (
        CheckConstraint("amount_paise > 0", name="ck_income_amount_positive"),
        Index("ix_income_income_date", "income_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    income_date: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (
        CheckConstraint("monthly_limit_paise > 0", name="ck_budget_limit_positive"),
        CheckConstraint("month >= 1 AND month <= 12", name="ck_budget_month_valid"),
        UniqueConstraint("category_id", "month", "year", name="uq_budget_category_month_year"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    monthly_limit_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)

    category: Mapped[Category] = relationship(back_populates="budgets")

class RecurringTransaction(Base):
    __tablename__ = "recurring_transactions"
    __table_args__ = (CheckConstraint("amount_paise > 0", name="ck_recurring_amount_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    description: Mapped[str] = mapped_column(String(250), nullable=False)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    frequency: Mapped[str] = mapped_column(String(20), nullable=False, default="MONTHLY")
    next_due_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

class AgentConversation(Base):
    __tablename__ = "agent_conversations"
    __table_args__ = (Index("ix_agent_conversations_session", "session_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
