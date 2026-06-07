from typing import List, Optional, Dict, Any
from fastapi import HTTPException
from sqlalchemy import select, func, or_, desc, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.modules.benefits.models import (
    BenefitType, EmployeeBenefit, BenefitRequest, BenefitRequestItem, BenefitRequestType, BenefitSubtype, BenefitGrantReason,
    AuthorizationLevel, BenefitModality, BenefitFrequency
)
from app.modules.benefits import schemas
from app.modules.employees.models import Employee
from app.modules.organization.models import Position, Area

async def get_benefit_types(db: AsyncSession, only_active: bool = False) -> List[BenefitType]:
    stmt = select(BenefitType).order_by(BenefitType.name)
    if only_active:
        stmt = stmt.where(BenefitType.is_active == True)
    result = await db.execute(stmt)
    return result.scalars().all()

async def get_benefit_type_by_id(db: AsyncSession, id: int) -> Optional[BenefitType]:
    """Obtiene un tipo de beneficio por ID."""
    return await db.get(BenefitType, id)

async def create_benefit_type(db: AsyncSession, data: schemas.BenefitTypeCreate):
    benefit = BenefitType(**data.model_dump())
    db.add(benefit)
    await db.commit()
    return benefit

async def update_benefit_type(db: AsyncSession, id: int, data: schemas.BenefitTypeUpdate):
    benefit = await db.get(BenefitType, id)
    if not benefit:
        return None
    
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(benefit, key, value)
    
    await db.commit()
    await db.refresh(benefit)
    return benefit

async def delete_benefit_type(db: AsyncSession, id: int):
    benefit = await db.get(BenefitType, id)
    if not benefit:
        raise HTTPException(404, "Tipo de beneficio no encontrado")

    # Validación RESTRICTED
    stmt = (
        select(Employee.full_name)
        .join(EmployeeBenefit)
        .where(EmployeeBenefit.benefit_type_id == id)
        .limit(5)
    )
    result = await db.execute(stmt)
    employees = result.scalars().all()

    if employees:
        count_stmt = select(func.count()).where(EmployeeBenefit.benefit_type_id == id)
        total = await db.scalar(count_stmt)
        
        names = ", ".join(employees)
        msg = f"No se puede eliminar. Está asignado a {total} colaboradores, incluyendo: {names}..."
        raise HTTPException(400, msg)

    await db.delete(benefit)
    await db.commit()

# --- REQUEST CATALOGS CRUD ---

async def get_request_types(db: AsyncSession, only_active: bool = False):
    stmt = select(BenefitRequestType).order_by(BenefitRequestType.name)
    if only_active: stmt = stmt.where(BenefitRequestType.is_active == True)
    return (await db.execute(stmt)).scalars().all()

async def create_request_type(db: AsyncSession, data: schemas.RequestTypeCreate):
    obj = BenefitRequestType(**data.model_dump())
    db.add(obj); await db.commit(); await db.refresh(obj)
    return obj

async def update_request_type(db: AsyncSession, id: int, data: schemas.RequestTypeUpdate):
    obj = await db.get(BenefitRequestType, id)
    if not obj: return None
    for k, v in data.model_dump(exclude_unset=True).items(): setattr(obj, k, v)
    await db.commit(); await db.refresh(obj)
    return obj

async def delete_request_type(db: AsyncSession, id: int):
    obj = await db.get(BenefitRequestType, id)
    if obj:
        await db.delete(obj); await db.commit()

async def get_subtypes(db: AsyncSession, only_active: bool = False):
    stmt = select(BenefitSubtype).order_by(BenefitSubtype.name)
    if only_active: stmt = stmt.where(BenefitSubtype.is_active == True)
    return (await db.execute(stmt)).scalars().all()

async def create_subtype(db: AsyncSession, data: schemas.SubtypeCreate):
    obj = BenefitSubtype(**data.model_dump())
    db.add(obj); await db.commit(); await db.refresh(obj)
    return obj

