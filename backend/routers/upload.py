# backend/routers/upload.py
# Enhanced upload router implementing 3-stage workflow:
# 1. Raw storage (immediate, no processing)
# 2. Schema detection + user configuration
# 3. Processing + confirmation

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import Dict, List, Optional, Any
from datetime import datetime
import asyncio
import hashlib
import io
import csv
import json

# Import enhanced models
from ..models import (
    get_db, RawFile, TrainingDataset, TrainingPattern, ProcessingSession, 
    ProcessedTransaction, ConfirmedTransaction, User, Category,
    FileType, ProcessingStatus, ConfidenceLevel
)

router = APIRouter()

# === STAGE 1: RAW FILE UPLOAD ===

@router.post("/transactions/")
async def upload_raw_file(
    file: UploadFile = File(...),
    file_purpose: str = "transaction_data",  # or "training_data"
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Stage 1: Store file exactly as uploaded, no processing
    Returns file ID for later processing configuration
    """
    
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No file provided"
        )
    
    # Read file content
    content = await file.read()
    file_size = len(content)
    
    # Validate file size (100MB limit for raw storage)
    MAX_FILE_SIZE = 100 * 1024 * 1024
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File too large. Maximum size is 100MB"
        )
    
    # Generate content hash to prevent duplicates
    content_hash = hashlib.sha256(content).hexdigest()
    
    # Check if file already exists
    existing_file = db.query(RawFile).filter(
        RawFile.content_hash == content_hash,
        RawFile.user_id == current_user.id
    ).first()
    
    if existing_file:
        return {
            "message": "File already exists",
            "file_id": existing_file.id,
            "filename": existing_file.filename,
            "upload_date": existing_file.upload_date.isoformat(),
            "duplicate": True
        }
    
    # Detect file type
    file_extension = '.' + file.filename.split('.')[-1].lower()
    detected_file_type = FileType.TRANSACTION_DATA if file_purpose == "transaction_data" else FileType.TRAINING_DATA
    
    # Basic schema detection (no processing, just inspection)
    schema_info = await detect_file_schema(content, file_extension)
    
    # Create raw file record
    raw_file = RawFile(
        filename=f"raw_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}",
        original_filename=file.filename,
        file_content=content,
        file_size=file_size,
        file_type=file_extension,
        content_hash=content_hash,
        detected_file_type=detected_file_type,
        detected_columns=schema_info.get("columns"),
        estimated_rows=schema_info.get("row_count"),
        sample_data=schema_info.get("sample_data"),
        encoding_detected=schema_info.get("encoding", "utf-8"),
        delimiter_detected=schema_info.get("delimiter"),
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
        "detected_type": detected_file_type.value,
        "schema_detected": schema_info,
        "upload_date": raw_file.upload_date.isoformat(),
        "next_step": "configure_processing" if detected_file_type == FileType.TRANSACTION_DATA else "configure_training"
    }

# === STAGE 1.5: SCHEMA INSPECTION ===

async def detect_file_schema(content: bytes, file_extension: str) -> Dict:
    """
    Analyze file structure without processing data
    Returns schema information for user review
    """
    
    try:
        if file_extension == '.csv':
            return await detect_csv_schema(content)
        elif file_extension in ['.xlsx', '.xls']:
            return await detect_excel_schema(content)
        else:
            return {"error": "Unsupported file type"}
    except Exception as e:
        return {"error": f"Schema detection failed: {str(e)}"}

async def detect_csv_schema(content: bytes) -> Dict:
    """Detect CSV file structure"""
    import chardet
    
    # Detect encoding
    detected = chardet.detect(content)
    encoding = detected.get('encoding', 'utf-8')
    
    try:
        text_content = content.decode(encoding)
    except UnicodeDecodeError:
        text_content = content.decode('utf-8', errors='ignore')
    
    # Try different delimiters
    best_result = None
    best_column_count = 0
    
    for delimiter in [',', ';', '\t', '|']:
        try:
            reader = csv.DictReader(io.StringIO(text_content), delimiter=delimiter)
            rows = list(reader)
            
            if len(rows) > 0 and len(rows[0]) > best_column_count:
                best_column_count = len(rows[0])
                best_result = {
                    "columns": list(rows[0].keys()),
                    "row_count": len(rows),
                    "sample_data": rows[:3],  # First 3 rows
                    "delimiter": delimiter,
                    "encoding": encoding
                }
        except Exception:
            continue
    
    return best_result or {"error": "Could not parse CSV"}

async def detect_excel_schema(content: bytes) -> Dict:
    """Detect Excel file structure"""
    try:
        import pandas as pd
        
        # Read Excel file
        excel_data = pd.read_excel(io.BytesIO(content), sheet_name=None)
        
        # Find sheet with most data
        best_sheet = None
        max_rows = 0
        
        for sheet_name, df in excel_data.items():
            if len(df) > max_rows:
                max_rows = len(df)
                best_sheet = df
        
        if best_sheet is not None and len(best_sheet) > 0:
            return {
                "columns": list(best_sheet.columns),
                "row_count": len(best_sheet),
                "sample_data": best_sheet.head(3).to_dict('records'),
                "encoding": "utf-8"
            }
        
        return {"error": "No data found in Excel file"}
        
    except Exception as e:
        return {"error": f"Excel processing failed: {str(e)}"}

@router.get("/detect-columns/{file_id}")
async def detect_columns_endpoint(
    file_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Auto-detect column mappings for a raw file"""
    
    raw_file = db.query(RawFile).filter(
        RawFile.id == file_id,
        RawFile.user_id == current_user.id
    ).first()
    
    if not raw_file:
        raise HTTPException(status_code=404, detail="Raw file not found")
    
    # Return detected column mapping
    return {
        "date": "auto_detect",
        "beneficiary": "auto_detect",
        "amount": "auto_detect", 
        "description": "auto_detect"
    }

@router.get("/training/list")
async def list_training_datasets(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List available training datasets"""
    
    datasets = db.query(TrainingDataset).filter(
        TrainingDataset.user_id == current_user.id,
        TrainingDataset.is_active == True
    ).all()
    
    return {
        "datasets": [
            {
                "id": d.id,
                "name": d.name,
                "pattern_count": d.total_patterns,
                "created_date": d.created_date.isoformat()
            }
            for d in datasets
        ]
    }

@router.post("/training/create/{file_id}")
async def create_training_data_from_raw_simplified(
    file_id: int,
    config: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Simplified training data creation endpoint"""
    
    return await create_training_data_from_raw(file_id, config, current_user, db)

@router.post("/processing/configure/{file_id}")
async def configure_processing_endpoint(
    file_id: int,
    config: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Configure processing endpoint"""
    
    return await configure_processing(file_id, config, current_user, db)

@router.post("/processing/start/{session_id}")
async def start_processing_endpoint(
    session_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Start processing endpoint"""
    
    return await start_processing(session_id, background_tasks, current_user, db)

@router.get("/processing/status/{session_id}")
async def get_processing_status(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get processing status"""
    
    session = db.query(ProcessingSession).filter(
        ProcessingSession.id == session_id,
        ProcessingSession.user_id == current_user.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {
        "status": session.status.value,
        "rows_processed": session.rows_processed,
        "total_rows_found": session.total_rows_found,
        "rows_with_suggestions": session.rows_with_suggestions,
        "high_confidence_suggestions": session.high_confidence_suggestions,
        "errors_found": session.errors_found
    }

@router.get("/processed/{session_id}")
async def get_processed_transactions_endpoint(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get processed transactions endpoint"""
    
    return await get_processed_transactions(session_id, current_user, db)

@router.post("/bootstrap/")
async def bootstrap_categories_from_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Legacy bootstrap endpoint - converts to new 3-stage workflow
    Maintains compatibility with existing frontend
    """
    
    # First upload as raw file
    file_content = await file.read()
    await file.seek(0)  # Reset file pointer
    
    # Create temporary raw file upload
    upload_result = await upload_raw_file(file, "training_data", current_user, db)
    
    # Auto-configure and create training dataset
    config = {
        "name": f"Bootstrap Data from {file.filename}",
        "column_mapping": {
            "merchant": "Beneficiary",
            "category": "Category", 
            "amount": "Amount"
        },
        "category_mapping": {
            # Default Hungarian -> English mappings
            "kávé": "Food & Beverage",
            "ruha": "Clothing",
            "háztartás": "Household",
            "autó": "Transportation",
            "étel": "Food & Beverage",
            "szórakozás": "Entertainment"
        },
        "language": "hu"
    }
    
    # Create training dataset
    training_result = await create_training_data_from_raw(
        upload_result["file_id"], config, current_user, db
    )
    
    return {
        "filename": file.filename,
        "processing_result": training_result,
        "timestamp": datetime.utcnow().isoformat()
    }

# === STAGE 2: TRAINING DATA PROCESSING ===

@router.post("/training/create-from-raw/{file_id}")
async def create_training_data_from_raw(
    file_id: int,
    config: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create training dataset from raw file (Hungarian data)
    Extract patterns and category mappings
    """
    
    # Get raw file
    raw_file = db.query(RawFile).filter(
        RawFile.id == file_id,
        RawFile.user_id == current_user.id
    ).first()
    
    if not raw_file:
        raise HTTPException(status_code=404, detail="Raw file not found")
    
    # Parse configuration
    column_mapping = config.get("column_mapping", {})
    category_mapping = config.get("category_mapping", {})  # Hungarian -> English
    dataset_name = config.get("name", f"Training Data from {raw_file.original_filename}")
    
    # Create training dataset
    training_dataset = TrainingDataset(
        name=dataset_name,
        description=f"Extracted from {raw_file.original_filename}",
        source_file_id=file_id,
        language=config.get("language", "hu"),  # Hungarian
        user_id=current_user.id
    )
    
    db.add(training_dataset)
    db.commit()
    db.refresh(training_dataset)
    
    # Process file content and extract patterns
    patterns_created = await extract_training_patterns(
        raw_file, training_dataset, column_mapping, category_mapping, db
    )
    
    # Update dataset metrics
    training_dataset.total_patterns = len(patterns_created)
    training_dataset.merchant_patterns = len([p for p in patterns_created if p.pattern_type == 'merchant'])
    training_dataset.category_mappings = len(set(p.category_mapped for p in patterns_created))
    
    db.commit()
    
    return {
        "message": "Training dataset created successfully",
        "dataset_id": training_dataset.id,
        "patterns_extracted": len(patterns_created),
        "merchant_patterns": training_dataset.merchant_patterns,
        "category_mappings": training_dataset.category_mappings,
        "ready_for_use": True
    }

async def extract_training_patterns(
    raw_file: RawFile, 
    dataset: TrainingDataset, 
    column_mapping: Dict, 
    category_mapping: Dict,
    db: Session
) -> List[TrainingPattern]:
    """Extract patterns from training data file"""
    
    patterns = []
    
    # Parse file content
    if raw_file.file_type == '.csv':
        file_data = await parse_csv_content(raw_file.file_content)
    else:
        file_data = await parse_excel_content(raw_file.file_content)
    
    # Extract patterns from each row
    for row in file_data:
        # Extract merchant pattern
        merchant = row.get(column_mapping.get('merchant', 'Beneficiary'))
        category_original = row.get(column_mapping.get('category', 'Category'))
        
        if merchant and category_original:
            # Map Hungarian category to English
            category_english = category_mapping.get(category_original, category_original)
            
            # Create or update merchant pattern
            existing_pattern = db.query(TrainingPattern).filter(
                TrainingPattern.dataset_id == dataset.id,
                TrainingPattern.pattern_type == 'merchant',
                TrainingPattern.pattern_value == merchant.strip()
            ).first()
            
            if existing_pattern:
                existing_pattern.occurrences += 1
                existing_pattern.confidence = min(1.0, existing_pattern.confidence + 0.1)
            else:
                pattern = TrainingPattern(
                    pattern_type='merchant',
                    pattern_value=merchant.strip(),
                    category_original=category_original,
                    category_mapped=category_english,
                    confidence=0.7,  # Start with medium confidence
                    dataset_id=dataset.id
                )
                db.add(pattern)
                patterns.append(pattern)
    
    db.commit()
    return patterns

# === STAGE 2: PROCESSING CONFIGURATION ===

@router.post("/processing/configure/{file_id}")
async def configure_processing(
    file_id: int,
    config: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Configure how to process a raw file
    User can map columns and set processing rules
    """
    
    raw_file = db.query(RawFile).filter(
        RawFile.id == file_id,
        RawFile.user_id == current_user.id
    ).first()
    
    if not raw_file:
        raise HTTPException(status_code=404, detail="Raw file not found")
    
    # Create processing session
    processing_session = ProcessingSession(
        session_name=config.get("session_name", f"Process {raw_file.original_filename}"),
        raw_file_id=file_id,
        column_mapping=config.get("column_mapping"),
        processing_rules=config.get("processing_rules", {}),
        use_training_data=config.get("use_training_data", True),
        training_dataset_ids=config.get("training_dataset_ids", []),
        status=ProcessingStatus.READY_TO_PROCESS,
        user_id=current_user.id
    )
    
    db.add(processing_session)
    db.commit()
    db.refresh(processing_session)
    
    return {
        "message": "Processing configured successfully",
        "session_id": processing_session.id,
        "status": processing_session.status.value,
        "ready_to_start": True,
        "estimated_processing_time": "2-5 minutes"  # Estimate based on file size
    }

@router.post("/processing/start/{session_id}")
async def start_processing(
    session_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Start processing a configured session
    Runs in background
    """
    
    session = db.query(ProcessingSession).filter(
        ProcessingSession.id == session_id,
        ProcessingSession.user_id == current_user.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Processing session not found")
    
    if session.status != ProcessingStatus.READY_TO_PROCESS:
        raise HTTPException(status_code=400, detail="Session not ready for processing")
    
    # Update status
    session.status = ProcessingStatus.PROCESSING
    session.started_at = datetime.utcnow()
    db.commit()
    
    # Start background processing
    background_tasks.add_task(
        process_file_with_training_data,
        session_id, current_user.id
    )
    
    return {
        "message": "Processing started",
        "session_id": session_id,
        "status": "processing",
        "estimated_completion": "2-5 minutes"
    }

# === BACKGROUND PROCESSING ===

async def process_file_with_training_data(session_id: int, user_id: int):
    """
    Background task: Process raw file using training data
    """
    
    db = next(get_db())
    
    try:
        session = db.query(ProcessingSession).filter(
            ProcessingSession.id == session_id
        ).first()
        
        raw_file = session.raw_file
        
        # Parse file content
        if raw_file.file_type == '.csv':
            file_data = await parse_csv_content(raw_file.file_content)
        else:
            file_data = await parse_excel_content(raw_file.file_content)
        
        session.total_rows_found = len(file_data)
        
        # Get training data patterns
        training_patterns = []
        if session.use_training_data:
            training_patterns = db.query(TrainingPattern).filter(
                TrainingPattern.dataset_id.in_(session.training_dataset_ids)
            ).all()
        
        # Process each row
        processed_count = 0
        suggestions_count = 0
        high_confidence_count = 0
        
        for i, row in enumerate(file_data):
            try:
                # Convert row to structured transaction
                processed_txn = await process_single_row(
                    row, session.column_mapping, training_patterns, session, db
                )
                
                if processed_txn.suggested_category:
                    suggestions_count += 1
                    if processed_txn.confidence_level == ConfidenceLevel.VERY_HIGH:
                        high_confidence_count += 1
                
                processed_count += 1
                
                # Update progress occasionally
                if i % 100 == 0:
                    session.rows_processed = processed_count
                    db.commit()
                    
            except Exception as e:
                session.processing_errors.append({
                    "row": i + 1,
                    "error": str(e),
                    "data": row
                })
        
        # Complete processing
        session.status = ProcessingStatus.PROCESSED
        session.completed_at = datetime.utcnow()
        session.rows_processed = processed_count
        session.rows_with_suggestions = suggestions_count
        session.high_confidence_suggestions = high_confidence_count
        
        db.commit()
        
    except Exception as e:
        session.status = ProcessingStatus.FAILED
        session.processing_errors.append({"error": str(e)})
        db.commit()
    
    finally:
        db.close()

async def process_single_row(
    row: Dict, 
    column_mapping: Dict, 
    training_patterns: List[TrainingPattern],
    session: ProcessingSession,
    db: Session
) -> ProcessedTransaction:
    """Process a single transaction row with training data"""
    
    # Extract data using column mapping
    date_value = parse_date(row.get(column_mapping.get('date')))
    beneficiary = str(row.get(column_mapping.get('beneficiary', 'Beneficiary'))).strip()
    amount = parse_amount(row.get(column_mapping.get('amount')))
    description = str(row.get(column_mapping.get('description', '')) or '').strip()
    
    # Find matching training patterns
    suggestion = find_best_category_suggestion(beneficiary, description, training_patterns)
    
    # Create processed transaction
    processed_txn = ProcessedTransaction(
        transaction_date=date_value,
        beneficiary=beneficiary,
        amount=amount,
        description=description,
        suggested_category=suggestion.get('category'),
        confidence_score=suggestion.get('confidence', 0.0),
        confidence_level=get_confidence_level(suggestion.get('confidence', 0.0)),
        suggestion_source=suggestion.get('source', 'training_data'),
        alternative_suggestions=suggestion.get('alternatives', []),
        raw_row_data=row,
        requires_review=suggestion.get('confidence', 0.0) < 0.9,
        processing_session_id=session.id,
        user_id=session.user_id
    )
    
    db.add(processed_txn)
    return processed_txn

def find_best_category_suggestion(
    beneficiary: str, 
    description: str, 
    patterns: List[TrainingPattern]
) -> Dict:
    """Find best category suggestion from training patterns"""
    
    best_match = None
    best_confidence = 0.0
    
    search_text = f"{beneficiary} {description}".lower()
    
    for pattern in patterns:
        if pattern.pattern_type == 'merchant':
            pattern_value = pattern.pattern_value.lower()
            
            if pattern_value in search_text:
                confidence = pattern.confidence * pattern.success_rate
                if confidence > best_confidence:
                    best_confidence = confidence
                    best_match = pattern
    
    if best_match:
        return {
            'category': best_match.category_mapped,
            'confidence': best_confidence,
            'source': 'training_pattern',
            'pattern_used': best_match.pattern_value
        }
    
    return {'confidence': 0.0}

def get_confidence_level(confidence: float) -> ConfidenceLevel:
    """Convert confidence score to enum"""
    if confidence >= 0.91:
        return ConfidenceLevel.VERY_HIGH
    elif confidence >= 0.71:
        return ConfidenceLevel.HIGH
    elif confidence >= 0.41:
        return ConfidenceLevel.MEDIUM
    else:
        return ConfidenceLevel.LOW

# Helper functions for parsing
def parse_date(date_str):
    """Parse date from various formats"""
    # Implement flexible date parsing
    pass

def parse_amount(amount_str):
    """Parse amount from string"""
    # Implement amount parsing
    pass

async def parse_csv_content(content: bytes) -> List[Dict]:
    """Parse CSV content to list of dictionaries"""
    # Implement CSV parsing
    pass

async def parse_excel_content(content: bytes) -> List[Dict]:
    """Parse Excel content to list of dictionaries"""
    # Implement Excel parsing
    pass

# === STAGE 3: CONFIRMATION ENDPOINTS ===

@router.get("/processed/{session_id}")
async def get_processed_transactions(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get processed transactions for user review"""
    
    transactions = db.query(ProcessedTransaction).filter(
        ProcessedTransaction.processing_session_id == session_id,
        ProcessedTransaction.user_id == current_user.id
    ).all()
    
    return {
        "transactions": [
            {
                "id": txn.id,
                "date": txn.transaction_date.isoformat(),
                "beneficiary": txn.beneficiary,
                "amount": float(txn.amount),
                "description": txn.description,
                "suggested_category": txn.suggested_category,
                "confidence": txn.confidence_score,
                "requires_review": txn.requires_review,
                "alternatives": txn.alternative_suggestions
            }
            for txn in transactions
        ]
    }

@router.post("/confirm/{transaction_id}")
async def confirm_transaction(
    transaction_id: int,
    confirmation: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Confirm a processed transaction"""
    
    processed_txn = db.query(ProcessedTransaction).filter(
        ProcessedTransaction.id == transaction_id,
        ProcessedTransaction.user_id == current_user.id
    ).first()
    
    if not processed_txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    # Create confirmed transaction
    confirmed_txn = ConfirmedTransaction(
        transaction_date=processed_txn.transaction_date,
        beneficiary=processed_txn.beneficiary,
        amount=processed_txn.amount,
        description=processed_txn.description,
        category=confirmation.get('category', processed_txn.suggested_category),
        category_id=confirmation.get('category_id'),
        tags=confirmation.get('tags', []),
        user_notes=confirmation.get('notes'),
        was_ai_suggested=processed_txn.suggested_category is not None,
        original_confidence=processed_txn.confidence_score,
        processed_transaction_id=transaction_id,
        processing_session_id=processed_txn.processing_session_id,
        user_id=current_user.id
    )
    
    db.add(confirmed_txn)
    
    # Update processed transaction
    processed_txn.user_reviewed = True
    processed_txn.user_approved = True
    processed_txn.review_date = datetime.utcnow()
    
    db.commit()
    
    return {
        "message": "Transaction confirmed successfully",
        "confirmed_id": confirmed_txn.id
    }

# === UTILITY ENDPOINTS ===

@router.get("/raw/list")
async def list_raw_files(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all raw files for user"""
    
    files = db.query(RawFile).filter(
        RawFile.user_id == current_user.id
    ).order_by(desc(RawFile.upload_date)).all()
    
    return {
        "files": [
            {
                "id": f.id,
                "filename": f.original_filename,
                "upload_date": f.upload_date.isoformat(),
                "file_size": f.file_size,
                "detected_type": f.detected_file_type.value,
                "estimated_rows": f.estimated_rows,
                "processing_sessions": len(f.processing_sessions)
            }
            for f in files
        ]
    }

async def get_current_user():
    """Placeholder for user authentication"""
    # Implement user authentication
    pass