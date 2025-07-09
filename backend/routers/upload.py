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

@router.post("/transactions/")
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
    
    try:
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
        
        # Update upload session with final results
        upload_session.status = models.UploadStatus.STAGED if result['success'] else models.UploadStatus.FAILED
        upload_session.processing_end = datetime.utcnow()
        upload_session.total_rows = result.get('total_rows', 0)
        upload_session.staged_count = result.get('staged_count', 0)
        upload_session.error_count = result.get('error_count', 0)
        upload_session.duplicate_count = result.get('duplicate_count', 0)
        upload_session.format_detected = result.get('format_detected', 'unknown')
        upload_session.processing_log = {
            'result': result,
            'processing_time': (upload_session.processing_end - upload_session.processing_start).total_seconds()
        }
        
        db.commit()
        
        # Send final progress update
        await progress_tracker.send_final_update(result)
        
        return {
            "success": result['success'],
            "session_id": upload_session.id,
            "filename": file.filename,
            "file_size": len(content),
            "total_rows": result.get('total_rows', 0),
            "staged_count": result.get('staged_count', 0),
            "duplicate_count": result.get('duplicate_count', 0),
            "error_count": result.get('error_count', 0),
            "errors": result.get('errors', []),
            "processing_time_seconds": upload_session.processing_log['processing_time'],
            "format_detected": result.get('format_detected', 'unknown'),
            "suggested_actions": [
                "Review staged transactions in the staging area",
                "Confirm or reject transactions individually",
                "Use bulk actions for faster processing",
                "Check categorization suggestions"
            ] if result['success'] else [
                "Check file format and content",
                "Ensure file has required columns",
                "Try a different file format"
            ]
        }
        
    except ValueError as e:
        # Update session status on error
        if 'upload_session' in locals():
            upload_session.status = models.UploadStatus.FAILED
            upload_session.processing_end = datetime.utcnow()
            upload_session.processing_log = {'error': str(e)}
            db.commit()
        
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File processing error: {str(e)}"
        )
    except Exception as e:
        # Update session status on error
        if 'upload_session' in locals():
            upload_session.status = models.UploadStatus.FAILED
            upload_session.processing_end = datetime.utcnow()
            upload_session.processing_log = {'error': str(e)}
            db.commit()
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error during file processing: {str(e)}"
        )