async def update_subtype(db: AsyncSession, id: int, data: schemas.SubtypeUpdate):
    obj = await db.get(BenefitSubtype, id)
    if not obj: return None
    for k, v in data.model_dump(exclude_unset=True).items(): setattr(obj, k, v)
    await db.commit(); await db.refresh(obj)
    return obj

async def delete_subtype(db: AsyncSession, id: int):
    obj = await db.get(BenefitSubtype, id)
    if obj:
        await db.delete(obj); await db.commit()

async def get_grant_reasons(db: AsyncSession, only_active: bool = False):
    stmt = select(BenefitGrantReason).order_by(BenefitGrantReason.name)
    if only_active: stmt = stmt.where(BenefitGrantReason.is_active == True)
    return (await db.execute(stmt)).scalars().all()

async def create_grant_reason(db: AsyncSession, data: schemas.GrantReasonCreate):
    obj = BenefitGrantReason(**data.model_dump())
    db.add(obj); await db.commit(); await db.refresh(obj)
    return obj

async def update_grant_reason(db: AsyncSession, id: int, data: schemas.GrantReasonUpdate):
    obj = await db.get(BenefitGrantReason, id)
    if not obj: return None
    for k, v in data.model_dump(exclude_unset=True).items(): setattr(obj, k, v)
    await db.commit(); await db.refresh(obj)
    return obj

async def delete_grant_reason(db: AsyncSession, id: int):
    obj = await db.get(BenefitGrantReason, id)
    if obj:
        await db.delete(obj); await db.commit()

# --- NUEVOS CATALOGOS DE APROBACIÓN ---

async def get_authorization_levels(db: AsyncSession, only_active: bool = False):
    stmt = select(AuthorizationLevel).order_by(AuthorizationLevel.name)
    if only_active: stmt = stmt.where(AuthorizationLevel.is_active == True)
    return (await db.execute(stmt)).scalars().all()

async def create_authorization_level(db: AsyncSession, data: schemas.AuthorizationLevelCreate):
    obj = AuthorizationLevel(**data.model_dump())
    db.add(obj); await db.commit(); await db.refresh(obj)
    return obj

async def update_authorization_level(db: AsyncSession, id: int, data: schemas.AuthorizationLevelUpdate):
    obj = await db.get(AuthorizationLevel, id)
    if not obj: return None
    for k, v in data.model_dump(exclude_unset=True).items(): setattr(obj, k, v)
    await db.commit(); await db.refresh(obj)
    return obj

async def delete_authorization_level(db: AsyncSession, id: int):
    obj = await db.get(AuthorizationLevel, id)
    if obj: await db.delete(obj); await db.commit()

async def get_benefit_modalities(db: AsyncSession, only_active: bool = False):
    stmt = select(BenefitModality).order_by(BenefitModality.name)
    if only_active: stmt = stmt.where(BenefitModality.is_active == True)
    return (await db.execute(stmt)).scalars().all()

async def create_benefit_modality(db: AsyncSession, data: schemas.BenefitModalityCreate):
    obj = BenefitModality(**data.model_dump())
    db.add(obj); await db.commit(); await db.refresh(obj)
    return obj

async def update_benefit_modality(db: AsyncSession, id: int, data: schemas.BenefitModalityUpdate):
    obj = await db.get(BenefitModality, id)
    if not obj: return None
    for k, v in data.model_dump(exclude_unset=True).items(): setattr(obj, k, v)
    await db.commit(); await db.refresh(obj)
    return obj

async def delete_benefit_modality(db: AsyncSession, id: int):
    obj = await db.get(BenefitModality, id)
    if obj: await db.delete(obj); await db.commit()

async def get_benefit_frequencies(db: AsyncSession, only_active: bool = False):
    stmt = select(BenefitFrequency).order_by(BenefitFrequency.name)
    if only_active: stmt = stmt.where(BenefitFrequency.is_active == True)
    return (await db.execute(stmt)).scalars().all()

