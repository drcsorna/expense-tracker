# backend/main.py
# Main FastAPI app instance with enhanced staged data architecture

from datetime import datetime, timedelta
from typing import List, Optional
import os
from decimal import Decimal

from fastapi import Depends, FastAPI, HTTPException, status, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, desc, asc

# Import our modules
from . import models
from . import schemas
from .models import engine, get_db, create_default_categories
from .auth import get_current_user, verify_password, get_password_hash, create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES

# Import routers
from .routers import upload

# --- Application Setup ---
models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Expense Tracker API",
    description="A comprehensive expense tracking application with staged data processing",
    version="2.0.0"
)

# --- CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Static Files ---
frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")

# --- Include Routers ---
app.include_router(upload.router)

# --- Core API Endpoints ---

@app.get("/")
def read_root():
    """Root endpoint - serve frontend or API info."""
    frontend_index = os.path.join(frontend_path, "index.html")
    if os.path.exists(frontend_index):
        return FileResponse(frontend_index)
    
    return {
        "message": "Welcome to the Expense Tracker API v2.0",
        "version": "2.0.0",
        "status": "running",
        "features": [
            "Staged data processing",
            "Smart categorization",
            "Bulk operations",
            "Real-time progress tracking",
            "Advanced filtering"
        ]
    }

@app.get("/app")
def serve_frontend():
    """Serve the frontend application."""
    frontend_index = os.path.join(frontend_path, "index.html")
    if os.path.exists(frontend_index):
        return FileResponse(frontend_index)
    else:
        raise HTTPException(status_code=404, detail="Frontend not found")

@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "expense-tracker-api",
        "version": "2.0.0"
    }

# --- Authentication Endpoints ---

