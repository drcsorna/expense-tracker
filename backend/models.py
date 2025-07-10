# backend/models.py
# Enhanced database models with ML categorization, duplicates, and user-defined categories

from sqlalchemy import (
    create_engine, Column, Integer, String, Date, Numeric, Boolean, JSON, 
    ForeignKey, DateTime, Text, Float, UniqueConstraint, Index
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

# Enums
class UploadStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class DuplicateStatus(Enum):
    PENDING = "pending"
    RESOLVED = "resolved"
    IGNORED = "ignored"
    MERGED = "merged"

class CategorizationConfidence(Enum):
    LOW = "low"          # 0-40%
    MEDIUM = "medium"    # 41-70%
    HIGH = "high"        # 71-90%
    VERY_HIGH = "very_high"  # 91-100%

# Main Models
class User(Base):
    """Enhanced user model with preferences."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    
    # User preferences for ML and duplicates
    preferences = Column(JSON, default={
        "duplicate_detection": {
            "amount_tolerance": 0.01,
            "date_range_days": 3,
            "beneficiary_similarity_threshold": 0.8
        },
        "categorization": {
            "auto_approve_high_confidence": False,
            "confidence_threshold": 0.9
        },
        "ui": {
            "theme": "auto",
            "default_currency": "EUR"
        }
    })

    # Relationships
    transactions = relationship("Transaction", back_populates="owner", cascade="all, delete-orphan")
    staged_transactions = relationship("StagedTransaction", back_populates="owner", cascade="all, delete-orphan")
    upload_sessions = relationship("UploadSession", back_populates="user", cascade="all, delete-orphan")
    categories = relationship("Category", back_populates="user", cascade="all, delete-orphan")
    duplicate_groups = relationship("DuplicateGroup", back_populates="user", cascade="all, delete-orphan")

class Category(Base):
    """User-defined categories with ML learning capabilities."""
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    color = Column(String, default="#6366f1")  # Hex color code
    icon = Column(String, nullable=True)        # Emoji or icon name
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # ML learning data
    keywords = Column(JSON, default=[])  # User-defined keywords
    learned_patterns = Column(JSON, default={})  # ML-discovered patterns
    confidence_score = Column(Float, default=0.0)  # Overall learning confidence
    usage_count = Column(Integer, default=0)  # Number of transactions
    
    # Foreign key
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Relationships
    user = relationship("User", back_populates="categories")
    transactions = relationship("Transaction", back_populates="category_obj")
    staged_transactions = relationship("StagedTransaction", back_populates="suggested_category_obj")
    categorization_rules = relationship("CategorizationRule", back_populates="category")
    
    # Constraints
    __table_args__ = (
        UniqueConstraint('user_id', 'name', name='unique_user_category'),
        Index('idx_category_user_active', 'user_id', 'is_active'),
    )

class CategorizationRule(Base):
    """ML-learned rules for automatic categorization."""
    __tablename__ = "categorization_rules"

    id = Column(Integer, primary_key=True, index=True)
    rule_type = Column(String, nullable=False)  # 'keyword', 'amount_range', 'beneficiary_pattern', 'ml_vector'
    pattern = Column(JSON, nullable=False)      # The actual rule data
    confidence = Column(Float, nullable=False)  # Rule confidence (0.0-1.0)
    success_count = Column(Integer, default=0)  # Successful applications
    failure_count = Column(Integer, default=0)  # Failed applications
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used = Column(DateTime, nullable=True)
    
    # Foreign keys
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Relationships
    category = relationship("Category", back_populates="categorization_rules")
    
    # Indexes
    __table_args__ = (
        Index('idx_rule_type_active', 'rule_type', 'is_active'),
        Index('idx_rule_confidence', 'confidence'),
    )

class Transaction(Base):
    """Enhanced transaction model with categorization tracking."""
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    transaction_date = Column(Date, nullable=False)
    beneficiary = Column(String, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    category = Column(String, nullable=True)  # Category name for backward compatibility
    description = Column(Text, nullable=True)  # Additional description
    
    # Enhanced metadata
    is_private = Column(Boolean, default=False)
    tags = Column(JSON, default=[])  # User-defined tags
    notes = Column(Text, nullable=True)  # User notes
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Categorization tracking
    categorization_method = Column(String, nullable=True)  # 'manual', 'ml_auto', 'ml_suggested', 'rule_based'
    categorization_confidence = Column(Float, nullable=True)  # ML confidence score
    manual_review_required = Column(Boolean, default=False)
    
    # File processing metadata
    raw_data = Column(JSON, nullable=True)  # Original CSV row
    file_hash = Column(String, nullable=True)  # For duplicate detection
    import_batch_id = Column(String, nullable=True)  # Batch tracking
    
    # Foreign keys
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    upload_session_id = Column(Integer, ForeignKey("upload_sessions.id"), nullable=True)
    
    # Relationships
    owner = relationship("User", back_populates="transactions")
    category_obj = relationship("Category", back_populates="transactions")
    upload_session = relationship("UploadSession", back_populates="transactions")
    duplicate_entries = relationship("DuplicateEntry", back_populates="transaction")
    
    # Indexes
    __table_args__ = (
        Index('idx_transaction_date_user', 'transaction_date', 'owner_id'),
        Index('idx_transaction_beneficiary', 'beneficiary'),
        Index('idx_transaction_amount', 'amount'),
        Index('idx_transaction_category', 'category_id'),
        Index('idx_transaction_hash', 'file_hash'),
    )

class StagedTransaction(Base):
    """Enhanced staged transactions with ML suggestions."""
    __tablename__ = "staged_transactions"

    id = Column(Integer, primary_key=True, index=True)
    transaction_date = Column(Date, nullable=False)
    beneficiary = Column(String, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    description = Column(Text, nullable=True)
    
    # ML categorization suggestions
    suggested_category = Column(String, nullable=True)
    suggested_category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    confidence = Column(Float, nullable=True)  # ML confidence (0.0-1.0)
    confidence_level = Column(sa.Enum(CategorizationConfidence), nullable=True)
    alternative_suggestions = Column(JSON, default=[])  # Other possible categories
    
    # Processing metadata
    raw_data = Column(JSON, nullable=True)
    file_hash = Column(String, nullable=True)
    processing_notes = Column(JSON, default=[])  # Processing warnings/info
    requires_review = Column(Boolean, default=True)
    auto_approve_eligible = Column(Boolean, default=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    suggested_at = Column(DateTime, nullable=True)
    
    # Foreign keys
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    upload_session_id = Column(Integer, ForeignKey("upload_sessions.id"), nullable=False)
    
    # Relationships
    owner = relationship("User", back_populates="staged_transactions")
    upload_session = relationship("UploadSession", back_populates="staged_transactions")
    suggested_category_obj = relationship("Category", back_populates="staged_transactions")
    
    # Indexes
    __table_args__ = (
        Index('idx_staged_confidence', 'confidence'),
        Index('idx_staged_session', 'upload_session_id'),
        Index('idx_staged_hash', 'file_hash'),
    )

class UploadSession(Base):
    """Enhanced upload session tracking with detailed metrics."""
    __tablename__ = "upload_sessions"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    upload_date = Column(DateTime, default=datetime.utcnow)
    file_size = Column(Integer, nullable=False)
    file_type = Column(String, nullable=False)
    status = Column(sa.Enum(UploadStatus), default=UploadStatus.PENDING)
    
    # Processing metrics
    total_rows = Column(Integer, default=0)
    processed_rows = Column(Integer, default=0)
    staged_count = Column(Integer, default=0)
    approved_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    duplicate_count = Column(Integer, default=0)
    
    # ML categorization metrics
    ml_suggestions_count = Column(Integer, default=0)
    high_confidence_suggestions = Column(Integer, default=0)
    auto_categorized_count = Column(Integer, default=0)
    
    # Timing
    processing_start = Column(DateTime, nullable=True)
    processing_end = Column(DateTime, nullable=True)
    
    # Metadata
    raw_data_sample = Column(JSON, nullable=True)  # First 100 rows for audit
    processing_log = Column(JSON, default=[])      # Detailed processing events
    format_detected = Column(String, nullable=True)
    error_details = Column(JSON, default=[])       # Error information
    
    # Foreign key
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Relationships
    user = relationship("User", back_populates="upload_sessions")
    staged_transactions = relationship("StagedTransaction", back_populates="upload_session")
    transactions = relationship("Transaction", back_populates="upload_session")
    
    @property
    def processing_time_seconds(self):
        if self.processing_start and self.processing_end:
            return (self.processing_end - self.processing_start).total_seconds()
        return None

class DuplicateGroup(Base):
    """Groups of potentially duplicate transactions."""
    __tablename__ = "duplicate_groups"

    id = Column(Integer, primary_key=True, index=True)
    similarity_score = Column(Float, nullable=False)  # Overall similarity (0.0-1.0)
    detection_method = Column(String, nullable=False)  # 'hash', 'fuzzy', 'ml', 'manual'
    status = Column(sa.Enum(DuplicateStatus), default=DuplicateStatus.PENDING)
    resolved_at = Column(DateTime, nullable=True)
    resolution_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Foreign key
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Relationships
    user = relationship("User", back_populates="duplicate_groups")
    entries = relationship("DuplicateEntry", back_populates="group", cascade="all, delete-orphan")

class DuplicateEntry(Base):
    """Individual transaction entries within a duplicate group."""
    __tablename__ = "duplicate_entries"

    id = Column(Integer, primary_key=True, index=True)
    is_primary = Column(Boolean, default=False)  # The "keep" transaction
    similarity_details = Column(JSON, default={})  # Detailed similarity metrics
    
    # Foreign keys
    group_id = Column(Integer, ForeignKey("duplicate_groups.id"), nullable=False)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False)
    
    # Relationships
    group = relationship("DuplicateGroup", back_populates="entries")
    transaction = relationship("Transaction", back_populates="duplicate_entries")

class MLTrainingData(Base):
    """Training data for ML categorization improvement."""
    __tablename__ = "ml_training_data"

    id = Column(Integer, primary_key=True, index=True)
    beneficiary = Column(String, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    category = Column(String, nullable=False)
    user_corrected = Column(Boolean, default=False)  # User manually corrected
    confidence_when_predicted = Column(Float, nullable=True)
    
    # Feature vectors for ML
    features = Column(JSON, default={})  # Extracted features
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Foreign key
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Indexes
    __table_args__ = (
        Index('idx_ml_training_category', 'category'),
        Index('idx_ml_training_user', 'user_id'),
    )

class UserFeedback(Base):
    """User feedback on ML suggestions for continuous learning."""
    __tablename__ = "user_feedback"

    id = Column(Integer, primary_key=True, index=True)
    transaction_beneficiary = Column(String, nullable=False)
    transaction_amount = Column(Numeric(10, 2), nullable=False)
    suggested_category = Column(String, nullable=False)
    actual_category = Column(String, nullable=False)
    was_accepted = Column(Boolean, nullable=False)
    confidence_score = Column(Float, nullable=False)
    feedback_type = Column(String, nullable=False)  # 'correction', 'confirmation', 'rejection'
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Foreign key
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Indexes
    __table_args__ = (
        Index('idx_feedback_category', 'suggested_category', 'actual_category'),
        Index('idx_feedback_confidence', 'confidence_score'),
    )

# Utility functions
def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def create_tables():
    """Create all database tables."""
    Base.metadata.create_all(bind=engine)

def drop_tables():
    """Drop all database tables."""
    Base.metadata.drop_all(bind=engine)

# Default categories for new users
DEFAULT_CATEGORIES = [
    {"name": "Food & Dining", "color": "#ef4444", "icon": "🍽️", "keywords": ["restaurant", "food", "dining", "grocery", "supermarket"]},
    {"name": "Transportation", "color": "#f97316", "icon": "🚗", "keywords": ["gas", "fuel", "parking", "taxi", "uber", "public transport"]},
    {"name": "Entertainment", "color": "#8b5cf6", "icon": "🎬", "keywords": ["movie", "theater", "netflix", "spotify", "games"]},
    {"name": "Shopping", "color": "#06b6d4", "icon": "🛍️", "keywords": ["amazon", "shopping", "clothes", "retail"]},
    {"name": "Bills & Utilities", "color": "#dc2626", "icon": "⚡", "keywords": ["electric", "water", "gas", "internet", "phone", "insurance"]},
    {"name": "Healthcare", "color": "#16a34a", "icon": "🏥", "keywords": ["doctor", "pharmacy", "hospital", "medical", "health"]},
    {"name": "Income", "color": "#22c55e", "icon": "💰", "keywords": ["salary", "income", "deposit", "refund"]},
    {"name": "Transfer", "color": "#6b7280", "icon": "🔄", "keywords": ["transfer", "atm", "withdrawal"]},
    {"name": "Other", "color": "#9ca3af", "icon": "📝", "keywords": []}
]

async def create_default_categories(db: SessionLocal, user_id: int):
    """Create default categories for a new user."""
    for cat_data in DEFAULT_CATEGORIES:
        category = Category(
            name=cat_data["name"],
            color=cat_data["color"],
            icon=cat_data["icon"],
            keywords=cat_data["keywords"],
            user_id=user_id
        )
        db.add(category)
    db.commit()