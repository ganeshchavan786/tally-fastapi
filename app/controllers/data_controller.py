"""
Data Controller
Handles data query API endpoints
"""

from fastapi import APIRouter, Query, HTTPException
from typing import Optional, List

from ..services.database_service import database_service
from ..utils.logger import logger

router = APIRouter()


@router.get("/groups")
async def get_groups(
    parent: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0)
):
    """Get all groups"""
    try:
        await database_service.connect()
        
        query = "SELECT * FROM mst_group"
        params = []
        conditions = []
        
        if parent:
            conditions.append("parent = ?")
            params.append(parent)
        if search:
            conditions.append("name LIKE ?")
            params.append(f"%{search}%")
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += f" LIMIT {limit} OFFSET {offset}"
        
        data = await database_service.fetch_all(query, tuple(params))
        total = await database_service.fetch_scalar("SELECT COUNT(*) FROM mst_group")
        
        return {"total": total, "data": data}
    except Exception as e:
        logger.error(f"Failed to get groups: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ledgers")
async def get_ledgers(
    parent: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0)
):
    """Get all ledgers"""
    try:
        await database_service.connect()
        
        query = "SELECT * FROM mst_ledger"
        params = []
        conditions = []
        
        if parent:
            conditions.append("parent = ?")
            params.append(parent)
        if search:
            conditions.append("name LIKE ?")
            params.append(f"%{search}%")
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += f" LIMIT {limit} OFFSET {offset}"
        
        data = await database_service.fetch_all(query, tuple(params))
        total = await database_service.fetch_scalar("SELECT COUNT(*) FROM mst_ledger")
        
        return {"total": total, "data": data}
    except Exception as e:
        logger.error(f"Failed to get ledgers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/vouchers")
async def get_vouchers(
    voucher_type: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0)
):
    """Get vouchers with filters"""
    try:
        await database_service.connect()
        
        query = "SELECT * FROM trn_voucher"
        params = []
        conditions = []
        
        if voucher_type:
            conditions.append("voucher_type = ?")
            params.append(voucher_type)
        if from_date:
            conditions.append("date >= ?")
            params.append(from_date)
        if to_date:
            conditions.append("date <= ?")
            params.append(to_date)
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += f" ORDER BY date DESC LIMIT {limit} OFFSET {offset}"
        
        data = await database_service.fetch_all(query, tuple(params))
        total = await database_service.fetch_scalar("SELECT COUNT(*) FROM trn_voucher")
        
        return {"total": total, "data": data}
    except Exception as e:
        logger.error(f"Failed to get vouchers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stock-items")
async def get_stock_items(
    parent: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0)
):
    """Get all stock items"""
    try:
        await database_service.connect()
        
        query = "SELECT * FROM mst_stock_item"
        params = []
        conditions = []
        
        if parent:
            conditions.append("parent = ?")
            params.append(parent)
        if search:
            conditions.append("name LIKE ?")
            params.append(f"%{search}%")
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += f" LIMIT {limit} OFFSET {offset}"
        
        data = await database_service.fetch_all(query, tuple(params))
        total = await database_service.fetch_scalar("SELECT COUNT(*) FROM mst_stock_item")
        
        return {"total": total, "data": data}
    except Exception as e:
        logger.error(f"Failed to get stock items: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query")
async def execute_query(query_request: dict):
    """Execute custom SQL query (SELECT only)"""
    query = query_request.get("query", "")
    
    # Security: Only allow SELECT queries
    if not query.strip().upper().startswith("SELECT"):
        raise HTTPException(status_code=400, detail="Only SELECT queries are allowed")
    
    try:
        await database_service.connect()
        data = await database_service.fetch_all(query)
        
        return {
            "columns": list(data[0].keys()) if data else [],
            "data": data,
            "row_count": len(data)
        }
    except Exception as e:
        logger.error(f"Query execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/counts")
async def get_table_counts():
    """Get row counts for all tables"""
    try:
        await database_service.connect()
        counts = await database_service.get_all_table_counts()
        return counts
    except Exception as e:
        logger.error(f"Failed to get counts: {e}")
        raise HTTPException(status_code=500, detail=str(e))
