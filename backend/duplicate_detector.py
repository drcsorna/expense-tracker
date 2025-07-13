# backend/duplicate_detector.py
# Minimal duplicate detection implementation

import re
from typing import Dict, List, Optional, Tuple, Any
from sqlalchemy.orm import Session
from datetime import datetime, date, timedelta
from decimal import Decimal
from collections import defaultdict

# Fuzzy matching imports with fallback
try:
    from fuzzywuzzy import fuzz
    FUZZY_AVAILABLE = True
except ImportError:
    FUZZY_AVAILABLE = False

from . import models

class DuplicateDetector:
    """Advanced duplicate transaction detection engine (minimal implementation)."""
    
    def __init__(self, user_id: int, db: Session):
        self.user_id = user_id
        self.db = db
        self.detection_methods = [
            "exact_match",
            "amount_date_match", 
            "fuzzy_beneficiary_match",
            "similar_transactions"
        ]
        self.similarity_threshold = 0.85
        self.date_tolerance_days = 2
        
    async def find_all_duplicates(self) -> List[Dict[str, Any]]:
        """Find all duplicate transactions using multiple detection methods."""
        
        try:
            # Get all transactions for the user
            transactions = self.db.query(models.Transaction).filter(
                models.Transaction.owner_id == self.user_id
            ).order_by(models.Transaction.transaction_date.desc()).all()
            
            if len(transactions) < 2:
                return []
            
            all_duplicate_groups = []
            processed_transactions = set()
            
            # Method 1: Exact matches
            exact_groups = self._find_exact_duplicates(transactions, processed_transactions)
            all_duplicate_groups.extend(exact_groups)
            
            # Method 2: Amount + Date matches
            amount_date_groups = self._find_amount_date_duplicates(transactions, processed_transactions)
            all_duplicate_groups.extend(amount_date_groups)
            
            # Method 3: Fuzzy beneficiary matches (if fuzzy matching available)
            if FUZZY_AVAILABLE:
                fuzzy_groups = self._find_fuzzy_duplicates(transactions, processed_transactions)
                all_duplicate_groups.extend(fuzzy_groups)
            
            # Create duplicate groups in database (simplified)
            created_groups = []
            for group_data in all_duplicate_groups:
                try:
                    # Create or find duplicate group
                    duplicate_group = models.DuplicateGroup(
                        detection_method=group_data["method"],
                        confidence_score=group_data["confidence"],
                        user_id=self.user_id,
                        status=models.DuplicateStatus.PENDING
                    )
                    
                    self.db.add(duplicate_group)
                    self.db.flush()  # Get ID without committing
                    
                    # Add entries
                    entries = []
                    for i, transaction_id in enumerate(group_data["transaction_ids"]):
                        entry = models.DuplicateEntry(
                            group_id=duplicate_group.id,
                            transaction_id=transaction_id,
                            is_primary=(i == 0),  # First one is primary
                            confidence_score=group_data["confidence"]
                        )
                        entries.append(entry)
                        self.db.add(entry)
                    
                    created_groups.append({
                        "id": duplicate_group.id,
                        "method": group_data["method"],
                        "confidence": group_data["confidence"],
                        "transaction_count": len(group_data["transaction_ids"]),
                        "transactions": group_data["transaction_ids"]
                    })
                    
                except Exception as e:
                    # Skip this group if there's an error
                    continue
            
            self.db.commit()
            return created_groups
            
        except Exception as e:
            return [{
                "error": f"Duplicate detection failed: {str(e)}",
                "method": "error",
                "transaction_count": 0
            }]
    
    def _find_exact_duplicates(self, transactions: List, processed: set) -> List[Dict[str, Any]]:
        """Find transactions with identical beneficiary, amount, and date."""
        
        groups = []
        transaction_map = defaultdict(list)
        
        # Group by exact match criteria
        for transaction in transactions:
            if transaction.id in processed:
                continue
                
            key = (
                transaction.beneficiary.strip().lower(),
                float(transaction.amount),
                transaction.transaction_date
            )
            transaction_map[key].append(transaction)
        
        # Find groups with more than one transaction
        for key, group in transaction_map.items():
            if len(group) > 1:
                transaction_ids = [t.id for t in group]
                processed.update(transaction_ids)
                
                groups.append({
                    "method": "exact_match",
                    "confidence": 1.0,
                    "transaction_ids": transaction_ids,
                    "match_criteria": {
                        "beneficiary": key[0],
                        "amount": key[1],
                        "date": key[2].isoformat()
                    }
                })
        
        return groups
    
    def _find_amount_date_duplicates(self, transactions: List, processed: set) -> List[Dict[str, Any]]:
        """Find transactions with same amount within date tolerance."""
        
        groups = []
        
        for i, transaction1 in enumerate(transactions):
            if transaction1.id in processed:
                continue
                
            similar_transactions = [transaction1]
            
            for j, transaction2 in enumerate(transactions[i+1:], i+1):
                if transaction2.id in processed:
                    continue
                
                # Check amount match
                if abs(float(transaction1.amount) - float(transaction2.amount)) < 0.01:
                    # Check date tolerance
                    date_diff = abs((transaction1.transaction_date - transaction2.transaction_date).days)
                    
                    if date_diff <= self.date_tolerance_days:
                        # Check beneficiary similarity (basic)
                        beneficiary_sim = self._simple_string_similarity(
                            transaction1.beneficiary, 
                            transaction2.beneficiary
                        )
                        
                        if beneficiary_sim > 0.6:  # 60% similarity threshold
                            similar_transactions.append(transaction2)
            
            if len(similar_transactions) > 1:
                transaction_ids = [t.id for t in similar_transactions]
                processed.update(transaction_ids)
                
                groups.append({
                    "method": "amount_date_match",
                    "confidence": 0.8,
                    "transaction_ids": transaction_ids,
                    "match_criteria": {
                        "amount": float(transaction1.amount),
                        "date_tolerance": self.date_tolerance_days
                    }
                })
        
        return groups
    
    def _find_fuzzy_duplicates(self, transactions: List, processed: set) -> List[Dict[str, Any]]:
        """Find transactions using fuzzy string matching."""
        
        if not FUZZY_AVAILABLE:
            return []
        
        groups = []
        
        for i, transaction1 in enumerate(transactions):
            if transaction1.id in processed:
                continue
                
            similar_transactions = [transaction1]
            
            for j, transaction2 in enumerate(transactions[i+1:], i+1):
                if transaction2.id in processed:
                    continue
                
                # Fuzzy match beneficiary
                beneficiary_ratio = fuzz.ratio(
                    transaction1.beneficiary.lower(),
                    transaction2.beneficiary.lower()
                )
                
                # Check if similar beneficiary and similar amount
                amount_diff = abs(float(transaction1.amount) - float(transaction2.amount))
                amount_ratio = min(float(transaction1.amount), float(transaction2.amount)) / max(float(transaction1.amount), float(transaction2.amount))
                
                if (beneficiary_ratio > 85 and  # High beneficiary similarity
                    amount_ratio > 0.9 and     # Similar amounts (within 10%)
                    amount_diff < 50):         # Not too different in absolute terms
                    
                    # Check date proximity
                    date_diff = abs((transaction1.transaction_date - transaction2.transaction_date).days)
                    if date_diff <= 7:  # Within a week
                        similar_transactions.append(transaction2)
            
            if len(similar_transactions) > 1:
                transaction_ids = [t.id for t in similar_transactions]
                processed.update(transaction_ids)
                
                confidence = min(0.9, beneficiary_ratio / 100.0)
                
                groups.append({
                    "method": "fuzzy_beneficiary_match",
                    "confidence": confidence,
                    "transaction_ids": transaction_ids,
                    "match_criteria": {
                        "beneficiary_similarity": beneficiary_ratio,
                        "amount_ratio": amount_ratio
                    }
                })
        
        return groups
    
    def _simple_string_similarity(self, str1: str, str2: str) -> float:
        """Simple string similarity calculation (fallback when fuzzy not available)."""
        
        str1 = str1.lower().strip()
        str2 = str2.lower().strip()
        
        if str1 == str2:
            return 1.0
        
        # Simple word overlap
        words1 = set(re.findall(r'\b\w+\b', str1))
        words2 = set(re.findall(r'\b\w+\b', str2))
        
        if not words1 or not words2:
            return 0.0
        
        intersection = words1 & words2
        union = words1 | words2
        
        return len(intersection) / len(union) if union else 0.0
    
    async def get_duplicate_groups(self, status_filter=None) -> List[Dict[str, Any]]:
        """Get existing duplicate groups."""
        
        try:
            query = self.db.query(models.DuplicateGroup).filter(
                models.DuplicateGroup.user_id == self.user_id
            )
            
            if status_filter:
                query = query.filter(models.DuplicateGroup.status == status_filter)
            
            groups = query.all()
            
            result = []
            for group in groups:
                entries = self.db.query(models.DuplicateEntry).filter(
                    models.DuplicateEntry.group_id == group.id
                ).all()
                
                result.append({
                    "id": group.id,
                    "method": group.detection_method,
                    "confidence": float(group.confidence_score),
                    "status": group.status.value if hasattr(group.status, 'value') else str(group.status),
                    "transaction_count": len(entries),
                    "created_at": group.created_at.isoformat(),
                    "transactions": [entry.transaction_id for entry in entries]
                })
            
            return result
            
        except Exception as e:
            return [{
                "error": f"Failed to get duplicate groups: {str(e)}",
                "groups": []
            }]
    
    def get_detection_info(self) -> Dict[str, Any]:
        """Get information about the duplicate detection system."""
        
        return {
            "fuzzy_available": FUZZY_AVAILABLE,
            "detection_methods": self.detection_methods,
            "similarity_threshold": self.similarity_threshold,
            "date_tolerance_days": self.date_tolerance_days,
            "status": "minimal_implementation",
            "recommendations": [
                "Install fuzzywuzzy for better fuzzy matching" if not FUZZY_AVAILABLE else "Fuzzy matching available"
            ]
        }