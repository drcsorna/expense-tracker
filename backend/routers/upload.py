# backend/routers/upload.py
# Upload-related API routes with staged data processing

import asyncio
from datetime import datetime
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
import json

# Relative imports
from .. import models
from .. import schemas
from ..models import get_db
from ..auth import get_current_user
from ..upload_processor import StagedTransactionProcessor, ProgressTracker

router = APIRouter(
    prefix="/upload",
    tags=["upload"],
    responses={404: {"description": "Not found"}},
)

# Store active WebSocket connections for progress updates
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        self.active_connections[session_id] = websocket

    def disconnect(self, session_id: str):
        if session_id in self.active_connections:
            del self.active_connections[session_id]

    async def send_progress(self, session_id: str, data: dict):
        if session_id in self.active_connections:
            try:
                await self.active_connections[session_id].send_text(json.dumps(data))
            except:
                # Connection is broken, remove it
                self.disconnect(session_id)

manager = ConnectionManager()

@router.websocket("/progress/{session_id}")
async def websocket_progress(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for real-time upload progress."""
    await manager.connect(websocket, session_id)
    try:
        while True:
            # Keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(session_id)

@router.post("/transactions/", response_model=schemas.UploadResult)
async def upload_transactions(
    file: UploadFile = File(...),
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Upload and process transaction files with staged data architecture.
    
    **Enhanced Features:**
    - Real-time progress tracking via WebSocket
    - Staged data processing (parse → stage → review → confirm)
    - Intelligent categorization suggestions
    - Comprehensive audit trail
    - Batch processing for large files
    """
    
    # Validate file
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
    
    # Validate file size (25MB limit)
    MAX_FILE_SIZE = 25 * 1024 * 1024  # 25MB
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File too large. Maximum size is 25MB."
        )
    
    if len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty file provided"
        )
    
    processing_start = datetime.utcnow()
    
    try:
        # Create upload session
        upload_session = models.UploadSession(
            filename=file.filename,
            file_size=len(content),
            file_type=file_extension,
            status=models.UploadStatus.PROCESSING,
            user_id=current_user.id,
            processing_start=processing_start
        )
        db.add(upload_session)
        db.commit()
        db.refresh(upload_session)
        
        # Initialize progress tracker
        progress_tracker = ProgressTracker(
            session_id=str(upload_session.id),
            websocket_manager=manager
        )
        
        # Initialize processor
        processor = StagedTransactionProcessor(progress_tracker=progress_tracker)
        
        # Process file in background
        result = await processor.process_file_to_staged(
            content=content,
            filename=file.filename,
            file_type=file_extension,
            upload_session=upload_session,
            user=current_user,
            db=db
        )
        
        processing_end = datetime.utcnow()
        processing_time = (processing_end - processing_start).total_seconds()
        
        # Update upload session with final results
        upload_session.status = models.UploadStatus.STAGED if result.get('success', False) else models.UploadStatus.FAILED
        upload_session.processing_end = processing_end
        upload_session.total_rows = result.get('total_rows', 0)
        upload_session.staged_count = result.get('staged_count', 0)
        upload_session.error_count = result.get('error_count', 0)
        upload_session.duplicate_count = result.get('duplicate_count', 0)
        
        db.commit()
        
        # Send final progress update
        await progress_tracker.send_final_update({
            "success": result.get('success', False),
            "session_id": upload_session.id,
            "message": "File processing completed"
        })
        
        # Prepare response
        upload_result = schemas.UploadResult(
            success=result.get('success', False),
            session_id=upload_session.id,
            filename=file.filename,
            file_size=len(content),
            total_rows=result.get('total_rows', 0),
            staged_count=result.get('staged_count', 0),
            duplicate_count=result.get('duplicate_count', 0),
            error_count=result.get('error_count', 0),
            errors=result.get('errors', []),
            processing_time_seconds=processing_time,
            format_detected=result.get('format_detected', 'unknown'),
            suggested_actions=[
                "Review staged transactions",
                "Confirm or reject transactions",
                "Update categories if needed"
            ]
        )
        
        return upload_result
        
    except Exception as e:
        # Update upload session on error
        upload_session.status = models.UploadStatus.FAILED
        upload_session.processing_end = datetime.utcnow()
        upload_session.processing_log = {"error": str(e)}
        db.commit()
        
        # Send error update via WebSocket
        if 'progress_tracker' in locals():
            await progress_tracker.send_final_update({
                "success": False,
                "error": str(e),
                "message": "File processing failed"
            })
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"File processing failed: {str(e)}"
        )

