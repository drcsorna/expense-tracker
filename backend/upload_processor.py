# backend/upload_processor.py
# Enhanced file processing utilities with staged data architecture

import io
import re
import asyncio
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
import json

# Use pandas for robust file processing
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    
# Relative import
from . import models

class ProgressTracker:
    """Handles real-time progress tracking via WebSocket."""
    
    def __init__(self, session_id: str, websocket_manager=None):
        self.session_id = session_id
        self.websocket_manager = websocket_manager
        self.current_stage = "initializing"
        self.progress_percentage = 0.0
        self.rows_processed = 0
        self.total_rows = 0
        
    async def update_progress(self, stage: str, progress: float, rows_processed: int = 0, total_rows: int = 0, message: str = ""):
        """Send progress update via WebSocket."""
        self.current_stage = stage
        self.progress_percentage = min(progress, 100.0)
        self.rows_processed = rows_processed
        self.total_rows = total_rows
        
        if self.websocket_manager:
            await self.websocket_manager.send_progress(self.session_id, {
                "stage": stage,
                "progress": self.progress_percentage,
                "rows_processed": rows_processed,
                "total_rows": total_rows,
                "message": message,
                "timestamp": datetime.utcnow().isoformat()
            })
    
    async def send_final_update(self, result: dict):
        """Send final completion update."""
        if self.websocket_manager:
            await self.websocket_manager.send_progress(self.session_id, {
                "stage": "completed" if result.get('success') else "failed",
                "progress": 100.0,
                "final_result": result,
                "timestamp": datetime.utcnow().isoformat()
            })

