"""
Lógica de negocio principal para el módulo de Colaboradores.
"""

import os
import shutil
import secrets
import string
from datetime import date, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import HTTPException, UploadFile, BackgroundTasks
from sqlalchemy import desc, func, or_, select, update, distinct
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import get_password_hash
from app.modules.auth.models import User, UserRole
from app.modules.employees import schemas
from app.modules.employees.models import (
    Employee,
    EmployeeDocument,
    EmployeeHistory,
    EmployeePosition,
    EmergencyContact,
    MovementType,
    DocumentCategory
)
from app.modules.dietary.models import DietaryRestriction
from app.modules.organization.models import Area, Position, Sede, ContractType, ProbationDuration
from app.modules.trainings.models import (
    TrainingAttendance,
    TrainingEnrollment,
    TrainingSession,
)
from app.modules.benefits.models import EmployeeBenefit
from app.modules.notifications.service import send_email_notification
from app.core.config import settings

UPLOAD_DIR = "app/static/uploads/employees"
DOCS_DIR = "app/static/uploads/documents"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(DOCS_DIR, exist_ok=True)

async def save_photo(file: UploadFile) -> str:
    extension = file.filename.split(".")[-1]
    filename = f"{uuid4()}.{extension}"
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    content = await file.read()
    with open(file_path, "wb") as buffer:
        buffer.write(content)
        
    return f"/static/uploads/employees/{filename}"

def generate_random_password(length=10):
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(alphabet) for i in range(length))

# --- EMPLOYEE CRUD ---

async def get_employees_paginated(
    db: AsyncSession, 
    page: int = 1, 
    limit: int = 10, 
    search: Optional[str] = None,
    area_id: Optional[int] = None,
    sede_id: Optional[int] = None,
    company_id: Optional[int] = None,
    gender: Optional[str] = None,
    dietary_id: Optional[int] = None,
    birth_month: Optional[int] = None,
    is_leader: Optional[bool] = None
) -> Dict[str, Any]:
    offset = (page - 1) * limit
    base_stmt = select(Employee).distinct()

    if area_id or sede_id or is_leader is not None:
        base_stmt = base_stmt.join(Position, Employee.position_id == Position.id)
    
    if area_id or sede_id:
        base_stmt = base_stmt.join(Area, Position.area_id == Area.id)
    
    if dietary_id:
        base_stmt = base_stmt.join(Employee.dietary_restrictions)

    if search:
        term = f"%{search}%"
        base_stmt = base_stmt.where(
            or_(
                Employee.full_name.ilike(term),
                Employee.document_id.ilike(term),
                Employee.institutional_email.ilike(term),
                Employee.secondary_emails.ilike(term)
            )
        )
    
    if area_id: base_stmt = base_stmt.where(Area.id == area_id)
    if sede_id: base_stmt = base_stmt.where(Area.sede_id == sede_id)
    if company_id: base_stmt = base_stmt.where(Employee.company_id == company_id)
    if gender: base_stmt = base_stmt.where(Employee.gender == gender)
    if dietary_id: base_stmt = base_stmt.where(DietaryRestriction.id == dietary_id)
    if birth_month: base_stmt = base_stmt.where(func.extract('month', Employee.birthday) == birth_month)
    if is_leader is not None: base_stmt = base_stmt.where(Position.is_leader == is_leader)

    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total = await db.scalar(count_stmt) or 0

    items_stmt = base_stmt.options(
        selectinload(Employee.position_obj).selectinload(Position.area).selectinload(Area.sede),
        selectinload(Employee.position_obj).selectinload(Position.parent),
        selectinload(Employee.company)
    ).order_by(Employee.full_name).offset(offset).limit(limit)

    result = await db.execute(items_stmt)
    items = result.scalars().all()

    total_pages = (total + limit - 1) // limit if limit > 0 else 0

    return {
        "data": items, "total": total, "page": page, "limit": limit,
        "total_pages": total_pages, "has_next": page < total_pages, "has_prev": page > 1
    }

