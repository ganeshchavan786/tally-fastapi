"""
Sync Queue Service Module
Handles sequential sync of multiple companies
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum

from ..utils.logger import logger


class QueueItemStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SyncQueueService:
    """Service for managing sync queue for multiple companies"""
    
    def __init__(self):
        self.queue: List[Dict[str, Any]] = []
        self.current_index: int = -1
        self.is_processing: bool = False
        self.total_companies: int = 0
        self.completed_count: int = 0
        self.failed_count: int = 0
    
    def get_status(self) -> Dict[str, Any]:
        """Get current queue status"""
        current_company = None
        if 0 <= self.current_index < len(self.queue):
            current_company = self.queue[self.current_index]
        
        return {
            "is_processing": self.is_processing,
            "total_companies": self.total_companies,
            "completed_count": self.completed_count,
            "failed_count": self.failed_count,
            "current_index": self.current_index,
            "current_company": current_company,
            "queue": self.queue
        }
    
    def add_companies(self, companies: List[str], sync_type: str = "full") -> Dict[str, Any]:
        """Add multiple companies to sync queue"""
        if self.is_processing:
            return {"status": "error", "message": "Queue is already processing"}
        
        # Clear previous queue
        self.queue = []
        self.current_index = -1
        self.completed_count = 0
        self.failed_count = 0
        
        # Add companies to queue
        for company in companies:
            self.queue.append({
                "company": company,
                "sync_type": sync_type,
                "status": QueueItemStatus.PENDING,
                "started_at": None,
                "completed_at": None,
                "rows_processed": 0,
                "error": None
            })
        
        self.total_companies = len(self.queue)
        logger.info(f"Added {self.total_companies} companies to sync queue")
        
        return {
            "status": "success",
            "message": f"Added {self.total_companies} companies to queue",
            "queue": self.queue
        }
    
    async def start_processing(self) -> Dict[str, Any]:
        """Start processing the queue"""
        if self.is_processing:
            return {"status": "error", "message": "Queue is already processing"}
        
        if not self.queue:
            return {"status": "error", "message": "Queue is empty"}
        
        self.is_processing = True
        self.current_index = 0
        
        # Start async processing
        asyncio.create_task(self._process_queue())
        
        return {
            "status": "started",
            "message": f"Started processing {self.total_companies} companies"
        }
    
    async def _process_queue(self):
        """Process queue items one by one"""
        from .sync_service import sync_service
        
        while self.current_index < len(self.queue) and self.is_processing:
            item = self.queue[self.current_index]
            company = item["company"]
            sync_type = item["sync_type"]
            
            logger.info(f"Starting sync for company: {company} ({self.current_index + 1}/{self.total_companies})")
            
            # Update item status
            item["status"] = QueueItemStatus.RUNNING
            item["started_at"] = datetime.now().isoformat()
            
            try:
                # Run sync with company parameter
                if sync_type == "full":
                    result = await sync_service.full_sync(company=company)
                else:
                    result = await sync_service.incremental_sync(company=company)
                
                # Update item with result
                if result.get("status") == "completed":
                    item["status"] = QueueItemStatus.COMPLETED
                    item["rows_processed"] = result.get("rows_processed", 0)
                    self.completed_count += 1
                elif result.get("status") == "cancelled":
                    item["status"] = QueueItemStatus.CANCELLED
                    break
                else:
                    item["status"] = QueueItemStatus.FAILED
                    item["error"] = result.get("error_message", "Unknown error")
                    self.failed_count += 1
                
            except Exception as e:
                item["status"] = QueueItemStatus.FAILED
                item["error"] = str(e)
                self.failed_count += 1
                logger.error(f"Sync failed for {company}: {e}")
            
            item["completed_at"] = datetime.now().isoformat()
            self.current_index += 1
        
        self.is_processing = False
        logger.info(f"Queue processing complete. Completed: {self.completed_count}, Failed: {self.failed_count}")
    
    def cancel_queue(self) -> Dict[str, Any]:
        """Cancel queue processing"""
        if not self.is_processing:
            return {"status": "error", "message": "Queue is not processing"}
        
        from .sync_service import sync_service
        sync_service.cancel()
        self.is_processing = False
        
        # Mark remaining items as cancelled
        for i in range(self.current_index + 1, len(self.queue)):
            self.queue[i]["status"] = QueueItemStatus.CANCELLED
        
        return {"status": "cancelled", "message": "Queue cancelled"}
    
    def clear_queue(self) -> Dict[str, Any]:
        """Clear the queue"""
        if self.is_processing:
            return {"status": "error", "message": "Cannot clear while processing"}
        
        self.queue = []
        self.current_index = -1
        self.total_companies = 0
        self.completed_count = 0
        self.failed_count = 0
        
        return {"status": "success", "message": "Queue cleared"}


# Global service instance
sync_queue_service = SyncQueueService()
