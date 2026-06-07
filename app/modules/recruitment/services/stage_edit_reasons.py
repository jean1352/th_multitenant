from typing import List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.recruitment.models import StageEditReason
from app.modules.recruitment import schemas


async def get_stage_edit_reasons(
    db: AsyncSession, active_only: bool = False
) -> List[StageEditReason]:
    stmt = select(StageEditReason).order_by(StageEditReason.name)
    if active_only:
        stmt = stmt.where(StageEditReason.is_active == True)
    return (await db.execute(stmt)).scalars().all()


async def get_stage_edit_reason_by_id(
    db: AsyncSession, reason_id: int
) -> Optional[StageEditReason]:
    return await db.get(StageEditReason, reason_id)


async def create_stage_edit_reason(
    db: AsyncSession, reason_in: schemas.StageEditReasonCreate
) -> StageEditReason:
    new_reason = StageEditReason(
        name=reason_in.name,
        is_active=reason_in.is_active
    )
    db.add(new_reason)
    await db.commit()
    await db.refresh(new_reason)
    return new_reason


async def update_stage_edit_reason(
    db: AsyncSession, reason_id: int, reason_in: schemas.StageEditReasonUpdate
) -> Optional[StageEditReason]:
    reason = await db.get(StageEditReason, reason_id)
    if not reason:
        return None
    
    reason.name = reason_in.name
    reason.is_active = reason_in.is_active
    
    await db.commit()
    await db.refresh(reason)
    return reason


async def delete_stage_edit_reason(db: AsyncSession, reason_id: int) -> bool:
    reason = await db.get(StageEditReason, reason_id)
    if not reason:
        return False
    
    await db.delete(reason)
    await db.commit()
    return True