async def get_employee_detail(db: AsyncSession, emp_id: int) -> Optional[Employee]:
    stmt = (
        select(Employee)
        .options(
            selectinload(Employee.position_obj).selectinload(Position.area).selectinload(Area.sede),
            selectinload(Employee.position_obj).selectinload(Position.parent),
            selectinload(Employee.company),
            selectinload(Employee.positions_history).selectinload(EmployeePosition.position).selectinload(Position.area).selectinload(Area.sede),
            selectinload(Employee.positions_history).selectinload(EmployeePosition.company),
            selectinload(Employee.positions_history).selectinload(EmployeePosition.contract_type),
            selectinload(Employee.positions_history).selectinload(EmployeePosition.working_day_type),
            selectinload(Employee.positions_history).selectinload(EmployeePosition.salary_type),
            selectinload(Employee.positions_history).selectinload(EmployeePosition.currency),
            selectinload(Employee.positions_history).selectinload(EmployeePosition.payment_method),
            selectinload(Employee.positions_history).selectinload(EmployeePosition.bank),
            selectinload(Employee.positions_history).selectinload(EmployeePosition.cost_center),
            selectinload(Employee.positions_history).selectinload(EmployeePosition.probation_duration),
            selectinload(Employee.trainings).selectinload(TrainingEnrollment.training),
            selectinload(Employee.emergency_contacts).selectinload(EmergencyContact.relationship),
            selectinload(Employee.history).selectinload(EmployeeHistory.new_position).selectinload(Position.area).selectinload(Area.sede),
            selectinload(Employee.history).selectinload(EmployeeHistory.new_position).selectinload(Position.parent),
            selectinload(Employee.history).selectinload(EmployeeHistory.company),
            selectinload(Employee.history).selectinload(EmployeeHistory.contract_type),
            selectinload(Employee.history).selectinload(EmployeeHistory.currency),
            selectinload(Employee.documents),
            selectinload(Employee.benefits).selectinload(EmployeeBenefit.benefit_type),
            selectinload(Employee.sanctions),
            selectinload(Employee.recognitions),
            selectinload(Employee.dietary_restrictions)
        )
        .where(Employee.id == emp_id)
    )
    return (await db.execute(stmt)).scalar_one_or_none()

