from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, select

from database.connection import engine, SessionLocal
from database.models import Category
from utils.config import DATABASE_URL, PROJECT_ROOT

DEFAULT_EXPENSE_CATEGORIES = [
    "Food", "Groceries", "Transport", "Shopping", "Bills",
    "Entertainment", "Healthcare", "Education", "Travel",
    "Rent", "Personal Care", "Other",
]

BASELINE_REVISION = "0001_initial_schema"
_INITIALIZED = False


def _alembic_config() -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))
    return config


def _database_state() -> tuple[str | None, set[str]]:
    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
        tables = set(inspect(connection).get_table_names())
    return current, tables


def upgrade_database() -> None:
    """Apply migrations without recreating the database or dropping data.

    A legacy database created by the original ``create_all()`` has no
    ``alembic_version`` table. It is stamped at the baseline revision first,
    then only the additive multi-user revision is applied.
    """
    config = _alembic_config()
    current, tables = _database_state()

    if current is None and "expenses" in tables:
        command.stamp(config, BASELINE_REVISION)

    command.upgrade(config, "head")


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
    global _INITIALIZED
    if _INITIALIZED:
        return

    upgrade_database()
    seed_default_categories()
    _INITIALIZED = True


if __name__ == "__main__":
    initialize_database()
    print("Database migrated and default categories checked.")
