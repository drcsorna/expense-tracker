# backend/main.py
# Enhanced FastAPI application with all 2025 features

from fastapi import FastAPI, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import json
import asyncio
from typing import Dict, List, Optional, Any

# Import modules
from . import models, auth
from .websocket_manager import ConnectionManager

# Import routers (create them first or comment out if not ready)
try:
    from .routers import upload, categorization, duplicates, transactions
    ROUTERS_AVAILABLE = True
except ImportError:
    print("⚠️  Router files not found - creating basic upload router")
    ROUTERS_AVAILABLE = False

# Initialize FastAPI app
app = FastAPI(
    title="Expense Tracker 3.0",
    description="Smart financial management with ML-powered categorization",
    version="3.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8080"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security
security = HTTPBearer()

# WebSocket manager
manager = ConnectionManager()

# Create database tables
models.create_tables()

# Include routers
if ROUTERS_AVAILABLE:
    app.include_router(upload.router, prefix="/upload", tags=["upload"])
    app.include_router(categorization.router, prefix="/categorization", tags=["categorization"])
    app.include_router(duplicates.router, prefix="/duplicates", tags=["duplicates"])
    app.include_router(transactions.router, prefix="/transactions", tags=["transactions"])
    
    # Set WebSocket manager for upload router
    upload.set_websocket_manager(manager)
else:
    # Basic upload router fallback
    from fastapi import APIRouter
    basic_router = APIRouter()
    
    @basic_router.get("/staged/")
    async def get_staged_basic():
        return []
    
    app.include_router(basic_router, prefix="/upload", tags=["upload"])

# ===== DEPENDENCY FUNCTIONS =====
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(models.get_db)
):
    """Get current authenticated user."""
    try:
        payload = auth.verify_token(credentials.credentials)
        user_email = payload.get("sub")
        if user_email is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials"
            )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
    
    user = db.query(models.User).filter(models.User.email == user_email).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    
    # Update last login
    user.last_login = datetime.utcnow()
    db.commit()
    
    return user

# ===== AUTHENTICATION ENDPOINTS =====
@app.post("/auth/register")
async def register(user_data: dict, db: Session = Depends(models.get_db)):
    """Register a new user with default categories."""
    email = user_data.get("email")
    password = user_data.get("password")
    
    if not email or not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email and password are required"
        )
    
    # Check if user exists
    existing_user = db.query(models.User).filter(models.User.email == email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User already exists"
        )
    
    # Create user
    hashed_password = auth.get_password_hash(password)
    new_user = models.User(
        email=email,
        hashed_password=hashed_password,
        created_at=datetime.utcnow()
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    # Create default categories
    await models.create_default_categories(db, new_user.id)
    
    return {"message": "User registered successfully", "user_id": new_user.id}

@app.post("/auth/login")
async def login(form_data: dict, db: Session = Depends(models.get_db)):
    """Login user and return access token."""
    email = form_data.get("username")  # FastAPI OAuth2 uses 'username'
    password = form_data.get("password")
    
    if not email or not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email and password are required"
        )
    
    # Verify user
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user or not auth.verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is deactivated"
        )
    
    # Create access token
    access_token = auth.create_access_token(data={"sub": user.email})
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "created_at": user.created_at.isoformat()
        }
    }

# ===== WEBSOCKET ENDPOINTS =====
@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str, token: str = None):
    """WebSocket endpoint for real-time progress updates."""
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    
    # Verify token
    try:
        payload = auth.verify_token(token)
        user_email = payload.get("sub")
        if not user_email:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    
    await manager.connect(websocket, session_id)
    
    try:
        while True:
            # Keep connection alive with ping/pong
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
            
    except WebSocketDisconnect:
        manager.disconnect(session_id)

# ===== USER PREFERENCES =====
@app.get("/user/preferences")
async def get_user_preferences(
    current_user: models.User = Depends(get_current_user)
):
    """Get user preferences."""
    return {
        "preferences": current_user.preferences,
        "created_at": current_user.created_at.isoformat(),
        "last_login": current_user.last_login.isoformat() if current_user.last_login else None
    }

