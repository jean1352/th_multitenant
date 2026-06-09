"""
Lógica de negocio para el módulo de Capacitaciones.
Maneja operaciones CRUD, inscripciones, generación de sesiones y notificaciones.
"""

import uuid
from datetime import date, timedelta, datetime
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, Request, HTTPException
from sqlalchemy import delete, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.modules.employees.models import Employee
from app.modules.notifications.service import send_email_notification
from app.modules.organization.models import Area, Position
from app.modules.trainings import schemas
from app.modules.trainings.models import (
    EnrollmentStatus,
    SessionStatus,
    Training,
    TrainingAttendance,
    TrainingEnrollment,
    TrainingSession,
    TrainingType,
    TrainingProvider
)


# --- PROVIDER CRUD ---

async def get_providers(db: AsyncSession, active_only: bool = False) -> List[TrainingProvider]:
    stmt = select(TrainingProvider).order_by(TrainingProvider.business_name)
    if active_only:
        stmt = stmt.where(TrainingProvider.is_active == True)
    return (await db.execute(stmt)).scalars().all()

async def create_provider(db: AsyncSession, data: schemas.ProviderCreate) -> TrainingProvider:
    # Validar RUC único
    exists = await db.scalar(select(TrainingProvider).where(TrainingProvider.ruc == data.ruc))
    if exists:
        raise ValueError("Ya existe un proveedor con este RUC.")
    
    provider = TrainingProvider(**data.model_dump())
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return provider

async def update_provider(db: AsyncSession, id: int, data: schemas.ProviderUpdate) -> Optional[TrainingProvider]:
    provider = await db.get(TrainingProvider, id)
    if not provider: return None
    
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(provider, k, v)
    
    await db.commit()
    await db.refresh(provider)
    return provider

async def delete_provider(db: AsyncSession, id: int) -> bool:
    provider = await db.get(TrainingProvider, id)
    if not provider: return False
    
    # Verificar uso
    usage = await db.scalar(select(func.count(Training.id)).where(Training.provider_id == id))
    if usage > 0:
        raise ValueError(f"No se puede eliminar: Este proveedor tiene {usage} capacitaciones asociadas.")
        
    await db.delete(provider)
    await db.commit()
    return True


# --- TRAINING CRUD ---

