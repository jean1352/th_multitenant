"""
Utilidades transversales para el módulo de Capacitaciones:
- Cálculos en meses calendario (RNF-06, RN-05)
- Generador de archivos .ics (RF-11, CA-02)
- Resolución de jefes de área, alcance por área (CA-13) y correos de TH
- Registro en bitácora de auditoría (RF-33, RN-13)
"""

from __future__ import annotations

import calendar
import os
from datetime import date, datetime, time
from typing import Any, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.modules.auth.models import User, UserRole
from app.modules.employees.models import Employee
from app.modules.organization.models import Area, Position
from app.modules.trainings.models import Training, TrainingAudit, TrainingSession

UPLOADS_BASE_DIR = os.path.join("app", "static", "uploads", "trainings")
os.makedirs(UPLOADS_BASE_DIR, exist_ok=True)


def ensure_upload_dir(subdir: str = "") -> str:
    path = os.path.join(UPLOADS_BASE_DIR, subdir) if subdir else UPLOADS_BASE_DIR
    os.makedirs(path, exist_ok=True)
    return path


def add_calendar_months(source_date: date, months: int) -> date:
    """Suma meses calendario exactos (ej. 15/03 + 3 meses -> 15/06)."""
    total_months = source_date.month - 1 + months
    year = source_date.year + total_months // 12
    month = total_months % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    day = min(source_date.day, last_day)
    return date(year, month, day)


def _ics_escape(text: Optional[str]) -> str:
    if not text:
        return ""
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def generate_training_ics(
    training: Training,
    sessions: Optional[List[TrainingSession]] = None,
    attendee_email: Optional[str] = None,
    attendee_name: Optional[str] = None,
    organizer_email: Optional[str] = None,
) -> bytes:
    """Genera un calendario .ics válido (RFC 5545) con las sesiones o rango de fechas."""
    org_email = organizer_email or settings.EMAILS_FROM_EMAIL
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Talento Humano UP//Capacitaciones//ES",
        "CALSCALE:GREGORIAN",
        "METHOD:REQUEST",
    ]
    now_stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    location = training.location or training.meeting_url or "Por definir"

    if sessions:
        for s in sessions:
            dt_start = datetime.combine(s.date, s.start_time)
            dt_end = datetime.combine(s.date, s.end_time)
            s_loc = s.location_or_link or location
            uid = f"training-{training.id}-session-{s.id}@talento-up"
            lines.extend([
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{now_stamp}",
                f"DTSTART:{dt_start.strftime('%Y%m%dT%H%M%S')}",
                f"DTEND:{dt_end.strftime('%Y%m%dT%H%M%S')}",
                f"SUMMARY:{_ics_escape(training.name)} - {_ics_escape(s.topic)}",
                f"DESCRIPTION:{_ics_escape(training.objective or training.description or s.description)}",
                f"LOCATION:{_ics_escape(s_loc)}",
                f"ORGANIZER;CN={_ics_escape(settings.EMAILS_FROM_NAME)}:mailto:{org_email}",
            ])
            if attendee_email:
                cn = _ics_escape(attendee_name or attendee_email)
                lines.append(f"ATTENDEE;CN={cn};RSVP=TRUE:mailto:{attendee_email}")
            lines.append("END:VEVENT")
    else:
        dt_start = datetime.combine(training.start_date, time(9, 0))
        dt_end = datetime.combine(training.end_date, time(17, 0))
        uid = f"training-{training.id}@talento-up"
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{now_stamp}",
            f"DTSTART:{dt_start.strftime('%Y%m%dT%H%M%S')}",
            f"DTEND:{dt_end.strftime('%Y%m%dT%H%M%S')}",
            f"SUMMARY:{_ics_escape(training.name)}",
            f"DESCRIPTION:{_ics_escape(training.objective or training.description)}",
            f"LOCATION:{_ics_escape(location)}",
            f"ORGANIZER;CN={_ics_escape(settings.EMAILS_FROM_NAME)}:mailto:{org_email}",
        ])
        if attendee_email:
            cn = _ics_escape(attendee_name or attendee_email)
            lines.append(f"ATTENDEE;CN={cn};RSVP=TRUE:mailto:{attendee_email}")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


