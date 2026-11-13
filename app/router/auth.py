from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.db.database import get_db
from app.models import User
from app.passwords import verify_password
from app.schema.auth import LoginRequest
from app.schema.users import UserRead

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=UserRead)
async def login(
    body: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    response: Response,
):
    user = await db.scalar(select(User).where(func.lower(User.email) == body.username))
    valid = await run_in_threadpool(
        verify_password, body.password.get_secret_value(), user.password_hash if user else None
    )
    if not valid:
        raise HTTPException(status_code=403, detail="Invalid username or password")
    response.headers["Cache-Control"] = "no-store"
    return user
