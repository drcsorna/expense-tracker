# backend/routers/transactions.py
# Complete transactions management router

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, and_, or_
from typing import Dict, List, Optional, Any
from datetime import datetime, date, timedelta
from decimal import Decimal

from .. import models
from ..dependencies import get_current_user, get_db, get_pagination_params

router = APIRouter()

# ===== TRANSACTION RETRIEVAL =====

@router.get("/")
async def get_transactions(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    pagination: dict = Depends(get_pagination_params),
    category: Optional[str] = Query(None, description="Filter by category"),
    start_date: Optional[date] = Query(None, description="Start date filter"),
    end_date: Optional[date] = Query(None, description="End date filter"),
    search: Optional[str] = Query(None, description="Search in beneficiary or notes"),
    min_amount: Optional[float] = Query(None, description="Minimum amount filter"),
    max_amount: Optional[float] = Query(None, description="Maximum amount filter")
):
    """Get user's confirmed transactions with filtering and pagination."""
    
    try:
        # Build base query
        query = db.query(models.Transaction).filter(
            models.Transaction.owner_id == current_user.id
        )
        
        # Apply filters
        if category:
            query = query.filter(models.Transaction.category == category)
        
        if start_date:
            query = query.filter(models.Transaction.transaction_date >= start_date)
        
        if end_date:
            query = query.filter(models.Transaction.transaction_date <= end_date)
        
        if search:
            search_term = f"%{search}%"
            query = query.filter(
                or_(
                    models.Transaction.beneficiary.ilike(search_term),
                    models.Transaction.notes.ilike(search_term)
                )
            )
        
        if min_amount is not None:
            query = query.filter(models.Transaction.amount >= min_amount)
        
        if max_amount is not None:
            query = query.filter(models.Transaction.amount <= max_amount)
        
        # Get total count before pagination
        total = query.count()
        
        # Apply pagination and ordering
        transactions = query.order_by(
            models.Transaction.transaction_date.desc(),
            models.Transaction.id.desc()
        ).offset(pagination["offset"]).limit(pagination["limit"]).all()
        
        # Format response
        formatted_transactions = []
        for t in transactions:
            formatted_transactions.append({
                "id": t.id,
                "transaction_date": t.transaction_date.isoformat(),
                "beneficiary": t.beneficiary,
                "amount": float(t.amount),
                "category": t.category,
                "subcategory": getattr(t, 'subcategory', None),
                "labels": getattr(t, 'labels', []),
                "tags": getattr(t, 'tags', []),
                "notes": t.notes,
                "is_private": getattr(t, 'is_private', False),
                "created_at": t.created_at.isoformat() if hasattr(t, 'created_at') and t.created_at else None,
                "updated_at": t.updated_at.isoformat() if hasattr(t, 'updated_at') and t.updated_at else None
            })
        
        return {
            "transactions": formatted_transactions,
            "total": total,
            "offset": pagination["offset"],
            "limit": pagination["limit"],
            "filters_applied": {
                "category": category,
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None,
                "search": search,
                "min_amount": min_amount,
                "max_amount": max_amount
            }
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve transactions: {str(e)}"
        )

