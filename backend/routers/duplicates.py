# backend/routers/duplicates.py
# Fixed duplicates router with proper imports and error handling

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
        # Fallback: Basic duplicate detection without DuplicateDetector
        try:
            transactions = db.query(models.Transaction).filter(
                models.Transaction.owner_id == current_user.id
            ).all()
            
            # Simple duplicate detection: same amount + beneficiary + date within 3 days
            potential_duplicates = []
            seen_combinations = {}
            
            for txn in transactions:
                # Create a key for similar transactions
                date_key = txn.transaction_date.strftime("%Y-%m-%d")
                key = f"{abs(float(txn.amount))}_{txn.beneficiary.lower().strip()}"
                
                if key in seen_combinations:
                    # Check if dates are within 3 days
                    existing_txn = seen_combinations[key]
                    date_diff = abs((txn.transaction_date - existing_txn.transaction_date).days)
                    
                    if date_diff <= 3:
                        potential_duplicates.append({
                            "original": existing_txn,
                            "duplicate": txn,
                            "confidence": 0.8 if date_diff == 0 else 0.6
                        })
                else:
                    seen_combinations[key] = txn
            
            groups_found = len(potential_duplicates)
            total_duplicates = groups_found * 2 if groups_found > 0 else 0
            
            return {
                "message": "Basic duplicate scan completed",
                "groups_found": groups_found,
                "total_duplicates": total_duplicates,
                "scan_timestamp": datetime.utcnow().isoformat(),
                "method": "basic_detection"
            }
            
        except Exception as e:
            return {
                "message": "Duplicate scan failed",
                "error": str(e),
                "groups_found": 0,
                "total_duplicates": 0
            }
    
    # Full duplicate detection with DuplicateDetector
    try:
        detector = DuplicateDetector(db)
        
        # Check if recent scan exists and force_rescan is False
        recent_scan_cutoff = datetime.utcnow() - timedelta(hours=1)
        
        if not force_rescan:
            recent_scan = db.query(models.DuplicateGroup).filter(
                models.DuplicateGroup.user_id == current_user.id,
                models.DuplicateGroup.created_at >= recent_scan_cutoff
            ).first()
            
            if recent_scan:
                return {
                    "message": "Recent scan found, use force_rescan=true to override",
                    "groups_found": 0,
                    "total_duplicates": 0,
                    "last_scan": recent_scan.created_at.isoformat()
                }
        
        # Run detection
        scan_result = await detector.scan_user_transactions(current_user.id)
        
        return {
            "message": "Duplicate scan completed",
            "groups_found": scan_result.get("groups_created", 0),
            "total_duplicates": scan_result.get("total_duplicates", 0),
            "scan_timestamp": datetime.utcnow().isoformat(),
            "detection_methods_used": scan_result.get("methods_used", [])
        }
        
    except Exception as e:
        return {
            "message": "Duplicate scan failed",
            "error": str(e),
            "groups_found": 0,
            "total_duplicates": 0
        }

# ===== DUPLICATE GROUPS =====

