"""
Config Models
Pydantic models for configuration
"""

from typing import List, Optional
from pydantic import BaseModel


class TallyConfigModel(BaseModel):
    server: str = "localhost"
    port: int = 9000
    company: str = ""
    from_date: str = "2025-04-01"
    to_date: str = "2026-03-31"


class DatabaseConfigModel(BaseModel):
    path: str = "./tally.db"


class SyncConfigModel(BaseModel):
    mode: str = "full"
    batch_size: int = 1000


class ConfigUpdateRequest(BaseModel):
    tally: Optional[TallyConfigModel] = None
    database: Optional[DatabaseConfigModel] = None
    sync: Optional[SyncConfigModel] = None
