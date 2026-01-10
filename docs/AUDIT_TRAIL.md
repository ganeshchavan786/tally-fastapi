# Audit Trail Documentation

## Overview

Audit Trail हे एक powerful feature आहे जे Tally FastAPI Database Loader मध्ये incremental sync दरम्यान होणाऱ्या सर्व changes track करते. हे feature data integrity, debugging, आणि deleted records recovery साठी अत्यंत उपयुक्त आहे.

---

## Features

### 1. **Complete Change Tracking**
- **INSERT** - नवीन records add झाले तेव्हा log
- **UPDATE** - existing records मध्ये बदल झाले तेव्हा log (old + new values)
- **DELETE** - records delete झाले तेव्हा log

### 2. **Deleted Records Recovery**
- Delete झालेल्या records चा **full data** store होतो
- **Manual restore** - API call करून restore करता येतो (auto restore नाही)
- `POST /api/audit/restore/{id}` endpoint वापरून restore
- Financial data साठी compliance maintain होतो
- Restore करेपर्यंत data safe राहतो `deleted_records` table मध्ये

### 3. **Sync Session Grouping**
- प्रत्येक sync operation ला unique session ID
- एका sync मध्ये किती changes झाले ते track करता येतो
- Debugging साठी session-wise analysis

### 4. **Audit Statistics**
- Action-wise counts (INSERT/UPDATE/DELETE)
- Table-wise counts
- Pending deleted records count

### 5. **Record History**
- कोणत्याही record चा complete history पाहता येतो
- कधी create झाला, कधी update झाला, कधी delete झाला

---

## How It Works

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Incremental Sync                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. Sync Start                                               │
│     └── audit_service.start_session("incremental", company)  │
│                                                              │
│  2. Compare GUID + AlterID                                   │
│     ├── New records → INSERT                                 │
│     ├── Changed records → UPDATE                             │
│     └── Missing records → DELETE                             │
│                                                              │
│  3. For Each Change:                                         │
│     ├── INSERT → audit_service.log_insert()                  │
│     ├── UPDATE → audit_service.log_update(old, new)          │
│     └── DELETE → audit_service.log_delete() +                │
│                  store in deleted_records                    │
│                                                              │
│  4. Sync End                                                 │
│     └── audit_service.end_session()                          │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow

```
Tally Data ──► Compare with DB ──► Detect Changes ──► Log to Audit ──► Apply Changes
                    │                    │                  │
                    │                    │                  ▼
                    │                    │           ┌──────────────┐
                    │                    │           │  audit_log   │
                    │                    │           │    table     │
                    │                    │           └──────────────┘
                    │                    │                  │
                    │                    │                  ▼ (if DELETE)
                    │                    │           ┌──────────────┐
                    │                    │           │deleted_records│
                    │                    │           │    table     │
                    │                    │           └──────────────┘
```

---

## Database Tables

### 1. `audit_log` Table

Main audit table जी सर्व changes track करते.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `sync_session_id` | TEXT | Unique session identifier |
| `sync_type` | TEXT | "full" or "incremental" |
| `table_name` | TEXT | Table name (mst_ledger, trn_voucher, etc.) |
| `record_guid` | TEXT | GUID of the record |
| `record_name` | TEXT | Human-readable name |
| `action` | TEXT | INSERT, UPDATE, DELETE |
| `old_data` | TEXT | JSON - Previous values |
| `new_data` | TEXT | JSON - New values |
| `changed_fields` | TEXT | JSON array of changed field names |
| `company` | TEXT | Company name |
| `tally_alter_id` | INTEGER | Tally's AlterID |
| `created_at` | TIMESTAMP | When logged |
| `status` | TEXT | SUCCESS or FAILED |
| `message` | TEXT | Additional info |

### 2. `deleted_records` Table

Deleted records साठी full data storage (recovery साठी).

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `table_name` | TEXT | Original table name |
| `record_guid` | TEXT | GUID of deleted record |
| `record_name` | TEXT | Human-readable name |
| `record_data` | TEXT | JSON - Full record data |
| `company` | TEXT | Company name |
| `sync_session_id` | TEXT | Which sync deleted it |
| `deleted_at` | TIMESTAMP | When deleted |
| `is_restored` | INTEGER | 1 if restored |
| `restored_at` | TIMESTAMP | When restored |

