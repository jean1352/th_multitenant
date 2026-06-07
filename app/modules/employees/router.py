"""
Router para el módulo de Colaboradores.
"""

import json
import logging
from datetime import date, datetime
from typing import Annotated, Optional, Union, List

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    Query,
    BackgroundTasks
)
from fastapi.responses import HTMLResponse
from app.core.templates import templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.auth.dependencies import is_admin, is_authenticated, is_recruiter, is_manager
from app.modules.employees import schemas, service
from app.modules.organization import schemas as org_schemas
from app.modules.organization import service as org_service
from app.modules.organization.models import Sede
from app.modules.benefits import service as benefits_service
from app.modules.dietary import service as dietary_service
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/employees", tags=["employees"])


# --- API JSON SEARCH ---
@router.get("/api/search", response_model=List[schemas.EmployeeList])
@is_recruiter
async def search_employees_json(
    db: Annotated[AsyncSession, Depends(get_db)],
    area_id: Optional[int] = None,
    q: Optional[str] = None
):
    """Endpoint ligero para selectores dinámicos (JSON)."""
    result = await service.get_employees_paginated(db, page=1, limit=1000, search=q, area_id=area_id)
    
    employees = []
    for e in result["data"]:
        employees.append(schemas.EmployeeList.model_validate(e))
        
    return employees


# --- VISTAS HTML ---

@router.get("/", response_class=HTMLResponse)
@is_recruiter
async def list_employees(
    request: Request, 
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=5, le=100),
    q: Optional[str] = None,
    area_id: Optional[str] = None,
    sede_id: Optional[str] = None,
    company_id: Optional[str] = None,
    gender: Optional[str] = None,
    dietary_id: Optional[str] = None,
    birth_month: Optional[str] = None,
    is_leader: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    # --- Helpers de limpieza ---
    def parse_int(val: Optional[str]) -> Optional[int]:
        if val and val.strip().isdigit():
            return int(val)
        return None

    def parse_str(val: Optional[str]) -> Optional[str]:
        if val and val.strip():
            return val.strip()
        return None
    
    def parse_bool(val: Optional[str]) -> Optional[bool]:
        if val == 'true': return True
        if val == 'false': return False
        return None

    # Conversión de datos
    area_id_int = parse_int(area_id)
    sede_id_int = parse_int(sede_id)
    company_id_int = parse_int(company_id)
    dietary_id_int = parse_int(dietary_id)
    birth_month_int = parse_int(birth_month)
    gender_str = parse_str(gender)
    is_leader_bool = parse_bool(is_leader)

    # Obtener datos paginados
    pagination = await service.get_employees_paginated(
        db, 
        page, 
        limit, 
        q, 
        area_id_int, 
        sede_id_int, 
        company_id_int,
        gender_str, 
        dietary_id_int, 
        birth_month_int,
        is_leader_bool
    )
    
    # Cargar catálogos
    areas_orm = await org_service.get_areas(db)
    areas_data = [org_schemas.AreaRead.model_validate(a).model_dump() for a in areas_orm]
    
    sedes_orm = (await db.execute(select(Sede).order_by(Sede.name))).scalars().all()
    dietary_orm = await dietary_service.get_all(db)
    
    companies_orm = await org_service.get_companies(db)
    companies_data = [org_schemas.CompanyRead.model_validate(c).model_dump() for c in companies_orm]
    
    # Cargar Tipos de Contrato para el modal de creación
    contract_types_orm = await org_service.get_contract_types(db, active_only=True)
    contract_types_data = [org_schemas.ContractTypeRead.model_validate(c).model_dump() for c in contract_types_orm]

    # Cargar nuevos catálogos de contratación
    working_day_types = [org_schemas.WorkingDayTypeRead.model_validate(x).model_dump() for x in await org_service.get_working_day_types(db, active_only=True)]
    salary_types = [org_schemas.SalaryTypeRead.model_validate(x).model_dump() for x in await org_service.get_salary_types(db, active_only=True)]
    currencies = [org_schemas.CurrencyRead.model_validate(x).model_dump() for x in await org_service.get_currencies(db, active_only=True)]
    payment_methods = [org_schemas.PaymentMethodRead.model_validate(x).model_dump() for x in await org_service.get_payment_methods(db, active_only=True)]
    banks = [org_schemas.BankRead.model_validate(x).model_dump() for x in await org_service.get_banks(db, active_only=True)]
    cost_centers = [org_schemas.CostCenterRead.model_validate(x).model_dump() for x in await org_service.get_cost_centers(db, active_only=True)]
    probation_durations = [org_schemas.ProbationDurationRead.model_validate(x).model_dump() for x in await org_service.get_probation_durations(db, active_only=True)]
    relationship_types = [org_schemas.RelationshipTypeRead.model_validate(x).model_dump() for x in await org_service.get_relationship_types(db, active_only=True)]

    # Serializar empleados
    employees_data = []
    for e in pagination["data"]:
        emp_model = schemas.EmployeeList.model_validate(e)
        employees_data.append(emp_model)
    pagination["data"] = employees_data

    filters = {
        "q": q, 
        "area_id": area_id_int, 
        "sede_id": sede_id_int,
        "company_id": company_id_int,
        "gender": gender_str,
        "dietary_id": dietary_id_int,
        "birth_month": birth_month_int,
        "is_leader": is_leader,
        "limit": limit
    }

    return templates.TemplateResponse(request=request, name="employees/index.html", context=
        {
            "request": request,
            "pagination": pagination,
            "areas": areas_data,
            "sedes": sedes_orm,
            "dietary_options": dietary_orm,
            "filters": filters,
            "companies": companies_data,
            "contract_types": contract_types_data,
            "working_day_types": working_day_types,
            "salary_types": salary_types,
            "currencies": currencies,
            "payment_methods": payment_methods,
            "banks": banks,
            "cost_centers": cost_centers,
            "probation_durations": probation_durations,
            "relationship_types": relationship_types,
            "current_user": current_user,
            "settings": settings
        },
    )