@router.get("/{transaction_id}")
async def get_transaction(
    transaction_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific transaction by ID."""
    
    transaction = db.query(models.Transaction).filter(
        models.Transaction.id == transaction_id,
        models.Transaction.owner_id == current_user.id
    ).first()
    
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    return {
        "id": transaction.id,
        "transaction_date": transaction.transaction_date.isoformat(),
        "beneficiary": transaction.beneficiary,
        "amount": float(transaction.amount),
        "category": transaction.category,
        "subcategory": getattr(transaction, 'subcategory', None),
        "labels": getattr(transaction, 'labels', []),
        "tags": getattr(transaction, 'tags', []),
        "notes": transaction.notes,
        "is_private": getattr(transaction, 'is_private', False),
        "created_at": transaction.created_at.isoformat() if hasattr(transaction, 'created_at') and transaction.created_at else None,
        "updated_at": transaction.updated_at.isoformat() if hasattr(transaction, 'updated_at') and transaction.updated_at else None
    }

# ===== TRANSACTION CREATION =====

@router.post("/")
async def create_transaction(
    transaction_data: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new transaction."""
    
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
        
        # Create transaction
        transaction = models.Transaction(
            transaction_date=transaction_date,
            beneficiary=transaction_data["beneficiary"],
            amount=Decimal(str(transaction_data["amount"])),
            category=transaction_data.get("category"),
            subcategory=transaction_data.get("subcategory"),
            labels=transaction_data.get("labels", []),
            tags=transaction_data.get("tags", []),
            notes=transaction_data.get("notes"),
            is_private=transaction_data.get("is_private", False),
            owner_id=current_user.id
        )
        
        db.add(transaction)
        db.commit()
        db.refresh(transaction)
        
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
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create transaction: {str(e)}"
        )

# ===== TRANSACTION UPDATES =====

@router.put("/{transaction_id}")
async def update_transaction(
    transaction_id: int,
    transaction_data: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update an existing transaction."""
    
    transaction = db.query(models.Transaction).filter(
        models.Transaction.id == transaction_id,
        models.Transaction.owner_id == current_user.id
    ).first()
    
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    try:
        # Update fields
        for field, value in transaction_data.items():
            if field == "transaction_date" and isinstance(value, str):
                value = datetime.fromisoformat(value).date()
            elif field == "amount":
                value = Decimal(str(value))
            
            if hasattr(transaction, field):
                setattr(transaction, field, value)
        
        # Update timestamp if available
        if hasattr(transaction, 'updated_at'):
            transaction.updated_at = datetime.utcnow()
        
        db.commit()
        
        return {
            "id": transaction.id,
            "message": "Transaction updated successfully",
            "updated_fields": list(transaction_data.keys())
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update transaction: {str(e)}"
        )

# ===== TRANSACTION DELETION =====

@router.delete("/{transaction_id}")
async def delete_transaction(
    transaction_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a transaction."""
    
    transaction = db.query(models.Transaction).filter(
        models.Transaction.id == transaction_id,
        models.Transaction.owner_id == current_user.id
    ).first()
    
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    try:
        db.delete(transaction)
        db.commit()
        
        return {
            "message": "Transaction deleted successfully",
            "transaction_id": transaction_id
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete transaction: {str(e)}"
        )

# ===== BULK OPERATIONS =====

@router.post("/bulk-delete")
async def bulk_delete_transactions(
    transaction_ids: List[int],
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete multiple transactions at once."""
    
    try:
        deleted_count = db.query(models.Transaction).filter(
            models.Transaction.id.in_(transaction_ids),
            models.Transaction.owner_id == current_user.id
        ).delete(synchronize_session=False)
        
        db.commit()
        
        return {
            "message": f"Deleted {deleted_count} transactions",
            "deleted_count": deleted_count,
            "requested_count": len(transaction_ids)
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Bulk delete failed: {str(e)}"
        )

@router.post("/bulk-categorize")
async def bulk_categorize_transactions(
    categorize_data: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Bulk update category for multiple transactions."""
    
    transaction_ids = categorize_data.get("transaction_ids", [])
    new_category = categorize_data.get("category")
    
    if not transaction_ids or not new_category:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="transaction_ids and category are required"
        )
    
    try:
        updated_count = db.query(models.Transaction).filter(
            models.Transaction.id.in_(transaction_ids),
            models.Transaction.owner_id == current_user.id
        ).update({"category": new_category}, synchronize_session=False)
        
        db.commit()
        
        return {
            "message": f"Updated {updated_count} transactions",
            "updated_count": updated_count,
            "new_category": new_category
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Bulk categorization failed: {str(e)}"
        )

# ===== STATISTICS =====

@router.get("/stats/summary")
async def get_transaction_summary(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None)
):
    """Get transaction summary statistics."""
    
    try:
        # Build base query
        query = db.query(models.Transaction).filter(
            models.Transaction.owner_id == current_user.id
        )
        
        # Apply date filters
        if start_date:
            query = query.filter(models.Transaction.transaction_date >= start_date)
        if end_date:
            query = query.filter(models.Transaction.transaction_date <= end_date)
        
        # Get basic stats
        total_transactions = query.count()
        total_amount = db.query(func.sum(models.Transaction.amount)).filter(
            models.Transaction.owner_id == current_user.id
        ).scalar() or 0
        
        # Category breakdown
        category_stats = db.query(
            models.Transaction.category,
            func.count(models.Transaction.id).label('count'),
            func.sum(models.Transaction.amount).label('total_amount')
        ).filter(
            models.Transaction.owner_id == current_user.id
        ).group_by(models.Transaction.category).all()
        
        # Monthly breakdown (last 12 months)
        twelve_months_ago = datetime.utcnow().date() - timedelta(days=365)
        monthly_stats = db.query(
            func.strftime('%Y-%m', models.Transaction.transaction_date).label('month'),
            func.count(models.Transaction.id).label('count'),
            func.sum(models.Transaction.amount).label('total_amount')
        ).filter(
            models.Transaction.owner_id == current_user.id,
            models.Transaction.transaction_date >= twelve_months_ago
        ).group_by(func.strftime('%Y-%m', models.Transaction.transaction_date)).all()
        
        return {
            "total_transactions": total_transactions,
            "total_amount": float(total_amount),
            "date_range": {
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None
            },
            "category_breakdown": [
                {
                    "category": stat.category or "Uncategorized",
                    "count": stat.count,
                    "total_amount": float(stat.total_amount or 0)
                }
                for stat in category_stats
            ],
            "monthly_breakdown": [
                {
                    "month": stat.month,
                    "count": stat.count,
                    "total_amount": float(stat.total_amount or 0)
                }
                for stat in monthly_stats
            ]
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate summary: {str(e)}"
        )

