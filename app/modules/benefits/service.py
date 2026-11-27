import os
import shutil
from typing import List, Optional, Dict, Any
from datetime import date, datetime
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from sqlalchemy import select, func, or_, desc, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.modules.auth.models import User
from app.modules.benefits.models import (
    BenefitType, EmployeeBenefit, BenefitRequest, BenefitRequestItem, BenefitRequestType, BenefitSubtype, BenefitGrantReason,
    AuthorizationLevel, BenefitModality, BenefitFrequency, BenefitRequestAuthorizer, BenefitRequestAttachment
)
from app.modules.benefits import schemas
from app.modules.employees.models import Employee, EmployeePosition
from app.modules.organization.models import Position, Area

ATTACHMENTS_DIR = "app/static/uploads/benefit_requests"
os.makedirs(ATTACHMENTS_DIR, exist_ok=True)

async def resolve_employee_position_id(db: AsyncSession, employee_id: Optional[int], position_id: Optional[int]) -> Optional[int]:
    if not employee_id:
        return None
    
    # Try to find by employee_id and position_id
    if position_id:
        stmt = select(EmployeePosition.id).where(
            EmployeePosition.employee_id == employee_id,
            EmployeePosition.position_id == position_id
        ).order_by(
            EmployeePosition.is_primary.desc(),
            EmployeePosition.end_date.is_(None).desc(),
            EmployeePosition.id.desc()
        ).limit(1)
        res = (await db.execute(stmt))
        resolved_id = res.scalar()
        if resolved_id:
            return resolved_id
            
    # Fallback to the primary / active position of the employee
    stmt = select(EmployeePosition.id).where(
        EmployeePosition.employee_id == employee_id
    ).order_by(
        EmployeePosition.is_primary.desc(),
        EmployeePosition.end_date.is_(None).desc(),
        EmployeePosition.id.desc()
    ).limit(1)
    res = (await db.execute(stmt))
    return res.scalar()

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
    
    # Extraer items y authorizers
    items_data = data.items
    authorizers_data = data.authorizers or []
    
    # Si authorizers_data viene vacío pero viene authorizer_id principal, creamos uno a partir de él
    if not authorizers_data and data.authorizer_id:
        authorizers_data = [
            schemas.BenefitRequestAuthorizerCreate(
                authorizer_id=data.authorizer_id,
                authorizer_position_id=data.authorizer_position_id,
                authorization_level_id=data.authorization_level_id
            )
        ]
        
    # Resolver los IDs de cargos de los autorizantes a employee_positions.id
    for auth in authorizers_data:
        auth.authorizer_position_id = await resolve_employee_position_id(
            db, auth.authorizer_id, auth.authorizer_position_id
        )
    
    # Establecer los campos legacy basados en el primer autorizante (si existe alguno)
    request_data = data.model_dump(exclude={'items', 'authorizers'})
    
    # Resolver los IDs de cargos del beneficiario y solicitante a employee_positions.id
    request_data['employee_position_id'] = await resolve_employee_position_id(
        db, request_data.get('employee_id'), request_data.get('employee_position_id')
    )
    request_data['requester_position_id'] = await resolve_employee_position_id(
        db, request_data.get('requester_id'), request_data.get('requester_position_id')
    )
    
    if authorizers_data:
        first_auth = authorizers_data[0]
        request_data['authorizer_id'] = first_auth.authorizer_id
        request_data['authorizer_position_id'] = first_auth.authorizer_position_id
        request_data['authorization_level_id'] = first_auth.authorization_level_id
        
    obj = BenefitRequest(request_code=new_code, **request_data)
    db.add(obj)
    await db.flush() # Para obtener el ID
    
    for item in items_data:
        new_item = BenefitRequestItem(benefit_request_id=obj.id, **item.model_dump())
        db.add(new_item)
        
    for auth in authorizers_data:
        new_auth = BenefitRequestAuthorizer(benefit_request_id=obj.id, **auth.model_dump())
        db.add(new_auth)
        
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
            selectinload(BenefitRequest.authorizers)
            .selectinload(BenefitRequestAuthorizer.authorizer)
        )\
        .options(
            selectinload(BenefitRequest.authorizers)
            .selectinload(BenefitRequestAuthorizer.authorizer_position)
        )\
        .options(
            selectinload(BenefitRequest.authorizers)
            .selectinload(BenefitRequestAuthorizer.authorization_level)
        )\
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
        .options(selectinload(BenefitRequest.approved_by))\
        .options(selectinload(BenefitRequest.attachments).selectinload(BenefitRequestAttachment.uploaded_by))\
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
        selectinload(BenefitRequest.authorizers).selectinload(BenefitRequestAuthorizer.authorizer),
        selectinload(BenefitRequest.authorizers).selectinload(BenefitRequestAuthorizer.authorizer_position),
        selectinload(BenefitRequest.authorizers).selectinload(BenefitRequestAuthorizer.authorization_level),
        selectinload(BenefitRequest.items).selectinload(BenefitRequestItem.benefit_type),
        selectinload(BenefitRequest.items).selectinload(BenefitRequestItem.benefit_subtype),
        selectinload(BenefitRequest.items).selectinload(BenefitRequestItem.currency),
        selectinload(BenefitRequest.items).selectinload(BenefitRequestItem.benefit_modality),
        selectinload(BenefitRequest.items).selectinload(BenefitRequestItem.benefit_frequency),
        selectinload(BenefitRequest.approved_by),
        selectinload(BenefitRequest.attachments).selectinload(BenefitRequestAttachment.uploaded_by)
    ).limit(limit)
    
    return (await db.execute(stmt)).scalars().all()

