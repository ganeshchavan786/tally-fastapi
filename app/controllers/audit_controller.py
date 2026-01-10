"""
Audit Trail Controller
=======================
API endpoints for viewing and managing audit trail data.

ENDPOINTS:
----------
GET  /api/audit/history         - Get audit history with filters
GET  /api/audit/record/{table}/{guid} - Get history of specific record
GET  /api/audit/session/{id}    - Get changes from sync session
GET  /api/audit/deleted         - Get deleted records
GET  /api/audit/stats           - Get audit statistics
POST /api/audit/restore/{id}    - Restore a deleted record
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from ..services.audit_service import audit_service
from ..services.database_service import database_service
from ..utils.logger import logger
import json

router = APIRouter(prefix="/api/audit", tags=["Audit Trail"])


@router.get("/history")
async def get_audit_history(
    table_name: Optional[str] = Query(None, description="Filter by table name"),
    record_guid: Optional[str] = Query(None, description="Filter by record GUID"),
    action: Optional[str] = Query(None, description="Filter by action (INSERT/UPDATE/DELETE)"),
    company: Optional[str] = Query(None, description="Filter by company"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    limit: int = Query(100, ge=1, le=1000, description="Max records to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination")
):
    """
    Get audit history with optional filters.
    
    Examples:
    - /api/audit/history?action=DELETE - All deletes
    - /api/audit/history?table_name=mst_ledger - All ledger changes
    - /api/audit/history?company=MyCompany&start_date=2026-01-01
    """
    try:
        records = await audit_service.get_audit_history(
            table_name=table_name,
            record_guid=record_guid,
            action=action,
            company=company,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset
        )
        
        # Parse JSON fields
        for record in records:
            if record.get("old_data"):
                record["old_data"] = json.loads(record["old_data"])
            if record.get("new_data"):
                record["new_data"] = json.loads(record["new_data"])
            if record.get("changed_fields"):
                record["changed_fields"] = json.loads(record["changed_fields"])
        
        return {
            "count": len(records),
            "limit": limit,
            "offset": offset,
            "records": records
        }
    except Exception as e:
        logger.error(f"Error getting audit history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/record/{table_name}/{record_guid}")
async def get_record_history(table_name: str, record_guid: str):
    """
    Get complete history of a specific record.
    
    Shows all INSERT, UPDATE, DELETE actions for this record.
    """
    try:
        records = await audit_service.get_record_history(table_name, record_guid)
        
        # Parse JSON fields
        for record in records:
            if record.get("old_data"):
                record["old_data"] = json.loads(record["old_data"])
            if record.get("new_data"):
                record["new_data"] = json.loads(record["new_data"])
            if record.get("changed_fields"):
                record["changed_fields"] = json.loads(record["changed_fields"])
        
        return {
            "table_name": table_name,
            "record_guid": record_guid,
            "history_count": len(records),
            "history": records
        }
    except Exception as e:
        logger.error(f"Error getting record history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/session/{session_id}")
async def get_sync_session_changes(session_id: str):
    """
    Get all changes from a specific sync session.
    
    Useful for reviewing what happened during a particular sync.
    """
    try:
        result = await audit_service.get_sync_session_changes(session_id)
        
        # Parse JSON fields in changes
        for record in result.get("changes", []):
            if record.get("old_data"):
                record["old_data"] = json.loads(record["old_data"])
            if record.get("new_data"):
                record["new_data"] = json.loads(record["new_data"])
            if record.get("changed_fields"):
                record["changed_fields"] = json.loads(record["changed_fields"])
        
        return result
    except Exception as e:
        logger.error(f"Error getting session changes: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/deleted")
async def get_deleted_records(
    table_name: Optional[str] = Query(None, description="Filter by table name"),
    company: Optional[str] = Query(None, description="Filter by company"),
    include_restored: bool = Query(False, description="Include already restored records"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """
    Get deleted records that can be restored.
    
    These records were deleted during sync because they no longer exist in Tally.
    """
    try:
        records = await audit_service.get_deleted_records(
            table_name=table_name,
            company=company,
            include_restored=include_restored,
            limit=limit,
            offset=offset
        )
        
        # Parse JSON data
        for record in records:
            if record.get("record_data"):
                record["record_data"] = json.loads(record["record_data"])
        
        return {
            "count": len(records),
            "records": records
        }
    except Exception as e:
        logger.error(f"Error getting deleted records: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_audit_stats(company: Optional[str] = Query(None)):
    """
    Get audit statistics.
    
    Shows counts by action type, by table, and pending deleted records.
    """
    try:
        stats = await audit_service.get_audit_stats(company)
        return stats
    except Exception as e:
        logger.error(f"Error getting audit stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/restore/{deleted_id}")
async def restore_deleted_record(deleted_id: int):
    """
    Restore a deleted record back to its original table.
    
    This will:
    1. Get the record data from deleted_records
    2. Insert it back into the original table
    3. Mark the deleted_record as restored
    """
    try:
        # Get the deleted record
        query = "SELECT * FROM deleted_records WHERE id = ? AND is_restored = 0"
        record = await database_service.fetch_one(query, (deleted_id,))
        
        if not record:
            raise HTTPException(status_code=404, detail="Deleted record not found or already restored")
        
        table_name = record["table_name"]
        record_data = json.loads(record["record_data"])
        
        # Build insert query
        columns = list(record_data.keys())
        placeholders = ", ".join(["?" for _ in columns])
        column_names = ", ".join(columns)
        
        insert_query = f"INSERT OR REPLACE INTO {table_name} ({column_names}) VALUES ({placeholders})"
        values = [record_data[col] for col in columns]
        
        # Insert the record
        await database_service.execute(insert_query, tuple(values))
        
        # Mark as restored
        update_query = "UPDATE deleted_records SET is_restored = 1, restored_at = CURRENT_TIMESTAMP WHERE id = ?"
        await database_service.execute(update_query, (deleted_id,))
        
        # Log the restore action
        await audit_service.log_insert(
            table_name=table_name,
            record_guid=record["record_guid"],
            record_name=record.get("record_name", ""),
            new_data=record_data,
            company=record["company"]
        )
        
        logger.info(f"Restored record {record['record_guid']} to {table_name}")
        
        return {
            "status": "success",
            "message": f"Record restored to {table_name}",
            "table_name": table_name,
            "record_guid": record["record_guid"],
            "record_name": record.get("record_name")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error restoring record: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions")
async def get_recent_sessions(
    limit: int = Query(20, ge=1, le=100),
    company: Optional[str] = Query(None)
):
    """
    Get list of recent sync sessions with summary.
    """
    try:
        query = """
            SELECT 
                sync_session_id,
                sync_type,
                company,
                MIN(created_at) as started_at,
                MAX(created_at) as ended_at,
                COUNT(*) as total_changes,
                SUM(CASE WHEN action = 'INSERT' THEN 1 ELSE 0 END) as inserts,
                SUM(CASE WHEN action = 'UPDATE' THEN 1 ELSE 0 END) as updates,
                SUM(CASE WHEN action = 'DELETE' THEN 1 ELSE 0 END) as deletes
            FROM audit_log
            WHERE sync_session_id IS NOT NULL
        """
        params = []
        
        if company:
            query += " AND company = ?"
            params.append(company)
        
        query += " GROUP BY sync_session_id ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        
        sessions = await database_service.fetch_all(query, tuple(params))
        
        return {
            "count": len(sessions),
            "sessions": sessions
        }
    except Exception as e:
        logger.error(f"Error getting sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e))
