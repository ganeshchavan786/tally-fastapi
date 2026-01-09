"""
Database Service Module
Handles SQLite database operations
"""

import aiosqlite
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ..config import config
from ..utils.logger import logger
from ..utils.decorators import timed
from ..utils.constants import ALL_TABLES, MASTER_TABLES, TRANSACTION_TABLES


class DatabaseService:
    """Service for SQLite database operations"""
    
    def __init__(self):
        self.db_path = config.database.path
        self._connection: Optional[aiosqlite.Connection] = None
        self._initialized = False
    
    async def _get_connection(self) -> aiosqlite.Connection:
        """Get or create database connection"""
        if self._connection is None:
            # Create directory if not exists
            db_file = Path(self.db_path)
            db_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Use WAL mode and timeout to prevent database locked errors
            self._connection = await aiosqlite.connect(
                self.db_path,
                timeout=30.0
            )
            self._connection.row_factory = aiosqlite.Row
            
            # Enable WAL mode for better concurrency (only once)
            if not self._initialized:
                await self._connection.execute("PRAGMA journal_mode=WAL")
                await self._connection.execute("PRAGMA busy_timeout=30000")
                await self._connection.execute("PRAGMA synchronous=NORMAL")
                self._initialized = True
            
            logger.info(f"Connected to SQLite database: {self.db_path}")
        
        return self._connection
    
    async def connect(self) -> None:
        """Open database connection"""
        await self._get_connection()
    
    async def disconnect(self) -> None:
        """Close database connection"""
        if self._connection:
            try:
                await self._connection.close()
            except:
                pass
            self._connection = None
            logger.info("Database connection closed")
    
    async def execute(self, query: str, params: Tuple = ()) -> int:
        """Execute a query and return affected rows"""
        conn = await self._get_connection()
        
        try:
            cursor = await conn.execute(query, params)
            await conn.commit()
            return cursor.rowcount
        except Exception as e:
            logger.error(f"Query execution failed: {e}\nQuery: {query[:200]}...")
            raise
    
    async def execute_many(self, query: str, params_list: List[Tuple]) -> int:
        """Execute query with multiple parameter sets"""
        conn = await self._get_connection()
        
        try:
            cursor = await conn.executemany(query, params_list)
            await conn.commit()
            return cursor.rowcount
        except Exception as e:
            logger.error(f"Batch execution failed: {e}")
            raise
    
    async def fetch_all(self, query: str, params: Tuple = ()) -> List[Dict[str, Any]]:
        """Fetch all rows from query"""
        conn = await self._get_connection()
        
        try:
            cursor = await conn.execute(query, params)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Fetch failed: {e}")
            raise
    
    async def fetch_one(self, query: str, params: Tuple = ()) -> Optional[Dict[str, Any]]:
        """Fetch single row from query"""
        conn = await self._get_connection()
        
        try:
            cursor = await conn.execute(query, params)
            row = await cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Fetch one failed: {e}")
            raise
    
    async def fetch_scalar(self, query: str, params: Tuple = ()) -> Any:
        """Fetch single value from query"""
        result = await self.fetch_one(query, params)
        if result:
            return list(result.values())[0]
        return None
    
    @timed
    async def create_tables(self, incremental: bool = None) -> None:
        """Create all database tables from database-structure.sql"""
        conn = await self._get_connection()
        
        # Check config for sync mode if not specified
        if incremental is None:
            from ..config import config
            incremental = config.sync.mode == "incremental"
        
        # Try to load from external SQL file first
        schema_sql = self._load_schema_from_file(incremental=incremental)
        if not schema_sql:
            schema_sql = self._get_schema_sql()
        
        # Convert SQL types for SQLite
        schema_sql = self._convert_sql_for_sqlite(schema_sql)
        
        try:
            # Split by semicolon and execute each statement
            statements = [s.strip() for s in schema_sql.split(';') if s.strip()]
            for stmt in statements:
                if stmt.strip():
                    await conn.execute(stmt)
            await conn.commit()
            logger.info("Database tables created successfully")
            
            # Auto-add _company column to all tables for multi-company support
            await self._ensure_company_column_exists()
        except Exception as e:
            logger.error(f"Failed to create tables: {e}")
            raise
    
    async def _ensure_company_column_exists(self) -> None:
        """Auto-add _company column to all tables for multi-company support"""
        conn = await self._get_connection()
        
        for table in ALL_TABLES:
            try:
                cursor = await conn.execute(f"PRAGMA table_info({table})")
                columns = await cursor.fetchall()
                column_names = [col[1] for col in columns]
                
                if "_company" not in column_names:
                    await conn.execute(f"ALTER TABLE {table} ADD COLUMN _company TEXT DEFAULT ''")
                    logger.debug(f"Added _company column to {table}")
            except Exception as e:
                logger.debug(f"Could not add _company to {table}: {e}")
        
        await conn.commit()
        logger.info("Ensured _company column exists in all tables")
    
    async def _ensure_columns_exist(self, table_name: str, columns: List[str]) -> None:
        """Auto-add missing columns to table based on data being inserted"""
        conn = await self._get_connection()
        
        try:
            cursor = await conn.execute(f"PRAGMA table_info({table_name})")
            existing_columns = await cursor.fetchall()
            existing_column_names = [col[1] for col in existing_columns]
            
            for col in columns:
                if col not in existing_column_names:
                    # Add missing column with TEXT type (safe default)
                    await conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {col} TEXT DEFAULT ''")
                    logger.debug(f"Auto-added column '{col}' to table '{table_name}'")
            
            await conn.commit()
        except Exception as e:
            logger.warning(f"Could not ensure columns for {table_name}: {e}")
    
    def _load_schema_from_file(self, incremental: bool = False) -> str:
        """Load schema from database-structure.sql file"""
        if incremental:
            schema_path = Path("database-structure-incremental.sql")
        else:
            schema_path = Path("database-structure.sql")
        
        if schema_path.exists():
            with open(schema_path, "r", encoding="utf-8") as f:
                logger.info(f"Loading schema from {schema_path}")
                return f.read()
        return ""
    
    def _convert_sql_for_sqlite(self, sql: str) -> str:
        """Convert SQL types to SQLite compatible types"""
        import re
        # Replace CREATE TABLE with CREATE TABLE IF NOT EXISTS
        sql = re.sub(r'create\s+table\s+(?!if)', 'CREATE TABLE IF NOT EXISTS ', sql, flags=re.IGNORECASE)
        # Replace CREATE INDEX with CREATE INDEX IF NOT EXISTS
        sql = re.sub(r'create\s+index\s+(?!if)', 'CREATE INDEX IF NOT EXISTS ', sql, flags=re.IGNORECASE)
        # Replace types - only when they appear as data types (after column name)
        # Pattern: column_name followed by space and type
        sql = re.sub(r'\bnvarchar\s*\(\d+\)', 'TEXT', sql, flags=re.IGNORECASE)
        sql = re.sub(r'\bvarchar\s*\(\d+\)', 'TEXT', sql, flags=re.IGNORECASE)
        sql = re.sub(r'\btinyint\b', 'INTEGER', sql, flags=re.IGNORECASE)
        sql = re.sub(r'\bdecimal\s*\(\d+,\s*\d+\)', 'REAL', sql, flags=re.IGNORECASE)
        # Replace 'int' only when it's a standalone type (not part of tinyint, etc.)
        sql = re.sub(r'(?<!\w)int(?!\w)', 'INTEGER', sql, flags=re.IGNORECASE)
        # Replace 'date' type only when followed by comma, newline, space+not/default, or closing paren
        # This avoids replacing column names like 'date' 
        sql = re.sub(r'(?<=\s)date(?=\s*,|\s*\n|\s+not|\s+default|\s*\))', 'TEXT', sql, flags=re.IGNORECASE)
        return sql
    
    async def truncate_table(self, table_name: str, company: str = None) -> None:
        """Delete all rows from a table, optionally only for a specific company"""
        if company:
            # Check if _company column exists
            conn = await self._get_connection()
            cursor = await conn.execute(f"PRAGMA table_info({table_name})")
            columns = await cursor.fetchall()
            has_company_col = any(col[1] == '_company' for col in columns)
            
            if has_company_col:
                await self.execute(f"DELETE FROM {table_name} WHERE _company = ?", (company,))
                logger.debug(f"Truncated table {table_name} for company: {company}")
            else:
                await self.execute(f"DELETE FROM {table_name}")
                logger.debug(f"Truncated table: {table_name} (no _company column)")
        else:
            await self.execute(f"DELETE FROM {table_name}")
            logger.debug(f"Truncated table: {table_name}")
    
    async def truncate_all_tables(self, company: str = None) -> None:
        """Truncate all tables, optionally only for a specific company"""
        for table in ALL_TABLES:
            try:
                await self.truncate_table(table, company)
            except Exception as e:
                logger.warning(f"Could not truncate {table}: {e}")
    
    @timed
    async def bulk_insert(self, table_name: str, rows: List[Dict[str, Any]], company_name: str = None) -> int:
        """Bulk insert rows into table, optionally with company name"""
        if not rows:
            return 0
        
        if not self._connection:
            await self.connect()
        
        # Add _company column if company_name provided
        if company_name:
            for row in rows:
                row['_company'] = company_name
        
        # Get column names from first row
        columns = list(rows[0].keys())
        
        # Auto-add missing columns to table
        await self._ensure_columns_exist(table_name, columns)
        
        placeholders = ', '.join(['?' for _ in columns])
        column_names = ', '.join(columns)
        
        query = f"INSERT INTO {table_name} ({column_names}) VALUES ({placeholders})"
        
        # Convert rows to tuples
        params_list = [tuple(row.get(col) for col in columns) for row in rows]
        
        try:
            # Insert in batches
            batch_size = config.sync.batch_size
            total_inserted = 0
            
            for i in range(0, len(params_list), batch_size):
                batch = params_list[i:i + batch_size]
                await self._connection.executemany(query, batch)
                total_inserted += len(batch)
            
            await self._connection.commit()
            logger.debug(f"Inserted {total_inserted} rows into {table_name}")
            return total_inserted
        except Exception as e:
            logger.error(f"Bulk insert failed for {table_name}: {e}")
            raise
    
    async def get_table_count(self, table_name: str) -> int:
        """Get row count for a table"""
        try:
            # Check if table exists first
            conn = await self._get_connection()
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,)
            )
            row = await cursor.fetchone()
            if not row or row[0] == 0:
                return 0
            
            # Table exists, get count
            cursor = await conn.execute(f"SELECT COUNT(*) FROM {table_name}")
            row = await cursor.fetchone()
            return row[0] if row else 0
        except:
            return 0
    
    async def get_all_table_counts(self) -> Dict[str, int]:
        """Get row counts for all tables"""
        counts = {}
        for table in ALL_TABLES:
            counts[table] = await self.get_table_count(table)
        return counts
    
    async def table_exists(self, table_name: str) -> bool:
        """Check if table exists"""
        result = await self.fetch_scalar(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,)
        )
        return result > 0
    
    async def get_database_size(self) -> int:
        """Get database file size in bytes"""
        try:
            return Path(self.db_path).stat().st_size
        except:
            return 0
    
    def _get_schema_sql(self) -> str:
        """Get database schema SQL"""
        return '''
-- Configuration Table
CREATE TABLE IF NOT EXISTS config (
    name TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

-- Master Tables
CREATE TABLE IF NOT EXISTS mst_group (
    guid TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    parent TEXT NOT NULL DEFAULT '',
    primary_group TEXT NOT NULL DEFAULT '',
    is_revenue INTEGER NOT NULL DEFAULT 0,
    is_deemedpositive INTEGER NOT NULL DEFAULT 0,
    is_subledger INTEGER NOT NULL DEFAULT 0,
    sort_position INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS mst_ledger (
    guid TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    parent TEXT NOT NULL DEFAULT '',
    alias TEXT NOT NULL DEFAULT '',
    opening_balance REAL NOT NULL DEFAULT 0,
    description TEXT NOT NULL DEFAULT '',
    mailing_name TEXT NOT NULL DEFAULT '',
    mailing_address TEXT NOT NULL DEFAULT '',
    mailing_state TEXT NOT NULL DEFAULT '',
    mailing_country TEXT NOT NULL DEFAULT '',
    mailing_pincode TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    mobile TEXT NOT NULL DEFAULT '',
    contact TEXT NOT NULL DEFAULT '',
    pan TEXT NOT NULL DEFAULT '',
    gstin TEXT NOT NULL DEFAULT '',
    gst_registration_type TEXT NOT NULL DEFAULT '',
    is_bill_wise INTEGER NOT NULL DEFAULT 0,
    is_cost_centre INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS mst_vouchertype (
    guid TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    parent TEXT NOT NULL DEFAULT '',
    numbering_method TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS mst_uom (
    guid TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    symbol TEXT NOT NULL DEFAULT '',
    is_simple_unit INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS mst_godown (
    guid TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    parent TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS mst_stock_category (
    guid TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    parent TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS mst_stock_group (
    guid TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    parent TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS mst_stock_item (
    guid TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    parent TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    alias TEXT NOT NULL DEFAULT '',
    uom TEXT NOT NULL DEFAULT '',
    opening_quantity REAL NOT NULL DEFAULT 0,
    opening_rate REAL NOT NULL DEFAULT 0,
    opening_value REAL NOT NULL DEFAULT 0,
    gst_applicable TEXT NOT NULL DEFAULT '',
    hsn_code TEXT NOT NULL DEFAULT '',
    gst_rate REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS mst_cost_category (
    guid TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    allocate_revenue INTEGER NOT NULL DEFAULT 0,
    allocate_non_revenue INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS mst_cost_centre (
    guid TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    parent TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS mst_attendance_type (
    guid TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    parent TEXT NOT NULL DEFAULT '',
    attendance_type TEXT NOT NULL DEFAULT '',
    attendance_period TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS mst_employee (
    guid TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    parent TEXT NOT NULL DEFAULT '',
    id_number TEXT NOT NULL DEFAULT '',
    date_of_joining TEXT,
    date_of_release TEXT,
    designation TEXT NOT NULL DEFAULT '',
    gender TEXT NOT NULL DEFAULT '',
    date_of_birth TEXT,
    pan TEXT NOT NULL DEFAULT '',
    aadhar TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS mst_payhead (
    guid TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    parent TEXT NOT NULL DEFAULT '',
    pay_type TEXT NOT NULL DEFAULT '',
    income_type TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS mst_gst_effective_rate (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_guid TEXT NOT NULL DEFAULT '',
    applicable_from TEXT,
    hsn_code TEXT NOT NULL DEFAULT '',
    rate REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS mst_opening_batch_allocation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_guid TEXT NOT NULL DEFAULT '',
    godown TEXT NOT NULL DEFAULT '',
    batch TEXT NOT NULL DEFAULT '',
    quantity REAL NOT NULL DEFAULT 0,
    rate REAL NOT NULL DEFAULT 0,
    amount REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS mst_opening_bill_allocation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_guid TEXT NOT NULL DEFAULT '',
    bill_name TEXT NOT NULL DEFAULT '',
    bill_type TEXT NOT NULL DEFAULT '',
    bill_date TEXT,
    amount REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS mst_stockitem_standard_cost (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_guid TEXT NOT NULL DEFAULT '',
    date TEXT,
    rate REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS mst_stockitem_standard_price (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_guid TEXT NOT NULL DEFAULT '',
    date TEXT,
    rate REAL NOT NULL DEFAULT 0
);

-- Transaction Tables
CREATE TABLE IF NOT EXISTS trn_voucher (
    guid TEXT PRIMARY KEY,
    date TEXT NOT NULL DEFAULT '',
    voucher_type TEXT NOT NULL DEFAULT '',
    voucher_number TEXT NOT NULL DEFAULT '',
    reference_number TEXT NOT NULL DEFAULT '',
    reference_date TEXT,
    narration TEXT NOT NULL DEFAULT '',
    party_name TEXT NOT NULL DEFAULT '',
    place_of_supply TEXT NOT NULL DEFAULT '',
    is_invoice INTEGER NOT NULL DEFAULT 0,
    is_accounting_voucher INTEGER NOT NULL DEFAULT 0,
    is_inventory_voucher INTEGER NOT NULL DEFAULT 0,
    is_order_voucher INTEGER NOT NULL DEFAULT 0,
    is_cancelled INTEGER NOT NULL DEFAULT 0,
    is_optional INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS trn_accounting (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guid TEXT NOT NULL,
    ledger TEXT NOT NULL DEFAULT '',
    amount REAL NOT NULL DEFAULT 0,
    amount_forex REAL NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT '',
    is_party_ledger INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS trn_inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guid TEXT NOT NULL,
    stock_item TEXT NOT NULL DEFAULT '',
    quantity REAL NOT NULL DEFAULT 0,
    rate REAL NOT NULL DEFAULT 0,
    amount REAL NOT NULL DEFAULT 0,
    godown TEXT NOT NULL DEFAULT '',
    tracking_number TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS trn_cost_centre (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guid TEXT NOT NULL,
    ledger TEXT NOT NULL DEFAULT '',
    cost_centre TEXT NOT NULL DEFAULT '',
    amount REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS trn_cost_category_centre (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guid TEXT NOT NULL,
    ledger TEXT NOT NULL DEFAULT '',
    cost_category TEXT NOT NULL DEFAULT '',
    cost_centre TEXT NOT NULL DEFAULT '',
    amount REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS trn_cost_inventory_category_centre (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guid TEXT NOT NULL,
    stock_item TEXT NOT NULL DEFAULT '',
    cost_category TEXT NOT NULL DEFAULT '',
    cost_centre TEXT NOT NULL DEFAULT '',
    amount REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS trn_bill (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guid TEXT NOT NULL,
    ledger TEXT NOT NULL DEFAULT '',
    bill_type TEXT NOT NULL DEFAULT '',
    bill_name TEXT NOT NULL DEFAULT '',
    amount REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS trn_bank (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guid TEXT NOT NULL,
    ledger TEXT NOT NULL DEFAULT '',
    transaction_type TEXT NOT NULL DEFAULT '',
    instrument_number TEXT NOT NULL DEFAULT '',
    instrument_date TEXT,
    bank_name TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS trn_batch (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guid TEXT NOT NULL,
    stock_item TEXT NOT NULL DEFAULT '',
    batch TEXT NOT NULL DEFAULT '',
    quantity REAL NOT NULL DEFAULT 0,
    rate REAL NOT NULL DEFAULT 0,
    amount REAL NOT NULL DEFAULT 0,
    godown TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS trn_inventory_accounting (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guid TEXT NOT NULL,
    stock_item TEXT NOT NULL DEFAULT '',
    ledger TEXT NOT NULL DEFAULT '',
    amount REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS trn_employee (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guid TEXT NOT NULL,
    employee TEXT NOT NULL DEFAULT '',
    amount REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS trn_payhead (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guid TEXT NOT NULL,
    employee TEXT NOT NULL DEFAULT '',
    payhead TEXT NOT NULL DEFAULT '',
    amount REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS trn_attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guid TEXT NOT NULL,
    employee TEXT NOT NULL DEFAULT '',
    attendance_type TEXT NOT NULL DEFAULT '',
    value REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS trn_closingstock_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guid TEXT NOT NULL,
    stock_item TEXT NOT NULL DEFAULT '',
    ledger TEXT NOT NULL DEFAULT '',
    amount REAL NOT NULL DEFAULT 0
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_trn_voucher_date ON trn_voucher(date);
CREATE INDEX IF NOT EXISTS idx_trn_voucher_type ON trn_voucher(voucher_type);
CREATE INDEX IF NOT EXISTS idx_trn_accounting_guid ON trn_accounting(guid);
CREATE INDEX IF NOT EXISTS idx_trn_inventory_guid ON trn_inventory(guid);
CREATE INDEX IF NOT EXISTS idx_mst_ledger_parent ON mst_ledger(parent);
CREATE INDEX IF NOT EXISTS idx_mst_stock_item_parent ON mst_stock_item(parent);
'''


    async def add_company_name_to_sync_history(self) -> None:
        """Add company_name column to sync_history table if not exists"""
        conn = await self._get_connection()
        try:
            cursor = await conn.execute("PRAGMA table_info(sync_history)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
            
            if "company_name" not in column_names:
                await conn.execute("ALTER TABLE sync_history ADD COLUMN company_name VARCHAR(256) DEFAULT ''")
                await conn.commit()
                logger.info("Added company_name column to sync_history")
        except Exception as e:
            logger.warning(f"Could not add company_name to sync_history: {e}")

    async def add_company_column_to_tables(self) -> Dict[str, Any]:
        """Add _company column to all tables for multi-company support"""
        conn = await self._get_connection()
        
        # Get list of all tables
        tables_to_update = [
            "mst_group", "mst_ledger", "mst_vouchertype", "mst_currency",
            "mst_stock_group", "mst_stock_category", "mst_stock_item", "mst_godown",
            "mst_unit", "mst_cost_category", "mst_cost_centre", "mst_employee",
            "mst_attendance_type", "mst_gst_effective_rate",
            "trn_voucher", "trn_accounting", "trn_inventory", "trn_cost_centre",
            "trn_bill", "trn_bank", "trn_batch", "trn_attendance"
        ]
        
        updated_tables = []
        skipped_tables = []
        
        for table in tables_to_update:
            try:
                # Check if column already exists
                cursor = await conn.execute(f"PRAGMA table_info({table})")
                columns = await cursor.fetchall()
                column_names = [col[1] for col in columns]
                
                if "_company" not in column_names:
                    # Add _company column
                    await conn.execute(f"ALTER TABLE {table} ADD COLUMN _company VARCHAR(256) DEFAULT ''")
                    updated_tables.append(table)
                    logger.info(f"Added _company column to {table}")
                else:
                    skipped_tables.append(table)
            except Exception as e:
                logger.warning(f"Could not update table {table}: {e}")
        
        await conn.commit()
        
        # Create index on _company for faster queries
        for table in updated_tables:
            try:
                await conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_company ON {table}(_company)")
            except:
                pass
        
        await conn.commit()
        
        return {
            "status": "success",
            "updated_tables": updated_tables,
            "skipped_tables": skipped_tables,
            "message": f"Updated {len(updated_tables)} tables, skipped {len(skipped_tables)}"
        }

    async def ensure_company_config_table(self) -> None:
        """Ensure company_config table exists with all required columns"""
        conn = await self._get_connection()
        try:
            # Create company_config table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS company_config (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_name TEXT NOT NULL UNIQUE,
                    company_guid TEXT DEFAULT '',
                    company_alterid INTEGER DEFAULT 0,
                    last_alter_id_master INTEGER DEFAULT 0,
                    last_alter_id_transaction INTEGER DEFAULT 0,
                    last_sync_at TEXT,
                    last_sync_type TEXT,
                    sync_count INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create _diff table for incremental sync (GUID + AlterID comparison)
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS _diff (
                    guid TEXT PRIMARY KEY,
                    alterid TEXT DEFAULT ''
                )
            ''')
            
            # Create _delete table for tracking records to delete
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS _delete (
                    guid TEXT PRIMARY KEY
                )
            ''')
            
            # Create index
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_company_config_name ON company_config(company_name)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_company_config_guid ON company_config(company_guid)')
            
            await conn.commit()
            logger.info("Ensured company_config table exists")
        except Exception as e:
            logger.warning(f"Could not ensure company_config table: {e}")

    async def update_company_config(self, company_name: str, company_guid: str = "", company_alterid: int = 0,
                                     last_alter_id_master: int = 0, last_alter_id_transaction: int = 0,
                                     sync_type: str = "full") -> None:
        """Update or insert company config record"""
        conn = await self._get_connection()
        try:
            # Check if company exists
            cursor = await conn.execute(
                "SELECT id, sync_count FROM company_config WHERE company_name = ?",
                (company_name,)
            )
            existing = await cursor.fetchone()
            
            now = datetime.now().isoformat()
            
            if existing:
                # Update existing record
                sync_count = (existing[1] or 0) + 1
                await conn.execute('''
                    UPDATE company_config SET
                        company_guid = COALESCE(NULLIF(?, ''), company_guid),
                        company_alterid = CASE WHEN ? > 0 THEN ? ELSE company_alterid END,
                        last_alter_id_master = ?,
                        last_alter_id_transaction = ?,
                        last_sync_at = ?,
                        last_sync_type = ?,
                        sync_count = ?,
                        updated_at = ?
                    WHERE company_name = ?
                ''', (company_guid, company_alterid, company_alterid, last_alter_id_master, 
                      last_alter_id_transaction, now, sync_type, sync_count, now, company_name))
                logger.info(f"Updated company config for: {company_name} (GUID: {company_guid})")
            else:
                # Insert new record
                await conn.execute('''
                    INSERT INTO company_config 
                    (company_name, company_guid, company_alterid, last_alter_id_master, 
                     last_alter_id_transaction, last_sync_at, last_sync_type, sync_count, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                ''', (company_name, company_guid, company_alterid, last_alter_id_master,
                      last_alter_id_transaction, now, sync_type, now, now))
                logger.info(f"New company added: {company_name} (GUID: {company_guid}, AlterID: {company_alterid})")
            
            await conn.commit()
        except Exception as e:
            logger.error(f"Failed to update company config: {e}")

    async def get_synced_companies(self) -> List[Dict[str, Any]]:
        """Get list of synced companies from company_config"""
        try:
            rows = await self.fetch_all(
                "SELECT company_name, company_guid, company_alterid, last_alter_id_master, "
                "last_alter_id_transaction, last_sync_at, sync_count FROM company_config ORDER BY company_name"
            )
            return rows
        except Exception as e:
            logger.error(f"Failed to get synced companies: {e}")
            return []


# Global service instance
database_service = DatabaseService()
