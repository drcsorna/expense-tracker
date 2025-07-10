# backend/routers/upload.py
# Enhanced upload router with real-time progress tracking and smart processing

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import Dict, List, Optional, Any
from datetime import datetime
import asyncio
import uuid

from .. import models
from ..upload_processor import StagedTransactionProcessor, ProgressTracker
from ..websocket_manager import ConnectionManager

router = APIRouter()

# WebSocket manager instance (will be injected by main app)
manager: ConnectionManager = None

def set_websocket_manager(websocket_manager: ConnectionManager):
    """Set the WebSocket manager instance."""
    global manager
    manager = websocket_manager

async def get_current_user(db: Session = Depends(models.get_db)):
    """Dependency to get current user - simplified for this example."""
    # In production, this would validate JWT token and return actual user
    return db.query(models.User).first()

# ===== FILE UPLOAD ENDPOINTS =====

@router.post("/transactions/")
async def upload_transaction_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    session_id: Optional[str] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Upload and process transaction file with real-time progress tracking."""
    
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
            detail=f"Unsupported file type '{file_extension}'. Allowed: {', '.join(allowed_extensions)}"
        )
    
    # Validate file size (50MB limit)
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File too large. Maximum size is 50MB."
        )
    
    if len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty file provided"
        )
    
    # Generate session ID if not provided
    if not session_id:
        session_id = str(uuid.uuid4())
    
    # Create upload session
    upload_session = models.UploadSession(
        filename=file.filename,
        file_size=len(content),
        file_type=file_extension,
        status=models.UploadStatus.PROCESSING,
        user_id=current_user.id,
        processing_start=datetime.utcnow()
    )
    db.add(upload_session)
    db.commit()
    db.refresh(upload_session)
    
    # Start background processing
    background_tasks.add_task(
        process_file_background,
        upload_session.id,
        session_id,
        content,
        file.filename,
        file_extension,
        current_user.id
    )
    
    return {
        "message": "File upload started",
        "upload_session_id": upload_session.id,
        "session_id": session_id,
        "filename": file.filename,
        "file_size": len(content),
        "status": "processing"
    }

@router.post("/validate/")
async def validate_file_structure(
    file: UploadFile = File(...),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Validate file structure before upload."""
    
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
            detail=f"Unsupported file type '{file_extension}'. Allowed: {', '.join(allowed_extensions)}"
        )
    
    # Read file content (limit to first 5MB for validation)
    content = await file.read()
    validation_content = content[:5 * 1024 * 1024]  # First 5MB
    
    try:
        processor = StagedTransactionProcessor()
        validation_result = await processor.validate_file_structure(
            validation_content, file.filename
        )
        
        return {
            "filename": file.filename,
            "file_size": len(content),
            "validation": validation_result,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File validation failed: {str(e)}"
        )

@router.get("/formats/")
async def get_supported_formats():
    """Get information about supported file formats and their expected structure."""
    
    return {
        "supported_formats": [
            {
                "extension": ".csv",
                "description": "Comma-separated values",
                "mime_types": ["text/csv", "application/csv"],
                "max_size": "50MB"
            },
            {
                "extension": ".xlsx",
                "description": "Excel spreadsheet (modern)",
                "mime_types": ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
                "max_size": "50MB"
            },
            {
                "extension": ".xls",
                "description": "Excel spreadsheet (legacy)",
                "mime_types": ["application/vnd.ms-excel"],
                "max_size": "50MB"
            }
        ],
        "required_columns": [
            {
                "name": "Date",
                "description": "Transaction date",
                "examples": ["2023-12-01", "01/12/2023", "Dec 1, 2023"],
                "required": True
            },
            {
                "name": "Beneficiary/Description",
                "description": "Transaction description or beneficiary",
                "examples": ["AMAZON.COM", "GROCERY STORE", "SALARY DEPOSIT"],
                "required": True
            },
            {
                "name": "Amount",
                "description": "Transaction amount (positive for income, negative for expenses)",
                "examples": ["-125.50", "2500.00", "(125.50)"],
                "required": True
            }
        ],
        "optional_columns": [
            {
                "name": "Category",
                "description": "Transaction category",
                "examples": ["Food", "Transportation", "Income"],
                "required": False
            },
            {
                "name": "Description/Memo",
                "description": "Additional transaction details",
                "examples": ["Weekly grocery shopping", "Monthly salary"],
                "required": False
            }
        ],
        "tips": [
            "Ensure your file has column headers in the first row",
            "Date formats are automatically detected",
            "Amount formats with currency symbols are supported",
            "Categories will be auto-suggested using ML if not provided"
        ]
    }

# ===== PROGRESS TRACKING =====

