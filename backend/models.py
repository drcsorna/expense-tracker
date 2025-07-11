# backend/models.py
# Enhanced database models implementing 3-stage workflow:
# 1. Raw Storage (immutable)
# 2. Training Data + Processing 
# 3. Confirmed Transactions

from sqlalchemy import (
    create_engine, Column, Integer, String, Date, Numeric, Boolean, JSON, 
    ForeignKey, DateTime, Text, Float, UniqueConstraint, Index, LargeBinary
)
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
from enum import Enum
import sqlalchemy as sa

# Database Setup
DATABASE_URL = "sqlite:///./database.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Enhanced Enums
class FileType(Enum):
    TRANSACTION_DATA = "transaction_data"
    TRAINING_DATA = "training_data"
    UNKNOWN = "unknown"

class ProcessingStatus(Enum):
    RAW = "raw"                    # Just uploaded, not processed
    ANALYZING = "analyzing"        # Schema detection in progress
    READY_TO_PROCESS = "ready_to_process"  # Schema detected, waiting for user confirmation
    PROCESSING = "processing"      # Converting to structured data
    PROCESSED = "processed"        # Available for review
    CONFIRMED = "confirmed"        # User approved
    FAILED = "failed"
    CANCELLED = "cancelled"

class ConfidenceLevel(Enum):
    LOW = "low"          # 0-40%
    MEDIUM = "medium"    # 41-70%
    HIGH = "high"        # 71-90%
    VERY_HIGH = "very_high"  # 91-100%

# === STAGE 1: RAW STORAGE (Immutable) ===

class RawFile(Base):
    """
    Stage 1: Immutable raw file storage
    Stores ANY file structure exactly as uploaded
    """
    __tablename__ = "raw_files"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    original_filename = Column(String, nullable=False)
    file_content = Column(LargeBinary, nullable=False)  # Store actual file
    file_size = Column(Integer, nullable=False)
    file_type = Column(String, nullable=False)  # .csv, .xlsx, etc
    content_hash = Column(String, nullable=False, unique=True)  # Prevent duplicates
    
    # File classification
    detected_file_type = Column(sa.Enum(FileType), default=FileType.UNKNOWN)
    upload_date = Column(DateTime, default=datetime.utcnow)
    
    # Raw schema detection (no processing yet)
    detected_columns = Column(JSON, nullable=True)  # ['Date', 'Amount', 'Description']
    estimated_rows = Column(Integer, nullable=True)
    sample_data = Column(JSON, nullable=True)  # First 3 rows for preview
    encoding_detected = Column(String, default='utf-8')
    delimiter_detected = Column(String, nullable=True)  # For CSV files
    
    # Metadata
    upload_ip = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    processing_notes = Column(JSON, default=[])
    
    # Foreign key
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Relationships
    user = relationship("User", back_populates="raw_files")
    processing_sessions = relationship("ProcessingSession", back_populates="raw_file")
    
    # Indexes
    __table_args__ = (
        Index('idx_raw_files_user_date', 'user_id', 'upload_date'),
        Index('idx_raw_files_hash', 'content_hash'),
        Index('idx_raw_files_type', 'detected_file_type'),
    )

# === STAGE 2: TRAINING DATA & PROCESSING ===

class TrainingDataset(Base):
    """
    Training data extracted from uploaded files
    This is your Hungarian categorized data + learning from user corrections
    """
    __tablename__ = "training_datasets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)  # "Hungarian Bank Data", "User Corrections"
    description = Column(Text, nullable=True)
    source_file_id = Column(Integer, ForeignKey("raw_files.id"), nullable=True)
    
    # Training metrics
    total_patterns = Column(Integer, default=0)
    merchant_patterns = Column(Integer, default=0)
    category_mappings = Column(Integer, default=0)
    confidence_score = Column(Float, default=0.0)  # Overall dataset quality
    
    # Metadata
    created_date = Column(DateTime, default=datetime.utcnow)
    last_updated = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    language = Column(String, default='en')  # For multilingual support
    
    # Foreign key
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Relationships
    user = relationship("User", back_populates="training_datasets")
    source_file = relationship("RawFile")
    patterns = relationship("TrainingPattern", back_populates="dataset")

