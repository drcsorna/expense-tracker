# backend/ml_categorizer.py
# Machine Learning categorization engine with fuzzy matching and learning

import re
import json
from typing import Dict, List, Optional, Tuple, Any
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from decimal import Decimal

# ML and text processing imports
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.naive_bayes import MultinomialNB
    from sklearn.pipeline import Pipeline
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import accuracy_score
    import numpy as np
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

try:
    from fuzzywuzzy import fuzz, process
    FUZZY_AVAILABLE = True
except ImportError:
    FUZZY_AVAILABLE = False

from . import models

class MLCategorizer:
    """Advanced ML-powered transaction categorization engine."""
    
    def __init__(self, user_id: int, db: Session):
        self.user_id = user_id
        self.db = db
        self.model = None
        self.vectorizer = None
        self.categories = []
        self.keyword_rules = {}
        self.amount_patterns = {}
        self.beneficiary_patterns = {}
        self.confidence_threshold = 0.7
        
        # Load user preferences
        user = db.query(models.User).filter(models.User.id == user_id).first()
        if user and user.preferences:
            cat_prefs = user.preferences.get('categorization', {})
            self.confidence_threshold = cat_prefs.get('confidence_threshold', 0.7)
    
    async def train_model(self) -> Dict[str, Any]:
        """Train the ML model with existing user data."""
        
        # Load categories and rules
        await self._load_categories()
        await self._load_existing_rules()
        
        # Get training data from existing transactions
        training_data = self._get_training_data()
        
        if len(training_data) < 10:  # Not enough data for ML
            return {
                "model_trained": False,
                "reason": "insufficient_data",
                "training_samples": len(training_data),
                "min_required": 10
            }
        
        if not SKLEARN_AVAILABLE:
            return {
                "model_trained": False,
                "reason": "sklearn_unavailable",
                "training_samples": len(training_data)
            }
        
        try:
            # Prepare features and labels
            features = []
            labels = []
            
            for transaction in training_data:
                feature = self._extract_features(transaction)
                features.append(feature)
                labels.append(transaction['category'])
            
            # Create and train pipeline
            self.vectorizer = TfidfVectorizer(
                max_features=1000,
                stop_words='english',
                ngram_range=(1, 2),
                lowercase=True
            )
            
            self.model = Pipeline([
                ('tfidf', self.vectorizer),
                ('classifier', MultinomialNB(alpha=0.1))
            ])
            
            # Split data for validation
            if len(features) > 20:
                X_train, X_test, y_train, y_test = train_test_split(
                    features, labels, test_size=0.2, random_state=42
                )
                
                self.model.fit(X_train, y_train)
                
                # Calculate accuracy
                y_pred = self.model.predict(X_test)
                accuracy = accuracy_score(y_test, y_pred)
            else:
                # Use all data for training if too small for split
                self.model.fit(features, labels)
                accuracy = 0.0  # Can't calculate without test set
            
            return {
                "model_trained": True,
                "training_samples": len(training_data),
                "accuracy": accuracy,
                "categories_learned": len(set(labels))
            }
            
        except Exception as e:
            return {
                "model_trained": False,
                "reason": f"training_error: {str(e)}",
                "training_samples": len(training_data)
            }
    
    async def suggest_category(self, transaction: Dict) -> Dict[str, Any]:
        """Suggest category for a transaction with confidence score."""
        
        suggestions = []
        
        # Method 1: Exact keyword matching (highest confidence)
        keyword_match = self._match_keywords(transaction)
        if keyword_match:
            suggestions.append({
                "category": keyword_match["category"],
                "category_id": keyword_match["category_id"],
                "confidence": keyword_match["confidence"],
                "method": "keyword_exact"
            })
        
        # Method 2: Fuzzy beneficiary matching
        if FUZZY_AVAILABLE:
            fuzzy_match = await self._fuzzy_beneficiary_match(transaction)
            if fuzzy_match:
                suggestions.append({
                    "category": fuzzy_match["category"],
                    "category_id": fuzzy_match["category_id"],
                    "confidence": fuzzy_match["confidence"],
                    "method": "fuzzy_beneficiary"
                })
        
        # Method 3: Amount pattern matching
        amount_match = self._match_amount_patterns(transaction)
        if amount_match:
            suggestions.append({
                "category": amount_match["category"],
                "category_id": amount_match["category_id"],
                "confidence": amount_match["confidence"],
                "method": "amount_pattern"
            })
        
        # Method 4: ML model prediction
        if self.model and SKLEARN_AVAILABLE:
            ml_match = self._ml_predict(transaction)
            if ml_match:
                suggestions.append({
                    "category": ml_match["category"],
                    "category_id": ml_match["category_id"],
                    "confidence": ml_match["confidence"],
                    "method": "ml_model"
                })
        
        # Method 5: Rule-based matching
        rule_match = await self._apply_learned_rules(transaction)
        if rule_match:
            suggestions.append({
                "category": rule_match["category"],
                "category_id": rule_match["category_id"],
                "confidence": rule_match["confidence"],
                "method": "learned_rule"
            })
        
        # Combine and rank suggestions
        return self._combine_suggestions(suggestions)
    
    async def learn_from_correction(self, transaction: Dict, correct_category: str, was_suggestion: bool = False):
        """Learn from user corrections to improve future suggestions."""
        
        # Record user feedback
        feedback = models.UserFeedback(
            transaction_beneficiary=transaction.get('beneficiary', ''),
            transaction_amount=transaction.get('amount', 0),
            suggested_category=transaction.get('suggested_category', ''),
            actual_category=correct_category,
            was_accepted=not was_suggestion,
            confidence_score=transaction.get('confidence', 0.0),
            feedback_type='correction' if was_suggestion else 'manual',
            user_id=self.user_id
        )
        
        self.db.add(feedback)
        
        # Create or update categorization rules
        await self._update_categorization_rules(transaction, correct_category)
        
        self.db.commit()
    
    async def bulk_recategorize(self, old_category: str, new_category: str) -> Dict[str, Any]:
        """Recategorize all transactions from old_category to new_category."""
        
        # Update existing transactions
        updated_count = self.db.query(models.Transaction).filter(
            models.Transaction.owner_id == self.user_id,
            models.Transaction.category == old_category
        ).update({"category": new_category})
        
        # Update staged transactions
        staged_updated = self.db.query(models.StagedTransaction).filter(
            models.StagedTransaction.owner_id == self.user_id,
            models.StagedTransaction.suggested_category == old_category
        ).update({"suggested_category": new_category})
        
        # Update category rules
        self.db.query(models.CategorizationRule).filter(
            models.CategorizationRule.user_id == self.user_id,
            models.CategorizationRule.category.has(name=old_category)
        ).update({"category": self.db.query(models.Category).filter(
            models.Category.user_id == self.user_id,
            models.Category.name == new_category
        ).first()})
        
        self.db.commit()
        
        return {
            "updated_transactions": updated_count,
            "updated_staged": staged_updated,
            "old_category": old_category,
            "new_category": new_category
        }
    
    def _get_training_data(self) -> List[Dict]:
        """Get training data from existing categorized transactions."""
        
        # Get transactions with categories
        transactions = self.db.query(models.Transaction).filter(
            models.Transaction.owner_id == self.user_id,
            models.Transaction.category.isnot(None),
            models.Transaction.category != ""
        ).order_by(models.Transaction.transaction_date.desc()).limit(1000).all()
        
        training_data = []
        for txn in transactions:
            training_data.append({
                "beneficiary": txn.beneficiary,
                "amount": float(txn.amount),
                "category": txn.category,
                "date": txn.transaction_date,
                "description": txn.description or txn.beneficiary
            })
        
        return training_data
    
    async def _load_categories(self):
        """Load user categories and their metadata."""
        categories = self.db.query(models.Category).filter(
            models.Category.user_id == self.user_id,
            models.Category.is_active == True
        ).all()
        
        self.categories = {
            cat.name: {
                "id": cat.id,
                "keywords": cat.keywords or [],
                "learned_patterns": cat.learned_patterns or {},
                "confidence_score": cat.confidence_score or 0.0
            }
            for cat in categories
        }
    
    async def _load_existing_rules(self):
        """Load existing categorization rules."""
        rules = self.db.query(models.CategorizationRule).filter(
            models.CategorizationRule.user_id == self.user_id,
            models.CategorizationRule.is_active == True
        ).all()
        
        self.keyword_rules = {}
        self.amount_patterns = {}
        self.beneficiary_patterns = {}
        
        for rule in rules:
            category_name = rule.category.name
            pattern = rule.pattern
            
            if rule.rule_type == "keyword":
                if category_name not in self.keyword_rules:
                    self.keyword_rules[category_name] = []
                self.keyword_rules[category_name].append({
                    "keywords": pattern.get("keywords", []),
                    "confidence": rule.confidence
                })
            
            elif rule.rule_type == "amount_range":
                if category_name not in self.amount_patterns:
                    self.amount_patterns[category_name] = []
                self.amount_patterns[category_name].append({
                    "min_amount": pattern.get("min_amount"),
                    "max_amount": pattern.get("max_amount"),
                    "confidence": rule.confidence
                })
            
            elif rule.rule_type == "beneficiary_pattern":
                if category_name not in self.beneficiary_patterns:
                    self.beneficiary_patterns[category_name] = []
                self.beneficiary_patterns[category_name].append({
                    "pattern": pattern.get("pattern", ""),
                    "confidence": rule.confidence
                })
    
    def _match_keywords(self, transaction: Dict) -> Optional[Dict]:
        """Match transaction against keyword rules."""
        beneficiary = transaction.get('beneficiary', '').lower()
        description = transaction.get('description', '').lower()
        
        best_match = None
        best_confidence = 0
        
        for category_name, category_data in self.categories.items():
            keywords = category_data.get('keywords', [])
            
            for keyword in keywords:
                keyword_lower = keyword.lower()
                
                # Exact match in beneficiary or description
                if keyword_lower in beneficiary or keyword_lower in description:
                    confidence = 0.95  # High confidence for exact keyword match
                    
                    if confidence > best_confidence:
                        best_confidence = confidence
                        best_match = {
                            "category": category_name,
                            "category_id": category_data["id"],
                            "confidence": confidence,
                            "matched_keyword": keyword
                        }
        
        return best_match if best_confidence >= self.confidence_threshold else None
    
    async def _fuzzy_beneficiary_match(self, transaction: Dict) -> Optional[Dict]:
        """Match transaction using fuzzy string matching."""
        if not FUZZY_AVAILABLE:
            return None
        
        beneficiary = transaction.get('beneficiary', '')
        
        # Get all unique beneficiaries with their categories
        existing_beneficiaries = self.db.query(
            models.Transaction.beneficiary,
            models.Transaction.category
        ).filter(
            models.Transaction.owner_id == self.user_id,
            models.Transaction.category.isnot(None)
        ).distinct().all()
        
        if not existing_beneficiaries:
            return None
        
        # Find best fuzzy match
        beneficiary_list = [b.beneficiary for b in existing_beneficiaries]
        match = process.extractOne(beneficiary, beneficiary_list, scorer=fuzz.ratio)
        
        if match and match[1] >= 85:  # 85% similarity threshold
            matched_beneficiary = match[0]
            
            # Find the category for this beneficiary
            for b in existing_beneficiaries:
                if b.beneficiary == matched_beneficiary:
                    category_data = self.categories.get(b.category)
                    if category_data:
                        confidence = match[1] / 100.0  # Convert to 0-1 scale
                        
                        return {
                            "category": b.category,
                            "category_id": category_data["id"],
                            "confidence": confidence,
                            "matched_beneficiary": matched_beneficiary,
                            "similarity_score": match[1]
                        }
        
        return None
    
    def _match_amount_patterns(self, transaction: Dict) -> Optional[Dict]:
        """Match transaction based on amount patterns."""
        amount = float(transaction.get('amount', 0))
        
        best_match = None
        best_confidence = 0
        
        for category_name, patterns in self.amount_patterns.items():
            for pattern in patterns:
                min_amount = pattern.get('min_amount')
                max_amount = pattern.get('max_amount')
                
                # Check if amount falls within range
                if min_amount is not None and amount < min_amount:
                    continue
                if max_amount is not None and amount > max_amount:
                    continue
                
                confidence = pattern.get('confidence', 0.5)
                
                if confidence > best_confidence:
                    best_confidence = confidence
                    category_data = self.categories.get(category_name)
                    if category_data:
                        best_match = {
                            "category": category_name,
                            "category_id": category_data["id"],
                            "confidence": confidence
                        }
        
        return best_match if best_confidence >= self.confidence_threshold else None
    
    def _ml_predict(self, transaction: Dict) -> Optional[Dict]:
        """Use ML model to predict category."""
        if not self.model or not SKLEARN_AVAILABLE:
            return None
        
        try:
            feature = self._extract_features(transaction)
            
            # Get prediction and probabilities
            predicted_category = self.model.predict([feature])[0]
            probabilities = self.model.predict_proba([feature])[0]
            
            # Get confidence (max probability)
            confidence = float(max(probabilities))
            
            if confidence >= self.confidence_threshold:
                category_data = self.categories.get(predicted_category)
                if category_data:
                    return {
                        "category": predicted_category,
                        "category_id": category_data["id"],
                        "confidence": confidence
                    }
        
        except Exception:
            pass  # Model prediction failed
        
        return None
    
    async def _apply_learned_rules(self, transaction: Dict) -> Optional[Dict]:
        """Apply learned categorization rules."""
        # This would apply more complex rules learned from user behavior
        # For now, return None as this is a placeholder for advanced rule matching
        return None
    
    def _extract_features(self, transaction: Dict) -> str:
        """Extract text features for ML model."""
        beneficiary = transaction.get('beneficiary', '')
        description = transaction.get('description', '')
        amount = transaction.get('amount', 0)
        
        # Create feature string combining various elements
        features = []
        
        # Add beneficiary words
        beneficiary_words = re.findall(r'\w+', beneficiary.lower())
        features.extend(beneficiary_words)
        
        # Add description words if different from beneficiary
        if description and description != beneficiary:
            description_words = re.findall(r'\w+', description.lower())
            features.extend(description_words)
        
        # Add amount range indicators
        amount_val = float(amount)
        if amount_val < -100:
            features.append('large_expense')
        elif amount_val < -20:
            features.append('medium_expense')
        elif amount_val < 0:
            features.append('small_expense')
        elif amount_val > 1000:
            features.append('large_income')
        elif amount_val > 0:
            features.append('income')
        
        return ' '.join(features)
    
    def _combine_suggestions(self, suggestions: List[Dict]) -> Dict[str, Any]:
        """Combine multiple suggestions into final recommendation."""
        if not suggestions:
            return {
                "category": None,
                "category_id": None,
                "confidence": 0.0,
                "alternatives": []
            }
        
        # Sort by confidence
        suggestions.sort(key=lambda x: x["confidence"], reverse=True)
        
        # Take the highest confidence suggestion as primary
        primary = suggestions[0]
        
        # Collect alternatives (different categories)
        alternatives = []
        seen_categories = {primary["category"]}
        
        for suggestion in suggestions[1:]:
            if suggestion["category"] not in seen_categories:
                alternatives.append({
                    "category": suggestion["category"],
                    "confidence": suggestion["confidence"],
                    "method": suggestion["method"]
                })
                seen_categories.add(suggestion["category"])
                
                if len(alternatives) >= 3:  # Limit to 3 alternatives
                    break
        
        return {
            "category": primary["category"],
            "category_id": primary["category_id"],
            "confidence": primary["confidence"],
            "method": primary["method"],
            "alternatives": alternatives
        }
    
    async def _update_categorization_rules(self, transaction: Dict, category: str):
        """Update or create categorization rules based on user correction."""
        
        # Find or create category
        category_obj = self.db.query(models.Category).filter(
            models.Category.user_id == self.user_id,
            models.Category.name == category
        ).first()
        
        if not category_obj:
            return  # Category doesn't exist
        
        beneficiary = transaction.get('beneficiary', '').lower()
        
        # Check if we should create a new beneficiary pattern rule
        existing_rule = self.db.query(models.CategorizationRule).filter(
            models.CategorizationRule.user_id == self.user_id,
            models.CategorizationRule.category_id == category_obj.id,
            models.CategorizationRule.rule_type == "beneficiary_pattern",
            models.CategorizationRule.pattern.contains(beneficiary)
        ).first()
        
        if not existing_rule:
            # Create new rule
            new_rule = models.CategorizationRule(
                rule_type="beneficiary_pattern",
                pattern={"pattern": beneficiary, "exact_match": True},
                confidence=0.9,
                success_count=1,
                category_id=category_obj.id,
                user_id=self.user_id,
                created_at=datetime.utcnow()
            )
            self.db.add(new_rule)
        else:
            # Update existing rule
            existing_rule.success_count += 1
            existing_rule.confidence = min(0.95, existing_rule.confidence + 0.05)
            existing_rule.last_used = datetime.utcnow()
        
        # Update category usage count
        category_obj.usage_count += 1
        category_obj.updated_at = datetime.utcnow()