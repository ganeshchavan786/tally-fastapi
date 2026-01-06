"""
Constants Module
Application-wide constants
"""

# Application Info
APP_NAME = "Tally FastAPI Database Loader"
APP_VERSION = "1.0.0"

# Tally XML Constants
TALLY_XML_HEADER = '<?xml version="1.0" encoding="UTF-16"?>'
TALLY_ENVELOPE_START = '<ENVELOPE>'
TALLY_ENVELOPE_END = '</ENVELOPE>'

# Database Tables - Master
MASTER_TABLES = [
    "mst_group",
    "mst_ledger",
    "mst_vouchertype",
    "mst_uom",
    "mst_godown",
    "mst_stock_category",
    "mst_stock_group",
    "mst_stock_item",
    "mst_cost_category",
    "mst_cost_centre",
    "mst_attendance_type",
    "mst_employee",
    "mst_payhead",
    "mst_gst_effective_rate",
    "mst_opening_batch_allocation",
    "mst_opening_bill_allocation",
    "mst_stockitem_standard_cost",
    "mst_stockitem_standard_price"
]

# Database Tables - Transaction
TRANSACTION_TABLES = [
    "trn_voucher",
    "trn_accounting",
    "trn_inventory",
    "trn_cost_centre",
    "trn_cost_category_centre",
    "trn_cost_inventory_category_centre",
    "trn_bill",
    "trn_bank",
    "trn_batch",
    "trn_inventory_accounting",
    "trn_employee",
    "trn_payhead",
    "trn_attendance",
    "trn_closingstock_ledger"
]

# All Tables
ALL_TABLES = MASTER_TABLES + TRANSACTION_TABLES

# Error Codes
class ErrorCode:
    TALLY_CONNECTION_FAILED = "TALLY_CONNECTION_FAILED"
    TALLY_COMPANY_NOT_FOUND = "TALLY_COMPANY_NOT_FOUND"
    DATABASE_ERROR = "DATABASE_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    SYNC_IN_PROGRESS = "SYNC_IN_PROGRESS"
    SYNC_CANCELLED = "SYNC_CANCELLED"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"

# Sync Status
class SyncStatus:
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

# Health Status
class HealthStatus:
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DEGRADED = "degraded"