---

## API Endpoints

### 1. Get Audit History

```http
GET /api/audit/history
```

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `table_name` | string | Filter by table |
| `record_guid` | string | Filter by GUID |
| `action` | string | INSERT, UPDATE, DELETE |
| `company` | string | Filter by company |
| `start_date` | string | YYYY-MM-DD |
| `end_date` | string | YYYY-MM-DD |
| `limit` | int | Max records (default 100) |
| `offset` | int | Pagination offset |

**Example:**
```bash
# Get all DELETE actions
GET /api/audit/history?action=DELETE

# Get ledger changes for specific company
GET /api/audit/history?table_name=mst_ledger&company=OM%20ENGINEERING

# Get changes from specific date
GET /api/audit/history?start_date=2026-01-10
```

**Response:**
```json
{
  "count": 50,
  "limit": 100,
  "offset": 0,
  "records": [
    {
      "id": 1,
      "sync_session_id": "incremental_20260110_100524_abc123",
      "table_name": "mst_ledger",
      "record_guid": "abc-123-guid",
      "record_name": "Cash",
      "action": "UPDATE",
      "old_data": {"name": "Cash", "opening_balance": 1000},
      "new_data": {"name": "Cash", "opening_balance": 1500},
      "changed_fields": ["opening_balance"],
      "company": "OM ENGINEERING",
      "created_at": "2026-01-10T10:05:24"
    }
  ]
}
```

---

### 2. Get Record History

```http
GET /api/audit/record/{table_name}/{record_guid}
```

**Example:**
```bash
GET /api/audit/record/mst_ledger/abc-123-guid
```

**Response:**
```json
{
  "table_name": "mst_ledger",
  "record_guid": "abc-123-guid",
  "history_count": 3,
  "history": [
    {"action": "DELETE", "created_at": "2026-01-10T12:00:00", ...},
    {"action": "UPDATE", "created_at": "2026-01-09T15:30:00", ...},
    {"action": "INSERT", "created_at": "2026-01-08T10:00:00", ...}
  ]
}
```

---

### 3. Get Sync Session Changes

```http
GET /api/audit/session/{session_id}
```

**Example:**
```bash
GET /api/audit/session/incremental_20260110_100524_abc123
```

**Response:**
```json
{
  "session_id": "incremental_20260110_100524_abc123",
  "summary": {
    "INSERT": 50,
    "UPDATE": 120,
    "DELETE": 30
  },
  "total_changes": 200,
  "changes": [...]
}
```

---

### 4. Get Deleted Records

```http
GET /api/audit/deleted
```

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `table_name` | string | Filter by table |
| `company` | string | Filter by company |
| `include_restored` | bool | Include restored records |
| `limit` | int | Max records |
| `offset` | int | Pagination |

**Example:**
```bash
# Get all deleted ledgers
GET /api/audit/deleted?table_name=mst_ledger

# Get deleted records for company
GET /api/audit/deleted?company=OM%20ENGINEERING
```

**Response:**
```json
{
  "count": 1700,
  "records": [
    {
      "id": 42,
      "table_name": "mst_ledger",
      "record_guid": "xyz-456-guid",
      "record_name": "Old Ledger",
      "record_data": {"guid": "xyz-456-guid", "name": "Old Ledger", ...},
      "company": "OM ENGINEERING",
      "deleted_at": "2026-01-10T10:05:24",
      "is_restored": 0
    }
  ]
}
```

---

### 5. Restore Deleted Record

```http
POST /api/audit/restore/{deleted_id}
```

**Example:**
```bash
POST /api/audit/restore/42
```

**Response:**
```json
{
  "status": "success",
  "message": "Record restored to mst_ledger",
  "table_name": "mst_ledger",
  "record_guid": "xyz-456-guid",
  "record_name": "Old Ledger"
}
```

---

### 6. Get Audit Statistics

```http
GET /api/audit/stats
```

