# backend/category_bootstrap.py
# Bootstrap categorization engine from existing categorized data

import io
import csv
import re
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Tuple, Any
from sqlalchemy.orm import Session
from collections import defaultdict

# For Excel processing
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

# For fuzzy matching
try:
    from fuzzywuzzy import fuzz
    FUZZY_AVAILABLE = True
except ImportError:
    FUZZY_AVAILABLE = False

from . import models

class CategoryBootstrap:
    """Bootstrap categorization rules from existing categorized data."""
    
    def __init__(self, user_id: int, db: Session):
        self.user_id = user_id
        self.db = db
        self.required_columns = ['date', 'beneficiary', 'amount', 'category']
        self.optional_columns = ['description', 'memo', 'notes']
        
    async def process_bootstrap_file(self, content: bytes, filename: str) -> Dict[str, Any]:
        """Process uploaded file and create categorization rules."""
        
        try:
            # Parse file
            file_type = '.' + filename.split('.')[-1].lower()
            
            if file_type == '.csv':
                raw_data = await self._process_csv_file(content)
            else:
                raw_data = await self._process_excel_file(content)
            
            if not raw_data:
                return {
                    "success": False,
                    "error": "No data found in file",
                    "rows_processed": 0
                }
            
            # Validate file structure
            validation_result = self._validate_bootstrap_file(raw_data)
            if not validation_result["valid"]:
                return {
                    "success": False,
                    "error": validation_result["error"],
                    "suggestions": validation_result.get("suggestions", []),
                    "columns_found": validation_result.get("columns_found", [])
                }
            
            # Normalize data
            normalized_data = []
            errors = []
            
            for i, row in enumerate(raw_data):
                try:
                    normalized_transaction = self._normalize_transaction(row, i + 1)
                    if normalized_transaction:
                        normalized_data.append(normalized_transaction)
                except Exception as e:
                    errors.append(f"Row {i + 1}: {str(e)}")
                    continue
            
            if not normalized_data:
                return {
                    "success": False,
                    "error": "No valid transactions found",
                    "errors": errors[:10]
                }
            
            # Analyze patterns and create rules
            analysis_result = await self._analyze_categorization_patterns(normalized_data)
            
            # Create categories and rules
            categories_created = await self._create_categories_from_data(normalized_data)
            rules_created = await self._create_categorization_rules(analysis_result)
            
            # Store training data for ML
            training_data_stored = await self._store_training_data(normalized_data)
            
            return {
                "success": True,
                "rows_processed": len(normalized_data),
                "errors": errors[:10] if errors else [],
                "categories_created": categories_created,
                "rules_created": rules_created,
                "training_data_stored": training_data_stored,
                "unique_categories": len(set(t['category'] for t in normalized_data)),
                "analysis": {
                    "keyword_patterns": len(analysis_result.get("keyword_patterns", {})),
                    "amount_patterns": len(analysis_result.get("amount_patterns", {})),
                    "beneficiary_patterns": len(analysis_result.get("beneficiary_patterns", {}))
                }
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": f"Processing failed: {str(e)}",
                "rows_processed": 0
            }
    
    async def _process_csv_file(self, content: bytes) -> List[Dict]:
        """Process CSV file with encoding detection."""
        import chardet
        
        # Detect encoding
        detected = chardet.detect(content)
        encoding = detected.get('encoding', 'utf-8')
        
        try:
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
                raise Exception("Could not decode file")
        
        # Parse CSV
        for delimiter in [',', ';', '\t', '|']:
            try:
                reader = csv.DictReader(io.StringIO(text_content), delimiter=delimiter)
                rows = list(reader)
                if len(rows) > 0 and len(rows[0]) > 1:
                    return rows
            except Exception:
                continue
        
        raise Exception("Could not parse CSV file")
    
    async def _process_excel_file(self, content: bytes) -> List[Dict]:
        """Process Excel file."""
        if not PANDAS_AVAILABLE:
            raise Exception("Pandas is required for Excel processing")
        
        try:
            # Read all sheets and find the best one
            excel_data = pd.read_excel(io.BytesIO(content), sheet_name=None)
            
            best_sheet = None
            max_rows = 0
            
            for sheet_name, df in excel_data.items():
                if len(df) > max_rows:
                    max_rows = len(df)
                    best_sheet = df
            
            if best_sheet is None or len(best_sheet) == 0:
                raise Exception("No data found in Excel file")
            
            return best_sheet.to_dict('records')
            
        except Exception as e:
            raise Exception(f"Excel processing failed: {str(e)}")
    
    def _validate_bootstrap_file(self, raw_data: List[Dict]) -> Dict[str, Any]:
        """Validate that the file has required columns for bootstrapping."""
        
        if not raw_data:
            return {"valid": False, "error": "No data found"}
        
        first_row = raw_data[0]
        columns = [col.lower().strip() for col in first_row.keys()]
        
        # Check for required columns
        missing_columns = []
        column_mapping = {}
        
        # Find date column
        date_patterns = ['date', 'transaction_date', 'datum', 'fecha']
        date_col = self._find_column_by_patterns(columns, date_patterns)
        if date_col:
            column_mapping['date'] = date_col
        else:
            missing_columns.append('date')
        
        # Find beneficiary/description column
        beneficiary_patterns = ['beneficiary', 'description', 'payee', 'merchant', 'vendor', 'name']
        beneficiary_col = self._find_column_by_patterns(columns, beneficiary_patterns)
        if beneficiary_col:
            column_mapping['beneficiary'] = beneficiary_col
        else:
            missing_columns.append('beneficiary')
        
        # Find amount column
        amount_patterns = ['amount', 'value', 'sum', 'total', 'bedrag']
        amount_col = self._find_column_by_patterns(columns, amount_patterns)
        if amount_col:
            column_mapping['amount'] = amount_col
        else:
            missing_columns.append('amount')
        
        # Find category column (most important for bootstrap)
        category_patterns = ['category', 'type', 'classification', 'tag', 'label']
        category_col = self._find_column_by_patterns(columns, category_patterns)
        if category_col:
            column_mapping['category'] = category_col
        else:
            missing_columns.append('category')
        
        if missing_columns:
            return {
                "valid": False,
                "error": f"Missing required columns: {', '.join(missing_columns)}",
                "columns_found": list(first_row.keys()),
                "suggestions": [
                    f"Ensure your file has columns for: {', '.join(self.required_columns)}",
                    "The category column is essential for bootstrap learning"
                ]
            }
        
        # Validate data quality in first few rows
        sample_size = min(5, len(raw_data))
        for i in range(sample_size):
            row = raw_data[i]
            
            # Check if category column has data
            category_value = None
            for col, value in row.items():
                if col.lower().strip() == column_mapping['category']:
                    category_value = value
                    break
            
            if not category_value or str(category_value).strip() == '':
                return {
                    "valid": False,
                    "error": f"Row {i + 2} has empty category - all rows must have categories for bootstrap",
                    "columns_found": list(first_row.keys())
                }
        
        return {
            "valid": True,
            "column_mapping": column_mapping,
            "estimated_rows": len(raw_data)
        }
    
    def _find_column_by_patterns(self, columns: List[str], patterns: List[str]) -> Optional[str]:
        """Find column that matches any of the patterns."""
        for pattern in patterns:
            for col in columns:
                if pattern in col or col in pattern:
                    return col
        return None
    
    def _normalize_transaction(self, row: Dict, row_num: int) -> Dict:
        """Normalize a transaction row for analysis."""
        normalized = {}
        
        # Find and parse date
        date_value = None
        for col, value in row.items():
            if any(pattern in col.lower() for pattern in ['date', 'datum', 'fecha']):
                date_value = self._parse_date(value)
                if date_value:
                    break
        
        if not date_value:
            raise Exception(f"Could not parse date from row {row_num}")
        
        normalized['transaction_date'] = date_value
        
        # Find beneficiary/description
        beneficiary = None
        for col, value in row.items():
            if any(pattern in col.lower() for pattern in ['beneficiary', 'description', 'payee', 'merchant']):
                beneficiary = str(value).strip() if value else None
                if beneficiary:
                    break
        
        if not beneficiary:
            raise Exception(f"Could not find beneficiary in row {row_num}")
        
        normalized['beneficiary'] = beneficiary
        
        # Find and parse amount
        amount = None
        for col, value in row.items():
            if any(pattern in col.lower() for pattern in ['amount', 'value', 'sum', 'total']):
                amount = self._parse_amount(value)
                if amount is not None:
                    break
        
        if amount is None:
            raise Exception(f"Could not parse amount from row {row_num}")
        
        normalized['amount'] = amount
        
        # Find category (required for bootstrap)
        category = None
        for col, value in row.items():
            if any(pattern in col.lower() for pattern in ['category', 'type', 'classification', 'tag']):
                category = str(value).strip() if value else None
                if category:
                    break
        
        if not category:
            raise Exception(f"Could not find category in row {row_num}")
        
        normalized['category'] = category
        
        # Optional: find description if different from beneficiary
        description = None
        for col, value in row.items():
            if 'description' in col.lower() or 'memo' in col.lower() or 'notes' in col.lower():
                desc_value = str(value).strip() if value else None
                if desc_value and desc_value != beneficiary:
                    description = desc_value
                    break
        
        if description:
            normalized['description'] = description
        
        return normalized
    
    def _parse_date(self, date_value) -> Optional[date]:
        """Parse date from various formats."""
        if not date_value:
            return None
        
        date_str = str(date_value).strip()
        
        # Common date formats
        date_formats = [
            "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y", 
            "%Y/%m/%d", "%d-%m-%Y", "%m-%d-%Y",
            "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"
        ]
        
        for fmt in date_formats:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        
        # Try pandas date parsing
        if PANDAS_AVAILABLE:
            try:
                return pd.to_datetime(date_str).date()
            except Exception:
                pass
        
        return None
    
    def _parse_amount(self, amount_value) -> Optional[Decimal]:
        """Parse amount from various formats."""
        if amount_value is None or amount_value == '':
            return None
        
        amount_str = str(amount_value).strip()
        
        # Remove currency symbols and formatting
        amount_clean = re.sub(r'[€$£¥₹,\s]', '', amount_str)
        
        # Handle parentheses for negative amounts
        if amount_clean.startswith('(') and amount_clean.endswith(')'):
            amount_clean = '-' + amount_clean[1:-1]
        
        try:
            return Decimal(amount_clean)
        except (InvalidOperation, ValueError):
            return None
    
    async def _analyze_categorization_patterns(self, transactions: List[Dict]) -> Dict[str, Any]:
        """Analyze transactions to find categorization patterns."""
        
        # Group transactions by category
        category_groups = defaultdict(list)
        for txn in transactions:
            category_groups[txn['category']].append(txn)
        
        analysis = {
            "keyword_patterns": {},
            "amount_patterns": {},
            "beneficiary_patterns": {},
            "category_stats": {}
        }
        
        for category, category_transactions in category_groups.items():
            
            # Analyze keywords in beneficiaries
            keywords = self._extract_keywords_from_beneficiaries(category_transactions)
            if keywords:
                analysis["keyword_patterns"][category] = keywords
            
            # Analyze amount patterns
            amounts = [float(txn['amount']) for txn in category_transactions]
            amount_stats = self._analyze_amount_patterns(amounts)
            if amount_stats:
                analysis["amount_patterns"][category] = amount_stats
            
            # Analyze beneficiary patterns
            beneficiaries = [txn['beneficiary'] for txn in category_transactions]
            beneficiary_patterns = self._extract_beneficiary_patterns(beneficiaries)
            if beneficiary_patterns:
                analysis["beneficiary_patterns"][category] = beneficiary_patterns
            
            # Category statistics
            analysis["category_stats"][category] = {
                "transaction_count": len(category_transactions),
                "total_amount": sum(amounts),
                "avg_amount": sum(amounts) / len(amounts),
                "unique_beneficiaries": len(set(beneficiaries))
            }
        
        return analysis
    
    def _extract_keywords_from_beneficiaries(self, transactions: List[Dict]) -> List[Dict]:
        """Extract common keywords from beneficiaries in a category."""
        
        # Collect all words from beneficiaries
        all_words = []
        for txn in transactions:
            beneficiary = txn['beneficiary'].lower()
            # Extract words (alphanumeric sequences)
            words = re.findall(r'\b\w+\b', beneficiary)
            all_words.extend(words)
        
        # Count word frequency
        word_counts = defaultdict(int)
        for word in all_words:
            if len(word) > 2:  # Ignore very short words
                word_counts[word] += 1
        
        # Find words that appear in multiple transactions
        total_transactions = len(transactions)
        significant_words = []
        
        for word, count in word_counts.items():
            frequency = count / total_transactions
            if frequency >= 0.3 and count >= 2:  # Word appears in at least 30% of transactions
                significant_words.append({
                    "keyword": word,
                    "frequency": frequency,
                    "count": count,
                    "confidence": min(0.9, frequency * 1.2)  # Cap at 0.9
                })
        
        # Sort by frequency
        return sorted(significant_words, key=lambda x: x['frequency'], reverse=True)[:10]
    
    def _analyze_amount_patterns(self, amounts: List[float]) -> Optional[Dict]:
        """Analyze amount patterns for a category."""
        
        if len(amounts) < 3:  # Need at least 3 transactions
            return None
        
        amounts.sort()
        
        # Check for recurring amounts (exact matches)
        amount_counts = defaultdict(int)
        for amount in amounts:
            amount_counts[amount] += 1
        
        recurring_amounts = [
            {"amount": amount, "count": count, "frequency": count / len(amounts)}
            for amount, count in amount_counts.items()
            if count >= 2 and count / len(amounts) >= 0.3
        ]
        
        if recurring_amounts:
            return {
                "type": "recurring",
                "patterns": sorted(recurring_amounts, key=lambda x: x['frequency'], reverse=True)[:5]
            }
        
        # Check for amount ranges
        min_amount = min(amounts)
        max_amount = max(amounts)
        avg_amount = sum(amounts) / len(amounts)
        
        # If amounts are in a tight range, create a range pattern
        amount_range = max_amount - min_amount
        if amount_range > 0 and amount_range / avg_amount <= 0.5:  # Range is within 50% of average
            return {
                "type": "range",
                "min_amount": min_amount,
                "max_amount": max_amount,
                "avg_amount": avg_amount,
                "confidence": 0.7
            }
        
        return None
    
    def _extract_beneficiary_patterns(self, beneficiaries: List[str]) -> List[Dict]:
        """Extract patterns from beneficiaries."""
        
        patterns = []
        
        # Find exact matches (case-insensitive)
        beneficiary_counts = defaultdict(int)
        for beneficiary in beneficiaries:
            beneficiary_counts[beneficiary.lower()] += 1
        
        total_beneficiaries = len(beneficiaries)
        
        for beneficiary, count in beneficiary_counts.items():
            frequency = count / total_beneficiaries
            if count >= 2 and frequency >= 0.3:  # Appears multiple times
                patterns.append({
                    "pattern": beneficiary,
                    "type": "exact_match",
                    "frequency": frequency,
                    "count": count,
                    "confidence": min(0.95, frequency * 1.1)
                })
        
        # Find partial patterns (common substrings)
        if FUZZY_AVAILABLE and len(beneficiaries) >= 5:
            # Group similar beneficiaries
            similar_groups = self._find_similar_beneficiaries(beneficiaries)
            
            for group in similar_groups:
                if len(group) >= 3:  # At least 3 similar beneficiaries
                    common_part = self._find_common_substring(group)
                    if common_part and len(common_part) >= 3:
                        patterns.append({
                            "pattern": common_part,
                            "type": "partial_match",
                            "frequency": len(group) / total_beneficiaries,
                            "count": len(group),
                            "confidence": 0.8,
                            "examples": group[:3]
                        })
        
        return sorted(patterns, key=lambda x: x['confidence'], reverse=True)[:5]
    
    def _find_similar_beneficiaries(self, beneficiaries: List[str]) -> List[List[str]]:
        """Group similar beneficiaries using fuzzy matching."""
        
        groups = []
        processed = set()
        
        for i, beneficiary1 in enumerate(beneficiaries):
            if beneficiary1 in processed:
                continue
            
            group = [beneficiary1]
            processed.add(beneficiary1)
            
            for j, beneficiary2 in enumerate(beneficiaries[i+1:], i+1):
                if beneficiary2 in processed:
                    continue
                
                similarity = fuzz.ratio(beneficiary1.lower(), beneficiary2.lower())
                if similarity >= 70:  # 70% similarity
                    group.append(beneficiary2)
                    processed.add(beneficiary2)
            
            if len(group) > 1:
                groups.append(group)
        
        return groups
    
    def _find_common_substring(self, strings: List[str]) -> str:
        """Find the longest common substring among a list of strings."""
        
        if not strings:
            return ""
        
        # Find the longest common substring
        first = strings[0].lower()
        common = ""
        
        for i in range(len(first)):
            for j in range(i + 3, len(first) + 1):  # Minimum 3 characters
                substring = first[i:j]
                if all(substring in s.lower() for s in strings[1:]):
                    if len(substring) > len(common):
                        common = substring
        
        return common.strip()
    
    async def _create_categories_from_data(self, transactions: List[Dict]) -> int:
        """Create categories from the bootstrap data if they don't exist."""
        
        unique_categories = set(txn['category'] for txn in transactions)
        created_count = 0
        
        for category_name in unique_categories:
            # Check if category already exists
            existing = self.db.query(models.Category).filter(
                models.Category.user_id == self.user_id,
                models.Category.name == category_name,
                models.Category.is_active == True
            ).first()
            
            if not existing:
                # Create new category
                new_category = models.Category(
                    name=category_name,
                    color=self._generate_category_color(category_name),
                    icon=self._suggest_category_icon(category_name),
                    user_id=self.user_id,
                    confidence_score=0.8  # Bootstrap categories get good confidence
                )
                
                self.db.add(new_category)
                created_count += 1
        
        self.db.commit()
        return created_count
    
    async def _create_categorization_rules(self, analysis: Dict[str, Any]) -> int:
        """Create categorization rules from the pattern analysis."""
        
        rules_created = 0
        
        # Create keyword rules
        for category_name, keywords in analysis.get("keyword_patterns", {}).items():
            category = self.db.query(models.Category).filter(
                models.Category.user_id == self.user_id,
                models.Category.name == category_name,
                models.Category.is_active == True
            ).first()
            
            if category:
                for keyword_data in keywords[:5]:  # Top 5 keywords
                    rule = models.CategorizationRule(
                        rule_type="keyword",
                        pattern={
                            "keywords": [keyword_data["keyword"]],
                            "exact_match": False
                        },
                        confidence=keyword_data["confidence"],
                        success_count=keyword_data["count"],
                        category_id=category.id,
                        user_id=self.user_id
                    )
                    self.db.add(rule)
                    rules_created += 1
        
        # Create amount pattern rules
        for category_name, amount_pattern in analysis.get("amount_patterns", {}).items():
            category = self.db.query(models.Category).filter(
                models.Category.user_id == self.user_id,
                models.Category.name == category_name,
                models.Category.is_active == True
            ).first()
            
            if category:
                if amount_pattern["type"] == "range":
                    rule = models.CategorizationRule(
                        rule_type="amount_range",
                        pattern={
                            "min_amount": amount_pattern["min_amount"],
                            "max_amount": amount_pattern["max_amount"]
                        },
                        confidence=amount_pattern["confidence"],
                        success_count=1,
                        category_id=category.id,
                        user_id=self.user_id
                    )
                    self.db.add(rule)
                    rules_created += 1
                elif amount_pattern["type"] == "recurring":
                    for pattern in amount_pattern["patterns"][:3]:  # Top 3 recurring amounts
                        rule = models.CategorizationRule(
                            rule_type="exact_amount",
                            pattern={
                                "amount": pattern["amount"],
                                "tolerance": 0.01
                            },
                            confidence=pattern["frequency"],
                            success_count=pattern["count"],
                            category_id=category.id,
                            user_id=self.user_id
                        )
                        self.db.add(rule)
                        rules_created += 1
        
        # Create beneficiary pattern rules
        for category_name, beneficiary_patterns in analysis.get("beneficiary_patterns", {}).items():
            category = self.db.query(models.Category).filter(
                models.Category.user_id == self.user_id,
                models.Category.name == category_name,
                models.Category.is_active == True
            ).first()
            
            if category:
                for pattern in beneficiary_patterns[:3]:  # Top 3 patterns
                    rule = models.CategorizationRule(
                        rule_type="beneficiary_pattern",
                        pattern={
                            "pattern": pattern["pattern"],
                            "match_type": pattern["type"]
                        },
                        confidence=pattern["confidence"],
                        success_count=pattern["count"],
                        category_id=category.id,
                        user_id=self.user_id
                    )
                    self.db.add(rule)
                    rules_created += 1
        
        self.db.commit()
        return rules_created
    
    async def _store_training_data(self, transactions: List[Dict]) -> int:
        """Store transactions as ML training data."""
        
        stored_count = 0
        
        for txn in transactions:
            # Create ML training data entry
            training_data = models.MLTrainingData(
                beneficiary=txn['beneficiary'],
                amount=txn['amount'],
                category=txn['category'],
                user_corrected=False,  # This is bootstrap data, not user corrections
                features={
                    "beneficiary_words": re.findall(r'\w+', txn['beneficiary'].lower()),
                    "amount_range": self._get_amount_range(float(txn['amount'])),
                    "description": txn.get('description', ''),
                    "date": txn['transaction_date'].isoformat()
                },
                user_id=self.user_id
            )
            
            self.db.add(training_data)
            stored_count += 1
        
        self.db.commit()
        return stored_count
    
    def _generate_category_color(self, category_name: str) -> str:
        """Generate a color for a category based on its name."""
        
        color_map = {
            'food': '#ef4444', 'restaurant': '#ef4444', 'grocery': '#ef4444', 'dining': '#ef4444',
            'transport': '#f97316', 'gas': '#f97316', 'fuel': '#f97316', 'taxi': '#f97316', 'uber': '#f97316',
            'entertainment': '#8b5cf6', 'movie': '#8b5cf6', 'netflix': '#8b5cf6', 'spotify': '#8b5cf6',
            'shopping': '#06b6d4', 'amazon': '#06b6d4', 'clothes': '#06b6d4', 'retail': '#06b6d4',
            'bills': '#dc2626', 'utilities': '#dc2626', 'electric': '#dc2626', 'water': '#dc2626',
            'health': '#16a34a', 'medical': '#16a34a', 'doctor': '#16a34a', 'pharmacy': '#16a34a',
            'income': '#22c55e', 'salary': '#22c55e', 'deposit': '#22c55e', 'refund': '#22c55e',
            'transfer': '#6b7280', 'atm': '#6b7280', 'withdrawal': '#6b7280'
        }
        
        category_lower = category_name.lower()
        
        for keyword, color in color_map.items():
            if keyword in category_lower:
                return color
        
        # Default color
        return '#6366f1'
    
    def _suggest_category_icon(self, category_name: str) -> str:
        """Suggest an icon for a category based on its name."""
        
        icon_map = {
            'food': '🍽️', 'restaurant': '🍽️', 'grocery': '🛒', 'dining': '🍽️',
            'transport': '🚗', 'gas': '⛽', 'fuel': '⛽', 'taxi': '🚕', 'uber': '🚕',
            'entertainment': '🎬', 'movie': '🎬', 'netflix': '📺', 'spotify': '🎵',
            'shopping': '🛍️', 'amazon': '📦', 'clothes': '👕', 'retail': '🏪',
            'bills': '⚡', 'utilities': '⚡', 'electric': '💡', 'water': '💧',
            'health': '🏥', 'medical': '🏥', 'doctor': '👨‍⚕️', 'pharmacy': '💊',
            'income': '💰', 'salary': '💰', 'deposit': '💰', 'refund': '💰',
            'transfer': '🔄', 'atm': '🏧', 'withdrawal': '🏧'
        }
        
        category_lower = category_name.lower()
        
        for keyword, icon in icon_map.items():
            if keyword in category_lower:
                return icon
        
        # Default icon
        return '📝'
    
    def _get_amount_range(self, amount: float) -> str:
        """Categorize amount into ranges for ML features."""
        
        abs_amount = abs(amount)
        
        if abs_amount < 10:
            return "micro"
        elif abs_amount < 50:
            return "small"
        elif abs_amount < 200:
            return "medium"
        elif abs_amount < 1000:
            return "large"
        else:
            return "very_large"