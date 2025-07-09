# backend/upload_processor.py
# File processing utilities for transaction uploads

import io
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

# Use pandas for robust file processing
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    
# Relative import
from . import models


class TransactionUploadProcessor:
    """Handles processing of uploaded transaction files"""
    
    @staticmethod
    async def process_csv_file(content: bytes) -> List[Dict[str, Any]]:
        """Process CSV files (Revolut format and other CSV formats)"""
        if not PANDAS_AVAILABLE:
            raise ValueError("Pandas is required for CSV processing. Please install with: pip install pandas")
            
        try:
            # Decode content with multiple encoding attempts
            csv_string = TransactionUploadProcessor._decode_content(content)
            
            # Use pandas for robust CSV parsing
            df = pd.read_csv(io.StringIO(csv_string))
            
            # Clean up column names (strip whitespace, normalize)
            df.columns = df.columns.str.strip()
            
            # Remove completely empty rows and rows where all values are NaN
            df = df.dropna(how='all')
            
            # Filter out rows where critical fields are empty/NaN
            # This will help reduce the "Could not parse date: nan" errors
            critical_date_columns = ['Date', 'Transaction Date', 'Completed Date', 'datum', 'transactiondate']
            date_column = None
            for col in df.columns:
                if col.lower().strip() in [c.lower() for c in critical_date_columns]:
                    date_column = col
                    break
            
            if date_column:
                # Remove rows where the date column is NaN/empty
                df = df.dropna(subset=[date_column])
            
            # Convert to list of dictionaries
            return df.to_dict('records')
            
        except Exception as e:
            raise ValueError(f"Could not process CSV file: {str(e)}")

    @staticmethod
    async def process_excel_file(content: bytes) -> List[Dict[str, Any]]:
        """Process Excel files (XLS/XLSX - Dutch bank format and others)"""
        if not PANDAS_AVAILABLE:
            raise ValueError("Pandas is required for Excel processing. Please install with: pip install pandas")
            
        try:
            # Determine Excel engine based on file signature
            engine = 'openpyxl' if content[:4] != b'\xd0\xcf\x11\xe0' else 'xlrd'
            
            # Read Excel file
            df = pd.read_excel(
                io.BytesIO(content), 
                engine=engine
            )
            
            # Clean up column names (strip whitespace, normalize case)
            df.columns = df.columns.str.strip().str.lower()
            
            # Remove empty rows
            df = df.dropna(how='all')
            
            # Convert to list of dictionaries
            return df.to_dict('records')
            
        except Exception as e:
            raise ValueError(f"Could not process Excel file: {str(e)}")

    @staticmethod
    def _decode_content(content: bytes) -> str:
        """Attempt to decode content with multiple encodings"""
        encodings = ['utf-8', 'utf-8-sig', 'iso-8859-1', 'cp1252', 'utf-16']
        
        for encoding in encodings:
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
                
        raise ValueError("Could not decode file with any common encoding")


