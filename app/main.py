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
