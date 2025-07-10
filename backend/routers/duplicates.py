# backend/routers/duplicates.py
# Advanced duplicate detection and management endpoints

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import Dict, List, Optional, Any
from datetime import datetime

from .. import models
from ..duplicate_detector import DuplicateDetector

router = APIRouter()

async def get_current_user(db: Session = Depends(models.get_db)):
    """Dependency to get current user - simplified for this example."""
    # In production, this would validate JWT token and return actual user
    return db.query(models.User).first()

# ===== DUPLICATE DETECTION =====

@router.get("/scan/")
async def scan_for_duplicates(
    force_rescan: bool = Query(False, description="Force rescan even if recent scan exists"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Scan for duplicate transactions using multiple detection methods."""
    
    try:
        detector = DuplicateDetector(current_user.id, db)
        
        # Check if recent scan exists (unless forced)
        if not force_rescan:
            recent_scan = db.query(models.DuplicateGroup).filter(
                models.DuplicateGroup.user_id == current_user.id,
                models.DuplicateGroup.created_at >= datetime.utcnow().replace(hour=0, minute=0, second=0)
            ).first()
            
            if recent_scan:
                # Get existing results
                existing_groups = await detector.get_duplicate_groups(models.DuplicateStatus.PENDING)
                return {
                    "scan_type": "existing",
                    "message": "Using existing scan results from today",
                    "groups_found": len(existing_groups),
                    "groups": existing_groups,
                    "scan_timestamp": recent_scan.created_at.isoformat()
                }
        
        # Perform new scan
        duplicate_groups = await detector.find_all_duplicates()
        
        return {
            "scan_type": "new",
            "message": "Duplicate scan completed",
            "groups_found": len(duplicate_groups),
            "groups": duplicate_groups,
            "scan_timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Duplicate scan failed: {str(e)}"
        )

@router.get("/groups/")
async def get_duplicate_groups(
    status_filter: Optional[str] = Query(None, description="Filter by status: pending, resolved, ignored"),
    limit: int = Query(50, description="Maximum number of groups to return"),
    offset: int = Query(0, description="Number of groups to skip"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Get duplicate groups with optional filtering."""
    
    try:
        detector = DuplicateDetector(current_user.id, db)
        
        # Convert string status to enum if provided
        status_enum = None
        if status_filter:
            try:
                status_enum = models.DuplicateStatus(status_filter.lower())
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid status filter: {status_filter}"
                )
        
        # Get groups
        all_groups = await detector.get_duplicate_groups(status_enum)
        
        # Apply pagination
        total_groups = len(all_groups)
        paginated_groups = all_groups[offset:offset + limit]
        
        return {
            "total": total_groups,
            "offset": offset,
            "limit": limit,
            "groups": paginated_groups
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get duplicate groups: {str(e)}"
        )

@router.get("/groups/{group_id}")
async def get_duplicate_group_details(
    group_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Get detailed information about a specific duplicate group."""
    
    group = db.query(models.DuplicateGroup).filter(
        models.DuplicateGroup.id == group_id,
        models.DuplicateGroup.user_id == current_user.id
    ).first()
    
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Duplicate group not found"
        )
    
    # Get entries with full transaction details
    entries = db.query(models.DuplicateEntry).filter(
        models.DuplicateEntry.group_id == group_id
    ).all()
    
    transactions = []
    for entry in entries:
        transaction = db.query(models.Transaction).filter(
            models.Transaction.id == entry.transaction_id
        ).first()
        
        if transaction:
            transactions.append({
                "id": transaction.id,
                "date": transaction.transaction_date.isoformat(),
                "beneficiary": transaction.beneficiary,
                "amount": float(transaction.amount),
                "category": transaction.category,
                "description": transaction.description,
                "created_at": transaction.created_at.isoformat(),
                "is_primary": entry.is_primary,
                "similarity_details": entry.similarity_details,
                "raw_data": transaction.raw_data
            })
    
    return {
        "id": group.id,
        "similarity_score": group.similarity_score,
        "detection_method": group.detection_method,
        "status": group.status.value,
        "created_at": group.created_at.isoformat(),
        "resolved_at": group.resolved_at.isoformat() if group.resolved_at else None,
        "resolution_notes": group.resolution_notes,
        "transaction_count": len(transactions),
        "transactions": transactions
    }

# ===== DUPLICATE RESOLUTION =====

@router.post("/groups/{group_id}/resolve")
async def resolve_duplicate_group(
    group_id: int,
    resolution_data: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Resolve a duplicate group by merging, deleting, or ignoring."""
    
    resolution_type = resolution_data.get("resolution")
    keep_transaction_id = resolution_data.get("keep_transaction_id")
    notes = resolution_data.get("notes", "")
    
    if not resolution_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Resolution type is required"
        )
    
    valid_resolutions = ["merge", "ignore", "delete_all"]
    if resolution_type not in valid_resolutions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid resolution type. Must be one of: {', '.join(valid_resolutions)}"
        )
    
    try:
        detector = DuplicateDetector(current_user.id, db)
        result = await detector.resolve_duplicate_group(
            group_id, resolution_type, keep_transaction_id
        )
        
        # Update resolution notes
        group = db.query(models.DuplicateGroup).filter(
            models.DuplicateGroup.id == group_id
        ).first()
        
        if group and notes:
            group.resolution_notes = notes
            db.commit()
        
        return {
            "group_id": group_id,
            "resolution": result,
            "message": f"Duplicate group {resolution_type}d successfully"
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Resolution failed: {str(e)}"
        )

