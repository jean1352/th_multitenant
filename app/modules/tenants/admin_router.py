from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from app.core.templates import templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Annotated

from app.core.database import get_db
from app.core.config import settings
from app.modules.auth.dependencies import is_superadmin
from app.modules.auth.models import User
from app.modules.auth.schemas import UserCreate as AuthUserCreate
from app.modules.tenants import models, schemas, service

router = APIRouter(prefix="/admin", tags=["SuperAdmin"])

@router.get("", response_class=RedirectResponse)
@router.get("/", response_class=RedirectResponse)
async def admin_root():
    return RedirectResponse(url="/admin/tenants")

@router.get("/tenants", response_class=HTMLResponse)
@is_superadmin
async def admin_tenants_view(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User
):
    # Solo permitir acceso si no hay tenant (estamos en el dominio principal)
    if getattr(request.state, "tenant", None) is not None:
         raise HTTPException(status_code=403, detail="Acceso denegado: Esta ruta solo está disponible en la administración global.")

    result = await db.execute(select(models.Tenant))
    tenants = result.scalars().all()
    
    return templates.TemplateResponse(request=request, name="admin/tenants.html", context={
        "request": request,
        "tenants": tenants,
        "current_user": current_user,
        "settings": settings
    })

@router.get("/users", response_class=HTMLResponse)
@is_superadmin
async def admin_users_view(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User
):
    if getattr(request.state, "tenant", None) is not None:
         raise HTTPException(status_code=403, detail="Acceso denegado: Esta ruta solo está disponible en la administración global.")

    # Listar usuarios globales (en el esquema public)
    result = await db.execute(select(models.Tenant))
    tenants = result.scalars().all()
    
    from app.modules.auth.service import get_users
    users = await get_users(db)
    
    return templates.TemplateResponse(request=request, name="admin/users.html", context={
        "request": request,
        "users": users,
        "tenants": tenants,
        "current_user": current_user,
        "settings": settings
    })

@router.get("/analysis", response_class=HTMLResponse)
@is_superadmin
async def admin_analysis_view(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User
):
    if getattr(request.state, "tenant", None) is not None:
         raise HTTPException(status_code=403, detail="Acceso denegado: Esta ruta solo está disponible en la administración global.")

    # Placeholder for global platform metrics
    return templates.TemplateResponse(request=request, name="admin/analysis.html", context={
        "request": request,
        "current_user": current_user,
        "settings": settings
    })

# API for SuperAdmin to create tenants
@router.post("/api/tenants", status_code=status.HTTP_201_CREATED)
@is_superadmin
async def admin_create_tenant(
    tenant_in: schemas.TenantCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User
):
    existing = await service.get_tenant_by_subdomain(db, tenant_in.subdomain)
    if existing:
        raise HTTPException(status_code=400, detail="Subdominio ya existe")
    
    return await service.create_tenant(db, name=tenant_in.name, subdomain=tenant_in.subdomain)
    
@router.post("/api/tenants/{tenant_id}/users", status_code=status.HTTP_201_CREATED)
@is_superadmin
async def admin_create_tenant_user(
    tenant_id: int,
    user_in: AuthUserCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User
):
    from app.modules.tenants.models import Tenant
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant no encontrado")
    
    # Seteamos el search_path al esquema del tenant para esta operación
    from sqlalchemy import text
    await db.execute(text(f'SET search_path TO "{tenant.schema_name}", public'))
    
    from app.modules.auth.service import create_user
    
    return await create_user(db, user_in)

@router.put("/api/tenants/{tenant_id}", response_model=schemas.Tenant)
@is_superadmin
async def admin_update_tenant(
    tenant_id: int,
    tenant_in: schemas.TenantUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User
):
    tenant = await db.get(models.Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant no encontrado")
    
    if tenant_in.name is not None:
        tenant.name = tenant_in.name
    if tenant_in.is_active is not None:
        tenant.is_active = tenant_in.is_active
        
    await db.commit()
    await db.refresh(tenant)
    return tenant

@router.delete("/api/tenants/{tenant_id}")
@is_superadmin
async def admin_delete_tenant(
    tenant_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User
):
    from sqlalchemy import text
    tenant = await db.get(models.Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant no encontrado")
    
    schema_name = tenant.schema_name
    
    # 1. Eliminar registro del Tenant
    await db.delete(tenant)
    await db.commit()
    
    # 2. Eliminar el esquema de base de datos asociado
    from app.core.database import engine
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        await conn.execute(text('SET search_path TO public'))
        
    return {"message": "Tenant y base de datos eliminados correctamente"}

@router.post("/api/tenants/{tenant_id}/demo")
@is_superadmin
async def admin_toggle_tenant_demo(
    tenant_id: int,
    action: str, # "seed" o "clean"
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User
):
    from app.modules.tenants.models import Tenant
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant no encontrado")
        
    if action not in ["seed", "clean"]:
        raise HTTPException(status_code=400, detail="Acción inválida. Use 'seed' o 'clean'")
        
    # Importar los métodos desde seed_data
    from seed_data import clean_tenant_data, seed_tenant_data
    
    schema_name = tenant.schema_name
    tenant_name = tenant.name
    
    try:
        if action == "clean":
            await clean_tenant_data(db, schema_name)
        elif action == "seed":
            # Limpiamos primero por seguridad
            await clean_tenant_data(db, schema_name)
            await seed_tenant_data(db, schema_name, tenant_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al procesar la demo: {str(e)}")
        
    return {"status": "success", "message": f"Modo Demo procesado con éxito: {action}"}
