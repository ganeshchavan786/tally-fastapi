"""
Sync Controller
Handles sync-related API endpoints
"""

from fastapi import APIRouter, BackgroundTasks
from typing import Optional

from ..services.sync_service import sync_service
from ..utils.logger import logger

router = APIRouter()


@router.post("/full")
async def trigger_full_sync(background_tasks: BackgroundTasks):
    """Trigger full data synchronization"""
    logger.info("Full sync requested")
    background_tasks.add_task(sync_service.full_sync)
    return {
        "status": "started",
        "message": "Full sync started in background"
    }


@router.post("/incremental")
async def trigger_incremental_sync(background_tasks: BackgroundTasks):
    """Trigger incremental data synchronization"""
    logger.info("Incremental sync requested")
    # TODO: Implement incremental sync
    return {
        "status": "not_implemented",
        "message": "Incremental sync not yet implemented"
    }


@router.get("/status")
async def get_sync_status():
    """Get current sync status"""
    return sync_service.get_status()


@router.post("/cancel")
async def cancel_sync():
    """Cancel running sync"""
    if sync_service.cancel():
        return {"status": "cancelled", "message": "Sync cancellation requested"}
    return {"status": "not_running", "message": "No sync is currently running"}