@router.post("/groups/{group_id}/set-primary")
async def set_primary_transaction(
    group_id: int,
    transaction_data: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Set which transaction should be the primary (kept) transaction in a group."""
    
    transaction_id = transaction_data.get("transaction_id")
    if not transaction_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transaction ID is required"
        )
    
    # Verify group exists and belongs to user
    group = db.query(models.DuplicateGroup).filter(
        models.DuplicateGroup.id == group_id,
        models.DuplicateGroup.user_id == current_user.id
    ).first()
    
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Duplicate group not found"
        )
    
    # Verify transaction is in this group
    entry = db.query(models.DuplicateEntry).filter(
        models.DuplicateEntry.group_id == group_id,
        models.DuplicateEntry.transaction_id == transaction_id
    ).first()
    
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transaction is not part of this duplicate group"
        )
    
    # Clear all primary flags for this group
    db.query(models.DuplicateEntry).filter(
        models.DuplicateEntry.group_id == group_id
    ).update({"is_primary": False})
    
    # Set the new primary
    entry.is_primary = True
    
    db.commit()
    
    return {
        "message": "Primary transaction updated successfully",
        "group_id": group_id,
        "primary_transaction_id": transaction_id
    }

@router.post("/groups/bulk-resolve")
async def bulk_resolve_duplicate_groups(
    bulk_data: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Bulk resolve multiple duplicate groups."""
    
    group_ids = bulk_data.get("group_ids", [])
    resolution_type = bulk_data.get("resolution")
    
    if not group_ids or not resolution_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Group IDs and resolution type are required"
        )
    
    valid_resolutions = ["merge", "ignore", "delete_all"]
    if resolution_type not in valid_resolutions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid resolution type. Must be one of: {', '.join(valid_resolutions)}"
        )
    
    try:
        detector = DuplicateDetector(current_user.id, db)
        results = []
        
        for group_id in group_ids:
            try:
                result = await detector.resolve_duplicate_group(group_id, resolution_type)
                results.append({
                    "group_id": group_id,
                    "success": True,
                    "result": result
                })
            except Exception as e:
                results.append({
                    "group_id": group_id,
                    "success": False,
                    "error": str(e)
                })
        
        successful_resolutions = sum(1 for r in results if r["success"])
        
        return {
            "total_groups": len(group_ids),
            "successful_resolutions": successful_resolutions,
            "failed_resolutions": len(group_ids) - successful_resolutions,
            "resolution_type": resolution_type,
            "results": results
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Bulk resolution failed: {str(e)}"
        )

# ===== SETTINGS AND PREFERENCES =====

@router.get("/settings/")
async def get_duplicate_detection_settings(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Get current duplicate detection settings for the user."""
    
    detector = DuplicateDetector(current_user.id, db)
    
    return {
        "settings": detector.preferences,
        "default_settings": {
            "amount_tolerance": 0.01,
            "date_range_days": 3,
            "beneficiary_similarity_threshold": 0.8
        },
        "description": {
            "amount_tolerance": "Maximum amount difference to consider duplicates (in currency units)",
            "date_range_days": "Maximum days between transactions to consider duplicates",
            "beneficiary_similarity_threshold": "Minimum similarity score (0-1) for beneficiary matching"
        }
    }

@router.put("/settings/")
async def update_duplicate_detection_settings(
    settings_data: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Update duplicate detection settings for the user."""
    
    # Validate settings
    valid_keys = ["amount_tolerance", "date_range_days", "beneficiary_similarity_threshold"]
    invalid_keys = [key for key in settings_data.keys() if key not in valid_keys]
    
    if invalid_keys:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid settings keys: {', '.join(invalid_keys)}"
        )
    
    # Validate ranges
    if "amount_tolerance" in settings_data:
        if not 0 <= settings_data["amount_tolerance"] <= 100:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="amount_tolerance must be between 0 and 100"
            )
    
    if "date_range_days" in settings_data:
        if not 0 <= settings_data["date_range_days"] <= 30:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="date_range_days must be between 0 and 30"
            )
    
    if "beneficiary_similarity_threshold" in settings_data:
        if not 0 <= settings_data["beneficiary_similarity_threshold"] <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="beneficiary_similarity_threshold must be between 0 and 1"
            )
    
    try:
        detector = DuplicateDetector(current_user.id, db)
        updated_preferences = await detector.update_detection_preferences(settings_data)
        
        return {
            "message": "Settings updated successfully",
            "updated_settings": updated_preferences
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update settings: {str(e)}"
        )