@router.post("/validate/", response_model=Dict[str, Any])
async def validate_file_structure(
    file: UploadFile = File(...),
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Validate file structure without full processing.
    Useful for pre-upload validation.
    """
    
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

@router.get("/formats/", response_model=Dict[str, Any])
async def get_supported_formats():
    """
    Get information about supported file formats and their expected structure.
    """
    return {
        "supported_formats": {
            "csv": {
                "extension": ".csv",
                "description": "Comma-separated values",
                "required_columns": ["date", "description/beneficiary", "amount"],
                "optional_columns": ["category", "notes", "labels"]
            },
            "excel": {
                "extensions": [".xls", ".xlsx"],
                "description": "Microsoft Excel files",
                "required_columns": ["date", "description/beneficiary", "amount"],
                "optional_columns": ["category", "notes", "labels"],
                "notes": "First sheet will be used for processing"
            }
        },
        "column_mapping": {
            "date_columns": ["date", "transaction_date", "datum", "fecha"],
            "description_columns": ["description", "beneficiary", "memo", "payee", "vendor"],
            "amount_columns": ["amount", "value", "bedrag", "cantidad"],
            "category_columns": ["category", "type", "categorie", "categoria"]
        },
        "date_formats": [
            "YYYY-MM-DD",
            "DD-MM-YYYY", 
            "MM/DD/YYYY",
            "DD/MM/YYYY",
            "YYYY/MM/DD"
        ],
        "notes": [
            "Files should have headers in the first row",
            "Amounts can be positive (income) or negative (expenses)",
            "Categories will be auto-detected or can be assigned later",
            "Maximum file size: 25MB"
        ]
    }

@router.delete("/sessions/{session_id}")
async def delete_upload_session(
    session_id: int,
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete an upload session and all its associated staged transactions.
    This is useful for cleaning up failed uploads or starting over.
    """
    
    # Find the upload session
    upload_session = db.query(models.UploadSession).filter(
        models.UploadSession.id == session_id,
        models.UploadSession.user_id == current_user.id
    ).first()
    
    if not upload_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload session not found"
        )
    
    try:
        # Delete associated staged transactions first
        staged_count = db.query(models.StagedTransaction).filter(
            models.StagedTransaction.upload_session_id == session_id
        ).count()
        
        db.query(models.StagedTransaction).filter(
            models.StagedTransaction.upload_session_id == session_id
        ).delete()
        
        # Delete the upload session
        db.delete(upload_session)
        db.commit()
        
        return {
            "message": f"Upload session {session_id} deleted successfully",
            "staged_transactions_deleted": staged_count
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete upload session: {str(e)}"
        )

@router.get("/sessions/{session_id}/staged-transactions", response_model=List[schemas.StagedTransaction])
async def get_session_staged_transactions(
    session_id: int,
    skip: int = 0,
    limit: int = 100,
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all staged transactions for a specific upload session.
    """
    
    # Verify session ownership
    upload_session = db.query(models.UploadSession).filter(
        models.UploadSession.id == session_id,
        models.UploadSession.user_id == current_user.id
    ).first()
    
    if not upload_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload session not found"
        )
    
    # Get staged transactions for this session
    staged_transactions = db.query(models.StagedTransaction).filter(
        models.StagedTransaction.upload_session_id == session_id
    ).order_by(models.StagedTransaction.created_at.desc()).offset(skip).limit(limit).all()
    
    return staged_transactions