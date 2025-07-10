# backend/upload_processor.py
# Enhanced file processing with ML categorization and duplicate detection

import io
import re
import csv
import asyncio
import hashlib
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session
import json

# Use pandas for robust file processing
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

# For Excel processing
try:
    import openpyxl
    import xlrd
    EXCEL_AVAILABLE = True
except ImportError:
    EXCEL_AVAILABLE = False

# For fuzzy matching
try:
    from fuzzywuzzy import fuzz
    FUZZY_AVAILABLE = True
except ImportError:
    FUZZY_AVAILABLE = False

from . import models
from .ml_categorizer import MLCategorizer
from .duplicate_detector import DuplicateDetector

class ProgressTracker:
    """Enhanced real-time progress tracking via WebSocket."""
    
    def __init__(self, session_id: str, websocket_manager=None):
        self.session_id = session_id
        self.websocket_manager = websocket_manager
        self.current_stage = "initializing"
        self.progress_percentage = 0.0
        self.rows_processed = 0
        self.total_rows = 0
        self.stage_weights = {
            "parsing": 20,      # 20% for file parsing
            "analyzing": 30,    # 30% for data analysis
            "categorizing": 40, # 40% for ML categorization
            "finalizing": 10    # 10% for finalization
        }
        
    async def update_progress(self, stage: str, stage_progress: float, rows_processed: int = 0, total_rows: int = 0, message: str = ""):
        """Send progress update via WebSocket with weighted stages."""
        self.current_stage = stage
        self.rows_processed = rows_processed
        self.total_rows = total_rows
        
        # Calculate overall progress based on stage weights
        stage_order = ["parsing", "analyzing", "categorizing", "finalizing"]
        
        if stage in stage_order:
            completed_stages = stage_order[:stage_order.index(stage)]
            completed_weight = sum(self.stage_weights[s] for s in completed_stages)
            current_stage_weight = self.stage_weights[stage] * (stage_progress / 100)
            self.progress_percentage = completed_weight + current_stage_weight
        
        if self.websocket_manager:
            await self.websocket_manager.send_progress(self.session_id, {
                "stage": stage,
                "progress": self.progress_percentage,
                "stage_progress": stage_progress,
                "rows_processed": rows_processed,
                "total_rows": total_rows,
                "message": message,
                "timestamp": datetime.utcnow().isoformat()
            })
    
    async def send_error(self, error_message: str, details: dict = None):
        """Send error update via WebSocket."""
        if self.websocket_manager:
            await self.websocket_manager.send_progress(self.session_id, {
                "stage": "failed",
                "progress": 0,
                "error": error_message,
                "details": details or {},
                "timestamp": datetime.utcnow().isoformat()
            })
    
    async def send_final_update(self, result: dict):
        """Send final completion update."""
        if self.websocket_manager:
            await self.websocket_manager.send_progress(self.session_id, {
                "stage": "completed" if result.get('success') else "failed",
                "progress": 100.0 if result.get('success') else 0,
                "final_result": result,
                "timestamp": datetime.utcnow().isoformat()
            })

