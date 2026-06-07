from typing import Annotated
from datetime import date, datetime

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from app.core.templates import templates
from sqlalchemy import select, desc, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.modules.auth.dependencies import is_authenticated
from app.modules.auth.models import User
from app.modules.employees.models import Employee
from app.modules.employees import schemas as emp_schemas
from app.modules.trainings.models import (
    TrainingEnrollment, 
    TrainingAttendance, 
    TrainingSession, 
    Training
)
from app.modules.calendar.models import (
    EventEnrollment, 
    CalendarEvent, 
    CalendarEventType
)
from app.modules.benefits.models import EmployeeBenefit, BenefitType
from app.modules.organization.models import Position, Area, Sede
from app.core.config import settings

router = APIRouter(prefix="/portal", tags=["portal"])

async def get_current_employee(db: AsyncSession, user: User) -> Employee:
    if not user.employee_id:
        return None
    
    stmt = (
        select(Employee)
        .options(
            # Cadena de carga: Employee -> Position -> Area -> Sede
            selectinload(Employee.position_obj)
            .selectinload(Position.area)
            .selectinload(Area.sede),
            
            selectinload(Employee.dietary_restrictions),
            
            # Cadena de carga: Employee -> EmployeeBenefit -> BenefitType
            selectinload(Employee.benefits).selectinload(EmployeeBenefit.benefit_type),
            
            selectinload(Employee.documents)
        )
        .where(Employee.id == user.employee_id)
    )
    return (await db.execute(stmt)).scalar_one_or_none()

@router.get("/dashboard", response_class=HTMLResponse)
@is_authenticated
async def portal_dashboard(
    request: Request, 
    current_user: User = Depends(is_authenticated),
    db: Annotated[AsyncSession, Depends(get_db)] = None
):
    """Vista principal del portal."""
    employee = await get_current_employee(db, current_user)
    
    if not employee:
        return templates.TemplateResponse(request=request, name="portal/no_employee.html", context= {"request": request, "current_user": current_user, "settings": settings})

    # 1. Próximos Eventos (Calendario + Capacitaciones)
    today = date.today()
    
    # Eventos de Calendario Futuros
    stmt_events = (
        select(EventEnrollment)
        .join(CalendarEvent)
        .options(
            selectinload(EventEnrollment.event).selectinload(CalendarEvent.event_type)
        )
        .where(
            EventEnrollment.employee_id == employee.id,
            CalendarEvent.date >= today
        )
        .order_by(CalendarEvent.date)
        .limit(3)
    )
    upcoming_events = (await db.execute(stmt_events)).scalars().all()

    # Capacitaciones en curso o futuras
    stmt_trainings = (
        select(TrainingEnrollment)
        .join(TrainingEnrollment.training)
        .options(selectinload(TrainingEnrollment.training))
        .where(
            TrainingEnrollment.employee_id == employee.id,
            TrainingEnrollment.training.has(Training.end_date >= today)
        )
        .order_by(desc(Training.start_date))
        .limit(3)
    )
    active_trainings = (await db.execute(stmt_trainings)).scalars().all()

    return templates.TemplateResponse(request=request, name="portal/dashboard.html", context=
        {
            "request": request,
            "current_user": current_user,
            "employee": employee,
            "upcoming_events": upcoming_events,
            "active_trainings": active_trainings,
            "settings": settings
        }
    )

@router.get("/profile", response_class=HTMLResponse)
@is_authenticated
async def portal_profile(
    request: Request, 
    current_user: User = Depends(is_authenticated),
    db: Annotated[AsyncSession, Depends(get_db)] = None
):
    """Vista de perfil completo (Legajo + Beneficios + Dieta)."""
    employee = await get_current_employee(db, current_user)
    if not employee:
        return templates.TemplateResponse(request=request, name="portal/no_employee.html", context= {"request": request, "current_user": current_user, "settings": settings})

    return templates.TemplateResponse(request=request, name="portal/profile.html", context=
        {
            "request": request,
            "current_user": current_user,
            "employee": employee,
            "settings": settings
        }
    )

@router.get("/trainings", response_class=HTMLResponse)
@is_authenticated
async def portal_trainings(
    request: Request, 
    current_user: User = Depends(is_authenticated),
    db: Annotated[AsyncSession, Depends(get_db)] = None
):
    """Vista de mis capacitaciones con detalle de asistencia."""
    if not current_user.employee_id:
        return templates.TemplateResponse(request=request, name="portal/no_employee.html", context= {"request": request, "current_user": current_user, "settings": settings})

    # Cargar inscripciones con sesiones y asistencias
    stmt = (
        select(TrainingEnrollment)
        .join(TrainingEnrollment.training)
        .options(
            selectinload(TrainingEnrollment.training).selectinload(Training.sessions),
            selectinload(TrainingEnrollment.attendances).selectinload(TrainingAttendance.session)
        )
        .where(TrainingEnrollment.employee_id == current_user.employee_id)
        .order_by(desc(Training.start_date))
    )
    enrollments = (await db.execute(stmt)).scalars().all()
    
    # Procesar datos para la vista (calcular % asistencia)
    trainings_data = []
    for enroll in enrollments:
        total_sessions = len(enroll.training.sessions)
        attended_sessions = len([a for a in enroll.attendances if a.is_present])
        attendance_pct = int((attended_sessions / total_sessions * 100)) if total_sessions > 0 else 0
        
        trainings_data.append({
            "enrollment": enroll,
            "training": enroll.training,
            "attendance_pct": attendance_pct,
            "total_sessions": total_sessions,
            "attended_sessions": attended_sessions,
            "sessions_detail": enroll.training.sessions, # Para el modal
            "my_attendance_map": {a.session_id: a for a in enroll.attendances} # Mapa rápido
        })

    return templates.TemplateResponse(request=request, name="portal/trainings.html", context=
        {
            "request": request,
            "current_user": current_user,
            "trainings_data": trainings_data,
            "settings": settings
        }
    )

@router.get("/events", response_class=HTMLResponse)
@is_authenticated
async def portal_events(
    request: Request, 
    current_user: User = Depends(is_authenticated),
    db: Annotated[AsyncSession, Depends(get_db)] = None
):
    """Vista de eventos institucionales (Calendario)."""
    if not current_user.employee_id:
        return templates.TemplateResponse(request=request, name="portal/no_employee.html", context= {"request": request, "current_user": current_user, "settings": settings})

    stmt = (
        select(EventEnrollment)
        .join(CalendarEvent)
        .options(
            selectinload(EventEnrollment.event).selectinload(CalendarEvent.event_type)
        )
        .where(EventEnrollment.employee_id == current_user.employee_id)
        .order_by(desc(CalendarEvent.date))
    )
    events = (await db.execute(stmt)).scalars().all()

    return templates.TemplateResponse(request=request, name="portal/events.html", context=
        {
            "request": request,
            "current_user": current_user,
            "events": events,
            "settings": settings
        }
    )