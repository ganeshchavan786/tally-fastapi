"""
Sync Controller
===============
API endpoints for data synchronization operations.

ENDPOINTS:
---------
POST /api/sync/full          - Start full sync (replaces all data)
POST /api/sync/incremental   - Start incremental sync (only changes)
GET  /api/sync/status        - Get current sync status
POST /api/sync/cancel        - Cancel running sync
GET  /api/sync/history       - Get sync history

QUEUE ENDPOINTS (Multi-Company):
-------------------------------
POST   /api/sync/queue        - Add companies to queue
POST   /api/sync/queue/start  - Start processing queue
GET    /api/sync/queue/status - Get queue status
DELETE /api/sync/queue        - Clear queue

USAGE:
-----
1. Single Company Sync:
   POST /api/sync/full?company=CompanyName

2. Multi-Company Sync:
   POST /api/sync/queue
   Body: {"companies": ["Company1", "Company2"], "sync_type": "full"}
   POST /api/sync/queue/start

BACKGROUND TASKS:
----------------
Sync operations run in background (BackgroundTasks).
Use /api/sync/status to monitor progress.
"""

from fastapi import APIRouter, BackgroundTasks
from typing import Optional, List
from pydantic import BaseModel

from ..services.sync_service import sync_service
from ..services.sync_queue_service import sync_queue_service
from ..utils.logger import logger

router = APIRouter()


class QueueRequest(BaseModel):
    companies: List[str]
    sync_type: str = "full"


@router.post("/full")
async def trigger_full_sync(background_tasks: BackgroundTasks, company: str = ""):
    """Trigger full data synchronization"""
    logger.info(f"Full sync requested for company: {company or 'Default'}")
    background_tasks.add_task(sync_service.full_sync, company)
    return {
        "status": "started",
        "message": f"Full sync started for {company or 'Default'}"
    }


@router.post("/incremental")
async def trigger_incremental_sync(background_tasks: BackgroundTasks, company: str = ""):
    """Trigger incremental data synchronization (only changed records)"""
    logger.info(f"Incremental sync requested for company: {company or 'Default'}")
    background_tasks.add_task(sync_service.incremental_sync, company)
    return {
        "status": "started",
        "message": f"Incremental sync started for {company or 'Default'}"
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


@router.get("/history")
async def get_sync_history(limit: int = 50):
    """Get sync history records"""
    history = await sync_service.get_sync_history(limit)
    return {"history": history, "count": len(history)}


# Queue endpoints for multi-company sync
@router.post("/queue")
async def add_to_queue(request: QueueRequest):
    """Add multiple companies to sync queue"""
    return sync_queue_service.add_companies(request.companies, request.sync_type)


@router.post("/queue/start")
async def start_queue():
    """Start processing the sync queue"""
    return await sync_queue_service.start_processing()


@router.get("/queue/status")
async def get_queue_status():
    """Get current queue status"""
    return sync_queue_service.get_status()


@router.post("/queue/cancel")
async def cancel_queue():
    """Cancel queue processing"""
    return sync_queue_service.cancel_queue()


@router.post("/queue/clear")
async def clear_queue():
    """Clear the sync queue"""
    return sync_queue_service.clear_queue()
