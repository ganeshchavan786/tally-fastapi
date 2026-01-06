"""
Master Data Models
Pydantic models for master data
"""

from typing import Optional
from pydantic import BaseModel


class Group(BaseModel):
    guid: str
    name: str = ""
    parent: str = ""
    primary_group: str = ""
    is_revenue: int = 0
    is_deemedpositive: int = 0
    is_subledger: int = 0
    sort_position: int = 0


class Ledger(BaseModel):
    guid: str
    name: str = ""
    parent: str = ""
    alias: str = ""
    opening_balance: float = 0.0
    description: str = ""
    mailing_name: str = ""
    mailing_address: str = ""
    mailing_state: str = ""
    mailing_country: str = ""
    mailing_pincode: str = ""
    email: str = ""
    phone: str = ""
    mobile: str = ""
    contact: str = ""
    pan: str = ""
    gstin: str = ""
    gst_registration_type: str = ""
    is_bill_wise: int = 0
    is_cost_centre: int = 0


class VoucherType(BaseModel):
    guid: str
    name: str = ""
    parent: str = ""
    numbering_method: str = ""
    is_active: int = 1


class StockItem(BaseModel):
    guid: str
    name: str = ""
    parent: str = ""
    category: str = ""
    alias: str = ""
    uom: str = ""
    opening_quantity: float = 0.0
    opening_rate: float = 0.0
    opening_value: float = 0.0
    gst_applicable: str = ""
    hsn_code: str = ""
    gst_rate: float = 0.0


class CostCentre(BaseModel):
    guid: str
    name: str = ""
    parent: str = ""
    category: str = ""


class Employee(BaseModel):
    guid: str
    name: str = ""
    parent: str = ""
    id_number: str = ""
    date_of_joining: Optional[str] = None
    date_of_release: Optional[str] = None
    designation: str = ""
    gender: str = ""
    date_of_birth: Optional[str] = None
    pan: str = ""
    aadhar: str = ""
