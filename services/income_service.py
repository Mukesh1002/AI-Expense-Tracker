from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import Income
from services.user_service import require_user, validate_user_id
from utils.money import rupees_to_paise


def add_income(
    db: Session,
    *,
    amount: str | int | float,
    source: str,
    income_date: date,
    user_id: int,
    notes: str | None = None,
) -> Income:
    user_id = require_user(db, user_id)

    source = source.strip()
    if not source:
        raise ValueError("Income source is required.")

    income = Income(
        amount_paise=rupees_to_paise(amount),
        source=source,
        income_date=income_date,
        notes=notes,
        user_id=user_id,
    )
    db.add(income)
    db.commit()
    db.refresh(income)
    return income


def list_incomes(
    db: Session,
    *,
    user_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[Income]:
    user_id = validate_user_id(user_id)
    query = (
        select(Income)
        .where(Income.user_id == user_id)
        .order_by(Income.income_date.desc(), Income.id.desc())
    )
    if start_date:
        query = query.where(Income.income_date >= start_date)
    if end_date:
        query = query.where(Income.income_date <= end_date)
    return list(db.scalars(query).all())


def update_income(
    db: Session,
    income_id: int,
    *,
    user_id: int,
    amount: str | int | float,
    source: str,
    income_date: date,
    notes: str | None = None,
) -> Income:
    user_id = validate_user_id(user_id)
    income = db.scalar(
        select(Income).where(
            Income.id == income_id,
            Income.user_id == user_id,
        )
    )
    if income is None:
        raise ValueError("Income record not found.")

    source = source.strip()
    if not source:
        raise ValueError("Income source is required.")

    income.amount_paise = rupees_to_paise(amount)
    income.source = source
    income.income_date = income_date
    income.notes = notes
    db.commit()
    db.refresh(income)
    return income