async def create_employee(
    db: AsyncSession,
    emp_data: schemas.EmployeeCreate,
    photo: Optional[UploadFile] = None,
    background_tasks: Optional[BackgroundTasks] = None,
    emergency_contacts_str: Optional[str] = None
) -> Employee:
    data = emp_data.model_dump()
    data["full_name"] = f"{data['first_name']} {data['last_name']}"
    
    restriction_ids = data.pop("dietary_restriction_ids", [])
    
    # Extraer campos de contratación y periodo de prueba
    hiring_fields = [
        "contract_type_id", "contract_end_date", "working_day_type_id",
        "work_schedule", "work_days", "salary_type_id", "base_salary",
        "currency_id", "payment_method_id", "bank_id", "cost_center_id",
        "probation_duration_id", "probation_start_date", "probation_evaluation"
    ]
    hiring_data = {f: data.pop(f, None) for f in hiring_fields}

    # Lógica automática de Periodo de Prueba para el ingreso
    if hiring_data.get("probation_duration_id"):
        # Obtener los días de la duración seleccionada
        prob_dur = await db.get(ProbationDuration, hiring_data["probation_duration_id"])
        if prob_dur:
            # fecha_inicio = fecha_ingreso (hoy por defecto en creación)
            start_date = date.today()
            hiring_data["probation_start_date"] = start_date
            # fecha_fin = inicio + días
            hiring_data["probation_end_date"] = start_date + timedelta(days=prob_dur.days)
            # evaluación inicial
            if not hiring_data.get("probation_evaluation"):
                hiring_data["probation_evaluation"] = "Pendiente"
            # estado automático
            hiring_data["probation_status"] = "Pendiente" if hiring_data["probation_evaluation"] == "Pendiente" else "Finalizado"

    restrictions_list = []
    if restriction_ids:
        result = await db.execute(select(DietaryRestriction).where(DietaryRestriction.id.in_(restriction_ids)))
        restrictions_list = result.scalars().all()

    if photo and photo.filename:
        data["photo_url"] = await save_photo(photo)

    new_emp = Employee(**data)
    new_emp.dietary_restrictions = restrictions_list
    
    if emergency_contacts_str:
        import json
        try:
            contacts_list = json.loads(emergency_contacts_str)
            for c in contacts_list:
                rel_id = c.get("relationship_id")
                if rel_id == "": rel_id = None
                elif rel_id is not None: rel_id = int(rel_id)
                new_emp.emergency_contacts.append(
                    EmergencyContact(name=c["name"], relationship_id=rel_id, phone=c["phone"])
                )
        except Exception as e:
            pass

    db.add(new_emp)

    try:
        await db.flush()
        
        history = EmployeeHistory(
            employee_id=new_emp.id,
            movement_type=MovementType.ENTRY,
            new_position_id=new_emp.position_id,
            company_id=new_emp.company_id,
            contract_type_id=hiring_data.get("contract_type_id"),
            base_salary=hiring_data.get("base_salary"),
            currency_id=hiring_data.get("currency_id"),
            notes="Ingreso al sistema",
        )
        db.add(history)

        emp_pos = EmployeePosition(
            employee_id=new_emp.id,
            position_id=new_emp.position_id,
            company_id=new_emp.company_id,
            is_primary=True,
            start_date=date.today(),
            **hiring_data
        )
        db.add(emp_pos)

        if new_emp.institutional_email:
            existing_user = await db.scalar(select(User).where(User.email == new_emp.institutional_email))
            if not existing_user:
                temp_password = generate_random_password()
                hashed_pwd = get_password_hash(temp_password)
                position = await db.get(Position, new_emp.position_id)
                new_user = User(
                    email=new_emp.institutional_email,
                    full_name=new_emp.full_name,
                    hashed_password=hashed_pwd,
                    role=UserRole.EMPLOYEE,
                    is_active=True,
                    employee_id=new_emp.id,
                    area_id=position.area_id if position else None
                )
                db.add(new_user)
                # Enviar correo (simplificado)
                if background_tasks:
                    await send_email_notification(db, new_emp.institutional_email, "Bienvenido", f"Tu contraseña temporal es: {temp_password}", background_tasks)

        await db.commit()
        return await get_employee_detail(db, new_emp.id)

    except IntegrityError as e:
        await db.rollback()
        if "employees_document_id_key" in str(e.orig):
            raise HTTPException(400, "Ya existe un colaborador con ese Documento.")
        raise HTTPException(400, "Error de integridad en la base de datos.")

