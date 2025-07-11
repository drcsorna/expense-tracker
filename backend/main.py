# backend/main.py
# Enhanced FastAPI application with all 2025 features + FIXED /auth/me endpoint

from fastapi import FastAPI, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from datetime import datetime, timedelta, date
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
    allow_origins=[
        "http://localhost:3000", 
        "http://127.0.0.1:3000", 
        "http://localhost:8080",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://192.168.10.160:8680",
        "http://192.168.10.160:8000",
        "*"  # For development only
    ],
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
        return {"staged_transactions": [], "total": 0, "offset": 0, "limit": 50}
    
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
    
    # Create default categories (if function exists)
    try:
        await models.create_default_categories(db, new_user.id)
    except:
        pass  # Skip if function doesn't exist
    
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
    
    # Check if user is active (if field exists)
    try:
        if hasattr(user, 'is_active') and not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account is deactivated"
            )
    except:
        pass  # Skip if field doesn't exist
    
    # Create access token
    access_token = auth.create_access_token(data={"sub": user.email})
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "created_at": user.created_at.isoformat() if hasattr(user, 'created_at') and user.created_at else datetime.utcnow().isoformat()
        }
    }

# ===== MISSING /auth/me ENDPOINT - THIS FIXES THE 500 ERROR =====
@app.get("/auth/me")
async def get_current_user_info(
    current_user: models.User = Depends(get_current_user)
):
    """Get current authenticated user information - FIXES THE 500 ERROR."""
    return {
        "id": current_user.id,
        "email": current_user.email,
        "created_at": current_user.created_at.isoformat() if hasattr(current_user, 'created_at') and current_user.created_at else datetime.utcnow().isoformat(),
        "last_login": current_user.last_login.isoformat() if hasattr(current_user, 'last_login') and current_user.last_login else None,
        "is_active": getattr(current_user, 'is_active', True),
        "preferences": getattr(current_user, 'preferences', {})
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
        "preferences": getattr(current_user, 'preferences', {}),
        "created_at": current_user.created_at.isoformat() if hasattr(current_user, 'created_at') and current_user.created_at else datetime.utcnow().isoformat(),
        "last_login": current_user.last_login.isoformat() if hasattr(current_user, 'last_login') and current_user.last_login else None
    }

@app.put("/user/preferences")
async def update_user_preferences(
    preferences: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Update user preferences."""
    # Merge with existing preferences
    current_prefs = getattr(current_user, 'preferences', {}) or {}
    
    # Update specific sections
    for section, values in preferences.items():
        if section in current_prefs:
            current_prefs[section].update(values)
        else:
            current_prefs[section] = values
    
    # Update user preferences if field exists
    if hasattr(current_user, 'preferences'):
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
    try:
        # Transaction counts
        total_transactions = db.query(func.count(models.Transaction.id)).filter(
            models.Transaction.owner_id == current_user.id
        ).scalar() or 0
        
        # Staged transactions count (if table exists)
        staged_count = 0
        try:
            staged_count = db.query(func.count(models.StagedTransaction.id)).filter(
                models.StagedTransaction.owner_id == current_user.id
            ).scalar() or 0
        except:
            pass  # Table might not exist
        
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
        ).scalar() or 0
        
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
        
        return {
            "totals": {
                "transactions": total_transactions,
                "staged": staged_count,
                "income": float(income),
                "expenses": float(expenses),
                "net": float(income + expenses)
            },
            "current_month": {
                "transactions": month_transactions,
                "income": float(month_income),
                "expenses": float(month_expenses),
                "net": float(month_income + month_expenses)
            },
            "user": {
                "id": current_user.id,
                "email": current_user.email,
                "member_since": current_user.created_at.isoformat() if hasattr(current_user, 'created_at') and current_user.created_at else datetime.utcnow().isoformat()
            }
        }
    except Exception as e:
        # Return basic data if there are any errors
        return {
            "totals": {
                "transactions": 0,
                "staged": 0,
                "income": 0.0,
                "expenses": 0.0,
                "net": 0.0
            },
            "current_month": {
                "transactions": 0,
                "income": 0.0,
                "expenses": 0.0,
                "net": 0.0
            },
            "user": {
                "id": current_user.id,
                "email": current_user.email,
                "member_since": datetime.utcnow().isoformat()
            },
            "error": f"Dashboard calculation error: {str(e)}"
        }

# ===== HEALTH CHECK =====
@app.get("/")
async def root():
    """Root endpoint with basic info."""
    return {
        "message": "💰 Expense Tracker 3.0 API",
        "version": "3.0.0",
        "docs": "/docs",
        "status": "running"
    }

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": "3.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "routers_available": ROUTERS_AVAILABLE
    }