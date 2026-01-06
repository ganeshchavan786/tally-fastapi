"""
Debug Controller
Handles debug mode API endpoints
"""

from fastapi import APIRouter

from ..config import config, save_config
from ..utils.logger import logger
from ..services.tally_service import tally_service
from ..services.xml_builder import xml_builder

router = APIRouter()


@router.get("/test-tally/{table_name}")
async def test_tally_table(table_name: str):
    """Test Tally connection and show raw response for a table"""
    # Find table config
    all_tables = xml_builder.get_all_tables()
    table_config = None
    for t in all_tables:
        if t.get("name") == table_name:
            table_config = t
            break
    
    if not table_config:
        return {"error": f"Table {table_name} not found"}
    
    try:
        xml_request = xml_builder.build_export_xml(table_config)
        response = await tally_service.send_xml(xml_request)
        
        # Count F01 occurrences to estimate rows
        f01_count = response.count("<F01>")
        
        return {
            "table": table_name,
            "request_length": len(xml_request),
            "response_length": len(response),
            "estimated_rows": f01_count,
            "response_preview": response[:2000] if len(response) > 2000 else response
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/status")
async def get_debug_status():
    """Get debug mode status"""
    return {
        "enabled": config.debug.enabled,
        "verbose_logging": config.debug.verbose_logging,
        "log_sql_queries": config.debug.log_sql_queries,
        "log_timing": config.debug.log_timing,
        "log_memory": config.debug.log_memory,
        "log_http_details": config.debug.log_http_details
    }


@router.post("/enable")
async def enable_debug():
    """Enable debug mode"""
    config.debug.enabled = True
    config.debug.verbose_logging = True
    config.debug.log_sql_queries = True
    config.debug.log_timing = True
    save_config(config)
    
    logger.info("Debug mode enabled")
    return {"status": "enabled", "message": "Debug mode enabled"}


@router.post("/disable")
async def disable_debug():
    """Disable debug mode"""
    config.debug.enabled = False
    config.debug.verbose_logging = False
    config.debug.log_sql_queries = False
    config.debug.log_timing = False
    config.debug.log_memory = False
    config.debug.log_http_details = False
    save_config(config)
    
    logger.info("Debug mode disabled")
    return {"status": "disabled", "message": "Debug mode disabled"}


@router.put("/settings")
async def update_debug_settings(settings: dict):
    """Update specific debug settings"""
    for key, value in settings.items():
        if hasattr(config.debug, key):
            setattr(config.debug, key, value)
    
    save_config(config)
    logger.info(f"Debug settings updated: {settings}")
    
    return get_debug_status()
