"""
Sync Service Module
====================
Orchestrates data synchronization between Tally and SQLite.

ARCHITECTURE:
------------
This is the main sync orchestration service that coordinates:
1. TallyService - HTTP communication with Tally Gateway
2. DatabaseService - SQLite database operations
3. XMLBuilder - TDL XML request generation

SYNC TYPES:
-----------
1. FULL SYNC (full_sync):
   - Truncates all data for the company
   - Fetches ALL records from Tally
   - Use for: Initial sync, data corruption recovery

2. INCREMENTAL SYNC (incremental_sync):
   - Uses GUID + AlterID comparison (Node.js style)
   - Only fetches changed records
   - Detects: Added, Modified, Deleted records
   - Use for: Regular updates, faster sync

MULTI-COMPANY SUPPORT:
---------------------
- Each record has _company column
- Sync is company-specific (doesn't affect other companies)
- Queue service handles sequential multi-company sync

DATA FLOW:
---------
1. API Request → SyncService
2. SyncService → XMLBuilder (generate TDL XML)
3. XMLBuilder → TallyService (send to Tally)
4. TallyService → Parse XML response
5. SyncService → DatabaseService (bulk insert)

KEY TABLES:
----------
- company_config: Stores per-company sync metadata (AlterID, last_sync, etc.)
- _diff: Temporary table for GUID+AlterID comparison
- _delete: Temporary table for tracking records to delete

DEVELOPER NOTES:
---------------
- Always verify Tally connection before truncating data
- Use _process_diff_for_primary_tables() for delete detection
- AlterID filter ($AlterID > X) fetches only changed records
- Cascade delete handles related table cleanup
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import config
from ..utils.logger import logger
from ..utils.decorators import timed
from ..utils.constants import SyncStatus, MASTER_TABLES, TRANSACTION_TABLES
from ..utils.helpers import parse_tally_date, parse_tally_amount, parse_tally_boolean
from .tally_service import tally_service
from .database_service import database_service
from .xml_builder import xml_builder
from .audit_service import audit_service

# Sync state file for crash recovery
SYNC_STATE_FILE = Path("sync_state.json")


class SyncService:
    """Service for synchronizing data from Tally to SQLite"""
    
    def __init__(self):
        self.status = SyncStatus.IDLE
        self.progress = 0
        self.current_table = ""
        self.rows_processed = 0
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.error_message: Optional[str] = None
        self._cancel_requested = False
        self.current_company: str = ""  # For multi-company sync
    
    def get_status(self) -> Dict[str, Any]:
        """Get current sync status"""
        return {
            "status": self.status,
            "progress": self.progress,
            "current_table": self.current_table,
            "rows_processed": self.rows_processed,
            "current_company": self.current_company,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error_message": self.error_message
        }
    
    def cancel(self) -> bool:
        """Request sync cancellation"""
        if self.status == SyncStatus.RUNNING:
            self._cancel_requested = True
            logger.info("Sync cancellation requested")
            return True
        return False
    
    @timed
    async def full_sync(self, company: str = "", parallel: bool = False) -> Dict[str, Any]:
        """Perform full data synchronization for a specific company
        
        Args:
            company: Company name to sync (empty = active company in Tally)
            parallel: If True, fetch all tables from Tally simultaneously (3-5x faster)
        """
        if self.status == SyncStatus.RUNNING:
            return {"error": "Sync already in progress"}
        
        self._reset_status()
        self.status = SyncStatus.RUNNING
        self.started_at = datetime.now()
        self.current_company = company or config.tally.company
        sync_history_id = None
        
        # Set company in config for Tally requests
        if company:
            config.tally.company = company
        
        logger.info(f"Starting full sync for company: {self.current_company or 'Default'}")
        logger.info(f"Config company set to: {config.tally.company}")
        
        try:
            # Connect to database
            await database_service.connect()
            
            # Create tables if not exist
            logger.info("Creating database tables...")
            await database_service.create_tables()
            
            # Save sync history - started
            sync_history_id = await self._save_sync_history("full", "running")
            
            # Save sync state for crash recovery
            self._save_sync_state("full", "initializing", 0)
            
            # Verify Tally connection and company data before truncating
            # This prevents data loss if Tally returns empty response
            logger.info("Verifying Tally connection before truncate...")
            test_table = xml_builder.get_master_tables()[0] if xml_builder.get_master_tables() else None
            if test_table:
                test_rows = await self._extract_table_data(test_table)
                if not test_rows:
                    error_msg = f"Tally returned 0 rows for {test_table.get('name')}. Company may not be active in Tally. Aborting sync to prevent data loss."
                    logger.error(error_msg)
                    self.status = SyncStatus.FAILED
                    self.error_message = error_msg
                    await self._update_sync_history(sync_history_id, "failed", error_msg)
                    return self.get_status()
                logger.info(f"Tally verification passed: {len(test_rows)} rows from {test_table.get('name')}")
            
            # Truncate only current company's data (not all data)
            logger.info(f"Truncating data for company: {self.current_company}...")
            await database_service.truncate_all_tables(company=self.current_company)
            
            # Update config table BEFORE data sync (like Node.js)
            # This ensures company info is saved even if sync fails
            logger.info("Updating config table before sync...")
            await self._update_config_table()
            
            # Sync master data
            logger.info(f"Syncing master data... (parallel={parallel})")
            self._save_sync_state("full", "master_data", self.rows_processed)
            await self._sync_master_data(parallel=parallel)
            
            if self._cancel_requested:
                self.status = SyncStatus.CANCELLED
                await self._update_sync_history(sync_history_id, "cancelled")
                return self.get_status()
            
            # Sync transaction data
            logger.info(f"Syncing transaction data... (parallel={parallel})")
            self._save_sync_state("full", "transaction_data", self.rows_processed)
            await self._sync_transaction_data(parallel=parallel)
            
            if self._cancel_requested:
                self.status = SyncStatus.CANCELLED
                await self._update_sync_history(sync_history_id, "cancelled")
                self._clear_sync_state()
                return self.get_status()
            
            self.status = SyncStatus.COMPLETED
            self.completed_at = datetime.now()
            self.progress = 100
            
            # Update config table with sync info
            await self._update_config_table()
            
            # Update sync history - completed
            await self._update_sync_history(sync_history_id, "completed")
            
            # Clear sync state on success
            self._clear_sync_state()
            
            logger.info(f"Full sync completed. Total rows: {self.rows_processed}")
            return self.get_status()
            
        except Exception as e:
            self.status = SyncStatus.FAILED
            self.error_message = str(e)
            if sync_history_id:
                await self._update_sync_history(sync_history_id, "failed", str(e))
            logger.error(f"Sync failed: {e}")
            return self.get_status()
        finally:
            await database_service.disconnect()
    
    @timed
    async def incremental_sync(self, company: str = "") -> Dict[str, Any]:
        """Perform incremental data synchronization using GUID+AlterID diff comparison (Node.js style)"""
        if self.status == SyncStatus.RUNNING:
            return {"error": "Sync already in progress"}
        
        self._reset_status()
        self.status = SyncStatus.RUNNING
        self.started_at = datetime.now()
        self.current_company = company or config.tally.company
        sync_history_id = None
        
        # Set company in config for Tally requests
        if company:
            config.tally.company = company
        
        logger.info(f"Starting incremental sync for company: {self.current_company or 'Default'}")
        logger.info(f"Config company set to: {config.tally.company}")
        
        # Start audit session
        audit_service.start_session("incremental", self.current_company)
        
        try:
            # Reload config for incremental mode
            xml_builder.reload_config(incremental=True)
            
            # Connect to database
            await database_service.connect()
            
            # Create tables if not exist (with incremental schema)
            logger.info("Creating database tables (incremental schema)...")
            await database_service.create_tables(incremental=True)
            
            # Ensure _diff and _delete tables exist
            await database_service.ensure_company_config_table()
            
            # Save sync history - started
            sync_history_id = await self._save_sync_history("incremental", "running")
            
            # Get last sync alterid from database
            last_alterid_master = await self._get_last_alterid()
            last_alterid_transaction = await self._get_last_alterid_transaction()
            logger.info(f"Last sync AlterID - Master: {last_alterid_master}, Transaction: {last_alterid_transaction}")
            
            # Update config table BEFORE data sync (like Node.js)
            logger.info("Updating config table before sync...")
            await self._update_config_table()
            
            # Get current AlterID from Tally
            current_alterid_master = await self._get_current_alterid_from_tally("master")
            current_alterid_transaction = await self._get_current_alterid_from_tally("transaction")
            logger.info(f"Current Tally AlterID - Master: {current_alterid_master}, Transaction: {current_alterid_transaction}")
            
            # Check if anything changed
            master_changed = current_alterid_master != last_alterid_master
            transaction_changed = current_alterid_transaction != last_alterid_transaction
            
            if not master_changed and not transaction_changed:
                logger.info("No changes detected in Tally")
                self.status = SyncStatus.COMPLETED
                self.completed_at = datetime.now()
                self.progress = 100
                await self._update_sync_history(sync_history_id, "completed")
                return self.get_status()
            
            # Process Primary tables for diff comparison (deleted/modified records)
            if master_changed:
                logger.info("Processing master data diff...")
                await self._process_diff_for_primary_tables("master", last_alterid_master)
            
            if transaction_changed:
                logger.info("Processing transaction data diff...")
                await self._process_diff_for_primary_tables("transaction", last_alterid_transaction)
            
            if self._cancel_requested:
                self.status = SyncStatus.CANCELLED
                await self._update_sync_history(sync_history_id, "cancelled")
                return self.get_status()
            
            # Import new/modified records with AlterID filter
            if master_changed:
                logger.info("Importing changed master data...")
                await self._import_changed_records("master", last_alterid_master)
            
            if transaction_changed:
                logger.info("Importing changed transaction data...")
                await self._import_changed_records("transaction", last_alterid_transaction)
            
            if self._cancel_requested:
                self.status = SyncStatus.CANCELLED
                await self._update_sync_history(sync_history_id, "cancelled")
                return self.get_status()
            
            self.status = SyncStatus.COMPLETED
            self.completed_at = datetime.now()
            self.progress = 100
            
            # Update config table with sync info
            await self._update_config_table()
            
            # Update sync history - completed
            await self._update_sync_history(sync_history_id, "completed")
            
            logger.info(f"Incremental sync completed. Total rows: {self.rows_processed}")
            return self.get_status()
            
        except Exception as e:
            self.status = SyncStatus.FAILED
            self.error_message = str(e)
            if sync_history_id:
                await self._update_sync_history(sync_history_id, "failed", str(e))
            logger.error(f"Incremental sync failed: {e}")
            return self.get_status()
        finally:
            # End audit session
            audit_service.end_session()
            await database_service.disconnect()
    
    async def _get_last_alterid(self) -> int:
        """Get last sync alterid from company_config table for current company"""
        try:
            if self.current_company:
                result = await database_service.fetch_one(
                    "SELECT last_alter_id_master FROM company_config WHERE company_name = ?",
                    (self.current_company,)
                )
                if result:
                    return int(result.get("last_alter_id_master", 0) or 0)
            # Fallback to config table
            result = await database_service.fetch_one(
                "SELECT value FROM config WHERE name = 'Last AlterID Master'"
            )
            if result:
                return int(result.get("value", 0) or 0)
        except Exception as e:
            logger.warning(f"Could not get last alterid: {e}")
        return 0
    
    async def _get_last_alterid_transaction(self) -> int:
        """Get last sync transaction alterid from company_config table"""
        try:
            if self.current_company:
                result = await database_service.fetch_one(
                    "SELECT last_alter_id_transaction FROM company_config WHERE company_name = ?",
                    (self.current_company,)
                )
                if result:
                    return int(result.get("last_alter_id_transaction", 0) or 0)
            # Fallback to config table
            result = await database_service.fetch_one(
                "SELECT value FROM config WHERE name = 'Last AlterID Transaction'"
            )
            if result:
                return int(result.get("value", 0) or 0)
        except Exception as e:
            logger.warning(f"Could not get last transaction alterid: {e}")
        return 0
    
    async def _get_current_alterid_from_tally(self, data_type: str = "master") -> int:
        """Get current AlterID from Tally company info"""
        try:
            company_info = await tally_service.get_company_info()
            if data_type == "master":
                return int(company_info.get("alter_id", 0) or 0)
            else:
                # For transaction, use the same alterid for now
                return int(company_info.get("alter_id", 0) or 0)
        except Exception as e:
            logger.warning(f"Could not get current alterid from Tally: {e}")
        return 0
    
    async def _process_diff_for_primary_tables(self, data_type: str, last_alterid: int) -> None:
        """Process diff for Primary tables - find deleted/modified records using GUID+AlterID comparison"""
        if data_type == "master":
            tables = xml_builder.get_master_tables()
        else:
            tables = xml_builder.get_transaction_tables()
        
        # Filter only Primary nature tables
        primary_tables = [t for t in tables if t.get("nature") == "Primary"]
        
        for table_config in primary_tables:
            table_name = table_config.get("name", "")
            collection = table_config.get("collection", "")
            filters = table_config.get("filters", [])
            
            logger.info(f"  Processing diff for {table_name}...")
            
            try:
                # Step 1: Truncate _diff and _delete tables
                await database_service.execute("DELETE FROM _diff")
                await database_service.execute("DELETE FROM _delete")
                
                # Step 2: Fetch GUID + AlterID from Tally into _diff table
                diff_config = {
                    "name": "_diff",
                    "collection": collection,
                    "fields": [
                        {"name": "guid", "field": "Guid", "type": "text"},
                        {"name": "alterid", "field": "AlterId", "type": "text"}
                    ],
                    "fetch": ["AlterId"],
                    "filters": filters
                }
                
                diff_rows = await self._extract_table_data(diff_config)
                if diff_rows:
                    # Insert into _diff table
                    for row in diff_rows:
                        await database_service.execute(
                            "INSERT OR REPLACE INTO _diff (guid, alterid) VALUES (?, ?)",
                            (row.get("guid", ""), str(row.get("alterid", "")))
                        )
                    logger.info(f"    Fetched {len(diff_rows)} records from Tally for diff")
                
                # Step 3: Find deleted records (guid in DB but not in _diff)
                await database_service.execute(f"""
                    INSERT OR IGNORE INTO _delete 
                    SELECT guid FROM {table_name} 
                    WHERE guid NOT IN (SELECT guid FROM _diff)
                    AND _company = ?
                """, (self.current_company,))
                
                # Step 4: Find modified records (guid exists but alterid different)
                await database_service.execute(f"""
                    INSERT OR IGNORE INTO _delete 
                    SELECT t.guid FROM {table_name} t 
                    JOIN _diff d ON d.guid = t.guid 
                    WHERE d.alterid <> COALESCE(t.alterid, '')
                    AND t._company = ?
                """, (self.current_company,))
                
                # Step 5: Delete from main table (with audit logging)
                delete_result = await database_service.fetch_one("SELECT COUNT(*) as cnt FROM _delete")
                delete_count = delete_result.get("cnt", 0) if delete_result else 0
                
                if delete_count > 0:
                    # Fetch records to be deleted for audit trail
                    deleted_records = await database_service.fetch_all(f"""
                        SELECT * FROM {table_name} 
                        WHERE guid IN (SELECT guid FROM _delete)
                        AND _company = ?
                    """, (self.current_company,))
                    
                    # Log each delete to audit trail
                    for record in deleted_records:
                        await audit_service.log_delete(
                            table_name=table_name,
                            record_guid=record.get("guid", ""),
                            record_name=record.get("name", record.get("guid", "")),
                            old_data=dict(record),
                            company=self.current_company
                        )
                    
                    # Now delete from main table
                    await database_service.execute(f"""
                        DELETE FROM {table_name} 
                        WHERE guid IN (SELECT guid FROM _delete)
                        AND _company = ?
                    """, (self.current_company,))
                    logger.info(f"    Deleted {delete_count} modified/removed records from {table_name}")
                
                # Step 6: Cascade delete for related tables
                cascade_delete = table_config.get("cascade_delete", [])
                if cascade_delete and delete_count > 0:
                    for cascade in cascade_delete:
                        target_table = cascade.get("table", "")
                        target_field = cascade.get("field", "")
                        if target_table and target_field:
                            await database_service.execute(f"""
                                DELETE FROM {target_table} 
                                WHERE {target_field} IN (SELECT guid FROM _delete)
                            """)
                            logger.info(f"    Cascade deleted from {target_table}")
                
            except Exception as e:
                logger.error(f"    Failed to process diff for {table_name}: {e}")
    
    async def _import_changed_records(self, data_type: str, last_alterid: int) -> None:
        """Import new/modified records with AlterID filter"""
        if data_type == "master":
            tables = xml_builder.get_master_tables()
        else:
            tables = xml_builder.get_transaction_tables()
        
        total_tables = len(tables)
        
        for i, table_config in enumerate(tables):
            if self._cancel_requested:
                return
            
            table_name = table_config.get("name", "")
            self.current_table = table_name
            self.progress = int((i / total_tables) * 50) + 50  # 50-100%
            
            try:
                # Add AlterID filter
                table_config_with_filter = table_config.copy()
                if last_alterid > 0:
                    existing_filters = list(table_config_with_filter.get("filters", []) or [])
                    table_config_with_filter["filters"] = existing_filters + [f"$AlterID > {last_alterid}"]
                
                rows = await self._extract_table_data(table_config_with_filter)
                if rows:
                    # Add company name to rows
                    for row in rows:
                        row["_company"] = self.current_company
                    
                    # Audit trail: Log INSERT/UPDATE for each row
                    for row in rows:
                        guid = row.get("guid", "")
                        record_name = row.get("name", guid)
                        
                        # Check if record exists (UPDATE) or new (INSERT)
                        existing = await database_service.fetch_one(
                            f"SELECT * FROM {table_name} WHERE guid = ? AND _company = ?",
                            (guid, self.current_company)
                        )
                        
                        if existing:
                            # UPDATE - log with old and new data
                            await audit_service.log_update(
                                table_name=table_name,
                                record_guid=guid,
                                record_name=record_name,
                                old_data=dict(existing),
                                new_data=row,
                                company=self.current_company,
                                tally_alter_id=row.get("alterid")
                            )
                        else:
                            # INSERT - log new record
                            await audit_service.log_insert(
                                table_name=table_name,
                                record_guid=guid,
                                record_name=record_name,
                                new_data=row,
                                company=self.current_company,
                                tally_alter_id=row.get("alterid")
                            )
                    
                    # Use upsert (INSERT OR REPLACE)
                    count = await self._upsert_rows(table_name, rows)
                    self.rows_processed += count
                    logger.info(f"  {table_name}: imported {count} changed rows")
                else:
                    logger.info(f"  {table_name}: no changes")
            except Exception as e:
                logger.error(f"  {table_name}: failed - {e}")
    
    async def _update_last_alterid(self) -> None:
        """Update last alterid in config table after sync"""
        try:
            # Get max alterid from all tables
            max_alterid = 0
            for table in ["mst_group", "mst_ledger", "mst_vouchertype", "trn_voucher"]:
                try:
                    result = await database_service.fetch_one(f"SELECT MAX(alterid) as max_id FROM {table}")
                    if result and result.get("max_id"):
                        max_alterid = max(max_alterid, int(result.get("max_id", 0)))
                except:
                    pass
            
            # Upsert config value
            await database_service.execute(
                "INSERT OR REPLACE INTO config (name, value) VALUES ('last_alterid', ?)",
                (str(max_alterid),)
            )
            logger.info(f"Updated last_alterid to {max_alterid}")
        except Exception as e:
            logger.error(f"Failed to update last_alterid: {e}")
    
    
    async def _upsert_rows(self, table_name: str, rows: List[Dict]) -> int:
        """Insert or replace rows (upsert for incremental sync)"""
        if not rows:
            return 0
        
        columns = list(rows[0].keys())
        placeholders = ", ".join(["?" for _ in columns])
        column_names = ", ".join(columns)
        
        query = f"INSERT OR REPLACE INTO {table_name} ({column_names}) VALUES ({placeholders})"
        
        count = 0
        for row in rows:
            values = tuple(row.get(col) for col in columns)
            await database_service.execute(query, values)
            count += 1
        
        return count
    
    async def _sync_master_data(self, parallel: bool = False) -> None:
        """Sync all master data tables
        
        Args:
            parallel: If True, fetch all tables from Tally simultaneously (faster)
        """
        master_tables = xml_builder.get_master_tables()
        total_tables = len(master_tables) + len(xml_builder.get_transaction_tables())
        
        if parallel:
            await self._sync_tables_parallel(master_tables, 0, total_tables, "master")
        else:
            await self._sync_tables_sequential(master_tables, 0, total_tables)
    
    async def _sync_tables_sequential(self, tables: List[Dict], start_idx: int, total_tables: int) -> None:
        """Sync tables sequentially (original method)"""
        for i, table_config in enumerate(tables):
            if self._cancel_requested:
                return
            
            table_name = table_config.get("name", "")
            self.current_table = table_name
            self.progress = int(((start_idx + i) / total_tables) * 100)
            
            try:
                rows = await self._extract_table_data(table_config)
                if rows:
                    count = await database_service.bulk_insert(table_name, rows, self.current_company)
                    self.rows_processed += count
                    logger.info(f"  {table_name}: imported {count} rows for {self.current_company}")
                else:
                    logger.info(f"  {table_name}: imported 0 rows")
            except Exception as e:
                logger.error(f"  {table_name}: failed - {e}")
    
    async def _sync_tables_parallel(self, tables: List[Dict], start_idx: int, total_tables: int, data_type: str) -> None:
        """Sync tables in parallel - fetch all from Tally simultaneously
        
        PARALLEL SYNC FLOW:
        ------------------
        1. Create async tasks for all tables
        2. Fetch all tables from Tally simultaneously (asyncio.gather)
        3. Insert results into database sequentially
        
        This is ~3-5x faster than sequential for large number of tables.
        """
        logger.info(f"  Starting parallel fetch for {len(tables)} {data_type} tables...")
        
        async def fetch_table(table_config: Dict) -> tuple:
            """Fetch single table data from Tally"""
            table_name = table_config.get("name", "")
            try:
                rows = await self._extract_table_data(table_config)
                return (table_name, rows, None)
            except Exception as e:
                return (table_name, [], str(e))
        
        # Parallel fetch - all tables at once
        self.current_table = f"Fetching {len(tables)} tables..."
        tasks = [fetch_table(tc) for tc in tables]
        results = await asyncio.gather(*tasks)
        
        logger.info(f"  Parallel fetch complete. Inserting to database...")
        
        # Insert results sequentially (SQLite is single-writer)
        for i, (table_name, rows, error) in enumerate(results):
            if self._cancel_requested:
                return
            
            self.current_table = table_name
            self.progress = int(((start_idx + i) / total_tables) * 100)
            
            if error:
                logger.error(f"  {table_name}: failed - {error}")
                continue
            
            if rows:
                count = await database_service.bulk_insert(table_name, rows, self.current_company)
                self.rows_processed += count
                logger.info(f"  {table_name}: imported {count} rows for {self.current_company}")
            else:
                logger.info(f"  {table_name}: imported 0 rows")
    
    async def _sync_transaction_data(self, parallel: bool = False) -> None:
        """Sync all transaction data tables
        
        Args:
            parallel: If True, fetch all tables from Tally simultaneously (faster)
        """
        master_tables = xml_builder.get_master_tables()
        transaction_tables = xml_builder.get_transaction_tables()
        total_tables = len(master_tables) + len(transaction_tables)
        start_idx = len(master_tables)
        
        if parallel:
            await self._sync_tables_parallel(transaction_tables, start_idx, total_tables, "transaction")
        else:
            for i, table_config in enumerate(transaction_tables):
                if self._cancel_requested:
                    return
                
                table_name = table_config.get("name", "")
                self.current_table = table_name
                self.progress = int(((len(master_tables) + i) / total_tables) * 100)
                
                try:
                    rows = await self._extract_table_data(table_config)
                    if rows:
                        count = await database_service.bulk_insert(table_name, rows, self.current_company)
                        self.rows_processed += count
                        logger.info(f"  {table_name}: imported {count} rows for {self.current_company}")
                    else:
                        logger.info(f"  {table_name}: imported 0 rows")
                except Exception as e:
                    logger.error(f"  {table_name}: failed - {e}")
    
    async def _extract_table_data(self, table_config: Dict) -> List[Dict[str, Any]]:
        """Extract data for a specific table from Tally"""
        table_name = table_config.get("name", "")
        fields = table_config.get("fields", [])
        
        if not fields:
            return []
        
        try:
            # Build XML request using xml_builder
            xml_request = xml_builder.build_export_xml(table_config)
            
            # Send request to Tally
            response = await tally_service.send_xml(xml_request)
            
            # Debug: log response length
            logger.debug(f"{table_name}: Response length = {len(response)} chars")
            
            # Parse response - extract field names from config
            field_names = [f.get("name", "") for f in fields]
            rows = self._parse_xml_response(response, field_names, fields)
            
            logger.debug(f"{table_name}: Parsed {len(rows)} rows")
            
            return rows
        except Exception as e:
            logger.error(f"Failed to extract {table_name}: {e}")
            return []
    
    def _parse_xml_response(self, xml_response: str, field_names: List[str], field_configs: List[Dict]) -> List[Dict[str, Any]]:
        """Parse XML response from Tally into list of dictionaries"""
        rows = []
        
        try:
            # Remove BOM if present
            if xml_response.startswith('\ufeff'):
                xml_response = xml_response[1:]
            
            # Tally returns flat XML with repeating F01, F02, ... sequences
            # Each F01 starts a new row
            import re
            
            num_fields = len(field_names)
            
            # Find all F01 values and their positions
            f01_pattern = re.compile(r'<F01>(.*?)</F01>', re.DOTALL)
            f01_matches = list(f01_pattern.finditer(xml_response))
            
            if not f01_matches:
                return rows
            
            # For each F01, extract all fields for that row
            for match_idx, f01_match in enumerate(f01_matches):
                # Determine the end position for this row
                if match_idx + 1 < len(f01_matches):
                    end_pos = f01_matches[match_idx + 1].start()
                else:
                    end_pos = len(xml_response)
                
                start_pos = f01_match.start()
                row_xml = xml_response[start_pos:end_pos]
                
                # Extract all field values for this row
                row = {}
                for i, field_name in enumerate(field_names):
                    tag_name = f"F{str(i + 1).zfill(2)}"
                    pattern = f'<{tag_name}>(.*?)</{tag_name}>'
                    match = re.search(pattern, row_xml, re.DOTALL)
                    
                    value = match.group(1) if match else ""
                    
                    # Handle null marker (ñ = chr(241))
                    if value == "ñ" or value == chr(241) or value == "":
                        value = None
                    
                    # Get field type for conversion
                    field_type = field_configs[i].get("type", "text") if i < len(field_configs) else "text"
                    
                    if value is not None:
                        if field_type in ("amount", "number", "rate", "quantity"):
                            try:
                                value = float(value) if value else 0.0
                            except:
                                value = 0.0
                        elif field_type == "logical":
                            value = 1 if str(value) in ("Yes", "1", "true", "True") else 0
                        elif field_type == "date":
                            value = parse_tally_date(str(value))
                    else:
                        if field_type in ("amount", "number", "rate", "quantity"):
                            value = 0.0
                        elif field_type == "logical":
                            value = 0
                        else:
                            value = ""
                    
                    row[field_name] = value
                rows.append(row)
                    
        except Exception as e:
            logger.error(f"Error parsing XML response: {e}")
        
        return rows
    
    def _parse_tabular_response(self, response: str, field_names: List[str], field_configs: List[Dict]) -> List[Dict[str, Any]]:
        """Parse tab-separated response as fallback"""
        rows = []
        try:
            lines = response.strip().split('\r\n')
            for line in lines:
                if not line.strip():
                    continue
                values = line.split('\t')
                if len(values) >= len(field_names):
                    row = {}
                    for i, field_name in enumerate(field_names):
                        value = values[i] if i < len(values) else ""
                        if value == "ñ" or value == chr(241):
                            value = ""
                        row[field_name] = value
                    rows.append(row)
        except Exception as e:
            logger.error(f"Error parsing tabular response: {e}")
        return rows
    
    def _get_tdl_for_table(self, table_name: str) -> Optional[str]:
        """Get TDL XML definition for a table"""
        # TDL definitions for each table
        tdl_definitions = {
            "mst_group": self._get_group_tdl(),
            "mst_ledger": self._get_ledger_tdl(),
            "mst_vouchertype": self._get_vouchertype_tdl(),
            "mst_stock_item": self._get_stockitem_tdl(),
            "trn_voucher": self._get_voucher_tdl(),
            # Add more as needed
        }
        return tdl_definitions.get(table_name)
    
    def _get_field_names(self, table_name: str) -> List[str]:
        """Get field names for a table"""
        field_definitions = {
            "mst_group": ["guid", "name", "parent", "primary_group", "is_revenue", "is_deemedpositive", "is_subledger", "sort_position"],
            "mst_ledger": ["guid", "name", "parent", "alias", "opening_balance", "description", "mailing_name", "mailing_address", "mailing_state", "mailing_country", "mailing_pincode", "email", "phone", "mobile", "contact", "pan", "gstin", "gst_registration_type", "is_bill_wise", "is_cost_centre"],
            "mst_vouchertype": ["guid", "name", "parent", "numbering_method", "is_active"],
            "mst_stock_item": ["guid", "name", "parent", "category", "alias", "uom", "opening_quantity", "opening_rate", "opening_value", "gst_applicable", "hsn_code", "gst_rate"],
            "trn_voucher": ["guid", "date", "voucher_type", "voucher_number", "reference_number", "reference_date", "narration", "party_name", "place_of_supply", "is_invoice", "is_accounting_voucher", "is_inventory_voucher", "is_order_voucher", "is_cancelled", "is_optional"],
        }
        return field_definitions.get(table_name, [])
    
    def _get_group_tdl(self) -> str:
        """TDL for mst_group"""
        return '''
            <REPORT NAME="mst_group">
                <FORMS>mst_group</FORMS>
            </REPORT>
            <FORM NAME="mst_group">
                <PARTS>mst_group</PARTS>
            </FORM>
            <PART NAME="mst_group">
                <LINES>mst_group</LINES>
                <REPEAT>mst_group : Group</REPEAT>
                <SCROLLED>Vertical</SCROLLED>
            </PART>
            <LINE NAME="mst_group">
                <FIELDS>FldGuid,FldName,FldParent,FldPrimaryGroup,FldIsRevenue,FldIsDeemedPositive,FldIsSubledger,FldSortPosition</FIELDS>
            </LINE>
            <FIELD NAME="FldGuid"><SET>$Guid</SET></FIELD>
            <FIELD NAME="FldName"><SET>$Name</SET></FIELD>
            <FIELD NAME="FldParent"><SET>$Parent</SET></FIELD>
            <FIELD NAME="FldPrimaryGroup"><SET>$_PrimaryGroup</SET></FIELD>
            <FIELD NAME="FldIsRevenue"><SET>$IsRevenue</SET></FIELD>
            <FIELD NAME="FldIsDeemedPositive"><SET>$IsDeemedPositive</SET></FIELD>
            <FIELD NAME="FldIsSubledger"><SET>$IsSubledger</SET></FIELD>
            <FIELD NAME="FldSortPosition"><SET>$SortPosition</SET></FIELD>
        '''
    
    def _get_ledger_tdl(self) -> str:
        """TDL for mst_ledger"""
        return '''
            <REPORT NAME="mst_ledger">
                <FORMS>mst_ledger</FORMS>
            </REPORT>
            <FORM NAME="mst_ledger">
                <PARTS>mst_ledger</PARTS>
            </FORM>
            <PART NAME="mst_ledger">
                <LINES>mst_ledger</LINES>
                <REPEAT>mst_ledger : Ledger</REPEAT>
                <SCROLLED>Vertical</SCROLLED>
            </PART>
            <LINE NAME="mst_ledger">
                <FIELDS>FldGuid,FldName,FldParent,FldAlias,FldOpeningBalance,FldDescription,FldMailingName,FldMailingAddress,FldMailingState,FldMailingCountry,FldMailingPincode,FldEmail,FldPhone,FldMobile,FldContact,FldPan,FldGstin,FldGstRegType,FldIsBillWise,FldIsCostCentre</FIELDS>
            </LINE>
            <FIELD NAME="FldGuid"><SET>$Guid</SET></FIELD>
            <FIELD NAME="FldName"><SET>$Name</SET></FIELD>
            <FIELD NAME="FldParent"><SET>$Parent</SET></FIELD>
            <FIELD NAME="FldAlias"><SET>$Alias</SET></FIELD>
            <FIELD NAME="FldOpeningBalance"><SET>$OpeningBalance</SET></FIELD>
            <FIELD NAME="FldDescription"><SET>$Description</SET></FIELD>
            <FIELD NAME="FldMailingName"><SET>$MailingName</SET></FIELD>
            <FIELD NAME="FldMailingAddress"><SET>$Address</SET></FIELD>
            <FIELD NAME="FldMailingState"><SET>$LedStateName</SET></FIELD>
            <FIELD NAME="FldMailingCountry"><SET>$CountryName</SET></FIELD>
            <FIELD NAME="FldMailingPincode"><SET>$Pincode</SET></FIELD>
            <FIELD NAME="FldEmail"><SET>$Email</SET></FIELD>
            <FIELD NAME="FldPhone"><SET>$LedgerPhone</SET></FIELD>
            <FIELD NAME="FldMobile"><SET>$LedgerMobile</SET></FIELD>
            <FIELD NAME="FldContact"><SET>$LedgerContact</SET></FIELD>
            <FIELD NAME="FldPan"><SET>$IncomeTaxNumber</SET></FIELD>
            <FIELD NAME="FldGstin"><SET>$PartyGSTIN</SET></FIELD>
            <FIELD NAME="FldGstRegType"><SET>$GSTRegistrationType</SET></FIELD>
            <FIELD NAME="FldIsBillWise"><SET>$IsBillWiseOn</SET></FIELD>
            <FIELD NAME="FldIsCostCentre"><SET>$IsCostCentresOn</SET></FIELD>
        '''
    
    def _get_vouchertype_tdl(self) -> str:
        """TDL for mst_vouchertype"""
        return '''
            <REPORT NAME="mst_vouchertype">
                <FORMS>mst_vouchertype</FORMS>
            </REPORT>
            <FORM NAME="mst_vouchertype">
                <PARTS>mst_vouchertype</PARTS>
            </FORM>
            <PART NAME="mst_vouchertype">
                <LINES>mst_vouchertype</LINES>
                <REPEAT>mst_vouchertype : VoucherType</REPEAT>
                <SCROLLED>Vertical</SCROLLED>
            </PART>
            <LINE NAME="mst_vouchertype">
                <FIELDS>FldGuid,FldName,FldParent,FldNumberingMethod,FldIsActive</FIELDS>
            </LINE>
            <FIELD NAME="FldGuid"><SET>$Guid</SET></FIELD>
            <FIELD NAME="FldName"><SET>$Name</SET></FIELD>
            <FIELD NAME="FldParent"><SET>$Parent</SET></FIELD>
            <FIELD NAME="FldNumberingMethod"><SET>$NumberingMethod</SET></FIELD>
            <FIELD NAME="FldIsActive"><SET>$IsActive</SET></FIELD>
        '''
    
    def _get_stockitem_tdl(self) -> str:
        """TDL for mst_stock_item"""
        return '''
            <REPORT NAME="mst_stock_item">
                <FORMS>mst_stock_item</FORMS>
            </REPORT>
            <FORM NAME="mst_stock_item">
                <PARTS>mst_stock_item</PARTS>
            </FORM>
            <PART NAME="mst_stock_item">
                <LINES>mst_stock_item</LINES>
                <REPEAT>mst_stock_item : StockItem</REPEAT>
                <SCROLLED>Vertical</SCROLLED>
            </PART>
            <LINE NAME="mst_stock_item">
                <FIELDS>FldGuid,FldName,FldParent,FldCategory,FldAlias,FldUom,FldOpeningQty,FldOpeningRate,FldOpeningValue,FldGstApplicable,FldHsnCode,FldGstRate</FIELDS>
            </LINE>
            <FIELD NAME="FldGuid"><SET>$Guid</SET></FIELD>
            <FIELD NAME="FldName"><SET>$Name</SET></FIELD>
            <FIELD NAME="FldParent"><SET>$Parent</SET></FIELD>
            <FIELD NAME="FldCategory"><SET>$Category</SET></FIELD>
            <FIELD NAME="FldAlias"><SET>$Alias</SET></FIELD>
            <FIELD NAME="FldUom"><SET>$BaseUnits</SET></FIELD>
            <FIELD NAME="FldOpeningQty"><SET>$OpeningBalance</SET></FIELD>
            <FIELD NAME="FldOpeningRate"><SET>$OpeningRate</SET></FIELD>
            <FIELD NAME="FldOpeningValue"><SET>$OpeningValue</SET></FIELD>
            <FIELD NAME="FldGstApplicable"><SET>$GSTApplicable</SET></FIELD>
            <FIELD NAME="FldHsnCode"><SET>$HSNCode</SET></FIELD>
            <FIELD NAME="FldGstRate"><SET>$GSTRate</SET></FIELD>
        '''
    
    def _get_voucher_tdl(self) -> str:
        """TDL for trn_voucher"""
        return '''
            <REPORT NAME="trn_voucher">
                <FORMS>trn_voucher</FORMS>
            </REPORT>
            <FORM NAME="trn_voucher">
                <PARTS>trn_voucher</PARTS>
            </FORM>
            <PART NAME="trn_voucher">
                <LINES>trn_voucher</LINES>
                <REPEAT>trn_voucher : Voucher</REPEAT>
                <SCROLLED>Vertical</SCROLLED>
            </PART>
            <LINE NAME="trn_voucher">
                <FIELDS>FldGuid,FldDate,FldVoucherType,FldVoucherNumber,FldRefNumber,FldRefDate,FldNarration,FldPartyName,FldPlaceOfSupply,FldIsInvoice,FldIsAccVoucher,FldIsInvVoucher,FldIsOrderVoucher,FldIsCancelled,FldIsOptional</FIELDS>
            </LINE>
            <FIELD NAME="FldGuid"><SET>$Guid</SET></FIELD>
            <FIELD NAME="FldDate"><SET>$Date</SET></FIELD>
            <FIELD NAME="FldVoucherType"><SET>$VoucherTypeName</SET></FIELD>
            <FIELD NAME="FldVoucherNumber"><SET>$VoucherNumber</SET></FIELD>
            <FIELD NAME="FldRefNumber"><SET>$Reference</SET></FIELD>
            <FIELD NAME="FldRefDate"><SET>$ReferenceDate</SET></FIELD>
            <FIELD NAME="FldNarration"><SET>$Narration</SET></FIELD>
            <FIELD NAME="FldPartyName"><SET>$PartyLedgerName</SET></FIELD>
            <FIELD NAME="FldPlaceOfSupply"><SET>$PlaceOfSupply</SET></FIELD>
            <FIELD NAME="FldIsInvoice"><SET>$IsInvoice</SET></FIELD>
            <FIELD NAME="FldIsAccVoucher"><SET>$IsAccountingVoucher</SET></FIELD>
            <FIELD NAME="FldIsInvVoucher"><SET>$IsInventoryVoucher</SET></FIELD>
            <FIELD NAME="FldIsOrderVoucher"><SET>$IsOrderVoucher</SET></FIELD>
            <FIELD NAME="FldIsCancelled"><SET>$IsCancelled</SET></FIELD>
            <FIELD NAME="FldIsOptional"><SET>$IsOptional</SET></FIELD>
        '''
    
    def _reset_status(self) -> None:
        """Reset sync status"""
        self.status = SyncStatus.IDLE
        self.progress = 0
        self.current_table = ""
        self.rows_processed = 0
        self.started_at = None
        self.completed_at = None
        self.error_message = None
        self._cancel_requested = False
    
    async def _save_sync_history(self, sync_type: str, status: str) -> int:
        """Save sync history record and return ID"""
        try:
            query = """
                INSERT INTO sync_history (sync_type, status, started_at, rows_processed, company_name)
                VALUES (?, ?, ?, 0, ?)
            """
            await database_service.execute(query, (sync_type, status, self.started_at.isoformat(), self.current_company))
            
            # Get last inserted ID
            result = await database_service.fetch_one("SELECT last_insert_rowid() as id")
            return result.get("id", 0) if result else 0
        except Exception as e:
            logger.warning(f"Failed to save sync history: {e}")
            return 0
    
    async def _update_sync_history(self, history_id: int, status: str, error_message: str = None) -> None:
        """Update sync history record"""
        if not history_id:
            return
        try:
            completed_at = datetime.now()
            duration = int((completed_at - self.started_at).total_seconds()) if self.started_at else 0
            
            query = """
                UPDATE sync_history 
                SET status = ?, completed_at = ?, rows_processed = ?, 
                    duration_seconds = ?, error_message = ?
                WHERE id = ?
            """
            await database_service.execute(query, (
                status, completed_at.isoformat(), self.rows_processed,
                duration, error_message, history_id
            ))
        except Exception as e:
            logger.warning(f"Failed to update sync history: {e}")
    
    async def get_sync_history(self, limit: int = 50) -> List[Dict]:
        """Get sync history records"""
        try:
            await database_service.connect()
            query = """
                SELECT id, sync_type, status, started_at, completed_at, 
                       rows_processed, duration_seconds, error_message
                FROM sync_history 
                ORDER BY started_at DESC 
                LIMIT ?
            """
            return await database_service.fetch_all(query, (limit,))
        except Exception as e:
            logger.error(f"Failed to get sync history: {e}")
            return []
    
    # ============== Crash Recovery Methods ==============
    
    def _save_sync_state(self, sync_type: str, table: str = "", rows: int = 0) -> None:
        """Save current sync state to file for crash recovery"""
        state = {
            "sync_type": sync_type,
            "status": "running",
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "current_table": table,
            "rows_processed": rows,
            "last_updated": datetime.now().isoformat()
        }
        try:
            with open(SYNC_STATE_FILE, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save sync state: {e}")
    
    def _clear_sync_state(self) -> None:
        """Clear sync state file after successful completion"""
        try:
            if SYNC_STATE_FILE.exists():
                SYNC_STATE_FILE.unlink()
        except Exception as e:
            logger.warning(f"Failed to clear sync state: {e}")
    
    def get_incomplete_sync(self) -> Optional[Dict]:
        """Check for incomplete sync from previous crash"""
        try:
            if SYNC_STATE_FILE.exists():
                with open(SYNC_STATE_FILE, "r") as f:
                    state = json.load(f)
                if state.get("status") == "running":
                    return state
        except Exception as e:
            logger.warning(f"Failed to read sync state: {e}")
        return None
    
    def dismiss_incomplete_sync(self) -> Dict:
        """Dismiss incomplete sync warning"""
        self._clear_sync_state()
        return {"status": "dismissed", "message": "Incomplete sync warning dismissed"}
    
    async def _update_config_table(self) -> None:
        """Update config table with sync info (like Node.js app does)"""
        try:
            # Clear existing config
            await database_service.execute("DELETE FROM config")
            
            # Get company name - use current_company if set, otherwise get from Tally
            company_name = self.current_company or "Unknown"
            company_guid = ""
            company_alterid = 0
            
            if not self.current_company:
                try:
                    company_info = await tally_service.get_company_info()
                    if company_info and not company_info.get("error"):
                        company_name = company_info.get("company_name", "Unknown") or "Unknown"
                        company_guid = company_info.get("guid", "") or ""
                        company_alterid = int(company_info.get("alterid", 0) or 0)
                except Exception as e:
                    logger.warning(f"Could not get company info: {e}")
            else:
                # Get GUID and AlterID for current company
                try:
                    company_info = await tally_service.get_company_info()
                    if company_info and not company_info.get("error"):
                        company_guid = company_info.get("guid", "") or ""
                        company_alterid = int(company_info.get("alterid", 0) or 0)
                except Exception as e:
                    logger.warning(f"Could not get company GUID/AlterID: {e}")
            
            # Get Last AlterID from Tally for incremental sync
            alt_id_master = 0
            alt_id_transaction = 0
            try:
                alter_ids = await tally_service.get_last_alter_ids()
                if alter_ids:
                    alt_id_master = int(alter_ids.get("master", 0) or 0)
                    alt_id_transaction = int(alter_ids.get("transaction", 0) or 0)
            except Exception as e:
                logger.warning(f"Could not get AlterIDs: {e}")
            
            # Update company_config table with GUID and AlterID
            await database_service.update_company_config(
                company_name=company_name,
                company_guid=company_guid,
                company_alterid=company_alterid,
                last_alter_id_master=alt_id_master,
                last_alter_id_transaction=alt_id_transaction,
                sync_type="full" if self.status != SyncStatus.RUNNING else "incremental"
            )
            
            # Insert config values (from_date/to_date are in tally config, not sync config)
            config_values = [
                ("Update Timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                ("Company Name", company_name),
                ("Period From", config.tally.from_date),
                ("Period To", config.tally.to_date),
                ("Sync Mode", config.sync.mode),
                ("Total Rows", str(self.rows_processed)),
                ("Last AlterID Master", str(alt_id_master)),
                ("Last AlterID Transaction", str(alt_id_transaction)),
            ]
            
            for name, value in config_values:
                await database_service.execute(
                    "INSERT INTO config (name, value) VALUES (?, ?)",
                    (name, value)
                )
            
            logger.info(f"Config updated for company: {company_name}, AlterID Master: {alt_id_master}, AlterID Transaction: {alt_id_transaction}")
        except Exception as e:
            logger.warning(f"Failed to update config table: {e}")


# Global service instance
sync_service = SyncService()
