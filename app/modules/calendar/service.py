"""
Lógica de negocio para el módulo de Calendario.
"""

import io
import uuid
from datetime import date, datetime
from typing import List, Optional

import pandas as pd
from fastapi import BackgroundTasks, Request
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.calendar import schemas
from app.modules.calendar.models import (
    CalendarEvent,
    CalendarEventType,
    EnrollmentStatus,
    EventEnrollment,
)
from app.modules.employees.models import Employee
from app.modules.notifications.service import send_email_notification
from app.modules.organization.models import Area, Position
from app.modules.trainings.models import TrainingSession


# --- EVENT TYPES CRUD ---

async def get_event_types(db: AsyncSession) -> List[CalendarEventType]:
    result = await db.execute(select(CalendarEventType).order_by(CalendarEventType.name))
    return result.scalars().all()

async def create_event_type(db: AsyncSession, data: schemas.EventTypeCreate) -> CalendarEventType:
    obj = CalendarEventType(**data.model_dump())
    db.add(obj)
    await db.commit()
    return obj

async def delete_event_type(db: AsyncSession, id: int) -> bool:
    obj = await db.get(CalendarEventType, id)
    if not obj: return False
    # Validar uso
    usage = await db.scalar(select(CalendarEvent).where(CalendarEvent.event_type_id == id))
    if usage:
        raise ValueError("No se puede eliminar: Hay eventos usando este tipo.")
    await db.delete(obj)
    await db.commit()
    return True


# --- EVENTS ---

async def get_all_events(
    db: AsyncSession, start: date, end: date
) -> List[schemas.FullCalendarEvent]:
    events = []

    # 1. Eventos del Calendario (Con Tipo Dinámico cargado)
    stmt_cal = select(CalendarEvent).options(selectinload(CalendarEvent.event_type)).where(
        CalendarEvent.date.between(start, end)
    )
    cal_events = (await db.execute(stmt_cal)).scalars().all()

    for e in cal_events:
        # Fallback de seguridad si se borró el tipo (aunque la FK debería impedirlo)
        color = e.event_type.color if e.event_type else "#3B82F6"
        category_name = e.event_type.name if e.event_type else "General"
        
        events.append(
            schemas.FullCalendarEvent(
                id=f"evt_{e.id}",
                title=e.title,
                start=e.date,
                backgroundColor=color,
                borderColor=color,
                extendedProps={
                    "type": "event",
                    "description": e.description,
                    "category": category_name,
                    "is_enrollable": e.is_enrollable,
                    "url": f"/calendar/events/{e.id}" if e.is_enrollable else None,
                },
            )
        )

    # 2. Sesiones de Capacitación
    stmt_train = select(TrainingSession).where(
        TrainingSession.date.between(start, end)
    )
    train_sessions = (await db.execute(stmt_train)).scalars().all()

    for s in train_sessions:
        events.append(
            schemas.FullCalendarEvent(
                id=f"train_{s.id}",
                title=f"Capacitación: {s.topic}",
                start=s.date,
                backgroundColor="#10B981",
                borderColor="#10B981",
                extendedProps={
                    "type": "training",
                    "time": f"{s.start_time} - {s.end_time}",
                    "url": f"/trainings/{s.training_id}",
                },
            )
        )

    # 3. Cumpleaños
    stmt_emp = select(Employee).where(Employee.is_active == True) # noqa
    employees = (await db.execute(stmt_emp)).scalars().all()
    birthdays_by_date = {}

    for emp in employees:
        if not emp.birthday:
            continue
        for year in range(start.year, end.year + 1):
            try:
                bday_this_year = emp.birthday.replace(year=year)
            except ValueError:
                bday_this_year = date(year, 3, 1)

            if start <= bday_this_year <= end:
                k = bday_this_year.isoformat()
                if k not in birthdays_by_date:
                    birthdays_by_date[k] = []
                birthdays_by_date[k].append(emp)

    for date_str, emps in birthdays_by_date.items():
        title = f"🎂 {len(emps)} Cumpleaños"
        desc = "<br>".join(
            [f"- <a href='/employees/{e.id}'>{e.full_name}</a>" for e in emps]
        )
        events.append(
            schemas.FullCalendarEvent(
                id=f"bday_{date_str}",
                title=title,
                start=date.fromisoformat(date_str),
                backgroundColor="#F59E0B",
                borderColor="#F59E0B",
                extendedProps={"type": "birthday", "html_content": desc},
            )
        )

    return events


async def create_event(
    db: AsyncSession, evt: schemas.CalendarEventCreate
) -> CalendarEvent:
    """Crea un evento y recarga la relación event_type para evitar MissingGreenlet."""
    new_evt = CalendarEvent(**evt.model_dump())
    db.add(new_evt)
    await db.commit()
    
    # CORRECCIÓN: Recargar el objeto con la relación cargada explícitamente
    stmt = (
        select(CalendarEvent)
        .options(selectinload(CalendarEvent.event_type))
        .where(CalendarEvent.id == new_evt.id)
    )
    result = await db.execute(stmt)
    return result.scalar_one()


