# backend/models.py
# Complete database models implementing 3-stage workflow + bootstrap

from sqlalchemy import (
    create_engine, Column, Integer, String, Date, Numeric, Boolean, JSON, 
    ForeignKey, DateTime, Text, Float, UniqueConstraint, Index, LargeBinary, Enum
)
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
from enum import Enum as PyEnum
import sqlalchemy as sa

# Database Setup
DATABASE_URL = "sqlite:///./database.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Dependency function
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ===== ENUMS =====

class FileType(PyEnum):
    TRANSACTION_DATA = "transaction_data"
    TRAINING_DATA = "training_data"
    UNKNOWN = "unknown"

class ProcessingStatus(PyEnum):
    RAW = "raw"
    ANALYZING = "analyzing"
    READY_TO_PROCESS = "ready_to_process"
    PROCESSING = "processing"
    PROCESSED = "processed"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class TransactionStatus(PyEnum):
    STAGED = "staged"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"

class DuplicateStatus(PyEnum):
    PENDING = "pending"
    RESOLVED = "resolved"
    IGNORED = "ignored"

class ConfidenceLevel(PyEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"

# ===== CORE USER MODEL =====

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    
    # Profile fields
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    
    # User preferences and settings
    preferences = Column(JSON, default={})
    
    # Relationships
    transactions = relationship("Transaction", back_populates="owner")
    staged_transactions = relationship("StagedTransaction", back_populates="user")
    categories = relationship("Category", back_populates="user")
    raw_files = relationship("RawFile", back_populates="user")
    processing_sessions = relationship("ProcessingSession", back_populates="user")
    duplicate_groups = relationship("DuplicateGroup", back_populates="user")

# ===== STAGE 1: RAW STORAGE =====

class RawFile(Base):
    """Stage 1: Immutable raw file storage"""
    __tablename__ = "raw_files"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    original_filename = Column(String, nullable=False)
    file_content = Column(LargeBinary, nullable=False)
    file_size = Column(Integer, nullable=False)
    file_type = Column(String, nullable=False)  # .csv, .xlsx, etc
    content_hash = Column(String, nullable=False, unique=True)
    
    # Classification
    detected_file_type = Column(Enum(FileType), default=FileType.UNKNOWN)
    upload_date = Column(DateTime, default=datetime.utcnow)
    
    # Schema detection (no processing yet)
    detected_columns = Column(JSON, nullable=True)
    estimated_rows = Column(Integer, nullable=True)
    sample_data = Column(JSON, nullable=True)
    encoding_detected = Column(String, default='utf-8')
    delimiter_detected = Column(String, nullable=True)
    
    # Metadata
    upload_ip = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    processing_notes = Column(JSON, default=[])
    
    # Relationships
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user = relationship("User", back_populates="raw_files")
    processing_sessions = relationship("ProcessingSession", back_populates="raw_file")

# ===== STAGE 2: PROCESSING =====

class ProcessingSession(Base):
    """Processing configuration and session management"""
    __tablename__ = "processing_sessions"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, unique=True, index=True, nullable=False)
    
    # Processing configuration
    configuration = Column(JSON, nullable=False)  # Column mapping, etc.
    status = Column(Enum(ProcessingStatus), default=ProcessingStatus.RAW)
    
    # Progress tracking
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    total_rows = Column(Integer, nullable=True)
    rows_processed = Column(Integer, default=0)
    rows_with_suggestions = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    
    # Relationships
    raw_file_id = Column(Integer, ForeignKey("raw_files.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    raw_file = relationship("RawFile", back_populates="processing_sessions")
    user = relationship("User", back_populates="processing_sessions")
    staged_transactions = relationship("StagedTransaction", back_populates="processing_session")

# ===== STAGE 3: STAGED TRANSACTIONS =====

class StagedTransaction(Base):
    """Stage 3: Processed transactions awaiting user confirmation"""
    __tablename__ = "staged_transactions"

    id = Column(Integer, primary_key=True, index=True)
    
    # Core transaction data
    transaction_date = Column(Date, nullable=False)
    beneficiary = Column(String, nullable=False)
    amount = Column(Numeric(precision=12, scale=2), nullable=False)
    
    # ML suggestions
    suggested_category = Column(String, nullable=True)
    confidence_score = Column(Numeric(precision=3, scale=2), default=0.0)
    
    # Additional fields
    notes = Column(Text, nullable=True)
    labels = Column(JSON, default=[])
    is_private = Column(Boolean, default=False)
    
    # Processing metadata
    status = Column(Enum(TransactionStatus), default=TransactionStatus.STAGED)
    raw_transaction_data = Column(JSON, nullable=True)  # Original row data
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    confirmed_at = Column(DateTime, nullable=True)
    
    # Relationships
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    processing_session_id = Column(Integer, ForeignKey("processing_sessions.id"), nullable=True)
    
    user = relationship("User", back_populates="staged_transactions")
    processing_session = relationship("ProcessingSession", back_populates="staged_transactions")

# ===== CONFIRMED TRANSACTIONS =====

class Transaction(Base):
    """Final confirmed transactions"""
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    
    # Core fields
    transaction_date = Column(Date, nullable=False, index=True)
    beneficiary = Column(String, nullable=False, index=True)
    amount = Column(Numeric(precision=12, scale=2), nullable=False)
    
    # Categorization
    category = Column(String, nullable=True, index=True)
    subcategory = Column(String, nullable=True)
    
    # Additional data
    labels = Column(JSON, default=[])
    tags = Column(JSON, default=[])
    notes = Column(Text, nullable=True)
    is_private = Column(Boolean, default=False)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    owner = relationship("User", back_populates="transactions")
    
    # Indexes
    __table_args__ = (
        Index('idx_transactions_date_owner', 'transaction_date', 'owner_id'),
        Index('idx_transactions_category_owner', 'category', 'owner_id'),
        Index('idx_transactions_amount', 'amount'),
    )

# ===== CATEGORIES =====

class Category(Base):
    """User-defined categories"""
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    
    # Visual properties
    color = Column(String, default="#007bff")
    icon = Column(String, default="📊")
    description = Column(Text, nullable=True)
    
    # Categorization aids
    keywords = Column(JSON, default=[])  # Keywords for auto-categorization
    confidence_score = Column(Float, default=0.0)  # ML confidence
    
    # Hierarchy
    parent_category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user = relationship("User", back_populates="categories")
    parent = relationship("Category", remote_side=[id])

# ===== TRAINING DATA & BOOTSTRAP =====

class TrainingDataset(Base):
    """Training data for ML categorization"""
    __tablename__ = "training_datasets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    source_file_id = Column(Integer, ForeignKey("raw_files.id"), nullable=True)
    
    # Training metrics
    total_patterns = Column(Integer, default=0)
    merchant_patterns = Column(Integer, default=0)
    category_mappings = Column(Integer, default=0)
    confidence_score = Column(Float, default=0.0)
    
    # Metadata
    created_date = Column(DateTime, default=datetime.utcnow)
    last_updated = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    language = Column(String, default='en')
    
    # Relationships
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    patterns = relationship("TrainingPattern", back_populates="dataset")

class TrainingPattern(Base):
    """Individual patterns extracted from training data"""
    __tablename__ = "training_patterns"

    id = Column(Integer, primary_key=True, index=True)
    
    # Pattern data
    pattern_type = Column(String, nullable=False)  # 'merchant', 'keyword', 'amount_range'
    pattern_value = Column(String, nullable=False)  # The actual pattern
    category_original = Column(String, nullable=False)  # Original category (e.g., Hungarian)
    category_mapped = Column(String, nullable=False)   # Mapped category (e.g., English)
    
    # Quality metrics
    confidence = Column(Float, default=0.0)
    occurrences = Column(Integer, default=1)
    
    # Relationships
    dataset_id = Column(Integer, ForeignKey("training_datasets.id"), nullable=False)
    dataset = relationship("TrainingDataset", back_populates="patterns")

# ===== DUPLICATE DETECTION =====

class DuplicateGroup(Base):
    """Groups of potentially duplicate transactions"""
    __tablename__ = "duplicate_groups"

    id = Column(Integer, primary_key=True, index=True)
    
    # Detection metadata
    detection_method = Column(String, nullable=False)  # 'exact', 'fuzzy', 'amount_date'
    confidence_score = Column(Float, nullable=False)
    status = Column(Enum(DuplicateStatus), default=DuplicateStatus.PENDING)
    
    # Resolution
    resolved_at = Column(DateTime, nullable=True)
    resolution_action = Column(String, nullable=True)  # 'keep_primary', 'keep_all', 'delete_all'
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user = relationship("User", back_populates="duplicate_groups")
    entries = relationship("DuplicateEntry", back_populates="group")

class DuplicateEntry(Base):
    """Individual transactions within a duplicate group"""
    __tablename__ = "duplicate_entries"

    id = Column(Integer, primary_key=True, index=True)
    
    # Group membership
    is_primary = Column(Boolean, default=False)  # The transaction to keep
    confidence_score = Column(Float, nullable=False)
    
    # Relationships
    group_id = Column(Integer, ForeignKey("duplicate_groups.id"), nullable=False)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False)
    
    group = relationship("DuplicateGroup", back_populates="entries")
    transaction = relationship("Transaction")

# ===== CREATE TABLES =====

def create_tables():
    """Create all database tables."""
    try:
        Base.metadata.create_all(bind=engine)
        print("✅ Database tables created successfully")
    except Exception as e:
        print(f"❌ Error creating tables: {e}")

# ===== DEFAULT DATA CREATION =====

async def create_default_categories(db, user_id: int):
    """Create default categories for a new user."""
    
    default_categories = [
        {"name": "Food & Beverage", "color": "#e74c3c", "icon": "🍽️"},
        {"name": "Shopping", "color": "#3498db", "icon": "🛍️"},
        {"name": "Transportation", "color": "#9b59b6", "icon": "🚗"},
        {"name": "Entertainment", "color": "#f39c12", "icon": "🎬"},
        {"name": "Healthcare", "color": "#27ae60", "icon": "🏥"},
        {"name": "Bills & Utilities", "color": "#34495e", "icon": "📄"},
        {"name": "Education", "color": "#16a085", "icon": "📚"},
        {"name": "Travel", "color": "#e67e22", "icon": "✈️"},
        {"name": "Business", "color": "#2c3e50", "icon": "💼"},
        {"name": "Other", "color": "#95a5a6", "icon": "📝"}
    ]
    
    try:
        for cat_data in default_categories:
            # Check if category already exists
            existing = db.query(Category).filter(
                Category.user_id == user_id,
                Category.name == cat_data["name"]
            ).first()
            
            if not existing:
                category = Category(
                    name=cat_data["name"],
                    color=cat_data["color"],
                    icon=cat_data["icon"],
                    user_id=user_id
                )
                db.add(category)
        
        db.commit()
        print(f"✅ Default categories created for user {user_id}")
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error creating default categories: {e}")

# ===== UTILITY FUNCTIONS =====

def get_user_by_email(db, email: str):
    """Get user by email address."""
    return db.query(User).filter(User.email == email).first()

def get_user_transactions(db, user_id: int, limit: int = 50, offset: int = 0):
    """Get user's transactions with pagination."""
    return db.query(Transaction).filter(
        Transaction.owner_id == user_id
    ).order_by(Transaction.transaction_date.desc()).offset(offset).limit(limit).all()

def get_staged_transactions(db, user_id: int, limit: int = 50, offset: int = 0):
    """Get user's staged transactions."""
    return db.query(StagedTransaction).filter(
        StagedTransaction.user_id == user_id,
        StagedTransaction.status == TransactionStatus.STAGED
    ).order_by(StagedTransaction.created_at.desc()).offset(offset).limit(limit).all()

# Make sure tables are created when module is imported
if __name__ == "__main__":
    create_tables()