class StagedTransactionProcessor:
    """Enhanced file processor with ML categorization and duplicate detection."""
    
    def __init__(self, progress_tracker: Optional[ProgressTracker] = None):
        self.progress_tracker = progress_tracker
        self.ml_categorizer = None
        self.duplicate_detector = None
        
        # Enhanced column patterns for auto-detection
        self.date_patterns = [
            r'date', r'transaction_date', r'datum', r'fecha', r'data', r'when',
            r'booking_date', r'value_date', r'posting_date', r'execution_date'
        ]
        self.description_patterns = [
            r'description', r'beneficiary', r'memo', r'payee', r'vendor', 
            r'merchant', r'name', r'omschrijving', r'descripcion', r'details',
            r'counterparty', r'reference', r'narrative'
        ]
        self.amount_patterns = [
            r'amount', r'value', r'sum', r'bedrag', r'cantidad', r'monto', 
            r'total', r'transaction_amount', r'debit', r'credit'
        ]
        self.category_patterns = [
            r'category', r'type', r'classification', r'categorie', r'categoria',
            r'tag', r'label', r'group'
        ]
        
        # File format templates
        self.format_templates = {
            "bank_standard": {
                "date_cols": ["date", "transaction_date", "booking_date"],
                "description_cols": ["description", "beneficiary", "counterparty"],
                "amount_cols": ["amount", "transaction_amount"],
                "debit_credit_cols": ["debit", "credit"]
            },
            "csv_export": {
                "date_cols": ["date"],
                "description_cols": ["description", "memo"],
                "amount_cols": ["amount"]
            },
            "mint_export": {
                "date_cols": ["date"],
                "description_cols": ["description"],
                "amount_cols": ["amount"],
                "category_cols": ["category"]
            }
        }
        
    async def process_file_to_staged(
        self, 
        content: bytes, 
        filename: str, 
        file_type: str,
        upload_session: models.UploadSession,
        user: models.User,
        db: Session
    ) -> Dict[str, Any]:
        """Enhanced file processing with ML categorization."""
        
        try:
            # Initialize ML components
            self.ml_categorizer = MLCategorizer(user.id, db)
            self.duplicate_detector = DuplicateDetector(user.id, db)
            
            # Stage 1: Parse file
            if self.progress_tracker:
                await self.progress_tracker.update_progress(
                    "parsing", 0, 0, 0, "Reading file content..."
                )
            
            raw_data = await self._process_file_content(content, filename, file_type)
            
            if not raw_data:
                error_result = {
                    "success": False,
                    "error": "No data found in file",
                    "total_rows": 0,
                    "staged_count": 0,
                    "error_count": 1,
                    "duplicate_count": 0,
                    "errors": ["File contains no readable data"]
                }
                if self.progress_tracker:
                    await self.progress_tracker.send_final_update(error_result)
                return error_result
            
            # Update upload session with raw data sample
            upload_session.raw_data_sample = raw_data[:100]
            upload_session.total_rows = len(raw_data)
            db.commit()
            
            if self.progress_tracker:
                await self.progress_tracker.update_progress(
                    "parsing", 100, 0, len(raw_data), f"Parsed {len(raw_data)} rows"
                )
            
            # Stage 2: Analyze and normalize data
            if self.progress_tracker:
                await self.progress_tracker.update_progress(
                    "analyzing", 0, 0, len(raw_data), "Detecting file format..."
                )
            
            format_detected = self._detect_format(raw_data)
            upload_session.format_detected = format_detected
            
            normalized_data = []
            errors = []
            processed_count = 0
            
            for i, row in enumerate(raw_data):
                try:
                    normalized_transaction = self._normalize_single_transaction(row, format_detected, i + 1)
                    if normalized_transaction:
                        normalized_data.append(normalized_transaction)
                    processed_count += 1
                    
                    # Update progress every 100 rows
                    if processed_count % 100 == 0 and self.progress_tracker:
                        progress = (processed_count / len(raw_data)) * 100
                        await self.progress_tracker.update_progress(
                            "analyzing", progress, processed_count, len(raw_data), 
                            f"Normalized {processed_count}/{len(raw_data)} transactions"
                        )
                        
                except Exception as e:
                    errors.append(f"Row {i + 1}: {str(e)}")
                    continue
            
            if self.progress_tracker:
                await self.progress_tracker.update_progress(
                    "analyzing", 100, len(normalized_data), len(raw_data), 
                    f"Analyzed {len(normalized_data)} valid transactions"
                )
            
            # Stage 3: ML Categorization and duplicate detection
            if self.progress_tracker:
                await self.progress_tracker.update_progress(
                    "categorizing", 0, 0, len(normalized_data), "Initializing ML categorizer..."
                )
            
            # Train ML model with existing data
            await self.ml_categorizer.train_model()
            
            staged_transactions = []
            duplicate_count = 0
            categorized_count = 0
            
            for i, transaction in enumerate(normalized_data):
                try:
                    # Generate file hash for duplicate detection
                    transaction['file_hash'] = self._generate_transaction_hash(transaction)
                    
                    # Check for duplicates
                    is_duplicate = await self.duplicate_detector.check_duplicate(transaction)
                    if is_duplicate:
                        duplicate_count += 1
                        # Still process duplicates but mark them
                        transaction['is_potential_duplicate'] = True
                    
                    # ML Categorization
                    category_suggestion = await self.ml_categorizer.suggest_category(transaction)
                    
                    # Create staged transaction
                    staged_txn = models.StagedTransaction(
                        transaction_date=transaction['transaction_date'],
                        beneficiary=transaction['beneficiary'],
                        amount=transaction['amount'],
                        description=transaction.get('description'),
                        suggested_category=category_suggestion.get('category'),
                        suggested_category_id=category_suggestion.get('category_id'),
                        confidence=category_suggestion.get('confidence'),
                        confidence_level=self._get_confidence_level(category_suggestion.get('confidence', 0)),
                        alternative_suggestions=category_suggestion.get('alternatives', []),
                        raw_data=transaction,
                        file_hash=transaction['file_hash'],
                        processing_notes=transaction.get('processing_notes', []),
                        requires_review=category_suggestion.get('confidence', 0) < 0.9,
                        auto_approve_eligible=category_suggestion.get('confidence', 0) >= 0.95,
                        owner_id=user.id,
                        upload_session_id=upload_session.id
                    )
                    
                    db.add(staged_txn)
                    staged_transactions.append(staged_txn)
                    
                    if category_suggestion.get('category'):
                        categorized_count += 1
                    
                    # Update progress every 50 transactions
                    if (i + 1) % 50 == 0 and self.progress_tracker:
                        progress = ((i + 1) / len(normalized_data)) * 100
                        await self.progress_tracker.update_progress(
                            "categorizing", progress, i + 1, len(normalized_data), 
                            f"Categorized {categorized_count}/{i + 1} transactions"
                        )
                        
                except Exception as e:
                    errors.append(f"Categorization error for row {i + 1}: {str(e)}")
                    continue
            
            # Stage 4: Finalization
            if self.progress_tracker:
                await self.progress_tracker.update_progress(
                    "finalizing", 0, len(staged_transactions), len(normalized_data), 
                    "Saving to database..."
                )
            
            # Commit all staged transactions
            db.commit()
            
            # Update upload session metrics
            upload_session.processed_rows = len(normalized_data)
            upload_session.staged_count = len(staged_transactions)
            upload_session.error_count = len(errors)
            upload_session.duplicate_count = duplicate_count
            upload_session.ml_suggestions_count = categorized_count
            upload_session.high_confidence_suggestions = sum(
                1 for txn in staged_transactions if txn.confidence and txn.confidence >= 0.9
            )
            upload_session.status = models.UploadStatus.COMPLETED
            upload_session.processing_end = datetime.utcnow()
            upload_session.processing_log = {
                "format_detected": format_detected,
                "ml_suggestions": categorized_count,
                "duplicates_found": duplicate_count,
                "errors": errors[:50]  # Limit error log size
            }
            
            db.commit()
            
            if self.progress_tracker:
                await self.progress_tracker.update_progress(
                    "finalizing", 100, len(staged_transactions), len(normalized_data), 
                    "Processing complete!"
                )
            
            # Prepare final result
            result = {
                "success": True,
                "upload_session_id": upload_session.id,
                "total_rows": len(raw_data),
                "processed_rows": len(normalized_data),
                "staged_count": len(staged_transactions),
                "error_count": len(errors),
                "duplicate_count": duplicate_count,
                "ml_suggestions_count": categorized_count,
                "high_confidence_count": upload_session.high_confidence_suggestions,
                "format_detected": format_detected,
                "processing_time_seconds": upload_session.processing_time_seconds,
                "errors": errors[:10] if errors else []  # Return first 10 errors
            }
            
            if self.progress_tracker:
                await self.progress_tracker.send_final_update(result)
            
            return result
            
        except Exception as e:
            # Handle processing errors
            upload_session.status = models.UploadStatus.FAILED
            upload_session.processing_end = datetime.utcnow()
            upload_session.error_details = {"error": str(e)}
            db.commit()
            
            error_result = {
                "success": False,
                "error": str(e),
                "upload_session_id": upload_session.id
            }
            
            if self.progress_tracker:
                await self.progress_tracker.send_error(str(e), {"session_id": upload_session.id})
                await self.progress_tracker.send_final_update(error_result)
            
            return error_result
    
    async def _process_file_content(self, content: bytes, filename: str, file_type: str) -> List[Dict]:
        """Process file content based on type."""
        if file_type == '.csv':
            return await self._process_csv_file(content)
        else:
            return await self._process_excel_file(content)
    
    async def _process_csv_file(self, content: bytes) -> List[Dict]:
        """Enhanced CSV processing with encoding detection."""
        import chardet
        
        # Detect encoding
        detected = chardet.detect(content)
        encoding = detected.get('encoding', 'utf-8')
        
        try:
            # Try detected encoding first
            text_content = content.decode(encoding)
        except UnicodeDecodeError:
            # Fallback encodings
            for fallback_encoding in ['utf-8', 'latin1', 'cp1252']:
                try:
                    text_content = content.decode(fallback_encoding)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                raise Exception("Could not decode file with any supported encoding")
        
        # Parse CSV with multiple delimiter detection
        for delimiter in [',', ';', '\t', '|']:
            try:
                reader = csv.DictReader(io.StringIO(text_content), delimiter=delimiter)
                rows = list(reader)
                if len(rows) > 0 and len(rows[0]) > 1:  # Valid CSV should have multiple columns
                    return rows
            except Exception:
                continue
        
        raise Exception("Could not parse CSV file with any supported delimiter")
    
    async def _process_excel_file(self, content: bytes) -> List[Dict]:
        """Enhanced Excel processing with multiple sheet support."""
        if not PANDAS_AVAILABLE:
            raise Exception("Pandas is required for Excel file processing")
        
        try:
            # Read Excel file
            excel_data = pd.read_excel(io.BytesIO(content), sheet_name=None)  # Read all sheets
            
            # Find the sheet with the most data
            best_sheet = None
            max_rows = 0
            
            for sheet_name, df in excel_data.items():
                if len(df) > max_rows:
                    max_rows = len(df)
                    best_sheet = df
            
            if best_sheet is None or len(best_sheet) == 0:
                raise Exception("No data found in Excel file")
            
            # Convert to list of dictionaries
            return best_sheet.to_dict('records')
            
        except Exception as e:
            raise Exception(f"Excel processing failed: {str(e)}")
    
    def _detect_format(self, raw_data: List[Dict]) -> str:
        """Enhanced format detection with scoring."""
        if not raw_data:
            return "unknown"
        
        first_row = raw_data[0]
        columns = [col.lower().strip() for col in first_row.keys()]
        
        format_scores = {}
        
        for format_name, template in self.format_templates.items():
            score = 0
            total_possible = 0
            
            # Check for date columns
            for date_col in template.get("date_cols", []):
                total_possible += 1
                if any(self._column_matches(col, [date_col]) for col in columns):
                    score += 1
            
            # Check for description columns
            for desc_col in template.get("description_cols", []):
                total_possible += 1
                if any(self._column_matches(col, [desc_col]) for col in columns):
                    score += 1
            
            # Check for amount columns
            for amount_col in template.get("amount_cols", []):
                total_possible += 1
                if any(self._column_matches(col, [amount_col]) for col in columns):
                    score += 1
            
            format_scores[format_name] = score / total_possible if total_possible > 0 else 0
        
        # Return the format with the highest score
        best_format = max(format_scores, key=format_scores.get)
        if format_scores[best_format] > 0.5:  # At least 50% match
            return best_format
        
        return "generic"
    
    def _column_matches(self, column: str, patterns: List[str]) -> bool:
        """Check if column matches any of the patterns."""
        column_clean = column.lower().strip()
        for pattern in patterns:
            if pattern.lower() in column_clean or column_clean in pattern.lower():
                return True
        return False
    
    def _normalize_single_transaction(self, row: Dict, format_detected: str, row_num: int) -> Dict:
        """Enhanced transaction normalization with better error handling."""
        normalized = {}
        processing_notes = []
        
        # Find date column
        date_value = None
        for col, value in row.items():
            if self._column_matches(col, self.date_patterns):
                date_value = self._parse_date(value)
                if date_value:
                    break
        
        if not date_value:
            raise Exception(f"Could not parse date from row {row_num}")
        
        normalized['transaction_date'] = date_value
        
        # Find description/beneficiary
        beneficiary = None
        for col, value in row.items():
            if self._column_matches(col, self.description_patterns):
                beneficiary = str(value).strip() if value else None
                if beneficiary:
                    break
        
        if not beneficiary:
            raise Exception(f"Could not find beneficiary/description in row {row_num}")
        
        normalized['beneficiary'] = beneficiary
        
        # Find amount (handle debit/credit columns)
        amount = None
        
        # First, try to find a single amount column
        for col, value in row.items():
            if self._column_matches(col, self.amount_patterns):
                amount = self._parse_amount(value)
                if amount is not None:
                    break
        
        # If no single amount found, try debit/credit columns
        if amount is None:
            debit = credit = None
            for col, value in row.items():
                col_lower = col.lower()
                if 'debit' in col_lower or 'withdrawal' in col_lower:
                    debit = self._parse_amount(value)
                elif 'credit' in col_lower or 'deposit' in col_lower:
                    credit = self._parse_amount(value)
            
            if debit is not None and credit is not None:
                amount = credit - debit  # Credit positive, debit negative
            elif debit is not None:
                amount = -abs(debit)  # Debit is negative
            elif credit is not None:
                amount = abs(credit)  # Credit is positive
        
        if amount is None:
            raise Exception(f"Could not parse amount from row {row_num}")
        
        normalized['amount'] = amount
        
        # Optional: find category if present
        category = None
        for col, value in row.items():
            if self._column_matches(col, self.category_patterns):
                category = str(value).strip() if value else None
                if category:
                    break
        
        if category:
            normalized['existing_category'] = category
            processing_notes.append(f"Original category: {category}")
        
        # Add additional fields
        normalized['description'] = beneficiary  # Use beneficiary as description
        normalized['processing_notes'] = processing_notes
        
        return normalized
    
    def _parse_date(self, date_value) -> Optional[date]:
        """Enhanced date parsing with multiple formats."""
        if not date_value:
            return None
        
        # Convert to string if needed
        date_str = str(date_value).strip()
        
        # Common date formats
        date_formats = [
            "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y", 
            "%Y/%m/%d", "%d-%m-%Y", "%m-%d-%Y", "%d %m %Y",
            "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"
        ]
        
        for fmt in date_formats:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        
        # Try pandas date parsing as fallback
        if PANDAS_AVAILABLE:
            try:
                return pd.to_datetime(date_str).date()
            except Exception:
                pass
        
        return None
    
    def _parse_amount(self, amount_value) -> Optional[Decimal]:
        """Enhanced amount parsing with currency symbol handling."""
        if amount_value is None or amount_value == '':
            return None
        
        # Convert to string
        amount_str = str(amount_value).strip()
        
        # Remove currency symbols and formatting
        amount_clean = re.sub(r'[€$£¥₹,\s]', '', amount_str)
        
        # Handle negative amounts in parentheses
        if amount_clean.startswith('(') and amount_clean.endswith(')'):
            amount_clean = '-' + amount_clean[1:-1]
        
        try:
            return Decimal(amount_clean)
        except (InvalidOperation, ValueError):
            return None
    
    def _generate_transaction_hash(self, transaction: Dict) -> str:
        """Generate hash for duplicate detection."""
        # Create a consistent string for hashing
        hash_string = f"{transaction['transaction_date']}|{transaction['beneficiary']}|{transaction['amount']}"
        return hashlib.md5(hash_string.encode()).hexdigest()
    
    def _get_confidence_level(self, confidence: float) -> models.CategorizationConfidence:
        """Convert confidence score to enum."""
        if confidence >= 0.91:
            return models.CategorizationConfidence.VERY_HIGH
        elif confidence >= 0.71:
            return models.CategorizationConfidence.HIGH
        elif confidence >= 0.41:
            return models.CategorizationConfidence.MEDIUM
        else:
            return models.CategorizationConfidence.LOW
    
    async def validate_file_structure(self, content: bytes, filename: str) -> Dict[str, Any]:
        """Enhanced file validation with detailed feedback."""
        try:
            file_type = '.' + filename.split('.')[-1].lower()
            
            # Process file
            raw_data = await self._process_file_content(content, filename, file_type)
            
            if not raw_data:
                return {"valid": False, "error": "No data found in file"}
            
            format_detected = self._detect_format(raw_data)
            issues = []
            suggestions = []
            
            # Check for required columns
            first_row = raw_data[0]
            columns = list(first_row.keys())
            
            # Validate date column
            has_date = any(self._column_matches(col, self.date_patterns) for col in columns)
            if not has_date:
                issues.append("No date column detected")
                suggestions.append("Ensure file has a column with dates (e.g., 'Date', 'Transaction Date')")
            
            # Validate description column
            has_description = any(self._column_matches(col, self.description_patterns) for col in columns)
            if not has_description:
                issues.append("No description/beneficiary column detected")
                suggestions.append("Ensure file has a column with transaction descriptions")
            
            # Validate amount column
            has_amount = any(self._column_matches(col, self.amount_patterns) for col in columns)
            if not has_amount:
                issues.append("No amount column detected")
                suggestions.append("Ensure file has a column with transaction amounts")
            
            # Test data quality on sample rows
            sample_size = min(5, len(raw_data))
            for i in range(sample_size):
                try:
                    self._normalize_single_transaction(raw_data[i], format_detected, i + 1)
                except Exception as e:
                    issues.append(f"Row {i + 2}: {str(e)}")
            
            return {
                "valid": len(issues) == 0,
                "format_detected": format_detected,
                "estimated_rows": len(raw_data),
                "columns_found": columns,
                "column_mapping": self._suggest_column_mapping(columns),
                "issues": issues,
                "suggestions": suggestions,
                "sample_data": raw_data[:3]  # First 3 rows for preview
            }
            
        except Exception as e:
            return {"valid": False, "error": str(e)}
    
    def _suggest_column_mapping(self, columns: List[str]) -> Dict[str, str]:
        """Suggest column mapping for manual override."""
        mapping = {}
        
        for col in columns:
            col_lower = col.lower().strip()
            
            if any(pattern in col_lower for pattern in ['date', 'datum', 'fecha']):
                mapping[col] = "date"
            elif any(pattern in col_lower for pattern in ['description', 'beneficiary', 'payee', 'merchant']):
                mapping[col] = "description"
            elif any(pattern in col_lower for pattern in ['amount', 'value', 'sum', 'total']):
                mapping[col] = "amount"
            elif any(pattern in col_lower for pattern in ['category', 'type', 'classification']):
                mapping[col] = "category"
        
        return mapping