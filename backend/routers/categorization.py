# backend/routers/categorization.py
# ML-powered categorization management endpoints

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import Dict, List, Optional, Any
from datetime import datetime
import json

from .. import models
from ..ml_categorizer import MLCategorizer
from ..category_bootstrap import CategoryBootstrap

router = APIRouter()

async def get_current_user(db: Session = Depends(models.get_db)):
    """Dependency to get current user - simplified for this example."""
    # In production, this would validate JWT token and return actual user
    # For now, returning a mock user
    return db.query(models.User).first()

# ===== CATEGORY MANAGEMENT =====

@router.get("/categories/")
async def get_user_categories(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Get all categories for the current user with usage statistics."""
    
    categories = db.query(models.Category).filter(
        models.Category.user_id == current_user.id,
        models.Category.is_active == True
    ).order_by(models.Category.name).all()
    
    result = []
    for category in categories:
        # Get transaction count for this category
        transaction_count = db.query(func.count(models.Transaction.id)).filter(
            models.Transaction.owner_id == current_user.id,
            models.Transaction.category == category.name
        ).scalar() or 0
        
        # Get recent usage
        recent_usage = db.query(func.count(models.Transaction.id)).filter(
            models.Transaction.owner_id == current_user.id,
            models.Transaction.category == category.name,
            models.Transaction.transaction_date >= datetime.now().date().replace(day=1)
        ).scalar() or 0
        
        result.append({
            "id": category.id,
            "name": category.name,
            "color": category.color,
            "icon": category.icon,
            "description": category.description,
            "keywords": category.keywords,
            "confidence_score": category.confidence_score,
            "transaction_count": transaction_count,
            "recent_usage": recent_usage,
            "created_at": category.created_at.isoformat(),
            "updated_at": category.updated_at.isoformat()
        })
    
    return result

@router.post("/categories/")
async def create_category(
    category_data: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Create a new category with optional keywords."""
    
    name = category_data.get("name", "").strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category name is required"
        )
    
    # Check if category already exists
    existing = db.query(models.Category).filter(
        models.Category.user_id == current_user.id,
        models.Category.name == name,
        models.Category.is_active == True
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category already exists"
        )
    
    # Parse keywords
    keywords = []
    if category_data.get("keywords"):
        keywords = [k.strip() for k in category_data["keywords"].split(",") if k.strip()]
    
    # Create category
    new_category = models.Category(
        name=name,
        color=category_data.get("color", "#6366f1"),
        icon=category_data.get("icon"),
        description=category_data.get("description"),
        keywords=keywords,
        user_id=current_user.id
    )
    
    db.add(new_category)
    db.commit()
    db.refresh(new_category)
    
    # Create keyword-based categorization rules
    if keywords:
        await _create_keyword_rules(new_category, keywords, db)
    
    return {
        "id": new_category.id,
        "name": new_category.name,
        "color": new_category.color,
        "icon": new_category.icon,
        "keywords": new_category.keywords,
        "message": "Category created successfully"
    }

@router.put("/categories/{category_id}")
async def update_category(
    category_id: int,
    category_data: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Update an existing category."""
    
    category = db.query(models.Category).filter(
        models.Category.id == category_id,
        models.Category.user_id == current_user.id
    ).first()
    
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found"
        )
    
    old_name = category.name
    
    # Update fields
    if "name" in category_data:
        new_name = category_data["name"].strip()
        if new_name and new_name != old_name:
            # Check for duplicate name
            existing = db.query(models.Category).filter(
                models.Category.user_id == current_user.id,
                models.Category.name == new_name,
                models.Category.id != category_id,
                models.Category.is_active == True
            ).first()
            
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Category name already exists"
                )
            
            category.name = new_name
    
    if "color" in category_data:
        category.color = category_data["color"]
    
    if "icon" in category_data:
        category.icon = category_data["icon"]
    
    if "description" in category_data:
        category.description = category_data["description"]
    
    if "keywords" in category_data:
        keywords = [k.strip() for k in category_data["keywords"].split(",") if k.strip()]
        category.keywords = keywords
        
        # Update keyword rules
        await _update_keyword_rules(category, keywords, db)
    
    category.updated_at = datetime.utcnow()
    db.commit()
    
    # If name changed, update all transactions using the old category name
    if old_name != category.name:
        ml_categorizer = MLCategorizer(current_user.id, db)
        await ml_categorizer.bulk_recategorize(old_name, category.name)
    
    return {
        "id": category.id,
        "name": category.name,
        "message": "Category updated successfully",
        "name_changed": old_name != category.name
    }

@router.delete("/categories/{category_id}")
async def delete_category(
    category_id: int,
    merge_to_category: Optional[str] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Delete a category, optionally merging transactions to another category."""
    
    category = db.query(models.Category).filter(
        models.Category.id == category_id,
        models.Category.user_id == current_user.id
    ).first()
    
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found"
        )
    
    # Count transactions using this category
    transaction_count = db.query(func.count(models.Transaction.id)).filter(
        models.Transaction.owner_id == current_user.id,
        models.Transaction.category == category.name
    ).scalar() or 0
    
    # Handle existing transactions
    if transaction_count > 0:
        if merge_to_category:
            # Verify target category exists
            target_category = db.query(models.Category).filter(
                models.Category.user_id == current_user.id,
                models.Category.name == merge_to_category,
                models.Category.is_active == True
            ).first()
            
            if not target_category:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Target category for merge does not exist"
                )
            
            # Update all transactions to use the target category
            db.query(models.Transaction).filter(
                models.Transaction.owner_id == current_user.id,
                models.Transaction.category == category.name
            ).update({"category": merge_to_category})
            
        else:
            # Set category to None (uncategorized)
            db.query(models.Transaction).filter(
                models.Transaction.owner_id == current_user.id,
                models.Transaction.category == category.name
            ).update({"category": None})
    
    # Delete associated rules
    db.query(models.CategorizationRule).filter(
        models.CategorizationRule.category_id == category_id
    ).delete()
    
    # Soft delete the category
    category.is_active = False
    category.updated_at = datetime.utcnow()
    
    db.commit()
    
    return {
        "message": "Category deleted successfully",
        "affected_transactions": transaction_count,
        "merged_to": merge_to_category
    }