class StagedTransactionProcessor:
    """Handles processing of uploaded transaction files with staged architecture."""
    
    def __init__(self, progress_tracker: Optional[ProgressTracker] = None):
        self.progress_tracker = progress_tracker
        
    async def process_file_to_staged(
        self, 
        content: bytes, 
        filename: str, 
        file_type: str,
        upload_session: models.UploadSession,
        user: models.User,
        db: Session
    ) -> Dict[str, Any]:
        """Process file and create staged transactions."""
        
        try:
            # Stage 1: Parse file content
            if self.progress_tracker:
                await self.progress_tracker.update_progress("parsing", 10.0, message="Parsing file content...")
            
            if file_type == '.csv':
                raw_data = await self._process_csv_file(content)
            else:  # .xls or .xlsx
                raw_data = await self._process_excel_file(content)
            
            if not raw_data:
                return {"success": False, "error": "No valid data found in file"}
            
            # Store raw data in upload session
            upload_session.raw_data = raw_data[:1000]  # Store sample for audit
            upload_session.total_rows = len(raw_data)
            db.commit()
            
            # Stage 2: Detect format and validate
            if self.progress_tracker:
                await self.progress_tracker.update_progress("validating", 20.0, message="Detecting format and validating data...")
            
            format_detected = self._detect_format(raw_data)
            
            # Stage 3: Process transactions in batches
            if self.progress_tracker:
                await self.progress_tracker.update_progress("processing", 30.0, message="Processing transactions...")
            
            result = await self._process_transactions_to_staged(
                raw_data=raw_data,
                format_detected=format_detected,
                upload_session=upload_session,
                user=user,
                db=db
            )
            
            result.update({
                "success": True,
                "total_rows": len(raw_data),
                "format_detected": format_detected
            })
            
            return result
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _process_transactions_to_staged(
        self,
        raw_data: List[Dict[str, Any]],
        format_detected: str,
        upload_session: models.UploadSession,
        user: models.User,
        db: Session
    ) -> Dict[str, Any]:
        """Process raw transaction data into staged transactions."""
        
        mapper = TransactionMapper()
        duplicate_detector = EnhancedDeduplicationService()
        categorizer = SmartCategorizer(user.id, db)
        
        staged_count = 0
        error_count = 0
        duplicate_count = 0
        errors = []
        
        batch_size = 100
        total_rows = len(raw_data)
        
        for batch_start in range(0, total_rows, batch_size):
            batch_end = min(batch_start + batch_size, total_rows)
            batch = raw_data[batch_start:batch_end]
            
            # Update progress
            progress = 30.0 + (batch_end / total_rows) * 60.0  # 30% to 90%
            if self.progress_tracker:
                await self.progress_tracker.update_progress(
                    "processing", 
                    progress, 
                    batch_end, 
                    total_rows,
                    f"Processing batch {batch_start//batch_size + 1}..."
                )
            
            for idx, raw_transaction in enumerate(batch):
                try:
                    # Skip empty rows
                    if not any(str(v).strip() for v in raw_transaction.values() if v is not None):
                        continue
                    
                    # Map transaction fields
                    mapped_transaction = mapper.map_transaction_fields(raw_transaction, format_detected)
                    
                    # Validate required fields
                    validation_error = self._validate_transaction_data(mapped_transaction, batch_start + idx + 2)
                    if validation_error:
                        errors.append(validation_error)
                        error_count += 1
                        continue
                    
                    # Check for duplicates in existing confirmed transactions
                    if duplicate_detector.is_duplicate_transaction(mapped_transaction, user.id, db):
                        duplicate_count += 1
                        continue
                    
                    # Get smart categorization suggestions
                    category_suggestion = await categorizer.suggest_category(mapped_transaction['beneficiary'])
                    
                    # Create staged transaction
                    staged_transaction = models.StagedTransaction(
                        transaction_date=mapped_transaction['transaction_date'],
                        beneficiary=mapped_transaction['beneficiary'],
                        amount=mapped_transaction['amount'],
                        category=mapped_transaction.get('category'),
                        labels=mapped_transaction.get('labels'),
                        is_private=mapped_transaction.get('is_private', False),
                        suggested_category=category_suggestion.get('category'),
                        suggested_labels=category_suggestion.get('labels', []),
                        confidence_score=category_suggestion.get('confidence', 1.0),
                        raw_transaction_data=raw_transaction,
                        user_id=user.id,
                        upload_session_id=upload_session.id
                    )
                    
                    db.add(staged_transaction)
                    staged_count += 1
                    
                    # Commit in batches
                    if staged_count % 50 == 0:
                        db.commit()
                
                except Exception as e:
                    error_count += 1
                    errors.append(f"Row {batch_start + idx + 2}: {str(e)}")
            
            # Commit batch
            db.commit()
            
            # Add small delay to prevent overwhelming the system
            if batch_end < total_rows:
                await asyncio.sleep(0.1)
        
        # Final progress update
        if self.progress_tracker:
            await self.progress_tracker.update_progress(
                "finalizing", 
                95.0, 
                total_rows, 
                total_rows,
                "Finalizing staged transactions..."
            )
        
        # Update upload session
        upload_session.staged_count = staged_count
        upload_session.error_count = error_count
        upload_session.duplicate_count = duplicate_count
        upload_session.processed_rows = total_rows
        db.commit()
        
        return {
            "staged_count": staged_count,
            "error_count": error_count,
            "duplicate_count": duplicate_count,
            "errors": errors[:10]  # Limit errors in response
        }
    
    def _validate_transaction_data(self, transaction: Dict[str, Any], row_num: int) -> Optional[str]:
        """Validate transaction data and return error message if invalid."""
        if not transaction.get('transaction_date'):
            return f"Row {row_num}: Missing or invalid date"
        
        if not transaction.get('beneficiary'):
            return f"Row {row_num}: Missing beneficiary/description"
        
        if transaction.get('amount') is None:
            return f"Row {row_num}: Missing or invalid amount"
        
        return None
    
    async def validate_file_structure(self, content: bytes, filename: str) -> Dict[str, Any]:
        """Validate file structure without full processing."""
        try:
            file_type = '.' + filename.split('.')[-1].lower()
            
            if file_type == '.csv':
                raw_data = await self._process_csv_file(content)
            else:
                raw_data = await self._process_excel_file(content)
            
            if not raw_data:
                return {"valid": False, "error": "No data found in file"}
            
            format_detected = self._detect_format(raw_data)
            issues = []
            suggestions = []
            
            # Check for required columns based on detected format
            first_row = raw_data[0]
            columns = list(first_row.keys())
            
            if format_detected == "unknown":
                issues.append("Could not detect a known format")
                suggestions.append("Ensure file has date, description, and amount columns")
            
            return {
                "valid": len(issues) == 0,
                "format_detected": format_detected,
                "estimated_rows": len(raw_data),
                "columns_found": columns,
                "issues": issues,
                "suggestions": suggestions
            }
            
        except Exception as e:
            return {"valid": False, "error": str(e)}
    
    async def _process_csv_file(self, content: bytes) -> List[Dict[str, Any]]:
        """Process CSV files with enhanced error handling."""
        if not PANDAS_AVAILABLE:
            raise ValueError("Pandas is required for CSV processing")
        
        try:
            csv_string = self._decode_content(content)
            df = pd.read_csv(io.StringIO(csv_string))
            df.columns = df.columns.str.strip()
            df = df.dropna(how='all')
            
            # Filter out rows with NaN in critical columns
            critical_columns = ['Date', 'Transaction Date', 'Completed Date', 'datum', 'transactiondate']
            date_column = None
            for col in df.columns:
                if col.lower().strip() in [c.lower() for c in critical_columns]:
                    date_column = col
                    break
            
            if date_column:
                df = df.dropna(subset=[date_column])
            
            return df.to_dict('records')
            
        except Exception as e:
            raise ValueError(f"Could not process CSV file: {str(e)}")
    
    async def _process_excel_file(self, content: bytes) -> List[Dict[str, Any]]:
        """Process Excel files with enhanced error handling."""
        if not PANDAS_AVAILABLE:
            raise ValueError("Pandas is required for Excel processing")
        
        try:
            engine = 'openpyxl' if content[:4] != b'\xd0\xcf\x11\xe0' else 'xlrd'
            df = pd.read_excel(io.BytesIO(content), engine=engine)
            df.columns = df.columns.str.strip().str.lower()
            df = df.dropna(how='all')
            return df.to_dict('records')
            
        except Exception as e:
            raise ValueError(f"Could not process Excel file: {str(e)}")
    
    def _detect_format(self, data: List[Dict[str, Any]]) -> str:
        """Detect transaction format based on available fields."""
        if not data:
            return "unknown"
        
        first_row = data[0]
        available_fields = set(str(k).lower().strip() for k in first_row.keys())
        
        if 'completed date' in available_fields or 'completed_date' in available_fields:
            return 'revolut'
        elif 'transactiondate' in available_fields and any('mutation' in field for field in available_fields):
            return 'dutch_bank'
        elif any(field in available_fields for field in ['date', 'datum']) and 'amount' in available_fields:
            return 'generic'
        else:
            return 'unknown'
    
    @staticmethod
    def _decode_content(content: bytes) -> str:
        """Decode content with multiple encoding attempts."""
        encodings = ['utf-8', 'utf-8-sig', 'iso-8859-1', 'cp1252', 'utf-16']
        
        for encoding in encodings:
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        
        raise ValueError("Could not decode file with any common encoding")

