"""
Health Service Module
Handles health checks for system components
"""

from datetime import datetime
from typing import Any, Dict

from ..config import config
from ..utils.logger import logger
from ..utils.constants import HealthStatus
from .tally_service import tally_service
from .database_service import database_service


class HealthService:
    """Service for health monitoring"""
    
    async def check_all(self) -> Dict[str, Any]:
        """Check health of all components"""
        tally_health = await self.check_tally()
        database_health = await self.check_database()
        
        # Overall status
        if tally_health['status'] == HealthStatus.HEALTHY and database_health['status'] == HealthStatus.HEALTHY:
            overall_status = HealthStatus.HEALTHY
        elif tally_health['status'] == HealthStatus.UNHEALTHY and database_health['status'] == HealthStatus.UNHEALTHY:
            overall_status = HealthStatus.UNHEALTHY
        else:
            overall_status = HealthStatus.DEGRADED
        
        return {
            'status': overall_status,
            'timestamp': datetime.now().isoformat(),
            'components': {
                'tally': tally_health,
                'database': database_health
            }
        }
    
    async def check_tally(self) -> Dict[str, Any]:
        """Check Tally connection health"""
        try:
            result = await tally_service.test_connection()
            if result.get('connected'):
                return {
                    'status': HealthStatus.HEALTHY,
                    'server': config.tally.server,
                    'port': config.tally.port,
                    'message': 'Connected'
                }
            else:
                return {
                    'status': HealthStatus.UNHEALTHY,
                    'server': config.tally.server,
                    'port': config.tally.port,
                    'message': result.get('error', 'Connection failed')
                }
        except Exception as e:
            return {
                'status': HealthStatus.UNHEALTHY,
                'server': config.tally.server,
                'port': config.tally.port,
                'message': str(e)
            }
    
    async def check_database(self) -> Dict[str, Any]:
        """Check database health"""
        try:
            await database_service.connect()
            size = await database_service.get_database_size()
            counts = await database_service.get_all_table_counts()
            total_rows = sum(counts.values())
            await database_service.disconnect()
            
            return {
                'status': HealthStatus.HEALTHY,
                'path': config.database.path,
                'size_bytes': size,
                'total_rows': total_rows,
                'message': 'Connected'
            }
        except Exception as e:
            return {
                'status': HealthStatus.UNHEALTHY,
                'path': config.database.path,
                'message': str(e)
            }


# Global service instance
health_service = HealthService()
