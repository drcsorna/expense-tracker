# backend/duplicate_detector.py
# Advanced duplicate detection with multiple criteria and similarity scoring

import hashlib
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple, Any
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_

# Fuzzy matching for beneficiary comparison
try:
    from fuzzywuzzy import fuzz
    FUZZY_AVAILABLE = True
except ImportError:
    FUZZY_AVAILABLE = False

from . import models

class DuplicateDetector:
    """Advanced duplicate detection system with multiple detection methods."""
    
    def __init__(self, user_id: int, db: Session):
        self.user_id = user_id
        self.db = db
        
        # Load user preferences for duplicate detection
        user = db.query(models.User).filter(models.User.id == user_id).first()
        self.preferences = {
            "amount_tolerance": 0.01,
            "date_range_days": 3,
            "beneficiary_similarity_threshold": 0.8
        }
        
        if user and user.preferences:
            dup_prefs = user.preferences.get('duplicate_detection', {})
            self.preferences.update(dup_prefs)
    
    async def check_duplicate(self, transaction: Dict) -> bool:
        """Check if transaction is a duplicate using multiple methods."""
        
        # Method 1: Exact hash match (fastest)
        if await self._check_hash_duplicate(transaction):
            return True
        
        # Method 2: Similar transaction detection
        if await self._check_similar_duplicate(transaction):
            return True
        
        # Method 3: Fuzzy matching for beneficiary variations
        if FUZZY_AVAILABLE and await self._check_fuzzy_duplicate(transaction):
            return True
        
        return False
    
    async def find_all_duplicates(self) -> List[Dict[str, Any]]:
        """Find all potential duplicate groups for the user."""
        
        duplicate_groups = []
        
        # Find hash-based duplicates
        hash_groups = await self._find_hash_duplicates()
        duplicate_groups.extend(hash_groups)
        
        # Find similarity-based duplicates
        similarity_groups = await self._find_similarity_duplicates()
        duplicate_groups.extend(similarity_groups)
        
        # Find fuzzy beneficiary duplicates
        if FUZZY_AVAILABLE:
            fuzzy_groups = await self._find_fuzzy_duplicates()
            duplicate_groups.extend(fuzzy_groups)
        
        return duplicate_groups
    
    async def create_duplicate_group(self, transactions: List[models.Transaction], detection_method: str, similarity_score: float) -> models.DuplicateGroup:
        """Create a new duplicate group with given transactions."""
        
        # Create the group
        group = models.DuplicateGroup(
            similarity_score=similarity_score,
            detection_method=detection_method,
            status=models.DuplicateStatus.PENDING,
            user_id=self.user_id,
            created_at=datetime.utcnow()
        )
        
        self.db.add(group)
        self.db.flush()  # Get the ID
        
        # Add entries to the group
        for i, transaction in enumerate(transactions):
            entry = models.DuplicateEntry(
                group_id=group.id,
                transaction_id=transaction.id,
                is_primary=(i == 0),  # First transaction is primary by default
                similarity_details=self._calculate_similarity_details(transactions[0], transaction)
            )
            self.db.add(entry)
        
        self.db.commit()
        return group
    
    async def resolve_duplicate_group(self, group_id: int, resolution: str, keep_transaction_id: Optional[int] = None) -> Dict[str, Any]:
        """Resolve a duplicate group by merging, deleting, or ignoring."""
        
        group = self.db.query(models.DuplicateGroup).filter(
            models.DuplicateGroup.id == group_id,
            models.DuplicateGroup.user_id == self.user_id
        ).first()
        
        if not group:
            raise ValueError("Duplicate group not found")
        
        entries = self.db.query(models.DuplicateEntry).filter(
            models.DuplicateEntry.group_id == group_id
        ).all()
        
        result = {"action": resolution, "affected_transactions": len(entries)}
        
        if resolution == "merge":
            # Keep one transaction, delete others
            keep_entry = None
            if keep_transaction_id:
                keep_entry = next((e for e in entries if e.transaction_id == keep_transaction_id), None)
            
            if not keep_entry:
                keep_entry = entries[0]  # Keep first by default
            
            # Delete other transactions
            deleted_count = 0
            for entry in entries:
                if entry.id != keep_entry.id:
                    transaction = self.db.query(models.Transaction).filter(
                        models.Transaction.id == entry.transaction_id
                    ).first()
                    if transaction:
                        self.db.delete(transaction)
                        deleted_count += 1
            
            result["kept_transaction_id"] = keep_entry.transaction_id
            result["deleted_count"] = deleted_count
            group.status = models.DuplicateStatus.RESOLVED
            
        elif resolution == "ignore":
            # Mark as not duplicates
            group.status = models.DuplicateStatus.IGNORED
            result["message"] = "Marked as not duplicates"
            
        elif resolution == "delete_all":
            # Delete all transactions in the group
            deleted_count = 0
            for entry in entries:
                transaction = self.db.query(models.Transaction).filter(
                    models.Transaction.id == entry.transaction_id
                ).first()
                if transaction:
                    self.db.delete(transaction)
                    deleted_count += 1
            
            result["deleted_count"] = deleted_count
            group.status = models.DuplicateStatus.RESOLVED
        
        group.resolved_at = datetime.utcnow()
        self.db.commit()
        
        return result
    
    async def get_duplicate_groups(self, status: Optional[models.DuplicateStatus] = None) -> List[Dict[str, Any]]:
        """Get duplicate groups for the user with full details."""
        
        query = self.db.query(models.DuplicateGroup).filter(
            models.DuplicateGroup.user_id == self.user_id
        )
        
        if status:
            query = query.filter(models.DuplicateGroup.status == status)
        
        groups = query.order_by(models.DuplicateGroup.created_at.desc()).all()
        
        result = []
        for group in groups:
            entries = self.db.query(models.DuplicateEntry).filter(
                models.DuplicateEntry.group_id == group.id
            ).all()
            
            transactions = []
            for entry in entries:
                transaction = self.db.query(models.Transaction).filter(
                    models.Transaction.id == entry.transaction_id
                ).first()
                
                if transaction:
                    transactions.append({
                        "id": transaction.id,
                        "date": transaction.transaction_date.isoformat(),
                        "beneficiary": transaction.beneficiary,
                        "amount": float(transaction.amount),
                        "category": transaction.category,
                        "is_primary": entry.is_primary,
                        "similarity_details": entry.similarity_details
                    })
            
            result.append({
                "id": group.id,
                "similarity_score": group.similarity_score,
                "detection_method": group.detection_method,
                "status": group.status.value,
                "created_at": group.created_at.isoformat(),
                "resolved_at": group.resolved_at.isoformat() if group.resolved_at else None,
                "transaction_count": len(transactions),
                "transactions": transactions
            })
        
        return result
    
    async def update_detection_preferences(self, preferences: Dict[str, Any]) -> Dict[str, Any]:
        """Update user's duplicate detection preferences."""
        
        user = self.db.query(models.User).filter(models.User.id == self.user_id).first()
        if not user:
            raise ValueError("User not found")
        
        current_prefs = user.preferences or {}
        dup_prefs = current_prefs.get('duplicate_detection', {})
        
        # Update with new preferences
        dup_prefs.update(preferences)
        current_prefs['duplicate_detection'] = dup_prefs
        
        user.preferences = current_prefs
        self.db.commit()
        
        # Update local preferences
        self.preferences.update(preferences)
        
        return self.preferences
    
    # Private methods
    
    async def _check_hash_duplicate(self, transaction: Dict) -> bool:
        """Check for exact hash duplicates."""
        file_hash = transaction.get('file_hash')
        if not file_hash:
            return False
        
        # Check in existing transactions
        existing = self.db.query(models.Transaction).filter(
            models.Transaction.owner_id == self.user_id,
            models.Transaction.file_hash == file_hash
        ).first()
        
        if existing:
            return True
        
        # Check in staged transactions
        staged = self.db.query(models.StagedTransaction).filter(
            models.StagedTransaction.owner_id == self.user_id,
            models.StagedTransaction.file_hash == file_hash
        ).first()
        
        return staged is not None
    
    async def _check_similar_duplicate(self, transaction: Dict) -> bool:
        """Check for similar transactions based on amount, date, and beneficiary."""
        
        txn_date = transaction.get('transaction_date')
        txn_amount = Decimal(str(transaction.get('amount', 0)))
        txn_beneficiary = transaction.get('beneficiary', '').lower().strip()
        
        if not txn_date or not txn_beneficiary:
            return False
        
        # Date range
        date_range = timedelta(days=self.preferences['date_range_days'])
        start_date = txn_date - date_range
        end_date = txn_date + date_range
        
        # Amount tolerance
        amount_tolerance = Decimal(str(self.preferences['amount_tolerance']))
        min_amount = txn_amount - amount_tolerance
        max_amount = txn_amount + amount_tolerance
        
        # Check existing transactions
        similar_transactions = self.db.query(models.Transaction).filter(
            models.Transaction.owner_id == self.user_id,
            models.Transaction.transaction_date >= start_date,
            models.Transaction.transaction_date <= end_date,
            models.Transaction.amount >= min_amount,
            models.Transaction.amount <= max_amount,
            func.lower(models.Transaction.beneficiary) == txn_beneficiary
        ).all()
        
        if similar_transactions:
            return True
        
        # Check staged transactions
        similar_staged = self.db.query(models.StagedTransaction).filter(
            models.StagedTransaction.owner_id == self.user_id,
            models.StagedTransaction.transaction_date >= start_date,
            models.StagedTransaction.transaction_date <= end_date,
            models.StagedTransaction.amount >= min_amount,
            models.StagedTransaction.amount <= max_amount,
            func.lower(models.StagedTransaction.beneficiary) == txn_beneficiary
        ).all()
        
        return len(similar_staged) > 0
    
    async def _check_fuzzy_duplicate(self, transaction: Dict) -> bool:
        """Check for duplicates using fuzzy string matching."""
        if not FUZZY_AVAILABLE:
            return False
        
        txn_date = transaction.get('transaction_date')
        txn_amount = Decimal(str(transaction.get('amount', 0)))
        txn_beneficiary = transaction.get('beneficiary', '').strip()
        
        if not txn_date or not txn_beneficiary:
            return False
        
        # Date and amount ranges
        date_range = timedelta(days=self.preferences['date_range_days'])
        start_date = txn_date - date_range
        end_date = txn_date + date_range
        
        amount_tolerance = Decimal(str(self.preferences['amount_tolerance']))
        min_amount = txn_amount - amount_tolerance
        max_amount = txn_amount + amount_tolerance
        
        # Get candidates within date and amount range
        candidates = self.db.query(models.Transaction).filter(
            models.Transaction.owner_id == self.user_id,
            models.Transaction.transaction_date >= start_date,
            models.Transaction.transaction_date <= end_date,
            models.Transaction.amount >= min_amount,
            models.Transaction.amount <= max_amount
        ).all()
        
        # Check fuzzy similarity
        similarity_threshold = self.preferences['beneficiary_similarity_threshold'] * 100
        
        for candidate in candidates:
            similarity = fuzz.ratio(txn_beneficiary.lower(), candidate.beneficiary.lower())
            if similarity >= similarity_threshold:
                return True
        
        return False
    
    async def _find_hash_duplicates(self) -> List[Dict[str, Any]]:
        """Find groups of transactions with identical hashes."""
        
        # Query for hash duplicates
        hash_duplicates = self.db.query(
            models.Transaction.file_hash,
            func.count(models.Transaction.id).label('count')
        ).filter(
            models.Transaction.owner_id == self.user_id,
            models.Transaction.file_hash.isnot(None)
        ).group_by(
            models.Transaction.file_hash
        ).having(func.count(models.Transaction.id) > 1).all()
        
        groups = []
        for hash_dup in hash_duplicates:
            transactions = self.db.query(models.Transaction).filter(
                models.Transaction.owner_id == self.user_id,
                models.Transaction.file_hash == hash_dup.file_hash
            ).all()
            
            if len(transactions) > 1:
                # Check if group already exists
                existing_group = self._find_existing_group(transactions)
                if not existing_group:
                    group = await self.create_duplicate_group(
                        transactions, "hash_match", 1.0
                    )
                    groups.append(self._format_duplicate_group(group, transactions))
        
        return groups
    
    async def _find_similarity_duplicates(self) -> List[Dict[str, Any]]:
        """Find groups of similar transactions."""
        
        # Get all transactions for comparison
        transactions = self.db.query(models.Transaction).filter(
            models.Transaction.owner_id == self.user_id
        ).order_by(models.Transaction.transaction_date.desc()).limit(1000).all()
        
        groups = []
        processed_ids = set()
        
        for i, txn1 in enumerate(transactions):
            if txn1.id in processed_ids:
                continue
            
            similar_transactions = [txn1]
            processed_ids.add(txn1.id)
            
            for j, txn2 in enumerate(transactions[i+1:], i+1):
                if txn2.id in processed_ids:
                    continue
                
                similarity_score = self._calculate_similarity_score(txn1, txn2)
                if similarity_score >= 0.8:  # 80% similarity threshold
                    similar_transactions.append(txn2)
                    processed_ids.add(txn2.id)
            
            if len(similar_transactions) > 1:
                # Check if group already exists
                existing_group = self._find_existing_group(similar_transactions)
                if not existing_group:
                    avg_similarity = sum(
                        self._calculate_similarity_score(similar_transactions[0], t)
                        for t in similar_transactions[1:]
                    ) / (len(similar_transactions) - 1)
                    
                    group = await self.create_duplicate_group(
                        similar_transactions, "similarity_match", avg_similarity
                    )
                    groups.append(self._format_duplicate_group(group, similar_transactions))
        
        return groups
    
    async def _find_fuzzy_duplicates(self) -> List[Dict[str, Any]]:
        """Find duplicates using fuzzy string matching."""
        if not FUZZY_AVAILABLE:
            return []
        
        # This would implement fuzzy duplicate detection
        # Similar to similarity duplicates but using fuzzy string matching
        return []
    
    def _calculate_similarity_score(self, txn1: models.Transaction, txn2: models.Transaction) -> float:
        """Calculate overall similarity score between two transactions."""
        
        scores = []
        weights = []
        
        # Date similarity (within date range gets full score)
        date_diff = abs((txn1.transaction_date - txn2.transaction_date).days)
        if date_diff <= self.preferences['date_range_days']:
            date_score = 1.0 - (date_diff / self.preferences['date_range_days'])
        else:
            date_score = 0.0
        scores.append(date_score)
        weights.append(0.3)
        
        # Amount similarity
        amount_diff = abs(float(txn1.amount) - float(txn2.amount))
        amount_tolerance = self.preferences['amount_tolerance']
        if amount_diff <= amount_tolerance:
            amount_score = 1.0 - (amount_diff / amount_tolerance) if amount_tolerance > 0 else 1.0
        else:
            amount_score = 0.0
        scores.append(amount_score)
        weights.append(0.4)
        
        # Beneficiary similarity
        if FUZZY_AVAILABLE:
            beneficiary_score = fuzz.ratio(
                txn1.beneficiary.lower(), 
                txn2.beneficiary.lower()
            ) / 100.0
        else:
            beneficiary_score = 1.0 if txn1.beneficiary.lower() == txn2.beneficiary.lower() else 0.0
        scores.append(beneficiary_score)
        weights.append(0.3)
        
        # Calculate weighted average
        weighted_score = sum(s * w for s, w in zip(scores, weights)) / sum(weights)
        return weighted_score
    
    def _calculate_similarity_details(self, txn1: models.Transaction, txn2: models.Transaction) -> Dict[str, Any]:
        """Calculate detailed similarity metrics between transactions."""
        
        details = {}
        
        # Date difference
        date_diff = abs((txn1.transaction_date - txn2.transaction_date).days)
        details['date_difference_days'] = date_diff
        
        # Amount difference
        amount_diff = abs(float(txn1.amount) - float(txn2.amount))
        details['amount_difference'] = amount_diff
        
        # Beneficiary similarity
        if FUZZY_AVAILABLE:
            beneficiary_similarity = fuzz.ratio(txn1.beneficiary.lower(), txn2.beneficiary.lower())
            details['beneficiary_similarity_percent'] = beneficiary_similarity
        else:
            details['beneficiary_exact_match'] = txn1.beneficiary.lower() == txn2.beneficiary.lower()
        
        # Overall similarity
        details['overall_similarity'] = self._calculate_similarity_score(txn1, txn2)
        
        return details
    
    def _find_existing_group(self, transactions: List[models.Transaction]) -> Optional[models.DuplicateGroup]:
        """Check if a duplicate group already exists for these transactions."""
        
        transaction_ids = [t.id for t in transactions]
        
        # Find groups that contain any of these transactions
        existing_entries = self.db.query(models.DuplicateEntry).filter(
            models.DuplicateEntry.transaction_id.in_(transaction_ids)
        ).all()
        
        if existing_entries:
            # Check if any group contains all transactions
            group_transaction_counts = {}
            for entry in existing_entries:
                group_id = entry.group_id
                if group_id not in group_transaction_counts:
                    group_transaction_counts[group_id] = 0
                group_transaction_counts[group_id] += 1
            
            # Find group with all transactions
            for group_id, count in group_transaction_counts.items():
                if count == len(transactions):
                    return self.db.query(models.DuplicateGroup).filter(
                        models.DuplicateGroup.id == group_id
                    ).first()
        
        return None
    
    def _format_duplicate_group(self, group: models.DuplicateGroup, transactions: List[models.Transaction]) -> Dict[str, Any]:
        """Format duplicate group for API response."""
        
        return {
            "id": group.id,
            "similarity_score": group.similarity_score,
            "detection_method": group.detection_method,
            "status": group.status.value,
            "created_at": group.created_at.isoformat(),
            "transaction_count": len(transactions),
            "transactions": [
                {
                    "id": t.id,
                    "date": t.transaction_date.isoformat(),
                    "beneficiary": t.beneficiary,
                    "amount": float(t.amount),
                    "category": t.category
                }
                for t in transactions
            ]
        }