@router.get("/{id}", response_class=HTMLResponse)
@is_recruiter
async def detail_employee(
    id: int, request: Request, db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user)
):
    employee = await service.get_employee_detail(db, id)
    if not employee:
        return templates.TemplateResponse(request=request, name="404.html", context= {"request": request, "settings": settings}, status_code=404)
    
    areas_orm = await org_service.get_areas(db)
    areas_data = [org_schemas.AreaRead.model_validate(a).model_dump() for a in areas_orm]
    
    benefit_types_orm = await benefits_service.get_benefit_types(db, only_active=True)
    from app.modules.benefits import schemas as ben_schemas
    benefit_types = [ben_schemas.BenefitTypeRead.model_validate(b).model_dump(mode="json") for b in benefit_types_orm]
    
    companies_orm = await org_service.get_companies(db)
    companies_data = [org_schemas.CompanyRead.model_validate(c).model_dump() for c in companies_orm]
    
    contract_types_orm = await org_service.get_contract_types(db, active_only=True)
    contract_types_data = [org_schemas.ContractTypeRead.model_validate(c).model_dump() for c in contract_types_orm]
    
    # Cargar nuevos catálogos de contratación
    working_day_types = [org_schemas.WorkingDayTypeRead.model_validate(x).model_dump() for x in await org_service.get_working_day_types(db, active_only=True)]
    salary_types = [org_schemas.SalaryTypeRead.model_validate(x).model_dump() for x in await org_service.get_salary_types(db, active_only=True)]
    currencies = [org_schemas.CurrencyRead.model_validate(x).model_dump() for x in await org_service.get_currencies(db, active_only=True)]
    payment_methods = [org_schemas.PaymentMethodRead.model_validate(x).model_dump() for x in await org_service.get_payment_methods(db, active_only=True)]
    banks = [org_schemas.BankRead.model_validate(x).model_dump() for x in await org_service.get_banks(db, active_only=True)]
    cost_centers = [org_schemas.CostCenterRead.model_validate(x).model_dump() for x in await org_service.get_cost_centers(db, active_only=True)]
    probation_durations = [org_schemas.ProbationDurationRead.model_validate(x).model_dump() for x in await org_service.get_probation_durations(db, active_only=True)]
    relationship_types = [org_schemas.RelationshipTypeRead.model_validate(x).model_dump() for x in await org_service.get_relationship_types(db, active_only=True)]

    emp_data = schemas.EmployeeRead.model_validate(employee)

    return templates.TemplateResponse(request=request, name="employees/detail.html", context=
        {
            "request": request,
            "employee": emp_data,
            "areas": areas_data,
            "benefit_types": benefit_types,
            "companies": companies_data,
            "contract_types": contract_types_data,
            "working_day_types": working_day_types,
            "salary_types": salary_types,
            "currencies": currencies,
            "payment_methods": payment_methods,
            "banks": banks,
            "cost_centers": cost_centers,
            "probation_durations": probation_durations,
            "relationship_types": relationship_types,
            "current_user": current_user,
            "settings": settings
        },
    )