@router.get("/progress/{session_id}")
async def get_upload_progress(
    session_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Get upload progress for a specific session (fallback for when WebSocket fails)."""
    
    # Find upload session by session_id (stored in processing_log or use latest)
    upload_session = db.query(models.UploadSession).filter(
        models.UploadSession.user_id == current_user.id
    ).order_by(desc(models.UploadSession.upload_date)).first()
    
    if not upload_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload session not found"
        )
    
    # Calculate progress based on status
    progress_data = {
        "session_id": session_id,
        "status": upload_session.status.value,
        "filename": upload_session.filename,
        "upload_date": upload_session.upload_date.isoformat(),
        "processing_start": upload_session.processing_start.isoformat() if upload_session.processing_start else None,
        "processing_end": upload_session.processing_end.isoformat() if upload_session.processing_end else None,
    }
    
    if upload_session.status == models.UploadStatus.PROCESSING:
        # Estimate progress based on processed rows
        if upload_session.total_rows > 0:
            progress_percentage = min(90, (upload_session.processed_rows / upload_session.total_rows) * 90)
        else:
            progress_percentage = 30  # Default progress if no row info
        
        progress_data.update({
            "stage": "processing",
            "progress": progress_percentage,
            "rows_processed": upload_session.processed_rows,
            "total_rows": upload_session.total_rows,
            "message": f"Processing {upload_session.processed_rows}/{upload_session.total_rows} rows"
        })
        
    elif upload_session.status == models.UploadStatus.COMPLETED:
        progress_data.update({
            "stage": "completed",
            "progress": 100.0,
            "final_result": {
                "success": True,
                "total_rows": upload_session.total_rows,
                "processed_rows": upload_session.processed_rows,
                "staged_count": upload_session.staged_count,
                "error_count": upload_session.error_count,
                "duplicate_count": upload_session.duplicate_count,
                "ml_suggestions_count": upload_session.ml_suggestions_count,
                "high_confidence_count": upload_session.high_confidence_suggestions
            }
        })
        
    elif upload_session.status == models.UploadStatus.FAILED:
        progress_data.update({
            "stage": "failed",
            "progress": 0,
            "error": upload_session.error_details.get("error", "Processing failed") if upload_session.error_details else "Processing failed",
            "details": upload_session.error_details or {}
        })
        
    else:  # PENDING, CANCELLED
        progress_data.update({
            "stage": upload_session.status.value,
            "progress": 0,
            "message": f"Status: {upload_session.status.value}"
        })
    
    return progress_data

@router.post("/cancel/{session_id}")
async def cancel_upload(
    session_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Cancel an ongoing upload session."""
    
    # Find the most recent processing session for the user
    upload_session = db.query(models.UploadSession).filter(
        models.UploadSession.user_id == current_user.id,
        models.UploadSession.status == models.UploadStatus.PROCESSING
    ).order_by(desc(models.UploadSession.upload_date)).first()
    
    if not upload_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active upload session found"
        )
    
    # Update session status
    upload_session.status = models.UploadStatus.CANCELLED
    upload_session.processing_end = datetime.utcnow()
    
    db.commit()
    
    # Send cancellation message via WebSocket if available
    if manager:
        await manager.send_personal_message(session_id, {
            "type": "upload_cancelled",
            "session_id": session_id,
            "message": "Upload cancelled by user",
            "timestamp": datetime.utcnow().isoformat()
        })
    
    return {
        "message": "Upload cancelled successfully",
        "session_id": session_id,
        "upload_session_id": upload_session.id
    }

# ===== STAGED TRANSACTIONS MANAGEMENT =====

