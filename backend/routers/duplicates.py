# backend/routers/duplicates.py
# Fixed duplicates router with proper imports

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta

from .. import models
from ..dependencies import get_current_user, get_db

# Try to import DuplicateDetector (graceful degradation if missing)
try:
    from ..duplicate_detector import DuplicateDetector
    DUPLICATE_DETECTOR_AVAILABLE = True
except ImportError:
    DUPLICATE_DETECTOR_AVAILABLE = False

router = APIRouter()

# ===== DUPLICATE DETECTION =====

@router.post("/scan/")
async def scan_for_duplicates(
    force_rescan: bool = Query(False, description="Force rescan even if recent scan exists"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Scan for duplicate transactions using multiple detection methods."""
    
    if not DUPLICATE_DETECTOR_AVAILABLE:
        return {
            "message": "Duplicate detection not available",
            "error": "DuplicateDetector class not found",
            "groups_found": 0,
            "scan_type": "unavailable"
        }
    
    try:
        detector = DuplicateDetector(current_user.id, db)
        
        # Check if recent scan exists (unless forced)
        if not force_rescan:
            try:
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
            except:
                # If DuplicateGroup model doesn't exist, continue with new scan
                pass
        
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
    db: Session = Depends(get_db)
):
    """Get duplicate groups with optional filtering."""
    
    if not DUPLICATE_DETECTOR_AVAILABLE:
        return {
            "duplicate_groups": [],
            "total": 0,
            "offset": offset,
            "limit": limit,
            "message": "Duplicate detection not available"
        }
    
    try:
        # Build query
        query = db.query(models.DuplicateGroup).filter(
            models.DuplicateGroup.user_id == current_user.id
        )
        
        # Apply status filter if provided
        if status_filter:
            query = query.filter(models.DuplicateGroup.status == status_filter)
        
        # Get groups with pagination
        groups = query.order_by(
            models.DuplicateGroup.created_at.desc()
        ).offset(offset).limit(limit).all()
        
        # Get total count
        total = query.count()
        
        # Format response
        formatted_groups = []
        for group in groups:
            # Get entries for this group
            entries = db.query(models.DuplicateEntry).filter(
                models.DuplicateEntry.group_id == group.id
            ).all()
            
            formatted_groups.append({
                "id": group.id,
                "detection_method": group.detection_method,
                "confidence_score": float(group.confidence_score),
                "status": group.status.value if hasattr(group.status, 'value') else str(group.status),
                "created_at": group.created_at.isoformat(),
                "resolved_at": group.resolved_at.isoformat() if group.resolved_at else None,
                "transaction_count": len(entries),
                "transactions": [
                    {
                        "id": entry.transaction_id,
                        "is_primary": entry.is_primary,
                        "confidence": float(entry.confidence_score)
                    }
                    for entry in entries
                ]
            })
        
        return {
            "duplicate_groups": formatted_groups,
            "total": total,
            "offset": offset,
            "limit": limit
        }
        
    except Exception as e:
        return {
            "duplicate_groups": [],
            "total": 0,
            "offset": offset,
            "limit": limit,
            "error": str(e)
        }

@router.post("/groups/{group_id}/resolve")
async def resolve_duplicate_group(
    group_id: int,
    resolution_data: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Resolve a duplicate group by keeping primary and removing duplicates."""
    
    if not DUPLICATE_DETECTOR_AVAILABLE:
        return {
            "message": "Duplicate resolution not available",
            "error": "DuplicateDetector class not found"
        }
    
    try:
        # Get duplicate group
        group = db.query(models.DuplicateGroup).filter(
            models.DuplicateGroup.id == group_id,
            models.DuplicateGroup.user_id == current_user.id
        ).first()
        
        if not group:
            raise HTTPException(status_code=404, detail="Duplicate group not found")
        
        # Get resolution action
        action = resolution_data.get("action", "keep_primary")  # keep_primary, keep_all, delete_all
        primary_transaction_id = resolution_data.get("primary_transaction_id")
        
        # Get entries
        entries = db.query(models.DuplicateEntry).filter(
            models.DuplicateEntry.group_id == group_id
        ).all()
        
        resolved_count = 0
        
        if action == "keep_primary":
            # Mark primary if specified
            if primary_transaction_id:
                for entry in entries:
                    entry.is_primary = (entry.transaction_id == primary_transaction_id)
            
            # Delete non-primary transactions
            for entry in entries:
                if not entry.is_primary:
                    # Delete the actual transaction
                    transaction = db.query(models.Transaction).filter(
                        models.Transaction.id == entry.transaction_id,
                        models.Transaction.owner_id == current_user.id
                    ).first()
                    
                    if transaction:
                        db.delete(transaction)
                        resolved_count += 1
        
        elif action == "delete_all":
            # Delete all transactions in the group
            for entry in entries:
                transaction = db.query(models.Transaction).filter(
                    models.Transaction.id == entry.transaction_id,
                    models.Transaction.owner_id == current_user.id
                ).first()
                
                if transaction:
                    db.delete(transaction)
                    resolved_count += 1
        
        # Keep_all requires no action - just mark as resolved
        
        # Update group status
        group.status = models.DuplicateStatus.RESOLVED
        group.resolved_at = datetime.utcnow()
        group.resolution_action = action
        
        db.commit()
        
        return {
            "message": "Duplicate group resolved",
            "group_id": group_id,
            "action": action,
            "transactions_removed": resolved_count
        }
        
    except Exception as e:
        return {
            "message": "Resolution failed",
            "error": str(e),
            "group_id": group_id
        }

@router.post("/groups/{group_id}/ignore")
async def ignore_duplicate_group(
    group_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mark a duplicate group as ignored (false positive)."""
    
    try:
        group = db.query(models.DuplicateGroup).filter(
            models.DuplicateGroup.id == group_id,
            models.DuplicateGroup.user_id == current_user.id
        ).first()
        
        if not group:
            raise HTTPException(status_code=404, detail="Duplicate group not found")
        
        group.status = models.DuplicateStatus.IGNORED
        group.resolved_at = datetime.utcnow()
        group.resolution_action = "ignored"
        
        db.commit()
        
        return {
            "message": "Duplicate group ignored",
            "group_id": group_id
        }
        
    except Exception as e:
        return {
            "message": "Ignore action failed",
            "error": str(e),
            "group_id": group_id
        }

# ===== DUPLICATE STATISTICS =====

@router.get("/stats/")
async def get_duplicate_statistics(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get duplicate detection statistics for the user."""
    
    if not DUPLICATE_DETECTOR_AVAILABLE:
        return {
            "status_breakdown": [],
            "total_groups": 0,
            "total_duplicates_found": 0,
            "potential_savings": 0.0,
            "message": "Duplicate detection not available"
        }
    
    try:
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
                {"status": stat.status.value if hasattr(stat.status, 'value') else str(stat.status), "count": stat.count}
                for stat in status_stats
            ],
            "detection_methods": [
                {"method": stat.detection_method, "count": stat.count}
                for stat in method_stats
            ],
            "total_groups": sum(stat.count for stat in status_stats),
            "total_duplicates_found": total_duplicate_entries,
            "potential_savings": potential_savings,
            "recent_activity": {
                "groups_found_30d": recent_groups,
                "groups_resolved_30d": recent_resolutions
            }
        }
        
    except Exception as e:
        return {
            "status_breakdown": [],
            "total_groups": 0,
            "total_duplicates_found": 0,
            "potential_savings": 0.0,
            "error": str(e)
        }

# ===== DEBUG ENDPOINTS =====

@router.get("/debug/status")
async def debug_duplicate_detection_status():
    """Debug endpoint to check duplicate detection system status."""
    
    return {
        "duplicate_detector_available": DUPLICATE_DETECTOR_AVAILABLE,
        "features": {
            "basic_scanning": DUPLICATE_DETECTOR_AVAILABLE,
            "group_management": DUPLICATE_DETECTOR_AVAILABLE,
            "statistics": DUPLICATE_DETECTOR_AVAILABLE,
            "resolution": DUPLICATE_DETECTOR_AVAILABLE
        },
        "recommendations": [
            "Complete DuplicateDetector implementation" if not DUPLICATE_DETECTOR_AVAILABLE else "Duplicate detection ready"
        ]
    }