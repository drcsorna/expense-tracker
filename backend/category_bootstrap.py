# backend/category_bootstrap.py
# Bootstrap categorization engine from existing categorized data (Hungarian)

import io
import csv
import re
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Tuple, Any
from sqlalchemy.orm import Session
from collections import defaultdict

# Excel processing with fallback
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

# Fuzzy matching with fallback
try:
    from fuzzywuzzy import fuzz
    FUZZY_AVAILABLE = True
except ImportError:
    FUZZY_AVAILABLE = False

from . import models

class CategoryBootstrap:
    """Bootstrap categorization rules from existing categorized data (Hungarian transactions)."""
    
    def __init__(self, user_id: int, db: Session):
        self.user_id = user_id
        self.db = db
        self.required_columns = ['date', 'beneficiary', 'amount', 'category']
        self.optional_columns = ['description', 'memo', 'notes']
        
        # Hungarian -> English category mappings (default)
        self.default_category_mapping = {
            "kávé": "Food & Beverage",
            "ruha": "Clothing", 
            "háztartás": "Household",
            "autó": "Transportation",
            "étel": "Food & Beverage",
            "szórakozás": "Entertainment",
            "egyéb": "Other",
            "bevásárlás": "Shopping",
            "egészség": "Healthcare",
            "oktatás": "Education",
            "sport": "Sports & Fitness",
            "utazás": "Travel",
            "munka": "Business",
            "bank": "Banking & Fees",
            "biztosítás": "Insurance",
            "számla": "Bills & Utilities",
            "telefon": "Phone & Internet",
            "áram": "Utilities",
            "víz": "Utilities",
            "gáz": "Utilities",
            "internet": "Phone & Internet",
            "benzin": "Transportation",
            "parkolás": "Transportation",
            "taxi": "Transportation",
            "vonat": "Transportation",
            "busz": "Transportation",
            "repülő": "Travel",
            "szálloda": "Travel",
            "étterem": "Food & Beverage",
            "mozi": "Entertainment",
            "könyv": "Education",
            "gyógyszer": "Healthcare",
            "fogorvos": "Healthcare",
            "orvos": "Healthcare"
        }
        
        # Hungarian column name patterns
        self.hungarian_column_patterns = {
            'date': ['dátum', 'datum', 'date', 'év', 'hónap', 'nap'],
            'beneficiary': ['beneficiary', 'kedvezményezett', 'üzlet', 'merchant', 'vendor', 'bolt'],
            'amount': ['összeg', 'osszeg', 'amount', 'érték', 'value'],
            'category': ['kategória', 'kategoria', 'category', 'típus', 'tipus', 'type']
        }
        
    async def process_bootstrap_file(self, content: bytes, filename: str) -> Dict[str, Any]:
        """Process uploaded Hungarian categorized data file."""
        
        try:
            # Parse file based on extension
            file_type = '.' + filename.split('.')[-1].lower()
            
            if file_type == '.csv':
                raw_data = await self._process_csv_file(content)
            elif file_type in ['.xlsx', '.xls']:
                raw_data = await self._process_excel_file(content)
            else:
                return {
                    "success": False,
                    "error": f"Unsupported file type: {file_type}",
                    "rows_processed": 0
                }
            
            if not raw_data:
                return {
                    "success": False,
                    "error": "No data found in file",
                    "rows_processed": 0
                }
            
            # Validate and map columns
            validation_result = self._validate_and_map_columns(raw_data)
            if not validation_result["valid"]:
                return {
                    "success": False,
                    "error": validation_result["error"],
                    "suggestions": validation_result.get("suggestions", []),
                    "columns_found": validation_result.get("columns_found", [])
                }
            
            column_mapping = validation_result["column_mapping"]
            
            # Extract patterns and create bootstrap data
            patterns_result = await self._extract_patterns(raw_data, column_mapping)
            
            return {
                "success": True,
                "rows_processed": patterns_result["rows_processed"],
                "patterns_extracted": patterns_result["patterns_count"],
                "category_mappings": patterns_result["category_mappings"],
                "merchant_patterns": patterns_result["merchant_patterns"],
                "bootstrap_ready": True,
                "column_mapping": column_mapping,
                "file_info": {
                    "filename": filename,
                    "file_type": file_type,
                    "processed_at": datetime.utcnow().isoformat()
                }
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": f"Bootstrap processing failed: {str(e)}",
                "rows_processed": 0
            }
    
    async def _process_csv_file(self, content: bytes) -> List[Dict[str, str]]:
        """Process CSV file content."""
        
        try:
            # Detect encoding
            text_content = content.decode('utf-8')
        except UnicodeDecodeError:
            try:
                text_content = content.decode('iso-8859-1')
            except UnicodeDecodeError:
                text_content = content.decode('cp1252', errors='ignore')
        
        # Parse CSV
        csv_file = io.StringIO(text_content)
        
        # Try different delimiters
        sample = text_content[:1024]
        delimiter = ',' if ',' in sample else ';' if ';' in sample else '\t'
        
        reader = csv.DictReader(csv_file, delimiter=delimiter)
        return list(reader)
    
    async def _process_excel_file(self, content: bytes) -> List[Dict[str, str]]:
        """Process Excel file content."""
        
        if not PANDAS_AVAILABLE:
            return []
        
        try:
            # Use pandas to read Excel
            df = pd.read_excel(io.BytesIO(content))
            
            # Convert to list of dictionaries
            return df.to_dict('records')
            
        except Exception as e:
            # Fallback: try to read as CSV
            return await self._process_csv_file(content)
    
    def _validate_and_map_columns(self, raw_data: List[Dict]) -> Dict[str, Any]:
        """Validate file structure and map Hungarian column names."""
        
        if not raw_data:
            return {"valid": False, "error": "No data found"}
        
        first_row = raw_data[0]
        columns = [col.lower().strip() for col in first_row.keys()]
        
        column_mapping = {}
        missing_columns = []
        
        # Map columns using Hungarian patterns
        for required_col in self.required_columns:
            found_col = self._find_column_by_patterns(columns, self.hungarian_column_patterns[required_col])
            if found_col:
                column_mapping[required_col] = found_col
            else:
                missing_columns.append(required_col)
        
        if missing_columns:
            return {
                "valid": False,
                "error": f"Missing required columns: {', '.join(missing_columns)}",
                "columns_found": list(first_row.keys()),
                "suggestions": [
                    f"Required columns: {', '.join(self.required_columns)}",
                    f"Hungarian names supported: {', '.join([', '.join(patterns) for patterns in self.hungarian_column_patterns.values()])}",
                    "The category column is essential for bootstrap learning"
                ]
            }
        
        return {
            "valid": True,
            "column_mapping": column_mapping,
            "columns_found": list(first_row.keys())
        }
    
    def _find_column_by_patterns(self, columns: List[str], patterns: List[str]) -> Optional[str]:
        """Find column name that matches any of the given patterns."""
        
        for pattern in patterns:
            pattern_lower = pattern.lower()
            for col in columns:
                if pattern_lower in col or col in pattern_lower:
                    return col
        return None
    
    async def _extract_patterns(self, raw_data: List[Dict], column_mapping: Dict[str, str]) -> Dict[str, Any]:
        """Extract categorization patterns from Hungarian data."""
        
        patterns_created = 0
        category_mappings = {}
        merchant_patterns = {}
        errors = []
        
        for i, row in enumerate(raw_data):
            try:
                # Extract data using column mapping
                date_str = str(row.get(column_mapping['date'], '')).strip()
                beneficiary = str(row.get(column_mapping['beneficiary'], '')).strip()
                amount_str = str(row.get(column_mapping['amount'], '')).strip()
                category_original = str(row.get(column_mapping['category'], '')).strip()
                
                # Skip empty rows
                if not all([date_str, beneficiary, amount_str, category_original]):
                    continue
                
                # Map Hungarian category to English
                category_english = self._map_hungarian_category(category_original)
                category_mappings[category_original] = category_english
                
                # Create merchant pattern
                merchant_key = beneficiary.lower().strip()
                if merchant_key not in merchant_patterns:
                    merchant_patterns[merchant_key] = {
                        "category": category_english,
                        "confidence": 1.0,
                        "occurrences": 1,
                        "original_category": category_original
                    }
                else:
                    merchant_patterns[merchant_key]["occurrences"] += 1
                    # Update confidence based on consistency
                    if merchant_patterns[merchant_key]["category"] == category_english:
                        merchant_patterns[merchant_key]["confidence"] = min(1.0, 
                            merchant_patterns[merchant_key]["confidence"] + 0.1)
                
                patterns_created += 1
                
            except Exception as e:
                errors.append(f"Row {i+1}: {str(e)}")
                continue
        
        # Store patterns in database (simplified - could be expanded)
        await self._store_bootstrap_patterns(merchant_patterns, category_mappings)
        
        return {
            "rows_processed": len(raw_data),
            "patterns_count": patterns_created,
            "category_mappings": len(category_mappings),
            "merchant_patterns": len(merchant_patterns),
            "errors": errors[:10]  # Limit error reporting
        }
    
    def _map_hungarian_category(self, hungarian_category: str) -> str:
        """Map Hungarian category to English equivalent."""
        
        category_lower = hungarian_category.lower().strip()
        
        # Direct mapping
        if category_lower in self.default_category_mapping:
            return self.default_category_mapping[category_lower]
        
        # Fuzzy matching (if available)
        if FUZZY_AVAILABLE:
            best_match = None
            best_score = 0
            
            for hungarian, english in self.default_category_mapping.items():
                score = fuzz.ratio(category_lower, hungarian)
                if score > best_score and score > 80:  # 80% similarity threshold
                    best_score = score
                    best_match = english
            
            if best_match:
                return best_match
        
        # Keyword-based mapping
        for hungarian, english in self.default_category_mapping.items():
            if hungarian in category_lower or category_lower in hungarian:
                return english
        
        # Default to original if no mapping found
        return hungarian_category.title()
    
    async def _store_bootstrap_patterns(self, merchant_patterns: Dict, category_mappings: Dict):
        """Store extracted patterns in database for future use."""
        
        try:
            # This is a simplified version - in full implementation would use TrainingPattern model
            # For now, just store as user preferences
            
            user = self.db.query(models.User).filter(models.User.id == self.user_id).first()
            if user:
                if not user.preferences:
                    user.preferences = {}
                
                user.preferences['bootstrap_patterns'] = {
                    'merchant_patterns': merchant_patterns,
                    'category_mappings': category_mappings,
                    'created_at': datetime.utcnow().isoformat(),
                    'pattern_count': len(merchant_patterns)
                }
                
                self.db.commit()
                
        except Exception as e:
            # Non-critical - patterns can still be used in memory
            pass
    
    def get_bootstrap_suggestions(self, beneficiary: str) -> Dict[str, Any]:
        """Get category suggestion based on bootstrap patterns."""
        
        try:
            # Get patterns from user preferences
            user = self.db.query(models.User).filter(models.User.id == self.user_id).first()
            if not user or not user.preferences or 'bootstrap_patterns' not in user.preferences:
                return {"category": None, "confidence": 0.0, "method": "no_bootstrap_data"}
            
            patterns = user.preferences['bootstrap_patterns']
            merchant_patterns = patterns.get('merchant_patterns', {})
            
            # Direct match
            beneficiary_key = beneficiary.lower().strip()
            if beneficiary_key in merchant_patterns:
                pattern = merchant_patterns[beneficiary_key]
                return {
                    "category": pattern["category"],
                    "confidence": pattern["confidence"],
                    "method": "bootstrap_exact_match",
                    "occurrences": pattern["occurrences"]
                }
            
            # Fuzzy match (if available)
            if FUZZY_AVAILABLE:
                best_match = None
                best_score = 0
                
                for merchant_key, pattern in merchant_patterns.items():
                    score = fuzz.ratio(beneficiary_key, merchant_key)
                    if score > best_score and score > 85:  # 85% similarity threshold
                        best_score = score
                        best_match = pattern
                
                if best_match:
                    return {
                        "category": best_match["category"],
                        "confidence": best_match["confidence"] * (best_score / 100.0),
                        "method": "bootstrap_fuzzy_match",
                        "similarity_score": best_score
                    }
            
            # Partial match
            for merchant_key, pattern in merchant_patterns.items():
                if (len(merchant_key) > 3 and merchant_key in beneficiary_key) or \
                   (len(beneficiary_key) > 3 and beneficiary_key in merchant_key):
                    return {
                        "category": pattern["category"],
                        "confidence": pattern["confidence"] * 0.7,  # Lower confidence for partial match
                        "method": "bootstrap_partial_match"
                    }
            
            return {"category": None, "confidence": 0.0, "method": "no_bootstrap_match"}
            
        except Exception as e:
            return {"category": None, "confidence": 0.0, "method": "bootstrap_error", "error": str(e)}
    
    def get_bootstrap_info(self) -> Dict[str, Any]:
        """Get information about bootstrap data availability."""
        
        try:
            user = self.db.query(models.User).filter(models.User.id == self.user_id).first()
            if not user or not user.preferences or 'bootstrap_patterns' not in user.preferences:
                return {
                    "bootstrap_available": False,
                    "pattern_count": 0,
                    "category_mappings": 0,
                    "created_at": None
                }
            
            patterns = user.preferences['bootstrap_patterns']
            
            return {
                "bootstrap_available": True,
                "pattern_count": patterns.get('pattern_count', 0),
                "category_mappings": len(patterns.get('category_mappings', {})),
                "merchant_patterns": len(patterns.get('merchant_patterns', {})),
                "created_at": patterns.get('created_at'),
                "hungarian_mappings_available": len(self.default_category_mapping),
                "fuzzy_matching": FUZZY_AVAILABLE,
                "pandas_available": PANDAS_AVAILABLE
            }
            
        except Exception as e:
            return {
                "bootstrap_available": False,
                "error": str(e)
            }