from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.recruitment.models import HiringReason
from app.modules.recruitment import schemas

# --- HIRING REASON MANAGEMENT ---

async def get_hiring_reasons(db: AsyncSession) -> List[HiringReason]:
    """Obtiene todos los motivos de contratación configurados."""
    stmt = select(HiringReason).order_by(HiringReason.name)
    return (await db.execute(stmt)).scalars().all()


async def get_hiring_reason_by_id(
    db: AsyncSession, reason_id: int
) -> Optional[HiringReason]:
    """Obtiene el detalle de un motivo de contratación específico."""
    return await db.get(HiringReason, reason_id)


async def create_hiring_reason(
    db: AsyncSession, reason_in: schemas.HiringReasonCreate
) -> HiringReason:
    """Crea un nuevo motivo de contratación."""
    reason = HiringReason(**reason_in.model_dump())
    db.add(reason)
    await db.commit()
    await db.refresh(reason)
    return reason


async def update_hiring_reason(
    db: AsyncSession, reason_id: int, reason_in: schemas.HiringReasonUpdate
) -> Optional[HiringReason]:
    """Actualiza un motivo de contratación existente."""
    reason = await db.get(HiringReason, reason_id)
    if not reason:
        return None
    for key, value in reason_in.model_dump(exclude_unset=True).items():
        setattr(reason, key, value)
    await db.commit()
    await db.refresh(reason)
    return reason


async def delete_hiring_reason(db: AsyncSession, reason_id: int) -> bool:
    """Elimina un motivo de contratación."""
    # NOTE: Add check for usage in Vacancies if/when we link them in the future.
    # Currently, Vacancy model does not have hiring_reason_id, but it might be added later.
    reason = await db.get(HiringReason, reason_id)
    if not reason:
        return False
    await db.delete(reason)
    await db.commit()
    return True
