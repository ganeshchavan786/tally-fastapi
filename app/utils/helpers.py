"""
Helper Functions Module
Utility functions used across the application
"""

import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET


def parse_tally_date(date_str: str) -> Optional[str]:
    """Parse Tally date format to ISO format (YYYY-MM-DD)"""
    if not date_str or date_str == "ñ":
        return None
    try:
        # Clean up the date string
        date_str = date_str.strip()
        
        # Format: YYYYMMDD (e.g., 20210401)
        if len(date_str) == 8 and date_str.isdigit():
            return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        
        # Format: d-MMM-yy or dd-MMM-yy (e.g., 1-Apr-21, 01-Apr-21)
        # Also handles malformed: 1-Ap-r--21
        date_str = date_str.replace('--', '-').replace('- ', '-').replace(' -', '-')
        
        month_map = {
            'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04',
            'may': '05', 'jun': '06', 'jul': '07', 'aug': '08',
            'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12'
        }
        
        # Try to parse d-MMM-yy format
        parts = date_str.split('-')
        if len(parts) >= 3:
            day = parts[0].zfill(2)
            month_str = ''.join(parts[1:-1]).lower()[:3]  # Handle split month like "Ap-r"
            year = parts[-1]
            
            if month_str in month_map:
                month = month_map[month_str]
                # Convert 2-digit year to 4-digit
                if len(year) == 2:
                    year = '20' + year if int(year) < 50 else '19' + year
                return f"{year}-{month}-{day}"
        
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
