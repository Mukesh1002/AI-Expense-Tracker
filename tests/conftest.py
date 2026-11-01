import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.models import Base, Category, User
from database.init_db import DEFAULT_EXPENSE_CATEGORIES


def _make_user(session, *, sub: str, email: str, name: str) -> User:
    user = User(
        google_sub=sub,
        email=email,
        name=name,
        email_verified=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Match the application database: owner foreign keys are enforced.
    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSession()

    session.add_all([Category(name=n, type="EXPENSE") for n in DEFAULT_EXPENSE_CATEGORIES])
    session.commit()

    yield session
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def user(db_session):
    return _make_user(
        db_session,
        sub="test-google-sub",
        email="test@example.com",
        name="Test User",
    )


@pytest.fixture
def other_user(db_session):
    return _make_user(
        db_session,
        sub="other-google-sub",
        email="other@example.com",
        name="Other User",
    )
