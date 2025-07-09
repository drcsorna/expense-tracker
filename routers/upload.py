# backend/routers/upload.py
# Upload-related API routes

from datetime import datetime
from typing import List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

import models
import schemas
from models import get_db
from auth import get_current_user
from upload_processor import TransactionUploadProcessor, TransactionMapper, DeduplicationService

router = APIRouter(
    prefix="/upload",
    tags=["upload"],
    responses={404: {"description": "Not found"}},
)


@router.post("/transactions/")
async def upload_transactions(
    file: UploadFile = File(...),
    current_user: schemas.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Upload and process transaction files (CSV, XLS, XLSX).
    Supports multiple European banking formats with automatic detection.
    
    **Supported formats:**
    - CSV (Revolut-style): Type, Description, Amount, Completed Date
    - XLS/XLSX (Dutch bank): transactiondate, description, amount, mutationcode
    
    **Features:**
    - Automatic format detection
    - Deduplication (80% similarity threshold)
    - European encoding support
    - Error reporting per row
    """
    
    # Validate file type
    allowed_extensions = {'.csv', '.xls', '.xlsx'}
    file_extension = '.' + file.filename.split('.')[-1].lower()
    
    if file_extension not in allowed_extensions:
        raise HTTPException(
            status_code=400, 
            detail=f"Unsupported file type. Allowed: {', '.join(allowed_extensions)}"
        )
    
    try:
        # Read file content
        content = await file.read()
        
        # Process based on file type
        processor = TransactionUploadProcessor()
        if file_extension == '.csv':
            transactions_data = await processor.process_csv_file(content)
        else:  # .xls or .xlsx
            transactions_data = await processor.process_excel_file(content)
        
        # Initialize services
        mapper = TransactionMapper()
        dedup_service = DeduplicationService()
        
        # Convert and validate transactions
        processed_transactions = []
        duplicates_found = 0
        errors = []
        
        for idx, raw_transaction in enumerate(transactions_data):
            try:
                # Map to our transaction model
                mapped_transaction = mapper.map_transaction_fields(raw_transaction)
                
                # Check for duplicates
                if not dedup_service.is_duplicate_transaction(mapped_transaction, current_user.id, db):
                    # Create transaction
                    db_transaction = models.Transaction(
                        **mapped_transaction,
                        owner_id=current_user.id,
                        raw_data=raw_transaction  # Store original data for audit
                    )
                    db.add(db_transaction)
                    processed_transactions.append(mapped_transaction)
                else:
                    duplicates_found += 1
                    
            except Exception as e:
                errors.append(f"Row {idx + 1}: {str(e)}")
        
        # Commit all transactions
        db.commit()
        
        return {
            "success": True,
            "file_name": file.filename,
            "total_rows": len(transactions_data),
            "imported": len(processed_transactions),
            "duplicates_skipped": duplicates_found,
            "errors": errors,
            "summary": {
                "file_type": file_extension,
                "processing_time": datetime.utcnow().isoformat(),
                "user_id": current_user.id,
                "formats_detected": _detect_formats(transactions_data)
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"File processing error: {str(e)}")


def _detect_formats(data: List[dict]) -> dict:
    """Helper function to detect what formats were found in the file"""
    if not data:
        return {"detected": "empty"}
    
    first_row = data[0]
    
    if 'Completed Date' in first_row:
        return {"detected": "revolut_csv", "columns": list(first_row.keys())}
    elif 'transactiondate' in first_row:
        return {"detected": "dutch_bank_xls", "columns": list(first_row.keys())}
    else:
        return {"detected": "unknown", "columns": list(first_row.keys())}