class TransactionMapper:
    """Enhanced transaction mapping with format-specific logic."""
    
    def map_transaction_fields(self, raw_data: Dict[str, Any], format_type: str) -> Dict[str, Any]:
        """Map transaction fields based on detected format."""
        normalized_data = {str(k).lower().strip(): v for k, v in raw_data.items()}
        
        if format_type == 'revolut':
            return self._map_revolut_transaction(normalized_data, raw_data)
        elif format_type == 'dutch_bank':
            return self._map_dutch_bank_transaction(normalized_data, raw_data)
        else:
            return self._map_generic_transaction(normalized_data, raw_data)
    
    def _map_revolut_transaction(self, normalized_data: Dict[str, Any], original_data: Dict[str, Any]) -> Dict[str, Any]:
        """Map Revolut CSV format."""
        date_value = self._find_field_value(normalized_data, ['completed date', 'completed_date', 'date'])
        transaction_date = self._parse_date(date_value)
        
        beneficiary = self._find_field_value(normalized_data, ['description'])
        beneficiary = str(beneficiary).strip() if beneficiary else 'Unknown'
        
        amount_value = self._find_field_value(normalized_data, ['amount'])
        amount = self._parse_amount(amount_value)
        
        category = self._find_field_value(normalized_data, ['type'])
        category = str(category) if category else None
        
        labels = []
        currency = self._find_field_value(normalized_data, ['currency'])
        if currency and str(currency).upper() != 'EUR':
            labels.append(f"currency_{currency}")
        
        return {
            'transaction_date': transaction_date,
            'beneficiary': beneficiary,
            'amount': amount,
            'category': category,
            'labels': labels,
            'is_private': False
        }
    
    def _map_dutch_bank_transaction(self, normalized_data: Dict[str, Any], original_data: Dict[str, Any]) -> Dict[str, Any]:
        """Map Dutch bank format."""
        date_value = self._find_field_value(normalized_data, ['transactiondate', 'transaction_date', 'datum'])
        transaction_date = self._parse_dutch_date(date_value)
        
        description = self._find_field_value(normalized_data, ['description', 'omschrijving', 'mededelingen'])
        description = str(description) if description else ''
        beneficiary = self._extract_beneficiary_from_dutch_description(description)
        
        amount_value = self._find_field_value(normalized_data, ['amount', 'bedrag'])
        amount = self._parse_amount(amount_value)
        
        category = self._find_field_value(normalized_data, ['mutationcode', 'mutation_code', 'code'])
        category = str(category) if category else None
        
        return {
            'transaction_date': transaction_date,
            'beneficiary': beneficiary,
            'amount': amount,
            'category': category,
            'labels': [],
            'is_private': False
        }
    
    def _map_generic_transaction(self, normalized_data: Dict[str, Any], original_data: Dict[str, Any]) -> Dict[str, Any]:
        """Map generic transaction format."""
        date_value = self._find_field_value(normalized_data, ['date', 'transaction_date', 'datum', 'completed_date'])
        transaction_date = self._parse_date(date_value)
        
        beneficiary = self._find_field_value(normalized_data, ['description', 'beneficiary', 'merchant', 'omschrijving'])
        beneficiary = str(beneficiary).strip() if beneficiary else 'Unknown'
        
        amount_value = self._find_field_value(normalized_data, ['amount', 'value', 'bedrag'])
        amount = self._parse_amount(amount_value)
        
        category = self._find_field_value(normalized_data, ['type', 'category', 'code'])
        category = str(category) if category else None
        
        return {
            'transaction_date': transaction_date,
            'beneficiary': beneficiary,
            'amount': amount,
            'category': category,
            'labels': [],
            'is_private': False
        }
    
    def _find_field_value(self, data: Dict[str, Any], field_names: List[str]) -> Any:
        """Find the first available field value."""
        for field_name in field_names:
            if field_name in data and data[field_name] is not None:
                return data[field_name]
        return None
    
    def _parse_date(self, date_value: Any) -> datetime.date:
        """Parse various date formats."""
        if date_value is None or str(date_value).lower().strip() in ['nan', 'nat', '', 'null']:
            raise ValueError("Date field is required but not found or is empty")
        
        date_str = str(date_value).strip()
        
        if not date_str or date_str.lower() in ['nan', 'nat', 'null', 'none']:
            raise ValueError("Invalid or empty date value")
        
        date_formats = [
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d',
            '%d/%m/%Y',
            '%d-%m-%Y',
            '%m/%d/%Y',
            '%Y%m%d',
        ]
        
        for fmt in date_formats:
            try:
                parsed_date = datetime.strptime(date_str, fmt)
                return parsed_date.date()
            except ValueError:
                continue
        
        raise ValueError(f"Could not parse date: {date_value}")
    
    def _parse_dutch_date(self, date_value: Any) -> datetime.date:
        """Parse Dutch bank date format."""
        if date_value is None:
            raise ValueError("Date field is required")
        
        date_str = str(int(float(date_value))) if isinstance(date_value, (int, float)) else str(date_value)
        date_str = date_str.strip()
        
        if len(date_str) == 8 and date_str.isdigit():
            try:
                return datetime.strptime(date_str, '%Y%m%d').date()
            except ValueError:
                pass
        
        return self._parse_date(date_value)
    
    def _parse_amount(self, amount_value: Any) -> Decimal:
        """Parse amount value."""
        if amount_value is None:
            raise ValueError("Amount field is required")
        
        try:
            if isinstance(amount_value, str):
                cleaned = re.sub(r'[€$£¥\s]', '', amount_value)
                cleaned = cleaned.replace(',', '.')
                return Decimal(cleaned)
            else:
                return Decimal(str(amount_value))
        except (InvalidOperation, ValueError) as e:
            raise ValueError(f"Could not parse amount: {amount_value}")
    
    def _extract_beneficiary_from_dutch_description(self, description: str) -> str:
        """Extract beneficiary from Dutch bank descriptions."""
        if not description:
            return 'Unknown'
        
        if ', ' in description:
            parts = description.split(', ')
            if len(parts) >= 2:
                potential_beneficiary = parts[1].split(',')[0].strip()
                if potential_beneficiary:
                    return potential_beneficiary
        
        iban_match = re.search(r'IBAN:\s*[A-Z]{2}\d{2}[A-Z0-9]+\s+(.+?)(?:,|$)', description, re.IGNORECASE)
        if iban_match:
            return iban_match.group(1).strip()
        
        cleaned = re.sub(r'\s+', ' ', description).strip()
        return cleaned[:50] if len(cleaned) > 50 else cleaned