async def get_trainings_paginated(
    db: AsyncSession,
    page: int = 1,
    limit: int = 9,
    search: Optional[str] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    """Obtiene lista paginada de capacitaciones con filtros."""
    offset = (page - 1) * limit
    query = select(Training).options(
        selectinload(Training.internal_instructor).options(
            selectinload(Employee.position_obj),
            selectinload(Employee.company)
        ),
        selectinload(Training.provider_obj)
    )

    if status and status != "all":
        query = query.where(Training.status == status)

    if search:
        term = f"%{search}%"
        query = query.join(TrainingProvider, isouter=True).where(
            or_(
                Training.name.ilike(term),
                TrainingProvider.business_name.ilike(term)
            )
        )

    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0

    query = (
        query.order_by(desc(Training.start_date))
        .offset(offset)
        .limit(limit)
    )
    items = (await db.execute(query)).scalars().all()

    total_pages = (total + limit - 1) // limit

    return {
        "data": items,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    }


async def get_training_detail(
    db: AsyncSession, id: int
) -> Optional[Training]:
    """Obtiene el detalle de una capacitación incluyendo sus sesiones."""
    stmt = (
        select(Training)
        .options(
            selectinload(Training.sessions),
            selectinload(Training.internal_instructor).options(
                selectinload(Employee.position_obj),
                selectinload(Employee.company)
            ),
            selectinload(Training.provider_obj)
        )
        .where(Training.id == id)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def create_training(
    db: AsyncSession, t: schemas.TrainingCreate
) -> Training:
    """Crea una nueva capacitación."""
    data = t.model_dump()
    
    # Limpieza lógica según tipo
    if data['type'] == TrainingType.INTERNAL:
        data['provider_id'] = None
        data['cost_per_person'] = 0
        data['company_cost'] = 0
    else:
        data['internal_instructor_id'] = None

    new_t = Training(**data)
    db.add(new_t)
    await db.commit()
    
    # Recargar relaciones para la respuesta
    stmt = select(Training).options(
        selectinload(Training.internal_instructor).options(
            selectinload(Employee.position_obj),
            selectinload(Employee.company)
        ),
        selectinload(Training.provider_obj)
    ).where(Training.id == new_t.id)
    
    return (await db.execute(stmt)).scalar_one()


async def update_training(
    db: AsyncSession, id: int, t: schemas.TrainingUpdate
) -> Optional[Training]:
    """Actualiza los datos de una capacitación existente."""
    training = await db.get(Training, id)
    if not training:
        return None

    data = t.model_dump(exclude_unset=True)
    
    # Limpieza lógica si cambia el tipo
    if 'type' in data:
        if data['type'] == TrainingType.INTERNAL:
            data['provider_id'] = None
            data['cost_per_person'] = 0
            data['company_cost'] = 0
        else:
            data['internal_instructor_id'] = None

    for key, value in data.items():
        setattr(training, key, value)

    await db.commit()
    
    # Recargar relaciones
    stmt = select(Training).options(
        selectinload(Training.internal_instructor).options(
            selectinload(Employee.position_obj),
            selectinload(Employee.company)
        ),
        selectinload(Training.provider_obj)
    ).where(Training.id == id)
    
    return (await db.execute(stmt)).scalar_one()


async def delete_training(db: AsyncSession, id: int) -> bool:
    """Elimina una capacitación."""
    training = await db.get(Training, id)
    if not training:
        return False
    await db.delete(training)
    await db.commit()
    return True


# --- ENROLLMENT & INVITATIONS ---

async def get_enrollments_paginated(
    db: AsyncSession,
    training_id: int,
    page: int = 1,
    limit: int = 10,
    search: Optional[str] = None,
    area_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Obtiene lista paginada de inscritos con filtros de área y búsqueda."""
    offset = (page - 1) * limit
    query = (
        select(TrainingEnrollment)
        .join(Employee)
        .join(Position, Employee.position_id == Position.id)
        .join(Area, Position.area_id == Area.id)
        .options(
            selectinload(TrainingEnrollment.employee)
            .selectinload(Employee.position_obj)
            .selectinload(Position.area)
        )
        .where(TrainingEnrollment.training_id == training_id)
    )

    if area_id:
        query = query.where(Area.id == area_id)

    if search:
        term = f"%{search}%"
        query = query.where(
            or_(
                Employee.full_name.ilike(term),
                Employee.document_id.ilike(term)
            )
        )

    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0

    query = query.order_by(Employee.full_name).offset(offset).limit(limit)
    items = (await db.execute(query)).scalars().all()

    total_pages = (total + limit - 1) // limit

    return {
        "data": items,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    }


async def enroll_employee(
    db: AsyncSession, training_id: int, employee_id: int
) -> TrainingEnrollment:
    """Inscribe a un empleado en una capacitación y notifica por correo."""
    exists = await db.scalar(
        select(TrainingEnrollment).where(
            TrainingEnrollment.training_id == training_id,
            TrainingEnrollment.employee_id == employee_id,
        )
    )
    if exists:
        raise ValueError("Empleado ya inscrito")

    enrollment = TrainingEnrollment(
        training_id=training_id, employee_id=employee_id
    )
    db.add(enrollment)
    await db.commit()

    emp = await db.get(Employee, employee_id)
    training = await db.get(Training, training_id)

    if emp.all_emails:
        await send_email_notification(
            db,
            emp.all_emails,
            f"Inscripción: {training.name}",
            f"Has sido inscrito en el curso {training.name}.",
        )

    return enrollment


async def _send_invitation_email_bg(
    db_session_factory,
    recipient_email: str,
    subject: str,
    body: str,
    enrollment_id: int,
):
    """Worker para enviar invitaciones en background."""
    async with db_session_factory() as db:
        success = await send_email_notification(
            db, recipient_email, subject, body, is_html=True
        )
        if success:
            enroll = await db.get(TrainingEnrollment, enrollment_id)
            if enroll:
                enroll.invitation_sent_at = date.today()
                await db.commit()


async def send_mass_invitations(
    db: AsyncSession,
    training_id: int,
    payload: schemas.InvitationPayload,
    request: Request,
    background_tasks: BackgroundTasks,
    db_session_factory,
) -> int:
    """
    Envía invitaciones masivas para una capacitación.
    Crea inscripciones con estado INVITED si no existen.
    """
    query = (
        select(Employee)
        .join(Position)
        .join(Area)
        .where(Employee.is_active == True, Employee.institutional_email.is_not(None)) # noqa
    )

    if payload.sede_ids:
        query = query.where(Area.sede_id.in_(payload.sede_ids))
    if payload.area_ids:
        query = query.where(Area.id.in_(payload.area_ids))

    employees = (await db.execute(query)).scalars().all()
    count = 0
    base_url = str(request.base_url).rstrip("/")

    for emp in employees:
        existing = await db.scalar(
            select(TrainingEnrollment).where(
                TrainingEnrollment.training_id == training_id,
                TrainingEnrollment.employee_id == emp.id,
            )
        )

        enrollment = existing
        token = str(uuid.uuid4())

        if not existing:
            enrollment = TrainingEnrollment(
                training_id=training_id,
                employee_id=emp.id,
                status=EnrollmentStatus.INVITED,
                invitation_token=token,
            )
            db.add(enrollment)
        elif existing.status == EnrollmentStatus.INVITED:
            existing.invitation_token = token
            enrollment = existing
        else:
            continue # Ya está inscrito o rechazó

        await db.flush()

        link = f"{base_url}/trainings/public/respond/{token}"
        personal_body = (
            payload.html_body.replace("{{name}}", emp.full_name)
            .replace("{{link}}", link)
        )

        if emp.all_emails:
            background_tasks.add_task(
                _send_invitation_email_bg,
                db_session_factory,
                emp.all_emails,
                payload.subject,
                personal_body,
                enrollment.id,
            )
            count += 1

    await db.commit()
    return count


async def process_public_response(
    db: AsyncSession, token: str, action: str
) -> Optional[Training]:
    """Procesa la respuesta del empleado a la invitación."""
    stmt = (
        select(TrainingEnrollment)
        .options(selectinload(TrainingEnrollment.training))
        .where(TrainingEnrollment.invitation_token == token)
    )
    enrollment = (await db.execute(stmt)).scalar_one_or_none()

    if not enrollment:
        return None

    if action == "confirm":
        enrollment.status = EnrollmentStatus.ENROLLED
    elif action == "decline":
        enrollment.status = EnrollmentStatus.DECLINED

    await db.commit()
    return enrollment.training


async def get_training_by_token(
    db: AsyncSession, token: str
) -> Optional[Training]:
    stmt = (
        select(TrainingEnrollment)
        .options(selectinload(TrainingEnrollment.training))
        .where(TrainingEnrollment.invitation_token == token)
    )
    enrollment = (await db.execute(stmt)).scalar_one_or_none()
    return enrollment.training if enrollment else None


async def send_reminder_to_enrolled(
    background_tasks: BackgroundTasks,
    db_session_factory,
    training_id: int,
) -> int:
    """Encola la tarea de envío de recordatorios masivos."""
    background_tasks.add_task(
        _process_reminders_bg, db_session_factory, training_id
    )
    return 1


async def _process_reminders_bg(db_session_factory, training_id: int):
    """Tarea en segundo plano para enviar correos de recordatorio."""
    async with db_session_factory() as db:
        stmt = (
            select(Employee)
            .join(TrainingEnrollment)
            .where(
                TrainingEnrollment.training_id == training_id,
                TrainingEnrollment.status == EnrollmentStatus.ENROLLED, # Solo a confirmados
                Employee.institutional_email.is_not(None),
            )
        )
        employees = (await db.execute(stmt)).scalars().all()
        training = await db.get(Training, training_id)

        if not training:
            return

        for emp in employees:
            if emp.all_emails:
                await send_email_notification(
                    db,
                    emp.all_emails,
                    f"🔔 Recordatorio: {training.name}",
                    f"Hola {emp.full_name},\n\n"
                    f"Te recordamos tu participación en la capacitación "
                    f"'{training.name}' que inicia el {training.start_date}.\n\n"
                    f"¡Te esperamos!",
                )


# --- SESSIONS & ATTENDANCE ---

async def generate_sessions(
    db: AsyncSession, training_id: int, gen: schemas.SessionGenerator
):
    """Genera sesiones automáticamente según rango de fechas y días."""
    sessions = []
    current_date = gen.start_date
    while current_date <= gen.end_date:
        if current_date.weekday() in gen.days_of_week:
            session = TrainingSession(
                training_id=training_id,
                topic=gen.topic,
                description=gen.description,
                instructor=gen.instructor,
                date=current_date,
                start_time=gen.start_time,
                end_time=gen.end_time,
                status=SessionStatus.PENDING,
            )
            sessions.append(session)
        current_date += timedelta(days=1)

    if sessions:
        db.add_all(sessions)
        await db.commit()
    return len(sessions)


async def update_session(
    db: AsyncSession, session_id: int, data: schemas.SessionUpdate
) -> Optional[TrainingSession]:
    """Actualiza los datos de una sesión."""
    session = await db.get(TrainingSession, session_id)
    if not session:
        return None

    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(session, key, value)

    await db.commit()
    await db.refresh(session)
    return session


async def delete_session(db: AsyncSession, session_id: int) -> bool:
    """Elimina una sesión."""
    session = await db.get(TrainingSession, session_id)
    if not session:
        return False
    await db.delete(session)
    await db.commit()
    return True


async def get_session_attendance(db: AsyncSession, session_id: int):
    """Obtiene la lista de asistencia para una sesión."""
    session = await db.get(TrainingSession, session_id)
    if not session:
        return None

    enrollments = (
        await db.execute(
            select(TrainingEnrollment)
            .options(selectinload(TrainingEnrollment.employee))
            .where(
                TrainingEnrollment.training_id == session.training_id,
                TrainingEnrollment.status == EnrollmentStatus.ENROLLED # Solo mostrar confirmados
            )
        )
    ).scalars().all()

    attendances = (
        await db.execute(
            select(TrainingAttendance).where(
                TrainingAttendance.session_id == session_id
            )
        )
    ).scalars().all()

    att_map = {a.enrollment_id: a for a in attendances}
    result = []

    for enroll in enrollments:
        att = att_map.get(enroll.id)
        result.append(
            {
                "enrollment_id": enroll.id,
                "employee_name": enroll.employee.full_name,
                "is_present": att.is_present if att else False,
                "notes": att.notes if att else "",
            }
        )
    return result


async def save_attendance(
    db: AsyncSession, session_id: int, data: schemas.AttendanceList
):
    """Guarda o actualiza la asistencia de una sesión."""
    session = await db.get(TrainingSession, session_id)
    if not session:
        return False

    # Limpiar asistencia previa para evitar duplicados/conflictos
    await db.execute(
        delete(TrainingAttendance).where(
            TrainingAttendance.session_id == session_id
        )
    )

    new_records = [
        TrainingAttendance(
            session_id=session_id,
            enrollment_id=item.enrollment_id,
            is_present=item.is_present,
            notes=item.notes,
        )
        for item in data.attendances
    ]

    db.add_all(new_records)
    session.status = SessionStatus.CLOSED
    await db.commit()
    return True


async def toggle_session_status(
    db: AsyncSession, session_id: int, status: SessionStatus
):
    """Cambia el estado de una sesión manualmente."""
    session = await db.get(TrainingSession, session_id)
    if not session:
        return False
    session.status = status
    await db.commit()
    return True