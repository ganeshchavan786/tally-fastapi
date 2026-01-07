"""
Scheduler Service Module
Handles scheduled sync operations using APScheduler
"""

import asyncio
from datetime import datetime
from typing import Dict, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ..utils.logger import logger


class SchedulerService:
    """Service for managing scheduled sync jobs"""
    
    def __init__(self):
        self.scheduler: Optional[AsyncIOScheduler] = None
        self.is_running = False
        self.schedule_config = {
            "enabled": False,
            "sync_type": "incremental",  # full or incremental
            "time": "06:00",  # HH:MM format
            "days": ["mon", "tue", "wed", "thu", "fri", "sat"]  # Days to run
        }
    
    def start(self):
        """Start the scheduler"""
        if self.scheduler is None:
            self.scheduler = AsyncIOScheduler()
        
        if not self.scheduler.running:
            self.scheduler.start()
            self.is_running = True
            logger.info("Scheduler started")
    
    def stop(self):
        """Stop the scheduler"""
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            self.is_running = False
            logger.info("Scheduler stopped")
    
    def get_status(self) -> Dict:
        """Get scheduler status"""
        jobs = []
        if self.scheduler:
            for job in self.scheduler.get_jobs():
                next_run = job.next_run_time
                jobs.append({
                    "id": job.id,
                    "name": job.name,
                    "next_run": next_run.isoformat() if next_run else None
                })
        
        return {
            "is_running": self.is_running,
            "schedule_config": self.schedule_config,
            "jobs": jobs
        }
    
    def update_schedule(self, config: Dict) -> Dict:
        """Update schedule configuration"""
        self.schedule_config.update(config)
        
        # Remove existing job if any
        if self.scheduler:
            try:
                self.scheduler.remove_job("auto_sync")
            except:
                pass
        
        # Add new job if enabled
        if self.schedule_config.get("enabled"):
            self._add_sync_job()
            return {"status": "success", "message": "Schedule updated and enabled"}
        else:
            return {"status": "success", "message": "Schedule disabled"}
    
    def _add_sync_job(self):
        """Add sync job to scheduler"""
        if not self.scheduler:
            self.start()
        
        time_str = self.schedule_config.get("time", "06:00")
        hour, minute = map(int, time_str.split(":"))
        days = self.schedule_config.get("days", ["mon", "tue", "wed", "thu", "fri", "sat"])
        
        # Convert days to cron format
        day_of_week = ",".join(days)
        
        trigger = CronTrigger(
            hour=hour,
            minute=minute,
            day_of_week=day_of_week
        )
        
        self.scheduler.add_job(
            self._run_scheduled_sync,
            trigger=trigger,
            id="auto_sync",
            name="Auto Sync",
            replace_existing=True
        )
        
        logger.info(f"Scheduled sync job added: {time_str} on {day_of_week}")
    
    async def _run_scheduled_sync(self):
        """Execute scheduled sync"""
        from .sync_service import sync_service
        
        sync_type = self.schedule_config.get("sync_type", "incremental")
        logger.info(f"Running scheduled {sync_type} sync")
        
        try:
            if sync_type == "full":
                await sync_service.full_sync()
            else:
                await sync_service.incremental_sync()
            logger.info(f"Scheduled {sync_type} sync completed")
        except Exception as e:
            logger.error(f"Scheduled sync failed: {e}")
    
    def run_now(self) -> Dict:
        """Trigger immediate sync based on schedule config"""
        asyncio.create_task(self._run_scheduled_sync())
        return {"status": "started", "message": "Sync triggered manually"}


# Global service instance
scheduler_service = SchedulerService()