async def update_benefit_request(db: AsyncSession, req_id: int, data: schemas.BenefitRequestCreate) -> BenefitRequest:
    obj = await db.get(BenefitRequest, req_id)
    if not obj:
        return None
        
    items_data = data.items
    authorizers_data = data.authorizers or []
    
    # Si authorizers_data viene vacío pero viene authorizer_id principal, creamos uno a partir de él
    if not authorizers_data and data.authorizer_id:
        authorizers_data = [
            schemas.BenefitRequestAuthorizerCreate(
                authorizer_id=data.authorizer_id,
                authorizer_position_id=data.authorizer_position_id,
                authorization_level_id=data.authorization_level_id
            )
        ]
        
    # Resolver los IDs de cargos de los autorizantes a employee_positions.id
    for auth in authorizers_data:
        auth.authorizer_position_id = await resolve_employee_position_id(
            db, auth.authorizer_id, auth.authorizer_position_id
        )
        
    request_data = data.model_dump(exclude={'items', 'authorizers'}, exclude_unset=True)
    
    # Resolver los IDs de cargos del beneficiario y solicitante a employee_positions.id
    if 'employee_id' in request_data or 'employee_position_id' in request_data:
        emp_id = request_data.get('employee_id') or obj.employee_id
        emp_pos_id = request_data.get('employee_position_id') or obj.employee_position_id
        request_data['employee_position_id'] = await resolve_employee_position_id(db, emp_id, emp_pos_id)
        
    if 'requester_id' in request_data or 'requester_position_id' in request_data:
        req_id_val = request_data.get('requester_id') or obj.requester_id
        req_pos_id = request_data.get('requester_position_id') or obj.requester_position_id
        request_data['requester_position_id'] = await resolve_employee_position_id(db, req_id_val, req_pos_id)
        
    if authorizers_data:
        first_auth = authorizers_data[0]
        request_data['authorizer_id'] = first_auth.authorizer_id
        request_data['authorizer_position_id'] = first_auth.authorizer_position_id
        request_data['authorization_level_id'] = first_auth.authorization_level_id
    else:
        # Si no hay autorizantes, limpiamos los campos legacy
        request_data['authorizer_id'] = None
        request_data['authorizer_position_id'] = None
        request_data['authorization_level_id'] = None
    
    for k, v in request_data.items():
        setattr(obj, k, v)
        
    # Sincronizar items: Borrar y recrear
    await db.execute(delete(BenefitRequestItem).where(BenefitRequestItem.benefit_request_id == req_id))
    for item in items_data:
        new_item = BenefitRequestItem(benefit_request_id=req_id, **item.model_dump())
        db.add(new_item)
        
    # Sincronizar authorizers: Borrar y recrear
    await db.execute(delete(BenefitRequestAuthorizer).where(BenefitRequestAuthorizer.benefit_request_id == req_id))
    for auth in authorizers_data:
        new_auth = BenefitRequestAuthorizer(benefit_request_id=req_id, **auth.model_dump())
        db.add(new_auth)
        
    await db.commit()
    await db.refresh(obj)
    return await get_benefit_request_by_id(db, obj.id)

async def update_request_status(db: AsyncSession, req_id: int, status: str, current_user: Optional[User] = None):
    obj = await db.get(BenefitRequest, req_id)
    if not obj:
        return False

    previous_status = obj.status
    obj.status = status

    if status == "Aprobada":
        obj.approved_at = datetime.now()
        obj.benefit_status = "Activo"
        if current_user:
            obj.approved_by_user_id = current_user.id

        # Solo al pasar a "Aprobada" se cargan automáticamente los beneficios
        if previous_status != "Aprobada":
            items = (
                await db.execute(
                    select(BenefitRequestItem).where(BenefitRequestItem.benefit_request_id == req_id)
                )
            ).scalars().all()

            start = obj.grant_date or date.today()

            for item in items:
                db.add(EmployeeBenefit(
                    employee_id=obj.employee_id,
                    benefit_type_id=item.benefit_type_id,
                    start_date=start,
                    end_date=item.validity_end_date,
                    details=item.description_notes,
                    custom_data=item.custom_data,
                    is_active=True,
                ))
    elif status == "Rechazada":
        obj.benefit_status = "Rechazado"
    elif status == "Anulada":
        obj.benefit_status = "Finalizado"

    await db.commit()
    return True