@router.get("/staged/")
async def get_staged_transactions(
    limit: int = 50,
    offset: int = 0,
    category_filter: Optional[str] = None,
    confidence_min: Optional[float] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Get staged transactions with optional filtering."""
    
    query = db.query(models.StagedTransaction).filter(
        models.StagedTransaction.owner_id == current_user.id
    )
    
    # Apply filters
    if category_filter:
        query = query.filter(models.StagedTransaction.suggested_category == category_filter)
    
    if confidence_min is not None:
        query = query.filter(models.StagedTransaction.confidence >= confidence_min)
    
    # Get total count
    total_count = query.count()
    
    # Apply pagination and ordering
    staged_transactions = query.order_by(
        desc(models.StagedTransaction.confidence),
        desc(models.StagedTransaction.created_at)
    ).offset(offset).limit(limit).all()
    
    # Format response
    result = []
    for staged in staged_transactions:
        result.append({
            "id": staged.id,
            "transaction_date": staged.transaction_date.isoformat(),
            "beneficiary": staged.beneficiary,
            "amount": float(staged.amount),
            "description": staged.description,
            "suggested_category": staged.suggested_category,
            "suggested_category_id": staged.suggested_category_id,
            "confidence": staged.confidence,
            "confidence_level": staged.confidence_level.value if staged.confidence_level else None,
            "alternative_suggestions": staged.alternative_suggestions,
            "requires_review": staged.requires_review,
            "auto_approve_eligible": staged.auto_approve_eligible,
            "processing_notes": staged.processing_notes,
            "created_at": staged.created_at.isoformat()
        })
    
    return {
        "total": total_count,
        "offset": offset,
        "limit": limit,
        "staged_transactions": result
    }

@router.post("/staged/{staged_id}/approve")
async def approve_staged_transaction(
    staged_id: int,
    approval_data: Optional[dict] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Approve a staged transaction and move it to permanent transactions."""
    
    staged = db.query(models.StagedTransaction).filter(
        models.StagedTransaction.id == staged_id,
        models.StagedTransaction.owner_id == current_user.id
    ).first()
    
    if not staged:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Staged transaction not found"
        )
    
    # Get approval details
    category = approval_data.get("category") if approval_data else staged.suggested_category
    notes = approval_data.get("notes", "") if approval_data else ""
    
    # Create permanent transaction
    transaction = models.Transaction(
        transaction_date=staged.transaction_date,
        beneficiary=staged.beneficiary,
        amount=staged.amount,
        category=category,
        description=staged.description,
        categorization_method="ml_auto" if category == staged.suggested_category else "manual",
        categorization_confidence=staged.confidence,
        manual_review_required=False,
        raw_data=staged.raw_data,
        file_hash=staged.file_hash,
        notes=notes,
        owner_id=current_user.id,
        upload_session_id=staged.upload_session_id
    )
    
    db.add(transaction)
    
    # Update upload session metrics
    if staged.upload_session_id:
        upload_session = db.query(models.UploadSession).filter(
            models.UploadSession.id == staged.upload_session_id
        ).first()
        if upload_session:
            upload_session.approved_count += 1
    
    # Record ML feedback if category was changed
    if category != staged.suggested_category:
        from ..ml_categorizer import MLCategorizer
        ml_categorizer = MLCategorizer(current_user.id, db)
        await ml_categorizer.learn_from_correction({
            "beneficiary": staged.beneficiary,
            "amount": float(staged.amount),
            "suggested_category": staged.suggested_category,
            "confidence": staged.confidence
        }, category, True)
    
    # Delete staged transaction
    db.delete(staged)
    db.commit()
    
    return {
        "message": "Transaction approved successfully",
        "transaction_id": transaction.id,
        "category": category,
        "ml_feedback_recorded": category != staged.suggested_category
    }

@router.post("/staged/bulk-approve")
async def bulk_approve_staged_transactions(
    approval_data: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Bulk approve multiple staged transactions."""
    
    staged_ids = approval_data.get("staged_ids", [])
    default_category = approval_data.get("default_category")
    auto_approve_high_confidence = approval_data.get("auto_approve_high_confidence", False)
    confidence_threshold = approval_data.get("confidence_threshold", 0.9)
    
    if not staged_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No staged transaction IDs provided"
        )
    
    # Get staged transactions
    staged_transactions = db.query(models.StagedTransaction).filter(
        models.StagedTransaction.id.in_(staged_ids),
        models.StagedTransaction.owner_id == current_user.id
    ).all()
    
    if len(staged_transactions) != len(staged_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Some staged transactions not found"
        )
    
    approved_count = 0
    skipped_count = 0
    
    for staged in staged_transactions:
        # Determine category
        if auto_approve_high_confidence and staged.confidence and staged.confidence >= confidence_threshold:
            category = staged.suggested_category
        elif default_category:
            category = default_category
        else:
            category = staged.suggested_category
        
        if not category:
            skipped_count += 1
            continue
        
        # Create permanent transaction
        transaction = models.Transaction(
            transaction_date=staged.transaction_date,
            beneficiary=staged.beneficiary,
            amount=staged.amount,
            category=category,
            description=staged.description,
            categorization_method="ml_auto" if category == staged.suggested_category else "manual",
            categorization_confidence=staged.confidence,
            raw_data=staged.raw_data,
            file_hash=staged.file_hash,
            owner_id=current_user.id,
            upload_session_id=staged.upload_session_id
        )
        
        db.add(transaction)
        approved_count += 1
    
    # Delete approved staged transactions
    db.query(models.StagedTransaction).filter(
        models.StagedTransaction.id.in_([s.id for s in staged_transactions if s.suggested_category or default_category])
    ).delete(synchronize_session=False)
    
    db.commit()
    
    return {
        "message": f"Bulk approval completed",
        "approved_count": approved_count,
        "skipped_count": skipped_count,
        "total_processed": len(staged_transactions)
    }

@router.delete("/staged/{staged_id}")
async def delete_staged_transaction(
    staged_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Delete a staged transaction."""
    
    staged = db.query(models.StagedTransaction).filter(
        models.StagedTransaction.id == staged_id,
        models.StagedTransaction.owner_id == current_user.id
    ).first()
    
    if not staged:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Staged transaction not found"
        )
    
    db.delete(staged)
    db.commit()
    
    return {"message": "Staged transaction deleted successfully"}

