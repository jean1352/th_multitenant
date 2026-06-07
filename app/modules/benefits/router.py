from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from app.core.templates import templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.auth.dependencies import is_manager, is_recruiter, is_authenticated, is_admin
from app.modules.benefits import service, schemas
from app.core.config import settings

router = APIRouter(prefix="/benefits", tags=["benefits"])

@router.get("/config", response_class=HTMLResponse)
@is_recruiter
async def config_view(
    request: Request, 
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user)
):
    """Vista del catálogo de beneficios."""
    benefits_orm = await service.get_benefit_types(db)
    benefits_data = [
        schemas.BenefitTypeRead.model_validate(b).model_dump() 
        for b in benefits_orm
    ]
    return templates.TemplateResponse(request=request, name="benefits/index.html", context= 
        {"request": request, "benefits": benefits_data, "settings": settings, "current_user": current_user}
    )


@router.get("/types/{id}", response_class=HTMLResponse)
@is_recruiter
async def detail_view(
    id: int, 
    request: Request, 
    db: Annotated[AsyncSession, Depends(get_db)],
    q: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """Vista de detalle de un beneficio y sus asignados."""
    benefit = await service.get_benefit_type_by_id(db, id)
    if not benefit:
        return templates.TemplateResponse(request=request, name="404.html", context= {"request": request, "settings": settings, "current_user": current_user}, status_code=404)
    
    # Obtener asignaciones con filtro
    assignments = await service.get_employees_by_benefit(db, id, search=q)
    
    benefit_data = schemas.BenefitTypeRead.model_validate(benefit).model_dump()

    return templates.TemplateResponse(request=request, name="benefits/detail.html", context= 
        {
            "request": request, 
            "benefit": benefit_data, 
            "assignments": assignments,
            "q": q,
            "settings": settings,
            "current_user": current_user
        }
    )

# --- REQUESTS CATALOGS VIEWS ---
@router.get("/config/request-types", response_class=HTMLResponse)
@is_recruiter
async def view_request_types(request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: User = Depends(get_current_user)):
    data = [schemas.RequestTypeRead.model_validate(x).model_dump() for x in await service.get_request_types(db)]
    return templates.TemplateResponse(request=request, name="organization/generic_catalog.html", context={"items": data, "title": "Tipos de Solicitud", "api_path": "/benefits/api/config/request-types", "has_code": False, "hide_description": True, "settings": settings, "current_user": current_user})

@router.get("/config/subtypes", response_class=HTMLResponse)
@is_recruiter
async def view_subtypes(request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: User = Depends(get_current_user)):
    data = [schemas.SubtypeRead.model_validate(x).model_dump() for x in await service.get_subtypes(db)]
    return templates.TemplateResponse(request=request, name="organization/generic_catalog.html", context={"items": data, "title": "Subtipos de Beneficio", "api_path": "/benefits/api/config/subtypes", "has_code": False, "hide_description": True, "settings": settings, "current_user": current_user})

@router.get("/config/grant-reasons", response_class=HTMLResponse)
@is_recruiter
async def view_grant_reasons(request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: User = Depends(get_current_user)):
    data = [schemas.GrantReasonRead.model_validate(x).model_dump() for x in await service.get_grant_reasons(db)]
    return templates.TemplateResponse(request=request, name="organization/generic_catalog.html", context={"items": data, "title": "Motivos de Otorgamiento", "api_path": "/benefits/api/config/grant-reasons", "has_code": False, "hide_description": True, "settings": settings, "current_user": current_user})

@router.get("/config/authorization-levels", response_class=HTMLResponse)
@is_recruiter
async def view_authorization_levels(request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: User = Depends(get_current_user)):
    data = [schemas.AuthorizationLevelRead.model_validate(x).model_dump() for x in await service.get_authorization_levels(db)]
    return templates.TemplateResponse(request=request, name="organization/generic_catalog.html", context={"items": data, "title": "Niveles de Autorización", "api_path": "/benefits/api/config/authorization-levels", "has_code": False, "hide_description": True, "settings": settings, "current_user": current_user})

@router.get("/config/benefit-modalities", response_class=HTMLResponse)
@is_recruiter
async def view_benefit_modalities(request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: User = Depends(get_current_user)):
    data = [schemas.BenefitModalityRead.model_validate(x).model_dump() for x in await service.get_benefit_modalities(db)]
    return templates.TemplateResponse(request=request, name="organization/generic_catalog.html", context={"items": data, "title": "Modalidades de Beneficio", "api_path": "/benefits/api/config/benefit-modalities", "has_code": False, "hide_description": True, "settings": settings, "current_user": current_user})

@router.get("/config/benefit-frequencies", response_class=HTMLResponse)
@is_recruiter
async def view_benefit_frequencies(request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: User = Depends(get_current_user)):
    data = [schemas.BenefitFrequencyRead.model_validate(x).model_dump() for x in await service.get_benefit_frequencies(db)]
    return templates.TemplateResponse(request=request, name="organization/generic_catalog.html", context={"items": data, "title": "Frecuencias de Beneficio", "api_path": "/benefits/api/config/benefit-frequencies", "has_code": False, "hide_description": True, "settings": settings, "current_user": current_user})

# --- REQUESTS VIEWS ---
@router.get("/requests", response_class=HTMLResponse)
@is_recruiter
async def view_requests_list(
    request: Request, db: Annotated[AsyncSession, Depends(get_db)], 
    status: Optional[str] = None, q: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    requests_orm = await service.list_benefit_requests(db, status, q)
    requests_data = [schemas.BenefitRequestRead.model_validate(r).model_dump(mode="json") for r in requests_orm]
    
    return templates.TemplateResponse(request=request, name="benefits/requests/index.html", context={
        "request": request, "requests": requests_data, "status_filter": status, "q": q,
        "settings": settings, "current_user": current_user
    })

@router.get("/requests/new", response_class=HTMLResponse)
@is_recruiter
async def view_new_request(request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: User = Depends(get_current_user)):
    from app.modules.organization import service as org_service
    from app.modules.organization import schemas as org_schemas
    
    request_types = [schemas.RequestTypeRead.model_validate(x).model_dump() for x in await service.get_request_types(db, True)]
    subtypes = [schemas.SubtypeRead.model_validate(x).model_dump() for x in await service.get_subtypes(db, True)]
    grant_reasons = [schemas.GrantReasonRead.model_validate(x).model_dump() for x in await service.get_grant_reasons(db, True)]
    benefit_types = [schemas.BenefitTypeRead.model_validate(x).model_dump(mode="json") for x in await service.get_benefit_types(db, True)]
    currencies = [org_schemas.CurrencyRead.model_validate(x).model_dump() for x in await org_service.get_currencies(db, True)]
    auth_levels = [schemas.AuthorizationLevelRead.model_validate(x).model_dump() for x in await service.get_authorization_levels(db, True)]
    modalities = [schemas.BenefitModalityRead.model_validate(x).model_dump() for x in await service.get_benefit_modalities(db, True)]
    frequencies = [schemas.BenefitFrequencyRead.model_validate(x).model_dump() for x in await service.get_benefit_frequencies(db, True)]
    
    return templates.TemplateResponse(request=request, name="benefits/requests/create.html", context={
        "request": request, "request_types": request_types, "subtypes": subtypes,
        "grant_reasons": grant_reasons, "benefit_types": benefit_types, "currencies": currencies,
        "auth_levels": auth_levels, "modalities": modalities, "frequencies": frequencies,
        "settings": settings, "current_user": current_user
    })


@router.get("/requests/{id}/edit", response_class=HTMLResponse)
@is_recruiter
async def view_edit_request(id: int, request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: User = Depends(get_current_user)):
    from app.modules.organization import service as org_service
    from app.modules.organization import schemas as org_schemas
    
    req_orm = await service.get_benefit_request_by_id(db, id)
    if not req_orm:
        raise HTTPException(404, "Solicitud no encontrada")
        
    req_data = schemas.BenefitRequestRead.model_validate(req_orm).model_dump(mode="json")
    
    request_types = [schemas.RequestTypeRead.model_validate(x).model_dump() for x in await service.get_request_types(db, True)]
    subtypes = [schemas.SubtypeRead.model_validate(x).model_dump() for x in await service.get_subtypes(db, True)]
    grant_reasons = [schemas.GrantReasonRead.model_validate(x).model_dump() for x in await service.get_grant_reasons(db, True)]
    benefit_types = [schemas.BenefitTypeRead.model_validate(x).model_dump(mode="json") for x in await service.get_benefit_types(db, True)]
    currencies = [org_schemas.CurrencyRead.model_validate(x).model_dump() for x in await org_service.get_currencies(db, True)]
    auth_levels = [schemas.AuthorizationLevelRead.model_validate(x).model_dump() for x in await service.get_authorization_levels(db, True)]
    modalities = [schemas.BenefitModalityRead.model_validate(x).model_dump() for x in await service.get_benefit_modalities(db, True)]
    frequencies = [schemas.BenefitFrequencyRead.model_validate(x).model_dump() for x in await service.get_benefit_frequencies(db, True)]
    
    return templates.TemplateResponse(request=request, name="benefits/requests/edit.html", context={
        "request": request, "req": req_data, "request_types": request_types, "subtypes": subtypes,
        "grant_reasons": grant_reasons, "benefit_types": benefit_types, "currencies": currencies,
        "auth_levels": auth_levels, "modalities": modalities, "frequencies": frequencies,
        "settings": settings, "current_user": current_user
    })

# --- API REQUEST CATALOGS ---
@router.get("/api/config/request-types", response_model=list[schemas.RequestTypeRead])
@is_recruiter
async def api_get_request_types(db: Annotated[AsyncSession, Depends(get_db)]): return await service.get_request_types(db)

@router.post("/api/config/request-types", response_model=schemas.RequestTypeRead)
@is_admin
async def api_create_request_type(data: schemas.RequestTypeCreate, db: Annotated[AsyncSession, Depends(get_db)]): return await service.create_request_type(db, data)

@router.put("/api/config/request-types/{id}", response_model=schemas.RequestTypeRead)
@is_admin
async def api_update_request_type(id: int, data: schemas.RequestTypeUpdate, db: Annotated[AsyncSession, Depends(get_db)]): return await service.update_request_type(db, id, data)

@router.delete("/api/config/request-types/{id}", status_code=204)
@is_admin
async def api_delete_request_type(id: int, db: Annotated[AsyncSession, Depends(get_db)]): await service.delete_request_type(db, id); return None

@router.get("/api/config/subtypes", response_model=list[schemas.SubtypeRead])
@is_recruiter
async def api_get_subtypes(db: Annotated[AsyncSession, Depends(get_db)]): return await service.get_subtypes(db)

@router.post("/api/config/subtypes", response_model=schemas.SubtypeRead)
@is_admin
async def api_create_subtype(data: schemas.SubtypeCreate, db: Annotated[AsyncSession, Depends(get_db)]): return await service.create_subtype(db, data)

@router.put("/api/config/subtypes/{id}", response_model=schemas.SubtypeRead)
@is_admin
async def api_update_subtype(id: int, data: schemas.SubtypeUpdate, db: Annotated[AsyncSession, Depends(get_db)]): return await service.update_subtype(db, id, data)

@router.delete("/api/config/subtypes/{id}", status_code=204)
@is_admin
async def api_delete_subtype(id: int, db: Annotated[AsyncSession, Depends(get_db)]): await service.delete_subtype(db, id); return None

@router.get("/api/config/grant-reasons", response_model=list[schemas.GrantReasonRead])
@is_recruiter
async def api_get_grant_reasons(db: Annotated[AsyncSession, Depends(get_db)]): return await service.get_grant_reasons(db)

@router.post("/api/config/grant-reasons", response_model=schemas.GrantReasonRead)
@is_admin
async def api_create_grant_reason(data: schemas.GrantReasonCreate, db: Annotated[AsyncSession, Depends(get_db)]): return await service.create_grant_reason(db, data)

@router.put("/api/config/grant-reasons/{id}", response_model=schemas.GrantReasonRead)
@is_admin
async def api_update_grant_reason(id: int, data: schemas.GrantReasonUpdate, db: Annotated[AsyncSession, Depends(get_db)]): return await service.update_grant_reason(db, id, data)

@router.delete("/api/config/grant-reasons/{id}", status_code=204)
@is_admin
async def api_delete_grant_reason(id: int, db: Annotated[AsyncSession, Depends(get_db)]): await service.delete_grant_reason(db, id); return None

@router.get("/api/config/authorization-levels", response_model=list[schemas.AuthorizationLevelRead])
@is_recruiter
async def api_get_authorization_levels(db: Annotated[AsyncSession, Depends(get_db)]): return await service.get_authorization_levels(db)
@router.post("/api/config/authorization-levels", response_model=schemas.AuthorizationLevelRead)
@is_admin
async def api_create_authorization_level(data: schemas.AuthorizationLevelCreate, db: Annotated[AsyncSession, Depends(get_db)]): return await service.create_authorization_level(db, data)
@router.put("/api/config/authorization-levels/{id}", response_model=schemas.AuthorizationLevelRead)
@is_admin
async def api_update_authorization_level(id: int, data: schemas.AuthorizationLevelUpdate, db: Annotated[AsyncSession, Depends(get_db)]): return await service.update_authorization_level(db, id, data)
@router.delete("/api/config/authorization-levels/{id}", status_code=204)
@is_admin
async def api_delete_authorization_level(id: int, db: Annotated[AsyncSession, Depends(get_db)]): await service.delete_authorization_level(db, id); return None

@router.get("/api/config/benefit-modalities", response_model=list[schemas.BenefitModalityRead])
@is_recruiter
async def api_get_benefit_modalities(db: Annotated[AsyncSession, Depends(get_db)]): return await service.get_benefit_modalities(db)
@router.post("/api/config/benefit-modalities", response_model=schemas.BenefitModalityRead)
@is_admin
async def api_create_benefit_modality(data: schemas.BenefitModalityCreate, db: Annotated[AsyncSession, Depends(get_db)]): return await service.create_benefit_modality(db, data)
@router.put("/api/config/benefit-modalities/{id}", response_model=schemas.BenefitModalityRead)
@is_admin
async def api_update_benefit_modality(id: int, data: schemas.BenefitModalityUpdate, db: Annotated[AsyncSession, Depends(get_db)]): return await service.update_benefit_modality(db, id, data)
@router.delete("/api/config/benefit-modalities/{id}", status_code=204)
@is_admin
async def api_delete_benefit_modality(id: int, db: Annotated[AsyncSession, Depends(get_db)]): await service.delete_benefit_modality(db, id); return None

@router.get("/api/config/benefit-frequencies", response_model=list[schemas.BenefitFrequencyRead])
@is_recruiter
async def api_get_benefit_frequencies(db: Annotated[AsyncSession, Depends(get_db)]): return await service.get_benefit_frequencies(db)
@router.post("/api/config/benefit-frequencies", response_model=schemas.BenefitFrequencyRead)
@is_admin
async def api_create_benefit_frequency(data: schemas.BenefitFrequencyCreate, db: Annotated[AsyncSession, Depends(get_db)]): return await service.create_benefit_frequency(db, data)
@router.put("/api/config/benefit-frequencies/{id}", response_model=schemas.BenefitFrequencyRead)
@is_admin
async def api_update_benefit_frequency(id: int, data: schemas.BenefitFrequencyUpdate, db: Annotated[AsyncSession, Depends(get_db)]): return await service.update_benefit_frequency(db, id, data)
@router.delete("/api/config/benefit-frequencies/{id}", status_code=204)
@is_admin
async def api_delete_benefit_frequency(id: int, db: Annotated[AsyncSession, Depends(get_db)]): await service.delete_benefit_frequency(db, id); return None

# --- API REQUESTS ---
@router.post("/api/requests", response_model=schemas.BenefitRequestRead)
@is_recruiter
async def api_create_request(data: schemas.BenefitRequestCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    return await service.create_benefit_request(db, data)

@router.put("/api/requests/{id}", response_model=schemas.BenefitRequestRead)
@is_recruiter
async def api_update_request(id: int, data: schemas.BenefitRequestCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    updated = await service.update_benefit_request(db, id, data)
    if not updated:
        raise HTTPException(404, "Solicitud no encontrada")
    return updated

@router.put("/api/requests/{id}/status")
@is_recruiter
async def api_update_request_status(id: int, data: schemas.BenefitRequestUpdateStatus, db: Annotated[AsyncSession, Depends(get_db)]):
    if not await service.update_request_status(db, id, data.status):
        raise HTTPException(404, "Solicitud no encontrada")
    return {"message": "Estado actualizado"}

@router.post("/api/types", response_model=schemas.BenefitTypeRead)
@is_manager
async def create_type_api(
    data: schemas.BenefitTypeCreate, 
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Crear un nuevo tipo de beneficio."""
    return await service.create_benefit_type(db, data)


@router.put("/api/types/{id}", response_model=schemas.BenefitTypeRead)
@is_manager
async def update_type_api(
    id: int, 
    data: schemas.BenefitTypeUpdate, 
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Actualizar configuración de un beneficio."""
    updated = await service.update_benefit_type(db, id, data)
    if not updated:
        raise HTTPException(404, "Beneficio no encontrado")
    return updated


@router.delete("/api/types/{id}", status_code=204)
@is_manager
async def delete_type_api(
    id: int, 
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Eliminar un tipo de beneficio."""
    await service.delete_benefit_type(db, id)
    return None


@router.post("/api/assign/{emp_id}", response_model=schemas.EmployeeBenefitRead)
@is_recruiter
async def assign_benefit_api(
    emp_id: int, 
    raw_data: dict, # Recibimos como dict para limpiar
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Asignar un beneficio a un empleado."""
    # Limpieza de seguridad: si custom_data es string vacío, lo quitamos
    if "custom_data" in raw_data and (raw_data["custom_data"] == "" or raw_data["custom_data"] is None):
        del raw_data["custom_data"]
    
    try:
        data = schemas.EmployeeBenefitCreate(**raw_data)
        return await service.assign_benefit(db, emp_id, data)
    except Exception as e:
        raise HTTPException(400, f"Error en los datos del beneficio: {str(e)}")


@router.delete("/api/assign/{id}", status_code=204)
@is_recruiter
async def remove_benefit_api(
    id: int, 
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Quitar un beneficio a un empleado."""
    await service.remove_benefit(db, id)
    return None
