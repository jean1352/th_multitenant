from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.modules.disciplinary import schemas, service
from app.modules.auth.dependencies import is_admin, is_authenticated, is_recruiter, is_manager

router = APIRouter(prefix="/disciplinary", tags=["disciplinary"])

# --- API SANCTIONS ---
@router.post("/api/sanctions", response_model=schemas.SanctionRead)
@is_admin
async def create_sanction_api(
    data: schemas.SanctionCreate, 
    db: Annotated[AsyncSession, Depends(get_db)]
):
    return await service.create_sanction(db, data)

@router.delete("/api/sanctions/{id}", status_code=204)
@is_admin
async def delete_sanction_api(
    id: int, 
    db: Annotated[AsyncSession, Depends(get_db)]
):
    if not await service.delete_sanction(db, id):
        raise HTTPException(404, "Amonestación no encontrada")

# --- API RECOGNITIONS ---
@is_admin
@router.post("/api/recognitions", response_model=schemas.RecognitionRead)
async def create_recognition_api(
    data: schemas.RecognitionCreate, 
    db: Annotated[AsyncSession, Depends(get_db)]
):
    return await service.create_recognition(db, data)

@router.delete("/api/recognitions/{id}", status_code=204)
@is_admin
async def delete_recognition_api(
    id: int, 
    db: Annotated[AsyncSession, Depends(get_db)]
):
    if not await service.delete_recognition(db, id):
        raise HTTPException(404, "Reconocimiento no encontrado")