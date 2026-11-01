import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

import database.init_db as init_db


def test_initialize_database_creates_original_schema_and_categories(tmp_path, monkeypatch):
    database_path = tmp_path / "fresh-single-user.db"
    test_engine = create_engine(f"sqlite:///{database_path}")
    monkeypatch.setattr(init_db, "engine", test_engine)
    monkeypatch.setattr(
        init_db,
        "SessionLocal",
        sessionmaker(bind=test_engine, autoflush=False, autocommit=False),
    )

    init_db.initialize_database()

    tables = set(inspect(test_engine).get_table_names())
    assert {
        "categories",
        "expenses",
        "income",
        "budgets",
        "recurring_transactions",
        "agent_conversations",
    } <= tables
    assert "users" not in tables
    for table in ("expenses", "income", "agent_conversations"):
        assert "user_id" not in {
            column["name"] for column in inspect(test_engine).get_columns(table)
        }

    with init_db.SessionLocal() as db:
        category_names = {
            category.name for category in db.query(init_db.Category).all()
        }
    assert category_names == set(init_db.DEFAULT_EXPENSE_CATEGORIES)
    test_engine.dispose()


def test_initialize_database_refuses_multiuser_schema_without_modifying_it(
    tmp_path, monkeypatch
):
    database_path = tmp_path / "multi-user.db"
    test_engine = create_engine(f"sqlite:///{database_path}")
    with test_engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        connection.execute(
            text(
                "CREATE TABLE expenses (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL)"
            )
        )
        connection.execute(text("INSERT INTO users (id) VALUES (7)"))
        connection.execute(text("INSERT INTO expenses (id, user_id) VALUES (1, 7)"))

    monkeypatch.setattr(init_db, "engine", test_engine)

    with pytest.raises(RuntimeError, match="multi-user schema"):
        init_db.initialize_database()

    with test_engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM users")) == 1
        assert connection.scalar(text("SELECT user_id FROM expenses WHERE id = 1")) == 7
        assert connection.scalar(
            text("SELECT COUNT(*) FROM sqlite_master WHERE name = 'categories'")
        ) == 0
    test_engine.dispose()