# ===== ML CATEGORIZATION =====

@router.post("/suggest/{transaction_id}")
async def suggest_category_for_transaction(
    transaction_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Get ML category suggestion for a specific transaction."""
    
    # Check if it's a staged transaction
    staged_txn = db.query(models.StagedTransaction).filter(
        models.StagedTransaction.id == transaction_id,
        models.StagedTransaction.owner_id == current_user.id
    ).first()
    
    if staged_txn:
        transaction_data = {
            "beneficiary": staged_txn.beneficiary,
            "amount": float(staged_txn.amount),
            "transaction_date": staged_txn.transaction_date,
            "description": staged_txn.description
        }
    else:
        # Check regular transactions
        txn = db.query(models.Transaction).filter(
            models.Transaction.id == transaction_id,
            models.Transaction.owner_id == current_user.id
        ).first()
        
        if not txn:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transaction not found"
            )
        
        transaction_data = {
            "beneficiary": txn.beneficiary,
            "amount": float(txn.amount),
            "transaction_date": txn.transaction_date,
            "description": txn.description
        }
    
    # Get ML suggestion
    ml_categorizer = MLCategorizer(current_user.id, db)
    await ml_categorizer.train_model()
    suggestion = await ml_categorizer.suggest_category(transaction_data)
    
    return {
        "transaction_id": transaction_id,
        "suggestion": suggestion,
        "timestamp": datetime.utcnow().isoformat()
    }

@router.post("/train-model/")
async def train_categorization_model(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Manually trigger ML model training."""
    
    ml_categorizer = MLCategorizer(current_user.id, db)
    training_result = await ml_categorizer.train_model()
    
    return {
        "training_result": training_result,
        "timestamp": datetime.utcnow().isoformat()
    }

@router.post("/feedback/")
async def provide_categorization_feedback(
    feedback_data: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Provide feedback on ML categorization for learning."""
    
    transaction_data = feedback_data.get("transaction", {})
    correct_category = feedback_data.get("correct_category")
    was_suggestion = feedback_data.get("was_suggestion", False)
    
    if not transaction_data or not correct_category:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transaction data and correct category are required"
        )
    
    ml_categorizer = MLCategorizer(current_user.id, db)
    await ml_categorizer.learn_from_correction(
        transaction_data, correct_category, was_suggestion
    )
    
    return {
        "message": "Feedback recorded successfully",
        "will_improve_suggestions": True
    }

@router.post("/bulk-recategorize/")
async def bulk_recategorize_transactions(
    recategorize_data: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Bulk recategorize transactions from one category to another."""
    
    old_category = recategorize_data.get("old_category")
    new_category = recategorize_data.get("new_category")
    
    if not old_category or not new_category:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Both old_category and new_category are required"
        )
    
    # Verify new category exists
    target_category = db.query(models.Category).filter(
        models.Category.user_id == current_user.id,
        models.Category.name == new_category,
        models.Category.is_active == True
    ).first()
    
    if not target_category:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Target category does not exist"
        )
    
    ml_categorizer = MLCategorizer(current_user.id, db)
    result = await ml_categorizer.bulk_recategorize(old_category, new_category)
    
    return result

# ===== CATEGORY BOOTSTRAP =====

