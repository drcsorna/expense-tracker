# backend/upload_processor.py
# File processing utilities for transaction uploads

import io
import hashlib
import pandas as pd
from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, List
from sqlalchemy.orm import Session

import models


class TransactionUploadProcessor:
    """Handles processing of uploaded transaction files"""
    
    @staticmethod
    async def process_csv_file(content: bytes) -> List[Dict[str, Any]]:
        """Process CSV files (Revolut format)"""
        try:
            # Decode content
            csv_string = content.decode('utf-8')
            
            # Use pandas for robust CSV parsing
            df = pd.read_csv(io.StringIO(csv_string))
            
            # Convert to list of dictionaries
            return df.to_dict('records')
            
        except UnicodeDecodeError:
            # Try different encodings common in Europe
            for encoding in ['iso-8859-1', 'cp1252', 'utf-16']:
                try:
                    csv_string = content.decode(encoding)
                    df = pd.read_csv(io.StringIO(csv_string))
                    return df.to_dict('records')
                except:
                    continue
            raise ValueError("Could not decode CSV file with any common encoding")

    @staticmethod
    async def process_excel_file(content: bytes) -> List[Dict[str, Any]]:
        """Process Excel files (XLS/XLSX - Dutch bank format)"""
        try:
            # Read Excel file
            df = pd.read_excel(
                io.BytesIO(content), 
                engine='openpyxl' if content[:4] != b'\xd0\xcf\x11\xe0' else 'xlrd'
            )
            
            # Remove empty rows
            df = df.dropna(how='all')
            
            # Convert to list of dictionaries
            return df.to_dict('records')
            
        except Exception as e:
            raise ValueError(f"Could not process Excel file: {str(e)}")


class TransactionMapper:
    """Maps different file formats to our unified transaction model"""
    
    @staticmethod
    def map_transaction_fields(raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Map different file formats to our unified transaction model.
        Handles both CSV (Revolut) and XLS (Dutch bank) formats.
        """
        
        # Detect format by checking key fields
        if 'Completed Date' in raw_data and 'Description' in raw_data:
            # CSV format (Revolut-style)
            return TransactionMapper._map_csv_transaction(raw_data)
        elif 'transactiondate' in raw_data and 'description' in raw_data:
            # XLS format (Dutch bank-style)
            return TransactionMapper._map_xls_transaction(raw_data)
        else:
            raise ValueError(f"Unknown transaction format. Available fields: {list(raw_data.keys())}")

    @staticmethod
    def _map_csv_transaction(data: Dict[str, Any]) -> Dict[str, Any]:
        """Map CSV (Revolut) format to our model"""
        
        # Parse date - handle "2024-02-23 10:28:23" format
        date_str = str(data['Completed Date'])
        transaction_date = datetime.strptime(date_str.split(' ')[0], '%Y-%m-%d').date()
        
        # Clean description (use as beneficiary)
        beneficiary = str(data['Description']).strip()
        
        # Handle amount
        amount = Decimal(str(data['Amount']))
        
        # Determine category from Type
        category = str(data.get('Type', 'UNKNOWN'))
        
        # Create labels from available metadata
        labels = []
        if data.get('Currency') != 'EUR':
            labels.append(f"currency_{data['Currency']}")
        if data.get('Product'):
            labels.append(f"product_{data['Product']}")
        
        return {
            'transaction_date': transaction_date,
            'beneficiary': beneficiary,
            'amount': amount,
            'category': category,
            'labels': labels,
            'is_private': False
        }

    @staticmethod
    def _map_xls_transaction(data: Dict[str, Any]) -> Dict[str, Any]:
        """Map XLS (Dutch bank) format to our model"""
        
        # Parse date - handle 20240104 format
        date_str = str(int(data['transactiondate']))  # Remove any decimal
        transaction_date = datetime.strptime(date_str, '%Y%m%d').date()
        
        # Clean description - Dutch banks have verbose descriptions
        description = str(data['description']).strip()
        
        # Extract beneficiary from Dutch bank description
        beneficiary = TransactionMapper._extract_beneficiary_from_dutch_description(description)
        
        # Handle amount
        amount = Decimal(str(data['amount']))
        
        # Use mutation code as category
        category = str(data.get('mutationcode', 'UNKNOWN'))
        
        # Add account number as label for tracking
        labels = []
        if data.get('accountNumber'):
            labels.append(f"account_{data['accountNumber']}")
        
        return {
            'transaction_date': transaction_date,
            'beneficiary': beneficiary,
            'amount': amount,
            'category': category,
            'labels': labels,
            'is_private': False
        }

    @staticmethod
    def _extract_beneficiary_from_dutch_description(description: str) -> str:
        """
        Extract meaningful beneficiary name from Dutch bank transaction descriptions.
        Handles formats like: "BEA, Google Pay ESSO VALKENBOS,PAS011..."
        """
        
        # Common Dutch bank transaction patterns
        if ', ' in description:
            parts = description.split(', ')
            if len(parts) >= 2:
                # Skip transaction type (BEA, GEA, etc.) and get merchant name
                potential_beneficiary = parts[1].split(',')[0].strip()
                if potential_beneficiary:
                    return potential_beneficiary
        
        # Fallback: take first meaningful part (up to 50 chars)
        cleaned = description.replace('  ', ' ').strip()
        return cleaned[:50] if len(cleaned) > 50 else cleaned


class DeduplicationService:
    """Handles transaction deduplication logic"""
    
    @staticmethod
    def is_duplicate_transaction(transaction: Dict[str, Any], user_id: int, db: Session) -> bool:
        """
        Check if transaction already exists using fuzzy matching.
        Uses date + amount + beneficiary similarity for deduplication.
        """
        
        # Check if similar transaction exists (within same day, same amount)
        existing = db.query(models.Transaction).filter(
            models.Transaction.owner_id == user_id,
            models.Transaction.transaction_date == transaction['transaction_date'],
            models.Transaction.amount == transaction['amount']
        ).first()
        
        if existing:
            # Additional check: similar beneficiary (first 20 chars)
            existing_beneficiary = existing.beneficiary[:20].lower()
            new_beneficiary = transaction['beneficiary'][:20].lower()
            
            # If 80% similar, consider it a duplicate
            similarity = len(set(existing_beneficiary) & set(new_beneficiary)) / max(
                len(existing_beneficiary), len(new_beneficiary), 1
            )
            return similarity > 0.8
        
        return False