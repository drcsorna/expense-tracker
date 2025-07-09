# backend/models.py
# Database table definitions (SQLAlchemy) - Enhanced with staged data architecture

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Date,
    DateTime,
    Numeric,
    Boolean,
    JSON,
    ForeignKey,
    Text,
    Enum as SQLEnum,
)
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
import enum

# --- Database Setup ---
DATABASE_URL = "sqlite:///./database.db"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- Enums ---
class UploadStatus(enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    STAGED = "staged"
    CONFIRMED = "confirmed"
    FAILED = "failed"

class TransactionStatus(enum.Enum):
    STAGED = "staged"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"

# --- Database Models ---

class User(Base):
    """Represents a user in the database."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    preferences = Column(JSON, nullable=True)  # User preferences for categories, etc.

    # Relationships
    transactions = relationship("Transaction", back_populates="owner")
    staged_transactions = relationship("StagedTransaction", back_populates="owner")
    upload_sessions = relationship("UploadSession", back_populates="user")


class UploadSession(Base):
    """Tracks file upload sessions and their processing status."""
    __tablename__ = "upload_sessions"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    upload_date = Column(DateTime, default=datetime.utcnow)
    file_size = Column(Integer, nullable=False)
    file_type = Column(String, nullable=False)
    status = Column(SQLEnum(UploadStatus), default=UploadStatus.PENDING)
    
    # Processing results
    total_rows = Column(Integer, default=0)
    processed_rows = Column(Integer, default=0)
    staged_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    duplicate_count = Column(Integer, default=0)
    
    # Metadata
    processing_start = Column(DateTime, nullable=True)
    processing_end = Column(DateTime, nullable=True)
    raw_data = Column(JSON, nullable=True)  # Original file data for audit
    processing_log = Column(JSON, nullable=True)  # Detailed processing results
    format_detected = Column(String, nullable=True)
    
    # Foreign key
    user_id = Column(Integer, ForeignKey("users.id"))
    
    # Relationships
    user = relationship("User", back_populates="upload_sessions")
    staged_transactions = relationship("StagedTransaction", back_populates="upload_session")


class StagedTransaction(Base):
    """Parsed transactions awaiting user confirmation."""
    __tablename__ = "staged_transactions"

    id = Column(Integer, primary_key=True, index=True)
    
    # Core transaction data
    transaction_date = Column(Date, nullable=False)
    beneficiary = Column(String, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    category = Column(String, nullable=True)
    labels = Column(JSON, nullable=True)
    is_private = Column(Boolean, default=False)
    
    # Staging metadata
    status = Column(SQLEnum(TransactionStatus), default=TransactionStatus.STAGED)
    confidence_score = Column(Numeric(3, 2), default=1.0)  # AI confidence in parsing
    suggested_category = Column(String, nullable=True)
    suggested_labels = Column(JSON, nullable=True)
    notes = Column(Text, nullable=True)
    
    # Audit trail
    created_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime, nullable=True)
    raw_transaction_data = Column(JSON, nullable=True)  # Original row data
    
    # Foreign keys
    user_id = Column(Integer, ForeignKey("users.id"))
    upload_session_id = Column(Integer, ForeignKey("upload_sessions.id"))
    confirmed_transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)
    
    # Relationships
    owner = relationship("User", back_populates="staged_transactions")
    upload_session = relationship("UploadSession", back_populates="staged_transactions")
    confirmed_transaction = relationship("Transaction", foreign_keys=[confirmed_transaction_id])


class Transaction(Base):
    """Confirmed financial transactions - clean data."""
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    
    # Core transaction data
    transaction_date = Column(Date, nullable=False)
    beneficiary = Column(String, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    category = Column(String, nullable=True)
    labels = Column(JSON, nullable=True)
    is_private = Column(Boolean, default=False)
    
    # Enhanced categorization
    subcategory = Column(String, nullable=True)
    tags = Column(JSON, nullable=True)  # User-defined tags
    notes = Column(Text, nullable=True)
    
    # Split transaction support
    parent_transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)
    is_split = Column(Boolean, default=False)
    split_reason = Column(String, nullable=True)
    
    # Audit and tracking
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    confirmed_at = Column(DateTime, nullable=True)
    source_upload_session_id = Column(Integer, ForeignKey("upload_sessions.id"), nullable=True)
    
    # Legacy support
    raw_data = Column(JSON, nullable=True)  # For backward compatibility
    
    # Foreign keys
    owner_id = Column(Integer, ForeignKey("users.id"))
    
    # Relationships
    owner = relationship("User", back_populates="transactions")
    source_upload = relationship("UploadSession", foreign_keys=[source_upload_session_id])
    parent_transaction = relationship("Transaction", remote_side=[id], backref="split_transactions")


class Category(Base):
    """User-defined transaction categories."""
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    parent_category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    color = Column(String, nullable=True)  # Hex color code
    icon = Column(String, nullable=True)  # Icon identifier
    is_default = Column(Boolean, default=False)
    is_expense = Column(Boolean, default=True)  # True for expense, False for income
    
    # User association
    user_id = Column(Integer, ForeignKey("users.id"))
    
    # Audit
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user = relationship("User")
    parent_category = relationship("Category", remote_side=[id], backref="subcategories")


# --- Helper function to get a database session ---
def get_db():
    """Dependency function to get a database session for each request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- Utility functions ---
def create_default_categories(user_id: int, db):
    """Create default categories for a new user."""
    default_categories = [
        {"name": "Food & Dining", "color": "#FF6B6B", "icon": "🍽️", "is_expense": True},
        {"name": "Transportation", "color": "#4ECDC4", "icon": "🚗", "is_expense": True},
        {"name": "Shopping", "color": "#45B7D1", "icon": "🛍️", "is_expense": True},
        {"name": "Entertainment", "color": "#96CEB4", "icon": "🎬", "is_expense": True},
        {"name": "Bills & Utilities", "color": "#FECA57", "icon": "⚡", "is_expense": True},
        {"name": "Healthcare", "color": "#FF9FF3", "icon": "🏥", "is_expense": True},
        {"name": "Income", "color": "#26de81", "icon": "💰", "is_expense": False},
        {"name": "Transfer", "color": "#778beb", "icon": "↔️", "is_expense": False},
    ]
    
    for cat_data in default_categories:
        category = Category(user_id=user_id, is_default=True, **cat_data)
        db.add(category)
    
    db.commit()