class EnhancedDeduplicationService:
    """Enhanced deduplication with better similarity matching."""
    
    def is_duplicate_transaction(self, transaction: Dict[str, Any], user_id: int, db: Session) -> bool:
        """Check for duplicates using multiple criteria."""
        # Check exact matches first
        existing_exact = db.query(models.Transaction).filter(
            models.Transaction.owner_id == user_id,
            models.Transaction.transaction_date == transaction['transaction_date'],
            models.Transaction.amount == transaction['amount'],
            models.Transaction.beneficiary == transaction['beneficiary']
        ).first()
        
        if existing_exact:
            return True
        
        # Check fuzzy matches
        similar_transactions = db.query(models.Transaction).filter(
            models.Transaction.owner_id == user_id,
            models.Transaction.transaction_date == transaction['transaction_date'],
            models.Transaction.amount == transaction['amount']
        ).all()
        
        new_beneficiary = transaction['beneficiary'].lower().strip()
        
        for existing in similar_transactions:
            existing_beneficiary = existing.beneficiary.lower().strip()
            similarity = self._calculate_similarity(existing_beneficiary, new_beneficiary)
            
            if similarity > 0.85:  # 85% similarity threshold
                return True
        
        return False
    
    def _calculate_similarity(self, str1: str, str2: str) -> float:
        """Calculate similarity using multiple methods."""
        if not str1 or not str2:
            return 0.0
        
        # Exact match
        if str1 == str2:
            return 1.0
        
        # Word-based Jaccard similarity
        words1 = set(str1.split())
        words2 = set(str2.split())
        
        if not words1 and not words2:
            return 1.0
        
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        
        jaccard = intersection / union if union > 0 else 0.0
        
        # Character-based similarity
        char_similarity = len(set(str1) & set(str2)) / len(set(str1) | set(str2))
        
        # Combined score
        return (jaccard * 0.7) + (char_similarity * 0.3)

