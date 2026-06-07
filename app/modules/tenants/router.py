from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.core.database import get_db
from app.modules.tenants import schemas, service, models

router = APIRouter(prefix="/tenants", tags=["Tenants"])

@router.post("/", response_model=schemas.Tenant, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    tenant_in: schemas.TenantCreate,
    db: AsyncSession = Depends(get_db)
):
    # Verificar si el subdominio ya existe
    existing = await service.get_tenant_by_subdomain(db, tenant_in.subdomain)
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"El subdominio '{tenant_in.subdomain}' ya está en uso."
        )
    
    return await service.create_tenant(db, name=tenant_in.name, subdomain=tenant_in.subdomain)

@router.get("/", response_model=List[schemas.Tenant])
async def list_tenants(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.Tenant))
    return result.scalars().all()
