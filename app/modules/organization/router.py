"""
Router para el módulo de Organización.
Define los endpoints de la API y las vistas HTML.
"""

from typing import Annotated, List, Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Query
)
from fastapi.responses import HTMLResponse
from app.core.templates import templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.auth.dependencies import is_admin, is_authenticated, is_recruiter, is_manager
from app.modules.organization import schemas, service
from app.core.config import settings

router = APIRouter(prefix="/organization", tags=["organization"])


# --- VISTAS HTML ---

@router.get("/config", response_class=HTMLResponse)
@is_recruiter
async def view_config_hub(request: Request, current_user: User = Depends(get_current_user)):
    """Vista principal de configuraciones."""
    return templates.TemplateResponse(request=request, name="organization/config_hub.html", context= {"request": request, "settings": settings, "current_user": current_user})

@router.get("/sedes", response_class=HTMLResponse)
@is_recruiter
async def view_sedes(
    request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: User = Depends(get_current_user)
):
    """Vista de gestión de Sedes."""
    sedes_orm = await service.get_sedes(db)
    sedes_data = [
        schemas.SedeRead.model_validate(s).model_dump() for s in sedes_orm
    ]
    return templates.TemplateResponse(request=request, name="organization/sedes.html", context=
        {"request": request, "sedes": sedes_data, "settings": settings, "current_user": current_user},
    )


@router.get("/areas", response_class=HTMLResponse)
@is_recruiter
async def view_areas(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    q: Optional[str] = None,
    sede_id: Optional[int] = None,
    current_user: User = Depends(get_current_user)
):
    """Vista de gestión de Áreas."""
    areas_orm = await service.get_areas(db, search=q, sede_id=sede_id)
    sedes_orm = await service.get_sedes(db)
    areas_data = [
        schemas.AreaRead.model_validate(a).model_dump() for a in areas_orm
    ]
    sedes_data = [
        schemas.SedeRead.model_validate(s).model_dump() for s in sedes_orm
    ]
    return templates.TemplateResponse(request=request, name="organization/areas.html", context=
        {
            "request": request,
            "areas": areas_data,
            "sedes": sedes_data,
            "q": q,
            "sede_id": sede_id,
            "settings": settings,
            "current_user": current_user,
        },
    )


@router.get("/areas/{id}", response_class=HTMLResponse)
@is_recruiter
async def view_area_detail(
    id: int, request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: User = Depends(get_current_user)
):
    """Vista de detalle de Área y gestión de Cargos."""
    area = await service.get_area_by_id(db, id)
    if not area:
        return templates.TemplateResponse(request=request, name="404.html", context= {"request": request, "settings": settings}, status_code=404
        )
    area_data = schemas.AreaRead.model_validate(area).model_dump()
    return templates.TemplateResponse(request=request, name="organization/area_detail.html", context=
        {"request": request, "area": area_data, "settings": settings, "current_user": current_user},
    )


@router.get("/chart", response_class=HTMLResponse)
@is_recruiter
async def view_org_chart(request: Request, current_user: User = Depends(get_current_user)):
    """Vista del Organigrama Interactivo."""
    return templates.TemplateResponse(request=request, name="organization/chart.html", context= {"request": request, "settings": settings, "current_user": current_user}
    )


@router.get("/companies", response_class=HTMLResponse)
@is_recruiter
async def view_companies(
    request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: User = Depends(get_current_user)
):
    """Vista de gestión de Empresas."""
    companies_orm = await service.get_companies(db)
    companies_data = [
        schemas.CompanyRead.model_validate(c).model_dump() for c in companies_orm
    ]
    return templates.TemplateResponse(request=request, name="organization/companies.html", context=
        {"request": request, "companies": companies_data, "settings": settings, "current_user": current_user},
    )

@router.get("/contract-types", response_class=HTMLResponse)
@is_recruiter
async def view_contract_types(
    request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: User = Depends(get_current_user)
):
    """Vista de gestión de Tipos de Contrato."""
    types_orm = await service.get_contract_types(db)
    types_data = [
        schemas.ContractTypeRead.model_validate(t).model_dump() for t in types_orm
    ]
    return templates.TemplateResponse(request=request, name="organization/contract_types.html", context=
        {"request": request, "contract_types": types_data, "settings": settings, "current_user": current_user},
    )