@router.delete("/staged/bulk-delete")
async def bulk_delete_staged_transactions(
    delete_data: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Bulk delete multiple staged transactions."""
    
    staged_ids = delete_data.get("staged_ids", [])
    
    if not staged_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No staged transaction IDs provided"
        )
    
    # Delete staged transactions
    deleted_count = db.query(models.StagedTransaction).filter(
        models.StagedTransaction.id.in_(staged_ids),
        models.StagedTransaction.owner_id == current_user.id
    ).delete(synchronize_session=False)
    
    db.commit()
    
    return {
        "message": "Bulk deletion completed",
        "deleted_count": deleted_count
    }

# ===== UPLOAD HISTORY =====

@router.get("/history/")
async def get_upload_history(
    limit: int = 20,
    offset: int = 0,
    status_filter: Optional[str] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Get upload history for the user."""
    
    query = db.query(models.UploadSession).filter(
        models.UploadSession.user_id == current_user.id
    )
    
    # Apply status filter
    if status_filter:
        try:
            status_enum = models.UploadStatus(status_filter.lower())
            query = query.filter(models.UploadSession.status == status_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status filter: {status_filter}"
            )
    
    # Get total count
    total_count = query.count()
    
    # Apply pagination and ordering
    upload_sessions = query.order_by(
        desc(models.UploadSession.upload_date)
    ).offset(offset).limit(limit).all()
    
    # Format response
    result = []
    for session in upload_sessions:
        result.append({
            "id": session.id,
            "filename": session.filename,
            "upload_date": session.upload_date.isoformat(),
            "file_size": session.file_size,
            "file_type": session.file_type,
            "status": session.status.value,
            "total_rows": session.total_rows,
            "processed_rows": session.processed_rows,
            "staged_count": session.staged_count,
            "approved_count": session.approved_count,
            "error_count": session.error_count,
            "duplicate_count": session.duplicate_count,
            "ml_suggestions_count": session.ml_suggestions_count,
            "high_confidence_suggestions": session.high_confidence_suggestions,
            "format_detected": session.format_detected,
            "processing_start": session.processing_start.isoformat() if session.processing_start else None,
            "processing_end": session.processing_end.isoformat() if session.processing_end else None,
            "processing_time_seconds": session.processing_time_seconds
        })
    
    return {
        "total": total_count,
        "offset": offset,
        "limit": limit,
        "upload_history": result
    }

# ===== BACKGROUND PROCESSING =====

async def process_file_background(
    upload_session_id: int,
    session_id: str, 
    content: bytes,
    filename: str,
    file_type: str,
    user_id: int
):
    """Background task for processing uploaded files."""
    
    # Get database session
    db = next(models.get_db())
    
    try:
        # Get upload session and user
        upload_session = db.query(models.UploadSession).filter(
            models.UploadSession.id == upload_session_id
        ).first()
        
        user = db.query(models.User).filter(models.User.id == user_id).first()
        
        if not upload_session or not user:
            raise Exception("Upload session or user not found")
        
        # Create progress tracker
        progress_tracker = ProgressTracker(session_id, manager)
        
        # Create processor
        processor = StagedTransactionProcessor(progress_tracker=progress_tracker)
        
        # Process file
        result = await processor.process_file_to_staged(
            content=content,
            filename=filename,
            file_type=file_type,
            upload_session=upload_session,
            user=user,
            db=db
        )
        
        # Send completion notification
        if manager:
            await manager.send_completion(session_id, result)
        
    except Exception as e:
        # Handle errors
        upload_session = db.query(models.UploadSession).filter(
            models.UploadSession.id == upload_session_id
        ).first()
        
        if upload_session:
            upload_session.status = models.UploadStatus.FAILED
            upload_session.processing_end = datetime.utcnow()
            upload_session.error_details = {"error": str(e)}
            db.commit()
        
        if manager:
            await manager.send_error(session_id, str(e), {"upload_session_id": upload_session_id})
    
    finally:
        db.close()