async def update_employee(
    db: AsyncSession,
    emp_id: int,
    emp_data: schemas.EmployeeUpdate,
    photo: Optional[UploadFile] = None,
) -> Optional[Employee]:
    emp = await get_employee_detail(db, emp_id)
    if not emp: return None

    # Excluir None para evitar sobreescribir con vacíos campos que no se enviaron
    data = emp_data.model_dump(exclude_none=True)

    if photo and photo.filename:
        data["photo_url"] = await save_photo(photo)

    if "first_name" in data or "last_name" in data:
        fname = data.get("first_name", emp.first_name)
        lname = data.get("last_name", emp.last_name)
        data["full_name"] = f"{fname} {lname}"
        user = await db.scalar(select(User).where(User.employee_id == emp.id))
        if user:
            user.full_name = data["full_name"]
            db.add(user)

    if "dietary_restriction_ids" in data:
        r_ids = data.pop("dietary_restriction_ids")
        if r_ids is not None:
            restrictions = await db.execute(select(DietaryRestriction).where(DietaryRestriction.id.in_(r_ids)))
            emp.dietary_restrictions = restrictions.scalars().all()

    # Actualización de cargo/empresa/contratación (Corrección, no movimiento)
    hiring_fields = [
        "contract_type_id", "contract_end_date", "working_day_type_id",
        "work_schedule", "work_days", "salary_type_id", "base_salary",
        "currency_id", "payment_method_id", "bank_id", "cost_center_id",
        "probation_duration_id", "probation_start_date", "probation_evaluation"
    ]
    
    # Extraer ID de posición específico si viene en el form (para cargos secundarios)
    target_pos_id = data.pop("employee_position_id", None)
    hiring_updates = {f: data.pop(f) for f in hiring_fields if f in data}

    if ("position_id" in data and data["position_id"] != emp.position_id) or \
       ("company_id" in data and data["company_id"] != emp.company_id) or \
       hiring_updates:
        
        # Si no se especifica ID, buscamos el primario activo por defecto
        if target_pos_id:
            stmt_pos = select(EmployeePosition).where(
                EmployeePosition.id == int(target_pos_id),
                EmployeePosition.employee_id == emp.id
            )
        else:
            stmt_pos = select(EmployeePosition).where(
                EmployeePosition.employee_id == emp.id, 
                EmployeePosition.is_primary == True,
                EmployeePosition.end_date.is_(None)
            )
            
        current_pos = (await db.execute(stmt_pos)).scalar_one_or_none()
        if current_pos:
            if "position_id" in data: current_pos.position_id = data["position_id"]
            if "company_id" in data: current_pos.company_id = data["company_id"]
            
            # Lógica de cálculo automático de periodo de prueba en edición
            new_prob_dur_id = hiring_updates.get("probation_duration_id")
            new_prob_start = hiring_updates.get("probation_start_date")
            new_prob_eval = hiring_updates.get("probation_evaluation")

            # Si cambia la duración o el inicio, recalculamos el fin
            if new_prob_dur_id or new_prob_start:
                dur_id = new_prob_dur_id or current_pos.probation_duration_id
                start_dt = new_prob_start or current_pos.probation_start_date
                if dur_id and start_dt:
                    prob_dur = await db.get(ProbationDuration, dur_id)
                    if prob_dur:
                        current_pos.probation_end_date = start_dt + timedelta(days=prob_dur.days)
            
            # Si cambia la evaluación, actualizamos el estado
            if new_prob_eval:
                current_pos.probation_status = "Pendiente" if new_prob_eval == "Pendiente" else "Finalizado"
            elif "probation_evaluation" in hiring_updates: # Si se mandó explícito pero es el mismo
                current_pos.probation_status = "Pendiente" if hiring_updates["probation_evaluation"] == "Pendiente" else "Finalizado"

            for k, v in hiring_updates.items():
                setattr(current_pos, k, v)
                
            db.add(current_pos)

    # CAMPOS DE CONTACTO Y UBICACIÓN
    contact_fields = [
        "address", "personal_email", "phone"
    ]
    for field in contact_fields:
        if field in data:
            setattr(emp, field, data.pop(field))

    if "emergency_contacts" in data:
        contacts_str = data.pop("emergency_contacts")
        if contacts_str is not None:
            import json
            # Borrar actuales (o cascade)
            for ec in list(emp.emergency_contacts):
                await db.delete(ec)
            emp.emergency_contacts.clear()
            
            try:
                contacts_list = json.loads(contacts_str)
                for c in contacts_list:
                    rel_id = c.get("relationship_id")
                    if rel_id == "": rel_id = None
                    elif rel_id is not None: rel_id = int(rel_id)
                    emp.emergency_contacts.append(
                        EmergencyContact(name=c["name"], relationship_id=rel_id, phone=c["phone"])
                    )
            except Exception as e:
                pass

    if "document_id" in data and data["document_id"] == emp.document_id:
        del data["document_id"]

    for key, value in data.items():
        setattr(emp, key, value)

    try:
        await db.commit()
        return await get_employee_detail(db, emp_id)
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(400, f"Error de integridad: {str(e.orig)}")