@router.get("/working-day-types", response_class=HTMLResponse)
@is_recruiter
async def view_working_day_types(request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: User = Depends(get_current_user)):
    data = [schemas.WorkingDayTypeRead.model_validate(x).model_dump() for x in await service.get_working_day_types(db)]
    return templates.TemplateResponse(request=request, name="organization/generic_catalog.html", context={"items": data, "title": "Tipos de Jornada", "api_path": "/organization/api/working-day-types", "settings": settings, "current_user": current_user})

@router.get("/salary-types", response_class=HTMLResponse)
@is_recruiter
async def view_salary_types(request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: User = Depends(get_current_user)):
    data = [schemas.SalaryTypeRead.model_validate(x).model_dump() for x in await service.get_salary_types(db)]
    return templates.TemplateResponse(request=request, name="organization/generic_catalog.html", context={"items": data, "title": "Tipos de Salario", "api_path": "/organization/api/salary-types", "settings": settings, "current_user": current_user})

@router.get("/currencies", response_class=HTMLResponse)
@is_recruiter
async def view_currencies(request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: User = Depends(get_current_user)):
    data = [schemas.CurrencyRead.model_validate(x).model_dump() for x in await service.get_currencies(db)]
    return templates.TemplateResponse(request=request, name="organization/generic_catalog.html", context={"items": data, "title": "Monedas", "api_path": "/organization/api/currencies", "has_symbol": True, "settings": settings, "current_user": current_user})

@router.get("/payment-methods", response_class=HTMLResponse)
@is_recruiter
async def view_payment_methods(request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: User = Depends(get_current_user)):
    data = [schemas.PaymentMethodRead.model_validate(x).model_dump() for x in await service.get_payment_methods(db)]
    return templates.TemplateResponse(request=request, name="organization/generic_catalog.html", context={"items": data, "title": "Formas de Pago", "api_path": "/organization/api/payment-methods", "settings": settings, "current_user": current_user})

@router.get("/banks", response_class=HTMLResponse)
@is_recruiter
async def view_banks(request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: User = Depends(get_current_user)):
    data = [schemas.BankRead.model_validate(x).model_dump() for x in await service.get_banks(db)]
    return templates.TemplateResponse(request=request, name="organization/generic_catalog.html", context={"items": data, "title": "Bancos", "api_path": "/organization/api/banks", "has_code": True, "settings": settings, "current_user": current_user})

@router.get("/cost-centers", response_class=HTMLResponse)
@is_recruiter
async def view_cost_centers(request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: User = Depends(get_current_user)):
    data = [schemas.CostCenterRead.model_validate(x).model_dump() for x in await service.get_cost_centers(db)]
    return templates.TemplateResponse(request=request, name="organization/generic_catalog.html", context={"items": data, "title": "Centros de Costo", "api_path": "/organization/api/cost-centers", "has_code": True, "settings": settings, "current_user": current_user})

@router.get("/probation-durations", response_class=HTMLResponse)
@is_recruiter
async def view_probation_durations(request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: User = Depends(get_current_user)):
    data = [schemas.ProbationDurationRead.model_validate(x).model_dump() for x in await service.get_probation_durations(db)]
    return templates.TemplateResponse(request=request, name="organization/generic_catalog.html", context={"items": data, "title": "Duraciones de Periodo de Prueba", "api_path": "/organization/api/probation-durations", "has_code": False, "has_days": True, "hide_description": True, "settings": settings, "current_user": current_user})

@router.get("/relationship-types", response_class=HTMLResponse)
@is_recruiter
async def view_relationship_types(request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: User = Depends(get_current_user)):
    data = [schemas.RelationshipTypeRead.model_validate(x).model_dump() for x in await service.get_relationship_types(db)]
    return templates.TemplateResponse(request=request, name="organization/generic_catalog.html", context={"items": data, "title": "Tipos de Vínculo", "api_path": "/organization/api/relationship-types", "has_code": False, "hide_description": True, "settings": settings, "current_user": current_user})


# --- API ENDPOINTS ---

# CONTRACT TYPES
@router.get("/api/contract-types", response_model=List[schemas.ContractTypeRead])
@is_recruiter
async def read_contract_types_api(db: Annotated[AsyncSession, Depends(get_db)]):
    return await service.get_contract_types(db)

@router.post("/api/contract-types", response_model=schemas.ContractTypeRead)
@is_admin
async def create_contract_type_api(
    data: schemas.ContractTypeCreate, db: Annotated[AsyncSession, Depends(get_db)]
):
    return await service.create_contract_type(db, data)