class TransactionMapper:
    """Maps different file formats to our unified transaction model"""
    
    # Common field mappings for different formats
    FIELD_MAPPINGS = {
        # Revolut CSV format
        'revolut': {
            'date_fields': ['Completed Date', 'completed_date', 'date'],
            'description_fields': ['Description', 'description'],
            'amount_fields': ['Amount', 'amount'],
            'type_fields': ['Type', 'type'],
            'currency_fields': ['Currency', 'currency'],
        },
        # Dutch bank XLS format
        'dutch_bank': {
            'date_fields': ['transactiondate', 'transaction_date', 'datum'],
            'description_fields': ['description', 'omschrijving', 'mededelingen'],
            'amount_fields': ['amount', 'bedrag'],
            'type_fields': ['mutationcode', 'mutation_code', 'code'],
            'account_fields': ['accountNumber', 'accountnumber', 'rekening'],
        },
        # Generic format
        'generic': {
            'date_fields': ['date', 'transaction_date', 'datum', 'completed_date'],
            'description_fields': ['description', 'beneficiary', 'merchant', 'omschrijving'],
            'amount_fields': ['amount', 'value', 'bedrag'],
            'type_fields': ['type', 'category', 'code'],
        }
    }
    
    @staticmethod
    def map_transaction_fields(raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Map different file formats to our unified transaction model.
        Auto-detects format and maps fields accordingly.
        """
        
        # Normalize keys for case-insensitive comparison
        normalized_data = {k.lower().strip(): v for k, v in raw_data.items()}
        available_fields = set(normalized_data.keys())
        
        # Detect format
        format_type = TransactionMapper._detect_format(available_fields)
        
        # Map fields based on detected format
        if format_type == 'revolut':
            return TransactionMapper._map_revolut_transaction(normalized_data, raw_data)
        elif format_type == 'dutch_bank':
            return TransactionMapper._map_dutch_bank_transaction(normalized_data, raw_data)
        else:
            return TransactionMapper._map_generic_transaction(normalized_data, raw_data)

    @staticmethod
    def _detect_format(available_fields: set) -> str:
        """Detect the transaction format based on available fields"""
        
        # Check for Revolut format
        if 'completed date' in available_fields or 'completed_date' in available_fields:
            return 'revolut'
        
        # Check for Dutch bank format
        if 'transactiondate' in available_fields and 'mutationcode' in available_fields:
            return 'dutch_bank'
        
        # Default to generic
        return 'generic'

    @staticmethod
    def _map_revolut_transaction(normalized_data: Dict[str, Any], original_data: Dict[str, Any]) -> Dict[str, Any]:
        """Map Revolut CSV format to our model"""
        
        # Parse date
        date_value = TransactionMapper._find_field_value(normalized_data, ['completed date', 'completed_date', 'date'])
        transaction_date = TransactionMapper._parse_date(date_value)
        
        # Get description/beneficiary
        beneficiary = TransactionMapper._find_field_value(normalized_data, ['description'])
        beneficiary = str(beneficiary).strip() if beneficiary else 'Unknown'
        
        # Parse amount
        amount_value = TransactionMapper._find_field_value(normalized_data, ['amount'])
        amount = TransactionMapper._parse_amount(amount_value)
        
        # Get category/type
        category = TransactionMapper._find_field_value(normalized_data, ['type'])
        category = str(category) if category else 'UNKNOWN'
        
        # Create labels
        labels = []
        currency = TransactionMapper._find_field_value(normalized_data, ['currency'])
        if currency and str(currency).upper() != 'EUR':
            labels.append(f"currency_{currency}")
        
        product = TransactionMapper._find_field_value(normalized_data, ['product'])
        if product:
            labels.append(f"product_{product}")
        
        return {
            'transaction_date': transaction_date,
            'beneficiary': beneficiary,
            'amount': amount,
            'category': category,
            'labels': labels,
            'is_private': False,
            'raw_data': original_data
        }

    @staticmethod
    def _map_dutch_bank_transaction(normalized_data: Dict[str, Any], original_data: Dict[str, Any]) -> Dict[str, Any]:
        """Map Dutch bank XLS format to our model"""
        
        # Parse date (typically YYYYMMDD format)
        date_value = TransactionMapper._find_field_value(normalized_data, ['transactiondate', 'transaction_date', 'datum'])
        transaction_date = TransactionMapper._parse_dutch_date(date_value)
        
        # Get description and extract beneficiary
        description = TransactionMapper._find_field_value(normalized_data, ['description', 'omschrijving', 'mededelingen'])
        description = str(description) if description else ''
        beneficiary = TransactionMapper._extract_beneficiary_from_dutch_description(description)
        
        # Parse amount
        amount_value = TransactionMapper._find_field_value(normalized_data, ['amount', 'bedrag'])
        amount = TransactionMapper._parse_amount(amount_value)
        
        # Get mutation code as category
        category = TransactionMapper._find_field_value(normalized_data, ['mutationcode', 'mutation_code', 'code'])
        category = str(category) if category else 'UNKNOWN'
        
        # Add account number as label
        labels = []
        account = TransactionMapper._find_field_value(normalized_data, ['accountnumber', 'account_number', 'rekening'])
        if account:
            labels.append(f"account_{account}")
        
        return {
            'transaction_date': transaction_date,
            'beneficiary': beneficiary,
            'amount': amount,
            'category': category,
            'labels': labels,
            'is_private': False,
            'raw_data': original_data
        }

    @staticmethod
    def _map_generic_transaction(normalized_data: Dict[str, Any], original_data: Dict[str, Any]) -> Dict[str, Any]:
        """Map generic transaction format to our model"""
        
        # Parse date
        date_value = TransactionMapper._find_field_value(
            normalized_data, 
            ['date', 'transaction_date', 'datum', 'completed_date']
        )
        transaction_date = TransactionMapper._parse_date(date_value)
        
        # Get beneficiary
        beneficiary = TransactionMapper._find_field_value(
            normalized_data, 
            ['description', 'beneficiary', 'merchant', 'omschrijving']
        )
        beneficiary = str(beneficiary).strip() if beneficiary else 'Unknown'
        
        # Parse amount
        amount_value = TransactionMapper._find_field_value(normalized_data, ['amount', 'value', 'bedrag'])
        amount = TransactionMapper._parse_amount(amount_value)
        
        # Get category
        category = TransactionMapper._find_field_value(normalized_data, ['type', 'category', 'code'])
        category = str(category) if category else 'UNKNOWN'
        
        return {
            'transaction_date': transaction_date,
            'beneficiary': beneficiary,
            'amount': amount,
            'category': category,
            'labels': [],
            'is_private': False,
            'raw_data': original_data
        }

    @staticmethod
    def _find_field_value(data: Dict[str, Any], field_names: List[str]) -> Any:
        """Find the first available field value from a list of possible field names"""
        for field_name in field_names:
            if field_name in data and data[field_name] is not None:
                return data[field_name]
        return None

    @staticmethod
    def _parse_date(date_value: Any) -> datetime.date:
        """Parse various date formats into a date object"""
        if date_value is None or str(date_value).lower().strip() in ['nan', 'nat', '', 'null']:
            raise ValueError("Date field is required but not found or is empty")
        
        date_str = str(date_value).strip()
        
        # Skip empty or invalid dates
        if not date_str or date_str.lower() in ['nan', 'nat', 'null', 'none']:
            raise ValueError("Invalid or empty date value")
        
        # Common date formats to try
        date_formats = [
            '%Y-%m-%d %H:%M:%S',  # 2024-02-23 10:28:23
            '%Y-%m-%d',           # 2024-02-23
            '%d/%m/%Y',           # 23/02/2024
            '%d-%m-%Y',           # 23-02-2024
            '%m/%d/%Y',           # 02/23/2024
            '%Y%m%d',             # 20240223
        ]
        
        for fmt in date_formats:
            try:
                parsed_date = datetime.strptime(date_str, fmt)
                return parsed_date.date()
            except ValueError:
                continue
        
        raise ValueError(f"Could not parse date: {date_value}")

    @staticmethod
    def _parse_dutch_date(date_value: Any) -> datetime.date:
        """Parse Dutch bank date format (typically YYYYMMDD)"""
        if date_value is None:
            raise ValueError("Date field is required")
        
        # Convert to string and remove any decimal points
        date_str = str(int(float(date_value))) if isinstance(date_value, (int, float)) else str(date_value)
        date_str = date_str.strip()
        
        # Handle YYYYMMDD format
        if len(date_str) == 8 and date_str.isdigit():
            try:
                return datetime.strptime(date_str, '%Y%m%d').date()
            except ValueError:
                pass
        
        # Fallback to generic date parsing
        return TransactionMapper._parse_date(date_value)

    @staticmethod
    def _parse_amount(amount_value: Any) -> Decimal:
        """Parse amount value into Decimal"""
        if amount_value is None:
            raise ValueError("Amount field is required")
        
        try:
            # Handle string amounts with currency symbols or commas
            if isinstance(amount_value, str):
                # Remove currency symbols and normalize
                cleaned = re.sub(r'[€$£¥\s]', '', amount_value)
                # Replace comma decimal separator with dot
                cleaned = cleaned.replace(',', '.')
                return Decimal(cleaned)
            else:
                return Decimal(str(amount_value))
        except (InvalidOperation, ValueError) as e:
            raise ValueError(f"Could not parse amount: {amount_value}")

    @staticmethod
    def _extract_beneficiary_from_dutch_description(description: str) -> str:
        """Extract meaningful beneficiary name from Dutch bank transaction descriptions"""
        if not description:
            return 'Unknown'
        
        # Common Dutch bank transaction patterns
        if ', ' in description:
            parts = description.split(', ')
            if len(parts) >= 2:
                # Skip transaction type (BEA, GEA, etc.) and get merchant name
                potential_beneficiary = parts[1].split(',')[0].strip()
                if potential_beneficiary:
                    return potential_beneficiary
        
        # Extract from IBAN patterns like "IBAN: NL12BANK1234567890 Name"
        iban_match = re.search(r'IBAN:\s*[A-Z]{2}\d{2}[A-Z0-9]+\s+(.+?)(?:,|$)', description, re.IGNORECASE)
        if iban_match:
            return iban_match.group(1).strip()
        
        # Fallback: take first meaningful part (up to 50 chars)
        cleaned = re.sub(r'\s+', ' ', description).strip()
        return cleaned[:50] if len(cleaned) > 50 else cleaned


class DeduplicationService:
    """Handles transaction deduplication logic"""
    
    @staticmethod
    def is_duplicate_transaction(transaction: Dict[str, Any], user_id: int, db: Session) -> bool:
        """
        Check if transaction already exists using improved fuzzy matching.
        Uses date + amount + beneficiary similarity for deduplication.
        """
        
        # Check if similar transaction exists (within same day, same amount)
        existing_transactions = db.query(models.Transaction).filter(
            models.Transaction.owner_id == user_id,
            models.Transaction.transaction_date == transaction['transaction_date'],
            models.Transaction.amount == transaction['amount']
        ).all()
        
        if not existing_transactions:
            return False
        
        # Additional check: similar beneficiary
        new_beneficiary = transaction['beneficiary'].lower().strip()
        
        for existing in existing_transactions:
            existing_beneficiary = existing.beneficiary.lower().strip()
            
            # Calculate similarity using Jaccard similarity
            similarity = DeduplicationService._calculate_similarity(existing_beneficiary, new_beneficiary)
            
            # If 80% similar, consider it a duplicate
            if similarity > 0.8:
                return True
        
        return False

    @staticmethod
    def _calculate_similarity(str1: str, str2: str) -> float:
        """Calculate Jaccard similarity between two strings"""
        if not str1 or not str2:
            return 0.0
        
        # Use word-based similarity for better matching
        words1 = set(str1.split())
        words2 = set(str2.split())
        
        if not words1 and not words2:
            return 1.0
        
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        
        return intersection / union if union > 0 else 0.0