@app.put("/user/preferences")
async def update_user_preferences(
    preferences: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Update user preferences."""
    # Merge with existing preferences
    current_prefs = current_user.preferences or {}
    
    # Update specific sections
    for section, values in preferences.items():
        if section in current_prefs:
            current_prefs[section].update(values)
        else:
            current_prefs[section] = values
    
    current_user.preferences = current_prefs
    db.commit()
    
    return {"message": "Preferences updated successfully", "preferences": current_prefs}

# ===== DASHBOARD ENDPOINTS =====
@app.get("/dashboard/overview")
async def get_dashboard_overview(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Get dashboard overview with key metrics."""
    from sqlalchemy import func, extract
    from datetime import date, timedelta
    
    # Transaction counts
    total_transactions = db.query(func.count(models.Transaction.id)).filter(
        models.Transaction.owner_id == current_user.id
    ).scalar()
    
    staged_count = db.query(func.count(models.StagedTransaction.id)).filter(
        models.StagedTransaction.owner_id == current_user.id
    ).scalar()
    
    # Financial totals
    income = db.query(func.sum(models.Transaction.amount)).filter(
        models.Transaction.owner_id == current_user.id,
        models.Transaction.amount > 0
    ).scalar() or 0
    
    expenses = db.query(func.sum(models.Transaction.amount)).filter(
        models.Transaction.owner_id == current_user.id,
        models.Transaction.amount < 0
    ).scalar() or 0
    
    # This month's data
    current_month = date.today().replace(day=1)
    month_transactions = db.query(func.count(models.Transaction.id)).filter(
        models.Transaction.owner_id == current_user.id,
        models.Transaction.transaction_date >= current_month
    ).scalar()
    
    month_income = db.query(func.sum(models.Transaction.amount)).filter(
        models.Transaction.owner_id == current_user.id,
        models.Transaction.transaction_date >= current_month,
        models.Transaction.amount > 0
    ).scalar() or 0
    
    month_expenses = db.query(func.sum(models.Transaction.amount)).filter(
        models.Transaction.owner_id == current_user.id,
        models.Transaction.transaction_date >= current_month,
        models.Transaction.amount < 0
    ).scalar() or 0
    
    # Category breakdown
    category_stats = db.query(
        models.Transaction.category,
        func.count(models.Transaction.id).label('count'),
        func.sum(models.Transaction.amount).label('total')
    ).filter(
        models.Transaction.owner_id == current_user.id,
        models.Transaction.category.isnot(None)
    ).group_by(models.Transaction.category).all()
    
    # Duplicate count
    pending_duplicates = db.query(func.count(models.DuplicateGroup.id)).filter(
        models.DuplicateGroup.user_id == current_user.id,
        models.DuplicateGroup.status == models.DuplicateStatus.PENDING
    ).scalar()
    
    # Recent upload sessions
    recent_uploads = db.query(models.UploadSession).filter(
        models.UploadSession.user_id == current_user.id
    ).order_by(models.UploadSession.upload_date.desc()).limit(5).all()
    
    return {
        "totals": {
            "transactions": total_transactions,
            "staged": staged_count,
            "income": float(income),
            "expenses": float(expenses),
            "net_flow": float(income + expenses)
        },
        "this_month": {
            "transactions": month_transactions,
            "income": float(month_income),
            "expenses": float(month_expenses),
            "net_flow": float(month_income + month_expenses)
        },
        "categories": [
            {
                "name": cat.category,
                "count": cat.count,
                "total": float(cat.total)
            }
            for cat in category_stats
        ],
        "pending_duplicates": pending_duplicates,
        "recent_uploads": [
            {
                "id": upload.id,
                "filename": upload.filename,
                "status": upload.status.value,
                "upload_date": upload.upload_date.isoformat(),
                "staged_count": upload.staged_count,
                "approved_count": upload.approved_count
            }
            for upload in recent_uploads
        ]
    }

# ===== ANALYTICS ENDPOINTS =====
@app.get("/analytics/spending-trends")
async def get_spending_trends(
    period: str = "6m",  # 1m, 3m, 6m, 1y
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Get spending trends over time."""
    from sqlalchemy import func, extract
    from datetime import date, timedelta
    
    # Calculate date range
    end_date = date.today()
    if period == "1m":
        start_date = end_date - timedelta(days=30)
        group_by = "day"
    elif period == "3m":
        start_date = end_date - timedelta(days=90)
        group_by = "week"
    elif period == "6m":
        start_date = end_date - timedelta(days=180)
        group_by = "week"
    else:  # 1y
        start_date = end_date - timedelta(days=365)
        group_by = "month"
    
    # Query transactions
    query = db.query(
        models.Transaction.transaction_date,
        func.sum(models.Transaction.amount).label('amount')
    ).filter(
        models.Transaction.owner_id == current_user.id,
        models.Transaction.transaction_date >= start_date,
        models.Transaction.transaction_date <= end_date
    )
    
    if group_by == "month":
        query = query.group_by(
            extract('year', models.Transaction.transaction_date),
            extract('month', models.Transaction.transaction_date)
        )
    elif group_by == "week":
        query = query.group_by(
            extract('year', models.Transaction.transaction_date),
            extract('week', models.Transaction.transaction_date)
        )
    else:  # day
        query = query.group_by(models.Transaction.transaction_date)
    
    results = query.order_by(models.Transaction.transaction_date).all()
    
    return {
        "period": period,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "group_by": group_by,
        "data": [
            {
                "date": result.transaction_date.isoformat(),
                "amount": float(result.amount)
            }
            for result in results
        ]
    }

@app.get("/analytics/category-breakdown")
async def get_category_breakdown(
    period: str = "3m",
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Get category breakdown for pie charts."""
    from sqlalchemy import func
    from datetime import date, timedelta
    
    # Calculate date range
    end_date = date.today()
    if period == "1m":
        start_date = end_date - timedelta(days=30)
    elif period == "3m":
        start_date = end_date - timedelta(days=90)
    elif period == "6m":
        start_date = end_date - timedelta(days=180)
    else:  # 1y
        start_date = end_date - timedelta(days=365)
    
    # Query category breakdown (expenses only)
    results = db.query(
        models.Transaction.category,
        func.count(models.Transaction.id).label('count'),
        func.sum(models.Transaction.amount).label('total')
    ).filter(
        models.Transaction.owner_id == current_user.id,
        models.Transaction.transaction_date >= start_date,
        models.Transaction.transaction_date <= end_date,
        models.Transaction.amount < 0  # Expenses only
    ).group_by(models.Transaction.category).all()
    
    return {
        "period": period,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "categories": [
            {
                "name": result.category or "Uncategorized",
                "count": result.count,
                "total": abs(float(result.total)),
                "percentage": 0  # Will be calculated on frontend
            }
            for result in results
        ]
    }

# ===== SEARCH ENDPOINTS =====
@app.get("/search/transactions")
async def search_transactions(
    q: str,
    limit: int = 50,
    offset: int = 0,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Search transactions by beneficiary, category, or amount."""
    from sqlalchemy import or_, func
    
    # Build search query
    search_terms = q.lower().split()
    conditions = []
    
    for term in search_terms:
        conditions.append(
            or_(
                func.lower(models.Transaction.beneficiary).contains(term),
                func.lower(models.Transaction.category).contains(term),
                models.Transaction.amount == float(term) if term.replace('.', '').replace('-', '').isdigit() else False
            )
        )
    
    query = db.query(models.Transaction).filter(
        models.Transaction.owner_id == current_user.id
    )
    
    for condition in conditions:
        query = query.filter(condition)
    
    total = query.count()
    results = query.order_by(models.Transaction.transaction_date.desc()).offset(offset).limit(limit).all()
    
    return {
        "query": q,
        "total": total,
        "offset": offset,
        "limit": limit,
        "results": [
            {
                "id": txn.id,
                "date": txn.transaction_date.isoformat(),
                "beneficiary": txn.beneficiary,
                "amount": float(txn.amount),
                "category": txn.category,
                "created_at": txn.created_at.isoformat()
            }
            for txn in results
        ]
    }

# ===== HEALTH CHECK =====
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "3.0.0"
    }

@app.get("/")
async def api_root():
    """API root endpoint."""
    return {
        "message": "Expense Tracker 3.0 API",
        "version": "3.0.0",
        "features": [
            "ML-powered categorization",
            "Smart duplicate detection",
            "Real-time progress tracking",
            "Advanced analytics",
            "User-defined categories"
        ],
        "docs": "/docs"
    }

# ===== ERROR HANDLERS =====
@app.exception_handler(404)
async def not_found_handler(request, exc):
    """Handle 404 errors."""
    return {
        "error": "Not Found",
        "message": "The requested resource was not found",
        "status_code": 404
    }

@app.exception_handler(500)
async def internal_error_handler(request, exc):
    """Handle 500 errors."""
    return {
        "error": "Internal Server Error",
        "message": "An unexpected error occurred",
        "status_code": 500
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)