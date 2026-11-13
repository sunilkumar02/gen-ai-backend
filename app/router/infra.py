import logging

from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.database import engine

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Infrastructure"])


@router.get("/health")
async def health_check():
    return {"status": "ok"}



@router.get("/health/db")
async def database_health():
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as exc:
        logger.warning("Database health check failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        ) from exc

    return {"status": "ok", "database": "reachable"}

