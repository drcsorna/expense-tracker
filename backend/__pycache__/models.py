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