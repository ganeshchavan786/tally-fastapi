"""
Log Controller
Handles log viewing API endpoints
"""

from fastapi import APIRouter, Query
from fastapi.responses import Response
from typing import Optional

from ..services.log_service import log_service
from ..utils.logger import logger

router = APIRouter()


@router.get("")
async def get_logs(
    limit: int = Query(default=100, le=1000),
    level: Optional[str] = None
):
    """Get recent logs"""
    logs = log_service.get_recent_logs(limit=limit, level=level)
    return {
        "count": len(logs),
        "logs": logs
    }


@router.get("/download")
async def download_logs():
    """Download log file"""
    content = log_service.download_logs()
    if content:
        return Response(
            content=content,
            media_type="text/plain",
            headers={"Content-Disposition": "attachment; filename=app.log"}
        )
    return {"error": "Log file not found"}


@router.delete("/clear")
async def clear_logs():
    """Clear log file"""
    if log_service.clear_logs():
        return {"status": "success", "message": "Logs cleared"}
    return {"status": "error", "message": "Failed to clear logs"}


@router.get("/size")
async def get_log_size():
    """Get log file size"""
    size = log_service.get_log_file_size()
    return {"size_bytes": size}