@router.get("/progress/{session_id}")
async def get_upload_progress(
    session_id: int,
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get current upload progress for a session."""
    session = db.query(models.UploadSession).filter(
        models.UploadSession.id == session_id,
        models.UploadSession.user_id == current_user.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Upload session not found")
    
    # Calculate progress percentage
    progress_percentage = 0.0
    current_stage = "pending"
    
    if session.status == models.UploadStatus.PROCESSING:
        progress_percentage = min((session.processed_rows / max(session.total_rows, 1)) * 100, 95)
        current_stage = "processing"
    elif session.status == models.UploadStatus.STAGED:
        progress_percentage = 100.0
        current_stage = "completed"
    elif session.status == models.UploadStatus.FAILED:
        current_stage = "failed"
    
    return {
        "session_id": session.id,
        "filename": session.filename,
        "progress_percentage": progress_percentage,
        "current_stage": current_stage,
        "rows_processed": session.processed_rows,
        "total_rows": session.total_rows,
        "status": session.status.value
    }

@router.post("/batch-process/{session_id}")
async def batch_process_large_file(
    session_id: int,
    batch_size: int = 1000,
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Process large files in batches for better performance."""
    session = db.query(models.UploadSession).filter(
        models.UploadSession.id == session_id,
        models.UploadSession.user_id == current_user.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Upload session not found")
    
    if not session.raw_data:
        raise HTTPException(status_code=400, detail="No raw data found for processing")
    
    # Initialize progress tracker
    progress_tracker = ProgressTracker(
        session_id=str(session.id),
        websocket_manager=manager
    )
    
    processor = StagedTransactionProcessor(progress_tracker=progress_tracker)
    
    try:
        result = await processor.process_raw_data_in_batches(
            raw_data=session.raw_data,
            upload_session=session,
            user=current_user,
            db=db,
            batch_size=batch_size
        )
        
        return {
            "success": True,
            "session_id": session.id,
            "batches_processed": result.get('batches_processed', 0),
            "total_staged": result.get('total_staged', 0),
            "total_errors": result.get('total_errors', 0)
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Batch processing failed: {str(e)}"
        )

@router.get("/formats/")
async def get_supported_formats():
    """Get information about supported file formats and their expected columns."""
    return {
        "supported_formats": {
            "csv": {
                "description": "Comma-separated values file",
                "mime_types": ["text/csv", "application/csv"],
                "extensions": [".csv"],
                "max_size_mb": 25
            },
            "excel": {
                "description": "Microsoft Excel files",
                "mime_types": ["application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
                "extensions": [".xls", ".xlsx"],
                "max_size_mb": 25
            }
        },
        "expected_columns": {
            "revolut_csv": {
                "required": ["Completed Date", "Description", "Amount"],
                "optional": ["Type", "Currency", "Product"],
                "example": "Date,Description,Amount,Type\n2024-01-01,Coffee Shop,-5.50,CARD"
            },
            "dutch_bank_excel": {
                "required": ["transactiondate", "description", "amount"],
                "optional": ["mutationcode", "accountNumber"],
                "example": "transactiondate,description,amount,mutationcode\n20240101,Coffee Purchase,-5.50,BA"
            },
            "generic": {
                "required": ["date", "description", "amount"],
                "optional": ["type", "category", "beneficiary"],
                "example": "date,description,amount\n2024-01-01,Coffee Shop,-5.50"
            }
        },
        "new_features": [
            "Staged data processing for review before confirmation",
            "Real-time progress tracking via WebSocket",
            "Smart categorization suggestions based on merchant names",
            "Batch processing for large files",
            "Enhanced duplicate detection",
            "Comprehensive audit trail",
            "Bulk confirmation/rejection of staged transactions"
        ],
        "processing_stages": [
            "File Upload & Validation",
            "Data Parsing & Format Detection", 
            "Transaction Mapping & Validation",
            "Duplicate Detection",
            "Smart Categorization",
            "Staging for Review",
            "User Confirmation",
            "Final Storage"
        ]
    }

@router.delete("/sessions/{session_id}")
async def delete_upload_session(
    session_id: int,
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete an upload session and its staged transactions."""
    session = db.query(models.UploadSession).filter(
        models.UploadSession.id == session_id,
        models.UploadSession.user_id == current_user.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Upload session not found")
    
    # Delete associated staged transactions
    staged_count = db.query(models.StagedTransaction).filter(
        models.StagedTransaction.upload_session_id == session_id
    ).delete()
    
    # Delete the session
    db.delete(session)
    db.commit()
    
    return {
        "message": f"Upload session deleted successfully",
        "session_id": session_id,
        "staged_transactions_deleted": staged_count
    }

@router.post("/validate-file/")
async def validate_file_format(
    file: UploadFile = File(...),
    current_user: schemas.User = Depends(get_current_user)
):
    """Validate file format and structure without processing."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    
    # Read file content
    content = await file.read()
    
    try:
        processor = StagedTransactionProcessor()
        validation_result = await processor.validate_file_structure(content, file.filename)
        
        return {
            "valid": validation_result['valid'],
            "format_detected": validation_result.get('format_detected', 'unknown'),
            "estimated_rows": validation_result.get('estimated_rows', 0),
            "columns_found": validation_result.get('columns_found', []),
            "issues": validation_result.get('issues', []),
            "suggestions": validation_result.get('suggestions', [])
        }
        
    except Exception as e:
        return {
            "valid": False,
            "error": str(e),
            "suggestions": [
                "Check file format (CSV, XLS, XLSX)",
                "Ensure file has required columns",
                "Verify file is not corrupted"
            ]
        }