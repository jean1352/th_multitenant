from typing import Annotated
from datetime import date, datetime

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select, desc, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.modules.auth.dependencies import is_authenticated
from app.modules.auth.models import User
from app.modules.employees.models import Employee
from app.modules.employees import schemas as emp_schemas
from app.modules.trainings.models import (
    EnrollmentStatus,
    ReplicaCommitment,
    ReplicaStatus,
    TrainingEnrollment,
    TrainingAttendance,
    TrainingSession,
    Training,
    TrainingStatus,
)
from app.modules.trainings import replicas_service, parameters_service
from app.modules.trainings.notifications_service import _effective_presence
from app.modules.calendar.models import (
    EventEnrollment, 
    CalendarEvent, 
    CalendarEventType
)
from app.modules.benefits.models import EmployeeBenefit, BenefitType
from app.modules.organization.models import Position, Area, Sede
from app.core.config import settings

router = APIRouter(prefix="/portal", tags=["portal"])
from app.core.templates import templates

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

    # Historial de solicitudes de beneficios del colaborador (todos los estados)
    from app.modules.benefits import service as benefits_service
    from app.modules.benefits import schemas as ben_schemas
    benefit_history_orm = await benefits_service.get_benefit_history_by_employee(db, employee.id)
    benefit_history = [ben_schemas.BenefitRequestRead.model_validate(r).model_dump(mode="json") for r in benefit_history_orm]

    return templates.TemplateResponse(request=request, name="portal/profile.html", context=
        {
            "request": request,
            "current_user": current_user,
            "employee": employee,
            "benefit_history": benefit_history,
            "settings": settings
        }
    )

@router.get("/trainings", response_class=HTMLResponse)
@is_authenticated
async def portal_trainings(
    request: Request,
    current_user: User = Depends(is_authenticated),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """Vista de mis capacitaciones, historial, encuesta, QR y Mis Réplicas."""
    if not current_user.employee_id:
        return templates.TemplateResponse(
            request=request,
            name="portal/no_employee.html",
            context={"request": request, "current_user": current_user, "settings": settings},
        )

    params = await parameters_service.get_parameters_dict(db)
    stmt = (
        select(TrainingEnrollment)
        .join(TrainingEnrollment.training)
        .options(
            selectinload(TrainingEnrollment.training).selectinload(Training.sessions),
            selectinload(TrainingEnrollment.attendances).selectinload(TrainingAttendance.session),
            selectinload(TrainingEnrollment.survey),
        )
        .where(TrainingEnrollment.employee_id == current_user.employee_id)
        .order_by(desc(Training.start_date))
    )
    enrollments = (await db.execute(stmt)).scalars().all()

    trainings_data = []
    enrolled_training_ids = set()
    for enroll in enrollments:
        enrolled_training_ids.add(enroll.training_id)
        total_sessions = len(enroll.training.sessions)
        attended_sessions = len([a for a in enroll.attendances if _effective_presence(a, params)])
        attendance_pct = (
            round(enroll.attendance_pct, 1)
            if enroll.attendance_pct is not None
            else (round((attended_sessions / total_sessions * 100), 1) if total_sessions > 0 else 0.0)
        )
        trainings_data.append({
            "enrollment": enroll,
            "training": enroll.training,
            "attendance_pct": attendance_pct,
            "total_sessions": total_sessions,
            "attended_sessions": attended_sessions,
            "sessions_detail": enroll.training.sessions,
            "my_attendance_map": {a.session_id: a for a in enroll.attendances},
        })

    # Capacitaciones disponibles para solicitar inscripción (RF-10)
    open_stmt = (
        select(Training)
        .where(Training.status.in_([TrainingStatus.PLANNED, TrainingStatus.IN_PROGRESS]))
        .order_by(Training.start_date)
    )
    all_open = (await db.execute(open_stmt)).scalars().all()
    open_trainings = [t for t in all_open if t.id not in enrolled_training_ids]

    # Compromisos de réplica del colaborador ("Mis réplicas", RF-24, RF-25)
    my_commitments = await replicas_service.get_employee_commitments(db, current_user.employee_id)
    # Candidatos para réplica conjunta (RN-10)
    joint_candidates_map = {}
    for c_item in my_commitments:
        c = c_item["commitment"]
        peers = (
            await db.execute(
                select(ReplicaCommitment)
                .options(selectinload(ReplicaCommitment.employee))
                .where(
                    ReplicaCommitment.source_training_id == c.source_training_id,
                    ReplicaCommitment.id != c.id,
                    ReplicaCommitment.status.in_([ReplicaStatus.PENDING.value, ReplicaStatus.PROPOSED.value]),
                )
            )
        ).scalars().all()
        joint_candidates_map[c.id] = peers

    # Capacitaciones donde el colaborador es facilitador interno
    facilitated_trainings = (
        await db.execute(
            select(Training)
            .where(Training.internal_instructor_id == current_user.employee_id)
            .order_by(desc(Training.start_date))
        )
    ).scalars().all()

    areas = (await db.execute(select(Area).order_by(Area.name))).scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="portal/trainings.html",
        context={
            "request": request,
            "current_user": current_user,
            "trainings_data": trainings_data,
            "open_trainings": open_trainings,
            "commitments": my_commitments,
            "joint_candidates_map": joint_candidates_map,
            "facilitated_trainings": facilitated_trainings,
            "areas": areas,
            "settings": settings,
        },
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