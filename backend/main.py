# backend/main.py
# Enhanced FastAPI application with fixed import structure

from fastapi import FastAPI, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import json
import asyncio
from typing import Dict, List, Optional, Any

# Import modules
from . import models, auth
from .dependencies import get_current_user, get_db
from .websocket_manager import ConnectionManager

# Import routers
try:
    from .routers import upload, categorization, duplicates, transactions
    ROUTERS_AVAILABLE = True
except ImportError as e:
    print(f"⚠️  Router import error: {e}")
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

# WebSocket manager
manager = ConnectionManager()

# Create database tables
models.create_tables()

# Include routers if available
if ROUTERS_AVAILABLE:
    app.include_router(upload.router, prefix="/upload", tags=["upload"])
    app.include_router(categorization.router, prefix="/categorization", tags=["categorization"])
    app.include_router(duplicates.router, prefix="/duplicates", tags=["duplicates"])
    app.include_router(transactions.router, prefix="/transactions", tags=["transactions"])
    
    # Set WebSocket manager for upload router (if function exists)
    try:
        upload.set_websocket_manager(manager)
    except AttributeError:
        print("⚠️  upload.set_websocket_manager() function not found - WebSocket may not work")
else:
    # Basic fallback router
    from fastapi import APIRouter
    basic_router = APIRouter()
    
    @basic_router.get("/staged/")
    async def get_staged_basic():
        return {"staged_transactions": [], "total": 0, "offset": 0, "limit": 50}
    
    app.include_router(basic_router, prefix="/upload", tags=["upload"])

# ===== AUTHENTICATION ENDPOINTS =====
@app.post("/auth/register")
async def register(user_data: dict, db: Session = Depends(get_db)):
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
async def login(form_data: dict, db: Session = Depends(get_db)):
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

@app.get("/auth/me")
async def get_current_user_info(
    current_user: models.User = Depends(get_current_user)
):
    """Get current authenticated user information."""
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
    try:
        # Optional: Validate token for WebSocket connections
        # For now, accepting all connections but could add auth here
        
        await manager.connect(websocket, session_id)
        
        # Keep connection alive and handle messages
        while True:
            try:
                # Wait for messages (ping/pong, etc.)
                data = await websocket.receive_text()
                message = json.loads(data)
                
                # Handle different message types
                if message.get("type") == "ping":
                    await manager.send_personal_message(session_id, {
                        "type": "pong",
                        "timestamp": datetime.utcnow().isoformat()
                    })
                
            except WebSocketDisconnect:
                break
            except Exception as e:
                print(f"WebSocket message error: {e}")
                break
    
    except Exception as e:
        print(f"WebSocket connection error: {e}")
    finally:
        manager.disconnect(session_id)

# ===== HEALTH CHECK =====
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "3.0.0",
        "database": "connected"
    }

# ===== DEBUG ENDPOINTS =====
@app.get("/debug/routers")
async def debug_routers():
    """Debug endpoint to check router status."""
    router_status = {}
    
    if ROUTERS_AVAILABLE:
        router_status["upload"] = "loaded"
        router_status["categorization"] = "loaded"
        router_status["duplicates"] = "loaded"
        router_status["transactions"] = "loaded"
    else:
        router_status["status"] = "fallback - routers not loaded"
    
    return {
        "routers_available": ROUTERS_AVAILABLE,
        "router_status": router_status,
        "websocket_manager": "active",
        "active_connections": len(manager.active_connections)
    }