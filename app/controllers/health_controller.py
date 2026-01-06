"""
Health Controller
Handles health check API endpoints
"""

from fastapi import APIRouter

from ..services.health_service import health_service
from ..utils.logger import logger

router = APIRouter()


@router.get("")
async def health_check():
    """Complete health check"""
    return await health_service.check_all()


@router.get("/tally")
async def tally_health():
    """Tally connection health check"""
    return await health_service.check_tally()


@router.get("/database")
async def database_health():
    """Database health check"""
    return await health_service.check_database()
