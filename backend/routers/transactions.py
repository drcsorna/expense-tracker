# backend/routers/transactions.py
# Complete transaction management endpoints

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, asc, extract, and_, or_
from typing import Dict, List, Optional, Any
from datetime import datetime, date, timedelta
from decimal import Decimal
import json

from .. import models

router = APIRouter()

async def get_current_user(db: Session = Depends(models.get_db)):
    """Dependency to get current user - simplified for this example."""
    # In production, this would validate JWT token and return actual user
    return db.query(models.User).first()

# ===== TRANSACTION CRUD =====

@router.get("/")
async def get_transactions(
    limit: int = Query(50, description="Maximum number of transactions to return"),
    offset: int = Query(0, description="Number of transactions to skip"),
    category: Optional[str] = Query(None, description="Filter by category"),
    date_from: Optional[date] = Query(None, description="Filter transactions from this date"),
    date_to: Optional[date] = Query(None, description="Filter transactions to this date"),
    amount_min: Optional[float] = Query(None, description="Minimum amount filter"),
    amount_max: Optional[float] = Query(None, description="Maximum amount filter"),
    search: Optional[str] = Query(None, description="Search in beneficiary and description"),
    sort_by: str = Query("date", description="Sort by: date, amount, beneficiary, category"),
    sort_order: str = Query("desc", description="Sort order: asc, desc"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Get transactions with filtering and pagination."""
    
    # Build query
    query = db.query(models.Transaction).filter(
        models.Transaction.owner_id == current_user.id
    )
    
    # Apply filters
    if category:
        query = query.filter(models.Transaction.category == category)
    
    if date_from:
        query = query.filter(models.Transaction.transaction_date >= date_from)
    
    if date_to:
        query = query.filter(models.Transaction.transaction_date <= date_to)
    
    if amount_min is not None:
        query = query.filter(models.Transaction.amount >= amount_min)
    
    if amount_max is not None:
        query = query.filter(models.Transaction.amount <= amount_max)
    
    if search:
        search_term = f"%{search.lower()}%"
        query = query.filter(
            or_(
                func.lower(models.Transaction.beneficiary).contains(search_term),
                func.lower(models.Transaction.description).contains(search_term)
            )
        )
    
    # Apply sorting
    sort_column = {
        "date": models.Transaction.transaction_date,
        "amount": models.Transaction.amount,
        "beneficiary": models.Transaction.beneficiary,
        "category": models.Transaction.category
    }.get(sort_by, models.Transaction.transaction_date)
    
    if sort_order.lower() == "asc":
        query = query.order_by(asc(sort_column))
    else:
        query = query.order_by(desc(sort_column))
    
    # Get total count
    total_count = query.count()
    
    # Apply pagination
    transactions = query.offset(offset).limit(limit).all()
    
    # Format response
    result = []
    for txn in transactions:
        result.append({
            "id": txn.id,
            "transaction_date": txn.transaction_date.isoformat(),
            "beneficiary": txn.beneficiary,
            "amount": float(txn.amount),
            "category": txn.category,
            "description": txn.description,
            "is_private": txn.is_private,
            "tags": txn.tags,
            "notes": txn.notes,
            "categorization_method": txn.categorization_method,
            "categorization_confidence": txn.categorization_confidence,
            "created_at": txn.created_at.isoformat(),
            "updated_at": txn.updated_at.isoformat()
        })
    
    return {
        "total": total_count,
        "offset": offset,
        "limit": limit,
        "transactions": result,
        "filters_applied": {
            "category": category,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "amount_min": amount_min,
            "amount_max": amount_max,
            "search": search,
            "sort_by": sort_by,
            "sort_order": sort_order
        }
    }

@router.get("/{transaction_id}")
async def get_transaction(
    transaction_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Get a specific transaction by ID."""
    
    transaction = db.query(models.Transaction).filter(
        models.Transaction.id == transaction_id,
        models.Transaction.owner_id == current_user.id
    ).first()
    
    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found"
        )
    
    return {
        "id": transaction.id,
        "transaction_date": transaction.transaction_date.isoformat(),
        "beneficiary": transaction.beneficiary,
        "amount": float(transaction.amount),
        "category": transaction.category,
        "description": transaction.description,
        "is_private": transaction.is_private,
        "tags": transaction.tags,
        "notes": transaction.notes,
        "categorization_method": transaction.categorization_method,
        "categorization_confidence": transaction.categorization_confidence,
        "manual_review_required": transaction.manual_review_required,
        "raw_data": transaction.raw_data,
        "file_hash": transaction.file_hash,
        "import_batch_id": transaction.import_batch_id,
        "created_at": transaction.created_at.isoformat(),
        "updated_at": transaction.updated_at.isoformat()
    }

@router.post("/")
async def create_transaction(
    transaction_data: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Create a new transaction manually."""
    
    # Validate required fields
    required_fields = ["transaction_date", "beneficiary", "amount"]
    for field in required_fields:
        if field not in transaction_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Missing required field: {field}"
            )
    
    try:
        # Parse date
        if isinstance(transaction_data["transaction_date"], str):
            transaction_date = datetime.fromisoformat(transaction_data["transaction_date"]).date()
        else:
            transaction_date = transaction_data["transaction_date"]
        
        # Parse amount
        amount = Decimal(str(transaction_data["amount"]))
        
        # Create transaction
        transaction = models.Transaction(
            transaction_date=transaction_date,
            beneficiary=transaction_data["beneficiary"],
            amount=amount,
            category=transaction_data.get("category"),
            description=transaction_data.get("description"),
            is_private=transaction_data.get("is_private", False),
            tags=transaction_data.get("tags", []),
            notes=transaction_data.get("notes"),
            categorization_method="manual",
            owner_id=current_user.id
        )
        
        db.add(transaction)
        db.commit()
        db.refresh(transaction)
        
        # Learn from manual categorization if category provided
        if transaction.category:
            from ..ml_categorizer import MLCategorizer
            ml_categorizer = MLCategorizer(current_user.id, db)
            await ml_categorizer.learn_from_correction({
                "beneficiary": transaction.beneficiary,
                "amount": float(transaction.amount),
                "description": transaction.description
            }, transaction.category, False)
        
        return {
            "id": transaction.id,
            "message": "Transaction created successfully",
            "transaction": {
                "id": transaction.id,
                "transaction_date": transaction.transaction_date.isoformat(),
                "beneficiary": transaction.beneficiary,
                "amount": float(transaction.amount),
                "category": transaction.category
            }
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid data format: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create transaction: {str(e)}"
        )

@router.put("/{transaction_id}")
async def update_transaction(
    transaction_id: int,
    transaction_data: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Update an existing transaction."""
    
    transaction = db.query(models.Transaction).filter(
        models.Transaction.id == transaction_id,
        models.Transaction.owner_id == current_user.id
    ).first()
    
    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found"
        )
    
    try:
        old_category = transaction.category
        
        # Update fields
        if "transaction_date" in transaction_data:
            if isinstance(transaction_data["transaction_date"], str):
                transaction.transaction_date = datetime.fromisoformat(transaction_data["transaction_date"]).date()
            else:
                transaction.transaction_date = transaction_data["transaction_date"]
        
        if "beneficiary" in transaction_data:
            transaction.beneficiary = transaction_data["beneficiary"]
        
        if "amount" in transaction_data:
            transaction.amount = Decimal(str(transaction_data["amount"]))
        
        if "category" in transaction_data:
            transaction.category = transaction_data["category"]
        
        if "description" in transaction_data:
            transaction.description = transaction_data["description"]
        
        if "is_private" in transaction_data:
            transaction.is_private = transaction_data["is_private"]
        
        if "tags" in transaction_data:
            transaction.tags = transaction_data["tags"]
        
        if "notes" in transaction_data:
            transaction.notes = transaction_data["notes"]
        
        transaction.updated_at = datetime.utcnow()
        
        db.commit()
        
        # Learn from category change
        if old_category != transaction.category and transaction.category:
            from ..ml_categorizer import MLCategorizer
            ml_categorizer = MLCategorizer(current_user.id, db)
            await ml_categorizer.learn_from_correction({
                "beneficiary": transaction.beneficiary,
                "amount": float(transaction.amount),
                "description": transaction.description,
                "suggested_category": old_category
            }, transaction.category, old_category is not None)
        
        return {
            "message": "Transaction updated successfully",
            "transaction": {
                "id": transaction.id,
                "transaction_date": transaction.transaction_date.isoformat(),
                "beneficiary": transaction.beneficiary,
                "amount": float(transaction.amount),
                "category": transaction.category
            },
            "category_changed": old_category != transaction.category
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid data format: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update transaction: {str(e)}"
        )

@router.delete("/{transaction_id}")
async def delete_transaction(
    transaction_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Delete a transaction."""
    
    transaction = db.query(models.Transaction).filter(
        models.Transaction.id == transaction_id,
        models.Transaction.owner_id == current_user.id
    ).first()
    
    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found"
        )
    
    db.delete(transaction)
    db.commit()
    
    return {"message": "Transaction deleted successfully"}

# ===== BULK OPERATIONS =====

@router.post("/bulk-update")
async def bulk_update_transactions(
    bulk_data: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Bulk update multiple transactions."""
    
    transaction_ids = bulk_data.get("transaction_ids", [])
    updates = bulk_data.get("updates", {})
    
    if not transaction_ids or not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transaction IDs and updates are required"
        )
    
    # Get transactions
    transactions = db.query(models.Transaction).filter(
        models.Transaction.id.in_(transaction_ids),
        models.Transaction.owner_id == current_user.id
    ).all()
    
    if len(transactions) != len(transaction_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Some transactions not found"
        )
    
    updated_count = 0
    
    for transaction in transactions:
        # Apply updates
        if "category" in updates:
            transaction.category = updates["category"]
        
        if "is_private" in updates:
            transaction.is_private = updates["is_private"]
        
        if "tags" in updates:
            # Merge or replace tags
            if updates.get("tags_operation") == "merge":
                existing_tags = set(transaction.tags or [])
                new_tags = set(updates["tags"])
                transaction.tags = list(existing_tags.union(new_tags))
            else:
                transaction.tags = updates["tags"]
        
        transaction.updated_at = datetime.utcnow()
        updated_count += 1
    
    db.commit()
    
    return {
        "message": "Bulk update completed",
        "updated_count": updated_count,
        "updates_applied": updates
    }

@router.delete("/bulk-delete")
async def bulk_delete_transactions(
    delete_data: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Bulk delete multiple transactions."""
    
    transaction_ids = delete_data.get("transaction_ids", [])
    
    if not transaction_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transaction IDs are required"
        )
    
    # Delete transactions
    deleted_count = db.query(models.Transaction).filter(
        models.Transaction.id.in_(transaction_ids),
        models.Transaction.owner_id == current_user.id
    ).delete(synchronize_session=False)
    
    db.commit()
    
    return {
        "message": "Bulk deletion completed",
        "deleted_count": deleted_count
    }

# ===== STATISTICS AND ANALYTICS =====

@router.get("/stats/")
async def get_transaction_statistics(
    period: str = Query("all", description="Period: 1m, 3m, 6m, 1y, all"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Get comprehensive transaction statistics."""
    
    # Calculate date range
    end_date = date.today()
    start_date = None
    
    if period == "1m":
        start_date = end_date - timedelta(days=30)
    elif period == "3m":
        start_date = end_date - timedelta(days=90)
    elif period == "6m":
        start_date = end_date - timedelta(days=180)
    elif period == "1y":
        start_date = end_date - timedelta(days=365)
    # period == "all" means no date filter
    
    # Build base query
    query = db.query(models.Transaction).filter(
        models.Transaction.owner_id == current_user.id
    )
    
    if start_date:
        query = query.filter(models.Transaction.transaction_date >= start_date)
    
    # Basic counts
    total_transactions = query.count()
    
    # Income and expenses
    income_query = query.filter(models.Transaction.amount > 0)
    expense_query = query.filter(models.Transaction.amount < 0)
    
    total_income = income_query.with_entities(func.sum(models.Transaction.amount)).scalar() or 0
    total_expenses = expense_query.with_entities(func.sum(models.Transaction.amount)).scalar() or 0
    
    income_count = income_query.count()
    expense_count = expense_query.count()
    
    # Net flow
    net_flow = float(total_income) + float(total_expenses)
    
    # Average transaction amounts
    avg_income = float(total_income) / income_count if income_count > 0 else 0
    avg_expense = abs(float(total_expenses)) / expense_count if expense_count > 0 else 0
    
    # Category breakdown
    category_stats = db.query(
        models.Transaction.category,
        func.count(models.Transaction.id).label('count'),
        func.sum(models.Transaction.amount).label('total')
    ).filter(
        models.Transaction.owner_id == current_user.id,
        models.Transaction.category.isnot(None)
    )
    
    if start_date:
        category_stats = category_stats.filter(models.Transaction.transaction_date >= start_date)
    
    category_stats = category_stats.group_by(models.Transaction.category).all()
    
    # Monthly trends (last 12 months)
    monthly_trends = db.query(
        extract('year', models.Transaction.transaction_date).label('year'),
        extract('month', models.Transaction.transaction_date).label('month'),
        func.sum(models.Transaction.amount).label('total'),
        func.count(models.Transaction.id).label('count')
    ).filter(
        models.Transaction.owner_id == current_user.id,
        models.Transaction.transaction_date >= date.today() - timedelta(days=365)
    ).group_by(
        extract('year', models.Transaction.transaction_date),
        extract('month', models.Transaction.transaction_date)
    ).order_by(
        extract('year', models.Transaction.transaction_date),
        extract('month', models.Transaction.transaction_date)
    ).all()
    
    # Top beneficiaries
    top_beneficiaries = db.query(
        models.Transaction.beneficiary,
        func.count(models.Transaction.id).label('count'),
        func.sum(models.Transaction.amount).label('total')
    ).filter(
        models.Transaction.owner_id == current_user.id
    )
    
    if start_date:
        top_beneficiaries = top_beneficiaries.filter(models.Transaction.transaction_date >= start_date)
    
    top_beneficiaries = top_beneficiaries.group_by(
        models.Transaction.beneficiary
    ).order_by(desc('count')).limit(10).all()
    
    return {
        "period": period,
        "date_range": {
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat()
        },
        "totals": {
            "transactions": total_transactions,
            "income": float(total_income),
            "expenses": abs(float(total_expenses)),
            "net_flow": net_flow
        },
        "counts": {
            "income_transactions": income_count,
            "expense_transactions": expense_count
        },
        "averages": {
            "income_per_transaction": avg_income,
            "expense_per_transaction": avg_expense
        },
        "categories": [
            {
                "name": cat.category,
                "count": cat.count,
                "total": float(cat.total),
                "type": "income" if cat.total > 0 else "expense"
            }
            for cat in category_stats
        ],
        "monthly_trends": [
            {
                "year": int(trend.year),
                "month": int(trend.month),
                "total": float(trend.total),
                "count": trend.count
            }
            for trend in monthly_trends
        ],
        "top_beneficiaries": [
            {
                "beneficiary": ben.beneficiary,
                "count": ben.count,
                "total": float(ben.total)
            }
            for ben in top_beneficiaries
        ]
    }

@router.get("/stats/spending-by-category")
async def get_spending_by_category(
    period: str = Query("3m", description="Period: 1m, 3m, 6m, 1y"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Get spending breakdown by category for charts."""
    
    # Calculate date range
    end_date = date.today()
    if period == "1m":
        start_date = end_date - timedelta(days=30)
    elif period == "3m":
        start_date = end_date - timedelta(days=90)
    elif period == "6m":
        start_date = end_date - timedelta(days=180)
    else:  # 1y
        start_date = end_date - timedelta(days=365)
    
    # Get expenses by category
    category_expenses = db.query(
        models.Transaction.category,
        func.sum(models.Transaction.amount).label('total'),
        func.count(models.Transaction.id).label('count')
    ).filter(
        models.Transaction.owner_id == current_user.id,
        models.Transaction.transaction_date >= start_date,
        models.Transaction.amount < 0,  # Expenses only
        models.Transaction.category.isnot(None)
    ).group_by(models.Transaction.category).all()
    
    # Calculate total for percentage
    total_expenses = sum(abs(float(cat.total)) for cat in category_expenses)
    
    # Format for charts
    chart_data = []
    for cat in category_expenses:
        amount = abs(float(cat.total))
        percentage = (amount / total_expenses * 100) if total_expenses > 0 else 0
        
        chart_data.append({
            "category": cat.category,
            "amount": amount,
            "percentage": round(percentage, 2),
            "count": cat.count
        })
    
    # Sort by amount descending
    chart_data.sort(key=lambda x: x["amount"], reverse=True)
    
    return {
        "period": period,
        "date_range": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat()
        },
        "total_expenses": total_expenses,
        "categories": chart_data
    }

@router.get("/stats/income-vs-expenses")
async def get_income_vs_expenses_trends(
    period: str = Query("12m", description="Period: 6m, 12m, 24m"),
    granularity: str = Query("month", description="Granularity: week, month"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Get income vs expenses trends over time."""
    
    # Calculate date range
    end_date = date.today()
    if period == "6m":
        start_date = end_date - timedelta(days=180)
    elif period == "12m":
        start_date = end_date - timedelta(days=365)
    else:  # 24m
        start_date = end_date - timedelta(days=730)
    
    # Build query based on granularity
    if granularity == "week":
        group_func = func.extract('week', models.Transaction.transaction_date)
        group_label = 'week'
    else:  # month
        group_func = func.extract('month', models.Transaction.transaction_date)
        group_label = 'month'
    
    # Get income and expenses by period
    trends = db.query(
        extract('year', models.Transaction.transaction_date).label('year'),
        group_func.label(group_label),
        func.sum(
            func.case(
                (models.Transaction.amount > 0, models.Transaction.amount),
                else_=0
            )
        ).label('income'),
        func.sum(
            func.case(
                (models.Transaction.amount < 0, models.Transaction.amount),
                else_=0
            )
        ).label('expenses')
    ).filter(
        models.Transaction.owner_id == current_user.id,
        models.Transaction.transaction_date >= start_date
    ).group_by(
        extract('year', models.Transaction.transaction_date),
        group_func
    ).order_by(
        extract('year', models.Transaction.transaction_date),
        group_func
    ).all()
    
    # Format for charts
    chart_data = []
    for trend in trends:
        chart_data.append({
            "year": int(trend.year),
            group_label: int(getattr(trend, group_label)),
            "income": float(trend.income),
            "expenses": abs(float(trend.expenses)),
            "net": float(trend.income) + float(trend.expenses)
        })
    
    return {
        "period": period,
        "granularity": granularity,
        "date_range": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat()
        },
        "trends": chart_data
    }

# ===== EXPORT =====

@router.get("/export/")
async def export_transactions(
    format: str = Query("csv", description="Export format: csv, json, xlsx"),
    category: Optional[str] = Query(None, description="Filter by category"),
    date_from: Optional[date] = Query(None, description="Export from this date"),
    date_to: Optional[date] = Query(None, description="Export to this date"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Export transactions in various formats."""
    
    if format not in ["csv", "json", "xlsx"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Format must be 'csv', 'json', or 'xlsx'"
        )
    
    # Build query
    query = db.query(models.Transaction).filter(
        models.Transaction.owner_id == current_user.id
    )
    
    # Apply filters
    if category:
        query = query.filter(models.Transaction.category == category)
    
    if date_from:
        query = query.filter(models.Transaction.transaction_date >= date_from)
    
    if date_to:
        query = query.filter(models.Transaction.transaction_date <= date_to)
    
    # Get transactions
    transactions = query.order_by(desc(models.Transaction.transaction_date)).all()
    
    # Format data
    export_data = []
    for txn in transactions:
        export_data.append({
            "id": txn.id,
            "date": txn.transaction_date.isoformat(),
            "beneficiary": txn.beneficiary,
            "amount": float(txn.amount),
            "category": txn.category or "",
            "description": txn.description or "",
            "tags": ",".join(txn.tags) if txn.tags else "",
            "notes": txn.notes or "",
            "is_private": txn.is_private,
            "created_at": txn.created_at.isoformat()
        })
    
    return {
        "format": format,
        "export_timestamp": datetime.utcnow().isoformat(),
        "total_transactions": len(export_data),
        "filters_applied": {
            "category": category,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None
        },
        "data": export_data
    }

# ===== SEARCH AND INSIGHTS =====

@router.get("/search/")
async def search_transactions(
    q: str = Query(..., description="Search query"),
    limit: int = Query(20, description="Maximum results"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Advanced transaction search."""
    
    search_terms = q.lower().split()
    
    # Build search conditions
    conditions = []
    for term in search_terms:
        term_conditions = [
            func.lower(models.Transaction.beneficiary).contains(term),
            func.lower(models.Transaction.description).contains(term),
            func.lower(models.Transaction.category).contains(term)
        ]
        
        # Try to parse as amount
        try:
            amount_val = float(term)
            term_conditions.append(models.Transaction.amount == amount_val)
        except ValueError:
            pass
        
        conditions.append(or_(*term_conditions))
    
    # Execute search
    query = db.query(models.Transaction).filter(
        models.Transaction.owner_id == current_user.id,
        and_(*conditions)
    )
    
    total_results = query.count()
    results = query.order_by(desc(models.Transaction.transaction_date)).limit(limit).all()
    
    # Format results
    search_results = []
    for txn in results:
        search_results.append({
            "id": txn.id,
            "transaction_date": txn.transaction_date.isoformat(),
            "beneficiary": txn.beneficiary,
            "amount": float(txn.amount),
            "category": txn.category,
            "description": txn.description,
            "relevance_score": 1.0  # Could implement proper relevance scoring
        })
    
    return {
        "query": q,
        "total_results": total_results,
        "results_returned": len(search_results),
        "results": search_results
    }

@router.get("/insights/")
async def get_transaction_insights(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Get financial insights and recommendations."""
    
    # Get recent transactions for analysis
    thirty_days_ago = date.today() - timedelta(days=30)
    recent_transactions = db.query(models.Transaction).filter(
        models.Transaction.owner_id == current_user.id,
        models.Transaction.transaction_date >= thirty_days_ago
    ).all()
    
    insights = []
    
    # Insight 1: High spending categories
    category_spending = {}
    for txn in recent_transactions:
        if txn.amount < 0 and txn.category:  # Expenses only
            if txn.category not in category_spending:
                category_spending[txn.category] = 0
            category_spending[txn.category] += abs(float(txn.amount))
    
    if category_spending:
        top_category = max(category_spending, key=category_spending.get)
        top_amount = category_spending[top_category]
        
        insights.append({
            "type": "high_spending",
            "title": f"High spending in {top_category}",
            "description": f"You spent €{top_amount:.2f} on {top_category} in the last 30 days",
            "action": f"Consider reviewing your {top_category} expenses",
            "priority": "medium"
        })
    
    # Insight 2: Uncategorized transactions
    uncategorized = [txn for txn in recent_transactions if not txn.category]
    if len(uncategorized) > 5:
        insights.append({
            "type": "uncategorized",
            "title": "Many uncategorized transactions",
            "description": f"You have {len(uncategorized)} uncategorized transactions",
            "action": "Categorize transactions for better tracking",
            "priority": "low"
        })
    
    # Insight 3: Income vs expenses
    total_income = sum(float(txn.amount) for txn in recent_transactions if txn.amount > 0)
    total_expenses = sum(abs(float(txn.amount)) for txn in recent_transactions if txn.amount < 0)
    
    if total_expenses > total_income:
        insights.append({
            "type": "negative_flow",
            "title": "Expenses exceed income",
            "description": f"Your expenses (€{total_expenses:.2f}) exceeded income (€{total_income:.2f}) by €{total_expenses - total_income:.2f}",
            "action": "Review your spending patterns",
            "priority": "high"
        })
    
    return {
        "analysis_period": "30 days",
        "insights_count": len(insights),
        "insights": insights,
        "summary": {
            "transactions_analyzed": len(recent_transactions),
            "income": total_income,
            "expenses": total_expenses,
            "net_flow": total_income - total_expenses
        }
    }