"""
Audit Trail Service
====================
Handles all audit trail logging for sync operations.

FEATURES:
---------
1. Log INSERT, UPDATE, DELETE actions during sync
2. Store full record data for recovery
3. Async logging (doesn't block main sync)
4. Sync session grouping for easy tracking

USAGE:
------
from app.services.audit_service import audit_service

# Log an insert
await audit_service.log_insert(table, guid, name, new_data, company)

# Log an update
await audit_service.log_update(table, guid, name, old_data, new_data, company)

# Log a delete
await audit_service.log_delete(table, guid, name, old_data, company)
"""

import json
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional
from uuid import uuid4

from .database_service import database_service
from ..utils.logger import logger


class AuditService:
    """Service for audit trail logging"""
    
    def __init__(self):
        self.current_session_id: Optional[str] = None
        self.current_sync_type: Optional[str] = None
        self.current_company: Optional[str] = None
        self._queue: List[Dict] = []
        self._is_processing = False
    
    def start_session(self, sync_type: str, company: str) -> str:
        """Start a new audit session for a sync operation"""
        self.current_session_id = f"{sync_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
        self.current_sync_type = sync_type
        self.current_company = company
        logger.info(f"Audit session started: {self.current_session_id}")
        return self.current_session_id
    
    def end_session(self):
        """End the current audit session"""
        if self.current_session_id:
            logger.info(f"Audit session ended: {self.current_session_id}")
        self.current_session_id = None
        self.current_sync_type = None
        self.current_company = None
    
    async def log_insert(
        self,
        table_name: str,
        record_guid: str,
        record_name: str,
        new_data: Dict[str, Any],
        company: Optional[str] = None,
        tally_alter_id: Optional[int] = None
    ) -> None:
        """Log an INSERT action"""
        await self._log_action(
            action="INSERT",
            table_name=table_name,
            record_guid=record_guid,
            record_name=record_name,
            old_data=None,
            new_data=new_data,
            company=company or self.current_company,
            tally_alter_id=tally_alter_id
        )
    
    async def log_update(
        self,
        table_name: str,
        record_guid: str,
        record_name: str,
        old_data: Dict[str, Any],
        new_data: Dict[str, Any],
        company: Optional[str] = None,
        tally_alter_id: Optional[int] = None
    ) -> None:
        """Log an UPDATE action with old and new values"""
        # Find changed fields
        changed_fields = []
        for key, new_val in new_data.items():
            old_val = old_data.get(key)
            if old_val != new_val:
                changed_fields.append(key)
        
        await self._log_action(
            action="UPDATE",
            table_name=table_name,
            record_guid=record_guid,
            record_name=record_name,
            old_data=old_data,
            new_data=new_data,
            changed_fields=changed_fields,
            company=company or self.current_company,
            tally_alter_id=tally_alter_id
        )
    
    async def log_delete(
        self,
        table_name: str,
        record_guid: str,
        record_name: str,
        old_data: Dict[str, Any],
        company: Optional[str] = None
    ) -> None:
        """Log a DELETE action and store full record for recovery"""
        company = company or self.current_company
        
        # Log to audit_log
        await self._log_action(
            action="DELETE",
            table_name=table_name,
            record_guid=record_guid,
            record_name=record_name,
            old_data=old_data,
            new_data=None,
            company=company
        )
        
        # Store in deleted_records for recovery
        await self._store_deleted_record(
            table_name=table_name,
            record_guid=record_guid,
            record_name=record_name,
            record_data=old_data,
            company=company
        )
    
    async def _log_action(
        self,
        action: str,
        table_name: str,
        record_guid: str,
        record_name: str,
        old_data: Optional[Dict],
        new_data: Optional[Dict],
        company: str,
        changed_fields: Optional[List[str]] = None,
        tally_alter_id: Optional[int] = None
    ) -> None:
        """Internal method to log an action to audit_log table"""
        try:
            query = """
                INSERT INTO audit_log 
                (sync_session_id, sync_type, table_name, record_guid, record_name, 
                 action, old_data, new_data, changed_fields, company, tally_alter_id, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'SUCCESS')
            """
            params = (
                self.current_session_id,
                self.current_sync_type,
                table_name,
                record_guid,
                record_name,
                action,
                json.dumps(old_data) if old_data else None,
                json.dumps(new_data) if new_data else None,
                json.dumps(changed_fields) if changed_fields else None,
                company,
                tally_alter_id
            )
            
            await database_service.execute(query, params)
            
        except Exception as e:
            logger.error(f"Failed to log audit action: {e}")
    
    async def _store_deleted_record(
        self,
        table_name: str,
        record_guid: str,
        record_name: str,
        record_data: Dict[str, Any],
        company: str
    ) -> None:
        """Store deleted record for potential recovery"""
        try:
            query = """
                INSERT INTO deleted_records 
                (table_name, record_guid, record_name, record_data, company, sync_session_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """
            params = (
                table_name,
                record_guid,
                record_name,
                json.dumps(record_data),
                company,
                self.current_session_id
            )
            
            await database_service.execute(query, params)
            
        except Exception as e:
            logger.error(f"Failed to store deleted record: {e}")
    
    async def get_audit_history(
        self,
        table_name: Optional[str] = None,
        record_guid: Optional[str] = None,
        action: Optional[str] = None,
        company: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict]:
        """Get audit history with filters"""
        query = "SELECT * FROM audit_log WHERE 1=1"
        params = []
        
        if table_name:
            query += " AND table_name = ?"
            params.append(table_name)
        
        if record_guid:
            query += " AND record_guid = ?"
            params.append(record_guid)
        
        if action:
            query += " AND action = ?"
            params.append(action.upper())
        
        if company:
            query += " AND company = ?"
            params.append(company)
        
        if start_date:
            query += " AND created_at >= ?"
            params.append(start_date)
        
        if end_date:
            query += " AND created_at <= ?"
            params.append(end_date)
        
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        return await database_service.fetch_all(query, tuple(params))
    
    async def get_deleted_records(
        self,
        table_name: Optional[str] = None,
        company: Optional[str] = None,
        include_restored: bool = False,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict]:
        """Get deleted records for potential recovery"""
        query = "SELECT * FROM deleted_records WHERE 1=1"
        params = []
        
        if not include_restored:
            query += " AND is_restored = 0"
        
        if table_name:
            query += " AND table_name = ?"
            params.append(table_name)
        
        if company:
            query += " AND company = ?"
            params.append(company)
        
        query += " ORDER BY deleted_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        return await database_service.fetch_all(query, tuple(params))
    
    async def get_record_history(self, table_name: str, record_guid: str) -> List[Dict]:
        """Get complete history of a specific record"""
        query = """
            SELECT * FROM audit_log 
            WHERE table_name = ? AND record_guid = ?
            ORDER BY created_at DESC
        """
        return await database_service.fetch_all(query, (table_name, record_guid))
    
    async def get_sync_session_changes(self, session_id: str) -> Dict[str, Any]:
        """Get all changes from a specific sync session"""
        query = """
            SELECT action, COUNT(*) as count 
            FROM audit_log 
            WHERE sync_session_id = ?
            GROUP BY action
        """
        summary = await database_service.fetch_all(query, (session_id,))
        
        query = """
            SELECT * FROM audit_log 
            WHERE sync_session_id = ?
            ORDER BY created_at
        """
        details = await database_service.fetch_all(query, (session_id,))
        
        return {
            "session_id": session_id,
            "summary": {row["action"]: row["count"] for row in summary},
            "total_changes": len(details),
            "changes": details
        }
    
    async def get_audit_stats(self, company: Optional[str] = None) -> Dict[str, Any]:
        """Get audit statistics"""
        base_query = "FROM audit_log"
        params = []
        
        if company:
            base_query += " WHERE company = ?"
            params.append(company)
        
        # Total counts by action
        query = f"SELECT action, COUNT(*) as count {base_query} GROUP BY action"
        action_counts = await database_service.fetch_all(query, tuple(params))
        
        # Total counts by table
        query = f"SELECT table_name, COUNT(*) as count {base_query} GROUP BY table_name ORDER BY count DESC LIMIT 10"
        table_counts = await database_service.fetch_all(query, tuple(params))
        
        # Deleted records count
        del_query = "SELECT COUNT(*) as count FROM deleted_records WHERE is_restored = 0"
        if company:
            del_query += " AND company = ?"
        deleted_count = await database_service.fetch_one(del_query, tuple(params) if company else ())
        
        return {
            "by_action": {row["action"]: row["count"] for row in action_counts},
            "by_table": {row["table_name"]: row["count"] for row in table_counts},
            "pending_deleted_records": deleted_count.get("count", 0) if deleted_count else 0
        }


# Singleton instance
audit_service = AuditService()
