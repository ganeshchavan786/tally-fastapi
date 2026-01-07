"""
Tally FastAPI Database Loader
Main Application Entry Point
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from .config import config
from .utils.logger import setup_logger, logger
from .controllers.sync_controller import router as sync_router
from .controllers.data_controller import router as data_router
from .controllers.config_controller import router as config_router
from .controllers.health_controller import router as health_router
from .controllers.log_controller import router as log_router
from .controllers.debug_controller import router as debug_router


# Setup logging
setup_logger(
    level=config.logging.level,
    log_file=config.logging.file,
    max_size=config.logging.max_size,
    backup_count=config.logging.backup_count,
    console=config.logging.console,
    colorize=config.logging.colorize
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    logger.info("Tally FastAPI Database Loader starting...")
    logger.info(f"API running on http://{config.api.host}:{config.api.port}")
    yield
    logger.info("Tally FastAPI Database Loader shutting down...")


# Create FastAPI application
app = FastAPI(
    title="Tally FastAPI Database Loader",
    description="Sync Tally ERP data to SQLite database",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.api.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
static_path = Path(__file__).parent.parent / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

# Include routers
app.include_router(sync_router, prefix="/api/sync", tags=["Sync"])
app.include_router(data_router, prefix="/api/data", tags=["Data"])
app.include_router(config_router, prefix="/api/config", tags=["Config"])
app.include_router(health_router, prefix="/api/health", tags=["Health"])
app.include_router(log_router, prefix="/api/logs", tags=["Logs"])
app.include_router(debug_router, prefix="/api/debug", tags=["Debug"])


@app.get("/")
async def root():
    """Serve the dashboard HTML"""
    html_path = Path(__file__).parent.parent / "static" / "index.html"
    if html_path.exists():
        return FileResponse(str(html_path), media_type="text/html")
    return {
        "name": "Tally FastAPI Database Loader",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs"
    }


@app.get("/api/info")
async def info():
    """System information"""
    return {
        "name": "Tally FastAPI Database Loader",
        "version": "1.0.0",
        "tally": {
            "server": config.tally.server,
            "port": config.tally.port
        },
        "database": {
            "path": config.database.path
        }
    }


@app.post("/api/backup")
async def create_backup():
    """Create database backup before full sync"""
    import shutil
    from datetime import datetime
    
    db_path = Path(config.database.path)
    if not db_path.exists():
        return {"status": "skipped", "message": "No database to backup"}
    
    # Create backups folder
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(exist_ok=True)
    
    # Create backup with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"tally_backup_{timestamp}.db"
    
    try:
        shutil.copy2(db_path, backup_path)
        logger.info(f"Backup created: {backup_path}")
        
        # Keep only last 5 backups
        backups = sorted(backup_dir.glob("tally_backup_*.db"), reverse=True)
        for old_backup in backups[5:]:
            old_backup.unlink()
            logger.info(f"Deleted old backup: {old_backup}")
        
        return {
            "status": "success",
            "backup_path": str(backup_path),
            "message": f"Backup created successfully"
        }
    except Exception as e:
        logger.error(f"Backup failed: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/backups")
async def list_backups():
    """List all available backups"""
    db_path = Path(config.database.path)
    backup_dir = db_path.parent / "backups"
    
    if not backup_dir.exists():
        return {"backups": [], "count": 0}
    
    backups = []
    for backup_file in sorted(backup_dir.glob("tally_backup_*.db"), reverse=True):
        stat = backup_file.stat()
        # Parse timestamp from filename: tally_backup_20260107_110345.db
        filename = backup_file.stem
        try:
            timestamp_str = filename.replace("tally_backup_", "")
            from datetime import datetime
            timestamp = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
            created_at = timestamp.isoformat()
        except:
            created_at = None
        
        backups.append({
            "filename": backup_file.name,
            "path": str(backup_file),
            "size_bytes": stat.st_size,
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "created_at": created_at
        })
    
    return {"backups": backups, "count": len(backups)}


@app.post("/api/backup/restore")
async def restore_backup(request: dict):
    """Restore database from a backup file"""
    import shutil
    
    filename = request.get("filename")
    if not filename:
        return {"status": "error", "message": "Filename is required"}
    
    db_path = Path(config.database.path)
    backup_dir = db_path.parent / "backups"
    backup_path = backup_dir / filename
    
    if not backup_path.exists():
        return {"status": "error", "message": f"Backup file not found: {filename}"}
    
    try:
        # Create a backup of current database before restore
        if db_path.exists():
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            pre_restore_backup = backup_dir / f"pre_restore_{timestamp}.db"
            shutil.copy2(db_path, pre_restore_backup)
            logger.info(f"Pre-restore backup created: {pre_restore_backup}")
        
        # Restore the backup
        shutil.copy2(backup_path, db_path)
        logger.info(f"Database restored from: {backup_path}")
        
        return {
            "status": "success",
            "message": f"Database restored from {filename}",
            "restored_from": str(backup_path)
        }
    except Exception as e:
        logger.error(f"Restore failed: {e}")
        return {"status": "error", "message": str(e)}


# ============== Schedule API ==============
from .services.scheduler_service import scheduler_service

@app.get("/api/schedule")
async def get_schedule():
    """Get current schedule configuration"""
    return scheduler_service.get_status()


@app.post("/api/schedule")
async def update_schedule(config: dict):
    """Update schedule configuration"""
    return scheduler_service.update_schedule(config)


@app.post("/api/schedule/run")
async def run_scheduled_sync():
    """Trigger scheduled sync immediately"""
    return scheduler_service.run_now()


# ============== Crash Recovery API ==============
from .services.sync_service import sync_service as sync_svc

@app.get("/api/sync/incomplete")
async def check_incomplete_sync():
    """Check for incomplete sync from previous crash"""
    incomplete = sync_svc.get_incomplete_sync()
    if incomplete:
        return {"has_incomplete": True, "sync_state": incomplete}
    return {"has_incomplete": False}


@app.post("/api/sync/incomplete/dismiss")
async def dismiss_incomplete_sync():
    """Dismiss incomplete sync warning"""
    return sync_svc.dismiss_incomplete_sync()