async def remove_training_enrollment(db: AsyncSession, enrollment_id: int) -> bool:
    enroll = await db.get(TrainingEnrollment, enrollment_id)
    if not enroll: return False
    await db.delete(enroll)
    await db.commit()
    return True

async def add_secondary_position(db: AsyncSession, emp_id: int, data: schemas.AddPositionPayload) -> Employee:
    emp = await db.get(Employee, emp_id)
    if not emp: raise HTTPException(404, "Colaborador no encontrado")
    
    payload = data.model_dump()
    notes = payload.pop("notes", "")
    
    new_pos = EmployeePosition(
        employee_id=emp_id, 
        is_primary=False, 
        **payload
    )
    db.add(new_pos)
    
    pos_obj = await db.get(Position, data.position_id)
    history = EmployeeHistory(
        employee_id=emp_id, 
        movement_type=MovementType.ADD_ROLE, 
        date=data.start_date, 
        new_position_id=data.position_id, 
        company_id=data.company_id,
        contract_type_id=data.contract_type_id,
        base_salary=data.base_salary,
        currency_id=data.currency_id,
        notes=f"Asignación cargo secundario: {pos_obj.name}. {notes or ''}"
    )
    db.add(history)
    await db.commit()
    return await get_employee_detail(db, emp_id)

async def remove_secondary_position(db: AsyncSession, emp_pos_id: int) -> bool:
    emp_pos = await db.get(EmployeePosition, emp_pos_id)
    if not emp_pos: return False
    if emp_pos.is_primary: raise HTTPException(400, "No se puede eliminar el cargo principal desde aquí.")
    
    emp_pos.end_date = date.today()
    await db.refresh(emp_pos, attribute_names=["position"])
    
    history = EmployeeHistory(
        employee_id=emp_pos.employee_id, 
        movement_type=MovementType.REMOVE_ROLE, 
        date=date.today(), 
        previous_position_name=f"{emp_pos.position.name} (Secundario)", 
        company_id=emp_pos.company_id,
        contract_type_id=emp_pos.contract_type_id,
        notes="Fin de asignación secundaria"
    )
    db.add(history)
    await db.commit()
    return True

