"""
Sync Service Module
Orchestrates data synchronization between Tally and SQLite
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
    
    def get_status(self) -> Dict[str, Any]:
        """Get current sync status"""
        return {
            "status": self.status,
            "progress": self.progress,
            "current_table": self.current_table,
            "rows_processed": self.rows_processed,
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
    async def full_sync(self) -> Dict[str, Any]:
        """Perform full data synchronization"""
        if self.status == SyncStatus.RUNNING:
            return {"error": "Sync already in progress"}
        
        self._reset_status()
        self.status = SyncStatus.RUNNING
        self.started_at = datetime.now()
        sync_history_id = None
        
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
            
            # Truncate all tables for full sync
            logger.info("Truncating existing data...")
            await database_service.truncate_all_tables()
            
            # Sync master data
            logger.info("Syncing master data...")
            self._save_sync_state("full", "master_data", self.rows_processed)
            await self._sync_master_data()
            
            if self._cancel_requested:
                self.status = SyncStatus.CANCELLED
                await self._update_sync_history(sync_history_id, "cancelled")
                return self.get_status()
            
            # Sync transaction data
            logger.info("Syncing transaction data...")
            self._save_sync_state("full", "transaction_data", self.rows_processed)
            await self._sync_transaction_data()
            
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
    async def incremental_sync(self) -> Dict[str, Any]:
        """Perform incremental data synchronization (only changed records)"""
        if self.status == SyncStatus.RUNNING:
            return {"error": "Sync already in progress"}
        
        self._reset_status()
        self.status = SyncStatus.RUNNING
        self.started_at = datetime.now()
        sync_history_id = None
        
        try:
            # Reload config for incremental mode
            xml_builder.reload_config(incremental=True)
            
            # Connect to database
            await database_service.connect()
            
            # Create tables if not exist (with incremental schema)
            logger.info("Creating database tables (incremental schema)...")
            await database_service.create_tables(incremental=True)
            
            # Save sync history - started
            sync_history_id = await self._save_sync_history("incremental", "running")
            
            # Get last sync alterid from config table
            last_alterid = await self._get_last_alterid()
            logger.info(f"Last sync AlterID: {last_alterid}")
            
            # Sync master data with alterid filter
            logger.info("Syncing master data (incremental)...")
            await self._sync_master_data_incremental(last_alterid)
            
            if self._cancel_requested:
                self.status = SyncStatus.CANCELLED
                await self._update_sync_history(sync_history_id, "cancelled")
                return self.get_status()
            
            # Sync transaction data with alterid filter
            logger.info("Syncing transaction data (incremental)...")
            await self._sync_transaction_data_incremental(last_alterid)
            
            if self._cancel_requested:
                self.status = SyncStatus.CANCELLED
                await self._update_sync_history(sync_history_id, "cancelled")
                return self.get_status()
            
            # Update last alterid in config
            await self._update_last_alterid()
            
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
            await database_service.disconnect()
    
    async def _get_last_alterid(self) -> int:
        """Get last sync alterid from config table"""
        try:
            result = await database_service.fetch_one(
                "SELECT value FROM config WHERE name = 'last_alterid'"
            )
            if result:
                return int(result.get("value", 0))
        except:
            pass
        return 0
    
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
    
    async def _sync_master_data_incremental(self, last_alterid: int) -> None:
        """Sync master data with alterid filter"""
        master_tables = xml_builder.get_master_tables()
        total_tables = len(master_tables) + len(xml_builder.get_transaction_tables())
        
        for i, table_config in enumerate(master_tables):
            if self._cancel_requested:
                return
            
            table_name = table_config.get("name", "")
            self.current_table = table_name
            self.progress = int((i / total_tables) * 100)
            
            try:
                # Add alterid filter to table config
                table_config_with_filter = table_config.copy()
                if last_alterid > 0:
                    table_config_with_filter["filter"] = f"$AlterID > {last_alterid}"
                
                rows = await self._extract_table_data(table_config_with_filter)
                if rows:
                    # For incremental, use upsert (INSERT OR REPLACE)
                    count = await self._upsert_rows(table_name, rows)
                    self.rows_processed += count
                    logger.info(f"  {table_name}: upserted {count} rows")
                else:
                    logger.info(f"  {table_name}: no changes")
            except Exception as e:
                logger.error(f"  {table_name}: failed - {e}")
    
    async def _sync_transaction_data_incremental(self, last_alterid: int) -> None:
        """Sync transaction data with alterid filter"""
        master_tables = xml_builder.get_master_tables()
        transaction_tables = xml_builder.get_transaction_tables()
        total_tables = len(master_tables) + len(transaction_tables)
        
        for i, table_config in enumerate(transaction_tables):
            if self._cancel_requested:
                return
            
            table_name = table_config.get("name", "")
            self.current_table = table_name
            self.progress = int(((len(master_tables) + i) / total_tables) * 100)
            
            try:
                table_config_with_filter = table_config.copy()
                if last_alterid > 0:
                    table_config_with_filter["filter"] = f"$AlterID > {last_alterid}"
                
                rows = await self._extract_table_data(table_config_with_filter)
                if rows:
                    count = await self._upsert_rows(table_name, rows)
                    self.rows_processed += count
                    logger.info(f"  {table_name}: upserted {count} rows")
                else:
                    logger.info(f"  {table_name}: no changes")
            except Exception as e:
                logger.error(f"  {table_name}: failed - {e}")
    
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
    
    async def _sync_master_data(self) -> None:
        """Sync all master data tables"""
        master_tables = xml_builder.get_master_tables()
        total_tables = len(master_tables) + len(xml_builder.get_transaction_tables())
        
        for i, table_config in enumerate(master_tables):
            if self._cancel_requested:
                return
            
            table_name = table_config.get("name", "")
            self.current_table = table_name
            self.progress = int((i / total_tables) * 100)
            
            try:
                rows = await self._extract_table_data(table_config)
                if rows:
                    count = await database_service.bulk_insert(table_name, rows)
                    self.rows_processed += count
                    logger.info(f"  {table_name}: imported {count} rows")
                else:
                    logger.info(f"  {table_name}: imported 0 rows")
            except Exception as e:
                logger.error(f"  {table_name}: failed - {e}")
    
    async def _sync_transaction_data(self) -> None:
        """Sync all transaction data tables"""
        master_tables = xml_builder.get_master_tables()
        transaction_tables = xml_builder.get_transaction_tables()
        total_tables = len(master_tables) + len(transaction_tables)
        
        for i, table_config in enumerate(transaction_tables):
            if self._cancel_requested:
                return
            
            table_name = table_config.get("name", "")
            self.current_table = table_name
            self.progress = int(((len(master_tables) + i) / total_tables) * 100)
            
            try:
                rows = await self._extract_table_data(table_config)
                if rows:
                    count = await database_service.bulk_insert(table_name, rows)
                    self.rows_processed += count
                    logger.info(f"  {table_name}: imported {count} rows")
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
                INSERT INTO sync_history (sync_type, status, started_at, rows_processed)
                VALUES (?, ?, ?, 0)
            """
            await database_service.execute(query, (sync_type, status, self.started_at.isoformat()))
            
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
            
            # Get company name from Tally
            company_name = "Unknown"
            try:
                company_info = await tally_service.get_company_info()
                if company_info:
                    company_name = company_info.get("name", "Unknown")
            except:
                pass
            
            # Insert config values
            config_values = [
                ("Update Timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                ("Company Name", company_name),
                ("Period From", config.sync.from_date),
                ("Period To", config.sync.to_date),
                ("Sync Mode", config.sync.mode),
                ("Total Rows", str(self.rows_processed)),
            ]
            
            for name, value in config_values:
                await database_service.execute(
                    "INSERT INTO config (name, value) VALUES (?, ?)",
                    (name, value)
                )
            
            logger.info("Config table updated with sync info")
        except Exception as e:
            logger.warning(f"Failed to update config table: {e}")


# Global service instance
sync_service = SyncService()
