"""
Health Models
Pydantic models for health checks
"""

from typing import Dict, Optional
from pydantic import BaseModel


class ComponentHealth(BaseModel):
    status: str
    message: str = ""


class TallyHealth(ComponentHealth):
    server: str
    port: int


class DatabaseHealth(ComponentHealth):
    path: str
    size_bytes: int = 0
    total_rows: int = 0


class HealthCheckResponse(BaseModel):
    status: str
    timestamp: str
    components: Dict[str, ComponentHealth]
