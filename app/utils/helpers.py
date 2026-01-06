"""
Helper Functions Module
Utility functions used across the application
"""

import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET


def parse_tally_date(date_str: str) -> Optional[str]:
    """Parse Tally date format (YYYYMMDD) to ISO format (YYYY-MM-DD)"""
    if not date_str or date_str == "ñ":
        return None
    try:
        if len(date_str) == 8:
            return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        return date_str
    except:
        return None


def parse_tally_amount(amount_str: str) -> float:
    """Parse Tally amount string to float"""
    if not amount_str or amount_str == "ñ":
        return 0.0
    try:
        # Remove any non-numeric characters except minus and decimal
        cleaned = re.sub(r'[^\d.-]', '', amount_str)
        return float(cleaned) if cleaned else 0.0
    except:
        return 0.0


def parse_tally_boolean(bool_str: str) -> int:
    """Parse Tally boolean (Yes/No) to integer (1/0)"""
    if not bool_str:
        return 0
    return 1 if bool_str.upper() in ("YES", "TRUE", "1") else 0


def xml_to_dict(element: ET.Element) -> Dict[str, Any]:
    """Convert XML element to dictionary"""
    result = {}
    for child in element:
        if len(child) == 0:
            result[child.tag] = child.text or ""
        else:
            result[child.tag] = xml_to_dict(child)
    return result


def escape_sql_string(value: str) -> str:
    """Escape single quotes for SQL"""
    if value is None:
        return ""
    return str(value).replace("'", "''")


def get_current_timestamp() -> str:
    """Get current timestamp in ISO format"""
    return datetime.now().isoformat()


def format_file_size(size_bytes: int) -> str:
    """Format file size in human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} TB"


def chunk_list(lst: List[Any], chunk_size: int) -> List[List[Any]]:
    """Split list into chunks of specified size"""
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]
