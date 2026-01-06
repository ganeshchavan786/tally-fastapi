"""
JSON View
Formats responses as JSON
"""

from typing import Any, Dict, List, Optional
from datetime import datetime


class JsonView:
    """JSON response formatter"""
    
    @staticmethod
    def success(message: str = "", data: Any = None) -> Dict:
        """Format success response"""
        return {
            "status": "success",
            "message": message,
            "data": data,
            "timestamp": datetime.now().isoformat()
        }
    
    @staticmethod
    def error(code: str, message: str, details: Optional[str] = None) -> Dict:
        """Format error response"""
        return {
            "error": True,
            "code": code,
            "message": message,
            "details": details,
            "timestamp": datetime.now().isoformat()
        }
    
    @staticmethod
    def paginated(data: List, total: int, limit: int, offset: int) -> Dict:
        """Format paginated response"""
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "count": len(data),
            "data": data
        }
    
    @staticmethod
    def table_data(columns: List[str], rows: List[Dict], row_count: int) -> Dict:
        """Format table data response"""
        return {
            "columns": columns,
            "data": rows,
            "row_count": row_count
        }
