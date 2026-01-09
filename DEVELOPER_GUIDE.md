# Tally FastAPI Database Loader - Developer Guide

## Table of Contents
1. [Architecture Overview](#architecture-overview)
2. [Data Flow](#data-flow)
3. [File Structure](#file-structure)
4. [Core Services](#core-services)
5. [Sync Logic](#sync-logic)
6. [API Endpoints](#api-endpoints)
7. [Database Schema](#database-schema)
8. [Configuration Files](#configuration-files)
9. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         TALLY FASTAPI LOADER                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐             │
│  │   FastAPI    │────▶│   Services   │────▶│   Database   │             │
│  │  Controllers │     │              │     │   (SQLite)   │             │
│  └──────────────┘     └──────────────┘     └──────────────┘             │
│         │                    │                                           │
│         │                    ▼                                           │
│         │             ┌──────────────┐                                   │
│         │             │    Tally     │                                   │
│         │             │   Gateway    │                                   │
│         │             │  (Port 9000) │                                   │
│         │             └──────────────┘                                   │
│         │                    │                                           │
│         ▼                    ▼                                           │
│  ┌──────────────────────────────────────────────────────────┐           │
│  │                    XML Builder                            │           │
│  │  (Generates TDL XML requests from YAML config)           │           │
│  └──────────────────────────────────────────────────────────┘           │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Key Components:

| Component | File | Purpose |
|-----------|------|---------|
| **Controllers** | `app/controllers/*.py` | API endpoints (REST) |
| **Sync Service** | `app/services/sync_service.py` | Main sync orchestration |
| **Database Service** | `app/services/database_service.py` | SQLite operations |
| **Tally Service** | `app/services/tally_service.py` | Tally HTTP communication |
| **XML Builder** | `app/services/xml_builder.py` | TDL XML generation |
| **Queue Service** | `app/services/sync_queue_service.py` | Multi-company queue |

---

## Data Flow

### Full Sync Flow:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          FULL SYNC FLOW                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  1. API Request                                                          │
│     POST /api/sync/full?company=CompanyName                             │
│                    │                                                     │
│                    ▼                                                     │
│  2. Verify Tally Connection                                             │
│     - Check if Tally is accessible                                      │
│     - Verify company exists and has data                                │
│                    │                                                     │
│                    ▼                                                     │
│  3. Truncate Company Data                                               │
│     - DELETE FROM table WHERE _company = 'CompanyName'                  │
│     - Only deletes data for specified company                           │
│                    │                                                     │
│                    ▼                                                     │
│  4. Sync Master Tables (19 tables)                                      │
│     For each table in tally-export-config.yaml:                         │
│     a. Build XML request from YAML config                               │
│     b. Send to Tally Gateway (localhost:9000)                           │
│     c. Parse XML response                                               │
│     d. Bulk insert into SQLite                                          │
│                    │                                                     │
│                    ▼                                                     │
│  5. Sync Transaction Tables (13 tables)                                 │
│     Same process as master tables                                       │
│                    │                                                     │
│                    ▼                                                     │
│  6. Update company_config Table                                         │
│     - Save company GUID, AlterID                                        │
│     - Update last_sync_at, sync_count                                   │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Incremental Sync Flow (Node.js Style):

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      INCREMENTAL SYNC FLOW                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  1. Get Last AlterID from Database                                      │
│     SELECT last_alter_id_master FROM company_config                     │
│     WHERE company_name = 'CompanyName'                                  │
│                    │                                                     │
│                    ▼                                                     │
│  2. Get Current AlterID from Tally                                      │
│     - Request company info from Tally                                   │
│     - Extract current AlterID                                           │
│                    │                                                     │
│                    ▼                                                     │
│  3. Compare AlterIDs                                                    │
│     IF current_alterid == last_alterid:                                 │
│        → No changes, skip sync                                          │
│     ELSE:                                                               │
│        → Changes detected, continue                                     │
│                    │                                                     │
│                    ▼                                                     │
│  4. Process Diff for Primary Tables                                     │
│     For each PRIMARY table:                                             │
│     ┌─────────────────────────────────────────────────────────┐        │
│     │ a. Truncate _diff and _delete tables                     │        │
│     │                                                          │        │
│     │ b. Fetch GUID + AlterID from Tally into _diff            │        │
│     │    (All current records)                                 │        │
│     │                                                          │        │
│     │ c. Find DELETED records:                                 │        │
│     │    INSERT INTO _delete                                   │        │
│     │    SELECT guid FROM main_table                           │        │
│     │    WHERE guid NOT IN (SELECT guid FROM _diff)            │        │
│     │                                                          │        │
│     │ d. Find MODIFIED records:                                │        │
│     │    INSERT INTO _delete                                   │        │
│     │    SELECT t.guid FROM main_table t                       │        │
│     │    JOIN _diff d ON d.guid = t.guid                       │        │
│     │    WHERE d.alterid <> t.alterid                          │        │
│     │                                                          │        │
│     │ e. Delete from main table:                               │        │
│     │    DELETE FROM main_table                                │        │
│     │    WHERE guid IN (SELECT guid FROM _delete)              │        │
│     │                                                          │        │
│     │ f. Cascade delete related tables                         │        │
│     └─────────────────────────────────────────────────────────┘        │
│                    │                                                     │
│                    ▼                                                     │
│  5. Import Changed Records                                              │
│     For each table:                                                     │
│     - Add filter: $AlterID > last_alterid                              │
│     - Fetch only new/modified records                                   │
│     - Upsert into database                                              │
│                    │                                                     │
│                    ▼                                                     │
│  6. Update company_config                                               │
│     - Save new AlterID values                                           │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Multi-Company Queue Flow:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     MULTI-COMPANY QUEUE FLOW                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  1. Add Companies to Queue                                              │
│     POST /api/sync/queue                                                │
│     Body: {"companies": ["Company1", "Company2"], "sync_type": "full"}  │
│                    │                                                     │
│                    ▼                                                     │
│  2. Start Queue Processing                                              │
│     POST /api/sync/queue/start                                          │
│                    │                                                     │
│                    ▼                                                     │
│  3. Process Each Company Sequentially                                   │
│     ┌─────────────────────────────────────────────────────────┐        │
│     │  FOR each company in queue:                              │        │
│     │    - Set config.tally.company = company_name             │        │
│     │    - Run full_sync() or incremental_sync()               │        │
│     │    - Update queue status                                 │        │
│     │    - Continue to next company                            │        │
│     └─────────────────────────────────────────────────────────┘        │
│                    │                                                     │
│                    ▼                                                     │
│  4. Queue Complete                                                      │
│     All companies synced, status updated                                │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## File Structure

```
tally-fastapi/
├── app/
│   ├── __init__.py
│   ├── main.py                      # FastAPI app entry point
│   ├── config.py                    # Configuration loader
│   ├── controllers/
│   │   ├── __init__.py
│   │   ├── sync_controller.py       # Sync API endpoints
│   │   ├── data_controller.py       # Data query endpoints
│   │   └── health_controller.py     # Health check endpoint
│   ├── services/
│   │   ├── __init__.py
│   │   ├── sync_service.py          # ⭐ Main sync orchestration
│   │   ├── sync_queue_service.py    # Multi-company queue
│   │   ├── database_service.py      # SQLite operations
│   │   ├── tally_service.py         # Tally HTTP client
│   │   └── xml_builder.py           # TDL XML generator
│   └── utils/
│       ├── __init__.py
│       ├── logger.py                # Logging configuration
│       └── decorators.py            # Utility decorators
├── config.yaml                      # App configuration
├── tally-export-config.yaml         # Full sync table/field config
├── tally-export-config-incremental.yaml  # Incremental sync config
├── database-structure.sql           # Full sync DB schema
├── database-structure-incremental.sql    # Incremental sync schema
├── run.py                           # Server startup script
├── test_sync.py                     # Test script with UI
└── DEVELOPER_GUIDE.md               # This file
```

---

## Core Services

### 1. SyncService (`sync_service.py`)

**Purpose:** Orchestrates the entire sync process.

**Key Methods:**

```python
class SyncService:
    async def full_sync(company: str) -> Dict:
        """
        Full synchronization - replaces all data for a company.
        
        Flow:
        1. Verify Tally connection (prevent data loss)
        2. Truncate company data
        3. Sync master tables
        4. Sync transaction tables
        5. Update company_config
        """
    
    async def incremental_sync(company: str) -> Dict:
        """
        Incremental sync - only changed records.
        
        Flow:
        1. Get last AlterID from DB
        2. Get current AlterID from Tally
        3. If different → process diff
        4. Import changed records
        5. Update company_config
        """
    
    async def _process_diff_for_primary_tables(data_type: str, last_alterid: int):
        """
        Node.js style diff processing.
        
        Uses _diff and _delete tables to:
        - Find deleted records (GUID not in Tally)
        - Find modified records (AlterID changed)
        - Delete old versions before importing new
        """
    
    async def _import_changed_records(data_type: str, last_alterid: int):
        """
        Import only records with AlterID > last_alterid.
        Uses $AlterID filter in Tally XML request.
        """
```

### 2. DatabaseService (`database_service.py`)

**Purpose:** All SQLite database operations.

**Key Methods:**

```python
class DatabaseService:
    async def connect() -> None:
        """Connect to SQLite database."""
    
    async def create_tables(incremental: bool) -> None:
        """
        Create tables from SQL schema file.
        - Full sync: database-structure.sql
        - Incremental: database-structure-incremental.sql
        """
    
    async def bulk_insert(table_name: str, rows: List[Dict], company_name: str) -> int:
        """
        Bulk insert rows into table.
        - Auto-adds _company column
        - Auto-creates missing columns (from YAML config)
        """
    
    async def _ensure_columns_exist(table_name: str, columns: List[str]) -> None:
        """
        Auto-add missing columns to table.
        Prevents schema mismatch errors when YAML has new fields.
        """
    
    async def truncate_all_tables(company: str) -> None:
        """
        Delete data only for specified company.
        DELETE FROM table WHERE _company = 'company_name'
        """
    
    async def update_company_config(...) -> None:
        """
        Update company_config table with:
        - company_guid, company_alterid
        - last_alter_id_master, last_alter_id_transaction
        - last_sync_at, sync_count
        """
```

### 3. TallyService (`tally_service.py`)

**Purpose:** HTTP communication with Tally Gateway.

**Key Methods:**

```python
class TallyService:
    async def send_xml(xml_request: str) -> str:
        """
        Send XML request to Tally Gateway.
        - URL: http://localhost:9000
        - Method: POST
        - Content-Type: text/xml
        - Encoding: UTF-16
        """
    
    async def check_connection() -> bool:
        """Check if Tally is accessible."""
    
    async def get_open_companies() -> List[Dict]:
        """Get list of all open companies in Tally."""
    
    async def get_company_info() -> Dict:
        """
        Get current company info including:
        - name, guid, alter_id
        - books_from, books_to
        """
```

### 4. XMLBuilder (`xml_builder.py`)

**Purpose:** Generate TDL XML requests from YAML config.

**Key Methods:**

```python
class XMLBuilder:
    def reload_config(incremental: bool) -> None:
        """
        Load YAML config file.
        - Full: tally-export-config.yaml
        - Incremental: tally-export-config-incremental.yaml
        """
    
    def build_export_request(table_config: Dict) -> str:
        """
        Build TDL XML request for a table.
        
        Structure:
        <ENVELOPE>
          <HEADER>...</HEADER>
          <BODY>
            <DESC>
              <TDL>
                <TDLMESSAGE>
                  <REPORT>...</REPORT>
                  <FORM>...</FORM>
                  <PART>...</PART>
                  <LINE>...</LINE>
                  <FIELD>...</FIELD>
                  <FETCH>...</FETCH>
                  <FILTER>...</FILTER>
                </TDLMESSAGE>
              </TDL>
            </DESC>
          </BODY>
        </ENVELOPE>
        """
    
    def get_master_tables() -> List[Dict]:
        """Get list of master table configs."""
    
    def get_transaction_tables() -> List[Dict]:
        """Get list of transaction table configs."""
```

---

## API Endpoints

### Sync Endpoints (`/api/sync/`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/sync/full` | Start full sync |
| `POST` | `/api/sync/incremental` | Start incremental sync |
| `GET` | `/api/sync/status` | Get current sync status |
| `POST` | `/api/sync/cancel` | Cancel running sync |
| `GET` | `/api/sync/history` | Get sync history |
| `POST` | `/api/sync/queue` | Add companies to queue |
| `POST` | `/api/sync/queue/start` | Start queue processing |
| `GET` | `/api/sync/queue/status` | Get queue status |
| `DELETE` | `/api/sync/queue` | Clear queue |

### Data Endpoints (`/api/data/`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/data/companies` | List Tally companies |
| `GET` | `/api/data/synced-companies` | List synced companies |
| `GET` | `/api/data/counts` | Get row counts per table |
| `GET` | `/api/data/groups` | Query groups |
| `GET` | `/api/data/ledgers` | Query ledgers |
| `GET` | `/api/data/vouchers` | Query vouchers |

### Health Endpoint

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Check Tally & DB connection |

---

## Database Schema

### Key Tables:

```sql
-- Company configuration (per-company sync metadata)
CREATE TABLE company_config (
    id INTEGER PRIMARY KEY,
    company_name TEXT UNIQUE,      -- Company name
    company_guid TEXT,             -- Tally GUID
    company_alterid INTEGER,       -- Company AlterID
    last_alter_id_master INTEGER,  -- Last synced master AlterID
    last_alter_id_transaction INTEGER,  -- Last synced transaction AlterID
    last_sync_at TEXT,             -- Last sync timestamp
    last_sync_type TEXT,           -- 'full' or 'incremental'
    sync_count INTEGER             -- Total sync count
);

-- Diff table (for incremental sync)
CREATE TABLE _diff (
    guid TEXT PRIMARY KEY,
    alterid TEXT
);

-- Delete tracking table
CREATE TABLE _delete (
    guid TEXT PRIMARY KEY
);

-- All data tables have _company column
-- Example: mst_ledger
CREATE TABLE mst_ledger (
    guid VARCHAR(64) PRIMARY KEY,
    name NVARCHAR(1024),
    parent NVARCHAR(1024),
    ...
    _company TEXT DEFAULT ''  -- Multi-company support
);
```

### Multi-Company Support:

Every data table has `_company` column:
- Full sync: `DELETE FROM table WHERE _company = 'CompanyName'`
- Queries: `SELECT * FROM table WHERE _company = 'CompanyName'`

---

## Configuration Files

### 1. `config.yaml` - App Configuration

```yaml
tally:
  server: localhost
  port: 9000
  company: ""  # Empty = active company in Tally

database:
  path: ./tally.db

sync:
  mode: full  # 'full' or 'incremental'
  batch_size: 1000

api:
  host: 0.0.0.0
  port: 8000
```

### 2. `tally-export-config.yaml` - Table/Field Config

```yaml
master:
  - name: mst_ledger           # Table name in database
    collection: Ledger         # Tally collection name
    nature: Primary            # Primary or Derived
    fields:
      - name: guid             # Column name in database
        field: Guid            # Tally field/formula
        type: text             # text, number, amount, logical, date
      - name: name
        field: Name
        type: text
    filters:                   # Optional Tally filters
      - NOT $IsCancelled
    cascade_delete:            # For incremental sync
      - table: related_table
        field: ledger_guid

transaction:
  - name: trn_voucher
    collection: Voucher
    ...
```

### Field Types:

| Type | Description | Example |
|------|-------------|---------|
| `text` | String value | Name, GUID |
| `number` | Integer/decimal | Quantity, AlterID |
| `amount` | Currency value | Amount, Balance |
| `logical` | Boolean (Yes/No) | IsActive |
| `date` | Date value | VoucherDate |

---

## Troubleshooting

### Common Issues:

#### 1. Schema Mismatch Error
```
Error: table X has no column named Y
```

**Cause:** YAML config has field not in SQL schema.

**Solution:** 
- Auto-column creation handles this automatically
- Or manually add column to database-structure.sql

#### 2. Tally Connection Error
```
Error: Tally connection failed
```

**Cause:** Tally not running or wrong port.

**Solution:**
- Ensure Tally is running
- Check config.yaml port (default: 9000)
- Enable Tally Gateway Server in Tally

#### 3. Zero Rows Imported
```
Full sync completed. Total rows: 0
```

**Cause:** Company not active in Tally or wrong company name.

**Solution:**
- Open the company in Tally
- Verify company name matches exactly

#### 4. Incremental Sync Not Detecting Changes

**Cause:** AlterID not changing or filter issue.

**Solution:**
- Check company_config table for last_alter_id values
- Verify Tally is returning AlterID in company info

---

## Best Practices

1. **Always use Full Sync first** before Incremental Sync
2. **Keep YAML and SQL files in sync** when adding new fields
3. **Use queue for multi-company sync** instead of parallel requests
4. **Check logs** in case of issues
5. **Backup tally.db** before major changes

---

## Contact

For issues or questions, check the logs or create a GitHub issue.
