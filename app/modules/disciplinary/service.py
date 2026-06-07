from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.disciplinary.models import Sanction, Recognition
from app.modules.disciplinary import schemas

async def create_sanction(db: AsyncSession, data: schemas.SanctionCreate) -> Sanction:
    sanction = Sanction(**data.model_dump())
    db.add(sanction)
    await db.commit()
    await db.refresh(sanction)
    return sanction

async def delete_sanction(db: AsyncSession, id: int) -> bool:
    item = await db.get(Sanction, id)
    if not item:
        return False
    await db.delete(item)
    await db.commit()
    return True

async def create_recognition(db: AsyncSession, data: schemas.RecognitionCreate) -> Recognition:
    recog = Recognition(**data.model_dump())
    db.add(recog)
    await db.commit()
    await db.refresh(recog)
    return recog

async def delete_recognition(db: AsyncSession, id: int) -> bool:
    item = await db.get(Recognition, id)
    if not item:
        return False
    await db.delete(item)
    await db.commit()
    return True