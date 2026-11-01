from sqlalchemy import inspect, select

from database.connection import SessionLocal, engine
from database.models import Base, Category

DEFAULT_EXPENSE_CATEGORIES = [
    "Food", "Groceries", "Transport", "Shopping", "Bills",
    "Entertainment", "Healthcare", "Education", "Travel",
    "Rent", "Personal Care", "Other",
]


def _reject_multiuser_database() -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    owner_tables = {"expenses", "income", "agent_conversations"}
    if "users" in tables or any(
        "user_id" in {column["name"] for column in inspector.get_columns(table)}
        for table in owner_tables.intersection(tables)
    ):
        raise RuntimeError(
            "This database uses the Google-authenticated multi-user schema and "
            "cannot be used by the single-user application. Set DATABASE_URL to "
            "a new single-user SQLite database; the existing database was not changed."
        )


def seed_default_categories() -> None:
    with SessionLocal() as db:
        for name in DEFAULT_EXPENSE_CATEGORIES:
            existing = db.scalar(
                select(Category).where(
                    Category.name == name,
                    Category.type == "EXPENSE",
                )
            )
            if existing is None:
                db.add(Category(name=name, type="EXPENSE", is_active=True))
        db.commit()


def initialize_database() -> None:
    _reject_multiuser_database()
    Base.metadata.create_all(engine)
    seed_default_categories()


if __name__ == "__main__":
    initialize_database()
    print("Database initialized and default categories checked.")
