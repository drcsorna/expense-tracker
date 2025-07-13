# backend/dependencies.py
# Shared FastAPI dependencies for authentication and database

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional

from . import models, auth

# Security
security = HTTPBearer()

# ===== DATABASE DEPENDENCY =====
def get_db():
    """Database session dependency."""
    db = models.SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ===== AUTHENTICATION DEPENDENCIES =====
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> models.User:
    """Get current authenticated user from JWT token."""
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

async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db)
) -> Optional[models.User]:
    """Get current user if authenticated, None if not (for optional auth endpoints)."""
    if not credentials:
        return None
    
    try:
        return await get_current_user(credentials, db)
    except HTTPException:
        return None

# ===== ADMIN DEPENDENCIES =====
async def get_admin_user(
    current_user: models.User = Depends(get_current_user)
) -> models.User:
    """Require admin user for admin-only endpoints."""
    if not getattr(current_user, 'is_admin', False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user

# ===== PAGINATION DEPENDENCIES =====
def get_pagination_params(
    offset: int = 0,
    limit: int = 50
) -> dict:
    """Get pagination parameters with validation."""
    if offset < 0:
        offset = 0
    if limit < 1:
        limit = 50
    if limit > 1000:  # Prevent excessive queries
        limit = 1000
    
    return {"offset": offset, "limit": limit}