async def get_manager_area_ids(db: AsyncSession, user: User) -> List[int]:
    """Devuelve los IDs de área que un Jefe de Área (MANAGER) puede ver (CA-13)."""
    area_ids = set()
    if user.area_id:
        area_ids.add(user.area_id)
    if user.employee_id:
        emp = (
            await db.execute(
                select(Employee)
                .options(selectinload(Employee.position_obj))
                .where(Employee.id == user.employee_id)
            )
        ).scalar_one_or_none()
        if emp and emp.position_obj and emp.position_obj.area_id:
            area_ids.add(emp.position_obj.area_id)
    if user.email:
        rows = (
            await db.execute(select(Area.id).where(Area.responsible_email == user.email))
        ).scalars().all()
        area_ids.update(rows)
    return list(area_ids)


async def get_employee_manager_emails(db: AsyncSession, employee: Employee) -> List[str]:
    """Obtiene el(los) correo(s) del jefe inmediato o responsable del área del colaborador."""
    emails: List[str] = []
    pos = employee.position_obj
    if not pos and employee.position_id:
        pos = (
            await db.execute(
                select(Position)
                .options(selectinload(Position.area))
                .where(Position.id == employee.position_id)
            )
        ).scalar_one_or_none()

    if pos:
        if pos.parent_id:
            bosses = (
                await db.execute(
                    select(Employee).where(
                        Employee.position_id == pos.parent_id,
                        Employee.is_active == True,  # noqa
                    )
                )
            ).scalars().all()
            for boss in bosses:
                if boss.institutional_email:
                    emails.append(boss.institutional_email)

        if pos.area_id:
            mgr_users = (
                await db.execute(
                    select(User).where(
                        User.role == UserRole.MANAGER,
                        User.area_id == pos.area_id,
                        User.is_active == True,  # noqa
                    )
                )
            ).scalars().all()
            for u in mgr_users:
                if u.email:
                    emails.append(u.email)

            area = pos.area or await db.get(Area, pos.area_id)
            if area and area.responsible_email and not emails:
                emails.append(area.responsible_email)

    seen = set()
    unique: List[str] = []
    for e in emails:
        clean = e.strip()
        if clean and clean not in seen and clean != employee.institutional_email:
            seen.add(clean)
            unique.append(clean)
    return unique


async def get_th_emails(db: AsyncSession) -> List[str]:
    """Obtiene los correos de los gestores/administradores de TH activos."""
    users = (
        await db.execute(
            select(User).where(
                User.role.in_([UserRole.TH, UserRole.ADMIN]),
                User.is_active == True,  # noqa
            )
        )
    ).scalars().all()
    emails = [u.email for u in users if u.email]
    if not emails and settings.EMAILS_FROM_EMAIL:
        emails = [settings.EMAILS_FROM_EMAIL]
    return list(dict.fromkeys(emails))


async def log_training_audit(
    db: AsyncSession,
    entity_type: str,
    entity_id: int,
    action: str,
    field: Optional[str] = None,
    old_value: Any = None,
    new_value: Any = None,
    reason: Optional[str] = None,
    user_id: Optional[int] = None,
) -> TrainingAudit:
    """Registra una entrada en la bitácora de auditoría del módulo (RF-33)."""
    audit = TrainingAudit(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        field=field,
        old_value=str(old_value) if old_value is not None else None,
        new_value=str(new_value) if new_value is not None else None,
        reason=reason,
        user_id=user_id,
    )
    db.add(audit)
    return audit


def is_facilitator_of_training(user: User, training: Training) -> bool:
    """Indica si el usuario autenticado es el facilitador interno de la capacitación."""
    return bool(
        user.employee_id
        and training.internal_instructor_id
        and user.employee_id == training.internal_instructor_id
    )


    lines.append("END:VCALENDAR")
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")