async def promote_employee(db: AsyncSession, emp_id: int, data: schemas.PromotionPayload) -> Employee:
    emp = await get_employee_detail(db, emp_id)
    if not emp: raise HTTPException(404, "Colaborador no encontrado")
    
    history_company_id = None
    history_contract_id = data.new_contract_type_id
    
    if data.is_primary_promotion:
        # Cerrar cargo principal actual
        await db.execute(update(EmployeePosition).where(
            EmployeePosition.employee_id == emp.id, 
            EmployeePosition.is_primary == True, 
            EmployeePosition.end_date.is_(None)
        ).values(end_date=data.date, is_primary=False))
        
        # Si no se especifica contrato nuevo, intentar heredar el anterior
        if not history_contract_id:
            current_pos = next((p for p in emp.positions_history if p.is_primary and p.end_date == data.date), None)
            if current_pos: history_contract_id = current_pos.contract_type_id
        
        # Heredar otros campos de contratación del cargo que se cierra
        current_pos = next((p for p in emp.positions_history if p.is_primary and p.end_date == data.date), None)
        hiring_inheritance = {}
        if current_pos:
            fields_to_inherit = [
                "working_day_type_id", "work_schedule", "work_days", 
                "salary_type_id", "base_salary", "currency_id", 
                "payment_method_id", "bank_id", "cost_center_id"
            ]
            hiring_inheritance = {f: getattr(current_pos, f) for f in fields_to_inherit}

        new_pos_entry = EmployeePosition(
            employee_id=emp.id, 
            position_id=data.new_position_id, 
            company_id=data.new_company_id or emp.company_id,
            contract_type_id=history_contract_id,
            is_primary=True, 
            start_date=data.date,
            **hiring_inheritance
        )
        db.add(new_pos_entry)
        
        prev_pos_name = emp.position_obj.name
        prev_area_name = emp.position_obj.area.name
        
        # Actualizar empleado
        emp.position_id = data.new_position_id
        if data.new_company_id: emp.company_id = data.new_company_id
        history_company_id = data.new_company_id or emp.company_id
            
    else:
        # Promoción de cargo secundario
        if not data.previous_employee_position_id: raise HTTPException(400, "Especifique cargo secundario.")
        prev_emp_pos = await db.get(EmployeePosition, data.previous_employee_position_id)
        if not prev_emp_pos: raise HTTPException(404, "Cargo anterior no encontrado")
        
        await db.refresh(prev_emp_pos, attribute_names=["position"])
        prev_emp_pos.end_date = data.date
        prev_pos_name = prev_emp_pos.position.name
        prev_area_name = prev_emp_pos.position.area.name if prev_emp_pos.position.area else "Sin Área"
        
        if not history_contract_id: history_contract_id = prev_emp_pos.contract_type_id

        new_pos_entry = EmployeePosition(
            employee_id=emp.id, 
            position_id=data.new_position_id, 
            company_id=data.new_company_id or prev_emp_pos.company_id,
            contract_type_id=history_contract_id,
            is_primary=False, 
            start_date=data.date
        )
        db.add(new_pos_entry)
        history_company_id = data.new_company_id or prev_emp_pos.company_id
        
    history = EmployeeHistory(
        employee_id=emp.id, 
        movement_type=MovementType.PROMOTION, 
        date=data.date, 
        previous_position_name=prev_pos_name, 
        previous_area_name=prev_area_name, 
        new_position_id=data.new_position_id, 
        company_id=history_company_id,
        contract_type_id=history_contract_id,
        notes=data.notes
    )
    db.add(history)
    await db.commit()
    return await get_employee_detail(db, emp_id)

async def terminate_employee(db: AsyncSession, emp_id: int, data: schemas.ExitPayload) -> Employee:
    emp = await get_employee_detail(db, emp_id)
    if not emp: raise HTTPException(404, "Colaborador no encontrado")
    
    # Cerrar todos los cargos activos
    await db.execute(update(EmployeePosition).where(
        EmployeePosition.employee_id == emp.id, 
        EmployeePosition.end_date.is_(None)
    ).values(end_date=data.date))
    
    history = EmployeeHistory(
        employee_id=emp.id, 
        movement_type=MovementType.EXIT, 
        date=data.date, 
        previous_position_name=emp.position_obj.name, 
        previous_area_name=emp.position_obj.area.name, 
        company_id=emp.company_id,
        notes=data.notes
    )
    db.add(history)
    
    emp.is_active = False
    emp.exit_date = data.date
    
    user = await db.scalar(select(User).where(User.employee_id == emp.id))
    if user:
        user.is_active = False
        db.add(user)

    await db.commit()
    return await get_employee_detail(db, emp_id)

async def rehire_employee(db: AsyncSession, emp_id: int, data: schemas.RehirePayload) -> Employee:
    emp = await db.get(Employee, emp_id)
    if not emp: raise HTTPException(404, "Colaborador no encontrado")
    
    history = EmployeeHistory(
        employee_id=emp.id, 
        movement_type=MovementType.REHIRE, 
        date=data.date, 
        new_position_id=data.new_position_id, 
        company_id=data.new_company_id or emp.company_id,
        contract_type_id=data.new_contract_type_id,
        notes=data.notes
    )
    db.add(history)
    
    emp.is_active = True
    emp.exit_date = None
    emp.position_id = data.new_position_id
    if data.new_company_id: emp.company_id = data.new_company_id
        
    new_pos = EmployeePosition(
        employee_id=emp.id, 
        position_id=data.new_position_id, 
        company_id=data.new_company_id or emp.company_id,
        contract_type_id=data.new_contract_type_id,
        is_primary=True, 
        start_date=data.date
    )
    db.add(new_pos)
    
    user = await db.scalar(select(User).where(User.employee_id == emp.id))
    if user:
        user.is_active = True
        db.add(user)

    await db.commit()
    return await get_employee_detail(db, emp_id)

