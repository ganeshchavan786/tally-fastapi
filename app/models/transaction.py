"""
Transaction Data Models
Pydantic models for transaction data
"""

from typing import Optional
from pydantic import BaseModel


class Voucher(BaseModel):
    guid: str
    date: str = ""
    voucher_type: str = ""
    voucher_number: str = ""
    reference_number: str = ""
    reference_date: Optional[str] = None
    narration: str = ""
    party_name: str = ""
    place_of_supply: str = ""
    is_invoice: int = 0
    is_accounting_voucher: int = 0
    is_inventory_voucher: int = 0
    is_order_voucher: int = 0
    is_cancelled: int = 0
    is_optional: int = 0


class AccountingEntry(BaseModel):
    id: Optional[int] = None
    guid: str
    ledger: str = ""
    amount: float = 0.0
    amount_forex: float = 0.0
    currency: str = ""
    is_party_ledger: int = 0


class InventoryEntry(BaseModel):
    id: Optional[int] = None
    guid: str
    stock_item: str = ""
    quantity: float = 0.0
    rate: float = 0.0
    amount: float = 0.0
    godown: str = ""
    tracking_number: str = ""


class BillAllocation(BaseModel):
    id: Optional[int] = None
    guid: str
    ledger: str = ""
    bill_type: str = ""
    bill_name: str = ""
    amount: float = 0.0


class BankAllocation(BaseModel):
    id: Optional[int] = None
    guid: str
    ledger: str = ""
    transaction_type: str = ""
    instrument_number: str = ""
    instrument_date: Optional[str] = None
    bank_name: str = ""
