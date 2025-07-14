# backend/routers/upload.py
# Fixed upload router with proper authentication imports

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import Dict, List, Optional, Any
from datetime import datetime
import json
import hashlib

from .. import models, auth
from ..dependencies import get_current_user, get_db

router = APIRouter()

# Global WebSocket manager (set by main.py)
websocket_manager = None

def set_websocket_manager(manager):
    """Set the WebSocket manager for real-time updates."""
    global websocket_manager
    websocket_manager = manager

# ===== STAGE 1: RAW FILE UPLOAD =====

@router.post("/raw/")
async def upload_raw_file(
    file: UploadFile = File(...),
    file_type: str = "transaction_data",  # transaction_data, training_data
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Stage 1: Upload raw file for processing (immutable storage)."""
    
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No file provided"
        )
    
    # Validate file type
    allowed_extensions = {'.csv', '.xls', '.xlsx'}
    file_extension = '.' + file.filename.split('.')[-1].lower()
    
    if file_extension not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type {file_extension} not supported. Allowed: {', '.join(allowed_extensions)}"
        )
    
    # Read file content
    try:
        file_content = await file.read()
        file_size = len(file_content)
        
        # Create content hash for duplicate detection
        content_hash = hashlib.sha256(file_content).hexdigest()
        
        # Check for duplicate files
        existing_file = db.query(models.RawFile).filter(
            models.RawFile.content_hash == content_hash,
            models.RawFile.user_id == current_user.id
        ).first()
        
        if existing_file:
            return {
                "message": "File already uploaded",
                "file_id": existing_file.id,
                "filename": existing_file.original_filename,
                "upload_date": existing_file.upload_date.isoformat(),
                "duplicate": True
            }
        
        # Create raw file record
        # Create raw file record
        raw_file = models.RawFile(
            filename=f"raw_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{file.filename}",
            original_filename=file.filename,
            file_content=file_content,
            file_size=file_size,
            file_type=file_extension,
            content_hash=content_hash,
            detected_file_type=models.FileType(file_type),  # ← FIXED
            user_id=current_user.id
        )
        
        db.add(raw_file)
        db.commit()
        db.refresh(raw_file)
        
        return {
            "message": "File uploaded successfully",
            "file_id": raw_file.id,
            "filename": raw_file.original_filename,
            "file_size": file_size,
            "file_type": file_extension,
            "upload_date": raw_file.upload_date.isoformat(),
            "duplicate": False
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"File upload failed: {str(e)}"
        )

# ===== STAGE 2: PROCESSING CONFIGURATION & EXECUTION =====

@router.post("/processing/configure/{file_id}")
async def configure_processing(
    file_id: int,
    config: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Configure how to process a raw file."""
    
    # Get raw file
    raw_file = db.query(models.RawFile).filter(
        models.RawFile.id == file_id,
        models.RawFile.user_id == current_user.id
    ).first()
    
    if not raw_file:
        raise HTTPException(status_code=404, detail="Raw file not found")
    
    # Create processing session
    session_id = auth.generate_session_id()
    
    processing_session = models.ProcessingSession(
        session_id=session_id,
        raw_file_id=file_id,
        configuration=config,
        user_id=current_user.id
    )
    
    db.add(processing_session)
    db.commit()
    db.refresh(processing_session)
    
    return {
        "session_id": session_id,
        "message": "Processing session configured",
        "configuration": config
    }

@router.post("/processing/start/{session_id}")
async def start_processing(
    session_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Start processing a configured session."""
    
    # Get processing session
    session = db.query(models.ProcessingSession).filter(
        models.ProcessingSession.session_id == session_id,
        models.ProcessingSession.user_id == current_user.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Processing session not found")
    
    # Update session status
    session.status = models.ProcessingStatus.PROCESSING
    session.started_at = datetime.utcnow()
    db.commit()
    
    # Start background processing (simplified for now)
    try:
        # TODO: Implement actual file processing with ML categorization
        # For now, just mark as processed
        session.status = models.ProcessingStatus.PROCESSED
        session.completed_at = datetime.utcnow()
        session.rows_processed = 10  # Placeholder
        session.rows_with_suggestions = 8  # Placeholder
        db.commit()
        
        return {
            "message": "Processing started",
            "session_id": session_id,
            "status": "processing"
        }
        
    except Exception as e:
        session.status = models.ProcessingStatus.FAILED
        session.error_message = str(e)
        db.commit()
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Processing failed: {str(e)}"
        )

@router.get("/processing/status/{session_id}")
async def get_processing_status(
    session_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get processing status for a session."""
    
    session = db.query(models.ProcessingSession).filter(
        models.ProcessingSession.session_id == session_id,
        models.ProcessingSession.user_id == current_user.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Processing session not found")
    
    return {
        "session_id": session_id,
        "status": session.status.value,
        "rows_processed": session.rows_processed or 0,
        "total_rows_found": session.total_rows or 0,
        "rows_with_suggestions": session.rows_with_suggestions or 0,
        "started_at": session.started_at.isoformat() if session.started_at else None,
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        "error_message": session.error_message
    }

# ===== STAGE 3: STAGED TRANSACTIONS (Review & Confirm) =====

@router.get("/staged/")
async def get_staged_transactions(
    offset: int = 0,
    limit: int = 50,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get staged transactions for review."""
    
    # Get staged transactions
    staged_transactions = db.query(models.StagedTransaction).filter(
        models.StagedTransaction.user_id == current_user.id,
        models.StagedTransaction.status == models.TransactionStatus.STAGED
    ).offset(offset).limit(limit).all()
    
    # Get total count
    total = db.query(func.count(models.StagedTransaction.id)).filter(
        models.StagedTransaction.user_id == current_user.id,
        models.StagedTransaction.status == models.TransactionStatus.STAGED
    ).scalar()
    
    return {
        "staged_transactions": [
            {
                "id": t.id,
                "transaction_date": t.transaction_date.isoformat(),
                "beneficiary": t.beneficiary,
                "amount": float(t.amount),
                "suggested_category": t.suggested_category,
                "confidence_score": float(t.confidence_score) if t.confidence_score else 0.0,
                "notes": t.notes,
                "created_at": t.created_at.isoformat()
            }
            for t in staged_transactions
        ],
        "total": total,
        "offset": offset,
        "limit": limit
    }

@router.post("/staged/{transaction_id}/approve")
async def approve_staged_transaction(
    transaction_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Approve a staged transaction and move to confirmed transactions."""
    
    # Get staged transaction
    staged = db.query(models.StagedTransaction).filter(
        models.StagedTransaction.id == transaction_id,
        models.StagedTransaction.user_id == current_user.id,
        models.StagedTransaction.status == models.TransactionStatus.STAGED
    ).first()
    
    if not staged:
        raise HTTPException(status_code=404, detail="Staged transaction not found")
    
    # Create confirmed transaction
    confirmed = models.Transaction(
        transaction_date=staged.transaction_date,
        beneficiary=staged.beneficiary,
        amount=staged.amount,
        category=staged.suggested_category,
        notes=staged.notes,
        owner_id=current_user.id
    )
    
    db.add(confirmed)
    
    # Update staged transaction status
    staged.status = models.TransactionStatus.CONFIRMED
    staged.confirmed_at = datetime.utcnow()
    
    db.commit()
    
    return {
        "message": "Transaction approved",
        "transaction_id": confirmed.id
    }

@router.delete("/staged/{transaction_id}")
async def delete_staged_transaction(
    transaction_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a staged transaction."""
    
    staged = db.query(models.StagedTransaction).filter(
        models.StagedTransaction.id == transaction_id,
        models.StagedTransaction.user_id == current_user.id
    ).first()
    
    if not staged:
        raise HTTPException(status_code=404, detail="Staged transaction not found")
    
    db.delete(staged)
    db.commit()
    
    return {"message": "Staged transaction deleted"}

# ===== LEGACY BOOTSTRAP ENDPOINT (For Compatibility) =====

@router.post("/bootstrap/")
async def bootstrap_categories_from_file(
    file: UploadFile = File(...),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Legacy bootstrap endpoint - uploads Hungarian training data."""
    
    # Use the raw upload endpoint internally
    upload_result = await upload_raw_file(file, "training_data", current_user, db)
    
    return {
        "message": "Bootstrap file uploaded - use training data workflow to process",
        "file_id": upload_result["file_id"],
        "filename": upload_result["filename"],
        "next_steps": [
            "1. Configure training data extraction",
            "2. Process patterns and category mappings", 
            "3. Enable smart categorization for new uploads"
        ]
    }

# ===== DEBUG ENDPOINTS =====

@router.get("/debug/files")
async def debug_raw_files(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Debug endpoint to see all raw files."""
    
    files = db.query(models.RawFile).filter(
        models.RawFile.user_id == current_user.id
    ).order_by(models.RawFile.upload_date.desc()).limit(10).all()
    
    return {
        "raw_files": [
            {
                "id": f.id,
                "filename": f.original_filename,
                "file_type": f.file_type,
                "file_size": f.file_size,
                "upload_date": f.upload_date.isoformat(),
                "detected_type": f.detected_file_type.value if f.detected_file_type else None
            }
            for f in files
        ]
    }