async def delete_event(db: AsyncSession, id: int) -> bool:
    evt = await db.get(CalendarEvent, id)
    if not evt:
        return False
    await db.delete(evt)
    await db.commit()
    return True


async def get_event_detail(
    db: AsyncSession, id: int
) -> Optional[CalendarEvent]:
    stmt = (
        select(CalendarEvent)
        .options(
            selectinload(CalendarEvent.event_type),
            selectinload(CalendarEvent.enrollments)
            .selectinload(EventEnrollment.employee)
            .options(
                selectinload(Employee.position_obj).selectinload(Position.area),
                selectinload(Employee.dietary_restrictions)
            )
        )
        .where(CalendarEvent.id == id)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


# --- ENROLLMENT & INVITATIONS ---

async def enroll_employee_to_event(
    db: AsyncSession,
    event_id: int,
    employee_id: int,
    background_tasks: BackgroundTasks,
    db_session_factory,
) -> EventEnrollment:
    exists = await db.scalar(
        select(EventEnrollment).where(
            EventEnrollment.event_id == event_id,
            EventEnrollment.employee_id == employee_id,
        )
    )
    if exists:
        raise ValueError("Colaborador ya inscrito en este evento")

    enrollment = EventEnrollment(
        event_id=event_id,
        employee_id=employee_id,
        status=EnrollmentStatus.CONFIRMED,
    )
    db.add(enrollment)
    await db.commit()
    
    # Recargar para devolver datos completos si es necesario
    return enrollment


async def remove_event_enrollment(
    db: AsyncSession, enrollment_id: int
) -> bool:
    enroll = await db.get(EventEnrollment, enrollment_id)
    if not enroll:
        return False
    await db.delete(enroll)
    await db.commit()
    return True


async def generate_event_enrollment_report(
    db: AsyncSession, event_id: int
) -> Optional[io.BytesIO]:
    event = await get_event_detail(db, event_id)
    if not event:
        return None

    data = []
    for enroll in event.enrollments:
        emp = enroll.employee
        dietary = (
            ", ".join([d.name for d in emp.dietary_restrictions])
            if emp.dietary_restrictions
            else "Ninguna"
        )
        status_map = {"confirmed": "Confirmado", "invited": "Pendiente", "declined": "Rechazado"}

        data.append({
            "Estado": status_map.get(enroll.status.value, enroll.status),
            "Nombre Completo": emp.full_name,
            "Documento": emp.document_id,
            "Cargo": emp.position_obj.name if emp.position_obj else "-",
            "Área": emp.position_obj.area.name if emp.position_obj and emp.position_obj.area else "-",
            "Email": emp.institutional_email or "-",
            "Restricciones": dietary,
        })

    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Asistentes")
    output.seek(0)
    return output


# --- MASS INVITATION LOGIC ---

async def _send_invitation_email_bg(
    db_session_factory,
    recipient_email: str,
    subject: str,
    body: str,
    enrollment_id: int,
):
    async with db_session_factory() as db:
        success = await send_email_notification(
            db, recipient_email, subject, body, is_html=True
        )
        if success:
            enroll = await db.get(EventEnrollment, enrollment_id)
            if enroll:
                enroll.invitation_sent_at = datetime.now()
                await db.commit()


async def send_mass_invitations(
    db: AsyncSession,
    event_id: int,
    payload: schemas.InvitationPayload,
    request: Request,
    background_tasks: BackgroundTasks,
    db_session_factory,
) -> int:
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
            select(EventEnrollment).where(
                EventEnrollment.event_id == event_id,
                EventEnrollment.employee_id == emp.id,
            )
        )

        enrollment = existing
        token = str(uuid.uuid4())

        if not existing:
            enrollment = EventEnrollment(
                event_id=event_id,
                employee_id=emp.id,
                status=EnrollmentStatus.INVITED,
                invitation_token=token,
            )
            db.add(enrollment)
        elif existing.status == EnrollmentStatus.INVITED:
            existing.invitation_token = token
            enrollment = existing
        else:
            continue

        await db.flush()

        link = f"{base_url}/calendar/public/respond/{token}"
        personal_body = (
            payload.html_body.replace("{{name}}", emp.full_name)
            .replace("{{link}}", link)
        )

        # USAR all_emails PARA INVITACIONES
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
) -> Optional[CalendarEvent]:
    stmt = (
        select(EventEnrollment)
        .options(selectinload(EventEnrollment.event))
        .where(EventEnrollment.invitation_token == token)
    )
    enrollment = (await db.execute(stmt)).scalar_one_or_none()

    if not enrollment:
        return None

    if action == "confirm":
        enrollment.status = EnrollmentStatus.CONFIRMED
    elif action == "decline":
        enrollment.status = EnrollmentStatus.DECLINED

    enrollment.response_at = datetime.now()
    await db.commit()
    return enrollment.event


async def get_event_by_token(
    db: AsyncSession, token: str
) -> Optional[CalendarEvent]:
    stmt = (
        select(EventEnrollment)
        .options(selectinload(EventEnrollment.event))
        .where(EventEnrollment.invitation_token == token)
    )
    enrollment = (await db.execute(stmt)).scalar_one_or_none()
    return enrollment.event if enrollment else None