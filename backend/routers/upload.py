# backend/routers/upload.py
# Upload-related API routes

from datetime import datetime
from typing import List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.orm import Session

# Relative imports
from .. import models
from .. import schemas
from ..models import get_db
from ..auth import get_current_user
from ..upload_processor import TransactionUploadProcessor, TransactionMapper, DeduplicationService

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
    - Generic CSV/Excel with date, description, amount fields
    
    **Features:**
    - Automatic format detection
    - Intelligent field mapping
    - Deduplication (80% similarity threshold)
    - European encoding support (UTF-8, ISO-8859-1, CP1252)
    - Comprehensive error reporting
    - Audit trail with raw data storage
    
    **Response includes:**
    - Number of transactions imported
    - Number of duplicates skipped
    - Detailed error messages for failed rows
    - Processing summary and metadata
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
    
    # Validate file size (10MB limit)
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File too large. Maximum size is 10MB."
        )
    
    if len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty file provided"
        )
    
    try:
        # Process based on file type
        processor = TransactionUploadProcessor()
        
        if file_extension == '.csv':
            transactions_data = await processor.process_csv_file(content)
        else:  # .xls or .xlsx
            transactions_data = await processor.process_excel_file(content)
        
        if not transactions_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid transaction data found in file"
            )
        
        # Initialize services
        mapper = TransactionMapper()
        dedup_service = DeduplicationService()
        
        # Convert and validate transactions
        processed_transactions = []
        duplicates_found = 0
        errors = []
        
        for idx, raw_transaction in enumerate(transactions_data):
            try:
                # Skip completely empty rows
                if not any(str(v).strip() for v in raw_transaction.values() if v is not None):
                    continue
                    
                # Map to our transaction model
                mapped_transaction = mapper.map_transaction_fields(raw_transaction)
                
                # Validate required fields
                if not mapped_transaction.get('transaction_date'):
                    errors.append(f"Row {idx + 2}: Missing or invalid date")
                    continue
                    
                if not mapped_transaction.get('beneficiary'):
                    errors.append(f"Row {idx + 2}: Missing beneficiary/description")
                    continue
                    
                if mapped_transaction.get('amount') is None:
                    errors.append(f"Row {idx + 2}: Missing or invalid amount")
                    continue
                
                # Check for duplicates
                if not dedup_service.is_duplicate_transaction(mapped_transaction, current_user.id, db):
                    # Create transaction
                    db_transaction = models.Transaction(
                        **mapped_transaction,
                        owner_id=current_user.id
                    )
                    db.add(db_transaction)
                    processed_transactions.append(mapped_transaction)
                else:
                    duplicates_found += 1
                    
            except Exception as e:
                errors.append(f"Row {idx + 2}: {str(e)}")
        
        # Commit all transactions
        if processed_transactions:
            db.commit()
        
        # Prepare detailed response
        return {
            "success": True,
            "file_name": file.filename,
            "file_size_bytes": len(content),
            "total_rows": len(transactions_data),
            "imported": len(processed_transactions),
            "duplicates_skipped": duplicates_found,
            "errors": errors,
            "has_errors": len(errors) > 0,
            "summary": {
                "file_type": file_extension,
                "processing_time": datetime.utcnow().isoformat(),
                "user_id": current_user.id,
                "formats_detected": _detect_formats(transactions_data),
                "success_rate": f"{(len(processed_transactions) / len(transactions_data) * 100):.1f}%" if transactions_data else "0%"
            }
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File processing error: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error during file processing: {str(e)}"
        )


@router.get("/formats/")
async def get_supported_formats():
    """
    Get information about supported file formats and their expected columns.
    """
    return {
        "supported_formats": {
            "csv": {
                "description": "Comma-separated values file",
                "mime_types": ["text/csv", "application/csv"],
                "extensions": [".csv"],
                "max_size_mb": 10
            },
            "excel": {
                "description": "Microsoft Excel files",
                "mime_types": ["application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
                "extensions": [".xls", ".xlsx"],
                "max_size_mb": 10
            }
        },
        "expected_columns": {
            "revolut_csv": {
                "required": ["Completed Date", "Description", "Amount"],
                "optional": ["Type", "Currency", "Product"]
            },
            "dutch_bank_excel": {
                "required": ["transactiondate", "description", "amount"],
                "optional": ["mutationcode", "accountNumber"]
            },
            "generic": {
                "required": ["date", "description", "amount"],
                "optional": ["type", "category", "beneficiary"]
            }
        },
        "features": [
            "Automatic format detection",
            "Duplicate detection and prevention",
            "Multiple encoding support",
            "Comprehensive error reporting",
            "Raw data preservation for audit"
        ]
    }


def _detect_formats(data: List[dict]) -> dict:
    """Helper function to detect what formats were found in the file"""
    if not data:
        return {"detected": "empty", "confidence": "high"}
    
    first_row = data[0]
    available_columns = [col.lower().strip() for col in first_row.keys()]
    
    # Detection logic with confidence scoring
    if any('completed' in col for col in available_columns):
        return {
            "detected": "revolut_csv", 
            "confidence": "high",
            "columns": list(first_row.keys()),
            "rows_detected": len(data)
        }
    elif 'transactiondate' in available_columns and any('mutation' in col for col in available_columns):
        return {
            "detected": "dutch_bank_excel", 
            "confidence": "high",
            "columns": list(first_row.keys()),
            "rows_detected": len(data)
        }
    elif any(col in available_columns for col in ['date', 'datum']) and 'amount' in available_columns:
        return {
            "detected": "generic_transaction", 
            "confidence": "medium",
            "columns": list(first_row.keys()),
            "rows_detected": len(data)
        }
    else:
        return {
            "detected": "unknown", 
            "confidence": "low",
            "columns": list(first_row.keys()),
            "rows_detected": len(data),
            "suggestion": "Ensure file contains date, description, and amount columns"
        }