**Example:**
```bash
GET /api/audit/stats?company=OM%20ENGINEERING
```

**Response:**
```json
{
  "by_action": {
    "INSERT": 500,
    "UPDATE": 1200,
    "DELETE": 1700
  },
  "by_table": {
    "mst_stock_item": 1369,
    "mst_ledger": 249,
    "mst_group": 29,
    "mst_vouchertype": 27,
    "mst_uom": 18
  },
  "pending_deleted_records": 1700
}
```

---

### 7. Get Recent Sessions

```http
GET /api/audit/sessions
```

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `limit` | int | Max sessions (default 20) |
| `company` | string | Filter by company |

**Response:**
```json
{
  "count": 5,
  "sessions": [
    {
      "sync_session_id": "incremental_20260110_100524_abc123",
      "sync_type": "incremental",
      "company": "OM ENGINEERING",
      "started_at": "2026-01-10T10:05:24",
      "ended_at": "2026-01-10T10:11:41",
      "total_changes": 200,
      "inserts": 50,
      "updates": 120,
      "deletes": 30
    }
  ]
}
```

---

## Use Cases

### 1. Debugging Sync Issues

```bash
# काल sync मध्ये काय झालं?
GET /api/audit/history?start_date=2026-01-09&end_date=2026-01-09

# कोणते records delete झाले?
GET /api/audit/history?action=DELETE&start_date=2026-01-09
```

### 2. Record Investigation

```bash
# या ledger ला काय झालं?
GET /api/audit/record/mst_ledger/abc-123-guid

# हा voucher कधी बदलला?
GET /api/audit/record/trn_voucher/xyz-456-guid
```

### 3. Recovery Operations

```bash
# Deleted records पहा
GET /api/audit/deleted?table_name=mst_ledger

# Record restore करा
POST /api/audit/restore/42
```

### 4. Compliance & Reporting

```bash
# Monthly audit report
GET /api/audit/stats?company=OM%20ENGINEERING

# Session-wise analysis
GET /api/audit/sessions?limit=30
```

---

## Real-World Example

### Test Results (10 Jan 2026)

Incremental sync run केल्यावर audit trail मध्ये खालील data log झाला:

```json
{
  "by_action": {
    "DELETE": 1700
  },
  "by_table": {
    "mst_stock_item": 1369,
    "mst_ledger": 249,
    "mst_group": 29,
    "mst_vouchertype": 27,
    "mst_uom": 18,
    "mst_stock_group": 6,
    "mst_cost_category": 1,
    "mst_godown": 1
  },
  "pending_deleted_records": 1700
}
```

**Analysis:**
- Total 1700 records delete झाले (Tally मधून removed)
- सर्वात जास्त stock items (1369) delete झाले
- 249 ledgers delete झाले
- सर्व deleted records `deleted_records` table मध्ये stored आहेत
- कधीही restore करता येतील

---

## Best Practices

### 1. Regular Monitoring
```bash
# Daily check
GET /api/audit/stats
```

### 2. Before Major Changes
```bash
# Check pending deletes
GET /api/audit/deleted?table_name=mst_ledger
```

### 3. After Sync Issues
```bash
# Check last session
GET /api/audit/sessions?limit=1
GET /api/audit/session/{session_id}
```

### 4. Periodic Cleanup (Optional)
Audit data permanently ठेवला जातो. जर storage issue असेल तर manual cleanup करता येतो.

---

## Technical Notes

### Performance
- Audit writes are **synchronous** (not async) to ensure data integrity
- Indexes on frequently queried columns
- JSON storage for flexible schema

### Storage
- Each audit record ~1-2 KB
- Deleted records store full data (~2-5 KB each)
- No auto-cleanup (data retained permanently)

### Limitations
- Full sync doesn't log individual records (too many)
- Only incremental sync generates audit trail
- Large syncs may slow down due to audit logging

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| v2.3.0 | 10 Jan 2026 | Initial audit trail implementation |

---

## Support

For issues or questions:
- GitHub: https://github.com/ganeshchavan786/tally-fastapi
- Check `/docs` endpoint for API documentation
