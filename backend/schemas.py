# backend/schemas.py
# Data validation schemas (Pydantic) - Enhanced for staged data architecture

from pydantic import BaseModel, EmailStr, ConfigDict, Field
from typing import List, Optional, Any, Dict
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

# --- Enums ---
class UploadStatusEnum(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    STAGED = "staged"
    CONFIRMED = "confirmed"
    FAILED = "failed"

class TransactionStatusEnum(str, Enum):
    STAGED = "staged"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"

# --- Base Schemas ---
class TransactionBase(BaseModel):
    """Core fields for a transaction."""
    transaction_date: date
    beneficiary: str
    amount: Decimal
    category: Optional[str] = None
    labels: Optional[List[str]] = None
    is_private: bool = False

class CategoryBase(BaseModel):
    """Core fields for a category."""
    name: str
    parent_category_id: Optional[int] = None
    color: Optional[str] = None
    icon: Optional[str] = None
    is_expense: bool = True

class UserBase(BaseModel):
    """Core fields for a user."""
    email: EmailStr

# --- Creation Schemas ---
class TransactionCreate(TransactionBase):
    """Schema for creating a new transaction."""
    subcategory: Optional[str] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = None
    parent_transaction_id: Optional[int] = None
    split_reason: Optional[str] = None

class StagedTransactionCreate(TransactionBase):
    """Schema for creating a staged transaction."""
    confidence_score: Optional[Decimal] = Field(default=1.0, ge=0, le=1)
    suggested_category: Optional[str] = None
    suggested_labels: Optional[List[str]] = None
    notes: Optional[str] = None
    raw_transaction_data: Optional[Dict[str, Any]] = None

class CategoryCreate(CategoryBase):
    """Schema for creating a new category."""
    pass

class UserCreate(UserBase):
    """Schema for creating a new user."""
    password: str

# --- Update Schemas ---
class TransactionUpdate(BaseModel):
    """Schema for updating a transaction."""
    beneficiary: Optional[str] = None
    amount: Optional[Decimal] = None
    transaction_date: Optional[date] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    labels: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    is_private: Optional[bool] = None
    notes: Optional[str] = None

class StagedTransactionUpdate(BaseModel):
    """Schema for updating a staged transaction."""
    beneficiary: Optional[str] = None
    amount: Optional[Decimal] = None
    transaction_date: Optional[date] = None
    category: Optional[str] = None
    labels: Optional[List[str]] = None
    is_private: Optional[bool] = None
    notes: Optional[str] = None
    status: Optional[TransactionStatusEnum] = None

# --- Response Schemas ---
class Category(CategoryBase):
    """Schema for reading category data."""
    id: int
    user_id: int
    is_default: bool
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

class Transaction(TransactionBase):
    """Schema for reading confirmed transaction data."""
    id: int
    owner_id: int
    subcategory: Optional[str] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = None
    is_split: bool = False
    parent_transaction_id: Optional[int] = None
    split_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    confirmed_at: Optional[datetime] = None
    source_upload_session_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)

class StagedTransaction(TransactionBase):
    """Schema for reading staged transaction data."""
    id: int
    user_id: int
    upload_session_id: int
    status: TransactionStatusEnum
    confidence_score: Decimal
    suggested_category: Optional[str] = None
    suggested_labels: Optional[List[str]] = None
    notes: Optional[str] = None
    created_at: datetime
    reviewed_at: Optional[datetime] = None
    confirmed_transaction_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)

class UploadSession(BaseModel):
    """Schema for reading upload session data."""
    id: int
    filename: str
    upload_date: datetime
    file_size: int
    file_type: str
    status: UploadStatusEnum
    total_rows: int = 0
    processed_rows: int = 0
    staged_count: int = 0
    error_count: int = 0
    duplicate_count: int = 0
    processing_start: Optional[datetime] = None
    processing_end: Optional[datetime] = None
    format_detected: Optional[str] = None
    user_id: int

    model_config = ConfigDict(from_attributes=True)

class User(UserBase):
    """Schema for reading user data."""
    id: int
    created_at: datetime
    preferences: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)

class UserWithTransactions(User):
    """Schema for user data with transactions."""
    transactions: List[Transaction] = []
    staged_transactions: List[StagedTransaction] = []

    model_config = ConfigDict(from_attributes=True)

# --- Authentication Schemas ---
class Token(BaseModel):
    """Schema for authentication token."""
    access_token: str
    token_type: str

class TokenData(BaseModel):
    """Schema for token data."""
    email: Optional[str] = None

# --- Bulk Operation Schemas ---
class BulkTransactionAction(BaseModel):
    """Schema for bulk transaction operations."""
    action: str  # "confirm", "reject", "update_category"
    transaction_ids: List[int]
    category: Optional[str] = None
    notes: Optional[str] = None

class BulkActionResult(BaseModel):
    """Schema for bulk action results."""
    success: bool
    message: str
    processed_count: int
    failed_count: int
    errors: List[str] = []

# --- Split Transaction Schemas ---
class TransactionSplit(BaseModel):
    """Schema for splitting a transaction."""
    splits: List[Dict[str, Any]]  # List of split amounts and categories
    reason: Optional[str] = None

class SplitResult(BaseModel):
    """Schema for split operation result."""
    success: bool
    original_transaction_id: int
    new_transaction_ids: List[int]
    message: str

# --- Upload Response Schemas ---
class UploadProgress(BaseModel):
    """Schema for upload progress updates."""
    session_id: int
    filename: str
    progress_percentage: float
    current_stage: str
    rows_processed: int
    total_rows: int
    estimated_time_remaining: Optional[int] = None

class UploadResult(BaseModel):
    """Enhanced upload result schema."""
    success: bool
    session_id: int
    filename: str
    file_size: int
    total_rows: int
    staged_count: int
    duplicate_count: int
    error_count: int
    errors: List[str] = []
    processing_time_seconds: float
    format_detected: str
    suggested_actions: List[str] = []

# --- Filter and Pagination Schemas ---
class TransactionFilter(BaseModel):
    """Schema for transaction filtering."""
    search: Optional[str] = None
    category: Optional[str] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    amount_min: Optional[Decimal] = None
    amount_max: Optional[Decimal] = None
    is_private: Optional[bool] = None
    tags: Optional[List[str]] = None

class PaginationParams(BaseModel):
    """Schema for pagination parameters."""
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=1000)
    sort_by: Optional[str] = "transaction_date"
    sort_order: Optional[str] = "desc"

class PaginatedResponse(BaseModel):
    """Schema for paginated responses."""
    items: List[Any]
    total: int
    skip: int
    limit: int
    has_next: bool
    has_previous: bool

# --- Statistics Schemas ---
class TransactionStats(BaseModel):
    """Schema for transaction statistics."""
    total_transactions: int
    total_income: Decimal
    total_expenses: Decimal
    net_balance: Decimal
    categories_breakdown: Dict[str, Decimal]
    monthly_summary: Dict[str, Dict[str, Decimal]]

class CategoryStats(BaseModel):
    """Schema for category statistics."""
    category: str
    transaction_count: int
    total_amount: Decimal
    percentage_of_total: float
    average_amount: Decimal