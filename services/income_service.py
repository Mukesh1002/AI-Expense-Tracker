from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import Income
from utils.money import rupees_to_paise


def add_income(
    db: Session,
    *,
    amount: str | int | float,
    source: str,
    income_date: date,
    notes: str | None = None,
) -> Income:
    source = source.strip()
    if not source:
        raise ValueError("Income source is required.")

    income = Income(
        amount_paise=rupees_to_paise(amount),
        source=source,
        income_date=income_date,
        notes=notes,
    )
    db.add(income)
    db.commit()
    db.refresh(income)
    return income


def list_incomes(
    db: Session,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[Income]:
    query = select(Income).order_by(Income.income_date.desc(), Income.id.desc())
    if start_date:
        query = query.where(Income.income_date >= start_date)
    if end_date:
        query = query.where(Income.income_date <= end_date)
    return list(db.scalars(query).all())


def update_income(
    db: Session,
    income_id: int,
    *,
    amount: str | int | float,
    source: str,
    income_date: date,
    notes: str | None = None,
) -> Income:
    income = db.get(Income, income_id)
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


def delete_income(db: Session, income_id: int) -> bool:
    income = db.get(Income, income_id)
    if income is None:
        return False
    db.delete(income)
    db.commit()
    return True
