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

# Import and include routers individually with better error handling
routers_status = {}
ROUTERS_AVAILABLE = True

# Upload router
try:
    from .routers import upload
    app.include_router(upload.router, prefix="/upload", tags=["upload"])
    routers_status["upload"] = "✅ loaded"
    print("✅ Upload router loaded successfully")
    
    # Set WebSocket manager for upload router (if function exists)
    try:
        upload.set_websocket_manager(manager)
    except AttributeError:
        print("⚠️  upload.set_websocket_manager() function not found")
except ImportError as e:
    print(f"❌ Upload router import error: {e}")
    routers_status["upload"] = f"❌ failed: {e}"
    ROUTERS_AVAILABLE = False

# Transactions router
try:
    from .routers import transactions
    app.include_router(transactions.router, prefix="/transactions", tags=["transactions"])
    routers_status["transactions"] = "✅ loaded"
    print("✅ Transactions router loaded successfully")
except ImportError as e:
    print(f"❌ Transactions router import error: {e}")
    routers_status["transactions"] = f"❌ failed: {e}"
    ROUTERS_AVAILABLE = False

# Duplicates router - FIXED WITH BETTER ERROR HANDLING
try:
    from .routers import duplicates
    app.include_router(duplicates.router, prefix="/duplicates", tags=["duplicates"])
    routers_status["duplicates"] = "✅ loaded"
    print("✅ Duplicates router loaded successfully")
except ImportError as e:
    print(f"❌ Duplicates router import error: {e}")
    routers_status["duplicates"] = f"❌ failed: {e}"
    ROUTERS_AVAILABLE = False
    
    # Create basic fallback duplicates router if import fails
    from fastapi import APIRouter
    duplicates_fallback = APIRouter()
    
    @duplicates_fallback.get("/")
    async def get_duplicates_fallback(
        limit: int = 50,
        offset: int = 0,
        current_user: models.User = Depends(get_current_user),
        db: Session = Depends(get_db)
    ):
        return {
            "duplicate_groups": [],
            "total": 0,
            "offset": offset,
            "limit": limit,
            "message": "Duplicates router failed to load - using fallback"
        }
    
    @duplicates_fallback.post("/scan/")
    async def scan_duplicates_fallback(
        current_user: models.User = Depends(get_current_user),
        db: Session = Depends(get_db)
    ):
        return {
            "message": "Duplicate scanning not available - router failed to load",
            "groups_found": 0,
            "total_duplicates": 0
        }
    
    app.include_router(duplicates_fallback, prefix="/duplicates", tags=["duplicates"])
    print("⚠️  Using fallback duplicates router")

# Categorization router
try:
    from .routers import categorization
    app.include_router(categorization.router, prefix="/categorization", tags=["categorization"])
    routers_status["categorization"] = "✅ loaded"
    print("✅ Categorization router loaded successfully")
except ImportError as e:
    print(f"❌ Categorization router import error: {e}")
    routers_status["categorization"] = f"❌ failed: {e}"

# Basic fallback for upload if it fails completely
if routers_status.get("upload", "").startswith("❌"):
    from fastapi import APIRouter
    upload_fallback = APIRouter()
    
    @upload_fallback.get("/staged/")
    async def get_staged_fallback(
        limit: int = 25,
        offset: int = 0,
        current_user: models.User = Depends(get_current_user)
    ):
        return {"staged_transactions": [], "total": 0, "offset": offset, "limit": limit}
    
    app.include_router(upload_fallback, prefix="/upload", tags=["upload"])
    print("⚠️  Using fallback upload router")

# ===== AUTHENTICATION ENDPOINTS =====
@app.post("/auth/register")
async def register(user_data: dict, db: Session = Depends(get_db)):
    """Register a new user with default categories."""
    try:
        # Check if user already exists
        existing_user = db.query(models.User).filter(
            models.User.email == user_data["email"]
        ).first()
        
        if existing_user:
            raise HTTPException(
                status_code=400, 
                detail="Email already registered"
            )
        
        # Hash password
        hashed_password = auth.get_password_hash(user_data["password"])
        
        # Create user
        user = models.User(
            email=user_data["email"],
            hashed_password=hashed_password
        )
        
        db.add(user)
        db.commit()
        db.refresh(user)
        
        # Create access token
        access_token = auth.create_access_token(data={"sub": user.email})
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "email": user.email
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")

@app.post("/auth/login")
async def login(user_data: dict, db: Session = Depends(get_db)):
    """Authenticate user and return access token."""
    try:
        # Find user by email
        user = db.query(models.User).filter(
            models.User.email == user_data.get("username", user_data.get("email"))
        ).first()
        
        if not user or not auth.verify_password(user_data["password"], user.hashed_password):
            raise HTTPException(
                status_code=401,
                detail="Incorrect email or password"
            )
        
        # Create access token
        access_token = auth.create_access_token(data={"sub": user.email})
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "email": user.email
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Login failed: {str(e)}")

@app.get("/auth/me")
async def get_current_user_info(
    current_user: models.User = Depends(get_current_user)
):
    """Get current user information."""
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
        "database": "connected",
        "routers_loaded": len([k for k, v in routers_status.items() if v.startswith("✅")])
    }

# ===== DEBUG ENDPOINTS =====
@app.get("/debug/routers")
async def debug_routers():
    """Debug endpoint to check router status."""
    return {
        "routers_status": routers_status,
        "routers_available": ROUTERS_AVAILABLE,
        "websocket_manager": "active",
        "active_connections": len(manager.active_connections),
        "available_routes": [
            {"path": route.path, "methods": list(route.methods)} 
            for route in app.routes 
            if hasattr(route, 'path') and hasattr(route, 'methods')
        ]
    }