@router.put("/api/contract-types/{id}", response_model=schemas.ContractTypeRead)
@is_admin
async def update_contract_type_api(
    id: int, data: schemas.ContractTypeUpdate, db: Annotated[AsyncSession, Depends(get_db)]
):
    updated = await service.update_contract_type(db, id, data)
    if not updated: raise HTTPException(404, "Tipo de contrato no encontrado")
    return updated

@router.delete("/api/contract-types/{id}", status_code=204)
@is_admin
async def delete_contract_type_api(
    id: int, db: Annotated[AsyncSession, Depends(get_db)]
):
    if not await service.delete_contract_type(db, id):
        raise HTTPException(404, "Tipo de contrato no encontrado")
    return None

# WORKING DAY TYPES
@router.get("/api/working-day-types", response_model=List[schemas.WorkingDayTypeRead])
@is_recruiter
async def read_working_day_types_api(db: Annotated[AsyncSession, Depends(get_db)]):
    return await service.get_working_day_types(db)

@router.post("/api/working-day-types", response_model=schemas.WorkingDayTypeRead)
@is_admin
async def create_working_day_type_api(data: schemas.WorkingDayTypeCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    return await service.create_working_day_type(db, data)

@router.put("/api/working-day-types/{id}", response_model=schemas.WorkingDayTypeRead)
@is_admin
async def update_working_day_type_api(id: int, data: schemas.WorkingDayTypeUpdate, db: Annotated[AsyncSession, Depends(get_db)]):
    updated = await service.update_working_day_type(db, id, data)
    if not updated: raise HTTPException(404, "Tipo de jornada no encontrado")
    return updated

@router.delete("/api/working-day-types/{id}", status_code=204)
@is_admin
async def delete_working_day_type_api(id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    if not await service.delete_working_day_type(db, id): raise HTTPException(404, "Tipo de jornada no encontrado")
    return None

# SALARY TYPES
@router.get("/api/salary-types", response_model=List[schemas.SalaryTypeRead])
@is_recruiter
async def read_salary_types_api(db: Annotated[AsyncSession, Depends(get_db)]):
    return await service.get_salary_types(db)

@router.post("/api/salary-types", response_model=schemas.SalaryTypeRead)
@is_admin
async def create_salary_type_api(data: schemas.SalaryTypeCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    return await service.create_salary_type(db, data)

@router.put("/api/salary-types/{id}", response_model=schemas.SalaryTypeRead)
@is_admin
async def update_salary_type_api(id: int, data: schemas.SalaryTypeUpdate, db: Annotated[AsyncSession, Depends(get_db)]):
    updated = await service.update_salary_type(db, id, data)
    if not updated: raise HTTPException(404, "Tipo de salario no encontrado")
    return updated

@router.delete("/api/salary-types/{id}", status_code=204)
@is_admin
async def delete_salary_type_api(id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    if not await service.delete_salary_type(db, id): raise HTTPException(404, "Tipo de salario no encontrado")
    return None

# CURRENCIES
@router.get("/api/currencies", response_model=List[schemas.CurrencyRead])
@is_recruiter
async def read_currencies_api(db: Annotated[AsyncSession, Depends(get_db)]):
    return await service.get_currencies(db)

@router.post("/api/currencies", response_model=schemas.CurrencyRead)
@is_admin
async def create_currency_api(data: schemas.CurrencyCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    return await service.create_currency(db, data)

@router.put("/api/currencies/{id}", response_model=schemas.CurrencyRead)
@is_admin
async def update_currency_api(id: int, data: schemas.CurrencyUpdate, db: Annotated[AsyncSession, Depends(get_db)]):
    updated = await service.update_currency(db, id, data)
    if not updated: raise HTTPException(404, "Moneda no encontrada")
    return updated

@router.delete("/api/currencies/{id}", status_code=204)
@is_admin
async def delete_currency_api(id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    if not await service.delete_currency(db, id): raise HTTPException(404, "Moneda no encontrada")
    return None

# PAYMENT METHODS
@router.get("/api/payment-methods", response_model=List[schemas.PaymentMethodRead])
@is_recruiter
async def read_payment_methods_api(db: Annotated[AsyncSession, Depends(get_db)]):
    return await service.get_payment_methods(db)

@router.post("/api/payment-methods", response_model=schemas.PaymentMethodRead)
@is_admin
async def create_payment_method_api(data: schemas.PaymentMethodCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    return await service.create_payment_method(db, data)

@router.put("/api/payment-methods/{id}", response_model=schemas.PaymentMethodRead)
@is_admin
async def update_payment_method_api(id: int, data: schemas.PaymentMethodUpdate, db: Annotated[AsyncSession, Depends(get_db)]):
    updated = await service.update_payment_method(db, id, data)
    if not updated: raise HTTPException(404, "Forma de pago no encontrada")
    return updated

@router.delete("/api/payment-methods/{id}", status_code=204)
@is_admin
async def delete_payment_method_api(id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    if not await service.delete_payment_method(db, id): raise HTTPException(404, "Forma de pago no encontrada")
    return None

# BANKS
@router.get("/api/banks", response_model=List[schemas.BankRead])
@is_recruiter
async def read_banks_api(db: Annotated[AsyncSession, Depends(get_db)]):
    return await service.get_banks(db)

@router.post("/api/banks", response_model=schemas.BankRead)
@is_admin
async def create_bank_api(data: schemas.BankCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    return await service.create_bank(db, data)

@router.put("/api/banks/{id}", response_model=schemas.BankRead)
@is_admin
async def update_bank_api(id: int, data: schemas.BankUpdate, db: Annotated[AsyncSession, Depends(get_db)]):
    updated = await service.update_bank(db, id, data)
    if not updated: raise HTTPException(404, "Banco no encontrado")
    return updated

@router.delete("/api/banks/{id}", status_code=204)
@is_admin
async def delete_bank_api(id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    if not await service.delete_bank(db, id): raise HTTPException(404, "Banco no encontrado")
    return None

# COST CENTERS
@router.get("/api/cost-centers", response_model=List[schemas.CostCenterRead])
@is_recruiter
async def read_cost_centers_api(db: Annotated[AsyncSession, Depends(get_db)]):
    return await service.get_cost_centers(db)

@router.post("/api/cost-centers", response_model=schemas.CostCenterRead)
@is_admin
async def create_cost_center_api(data: schemas.CostCenterCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    return await service.create_cost_center(db, data)

@router.put("/api/cost-centers/{id}", response_model=schemas.CostCenterRead)
@is_admin
async def update_cost_center_api(id: int, data: schemas.CostCenterUpdate, db: Annotated[AsyncSession, Depends(get_db)]):
    updated = await service.update_cost_center(db, id, data)
    if not updated: raise HTTPException(404, "Centro de costo no encontrado")
    return updated

@router.delete("/api/cost-centers/{id}", status_code=204)
@is_admin
async def delete_cost_center_api(id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    if not await service.delete_cost_center(db, id): raise HTTPException(404, "Centro de costo no encontrado")
    return None

# PROBATION DURATIONS
@router.get("/api/probation-durations", response_model=List[schemas.ProbationDurationRead])
@is_recruiter
async def read_probation_durations_api(db: Annotated[AsyncSession, Depends(get_db)]):
    return await service.get_probation_durations(db)

@router.post("/api/probation-durations", response_model=schemas.ProbationDurationRead)
@is_admin
async def create_probation_duration_api(data: schemas.ProbationDurationCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    return await service.create_probation_duration(db, data)

@router.put("/api/probation-durations/{id}", response_model=schemas.ProbationDurationRead)
@is_admin
async def update_probation_duration_api(id: int, data: schemas.ProbationDurationUpdate, db: Annotated[AsyncSession, Depends(get_db)]):
    updated = await service.update_probation_duration(db, id, data)
    if not updated: raise HTTPException(404, "Duración no encontrada")
    return updated

@router.delete("/api/probation-durations/{id}", status_code=204)
@is_admin
async def delete_probation_duration_api(id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    if not await service.delete_probation_duration(db, id): raise HTTPException(404, "Duración no encontrada")
    return None

# RELATIONSHIP TYPES
@router.get("/api/relationship-types", response_model=List[schemas.RelationshipTypeRead])
@is_recruiter
async def read_relationship_types_api(db: Annotated[AsyncSession, Depends(get_db)]):
    return await service.get_relationship_types(db)

@router.post("/api/relationship-types", response_model=schemas.RelationshipTypeRead)
@is_admin
async def create_relationship_type_api(data: schemas.RelationshipTypeCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    return await service.create_relationship_type(db, data)

@router.put("/api/relationship-types/{id}", response_model=schemas.RelationshipTypeRead)
@is_admin
async def update_relationship_type_api(id: int, data: schemas.RelationshipTypeUpdate, db: Annotated[AsyncSession, Depends(get_db)]):
    updated = await service.update_relationship_type(db, id, data)
    if not updated: raise HTTPException(404, "Tipo de vínculo no encontrado")
    return updated

@router.delete("/api/relationship-types/{id}", status_code=204)
@is_admin
async def delete_relationship_type_api(id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    if not await service.delete_relationship_type(db, id): raise HTTPException(404, "Tipo de vínculo no encontrado")
    return None

# COMPANIES
@router.get("/api/companies", response_model=List[schemas.CompanyRead])
@is_recruiter
async def read_companies_api(db: Annotated[AsyncSession, Depends(get_db)]):
    return await service.get_companies(db)

@router.post("/api/companies", response_model=schemas.CompanyRead)
@is_admin
async def create_company_api(
    company: schemas.CompanyCreate, db: Annotated[AsyncSession, Depends(get_db)]
):
    return await service.create_company(db, company)

@router.put("/api/companies/{id}", response_model=schemas.CompanyRead)
@is_admin
async def update_company_api(
    id: int,
    company: schemas.CompanyUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await service.update_company(db, id, company)

@router.delete("/api/companies/{id}", status_code=204)
@is_admin
async def delete_company_api(
    id: int, db: Annotated[AsyncSession, Depends(get_db)]
):
    await service.delete_company(db, id)

# SEDES
@router.get("/api/sedes", response_model=List[schemas.SedeRead])
@is_recruiter
async def read_sedes_api(db: Annotated[AsyncSession, Depends(get_db)]):
    return await service.get_sedes(db)

@router.post("/api/sedes", response_model=schemas.SedeRead)
@is_admin
async def create_sede_api(
    sede: schemas.SedeCreate, db: Annotated[AsyncSession, Depends(get_db)]
):
    return await service.create_sede(db, sede)

@router.put("/api/sedes/{id}", response_model=schemas.SedeRead)
@is_admin
async def update_sede_api(
    id: int,
    sede: schemas.SedeUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await service.update_sede(db, id, sede)

@router.delete("/api/sedes/{id}", status_code=204)
@is_admin
async def delete_sede_api(
    id: int, db: Annotated[AsyncSession, Depends(get_db)]
):
    await service.delete_sede(db, id)

# AREAS
@router.get("/api/areas", response_model=List[schemas.AreaRead])
@is_recruiter
async def read_areas_api(
    db: Annotated[AsyncSession, Depends(get_db)],
    sede_id: Optional[int] = None
):
    return await service.get_areas(db, sede_id=sede_id)

@router.get("/api/areas/{id}", response_model=schemas.AreaRead)
@is_recruiter
async def read_area_detail_api(
    id: int, db: Annotated[AsyncSession, Depends(get_db)]
):
    area = await service.get_area_by_id(db, id)
    if not area:
        raise HTTPException(404, "Área no encontrada")
    return area

@router.post("/api/areas", response_model=schemas.AreaRead)
@is_admin
async def create_area_api(
    area: schemas.AreaCreate, db: Annotated[AsyncSession, Depends(get_db)]
):
    return await service.create_area(db, area)

@router.put("/api/areas/{id}", response_model=schemas.AreaRead)
@is_admin
async def update_area_api(
    id: int,
    area: schemas.AreaUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await service.update_area(db, id, area)

@router.delete("/api/areas/{id}", status_code=204)
@is_admin
async def delete_area_api(
    id: int, db: Annotated[AsyncSession, Depends(get_db)]
):
    await service.delete_area(db, id)

# POSITIONS
@router.post("/api/positions", response_model=schemas.PositionRead)
@is_admin
async def create_position_api(
    pos: schemas.PositionCreate, db: Annotated[AsyncSession, Depends(get_db)]
):
    return await service.create_position(db, pos)

@router.put("/api/positions/{id}", response_model=schemas.PositionRead)
@is_admin
async def update_position_api(
    id: int,
    pos: schemas.PositionUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    updated = await service.update_position(db, id, pos)
    if not updated:
        raise HTTPException(404, "Cargo no encontrado")
    return updated

@router.delete("/api/positions/{id}", status_code=204)
@is_admin
async def delete_position_api(
    id: int, db: Annotated[AsyncSession, Depends(get_db)]
):
    if not await service.delete_position(db, id):
        raise HTTPException(404, "Cargo no encontrado")
    return None

# CHART DATA
@router.get("/api/chart-data")
@is_recruiter
async def get_chart_data_api(
    db: Annotated[AsyncSession, Depends(get_db)],
    mode: str = Query("hierarchy", enum=["hierarchy", "structure", "people"])
):
    return await service.get_org_chart_data(db, mode)