# ===== EXPORT =====

@router.get("/export/csv")
async def export_transactions_csv(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None)
):
    """Export transactions as CSV."""
    
    try:
        # Build query with filters
        query = db.query(models.Transaction).filter(
            models.Transaction.owner_id == current_user.id
        )
        
        if start_date:
            query = query.filter(models.Transaction.transaction_date >= start_date)
        if end_date:
            query = query.filter(models.Transaction.transaction_date <= end_date)
        
        transactions = query.order_by(models.Transaction.transaction_date.desc()).all()
        
        # Generate CSV content
        csv_headers = ["Date", "Beneficiary", "Amount", "Category", "Notes"]
        csv_rows = []
        
        for t in transactions:
            csv_rows.append([
                t.transaction_date.isoformat(),
                t.beneficiary,
                str(t.amount),
                t.category or "",
                t.notes or ""
            ])
        
        return {
            "filename": f"transactions_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv",
            "headers": csv_headers,
            "rows": csv_rows,
            "total_transactions": len(csv_rows),
            "date_range": {
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None
            }
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Export failed: {str(e)}"
        )

# ===== DEBUG ENDPOINTS =====

@router.get("/debug/recent")
async def debug_recent_transactions(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(10, description="Number of recent transactions to show")
):
    """Debug endpoint to see recent transactions."""
    
    try:
        transactions = db.query(models.Transaction).filter(
            models.Transaction.owner_id == current_user.id
        ).order_by(models.Transaction.transaction_date.desc()).limit(limit).all()
        
        return {
            "recent_transactions": [
                {
                    "id": t.id,
                    "date": t.transaction_date.isoformat(),
                    "beneficiary": t.beneficiary,
                    "amount": float(t.amount),
                    "category": t.category
                }
                for t in transactions
            ],
            "count": len(transactions)
        }
        
    except Exception as e:
        return {
            "recent_transactions": [],
            "count": 0,
            "error": str(e)
        }