from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import Category, Expense
from utils.money import rupees_to_paise


def _get_category(db: Session, category_name: str) -> Category:
    category = db.scalar(
        select(Category).where(
            Category.name == category_name,
            Category.type == "EXPENSE",
            Category.is_active.is_(True),
        )
    )
    if category is None:
        raise ValueError(f"Unknown or inactive expense category: {category_name}")
    return category


def add_expense(
    db: Session,
    *,
    amount: str | int | float,
    description: str,
    category_name: str,
    expense_date: date,
    payment_method: str | None = None,
    notes: str | None = None,
    source: str = "MANUAL",
) -> Expense:
    description = description.strip()
    if not description:
        raise ValueError("Description is required.")

    category = _get_category(db, category_name)

    expense = Expense(
        amount_paise=rupees_to_paise(amount),
        description=description,
        category_id=category.id,
        expense_date=expense_date,
        payment_method=payment_method,
        notes=notes,
        source=source.upper(),
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense


def list_expenses(
    db: Session,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[Expense]:
    query = select(Expense).order_by(Expense.expense_date.desc(), Expense.id.desc())
    if start_date:
        query = query.where(Expense.expense_date >= start_date)
    if end_date:
        query = query.where(Expense.expense_date <= end_date)
    return list(db.scalars(query).all())


def delete_expense(db: Session, expense_id: int) -> bool:
    expense = db.get(Expense, expense_id)
    if expense is None:
        return False
    db.delete(expense)
    db.commit()
    return True


def update_expense(
    db: Session,
    expense_id: int,
    *,
    amount: str | int | float,
    description: str,
    category_name: str,
    expense_date: date,
    payment_method: str | None = None,
    notes: str | None = None,
) -> Expense:
    expense = db.get(Expense, expense_id)
    if expense is None:
        raise ValueError("Expense not found.")

    description = description.strip()
    if not description:
        raise ValueError("Description is required.")

    category = _get_category(db, category_name)

    expense.amount_paise = rupees_to_paise(amount)
    expense.description = description
    expense.category_id = category.id
    expense.expense_date = expense_date
    expense.payment_method = payment_method
    expense.notes = notes
    db.commit()
    db.refresh(expense)
    return expense
