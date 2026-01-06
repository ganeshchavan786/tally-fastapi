"""
Log Service Module
Handles log management and streaming
"""

import os
from pathlib import Path
from typing import List, Optional
from datetime import datetime

from ..config import config
from ..utils.logger import logger


class LogService:
    """Service for log management"""
    
    def __init__(self):
        self.log_file = config.logging.file
        self.max_lines = 1000
    
    def get_recent_logs(self, limit: int = 100, level: Optional[str] = None) -> List[dict]:
        """Get recent log entries"""
        logs = []
        try:
            log_path = Path(self.log_file)
            if not log_path.exists():
                return []
            
            with open(log_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # Get last N lines
            recent_lines = lines[-limit:] if len(lines) > limit else lines
            
            for line in recent_lines:
                log_entry = self._parse_log_line(line)
                if log_entry:
                    if level is None or log_entry.get('level') == level.upper():
                        logs.append(log_entry)
        except Exception as e:
            logger.error(f"Failed to read logs: {e}")
        
        return logs
    
    def _parse_log_line(self, line: str) -> Optional[dict]:
        """Parse a log line into structured format"""
        try:
            # Format: [TIMESTAMP] | [LEVEL] | [MODULE]:[FUNCTION] | [MESSAGE]
            parts = line.strip().split(' | ')
            if len(parts) >= 4:
                return {
                    'timestamp': parts[0].strip(),
                    'level': parts[1].strip(),
                    'source': parts[2].strip(),
                    'message': ' | '.join(parts[3:])
                }
        except:
            pass
        return None
    
    def clear_logs(self) -> bool:
        """Clear log file"""
        try:
            log_path = Path(self.log_file)
            if log_path.exists():
                with open(log_path, 'w', encoding='utf-8') as f:
                    f.write('')
                logger.info("Log file cleared")
                return True
        except Exception as e:
            logger.error(f"Failed to clear logs: {e}")
        return False
    
    def get_log_file_size(self) -> int:
        """Get log file size in bytes"""
        try:
            return Path(self.log_file).stat().st_size
        except:
            return 0
    
    def download_logs(self) -> Optional[bytes]:
        """Get log file content for download"""
        try:
            log_path = Path(self.log_file)
            if log_path.exists():
                return log_path.read_bytes()
        except Exception as e:
            logger.error(f"Failed to read log file: {e}")
        return None


# Global service instance
log_service = LogService()