async def change_contract_type(db: AsyncSession, emp_id: int, data: schemas.ChangeContractPayload) -> Employee:
    """
    Cambia el tipo de contrato del cargo principal actual.
    Cierra el registro actual en EmployeePosition y crea uno nuevo idéntico pero con el nuevo contrato.
    """
    emp = await get_employee_detail(db, emp_id)
    if not emp: raise HTTPException(404, "Colaborador no encontrado")

    # Buscar cargo principal activo
    stmt = select(EmployeePosition).where(
        EmployeePosition.employee_id == emp.id,
        EmployeePosition.is_primary == True,
        EmployeePosition.end_date.is_(None)
    )
    current_pos = (await db.execute(stmt)).scalar_one_or_none()
    
    if not current_pos:
        raise HTTPException(400, "El colaborador no tiene un cargo principal activo.")

    if current_pos.contract_type_id == data.new_contract_type_id:
        raise HTTPException(400, "El colaborador ya tiene este tipo de contrato.")

    # 1. Cerrar posición actual
    current_pos.end_date = data.date
    current_pos.is_primary = False # Ya no es el vigente
    db.add(current_pos)
    
    # 2. Crear nueva posición (copia de la anterior con nuevo contrato)
    new_pos = EmployeePosition(
        employee_id=emp.id,
        position_id=current_pos.position_id,
        company_id=current_pos.company_id,
        contract_type_id=data.new_contract_type_id,
        is_primary=True,
        start_date=data.date
    )
    db.add(new_pos)

    # 3. Registrar en Historial
    history = EmployeeHistory(
        employee_id=emp.id,
        movement_type=MovementType.CONTRACT_CHANGE,
        date=data.date,
        new_position_id=current_pos.position_id,
        company_id=current_pos.company_id,
        contract_type_id=data.new_contract_type_id,
        notes=data.notes or "Cambio de tipo de contrato"
    )
    db.add(history)

    await db.commit()
    return await get_employee_detail(db, emp_id)

async def change_salary(db: AsyncSession, emp_id: int, data: schemas.SalaryChangePayload) -> Employee:
    """
    Registra un cambio de salario para un cargo específico del colaborador.
    """
    emp = await get_employee_detail(db, emp_id)
    if not emp: raise HTTPException(404, "Colaborador no encontrado")

    # Buscar el registro de posición específico
    stmt = select(EmployeePosition).where(
        EmployeePosition.id == data.employee_position_id,
        EmployeePosition.employee_id == emp.id
    )
    target_pos = (await db.execute(stmt)).scalar_one_or_none()
    
    if not target_pos:
        raise HTTPException(400, "El registro de cargo especificado no existe o no pertenece al colaborador.")

    # 1. Actualizar el salario en la posición objetivo
    target_pos.base_salary = data.new_base_salary
    target_pos.currency_id = data.new_currency_id
    db.add(target_pos)

    # 2. Registrar en Historial
    history = EmployeeHistory(
        employee_id=emp.id,
        movement_type=MovementType.SALARY_CHANGE,
        date=data.date,
        new_position_id=target_pos.position_id,
        company_id=target_pos.company_id,
        contract_type_id=target_pos.contract_type_id,
        base_salary=data.new_base_salary,
        currency_id=data.new_currency_id,
        notes=f"[{target_pos.position.name}] {data.notes or 'Cambio de salario'}"
    )
    db.add(history)

    await db.commit()
    return await get_employee_detail(db, emp_id)

