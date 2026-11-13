from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.db.database import get_db
from app.models import User
from app.passwords import password_hasher
from app.schemas import UserCreate, UserRead, UserUpdate

Database = Annotated[AsyncSession, Depends(get_db)]

router = APIRouter(prefix="/users", tags=["Users"])


async def save_user(db: AsyncSession, user: User) -> User:
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email is already registered") from None
    await db.refresh(user)
    return user


async def find_user(user_id: UUID, db: Database) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


async def ensure_email_available(
    db: AsyncSession, email: str, user_id: UUID | None = None
) -> None:
    query = select(User.id).where(func.lower(User.email) == email.lower())
    if user_id is not None:
        query = query.where(User.id != user_id)
    if await db.scalar(query):
        raise HTTPException(status_code=409, detail="Email is already registered")


@router.post("", response_model=UserRead, status_code=201)
async def create_user(body: UserCreate, db: Database):
    await ensure_email_available(db, body.email)
    user = User(
        email=body.email, name=body.name,
        password_hash=await run_in_threadpool(password_hasher.hash, body.password.get_secret_value()),
    )
    db.add(user)
    return await save_user(db, user)


@router.get("", response_model=list[UserRead])
async def list_users(
    db: Database,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    query = select(User).order_by(User.created_at, User.id).offset(offset).limit(limit)
    return (await db.scalars(query)).all()


@router.get("/{user_id}", response_model=UserRead)
async def read_user(user_id: UUID, db: Database):
    return await find_user(user_id, db)


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(user_id: UUID, body: UserUpdate, db: Database):
    user = await find_user(user_id, db)
    changes = body.model_dump(exclude_unset=True)
    if "email" in changes:
        await ensure_email_available(db, changes["email"], user_id)
        user.email = changes["email"]
    if "name" in changes:
        user.name = changes["name"]
    if "password" in changes:
        user.password_hash = await run_in_threadpool(
            password_hasher.hash, body.password.get_secret_value()
        )
    return await save_user(db, user)


@router.delete("/{user_id}", status_code=204)
async def delete_user(user_id: UUID, db: Database):
    user = await find_user(user_id, db)
    await db.delete(user)
    await db.commit()
    return Response(status_code=204)
