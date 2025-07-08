# backend/tests/test_main.py
# Tests for the main FastAPI application.

from fastapi.testclient import TestClient

# Note: We don't need to import db_session or client here.
# Pytest automatically finds and uses the fixtures from conftest.py
# based on the function argument names.

def test_create_user(client: TestClient):
    """
    Test creating a new user successfully.
    """
    response = client.post(
        "/users/",
        json={"email": "test@example.com", "password": "testpassword"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "test@example.com"
    assert "id" in data
    # Ensure the password is not returned
    assert "hashed_password" not in data


def test_create_existing_user_fails(client: TestClient):
    """
    Test that creating a user with an already registered email fails.
    """
    # First, create a user
    client.post(
        "/users/",
        json={"email": "test@example.com", "password": "testpassword"},
    )
    # Then, try to create the same user again
    response = client.post(
        "/users/",
        json={"email": "test@example.com", "password": "testpassword"},
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "Email already registered"}


def test_login_for_access_token(client: TestClient):
    """
    Test logging in with correct credentials to get an access token.
    """
    # First, create a user to log in with
    client.post(
        "/users/",
        json={"email": "test@example.com", "password": "testpassword"},
    )
    # Now, log in
    response = client.post(
        "/token",
        data={"username": "test@example.com", "password": "testpassword"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_create_transaction_unauthorized(client: TestClient):
    """
    Test that creating a transaction fails if the user is not authenticated.
    """
    response = client.post(
        "/transactions/",
        json={
            "transaction_date": "2025-07-08",
            "beneficiary": "Test Shop",
            "amount": 12.34,
        },
    )
    # Should be 401 Unauthorized because we didn't provide a token
    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


def test_create_and_read_transaction_authorized(client: TestClient):
    """
    Test a full flow: create user, log in, create transaction, read transaction.
    """
    # 1. Create user
    client.post(
        "/users/",
        json={"email": "test@example.com", "password": "testpassword"},
    )

    # 2. Log in to get a token
    login_response = client.post(
        "/token",
        data={"username": "test@example.com", "password": "testpassword"},
    )
    token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 3. Create a transaction with the token
    transaction_data = {
        "transaction_date": "2025-07-08",
        "beneficiary": "Albert Heijn",
        "amount": 99.99,
        "category": "Groceries",
        "labels": ["food", "weekly"],
    }
    create_response = client.post(
        "/transactions/",
        json=transaction_data,
        headers=headers,
    )
    assert create_response.status_code == 200
    created_data = create_response.json()
    assert created_data["beneficiary"] == "Albert Heijn"
    assert created_data["amount"] == 99.99 # Pydantic handles the decimal conversion

    # 4. Read transactions to verify it was saved
    read_response = client.get("/transactions/", headers=headers)
    assert read_response.status_code == 200
    transactions = read_response.json()
    assert len(transactions) == 1
    assert transactions[0]["beneficiary"] == "Albert Heijn"