# --- API EMPLOYEES (CRUD) ---

@router.post("/api", response_model=schemas.EmployeeRead)
@is_recruiter
async def create_employee_api(
    db: Annotated[AsyncSession, Depends(get_db)],
    background_tasks: BackgroundTasks,
    first_name: str = Form(...),
    last_name: str = Form(...),
    document_id: str = Form(...),
    position_id: int = Form(...),
    company_id: int = Form(...),
    contract_type_id: Optional[int] = Form(None),
    
    # NUEVOS CAMPOS
    contract_end_date: Optional[str] = Form(None),
    working_day_type_id: Optional[int] = Form(None),
    work_schedule: Optional[str] = Form(None),
    work_days: Optional[str] = Form(None),
    salary_type_id: Optional[int] = Form(None),
    base_salary: Optional[float] = Form(None),
    currency_id: Optional[int] = Form(None),
    payment_method_id: Optional[int] = Form(None),
    bank_id: Optional[int] = Form(None),
    cost_center_id: Optional[int] = Form(None),
    
    # PERIODO DE PRUEBA Y EMERGENCIA
    probation_duration_id: Optional[int] = Form(None),
    probation_evaluation: Optional[str] = Form("Pendiente"),
    emergency_contacts: Optional[str] = Form(None),

    institutional_email: Optional[str] = Form(None),
    secondary_emails: Optional[str] = Form(None),
    personal_email: Optional[str] = Form(None),
    birthday: Optional[str] = Form(None),
    blood_type: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    dietary_restrictions: Optional[str] = Form(None),
    photo: Optional[UploadFile] = File(None),
):
    dietary_list = []
    if dietary_restrictions:
        try:
            dietary_list = json.loads(dietary_restrictions)
        except ValueError:
            dietary_list = []

    emp_data = schemas.EmployeeCreate(
        first_name=first_name,
        last_name=last_name,
        full_name=f"{first_name} {last_name}",
        document_id=document_id,
        position_id=position_id,
        company_id=company_id,
        contract_type_id=contract_type_id,
        contract_end_date=contract_end_date if contract_end_date else None,
        working_day_type_id=working_day_type_id,
        work_schedule=work_schedule,
        work_days=work_days,
        salary_type_id=salary_type_id,
        base_salary=base_salary,
        currency_id=currency_id,
        payment_method_id=payment_method_id,
        bank_id=bank_id,
        cost_center_id=cost_center_id,
        probation_duration_id=probation_duration_id,
        probation_evaluation=probation_evaluation,
        institutional_email=institutional_email,
        secondary_emails=secondary_emails,
        personal_email=personal_email,
        birthday=birthday if birthday else None,
        blood_type=blood_type,
        address=address,
        dietary_restriction_ids=dietary_list,
    )
    return await service.create_employee(db, emp_data, photo, background_tasks, emergency_contacts)

