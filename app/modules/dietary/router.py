from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, Request, Query, HTTPException
from fastapi.responses import HTMLResponse
from app.core.templates import templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.auth.dependencies import is_admin, is_authenticated, is_recruiter, is_manager
from app.modules.dietary import schemas, service
from app.modules.organization.models import Sede, Area
from app.core.config import settings

router = APIRouter(prefix="/dietary", tags=["dietary"])

# --- VISTAS ---

@router.get("/config", response_class=HTMLResponse)
@is_admin
async def config_view(request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: User = Depends(get_current_user)):
    restrictions = await service.get_all(db)
    return templates.TemplateResponse(request=request, name="dietary/index.html", context=
        {"request": request, "restrictions": restrictions, "settings": settings, "current_user": current_user}
    )

@router.get("/types/{id}/employees", response_class=HTMLResponse)
@is_recruiter
async def view_employees_by_restriction(
    id: int,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(1, ge=1),
    q: Optional[str] = None,
    sede_id: Optional[int] = None,
    area_id: Optional[int] = None,
    current_user: User = Depends(get_current_user)
):
    """Vista paginada de empleados con una restricción específica."""
    restriction = await service.get_by_id(db, id)
    if not restriction:
        return templates.TemplateResponse(request=request, name="404.html", context= {"request": request, "settings": settings, "current_user": current_user}, status_code=404)

    # Obtener datos paginados
    pagination = await service.get_employees_paginated(
        db, id, page, 20, q, sede_id, area_id
    )

    # Cargar filtros
    sedes = (await db.execute(select(Sede).order_by(Sede.name))).scalars().all()
    areas = []
    if sede_id:
        areas = (await db.execute(select(Area).where(Area.sede_id == sede_id).order_by(Area.name))).scalars().all()
    else:
        areas = (await db.execute(select(Area).order_by(Area.name))).scalars().all()

    return templates.TemplateResponse(request=request, name="dietary/employees.html", context=
        {
            "request": request,
            "restriction": restriction,
            "pagination": pagination,
            "sedes": sedes,
            "areas": areas,
            "filters": {"q": q, "sede_id": sede_id, "area_id": area_id},
            "settings": settings,
            "current_user": current_user
        }
    )

# --- API ---

@router.get("/api", response_model=List[schemas.DietaryRestrictionRead])
@is_recruiter
async def get_all_api(db: Annotated[AsyncSession, Depends(get_db)]):
    return await service.get_all(db)

@router.post("/api", response_model=schemas.DietaryRestrictionRead)
@is_admin
async def create_api(
    data: schemas.DietaryRestrictionCreate, db: Annotated[AsyncSession, Depends(get_db)]
):
    return await service.create(db, data)

@router.put("/api/{id}", response_model=schemas.DietaryRestrictionRead)
@is_admin
async def update_api(
    id: int, data: schemas.DietaryRestrictionCreate, db: Annotated[AsyncSession, Depends(get_db)]
):
    return await service.update(db, id, data)

@router.delete("/api/{id}", status_code=204)
@is_admin
async def delete_api(
    id: int, db: Annotated[AsyncSession, Depends(get_db)]
):
    await service.delete(db, id)
    return None