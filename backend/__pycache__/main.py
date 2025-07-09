# backend/main.py
# Main FastAPI app instance and core setup

from datetime import datetime, timedelta
from typing import List
import os

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

# Import our modules (relative imports since we're in the backend folder)
import models
import schemas
from models import engine, get_db
from auth import get_current_user, verify_password, get_password_hash, create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES

# Import routers
from routers import upload

# --- Application Setup ---

# Create the database tables if they don't exist on startup
models.Base.metadata.create_all(bind=engine)

# Initialize the FastAPI app
app = FastAPI(
    title="Expense Tracker API",
    description="A comprehensive expense tracking application with user authentication and file upload",
    version="1.0.0"
)

# --- CORS Middleware ---
# More flexible CORS configuration for development
origins = [
    "http://localhost",
    "http://localhost:3000",  # Default Next.js port
    "http://localhost:8000",  # FastAPI default
    "http://127.0.0.1:8000",
    "http://127.0.0.1:3000",
    # Add your specific development server if needed
    "http://192.168.10.160:8680",  # Your code-server proxy
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # More permissive for development - restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Static Files ---
# Serve the frontend directory as static files
frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")

# --- Include Routers ---
app.include_router(upload.router)

# --- Core API Endpoints ---

@app.get("/")
def read_root():
    """Root endpoint - can serve the frontend or API info."""
    # Check for frontend index.html
    frontend_index = os.path.join(frontend_path, "index.html")
    if os.path.exists(frontend_index):
        return FileResponse(frontend_index)
    
    # Otherwise, return API info
    return {
        "message": "Welcome to the Expense Tracker API",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "documentation": "/docs",
            "health": "/health",
            "create_user": "/users/",
            "login": "/token",
            "transactions": "/transactions/",
            "upload": "/upload/transactions/",
            "frontend": "/static/index.html"
        }
    }

@app.get("/app")
def serve_frontend():
    """Explicitly serve the frontend application."""
    frontend_index = os.path.join(frontend_path, "index.html")
    if os.path.exists(frontend_index):
        return FileResponse(frontend_index)
    else:
        raise HTTPException(status_code=404, detail="Frontend not found")

@app.get("/health")
def health_check():
    """Health check endpoint for monitoring."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "expense-tracker-api",
        "version": "1.0.0"
    }

@app.post("/token", response_model=schemas.Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Takes email (as username) and password, and returns an access token on success."""
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
    """Creates a new user in the database."""
    db_user = db.query(models.User).filter(models.User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    hashed_password = get_password_hash(user.password)
    db_user = models.User(email=user.email, hashed_password=hashed_password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

@app.get("/transactions/", response_model=List[schemas.Transaction])
def read_transactions(
    skip: int = 0,
    limit: int = 100,
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Retrieves a list of transactions for the currently authenticated user."""
    transactions = db.query(models.Transaction).filter(
        models.Transaction.owner_id == current_user.id
    ).order_by(models.Transaction.transaction_date.desc()).offset(skip).limit(limit).all()
    return transactions

@app.post("/transactions/", response_model=schemas.Transaction)
def create_transaction(
    transaction: schemas.TransactionCreate,
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Creates a new transaction for the currently authenticated user."""
    db_transaction = models.Transaction(**transaction.dict(), owner_id=current_user.id)
    db.add(db_transaction)
    db.commit()
    db.refresh(db_transaction)
    return db_transaction

@app.get("/transactions/{transaction_id}", response_model=schemas.Transaction)
def read_transaction(
    transaction_id: int,
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Retrieves a specific transaction by ID."""
    transaction = db.query(models.Transaction).filter(
        models.Transaction.id == transaction_id,
        models.Transaction.owner_id == current_user.id
    ).first()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return transaction

@app.delete("/transactions/{transaction_id}")
def delete_transaction(
    transaction_id: int,
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Deletes a specific transaction by ID."""
    transaction = db.query(models.Transaction).filter(
        models.Transaction.id == transaction_id,
        models.Transaction.owner_id == current_user.id
    ).first()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    db.delete(transaction)
    db.commit()
    return {"message": "Transaction deleted successfully"}