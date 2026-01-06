"""
Response Models
Pydantic models for API responses
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class SuccessResponse(BaseModel):
    status: str = "success"
    message: str = ""
    data: Optional[Any] = None


class ErrorResponse(BaseModel):
    error: bool = True
    code: str
    message: str
    details: Optional[str] = None
    timestamp: str


class PaginatedResponse(BaseModel):
    total: int
    data: List[Dict[str, Any]]
    limit: int
    offset: int


class SyncStatusResponse(BaseModel):
    status: str
    progress: int
    current_table: str
    rows_processed: int
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None


class QueryResponse(BaseModel):
    columns: List[str]
    data: List[Dict[str, Any]]
    row_count: int
