#!/bin/bash

# WARNING: This script is DESTRUCTIVE.
# It will delete all files and folders in the directory where it is run,
# except for the script file itself (if named 'setup.sh').

# --- Safety Confirmation ---
echo "⚠️  WARNING: This will DELETE all files and folders in the current directory."
echo "   The script will operate in: $(pwd)"
read -p "   Are you absolutely sure you want to continue? (y/n) " -n 1 -r
echo # Move to a new line

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted by user."
    exit 1
fi

# --- Cleanup Current Directory ---
echo "🧹 Cleaning current directory..."
for item in *; do
    if [ "$item" != "setup.sh" ]; then
        echo "   Removing: $item"
        rm -rf "$item"
    fi
done
echo "✅  Directory cleaned."

# --- Backend Directory Structure (FastAPI) ---
echo "Creating backend directory and files..."
mkdir -p backend
mkdir -p backend/tests

# Create empty files
touch backend/main.py
echo "# Main FastAPI app instance and API routes" > backend/main.py

touch backend/schemas.py
echo "# Data validation schemas (Pydantic)" > backend/schemas.py

touch backend/tests/__init__.py
touch backend/tests/conftest.py
echo "# Test configuration and fixtures" > backend/tests/conftest.py
touch backend/tests/test_main.py
echo "# Example test file" > backend/tests/test_main.py

# Create requirements.txt with testing libraries
echo "fastapi
uvicorn[standard]
sqlalchemy
python-jose[cryptography]
passlib[bcrypt]
python-multipart
pytest
requests" > backend/requirements.txt

# Create models.py with the full content
echo "📝 Populating backend/models.py..."
cat <<EOF > backend/models.py
# backend/models.py
# Database table definitions (SQLAlchemy)

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Date,
    Numeric,
    Boolean,
    JSON,
    ForeignKey,
)
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.ext.declarative import declarative_base

# --- Database Setup ---
# Define the local SQLite database file.
DATABASE_URL = "sqlite:///./database.db"

# Create the SQLAlchemy engine.
# connect_args is needed only for SQLite to allow multi-threaded access.
engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)

# Create a session factory to manage database sessions.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for our declarative models.
Base = declarative_base()


# --- Database Models ---

class User(Base):
    """
    Represents a user in the database.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)

    # This creates a one-to-many relationship.
    # One user can have many transactions.
    transactions = relationship("Transaction", back_populates="owner")


class Transaction(Base):
    """
    Represents a single financial transaction in the database.
    """
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    transaction_date = Column(Date, nullable=False)
    beneficiary = Column(String, nullable=False)
    # Using Numeric for precise decimal storage, essential for currency.
    amount = Column(Numeric(10, 2), nullable=False)
    category = Column(String, nullable=True)
    # Using JSON to store an array of text labels.
    labels = Column(JSON, nullable=True)
    is_private = Column(Boolean, default=False)
    # Storing the original CSV row for auditing and debugging.
    raw_data = Column(JSON, nullable=True)

    # Foreign key to link this transaction to a user.
    owner_id = Column(Integer, ForeignKey("users.id"))

    # This creates the other side of the one-to-many relationship.
    owner = relationship("User", back_populates="transactions")


# --- Helper function to get a database session ---
def get_db():
    """
    Dependency function to get a database session for each request.
    Ensures the session is always closed after the request is finished.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
EOF

# --- Frontend Directory Structure (Next.js) ---
echo "Creating frontend directory..."
mkdir -p frontend

echo ""
echo "✅ Project structure created successfully in the current directory!"
echo ""
echo "Next steps:"
echo "1. Navigate into the backend folder to set up the Python environment:"
echo "   cd backend"
echo "   uv venv"
echo "   source .venv/bin/activate  # (or .venv\Scripts\activate on Windows CMD)"
echo "   uv pip install -r requirements.txt"
echo ""
echo "2. Navigate into the frontend folder to create the Next.js app:"
echo "   cd ../frontend"
echo "   npx create-next-app@latest . -ts --tailwind --eslint"
echo ""
