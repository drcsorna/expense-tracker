# backend/main.py
# Enhanced FastAPI app with ML categorization and duplicate management

from datetime import datetime, timedelta, date
from typing import List, Optional, Dict, Any
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
from .routers import upload, categorization, duplicates

# --- Application Setup ---
models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Expense Tracker API 3.0",
    description="Intelligent expense tracking with ML-powered categorization and duplicate management",
    version="3.0.0"
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
app.include_router(categorization.router)
app.include_router(duplicates.router)

# --- Core API Endpoints ---

@app.get("/")
def read_root():
    """Root endpoint - serve frontend or API info."""
    frontend_index = os.path.join(frontend_path, "index.html")
    if os.path.exists(frontend_index):
        return FileResponse(frontend_index)
    
    return {
        "message": "Welcome to the Expense Tracker API v3.0",
        "version": "3.0.0",
        "status": "running",
        "features": [
            "ML-powered categorization",
            "Smart duplicate detection", 
            "Category bootstrap learning",
            "Real-time progress tracking",
            "Advanced filtering",
            "Dark/Light theme support"
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
    """Enhanced health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "expense-tracker-api",
        "version": "3.0.0",
        "features": {
            "ml_categorization": True,
            "duplicate_detection": True,
            "real_time_progress": True,
            "category_bootstrap": True
        }
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
    """Get paginated transactions with advanced filtering."""
    
    # Build query
    query = db.query(models.Transaction).filter(models.Transaction.owner_id == current_user.id)
    
    # Apply filters
    if search:
        query = query.filter(models.Transaction.beneficiary.ilike(f"%{search}%"))
    
    if category:
        query = query.filter(models.Transaction.category == category)
    
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d").date()
            query = query.filter(models.Transaction.transaction_date >= date_from_obj)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from format. Use YYYY-MM-DD")
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d").date()
            query = query.filter(models.Transaction.transaction_date <= date_to_obj)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_to format. Use YYYY-MM-DD")
    
    if is_private is not None:
        query = query.filter(models.Transaction.is_private == is_private)
    
    # Apply sorting
    sort_column = getattr(models.Transaction, sort_by, models.Transaction.transaction_date)
    if sort_order.lower() == "desc":
        query = query.order_by(desc(sort_column))
    else:
        query = query.order_by(asc(sort_column))
    
    # Get total count
    total = query.count()
    
    # Apply pagination
    transactions = query.offset(skip).limit(limit).all()
    
    return schemas.PaginatedResponse(
        items=transactions,
        total=total,
        skip=skip,
        limit=limit,
        page=skip // limit + 1,
        pages=(total + limit - 1) // limit
    )

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
    
    if not transaction:
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
    transaction = db.query(models.Transaction).filter(
        models.Transaction.id == transaction_id,
        models.Transaction.owner_id == current_user.id
    ).first()
    
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    # Update fields
    for field, value in transaction_update.dict(exclude_unset=True).items():
        setattr(transaction, field, value)
    
    transaction.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(transaction)
    
    return transaction

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
    
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    db.delete(transaction)
    db.commit()
    
    return {"message": "Transaction deleted successfully"}

# --- Staged Transaction Endpoints ---

@app.get("/staged-transactions/", response_model=List[schemas.StagedTransaction])
def read_staged_transactions(
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all staged transactions for review."""
    staged_transactions = db.query(models.StagedTransaction).filter(
        models.StagedTransaction.user_id == current_user.id,
        models.StagedTransaction.status == models.TransactionStatus.STAGED
    ).order_by(desc(models.StagedTransaction.created_at)).all()
    
    return staged_transactions

@app.get("/staged-transactions/{staged_id}", response_model=schemas.StagedTransaction)
def read_staged_transaction(
    staged_id: int,
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific staged transaction."""
    staged_transaction = db.query(models.StagedTransaction).filter(
        models.StagedTransaction.id == staged_id,
        models.StagedTransaction.user_id == current_user.id
    ).first()
    
    if not staged_transaction:
        raise HTTPException(status_code=404, detail="Staged transaction not found")
    
    return staged_transaction

@app.put("/staged-transactions/{staged_id}", response_model=schemas.StagedTransaction)
def update_staged_transaction(
    staged_id: int,
    transaction_update: schemas.StagedTransactionUpdate,
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
    
    # Update fields
    for field, value in transaction_update.dict(exclude_unset=True).items():
        setattr(staged_transaction, field, value)
    
    db.commit()
    db.refresh(staged_transaction)
    
    return staged_transaction

@app.post("/staged-transactions/bulk-action")
def bulk_action_staged_transactions(
    bulk_action: schemas.BulkStagedAction,
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Perform bulk actions on staged transactions."""
    
    # Get all specified staged transactions
    staged_transactions = db.query(models.StagedTransaction).filter(
        models.StagedTransaction.id.in_(bulk_action.transaction_ids),
        models.StagedTransaction.user_id == current_user.id,
        models.StagedTransaction.status == models.TransactionStatus.STAGED
    ).all()
    
    if len(staged_transactions) != len(bulk_action.transaction_ids):
        raise HTTPException(
            status_code=404, 
            detail="Some transactions not found or already processed"
        )
    
    processed_count = 0
    failed_count = 0
    errors = []
    
    try:
        for staged_transaction in staged_transactions:
            try:
                action_data = bulk_action
                
                if action_data.action == "confirm":
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
                        raw_data=staged_transaction.raw_transaction_data,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                    db.add(confirmed_transaction)
                    db.flush()
                    
                    staged_transaction.status = models.TransactionStatus.CONFIRMED
                    staged_transaction.confirmed_transaction_id = confirmed_transaction.id
                    
                elif action_data.action == "reject":
                    staged_transaction.status = models.TransactionStatus.REJECTED
                    
                elif action_data.action == "update_category":
                    if action_data.category:
                        staged_transaction.category = action_data.category
                        
                        # Smart recategorization: find similar transactions
                        similar_transactions = db.query(models.StagedTransaction).filter(
                            models.StagedTransaction.user_id == current_user.id,
                            models.StagedTransaction.beneficiary.ilike(f"%{staged_transaction.beneficiary}%"),
                            models.StagedTransaction.id != staged_transaction.id,
                            models.StagedTransaction.status == models.TransactionStatus.STAGED
                        ).all()
                        
                        # Also update confirmed transactions with similar beneficiaries
                        similar_confirmed = db.query(models.Transaction).filter(
                            models.Transaction.owner_id == current_user.id,
                            models.Transaction.beneficiary.ilike(f"%{staged_transaction.beneficiary}%")
                        ).all()
                        
                        for similar in similar_transactions:
                            similar.category = action_data.category
                            similar.suggested_category = action_data.category
                        
                        for similar in similar_confirmed:
                            similar.category = action_data.category
                            similar.updated_at = datetime.utcnow()
                    
                    if action_data.notes:
                        staged_transaction.notes = action_data.notes
                
                staged_transaction.reviewed_at = datetime.utcnow()
                processed_count += 1
                
            except Exception as e:
                failed_count += 1
                errors.append(f"Transaction {staged_transaction.id}: {str(e)}")
        
        db.commit()
        
        return {
            "success": processed_count > 0,
            "message": f"Processed {processed_count} transactions, {failed_count} failed",
            "processed_count": processed_count,
            "failed_count": failed_count,
            "errors": errors
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Bulk action failed: {str(e)}")

# --- Category Endpoints ---

@app.get("/categories/", response_model=List[schemas.CategoryWithStats])
def read_categories(
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all categories with transaction counts."""
    categories = db.query(models.Category).filter(
        models.Category.user_id == current_user.id
    ).order_by(models.Category.name).all()
    
    # Add transaction counts
    result = []
    for category in categories:
        transaction_count = db.query(models.Transaction).filter(
            models.Transaction.owner_id == current_user.id,
            models.Transaction.category == category.name
        ).count()
        
        category_dict = schemas.CategoryWithStats.from_orm(category).dict()
        category_dict['transaction_count'] = transaction_count
        result.append(category_dict)
    
    return result

@app.post("/categories/", response_model=schemas.Category)
def create_category(
    category: schemas.CategoryCreate,
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new category."""
    # Check if category already exists
    existing = db.query(models.Category).filter(
        models.Category.user_id == current_user.id,
        models.Category.name == category.name
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Category already exists")
    
    db_category = models.Category(
        **category.dict(),
        user_id=current_user.id
    )
    db.add(db_category)
    db.commit()
    db.refresh(db_category)
    
    return db_category

@app.put("/categories/{category_id}", response_model=schemas.Category)
def update_category(
    category_id: int,
    category_update: schemas.CategoryUpdate,
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a category and all associated transactions."""
    category = db.query(models.Category).filter(
        models.Category.id == category_id,
        models.Category.user_id == current_user.id
    ).first()
    
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    
    old_name = category.name
    
    # Update category
    for field, value in category_update.dict(exclude_unset=True).items():
        setattr(category, field, value)
    
    # If name changed, update all transactions
    if category_update.name and category_update.name != old_name:
        # Update confirmed transactions
        db.query(models.Transaction).filter(
            models.Transaction.owner_id == current_user.id,
            models.Transaction.category == old_name
        ).update({"category": category_update.name, "updated_at": datetime.utcnow()})
        
        # Update staged transactions
        db.query(models.StagedTransaction).filter(
            models.StagedTransaction.user_id == current_user.id,
            models.StagedTransaction.category == old_name
        ).update({"category": category_update.name})
    
    db.commit()
    db.refresh(category)
    
    return category

@app.delete("/categories/{category_id}")
def delete_category(
    category_id: int,
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a category."""
    category = db.query(models.Category).filter(
        models.Category.id == category_id,
        models.Category.user_id == current_user.id
    ).first()
    
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    
    # Check if category is in use
    transaction_count = db.query(models.Transaction).filter(
        models.Transaction.owner_id == current_user.id,
        models.Transaction.category == category.name
    ).count()
    
    if transaction_count > 0:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot delete category '{category.name}' - it's used by {transaction_count} transactions"
        )
    
    db.delete(category)
    db.commit()
    
    return {"message": f"Category '{category.name}' deleted successfully"}

# --- Analytics Endpoints ---

@app.get("/analytics/summary")
def get_analytics_summary(
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get financial analytics summary."""
    
    # Build base query
    query = db.query(models.Transaction).filter(models.Transaction.owner_id == current_user.id)
    
    # Apply date filters
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d").date()
            query = query.filter(models.Transaction.transaction_date >= date_from_obj)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from format. Use YYYY-MM-DD")
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d").date()
            query = query.filter(models.Transaction.transaction_date <= date_to_obj)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_to format. Use YYYY-MM-DD")
    
    # Calculate summary statistics
    total_transactions = query.count()
    
    # Income and expenses
    income_sum = query.filter(models.Transaction.amount > 0).with_entities(
        func.sum(models.Transaction.amount)
    ).scalar() or Decimal('0.00')
    
    expense_sum = query.filter(models.Transaction.amount < 0).with_entities(
        func.sum(models.Transaction.amount)
    ).scalar() or Decimal('0.00')
    
    # Top categories
    category_stats = query.filter(
        models.Transaction.category.isnot(None)
    ).with_entities(
        models.Transaction.category,
        func.count(models.Transaction.id).label('count'),
        func.sum(models.Transaction.amount).label('total')
    ).group_by(models.Transaction.category).order_by(desc('count')).limit(10).all()
    
    # Monthly trends (last 12 months)
    monthly_stats = query.with_entities(
        func.date_trunc('month', models.Transaction.transaction_date).label('month'),
        func.count(models.Transaction.id).label('count'),
        func.sum(models.Transaction.amount).label('total')
    ).group_by('month').order_by('month').all()
    
    return {
        "total_transactions": total_transactions,
        "total_income": float(income_sum),
        "total_expenses": float(expense_sum),
        "net_flow": float(income_sum + expense_sum),
        "top_categories": [
            {
                "category": stat[0],
                "transaction_count": stat[1],
                "total_amount": float(stat[2])
            }
            for stat in category_stats
        ],
        "monthly_trends": [
            {
                "month": stat[0].strftime("%Y-%m") if stat[0] else None,
                "transaction_count": stat[1],
                "total_amount": float(stat[2])
            }
            for stat in monthly_stats
        ]
    }

# --- Upload Session Management ---

@app.get("/upload-sessions/", response_model=List[schemas.UploadSession])
def read_upload_sessions(
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get user's upload sessions."""
    sessions = db.query(models.UploadSession).filter(
        models.UploadSession.user_id == current_user.id
    ).order_by(desc(models.UploadSession.created_at)).limit(20).all()
    
    return sessions

@app.get("/upload-sessions/{session_id}", response_model=schemas.UploadSession)
def read_upload_session(
    session_id: int,
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get specific upload session details."""
    session = db.query(models.UploadSession).filter(
        models.UploadSession.id == session_id,
        models.UploadSession.user_id == current_user.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Upload session not found")
    
    return session

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)