async def delete_benefit_request(db: AsyncSession, req_id: int) -> bool:
    obj = await db.get(BenefitRequest, req_id)
    if obj:
        await db.delete(obj)
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

# --- ARCHIVOS ADJUNTOS DE SOLICITUDES ---

async def upload_attachment(
    db: AsyncSession,
    req_id: int,
    name: str,
    file: UploadFile,
    current_user: Optional[User] = None
) -> BenefitRequestAttachment:
    """Sube un archivo adjunto (pdf, word, ppt, etc.) a una solicitud de beneficio."""
    request_obj = await db.get(BenefitRequest, req_id)
    if not request_obj:
        raise HTTPException(404, "Solicitud no encontrada")

    extension = ""
    if file.filename and "." in file.filename:
        extension = file.filename.split(".")[-1]
    filename = f"{req_id}_{uuid4()}.{extension}" if extension else f"{req_id}_{uuid4()}"
    file_path = os.path.join(ATTACHMENTS_DIR, filename)

    content = await file.read()
    with open(file_path, "wb") as buffer:
        buffer.write(content)

    attachment = BenefitRequestAttachment(
        benefit_request_id=req_id,
        name=name,
        file_url=f"/static/uploads/benefit_requests/{filename}",
        uploaded_by_user_id=current_user.id if current_user else None
    )
    db.add(attachment)
    await db.commit()
    await db.refresh(attachment)

    # Recargar con la relación uploaded_by para su correcta serialización
    stmt = (
        select(BenefitRequestAttachment)
        .options(selectinload(BenefitRequestAttachment.uploaded_by))
        .where(BenefitRequestAttachment.id == attachment.id)
    )
    return (await db.execute(stmt)).scalar_one()

async def delete_attachment(db: AsyncSession, attachment_id: int) -> bool:
    attachment = await db.get(BenefitRequestAttachment, attachment_id)
    if not attachment:
        return False

    # Eliminar el archivo físico si existe
    if attachment.file_url:
        rel_path = attachment.file_url.lstrip("/")
        abs_path = os.path.join("app", rel_path)
        if os.path.exists(abs_path):
            try:
                os.remove(abs_path)
            except OSError:
                pass

    await db.delete(attachment)
    await db.commit()
    return True

# --- HISTORIAL DE BENEFICIOS DEL COLABORADOR (SOLO REAL / NO PROCESO) ---

async def get_benefit_history_by_employee(
    db: AsyncSession,
    employee_id: int,
    only_approved: bool = False
) -> List[BenefitRequest]:
    """Devuelve todas las solicitudes de beneficio de un colaborador (con su estado).

    Por defecto devuelve todas las solicitudes (Pendiente, Aprobada, Rechazada, Anulada).
    Si `only_approved` es True, solo devuelve las aprobadas (beneficios reales).
    """
    stmt = (
        select(BenefitRequest)
        .options(
            selectinload(BenefitRequest.employee),
            selectinload(BenefitRequest.requester),
            selectinload(BenefitRequest.authorizer),
            selectinload(BenefitRequest.request_type),
            selectinload(BenefitRequest.grant_reason),
            selectinload(BenefitRequest.authorization_level),
            selectinload(BenefitRequest.authorizers).selectinload(BenefitRequestAuthorizer.authorizer),
            selectinload(BenefitRequest.authorizers).selectinload(BenefitRequestAuthorizer.authorizer_position),
            selectinload(BenefitRequest.authorizers).selectinload(BenefitRequestAuthorizer.authorization_level),
            selectinload(BenefitRequest.items).selectinload(BenefitRequestItem.benefit_type),
            selectinload(BenefitRequest.items).selectinload(BenefitRequestItem.benefit_subtype),
            selectinload(BenefitRequest.items).selectinload(BenefitRequestItem.currency),
            selectinload(BenefitRequest.items).selectinload(BenefitRequestItem.benefit_modality),
            selectinload(BenefitRequest.items).selectinload(BenefitRequestItem.benefit_frequency),
            selectinload(BenefitRequest.approved_by),
            selectinload(BenefitRequest.attachments).selectinload(BenefitRequestAttachment.uploaded_by),
        )
        .where(BenefitRequest.employee_id == employee_id)
    )
    if only_approved:
        stmt = stmt.where(BenefitRequest.status == "Aprobada")
    stmt = stmt.order_by(desc(BenefitRequest.created_at))
    result = await db.execute(stmt)
    return result.scalars().all()