from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models import Thread, User
from app.schema.thread import CreateThread, ReadThread, UpdateThread


Database = Annotated[AsyncSession, Depends(get_db)]

router = APIRouter(prefix="/thread", tags=["threads"])


async def find_thread(thread_id: UUID, db: AsyncSession) -> Thread:
    thread = await db.get(Thread, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread


async def save_thread(db: AsyncSession, thread: Thread) -> Thread:
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="Thread could not be saved because its user is no longer available"
        ) from None
    await db.refresh(thread)
    return thread


@router.post("", response_model=ReadThread, status_code=201)
async def create_thread(body: CreateThread, db: Database):
    if await db.get(User, body.user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    thread = Thread(user_id=body.user_id, title=body.title)
    db.add(thread)
    return await save_thread(db, thread)


@router.get("", response_model=list[ReadThread])
async def list_threads(
    db: Database,
    user_id: UUID | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    query = select(Thread)
    if user_id is not None:
        query = query.where(Thread.user_id == user_id)
    query = query.order_by(Thread.created_at.desc(), Thread.id.desc()).offset(offset).limit(limit)
    return (await db.scalars(query)).all()


@router.get("/{thread_id}", response_model=ReadThread)
async def read_thread(thread_id: UUID, db: Database):
    return await find_thread(thread_id, db)


@router.patch("/{thread_id}", response_model=ReadThread)
async def update_thread(thread_id: UUID, body: UpdateThread, db: Database):
    thread = await find_thread(thread_id, db)
    if "title" in body.model_fields_set:
        thread.title = body.title
    return await save_thread(db, thread)


@router.delete("/{thread_id}", status_code=204)
async def delete_thread(thread_id: UUID, db: Database):
    thread = await find_thread(thread_id, db)
    await db.delete(thread)
    await db.commit()
    return Response(status_code=204)


