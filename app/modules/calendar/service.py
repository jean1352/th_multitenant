"""
Lógica de negocio para el módulo de Calendario.
"""

import io
import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import BackgroundTasks, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.calendar import schemas
from app.modules.calendar.models import (
    CalendarEvent,
    CalendarEventType,
    EnrollmentStatus,
    EventEnrollment,
)
from app.modules.employees.models import Employee, EmployeePosition, EmployeeProbationStage
from app.modules.notifications.service import send_email_notification
from app.modules.organization.models import Area, Position, Sede
from app.modules.trainings.models import Training, TrainingSession


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

    # 4. Etapas de Periodo de Prueba (fechas de vencimiento por colaborador)
    stmt_prob = (
        select(EmployeeProbationStage, Employee, EmployeePosition, Position, Area)
        .join(EmployeePosition, EmployeeProbationStage.employee_position_id == EmployeePosition.id)
        .join(Employee, EmployeePosition.employee_id == Employee.id)
        .join(Position, EmployeePosition.position_id == Position.id)
        .join(Area, Position.area_id == Area.id)
        .where(
            EmployeeProbationStage.due_date.is_not(None),
            EmployeeProbationStage.due_date.between(start, end),
            EmployeePosition.end_date.is_(None),
            Employee.is_active == True,  # noqa
        )
    )
    prob_rows = (await db.execute(stmt_prob)).all()
    for stage, emp, emp_pos, pos, area in prob_rows:
        events.append(
            schemas.FullCalendarEvent(
                id=f"prob_{stage.id}",
                title=f"Etapa PP: {stage.name}",
                start=stage.due_date,
                backgroundColor="#6366F1",
                borderColor="#6366F1",
                extendedProps={
                    "type": "probation",
                    "employee": emp.full_name,
                    "position": pos.name,
                    "area": area.name,
                    "description": stage.description,
                    "completed": stage.is_completed,
                    "url": f"/employees/{emp.id}",
                },
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


# --- DASHBOARD DE EVENTOS ---

async def get_events_dashboard_data(
    db: AsyncSession,
    birth_month: Optional[int] = None,
    area_id: Optional[int] = None,
    sede_id: Optional[int] = None,
    year: Optional[int] = None,
    page: Optional[int] = None,
    per_page: int = 10
) -> Dict[str, Any]:
    """Consolida la información para el Dashboard de Eventos (cumpleaños, eventos,
    capacitaciones y feriados). Soporta filtros y paginación para cumpleaños."""
    today = date.today()
    if year is None:
        year = today.year

    # 1. Cumpleaños (colaboradores activos con fecha de nacimiento)
    stmt_birth = (
        select(Employee)
        .options(
            selectinload(Employee.position_obj).selectinload(Position.area).selectinload(Area.sede)
        )
        .join(Position, Employee.position_id == Position.id)
        .join(Area, Position.area_id == Area.id)
        .where(Employee.is_active == True, Employee.birthday.is_not(None))  # noqa
    )
    if birth_month:
        stmt_birth = stmt_birth.where(func.extract("month", Employee.birthday) == birth_month)
    if area_id:
        stmt_birth = stmt_birth.where(Area.id == area_id)
    if sede_id:
        stmt_birth = stmt_birth.where(Area.sede_id == sede_id)
    stmt_birth = stmt_birth.order_by(
        func.extract("month", Employee.birthday),
        func.extract("day", Employee.birthday),
        Employee.full_name,
    )
    employees = (await db.execute(stmt_birth)).scalars().all()

    birthdays = []
    for emp in employees:
        bday = emp.birthday
        age = None
        if bday:
            age = today.year - bday.year - ((today.month, today.day) < (bday.month, bday.day))
        birthdays.append({
            "id": emp.id,
            "full_name": emp.full_name,
            "document_id": emp.document_id,
            "position": emp.position_obj.name if emp.position_obj else "-",
            "area": emp.position_obj.area.name if emp.position_obj and emp.position_obj.area else "-",
            "sede": emp.position_obj.area.sede.name if emp.position_obj and emp.position_obj.area and emp.position_obj.area.sede else "-",
            "birthday": bday,
            "birthday_str": bday.strftime("%d/%m") if bday else "-",
            "age": age,
        })

    # 2. Eventos del calendario (excluyendo feriados)
    stmt_events = (
        select(CalendarEvent)
        .options(selectinload(CalendarEvent.event_type))
        .where(CalendarEvent.date >= date(year, 1, 1), CalendarEvent.date <= date(year, 12, 31))
        .order_by(CalendarEvent.date)
    )
    events = (await db.execute(stmt_events)).scalars().all()

    events_data = []
    holidays_data = []
    for e in events:
        is_holiday = e.event_type.affects_sla if e.event_type else False
        entry = {
            "id": e.id,
            "title": e.title,
            "description": e.description or "-",
            "date": e.date,
            "type": e.event_type.name if e.event_type else "General",
            "color": e.event_type.color if e.event_type else "#3B82F6",
            "is_enrollable": e.is_enrollable,
        }
        if is_holiday:
            holidays_data.append(entry)
        else:
            events_data.append(entry)

    # 3. Capacitaciones
    stmt_train = (
        select(Training)
        .where(Training.start_date >= date(year, 1, 1), Training.end_date <= date(year, 12, 31))
        .order_by(Training.start_date)
    )
    trainings = (await db.execute(stmt_train)).scalars().all()
    trainings_data = []
    type_map = {"internal": "Interna", "external": "Externa", "replica": "Réplica"}
    status_map = {
        "draft": "Borrador", "planned": "Programada", "in_progress": "En curso",
        "completed": "Finalizada", "closed": "Cerrada", "cancelled": "Cancelada",
    }
    for t in trainings:
        trainings_data.append({
            "id": t.id,
            "name": t.name,
            "description": t.description or "-",
            "type": type_map.get(t.type.value, t.type.value) if t.type else "-",
            "start_date": t.start_date,
            "end_date": t.end_date,
            "status": status_map.get(t.status.value, t.status.value) if t.status else "-",
        })

    # 4. Etapas de Periodo de Prueba (fechas de vencimiento en el año)
    stmt_prob = (
        select(EmployeeProbationStage, Employee, EmployeePosition, Position, Area)
        .join(EmployeePosition, EmployeeProbationStage.employee_position_id == EmployeePosition.id)
        .join(Employee, EmployeePosition.employee_id == Employee.id)
        .join(Position, EmployeePosition.position_id == Position.id)
        .join(Area, Position.area_id == Area.id)
        .where(
            EmployeeProbationStage.due_date.is_not(None),
            EmployeeProbationStage.due_date >= date(year, 1, 1),
            EmployeeProbationStage.due_date <= date(year, 12, 31),
            EmployeePosition.end_date.is_(None),
            Employee.is_active == True,  # noqa
        )
    )
    if area_id:
        stmt_prob = stmt_prob.where(Area.id == area_id)
    if sede_id:
        stmt_prob = stmt_prob.where(Area.sede_id == sede_id)
    stmt_prob = stmt_prob.order_by(EmployeeProbationStage.due_date)
    prob_rows = (await db.execute(stmt_prob)).all()
    probation_stages = []
    for stage, emp, emp_pos, pos, area in prob_rows:
        probation_stages.append({
            "id": stage.id,
            "name": stage.name,
            "description": stage.description or "-",
            "due_date": stage.due_date,
            "employee": emp.full_name,
            "employee_id": emp.id,
            "position": pos.name,
            "area": area.name,
            "is_completed": stage.is_completed,
        })

    birthdays_this_month = [b for b in birthdays if b["birthday"] and b["birthday"].month == today.month]

    # --- HOY (independiente del filtro de mes/año, respeta sede/área) ---
    stmt_today_birth = (
        select(Employee)
        .options(
            selectinload(Employee.position_obj).selectinload(Position.area).selectinload(Area.sede)
        )
        .join(Position, Employee.position_id == Position.id)
        .join(Area, Position.area_id == Area.id)
        .where(
            Employee.is_active == True,  # noqa
            Employee.birthday.is_not(None),
            func.extract("month", Employee.birthday) == today.month,
            func.extract("day", Employee.birthday) == today.day,
        )
    )
    if area_id:
        stmt_today_birth = stmt_today_birth.where(Area.id == area_id)
    if sede_id:
        stmt_today_birth = stmt_today_birth.where(Area.sede_id == sede_id)
    stmt_today_birth = stmt_today_birth.order_by(Employee.full_name)
    today_emps = (await db.execute(stmt_today_birth)).scalars().all()

    today_birthdays = []
    for emp in today_emps:
        bday = emp.birthday
        age = today.year - bday.year - ((today.month, today.day) < (bday.month, bday.day))
        today_birthdays.append({
            "id": emp.id,
            "full_name": emp.full_name,
            "area": emp.position_obj.area.name if emp.position_obj and emp.position_obj.area else "-",
            "sede": emp.position_obj.area.sede.name if emp.position_obj and emp.position_obj.area and emp.position_obj.area.sede else "-",
            "age": age,
        })

    # Eventos / Feriados de hoy
    stmt_today_events = (
        select(CalendarEvent)
        .options(selectinload(CalendarEvent.event_type))
        .where(CalendarEvent.date == today)
        .order_by(CalendarEvent.title)
    )
    today_events_orm = (await db.execute(stmt_today_events)).scalars().all()
    today_events = []
    today_holidays = []
    for e in today_events_orm:
        is_holiday = e.event_type.affects_sla if e.event_type else False
        entry = {
            "id": e.id,
            "title": e.title,
            "type": e.event_type.name if e.event_type else "General",
            "color": e.event_type.color if e.event_type else "#3B82F6",
            "description": e.description or "-",
        }
        if is_holiday:
            today_holidays.append(entry)
        else:
            today_events.append(entry)

    # Capacitaciones activas hoy
    stmt_today_trainings = (
        select(Training)
        .where(Training.start_date <= today, Training.end_date >= today)
        .order_by(Training.name)
    )
    today_trainings_orm = (await db.execute(stmt_today_trainings)).scalars().all()
    today_trainings = [
        {"id": t.id, "name": t.name, "start_date": t.start_date, "end_date": t.end_date}
        for t in today_trainings_orm
    ]

    # Etapas de Periodo de Prueba que vencen hoy
    stmt_today_prob = (
        select(EmployeeProbationStage, Employee, EmployeePosition, Position, Area)
        .join(EmployeePosition, EmployeeProbationStage.employee_position_id == EmployeePosition.id)
        .join(Employee, EmployeePosition.employee_id == Employee.id)
        .join(Position, EmployeePosition.position_id == Position.id)
        .join(Area, Position.area_id == Area.id)
        .where(
            EmployeeProbationStage.due_date == today,
            EmployeePosition.end_date.is_(None),
            Employee.is_active == True,  # noqa
        )
    )
    if area_id:
        stmt_today_prob = stmt_today_prob.where(Area.id == area_id)
    if sede_id:
        stmt_today_prob = stmt_today_prob.where(Area.sede_id == sede_id)
    stmt_today_prob = stmt_today_prob.order_by(Employee.full_name)
    today_prob_rows = (await db.execute(stmt_today_prob)).all()
    today_probation_stages = []
    for stage, emp, emp_pos, pos, area in today_prob_rows:
        today_probation_stages.append({
            "id": stage.id,
            "name": stage.name,
            "employee": emp.full_name,
            "position": pos.name,
            "area": area.name,
            "is_completed": stage.is_completed,
        })

    # Paginación de cumpleaños (page=None significa "sin paginar", usado por la exportación)
    total_birthdays = len(birthdays)
    per_page = max(1, per_page)
    total_pages = (total_birthdays + per_page - 1) // per_page if total_birthdays > 0 else 1

    if page is None:
        current_page = 1
        paged_birthdays = birthdays
    else:
        current_page = max(1, page)
        start_idx = (current_page - 1) * per_page
        end_idx = start_idx + per_page
        paged_birthdays = birthdays[start_idx:end_idx]

    return {
        "year": year,
        "birth_month": birth_month,
        "area_id": area_id,
        "sede_id": sede_id,
        "birthdays": paged_birthdays,
        "birthday_pagination": {
            "page": current_page,
            "per_page": per_page,
            "total": total_birthdays,
            "total_pages": total_pages,
            "has_prev": current_page > 1,
            "has_next": current_page < total_pages,
        },
        "events": events_data,
        "trainings": trainings_data,
        "holidays": holidays_data,
        "probation_stages": probation_stages,
        "today": {
            "date": today,
            "birthdays": today_birthdays,
            "events": today_events,
            "trainings": today_trainings,
            "holidays": today_holidays,
            "probation_stages": today_probation_stages,
        },
        "kpi": {
            "birthdays_total": total_birthdays,
            "birthdays_month": len(birthdays_this_month),
            "events_total": len(events_data),
            "trainings_total": len(trainings_data),
            "holidays_total": len(holidays_data),
            "probation_stages_total": len(probation_stages),
        },
    }


async def generate_events_dashboard_excel(
    db: AsyncSession,
    birth_month: Optional[int] = None,
    area_id: Optional[int] = None,
    sede_id: Optional[int] = None,
    year: Optional[int] = None
) -> io.BytesIO:
    """Genera un archivo Excel con el Dashboard de Eventos (varias hojas)."""
    data = await get_events_dashboard_data(db, birth_month, area_id, sede_id, year)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        # Cumpleaños
        pd.DataFrame([{
            "Nombre": b["full_name"],
            "Documento": b["document_id"],
            "Cargo": b["position"],
            "Área": b["area"],
            "Sede": b["sede"],
            "Fecha Nacimiento": b["birthday"].strftime("%d/%m/%Y") if b["birthday"] else "-",
            "Día/Mes": b["birthday_str"],
            "Edad": b["age"] if b["age"] is not None else "-",
        } for b in data["birthdays"]], columns=[
            "Nombre", "Documento", "Cargo", "Área", "Sede", "Fecha Nacimiento", "Día/Mes", "Edad"
        ]).to_excel(writer, index=False, sheet_name="Cumpleaños")

        # Eventos
        pd.DataFrame([{
            "Título": e["title"],
            "Descripción": e["description"],
            "Fecha": e["date"].strftime("%d/%m/%Y"),
            "Tipo": e["type"],
            "Inscribible": "Sí" if e["is_enrollable"] else "No",
        } for e in data["events"]], columns=[
            "Título", "Descripción", "Fecha", "Tipo", "Inscribible"
        ]).to_excel(writer, index=False, sheet_name="Eventos")

        # Capacitaciones
        pd.DataFrame([{
            "Nombre": t["name"],
            "Descripción": t["description"],
            "Tipo": t["type"],
            "Inicio": t["start_date"].strftime("%d/%m/%Y"),
            "Fin": t["end_date"].strftime("%d/%m/%Y"),
            "Estado": t["status"],
        } for t in data["trainings"]], columns=[
            "Nombre", "Descripción", "Tipo", "Inicio", "Fin", "Estado"
        ]).to_excel(writer, index=False, sheet_name="Capacitaciones")

        # Feriados
        pd.DataFrame([{
            "Título": h["title"],
            "Descripción": h["description"],
            "Fecha": h["date"].strftime("%d/%m/%Y"),
            "Tipo": h["type"],
        } for h in data["holidays"]], columns=[
            "Título", "Descripción", "Fecha", "Tipo"
        ]).to_excel(writer, index=False, sheet_name="Feriados")

        # Etapas de Periodo de Prueba
        pd.DataFrame([{
            "Etapa": p["name"],
            "Colaborador": p["employee"],
            "Cargo": p["position"],
            "Área": p["area"],
            "Vencimiento": p["due_date"].strftime("%d/%m/%Y") if p["due_date"] else "-",
            "Completada": "Sí" if p["is_completed"] else "No",
            "Descripción": p["description"],
        } for p in data["probation_stages"]], columns=[
            "Etapa", "Colaborador", "Cargo", "Área", "Vencimiento", "Completada", "Descripción"
        ]).to_excel(writer, index=False, sheet_name="Etapas PP")

    output.seek(0)
    return output