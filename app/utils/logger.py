"""
Logger Module
Centralized logging using Loguru
"""

import sys
from pathlib import Path
from loguru import logger as _logger
from typing import Optional


def setup_logger(
    level: str = "INFO",
    log_file: str = "./logs/app.log",
    max_size: int = 10,
    backup_count: int = 5,
    console: bool = True,
    colorize: bool = True
) -> None:
    """Setup logger with file and console handlers"""
    
    # Remove default handler
    _logger.remove()
    
    # Create logs directory if not exists
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Console handler
    if console:
        _logger.add(
            sys.stdout,
            level=level,
            format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{module}</cyan>:<cyan>{function}</cyan> | <level>{message}</level>",
            colorize=colorize
        )
    
    # File handler with rotation
    _logger.add(
        log_file,
        level=level,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {module}:{function} | {message}",
        rotation=f"{max_size} MB",
        retention=backup_count,
        encoding="utf-8"
    )


# Export logger instance
logger = _logger