@app.post("/token", response_model=schemas.Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Login and get access token."""
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/users/", response_model=schemas.User)
def create_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    """Create a new user with default categories."""
    db_user = db.query(models.User).filter(models.User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = get_password_hash(user.password)
    db_user = models.User(email=user.email, hashed_password=hashed_password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    
    # Create default categories for the new user
    create_default_categories(db_user.id, db)
    
    return db_user

# --- Transaction Endpoints (Confirmed) ---

@app.get("/transactions/", response_model=schemas.PaginatedResponse)
def read_transactions(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    search: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    is_private: Optional[bool] = Query(default=None),
    sort_by: str = Query(default="transaction_date"),
    sort_order: str = Query(default="desc"),
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get paginated transactions with filtering."""
    query = db.query(models.Transaction).filter(models.Transaction.owner_id == current_user.id)
    
    # Apply filters
    if search:
        query = query.filter(models.Transaction.beneficiary.ilike(f"%{search}%"))
    if category:
        query = query.filter(models.Transaction.category == category)
    if date_from:
        query = query.filter(models.Transaction.transaction_date >= date_from)
    if date_to:
        query = query.filter(models.Transaction.transaction_date <= date_to)
    if is_private is not None:
        query = query.filter(models.Transaction.is_private == is_private)
    
    # Apply sorting
    if sort_order.lower() == "desc":
        query = query.order_by(desc(getattr(models.Transaction, sort_by)))
    else:
        query = query.order_by(asc(getattr(models.Transaction, sort_by)))
    
    total = query.count()
    transactions = query.offset(skip).limit(limit).all()
    
    return {
        "items": transactions,
        "total": total,
        "skip": skip,
        "limit": limit,
        "has_next": skip + limit < total,
        "has_previous": skip > 0
    }

@app.get("/transactions/count")
def get_transactions_count(
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get total count of confirmed transactions."""
    count = db.query(models.Transaction).filter(
        models.Transaction.owner_id == current_user.id
    ).count()
    return {"total": count}

@app.get("/transactions/stats", response_model=schemas.TransactionStats)
def get_transaction_stats(
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get transaction statistics."""
    transactions = db.query(models.Transaction).filter(
        models.Transaction.owner_id == current_user.id
    ).all()
    
    total_transactions = len(transactions)
    total_income = sum(t.amount for t in transactions if t.amount > 0)
    total_expenses = abs(sum(t.amount for t in transactions if t.amount < 0))
    net_balance = total_income - total_expenses
    
    # Category breakdown
    categories_breakdown = {}
    for transaction in transactions:
        cat = transaction.category or "Uncategorized"
        categories_breakdown[cat] = categories_breakdown.get(cat, Decimal(0)) + abs(transaction.amount)
    
    # Monthly summary (simplified)
    monthly_summary = {}
    for transaction in transactions:
        month_key = transaction.transaction_date.strftime("%Y-%m")
        if month_key not in monthly_summary:
            monthly_summary[month_key] = {"income": Decimal(0), "expenses": Decimal(0)}
        
        if transaction.amount > 0:
            monthly_summary[month_key]["income"] += transaction.amount
        else:
            monthly_summary[month_key]["expenses"] += abs(transaction.amount)
    
    return {
        "total_transactions": total_transactions,
        "total_income": total_income,
        "total_expenses": total_expenses,
        "net_balance": net_balance,
        "categories_breakdown": categories_breakdown,
        "monthly_summary": monthly_summary
    }

@app.get("/transactions/{transaction_id}", response_model=schemas.Transaction)
def read_transaction(
    transaction_id: int,
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific transaction."""
    transaction = db.query(models.Transaction).filter(
        models.Transaction.id == transaction_id,
        models.Transaction.owner_id == current_user.id
    ).first()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return transaction

@app.put("/transactions/{transaction_id}", response_model=schemas.Transaction)
def update_transaction(
    transaction_id: int,
    transaction_update: schemas.TransactionUpdate,
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a transaction."""
    db_transaction = db.query(models.Transaction).filter(
        models.Transaction.id == transaction_id,
        models.Transaction.owner_id == current_user.id
    ).first()
    if not db_transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    update_data = transaction_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_transaction, field, value)
    
    db_transaction.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_transaction)
    return db_transaction

@app.post("/transactions/", response_model=schemas.Transaction)
def create_transaction(
    transaction: schemas.TransactionCreate,
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new transaction."""
    db_transaction = models.Transaction(
        **transaction.dict(),
        owner_id=current_user.id,
        confirmed_at=datetime.utcnow()
    )
    db.add(db_transaction)
    db.commit()
    db.refresh(db_transaction)
    return db_transaction

@app.post("/transactions/{transaction_id}/split", response_model=schemas.SplitResult)
def split_transaction(
    transaction_id: int,
    split_data: schemas.TransactionSplit,
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Split a transaction into multiple transactions."""
    original_transaction = db.query(models.Transaction).filter(
        models.Transaction.id == transaction_id,
        models.Transaction.owner_id == current_user.id
    ).first()
    
    if not original_transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    # Validate split amounts
    total_split_amount = sum(Decimal(str(split['amount'])) for split in split_data.splits)
    if abs(total_split_amount - abs(original_transaction.amount)) > Decimal('0.01'):
        raise HTTPException(status_code=400, detail="Split amounts don't match original amount")
    
    new_transaction_ids = []
    
    try:
        # Mark original as split
        original_transaction.is_split = True
        original_transaction.split_reason = split_data.reason
        
        # Create split transactions
        for i, split in enumerate(split_data.splits):
            new_transaction = models.Transaction(
                transaction_date=original_transaction.transaction_date,
                beneficiary=split.get('beneficiary', f"{original_transaction.beneficiary} (Split {i+1})"),
                amount=Decimal(str(split['amount'])),
                category=split.get('category', original_transaction.category),
                labels=split.get('labels', original_transaction.labels),
                is_private=original_transaction.is_private,
                parent_transaction_id=original_transaction.id,
                owner_id=current_user.id,
                confirmed_at=datetime.utcnow(),
                notes=split.get('notes')
            )
            db.add(new_transaction)
            db.flush()
            new_transaction_ids.append(new_transaction.id)
        
        db.commit()
        
        return {
            "success": True,
            "original_transaction_id": transaction_id,
            "new_transaction_ids": new_transaction_ids,
            "message": f"Transaction split into {len(split_data.splits)} parts"
        }
    
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error splitting transaction: {str(e)}")

@app.delete("/transactions/{transaction_id}")
def delete_transaction(
    transaction_id: int,
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a transaction."""
    transaction = db.query(models.Transaction).filter(
        models.Transaction.id == transaction_id,
        models.Transaction.owner_id == current_user.id
    ).first()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    db.delete(transaction)
    db.commit()
    return {"message": "Transaction deleted successfully"}

@app.delete("/transactions/")
def delete_all_transactions(
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete all transactions for the current user."""
    deleted_count = db.query(models.Transaction).filter(
        models.Transaction.owner_id == current_user.id
    ).delete()
    db.commit()
    return {
        "message": f"Successfully deleted {deleted_count} transactions",
        "deleted_count": deleted_count
    }

# --- Staged Transaction Endpoints ---

@app.get("/staged-transactions/", response_model=List[schemas.StagedTransaction])
def read_staged_transactions(
    skip: int = 0,
    limit: int = 100,
    status: Optional[schemas.TransactionStatusEnum] = None,
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get staged transactions."""
    query = db.query(models.StagedTransaction).filter(
        models.StagedTransaction.user_id == current_user.id
    )
    
    if status:
        query = query.filter(models.StagedTransaction.status == status)
    
    query = query.order_by(desc(models.StagedTransaction.created_at))
    return query.offset(skip).limit(limit).all()

@app.put("/staged-transactions/{staged_id}", response_model=schemas.StagedTransaction)
def update_staged_transaction(
    staged_id: int,
    update_data: schemas.StagedTransactionUpdate,
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a staged transaction."""
    staged_transaction = db.query(models.StagedTransaction).filter(
        models.StagedTransaction.id == staged_id,
        models.StagedTransaction.user_id == current_user.id
    ).first()
    
    if not staged_transaction:
        raise HTTPException(status_code=404, detail="Staged transaction not found")
    
    update_dict = update_data.dict(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(staged_transaction, field, value)
    
    db.commit()
    db.refresh(staged_transaction)
    return staged_transaction

@app.post("/staged-transactions/{staged_id}/confirm", response_model=schemas.Transaction)
def confirm_staged_transaction(
    staged_id: int,
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Confirm a staged transaction, moving it to confirmed transactions."""
    staged_transaction = db.query(models.StagedTransaction).filter(
        models.StagedTransaction.id == staged_id,
        models.StagedTransaction.user_id == current_user.id,
        models.StagedTransaction.status == schemas.TransactionStatusEnum.STAGED
    ).first()
    
    if not staged_transaction:
        raise HTTPException(status_code=404, detail="Staged transaction not found")
    
    # Create confirmed transaction
    confirmed_transaction = models.Transaction(
        transaction_date=staged_transaction.transaction_date,
        beneficiary=staged_transaction.beneficiary,
        amount=staged_transaction.amount,
        category=staged_transaction.category,
        labels=staged_transaction.labels,
        is_private=staged_transaction.is_private,
        notes=staged_transaction.notes,
        owner_id=current_user.id,
        source_upload_session_id=staged_transaction.upload_session_id,
        confirmed_at=datetime.utcnow(),
        raw_data=staged_transaction.raw_transaction_data
    )
    
    db.add(confirmed_transaction)
    db.flush()
    
    # Update staged transaction
    staged_transaction.status = schemas.TransactionStatusEnum.CONFIRMED
    staged_transaction.reviewed_at = datetime.utcnow()
    staged_transaction.confirmed_transaction_id = confirmed_transaction.id
    
    db.commit()
    db.refresh(confirmed_transaction)
    return confirmed_transaction

@app.post("/staged-transactions/bulk-action", response_model=schemas.BulkActionResult)
def bulk_staged_action(
    action_data: schemas.BulkTransactionAction,
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Perform bulk actions on staged transactions."""
    staged_transactions = db.query(models.StagedTransaction).filter(
        models.StagedTransaction.id.in_(action_data.transaction_ids),
        models.StagedTransaction.user_id == current_user.id
    ).all()
    
    if not staged_transactions:
        raise HTTPException(status_code=404, detail="No staged transactions found")
    
    processed_count = 0
    failed_count = 0
    errors = []
    
    try:
        for staged_tx in staged_transactions:
            try:
                if action_data.action == "confirm":
                    # Confirm transaction
                    confirmed_transaction = models.Transaction(
                        transaction_date=staged_tx.transaction_date,
                        beneficiary=staged_tx.beneficiary,
                        amount=staged_tx.amount,
                        category=staged_tx.category,
                        labels=staged_tx.labels,
                        is_private=staged_tx.is_private,
                        notes=staged_tx.notes,
                        owner_id=current_user.id,
                        source_upload_session_id=staged_tx.upload_session_id,
                        confirmed_at=datetime.utcnow(),
                        raw_data=staged_tx.raw_transaction_data
                    )
                    db.add(confirmed_transaction)
                    db.flush()
                    
                    staged_tx.status = schemas.TransactionStatusEnum.CONFIRMED
                    staged_tx.confirmed_transaction_id = confirmed_transaction.id
                    
                elif action_data.action == "reject":
                    staged_tx.status = schemas.TransactionStatusEnum.REJECTED
                    
                elif action_data.action == "update_category":
                    if action_data.category:
                        staged_tx.category = action_data.category
                
                staged_tx.reviewed_at = datetime.utcnow()
                if action_data.notes:
                    staged_tx.notes = action_data.notes
                
                processed_count += 1
                
            except Exception as e:
                failed_count += 1
                errors.append(f"Transaction {staged_tx.id}: {str(e)}")
        
        db.commit()
        
        return {
            "success": True,
            "message": f"Processed {processed_count} transactions",
            "processed_count": processed_count,
            "failed_count": failed_count,
            "errors": errors
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Bulk action failed: {str(e)}")

# --- Category Endpoints ---

@app.get("/categories/", response_model=List[schemas.Category])
def read_categories(
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get user categories."""
    return db.query(models.Category).filter(
        models.Category.user_id == current_user.id
    ).order_by(models.Category.name).all()

@app.post("/categories/", response_model=schemas.Category)
def create_category(
    category: schemas.CategoryCreate,
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new category."""
    db_category = models.Category(**category.dict(), user_id=current_user.id)
    db.add(db_category)
    db.commit()
    db.refresh(db_category)
    return db_category

# --- Upload Session Endpoints ---

@app.get("/upload-sessions/", response_model=List[schemas.UploadSession])
def read_upload_sessions(
    skip: int = 0,
    limit: int = 10,
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get upload sessions for the user."""
    return db.query(models.UploadSession).filter(
        models.UploadSession.user_id == current_user.id
    ).order_by(desc(models.UploadSession.upload_date)).offset(skip).limit(limit).all()

@app.get("/upload-sessions/{session_id}", response_model=schemas.UploadSession)
def read_upload_session(
    session_id: int,
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific upload session."""
    session = db.query(models.UploadSession).filter(
        models.UploadSession.id == session_id,
        models.UploadSession.user_id == current_user.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Upload session not found")
    
    return session