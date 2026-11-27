from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Annotated, List

from app.core.database import get_db
from app.modules.auth.dependencies import is_superadmin
from app.modules.auth.models import User
from app.modules.tenants import schemas, service, models

router = APIRouter(prefix="/tenants", tags=["Tenants"])


@router.post("/", response_model=schemas.Tenant, status_code=status.HTTP_201_CREATED)
@is_superadmin
async def create_tenant(
    request: Request,
    tenant_in: schemas.TenantCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User,
):
    if getattr(request.state, "tenant", None) is not None:
        raise HTTPException(status_code=403, detail="Acceso denegado: ruta exclusiva de administración global.")

    # Verificar si el subdominio ya existe
    existing = await service.get_tenant_by_subdomain(db, tenant_in.subdomain)
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"El subdominio '{tenant_in.subdomain}' ya está en uso."
        )

    return await service.create_tenant(db, name=tenant_in.name, subdomain=tenant_in.subdomain)


@router.get("/", response_model=List[schemas.Tenant])
@is_superadmin
async def list_tenants(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User,
):
    if getattr(request.state, "tenant", None) is not None:
        raise HTTPException(status_code=403, detail="Acceso denegado: ruta exclusiva de administración global.")
    result = await db.execute(select(models.Tenant))
    return result.scalars().all()