@router.post("/bootstrap/")
async def bootstrap_categories_from_file(
    file: UploadFile = File(...),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Bootstrap categorization rules from existing categorized data."""
    
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No file provided"
        )
    
    # Validate file type
    allowed_extensions = {'.csv', '.xls', '.xlsx'}
    file_extension = '.' + file.filename.split('.')[-1].lower()
    
    if file_extension not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type. Allowed: {', '.join(allowed_extensions)}"
        )
    
    try:
        # Read file content
        content = await file.read()
        
        # Initialize bootstrap processor
        bootstrap = CategoryBootstrap(current_user.id, db)
        
        # Process the file
        result = await bootstrap.process_bootstrap_file(content, file.filename)
        
        return {
            "filename": file.filename,
            "processing_result": result,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Bootstrap processing failed: {str(e)}"
        )

@router.get("/rules/")
async def get_categorization_rules(
    rule_type: Optional[str] = None,
    category_id: Optional[int] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Get categorization rules for the user."""
    
    query = db.query(models.CategorizationRule).filter(
        models.CategorizationRule.user_id == current_user.id,
        models.CategorizationRule.is_active == True
    )
    
    if rule_type:
        query = query.filter(models.CategorizationRule.rule_type == rule_type)
    
    if category_id:
        query = query.filter(models.CategorizationRule.category_id == category_id)
    
    rules = query.order_by(desc(models.CategorizationRule.confidence)).all()
    
    result = []
    for rule in rules:
        result.append({
            "id": rule.id,
            "rule_type": rule.rule_type,
            "pattern": rule.pattern,
            "confidence": rule.confidence,
            "success_count": rule.success_count,
            "failure_count": rule.failure_count,
            "category": {
                "id": rule.category.id,
                "name": rule.category.name,
                "color": rule.category.color
            },
            "created_at": rule.created_at.isoformat(),
            "last_used": rule.last_used.isoformat() if rule.last_used else None
        })
    
    return result

@router.delete("/rules/{rule_id}")
async def delete_categorization_rule(
    rule_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Delete a categorization rule."""
    
    rule = db.query(models.CategorizationRule).filter(
        models.CategorizationRule.id == rule_id,
        models.CategorizationRule.user_id == current_user.id
    ).first()
    
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rule not found"
        )
    
    rule.is_active = False
    db.commit()
    
    return {"message": "Rule deleted successfully"}

# ===== ANALYTICS =====

@router.get("/analytics/accuracy/")
async def get_categorization_accuracy(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Get ML categorization accuracy metrics."""
    
    # Get feedback data
    feedback_data = db.query(models.UserFeedback).filter(
        models.UserFeedback.user_id == current_user.id
    ).all()
    
    if not feedback_data:
        return {
            "total_feedback": 0,
            "accuracy": 0.0,
            "high_confidence_accuracy": 0.0,
            "category_performance": []
        }
    
    # Calculate overall accuracy
    correct_predictions = sum(1 for f in feedback_data if f.was_accepted)
    total_predictions = len(feedback_data)
    overall_accuracy = correct_predictions / total_predictions if total_predictions > 0 else 0
    
    # Calculate high-confidence accuracy (>= 0.8 confidence)
    high_conf_feedback = [f for f in feedback_data if f.confidence_score >= 0.8]
    high_conf_correct = sum(1 for f in high_conf_feedback if f.was_accepted)
    high_conf_accuracy = high_conf_correct / len(high_conf_feedback) if high_conf_feedback else 0
    
    # Category-wise performance
    category_performance = {}
    for feedback in feedback_data:
        cat = feedback.suggested_category
        if cat not in category_performance:
            category_performance[cat] = {"correct": 0, "total": 0}
        
        category_performance[cat]["total"] += 1
        if feedback.was_accepted:
            category_performance[cat]["correct"] += 1
    
    category_stats = [
        {
            "category": cat,
            "accuracy": stats["correct"] / stats["total"],
            "total_predictions": stats["total"]
        }
        for cat, stats in category_performance.items()
    ]
    
    return {
        "total_feedback": total_predictions,
        "accuracy": overall_accuracy,
        "high_confidence_accuracy": high_conf_accuracy,
        "category_performance": sorted(category_stats, key=lambda x: x["accuracy"], reverse=True)
    }

# ===== HELPER FUNCTIONS =====

async def _create_keyword_rules(category: models.Category, keywords: List[str], db: Session):
    """Create keyword-based categorization rules for a category."""
    
    for keyword in keywords:
        rule = models.CategorizationRule(
            rule_type="keyword",
            pattern={"keywords": [keyword], "exact_match": False},
            confidence=0.8,
            category_id=category.id,
            user_id=category.user_id
        )
        db.add(rule)
    
    db.commit()

async def _update_keyword_rules(category: models.Category, keywords: List[str], db: Session):
    """Update keyword rules for a category."""
    
    # Delete existing keyword rules for this category
    db.query(models.CategorizationRule).filter(
        models.CategorizationRule.category_id == category.id,
        models.CategorizationRule.rule_type == "keyword"
    ).delete()
    
    # Create new keyword rules
    await _create_keyword_rules(category, keywords, db)