# ===== STATISTICS AND ANALYTICS =====

@router.get("/stats/")
async def get_duplicate_statistics(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Get duplicate detection statistics and analytics."""
    
    # Get total duplicate groups by status
    status_stats = db.query(
        models.DuplicateGroup.status,
        func.count(models.DuplicateGroup.id).label('count')
    ).filter(
        models.DuplicateGroup.user_id == current_user.id
    ).group_by(models.DuplicateGroup.status).all()
    
    # Get detection method breakdown
    method_stats = db.query(
        models.DuplicateGroup.detection_method,
        func.count(models.DuplicateGroup.id).label('count')
    ).filter(
        models.DuplicateGroup.user_id == current_user.id
    ).group_by(models.DuplicateGroup.detection_method).all()
    
    # Get resolution statistics
    resolved_groups = db.query(models.DuplicateGroup).filter(
        models.DuplicateGroup.user_id == current_user.id,
        models.DuplicateGroup.status == models.DuplicateStatus.RESOLVED
    ).all()
    
    # Calculate potential savings (amount of duplicates resolved)
    total_duplicate_entries = 0
    potential_savings = 0.0
    
    for group in resolved_groups:
        entries = db.query(models.DuplicateEntry).filter(
            models.DuplicateEntry.group_id == group.id
        ).all()
        
        duplicate_count = len(entries) - 1  # Subtract 1 for the kept transaction
        total_duplicate_entries += duplicate_count
        
        # Calculate amount saved (sum of non-primary transactions)
        for entry in entries:
            if not entry.is_primary:
                transaction = db.query(models.Transaction).filter(
                    models.Transaction.id == entry.transaction_id
                ).first()
                if transaction:
                    potential_savings += abs(float(transaction.amount))
    
    # Get recent activity (last 30 days)
    from datetime import timedelta
    recent_date = datetime.utcnow() - timedelta(days=30)
    
    recent_groups = db.query(func.count(models.DuplicateGroup.id)).filter(
        models.DuplicateGroup.user_id == current_user.id,
        models.DuplicateGroup.created_at >= recent_date
    ).scalar() or 0
    
    recent_resolutions = db.query(func.count(models.DuplicateGroup.id)).filter(
        models.DuplicateGroup.user_id == current_user.id,
        models.DuplicateGroup.resolved_at >= recent_date
    ).scalar() or 0
    
    return {
        "status_breakdown": [
            {"status": stat.status.value, "count": stat.count}
            for stat in status_stats
        ],
        "detection_methods": [
            {"method": stat.detection_method, "count": stat.count}
            for stat in method_stats
        ],
        "resolution_stats": {
            "total_resolved_groups": len(resolved_groups),
            "total_duplicate_transactions_removed": total_duplicate_entries,
            "potential_amount_saved": potential_savings
        },
        "recent_activity": {
            "new_groups_last_30_days": recent_groups,
            "resolutions_last_30_days": recent_resolutions
        },
        "summary": {
            "total_groups": sum(stat.count for stat in status_stats),
            "pending_groups": next((stat.count for stat in status_stats if stat.status == models.DuplicateStatus.PENDING), 0),
            "resolution_rate": (len(resolved_groups) / max(1, sum(stat.count for stat in status_stats))) * 100
        }
    }

@router.get("/export/")
async def export_duplicate_report(
    format: str = Query("json", description="Export format: json, csv"),
    status_filter: Optional[str] = Query(None, description="Filter by status"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(models.get_db)
):
    """Export duplicate detection report."""
    
    if format not in ["json", "csv"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Format must be 'json' or 'csv'"
        )
    
    try:
        detector = DuplicateDetector(current_user.id, db)
        
        # Convert string status to enum if provided
        status_enum = None
        if status_filter:
            try:
                status_enum = models.DuplicateStatus(status_filter.lower())
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid status filter: {status_filter}"
                )
        
        groups = await detector.get_duplicate_groups(status_enum)
        
        if format == "json":
            return {
                "export_timestamp": datetime.utcnow().isoformat(),
                "total_groups": len(groups),
                "status_filter": status_filter,
                "groups": groups
            }
        
        elif format == "csv":
            # For CSV, we'll flatten the data
            csv_data = []
            for group in groups:
                for transaction in group["transactions"]:
                    csv_data.append({
                        "group_id": group["id"],
                        "similarity_score": group["similarity_score"],
                        "detection_method": group["detection_method"],
                        "status": group["status"],
                        "transaction_id": transaction["id"],
                        "date": transaction["date"],
                        "beneficiary": transaction["beneficiary"],
                        "amount": transaction["amount"],
                        "category": transaction["category"],
                        "is_primary": transaction["is_primary"]
                    })
            
            return {
                "format": "csv",
                "data": csv_data,
                "export_timestamp": datetime.utcnow().isoformat()
            }
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Export failed: {str(e)}"
        )