async def create_benefit_frequency(db: AsyncSession, data: schemas.BenefitFrequencyCreate):
    obj = BenefitFrequency(**data.model_dump())
    db.add(obj); await db.commit(); await db.refresh(obj)
    return obj

async def update_benefit_frequency(db: AsyncSession, id: int, data: schemas.BenefitFrequencyUpdate):
    obj = await db.get(BenefitFrequency, id)
    if not obj: return None
    for k, v in data.model_dump(exclude_unset=True).items(): setattr(obj, k, v)
    await db.commit(); await db.refresh(obj)
    return obj

async def delete_benefit_frequency(db: AsyncSession, id: int):
    obj = await db.get(BenefitFrequency, id)
    if obj: await db.delete(obj); await db.commit()


# --- REQUESTS CORE LOGIC ---

async def create_benefit_request(db: AsyncSession, data: schemas.BenefitRequestCreate) -> BenefitRequest:
    # Generar código auto-incremental BEXXX
    stmt_max = select(func.max(BenefitRequest.id))
    max_id = (await db.execute(stmt_max)).scalar() or 0
    next_id = max_id + 1
    new_code = f"BE{next_id:03d}"
    
    # Extraer items
    items_data = data.items
    request_data = data.model_dump(exclude={'items'})
    
    obj = BenefitRequest(request_code=new_code, **request_data)
    db.add(obj)
    await db.flush() # Para obtener el ID
    
    for item in items_data:
        new_item = BenefitRequestItem(benefit_request_id=obj.id, **item.model_dump())
        db.add(new_item)
        
    await db.commit()
    await db.refresh(obj)
    return await get_benefit_request_by_id(db, obj.id)

async def get_benefit_request_by_id(db: AsyncSession, req_id: int):
    stmt = select(BenefitRequest)\
        .options(selectinload(BenefitRequest.employee))\
        .options(selectinload(BenefitRequest.employee_position))\
        .options(selectinload(BenefitRequest.requester))\
        .options(selectinload(BenefitRequest.requester_position))\
        .options(selectinload(BenefitRequest.authorizer))\
        .options(selectinload(BenefitRequest.authorizer_position))\
        .options(selectinload(BenefitRequest.request_type))\
        .options(selectinload(BenefitRequest.grant_reason))\
        .options(selectinload(BenefitRequest.authorization_level))\
        .options(
            selectinload(BenefitRequest.items)
            .selectinload(BenefitRequestItem.benefit_type)
        )\
        .options(
            selectinload(BenefitRequest.items)
            .selectinload(BenefitRequestItem.benefit_subtype)
        )\
        .options(
            selectinload(BenefitRequest.items)
            .selectinload(BenefitRequestItem.currency)
        )\
        .options(
            selectinload(BenefitRequest.items)
            .selectinload(BenefitRequestItem.benefit_modality)
        )\
        .options(
            selectinload(BenefitRequest.items)
            .selectinload(BenefitRequestItem.benefit_frequency)
        )\
        .where(BenefitRequest.id == req_id)
    return (await db.execute(stmt)).scalar_one_or_none()

async def list_benefit_requests(
    db: AsyncSession, 
    status: Optional[str] = None, 
    search: Optional[str] = None,
    limit: int = 100
):
    stmt = select(BenefitRequest).order_by(desc(BenefitRequest.created_at))
    
    if status:
        stmt = stmt.where(BenefitRequest.status == status)
        
    if search:
        stmt = stmt.join(BenefitRequest.employee)\
            .where(or_(
                BenefitRequest.request_code.ilike(f"%{search}%"),
                Employee.full_name.ilike(f"%{search}%")
            ))
            
    stmt = stmt.options(
        selectinload(BenefitRequest.employee),
        selectinload(BenefitRequest.employee_position),
        selectinload(BenefitRequest.requester),
        selectinload(BenefitRequest.requester_position),
        selectinload(BenefitRequest.authorizer),
        selectinload(BenefitRequest.authorizer_position),
        selectinload(BenefitRequest.request_type),
        selectinload(BenefitRequest.grant_reason),
        selectinload(BenefitRequest.authorization_level),
        selectinload(BenefitRequest.items).selectinload(BenefitRequestItem.benefit_type),
        selectinload(BenefitRequest.items).selectinload(BenefitRequestItem.benefit_subtype),
        selectinload(BenefitRequest.items).selectinload(BenefitRequestItem.currency),
        selectinload(BenefitRequest.items).selectinload(BenefitRequestItem.benefit_modality),
        selectinload(BenefitRequest.items).selectinload(BenefitRequestItem.benefit_frequency)
    ).limit(limit)
    
    return (await db.execute(stmt)).scalars().all()