@router.get("/")
async def get_duplicate_groups(
    limit: int = Query(50, ge=1, le=1000, description="Number of groups to return"),
    offset: int = Query(0, ge=0, description="Number of groups to skip"),
    status_filter: Optional[str] = Query(None, description="Filter by status: pending, resolved, ignored"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get duplicate transaction groups for the current user."""
    
    try:
        # Build base query - graceful handling if DuplicateGroup doesn't exist
        try:
            query = db.query(models.DuplicateGroup).filter(
                models.DuplicateGroup.user_id == current_user.id
            )
        except Exception:
            # DuplicateGroup model doesn't exist
            return {
                "duplicate_groups": [],
                "total": 0,
                "offset": offset,
                "limit": limit,
                "message": "Duplicate detection models not available"
            }
        
        # Apply status filter if provided
        if status_filter:
            try:
                status_enum = getattr(models.DuplicateStatus, status_filter.upper())
                query = query.filter(models.DuplicateGroup.status == status_enum)
            except AttributeError:
                pass  # Invalid status, ignore filter
        
        # Get groups with pagination
        groups = query.order_by(
            models.DuplicateGroup.created_at.desc()
        ).offset(offset).limit(limit).all()
        
        # Get total count
        total = query.count()
        
        # Format response
        formatted_groups = []
        for group in groups:
            try:
                # Get entries for this group
                entries = db.query(models.DuplicateEntry).filter(
                    models.DuplicateEntry.group_id == group.id
                ).all()
                
                # Get actual transaction details
                transactions = []
                for entry in entries:
                    transaction = db.query(models.Transaction).filter(
                        models.Transaction.id == entry.transaction_id
                    ).first()
                    
                    if transaction:
                        transactions.append({
                            "id": transaction.id,
                            "transaction_date": transaction.transaction_date.isoformat(),
                            "beneficiary": transaction.beneficiary,
                            "amount": float(transaction.amount),
                            "category": transaction.category,
                            "is_primary": entry.is_primary,
                            "confidence": float(entry.confidence_score)
                        })
                
                formatted_groups.append({
                    "id": group.id,
                    "detection_method": group.detection_method,
                    "confidence_score": float(group.confidence_score),
                    "status": group.status.value if hasattr(group.status, 'value') else str(group.status),
                    "created_at": group.created_at.isoformat(),
                    "resolved_at": group.resolved_at.isoformat() if group.resolved_at else None,
                    "transaction_count": len(transactions),
                    "transactions": transactions
                })
            except Exception as e:
                # Skip problematic groups
                continue
        
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

@router.get("/{group_id}")
async def get_duplicate_group(
    group_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get details for a specific duplicate group."""
    
    try:
        group = db.query(models.DuplicateGroup).filter(
            models.DuplicateGroup.id == group_id,
            models.DuplicateGroup.user_id == current_user.id
        ).first()
        
        if not group:
            raise HTTPException(status_code=404, detail="Duplicate group not found")
        
        # Get entries and transaction details
        entries = db.query(models.DuplicateEntry).filter(
            models.DuplicateEntry.group_id == group.id
        ).all()
        
        transactions = []
        for entry in entries:
            transaction = db.query(models.Transaction).filter(
                models.Transaction.id == entry.transaction_id
            ).first()
            
            if transaction:
                transactions.append({
                    "id": transaction.id,
                    "transaction_date": transaction.transaction_date.isoformat(),
                    "beneficiary": transaction.beneficiary,
                    "amount": float(transaction.amount),
                    "category": transaction.category,
                    "is_private": transaction.is_private,
                    "is_primary": entry.is_primary,
                    "confidence": float(entry.confidence_score)
                })
        
        return {
            "id": group.id,
            "detection_method": group.detection_method,
            "confidence_score": float(group.confidence_score),
            "status": group.status.value if hasattr(group.status, 'value') else str(group.status),
            "created_at": group.created_at.isoformat(),
            "resolved_at": group.resolved_at.isoformat() if group.resolved_at else None,
            "resolution_action": group.resolution_action,
            "transaction_count": len(transactions),
            "transactions": transactions
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving group: {str(e)}")

# ===== DUPLICATE RESOLUTION =====

@router.post("/{group_id}/resolve")
async def resolve_duplicate_group(
    group_id: int,
    resolution_data: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Resolve a duplicate group by keeping primary and removing duplicates."""
    
    try:
        group = db.query(models.DuplicateGroup).filter(
            models.DuplicateGroup.id == group_id,
            models.DuplicateGroup.user_id == current_user.id
        ).first()
        
        if not group:
            raise HTTPException(status_code=404, detail="Duplicate group not found")
        
        action = resolution_data.get("action", "keep_primary")
        resolved_count = 0
        
        # Get all entries in the group
        entries = db.query(models.DuplicateEntry).filter(
            models.DuplicateEntry.group_id == group.id
        ).all()
        
        if action == "delete_duplicates":
            # Delete all non-primary transactions
            for entry in entries:
                if not entry.is_primary:
                    transaction = db.query(models.Transaction).filter(
                        models.Transaction.id == entry.transaction_id
                    ).first()
                    
                    if transaction:
                        db.delete(transaction)
                        resolved_count += 1
        
        elif action == "delete_all":
            # Delete all transactions in the group
            for entry in entries:
                transaction = db.query(models.Transaction).filter(
                    models.Transaction.id == entry.transaction_id
                ).first()
                
                if transaction:
                    db.delete(transaction)
                    resolved_count += 1
        
        elif action == "keep_original":
            # Keep first transaction, delete others
            for i, entry in enumerate(entries):
                if i > 0:  # Keep first, delete rest
                    transaction = db.query(models.Transaction).filter(
                        models.Transaction.id == entry.transaction_id
                    ).first()
                    
                    if transaction:
                        db.delete(transaction)
                        resolved_count += 1
        
        # Keep_all requires no action - just mark as resolved
        
        # Update group status
        group.status = getattr(models.DuplicateStatus, 'RESOLVED', 'resolved')
        group.resolved_at = datetime.utcnow()
        group.resolution_action = action
        
        db.commit()
        
        return {
            "message": "Duplicate group resolved",
            "group_id": group_id,
            "action": action,
            "transactions_removed": resolved_count
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Resolution failed: {str(e)}")

@router.post("/{group_id}/ignore")
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
        
        group.status = getattr(models.DuplicateStatus, 'IGNORED', 'ignored')
        group.resolved_at = datetime.utcnow()
        group.resolution_action = "ignored"
        
        db.commit()
        
        return {
            "message": "Duplicate group ignored",
            "group_id": group_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ignore action failed: {str(e)}")

# ===== DUPLICATE STATISTICS =====

@router.get("/stats/")
async def get_duplicate_statistics(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get duplicate detection statistics for the user."""
    
    try:
        # Get total duplicate groups by status
        try:
            status_stats = db.query(
                models.DuplicateGroup.status,
                func.count(models.DuplicateGroup.id).label('count')
            ).filter(
                models.DuplicateGroup.user_id == current_user.id
            ).group_by(models.DuplicateGroup.status).all()
        except Exception:
            status_stats = []
        
        # Get detection method breakdown
        try:
            method_stats = db.query(
                models.DuplicateGroup.detection_method,
                func.count(models.DuplicateGroup.id).label('count')
            ).filter(
                models.DuplicateGroup.user_id == current_user.id
            ).group_by(models.DuplicateGroup.detection_method).all()
        except Exception:
            method_stats = []
        
        # Calculate potential savings
        total_duplicate_entries = 0
        potential_savings = 0.0
        
        try:
            resolved_groups = db.query(models.DuplicateGroup).filter(
                models.DuplicateGroup.user_id == current_user.id,
                models.DuplicateGroup.status == getattr(models.DuplicateStatus, 'RESOLVED', 'resolved')
            ).all()
            
            for group in resolved_groups:
                try:
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
                except Exception:
                    continue
        except Exception:
            pass
        
        # Get recent activity (last 30 days)
        recent_date = datetime.utcnow() - timedelta(days=30)
        
        try:
            recent_groups = db.query(func.count(models.DuplicateGroup.id)).filter(
                models.DuplicateGroup.user_id == current_user.id,
                models.DuplicateGroup.created_at >= recent_date
            ).scalar() or 0
        except Exception:
            recent_groups = 0
        
        try:
            recent_resolutions = db.query(func.count(models.DuplicateGroup.id)).filter(
                models.DuplicateGroup.user_id == current_user.id,
                models.DuplicateGroup.resolved_at >= recent_date
            ).scalar() or 0
        except Exception:
            recent_resolutions = 0
        
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
            "detection_methods": [],
            "total_groups": 0,
            "total_duplicates_found": 0,
            "potential_savings": 0.0,
            "recent_activity": {
                "groups_found_30d": 0,
                "groups_resolved_30d": 0
            },
            "error": str(e)
        }

# ===== DEBUG ENDPOINTS =====

@router.get("/debug/status")
async def debug_duplicate_detection_status():
    """Debug endpoint to check duplicate detection system status."""
    
    return {
        "duplicate_detector_available": DUPLICATE_DETECTOR_AVAILABLE,
        "features": {
            "basic_scanning": True,  # Always available with fallback
            "advanced_scanning": DUPLICATE_DETECTOR_AVAILABLE,
            "group_management": True,
            "statistics": True,
            "resolution": True
        },
        "recommendations": [
            "Install DuplicateDetector for advanced features" if not DUPLICATE_DETECTOR_AVAILABLE else "Full duplicate detection available"
        ],
        "endpoints_available": [
            "/scan/ - Scan for duplicates",
            "/ - Get duplicate groups",
            "/{group_id} - Get group details", 
            "/{group_id}/resolve - Resolve duplicates",
            "/{group_id}/ignore - Ignore false positives",
            "/stats/ - Get statistics"
        ]
    }