class TrainingPattern(Base):
    """
    Individual patterns extracted from training data
    """
    __tablename__ = "training_patterns"

    id = Column(Integer, primary_key=True, index=True)
    pattern_type = Column(String, nullable=False)  # 'merchant', 'description', 'amount_range'
    pattern_value = Column(String, nullable=False)  # 'Zara Home', 'STARBUCKS'
    category_original = Column(String, nullable=True)  # 'ruha' (Hungarian)
    category_mapped = Column(String, nullable=False)  # 'Clothing' (English)
    
    # Pattern strength
    occurrences = Column(Integer, default=1)
    confidence = Column(Float, default=0.5)
    success_rate = Column(Float, default=0.0)  # How often this pattern is correct
    
    # Metadata
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_used = Column(DateTime, nullable=True)
    language = Column(String, default='en')
    
    # Foreign key
    dataset_id = Column(Integer, ForeignKey("training_datasets.id"), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    
    # Relationships
    dataset = relationship("TrainingDataset", back_populates="patterns")
    category = relationship("Category")
    
    # Indexes
    __table_args__ = (
        Index('idx_training_pattern_value', 'pattern_value'),
        Index('idx_training_pattern_type', 'pattern_type'),
        UniqueConstraint('dataset_id', 'pattern_type', 'pattern_value', name='uq_pattern'),
    )

class ProcessingSession(Base):
    """
    Stage 2: Processing session that converts raw files to structured data
    Links raw files to processed results
    """
    __tablename__ = "processing_sessions"

    id = Column(Integer, primary_key=True, index=True)
    session_name = Column(String, nullable=False)  # "Process Bank Statement 2025-07"
    raw_file_id = Column(Integer, ForeignKey("raw_files.id"), nullable=False)
    
    # Processing configuration
    column_mapping = Column(JSON, nullable=True)  # User-defined column mappings
    processing_rules = Column(JSON, default={})   # Custom processing rules
    use_training_data = Column(Boolean, default=True)
    training_dataset_ids = Column(JSON, default=[])  # Which datasets to use
    
    # Processing status
    status = Column(sa.Enum(ProcessingStatus), default=ProcessingStatus.RAW)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Results
    total_rows_found = Column(Integer, default=0)
    rows_processed = Column(Integer, default=0)
    rows_with_suggestions = Column(Integer, default=0)
    high_confidence_suggestions = Column(Integer, default=0)
    errors_found = Column(Integer, default=0)
    duplicates_found = Column(Integer, default=0)
    
    # Error tracking
    processing_errors = Column(JSON, default=[])
    column_detection_result = Column(JSON, nullable=True)
    data_quality_score = Column(Float, nullable=True)
    
    # Foreign keys
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Relationships
    user = relationship("User", back_populates="processing_sessions")
    raw_file = relationship("RawFile", back_populates="processing_sessions")
    processed_transactions = relationship("ProcessedTransaction", back_populates="processing_session")

# === STAGE 3: PROCESSED & CONFIRMED DATA ===

class ProcessedTransaction(Base):
    """
    Stage 2 → 3: Structured transaction data from processing
    Ready for user review and confirmation
    """
    __tablename__ = "processed_transactions"

    id = Column(Integer, primary_key=True, index=True)
    
    # Core transaction data
    transaction_date = Column(Date, nullable=False)
    beneficiary = Column(String, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    description = Column(Text, nullable=True)
    reference = Column(String, nullable=True)
    
    # AI suggestions
    suggested_category = Column(String, nullable=True)
    suggested_category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    confidence_score = Column(Float, nullable=True)
    confidence_level = Column(sa.Enum(ConfidenceLevel), nullable=True)
    suggestion_source = Column(String, nullable=True)  # 'training_data', 'pattern_match', 'ml_model'
    alternative_suggestions = Column(JSON, default=[])
    
    # Processing metadata
    raw_row_data = Column(JSON, nullable=False)  # Original CSV row
    processing_notes = Column(JSON, default=[])
    data_quality_flags = Column(JSON, default=[])  # ['low_confidence', 'unusual_amount']
    row_number = Column(Integer, nullable=True)  # Row in original file
    
    # User interaction
    requires_review = Column(Boolean, default=True)
    user_reviewed = Column(Boolean, default=False)
    user_approved = Column(Boolean, default=False)
    user_notes = Column(Text, nullable=True)
    review_date = Column(DateTime, nullable=True)
    
    # Duplicate detection
    is_potential_duplicate = Column(Boolean, default=False)
    duplicate_group_id = Column(Integer, nullable=True)
    similarity_score = Column(Float, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Foreign keys
    processing_session_id = Column(Integer, ForeignKey("processing_sessions.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Relationships
    processing_session = relationship("ProcessingSession", back_populates="processed_transactions")
    user = relationship("User", back_populates="processed_transactions")
    suggested_category_obj = relationship("Category")
    confirmed_transaction = relationship("ConfirmedTransaction", back_populates="processed_transaction", uselist=False)

class ConfirmedTransaction(Base):
    """
    Stage 3: Final confirmed transactions
    User has reviewed and approved these
    """
    __tablename__ = "confirmed_transactions"

    id = Column(Integer, primary_key=True, index=True)
    
    # Final transaction data
    transaction_date = Column(Date, nullable=False)
    beneficiary = Column(String, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    description = Column(Text, nullable=True)
    
    # User-confirmed categorization
    category = Column(String, nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)
    subcategory = Column(String, nullable=True)
    tags = Column(JSON, default=[])
    
    # User metadata
    is_private = Column(Boolean, default=False)
    user_notes = Column(Text, nullable=True)
    custom_fields = Column(JSON, default={})
    
    # Tracking
    confirmed_at = Column(DateTime, default=datetime.utcnow)
    modified_at = Column(DateTime, default=datetime.utcnow)
    was_ai_suggested = Column(Boolean, default=False)
    original_confidence = Column(Float, nullable=True)
    
    # Links back to processing
    processed_transaction_id = Column(Integer, ForeignKey("processed_transactions.id"), nullable=False)
    processing_session_id = Column(Integer, ForeignKey("processing_sessions.id"), nullable=False)
    
    # Foreign keys
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Relationships
    user = relationship("User", back_populates="confirmed_transactions")
    category_obj = relationship("Category", back_populates="confirmed_transactions")
    processed_transaction = relationship("ProcessedTransaction", back_populates="confirmed_transaction")

# === USER & CATEGORY MODELS (Enhanced) ===

class User(Base):
    """Enhanced user model with new relationships"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    
    # User preferences
    preferences = Column(JSON, default={
        "processing": {
            "auto_process_high_confidence": False,
            "confidence_threshold": 0.9,
            "use_training_data": True
        },
        "ui": {
            "theme": "auto",
            "default_currency": "EUR",
            "language": "en"
        }
    })

    # Relationships - New 3-stage workflow
    raw_files = relationship("RawFile", back_populates="user")
    training_datasets = relationship("TrainingDataset", back_populates="user")
    processing_sessions = relationship("ProcessingSession", back_populates="user")
    processed_transactions = relationship("ProcessedTransaction", back_populates="user")
    confirmed_transactions = relationship("ConfirmedTransaction", back_populates="user")
    categories = relationship("Category", back_populates="user")

class Category(Base):
    """User-defined categories"""
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    color = Column(String, default='#3B82F6')  # Hex color
    icon = Column(String, nullable=True)  # Emoji or icon name
    is_income = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    
    # Hierarchy support
    parent_category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    
    # Learning metadata
    auto_suggestions_enabled = Column(Boolean, default=True)
    pattern_count = Column(Integer, default=0)
    usage_count = Column(Integer, default=0)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    
    # Foreign key
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Relationships
    user = relationship("User", back_populates="categories")
    parent_category = relationship("Category", remote_side=[id])
    confirmed_transactions = relationship("ConfirmedTransaction", back_populates="category_obj")
    
    # Indexes
    __table_args__ = (
        UniqueConstraint('user_id', 'name', name='uq_user_category'),
        Index('idx_category_user', 'user_id'),
    )

# Helper function
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Create all tables
def create_tables():
    Base.metadata.create_all(bind=engine)

# Export all models for easy importing
__all__ = [
    'User', 'Category', 'RawFile', 'TrainingDataset', 'TrainingPattern', 
    'ProcessingSession', 'ProcessedTransaction', 'ConfirmedTransaction',
    'FileType', 'ProcessingStatus', 'ConfidenceLevel',
    'get_db', 'create_tables', 'Base', 'engine', 'SessionLocal'
]