@router.put("/api/{id}", response_model=schemas.EmployeeRead)
@is_recruiter
async def update_employee_api(
    id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    employee_position_id: Optional[int] = Form(None), # NUEVO
    first_name: Optional[str] = Form(None),
    last_name: Optional[str] = Form(None),
    position_id: Optional[str] = Form(None),
    company_id: Optional[str] = Form(None),
    contract_type_id: Optional[int] = Form(None),
    
    # NUEVOS CAMPOS
    contract_end_date: Optional[str] = Form(None),
    working_day_type_id: Optional[int] = Form(None),
    work_schedule: Optional[str] = Form(None),
    work_days: Optional[str] = Form(None),
    salary_type_id: Optional[int] = Form(None),
    base_salary: Optional[float] = Form(None),
    currency_id: Optional[int] = Form(None),
    payment_method_id: Optional[int] = Form(None),
    bank_id: Optional[int] = Form(None),
    cost_center_id: Optional[int] = Form(None),

    # PERIODO DE PRUEBA
    probation_duration_id: Optional[int] = Form(None),
    probation_start_date: Optional[str] = Form(None),
    probation_evaluation: Optional[str] = Form(None),
    probation_status: Optional[str] = Form(None),

    # EMERGENCIA
    emergency_contacts: Optional[str] = Form(None),

    institutional_email: Optional[str] = Form(None),
    secondary_emails: Optional[str] = Form(None),
    personal_email: Optional[str] = Form(None),
    birthday: Optional[str] = Form(None),
    blood_type: Optional[str] = Form(None),
    dietary_restrictions: Optional[str] = Form(None),
    
    gender: Optional[str] = Form(None),
    marital_status: Optional[str] = Form(None),
    nationality: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    internal_extension: Optional[str] = Form(None),
    office_location: Optional[str] = Form(None),
    document_id: Optional[str] = Form(None),
    
    photo: Optional[UploadFile] = File(None),
):
    dietary_list = None
    if dietary_restrictions is not None:
        try:
            dietary_list = json.loads(dietary_restrictions)
        except ValueError:
            dietary_list = []

    def clean(val): return None if val == "" or val == "string" else val
    pos_id_int = int(position_id) if position_id and position_id.strip().isdigit() else None
    comp_id_int = int(company_id) if company_id and company_id.strip().isdigit() else None
    photo_file = photo 

    try:
        raw_data = {
            "employee_position_id": employee_position_id,
            "first_name": clean(first_name),
            "last_name": clean(last_name),
            "document_id": clean(document_id),
            "position_id": pos_id_int,
            "company_id": comp_id_int,
            "contract_type_id": contract_type_id,
            "contract_end_date": clean(contract_end_date),
            "working_day_type_id": working_day_type_id,
            "work_schedule": clean(work_schedule),
            "work_days": clean(work_days),
            "salary_type_id": salary_type_id,
            "base_salary": base_salary,
            "currency_id": currency_id,
            "payment_method_id": payment_method_id,
            "bank_id": bank_id,
            "cost_center_id": cost_center_id,
            "probation_duration_id": probation_duration_id,
            "probation_start_date": clean(probation_start_date),
            "probation_evaluation": clean(probation_evaluation),
            "probation_status": clean(probation_status),
            "emergency_contacts": clean(emergency_contacts),
            "institutional_email": clean(institutional_email),
            "secondary_emails": clean(secondary_emails),
            "personal_email": clean(personal_email),
            "birthday": clean(birthday),
            "blood_type": clean(blood_type),
            "dietary_restriction_ids": dietary_list,
            "gender": clean(gender),
            "marital_status": clean(marital_status),
            "nationality": clean(nationality),
            "address": clean(address),
            "phone": clean(phone),
            "internal_extension": clean(internal_extension),
            "office_location": clean(office_location)
        }
        
        # Filtramos los campos vacíos antes de crear el Pydantic model
        filtered_data = {k: v for k, v in raw_data.items() if v is not None}
        
        emp_data = schemas.EmployeeUpdate(**filtered_data)
        
        updated = await service.update_employee(db, id, emp_data, photo_file)
        if not updated:
            raise HTTPException(404, "Colaborador no encontrado")
        return updated

    except Exception as e:
        logger.error(f"Error actualizando empleado {id}: {e}")
        raise HTTPException(400, f"Error al actualizar: {str(e)}")