class SmartCategorizer:
    """AI-powered transaction categorization."""
    
    def __init__(self, user_id: int, db: Session):
        self.user_id = user_id
        self.db = db
        self._load_user_patterns()
    
    def _load_user_patterns(self):
        """Load user's historical categorization patterns."""
        user_transactions = self.db.query(models.Transaction).filter(
            models.Transaction.owner_id == self.user_id,
            models.Transaction.category.isnot(None)
        ).all()
        
        self.merchant_patterns = {}
        for tx in user_transactions:
            merchant_key = tx.beneficiary.lower().strip()
            if merchant_key not in self.merchant_patterns:
                self.merchant_patterns[merchant_key] = {}
            
            category = tx.category
            if category in self.merchant_patterns[merchant_key]:
                self.merchant_patterns[merchant_key][category] += 1
            else:
                self.merchant_patterns[merchant_key][category] = 1
    
    async def suggest_category(self, beneficiary: str) -> Dict[str, Any]:
        """Suggest category based on beneficiary and patterns."""
        beneficiary_lower = beneficiary.lower().strip()
        
        # Check exact merchant match
        if beneficiary_lower in self.merchant_patterns:
            categories = self.merchant_patterns[beneficiary_lower]
            most_common_category = max(categories, key=categories.get)
            confidence = categories[most_common_category] / sum(categories.values())
            
            return {
                "category": most_common_category,
                "confidence": confidence,
                "labels": [f"pattern_match"],
                "reason": "Based on your previous categorizations"
            }
        
        # Check partial matches
        for pattern_merchant, categories in self.merchant_patterns.items():
            if self._calculate_merchant_similarity(beneficiary_lower, pattern_merchant) > 0.8:
                most_common_category = max(categories, key=categories.get)
                confidence = 0.7  # Lower confidence for partial matches
                
                return {
                    "category": most_common_category,
                    "confidence": confidence,
                    "labels": [f"similar_merchant"],
                    "reason": f"Similar to {pattern_merchant}"
                }
        
        # Rule-based categorization
        return self._rule_based_categorization(beneficiary)
    
    def _rule_based_categorization(self, beneficiary: str) -> Dict[str, Any]:
        """Rule-based categorization for new merchants."""
        beneficiary_lower = beneficiary.lower()
        
        # Define categorization rules
        rules = {
            "Food & Dining": ["restaurant", "cafe", "coffee", "pizza", "food", "dining", "bar", "pub"],
            "Transportation": ["uber", "taxi", "bus", "train", "gas", "fuel", "parking"],
            "Shopping": ["store", "shop", "market", "amazon", "ebay", "retail"],
            "Healthcare": ["hospital", "clinic", "pharmacy", "doctor", "medical"],
            "Entertainment": ["cinema", "movie", "netflix", "spotify", "game", "entertainment"],
            "Bills & Utilities": ["electric", "gas", "water", "internet", "phone", "utility"],
        }
        
        for category, keywords in rules.items():
            for keyword in keywords:
                if keyword in beneficiary_lower:
                    return {
                        "category": category,
                        "confidence": 0.6,
                        "labels": [f"rule_based"],
                        "reason": f"Contains keyword: {keyword}"
                    }
        
        return {
            "category": None,
            "confidence": 0.0,
            "labels": [],
            "reason": "No pattern found"
        }
    
    def _calculate_merchant_similarity(self, merchant1: str, merchant2: str) -> float:
        """Calculate similarity between merchant names."""
        words1 = set(merchant1.split())
        words2 = set(merchant2.split())
        
        if not words1 and not words2:
            return 1.0
        
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        
        return intersection / union if union > 0 else 0.0