async def update_benefit_request(db: AsyncSession, req_id: int, data: schemas.BenefitRequestCreate) -> BenefitRequest:
    obj = await db.get(BenefitRequest, req_id)
    if not obj:
        return None
        
    items_data = data.items
    request_data = data.model_dump(exclude={'items'}, exclude_unset=True)
    
    for k, v in request_data.items():
        setattr(obj, k, v)
        
    # Sincronizar items: Borrar y recrear
    await db.execute(delete(BenefitRequestItem).where(BenefitRequestItem.benefit_request_id == req_id))
    
    for item in items_data:
        new_item = BenefitRequestItem(benefit_request_id=req_id, **item.model_dump())
        db.add(new_item)
        
    await db.commit()
    await db.refresh(obj)
    return await get_benefit_request_by_id(db, obj.id)

async def update_request_status(db: AsyncSession, req_id: int, status: str):
    obj = await db.get(BenefitRequest, req_id)
    if obj:
        obj.status = status
        await db.commit()
        return True
    return False

# --- ASIGNACIONES ---

async def assign_benefit(db: AsyncSession, emp_id: int, data: schemas.EmployeeBenefitCreate):
    benefit = EmployeeBenefit(
        employee_id=emp_id,
        benefit_type_id=data.benefit_type_id,
        start_date=data.start_date,
        details=data.details,
        custom_data=data.custom_data
    )
    db.add(benefit)
    await db.commit()
    
    stmt = select(EmployeeBenefit).options(selectinload(EmployeeBenefit.benefit_type)).where(EmployeeBenefit.id == benefit.id)
    result = await db.execute(stmt)
    return result.scalar_one()

async def remove_benefit(db: AsyncSession, benefit_id: int):
    benefit = await db.get(EmployeeBenefit, benefit_id)
    if benefit:
        await db.delete(benefit)
        await db.commit()

# --- LISTAR EMPLEADOS POR BENEFICIO (CON BUSCADOR) ---

async def get_employees_by_benefit(
    db: AsyncSession, 
    benefit_type_id: int, 
    search: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Obtiene la lista de empleados que tienen asignado un beneficio, con filtro opcional."""
    stmt = (
        select(EmployeeBenefit)
        .join(Employee)
        .join(Position, Employee.position_id == Position.id)
        .join(Area, Position.area_id == Area.id)
        .options(
            selectinload(EmployeeBenefit.employee)
            .selectinload(Employee.position_obj)
            .selectinload(Position.area)
        )
        .where(EmployeeBenefit.benefit_type_id == benefit_type_id)
    )

    if search:
        term = f"%{search}%"
        stmt = stmt.where(
            or_(
                Employee.full_name.ilike(term),
                Employee.document_id.ilike(term),
                Area.name.ilike(term)
            )
        )
    
    stmt = stmt.order_by(Employee.full_name)
    
    result = await db.execute(stmt)
    assignments = result.scalars().all()
    
    data = []
    for a in assignments:
        data.append({
            "id": a.id, # ID de la asignación para poder borrarla
            "employee_id": a.employee.id,
            "employee_name": a.employee.full_name,
            "document_id": a.employee.document_id,
            "area_name": a.employee.position_obj.area.name,
            "position_name": a.employee.position_obj.name,
            "start_date": a.start_date,
            "details": a.details
        })
    return data