@router.post("/api/{id}/change-salary", response_model=schemas.EmployeeRead)
@is_manager
async def change_salary_api(id: int, data: schemas.SalaryChangePayload, db: Annotated[AsyncSession, Depends(get_db)]):
    """API: Cambiar salario del colaborador."""
    return await service.change_salary(db, id, data)

@router.post("/api/{id}/positions", response_model=schemas.EmployeeRead)
@is_admin
async def add_position_api(id: int, data: schemas.AddPositionPayload, db: Annotated[AsyncSession, Depends(get_db)]):
    return await service.add_secondary_position(db, id, data)

@router.delete("/api/positions/{emp_pos_id}", status_code=204)
@is_admin
async def remove_position_api(emp_pos_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    if not await service.remove_secondary_position(db, emp_pos_id): raise HTTPException(404, "Asignación no encontrada")
    return None

@router.post("/api/{id}/promote", response_model=schemas.EmployeeRead)
@is_manager
async def promote_employee_api(id: int, data: schemas.PromotionPayload, db: Annotated[AsyncSession, Depends(get_db)]):
    return await service.promote_employee(db, id, data)

@router.post("/api/{id}/terminate", response_model=schemas.EmployeeRead)
@is_manager
async def terminate_employee_api(id: int, data: schemas.ExitPayload, db: Annotated[AsyncSession, Depends(get_db)]):
    return await service.terminate_employee(db, id, data)

@router.post("/api/{id}/rehire", response_model=schemas.EmployeeRead)
@is_manager
async def rehire_employee_api(id: int, data: schemas.RehirePayload, db: Annotated[AsyncSession, Depends(get_db)]):
    return await service.rehire_employee(db, id, data)

@router.post("/api/{id}/change-contract", response_model=schemas.EmployeeRead)
@is_manager
async def change_contract_api(id: int, data: schemas.ChangeContractPayload, db: Annotated[AsyncSession, Depends(get_db)]):
    """API: Cambiar tipo de contrato del cargo principal."""
    return await service.change_contract_type(db, id, data)

@router.delete("/api/enrollments/{enrollment_id}", status_code=204)
@is_admin
async def delete_enrollment_api(enrollment_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    if not await service.remove_training_enrollment(db, enrollment_id): raise HTTPException(404, "Inscripción no encontrada")
    return None

@router.get("/api/enrollments/{enrollment_id}/attendance")
@is_recruiter
async def get_attendance_detail_api(enrollment_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    return await service.get_employee_attendance_detail(db, enrollment_id)

@router.post("/api/{id}/documents")
@is_recruiter
async def upload_doc_api(
    id: int, 
    db: Annotated[AsyncSession, Depends(get_db)], 
    name: str = Form(...), 
    category: str = Form(...), 
    file: UploadFile = File(...), 
    notes: Optional[str] = Form(None),
    expiration_date: Optional[str] = Form(None)
):
    exp_date = None
    if expiration_date and expiration_date.strip():
        try:
            exp_date = datetime.strptime(expiration_date, "%Y-%m-%d").date()
        except ValueError:
            pass

    await service.upload_document(db, id, name, category, file, notes, exp_date)
    return {"message": "Documento subido correctamente"}

@router.delete("/api/documents/{doc_id}", status_code=204)
@is_admin
async def delete_doc_api(doc_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    await service.delete_document(db, doc_id)
    return None

@router.get("/api/{id}/timeline", response_model=List[schemas.TimelineEvent])
@is_recruiter
async def get_timeline_api(id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    return await service.get_employee_timeline(db, id)