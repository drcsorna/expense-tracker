# backend/tests/conftest.py
# Test configuration and fixtures for pytest

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Import our FastAPI app and database models/setup
from main import app, get_db
from models import Base

# --- Test Database Setup ---
# Use an in-memory SQLite database for testing. This is faster and ensures
# that tests are isolated and don't interfere with the main database.
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

# Create a session factory specifically for the test database.
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# --- Pytest Fixtures ---
# Fixtures are reusable setup/teardown functions for tests.

@pytest.fixture(scope="function")
def db_session():
    """
    Pytest fixture to create a new database session for each test function.
    It creates all tables, yields the session for the test to use,
    and then drops all tables after the test is complete.
    """
    # Create all tables in the test database
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        # Drop all tables to ensure a clean state for the next test
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    """
    Pytest fixture to provide a TestClient for making API requests.
    This fixture also overrides the `get_db` dependency to use our
    in-memory test database instead of the real one.
    """

    def override_get_db():
        """
        A dependency override that provides the test database session.
        """
        try:
            yield db_session
        finally:
            db_session.close()

    # Apply the override to our FastAPI app
    app.dependency_overrides[get_db] = override_get_db

    # Yield the TestClient for the test to use
    yield TestClient(app)

    # Clean up the override after the test
    app.dependency_overrides.clear()