async def upload_document(
    db: AsyncSession, 
    emp_id: int, 
    name: str, 
    category: str, 
    file: UploadFile, 
    notes: str = None,
    expiration_date: date = None
) -> EmployeeDocument:
    extension = file.filename.split(".")[-1]
    filename = f"{emp_id}_{uuid4()}.{extension}"
    file_path = os.path.join(DOCS_DIR, filename)
    
    with open(file_path, "wb") as buffer: 
        shutil.copyfileobj(file.file, buffer)
        
    doc = EmployeeDocument(
        employee_id=emp_id, 
        name=name, 
        category=category, 
        file_url=f"/static/uploads/documents/{filename}", 
        notes=notes,
        expiration_date=expiration_date
    )
    db.add(doc)
    await db.commit()
    return doc

async def delete_document(db: AsyncSession, doc_id: int):
    doc = await db.get(EmployeeDocument, doc_id)
    if doc:
        await db.delete(doc)
        await db.commit()

async def get_employee_attendance_detail(db: AsyncSession, enrollment_id: int) -> List[Dict[str, Any]]:
    enrollment = await db.get(TrainingEnrollment, enrollment_id)
    if not enrollment: return []
    stmt_sessions = select(TrainingSession).where(TrainingSession.training_id == enrollment.training_id).order_by(TrainingSession.date)
    sessions = (await db.execute(stmt_sessions)).scalars().all()
    stmt_att = select(TrainingAttendance).where(TrainingAttendance.enrollment_id == enrollment_id)
    attendances = (await db.execute(stmt_att)).scalars().all()
    att_map = {a.session_id: a for a in attendances}
    result = []
    for session in sessions:
        att = att_map.get(session.id)
        result.append({"session_date": session.date, "session_topic": session.topic, "is_present": att.is_present if att else False, "notes": att.notes if att else "", "status": "Registrado" if att else "Pendiente"})
    return result

async def get_employee_timeline(db: AsyncSession, emp_id: int) -> List[schemas.TimelineEvent]:
    emp = await get_employee_detail(db, emp_id)
    if not emp: return []
    events = []
    for h in emp.history:
        color = "gray"; icon = "info"; title = h.movement_type.value.upper()
        if h.movement_type == MovementType.ENTRY: color = "green"; icon = "user-plus"; title = "Ingreso"
        elif h.movement_type == MovementType.PROMOTION: color = "blue"; icon = "trending-up"; title = "Promoción"
        elif h.movement_type == MovementType.EXIT: color = "red"; icon = "log-out"; title = "Salida"
        elif h.movement_type == MovementType.REHIRE: color = "green"; icon = "refresh-cw"; title = "Reingreso"
        elif h.movement_type == MovementType.CONTRACT_CHANGE: color = "purple"; icon = "file-text"; title = "Cambio Contrato"
        elif h.movement_type == MovementType.SALARY_CHANGE: color = "emerald"; icon = "dollar-sign"; title = "Cambio Salario"
        
        desc = h.notes
        if h.new_position: desc = f"Cargo: {h.new_position.name}. {h.notes or ''}"
        elif h.previous_position_name: desc = f"Desde: {h.previous_position_name}. {h.notes or ''}"
        
        if h.contract_type:
            desc += f" [Contrato: {h.contract_type.name}]"
            
        if h.base_salary:
            curr_name = h.currency.name if h.currency else ""
            desc += f" [Nuevo Salario: {h.base_salary:,.0f} {curr_name}]"
        
        events.append(schemas.TimelineEvent(date=h.date, category="history", type_label=title, title=title, description=desc, color=color, icon=icon))
    
    for s in emp.sanctions:
        events.append(schemas.TimelineEvent(date=s.date, category="sanction", type_label="Sanción", title=s.type.value.upper(), description=f"{s.reason}", color="red", icon="alert-triangle"))
    for r in emp.recognitions:
        events.append(schemas.TimelineEvent(date=r.date, category="recognition", type_label="Reconocimiento", title=r.title, description=r.description, color="yellow", icon="star"))
    for b in emp.benefits:
        events.append(schemas.TimelineEvent(date=b.start_date, category="benefit", type_label="Beneficio", title=b.benefit_type.name, description=b.details, color="teal", icon="gift"))
    
    events.sort(key=lambda x: x.date, reverse=True)
    return events