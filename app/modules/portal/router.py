from typing import Annotated, Optional
from datetime import date, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy import select, desc, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.exceptions import RolePermissionError
from app.modules.auth.dependencies import is_authenticated
from app.modules.auth.models import User, UserRole
from app.modules.employees.models import Employee
from app.modules.employees import schemas as emp_schemas
from app.modules.portal import schemas as portal_schemas
from app.modules.portal import service as portal_service
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

    leader_ctx = await portal_service.get_leader_context(db, employee, current_user)
    my_vacations = await portal_service.list_my_vacation_requests(db, employee.id)

    pending_benefits_count = 0
    open_vacancies_count = 0
    team_events_count = 0
    if leader_ctx["is_leader"]:
        pending_benefits = await portal_service.get_area_pending_benefit_requests(
            db, leader_ctx["subordinate_employee_ids"]
        )
        pending_benefits_count = len(pending_benefits)
        area_vacancies = await portal_service.get_area_vacancies_status(
            db, leader_ctx["leader_area_ids"]
        )
        open_vacancies_count = len([v for v in area_vacancies if v["status"] == "open"])
        team_events = await portal_service.get_team_events_participation(
            db, leader_ctx["subordinate_employee_ids"]
        )
        team_events_count = len(team_events)

    return templates.TemplateResponse(request=request, name="portal/dashboard.html", context=
        {
            "request": request,
            "current_user": current_user,
            "employee": employee,
            "upcoming_events": upcoming_events,
            "active_trainings": active_trainings,
            "my_vacations": my_vacations[:3],
            "leader_ctx": leader_ctx,
            "pending_benefits_count": pending_benefits_count,
            "open_vacancies_count": open_vacancies_count,
            "team_events_count": team_events_count,
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
    leader_ctx = await portal_service.get_leader_context(db, employee, current_user)

    return templates.TemplateResponse(request=request, name="portal/profile.html", context=
        {
            "request": request,
            "current_user": current_user,
            "employee": employee,
            "benefit_history": benefit_history,
            "leader_ctx": leader_ctx,
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
    employee = await get_current_employee(db, current_user)
    leader_ctx = await portal_service.get_leader_context(db, employee, current_user)

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
            "leader_ctx": leader_ctx,
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
    employee = await get_current_employee(db, current_user)
    if not employee:
        return templates.TemplateResponse(request=request, name="portal/no_employee.html", context= {"request": request, "current_user": current_user, "settings": settings})

    stmt = (
        select(EventEnrollment)
        .join(CalendarEvent)
        .options(
            selectinload(EventEnrollment.event).selectinload(CalendarEvent.event_type)
        )
        .where(EventEnrollment.employee_id == employee.id)
        .order_by(desc(CalendarEvent.date))
    )
    events = (await db.execute(stmt)).scalars().all()
    leader_ctx = await portal_service.get_leader_context(db, employee, current_user)

    return templates.TemplateResponse(request=request, name="portal/events.html", context=
        {
            "request": request,
            "current_user": current_user,
            "events": events,
            "leader_ctx": leader_ctx,
            "settings": settings
        }
    )


@router.get("/vacations", response_class=HTMLResponse)
@is_authenticated
async def portal_vacations(
    request: Request,
    current_user: User = Depends(is_authenticated),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """Vista para solicitar vacaciones formalmente y ver el historial propio."""
    employee = await get_current_employee(db, current_user)
    if not employee:
        return templates.TemplateResponse(
            request=request,
            name="portal/no_employee.html",
            context={"request": request, "current_user": current_user, "settings": settings},
        )

    leader_ctx = await portal_service.get_leader_context(db, employee, current_user)
    my_requests = await portal_service.list_my_vacation_requests(db, employee.id)
    primary_sup, superiors, recipient_emails = await portal_service.get_employee_superiors_and_emails(
        db, employee
    )

    current_year = date.today().year
    approved_days_year = sum(
        r.business_days or r.days_requested
        for r in my_requests
        if r.status == "Aprobada" and r.start_date.year == current_year
    )
    pending_count = sum(1 for r in my_requests if r.status == "Pendiente")
    approved_count = sum(1 for r in my_requests if r.status == "Aprobada")

    return templates.TemplateResponse(
        request=request,
        name="portal/vacations.html",
        context={
            "request": request,
            "current_user": current_user,
            "employee": employee,
            "leader_ctx": leader_ctx,
            "my_requests": my_requests,
            "primary_superior": primary_sup,
            "superiors": superiors,
            "recipient_emails": recipient_emails,
            "approved_days_year": approved_days_year,
            "pending_count": pending_count,
            "approved_count": approved_count,
            "current_year": current_year,
            "settings": settings,
        },
    )


# --- PANEL DE LÍDER ---

@router.get("/leader", response_class=HTMLResponse)
@is_authenticated
async def portal_leader_dashboard(
    request: Request,
    current_user: User = Depends(is_authenticated),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """Panel de gestión para líderes de área / equipo (solo colaboradores abajo)."""
    employee = await get_current_employee(db, current_user)
    if not employee:
        return templates.TemplateResponse(
            request=request,
            name="portal/no_employee.html",
            context={"request": request, "current_user": current_user, "settings": settings},
        )

    leader_ctx = await portal_service.get_leader_context(db, employee, current_user)
    if not leader_ctx["is_leader"]:
        raise RolePermissionError(
            "Acceso restringido: Esta sección es exclusiva para líderes de área o jefaturas."
        )

    sub_ids = leader_ctx["subordinate_employee_ids"]
    vacation_requests = await portal_service.list_leader_vacation_requests(db, sub_ids)
    pending_vacations = [v for v in vacation_requests if v.status == "Pendiente"]
    history_vacations = [v for v in vacation_requests if v.status != "Pendiente"]

    pending_benefits = await portal_service.get_area_pending_benefit_requests(db, sub_ids)
    area_vacancies = await portal_service.get_area_vacancies_status(
        db, leader_ctx["leader_area_ids"]
    )
    team_events = await portal_service.get_team_events_participation(db, sub_ids)
    team_trainings = await portal_service.get_team_trainings_participation(db, sub_ids)

    return templates.TemplateResponse(
        request=request,
        name="portal/leader.html",
        context={
            "request": request,
            "current_user": current_user,
            "employee": employee,
            "leader_ctx": leader_ctx,
            "pending_vacations": pending_vacations,
            "history_vacations": history_vacations,
            "pending_benefits": pending_benefits,
            "area_vacancies": area_vacancies,
            "team_events": team_events,
            "team_trainings": team_trainings,
            "settings": settings,
        },
    )


@router.get("/leader/employees/{emp_id}", response_class=HTMLResponse)
@is_authenticated
async def portal_leader_employee_detail(
    emp_id: int,
    request: Request,
    current_user: User = Depends(is_authenticated),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """Vista del legajo de un colaborador subordinado (estrictamente abajo del líder)."""
    employee = await get_current_employee(db, current_user)
    if not employee:
        return templates.TemplateResponse(
            request=request,
            name="portal/no_employee.html",
            context={"request": request, "current_user": current_user, "settings": settings},
        )

    if emp_id == employee.id:
        return RedirectResponse(url="/portal/profile", status_code=302)

    leader_ctx = await portal_service.get_leader_context(db, employee, current_user)
    if not leader_ctx["is_leader"]:
        raise RolePermissionError(
            "No tienes permisos para ver legajos de otros colaboradores."
        )

    detail = await portal_service.get_subordinate_employee_detail(
        db, leader_ctx, emp_id
    )
    if not detail:
        raise RolePermissionError(
            "Acceso denegado: Solo puedes consultar el legajo de colaboradores que están bajo tu línea de reporte."
        )

    return templates.TemplateResponse(
        request=request,
        name="portal/team_employee_detail.html",
        context={
            "request": request,
            "current_user": current_user,
            "leader": employee,
            "leader_ctx": leader_ctx,
            "subordinate": detail["employee"],
            "events": detail["events"],
            "vacations": detail["vacations"],
            "is_direct": detail["is_direct"],
            "settings": settings,
        },
    )


# --- API VACACIONES & LÍDER ---

@router.get("/api/vacations/preview-days")
@is_authenticated
async def preview_vacation_days_api(
    start_date: date = Query(...),
    end_date: date = Query(...),
    current_user: User = Depends(is_authenticated),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    if end_date < start_date:
        raise HTTPException(400, "La fecha de fin no puede ser anterior a la fecha de inicio.")
    calendar_days = (end_date - start_date).days + 1
    business_days = await portal_service.count_inclusive_business_days(db, start_date, end_date)
    return {"calendar_days": calendar_days, "business_days": business_days}


@router.get("/api/vacations", response_model=list[portal_schemas.VacationRequestRead])
@is_authenticated
async def list_my_vacations_api(
    current_user: User = Depends(is_authenticated),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    employee = await get_current_employee(db, current_user)
    if not employee:
        raise HTTPException(400, "Tu usuario no está vinculado a un colaborador.")
    return await portal_service.list_my_vacation_requests(db, employee.id)


@router.post("/api/vacations", response_model=portal_schemas.VacationRequestRead, status_code=201)
@is_authenticated
async def create_vacation_api(
    data: portal_schemas.VacationRequestCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(is_authenticated),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    employee = await get_current_employee(db, current_user)
    if not employee:
        raise HTTPException(400, "Tu usuario no está vinculado a un colaborador.")
    return await portal_service.create_vacation_request(db, employee, data, background_tasks)


@router.post("/api/vacations/{req_id}/cancel", response_model=portal_schemas.VacationRequestRead)
@is_authenticated
async def cancel_vacation_api(
    req_id: int,
    current_user: User = Depends(is_authenticated),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    employee = await get_current_employee(db, current_user)
    if not employee:
        raise HTTPException(400, "Tu usuario no está vinculado a un colaborador.")
    return await portal_service.cancel_vacation_request(db, employee, req_id)


@router.get("/api/leader/vacations", response_model=list[portal_schemas.VacationRequestRead])
@is_authenticated
async def list_leader_vacations_api(
    status: Optional[str] = None,
    current_user: User = Depends(is_authenticated),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    employee = await get_current_employee(db, current_user)
    if not employee:
        raise HTTPException(400, "Tu usuario no está vinculado a un colaborador.")
    leader_ctx = await portal_service.get_leader_context(db, employee, current_user)
    if not leader_ctx["is_leader"]:
        raise HTTPException(403, "Acceso exclusivo para líderes.")
    return await portal_service.list_leader_vacation_requests(
        db, leader_ctx["subordinate_employee_ids"], status_filter=status
    )


@router.post("/api/leader/vacations/{req_id}/decision", response_model=portal_schemas.VacationRequestRead)
@is_authenticated
async def review_vacation_api(
    req_id: int,
    data: portal_schemas.VacationRequestDecision,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(is_authenticated),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    employee = await get_current_employee(db, current_user)
    if not employee and current_user.role != UserRole.ADMIN:
        raise HTTPException(400, "Tu usuario no está vinculado a un colaborador.")
    return await portal_service.review_vacation_request(
        db, employee, current_user, req_id, data, background_tasks
    )



async def _require_leader_and_subordinate(
    db: AsyncSession, current_user: User, emp_id: Optional[int] = None
):
    employee = await get_current_employee(db, current_user)
    if not employee:
        raise HTTPException(400, "Tu usuario no está vinculado a un colaborador.")
    leader_ctx = await portal_service.get_leader_context(db, employee, current_user)
    if not leader_ctx["is_leader"]:
        raise HTTPException(403, "Acceso exclusivo para líderes.")
    if emp_id is not None and emp_id not in leader_ctx["subordinate_employee_ids"]:
        raise HTTPException(
            403,
            "Acceso denegado: Solo puedes gestionar colaboradores que están bajo tu línea de reporte.",
        )
    return employee, leader_ctx


@router.get("/api/leader/hierarchy")
@is_authenticated
async def leader_hierarchy_api(
    mode: str = Query("people"),
    current_user: User = Depends(is_authenticated),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    employee, leader_ctx = await _require_leader_and_subordinate(db, current_user)
    return await portal_service.get_leader_hierarchy_tree(
        db, employee, leader_ctx, mode=mode
    )


@router.get("/api/leader/reports/excel")
@is_authenticated
async def leader_excel_report_api(
    section: str = Query("all"),
    current_user: User = Depends(is_authenticated),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    employee, leader_ctx = await _require_leader_and_subordinate(db, current_user)
    if section not in ("all", "team", "vacations", "recruitment", "events"):
        section = "all"
    excel_io = await portal_service.generate_leader_excel_report(
        db, employee, leader_ctx, section=section
    )
    filename = f"reporte_lider_{section}_{date.today().strftime('%Y%m%d')}.xlsx"
    return StreamingResponse(
        excel_io,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/api/leader/employees/{emp_id}/report/excel")
@is_authenticated
async def leader_subordinate_excel_api(
    emp_id: int,
    current_user: User = Depends(is_authenticated),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    _, leader_ctx = await _require_leader_and_subordinate(db, current_user, emp_id)
    res = await portal_service.generate_subordinate_legajo_excel(db, leader_ctx, emp_id)
    if not res:
        raise HTTPException(404, "Colaborador no encontrado.")
    excel_io, emp = res
    safe_name = "".join(c if c.isalnum() else "_" for c in emp.full_name).strip("_")
    filename = f"legajo_{safe_name}_{date.today().strftime('%Y%m%d')}.xlsx"
    return StreamingResponse(
        excel_io,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )



@router.get("/api/leader/employees/{emp_id}/timeline")
@is_authenticated
async def leader_subordinate_timeline_api(
    emp_id: int,
    current_user: User = Depends(is_authenticated),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    _, leader_ctx = await _require_leader_and_subordinate(db, current_user, emp_id)
    timeline = await portal_service.get_subordinate_timeline(db, leader_ctx, emp_id)
    if timeline is None:
        raise HTTPException(403, "No tienes acceso a este colaborador.")
    return timeline


@router.post("/api/leader/employees/{emp_id}/sanctions")
@is_authenticated
async def leader_create_sanction_api(
    emp_id: int,
    data: dict,
    current_user: User = Depends(is_authenticated),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    await _require_leader_and_subordinate(db, current_user, emp_id)
    from app.modules.disciplinary import schemas as disc_schemas, service as disc_service

    payload = disc_schemas.SanctionCreate(employee_id=emp_id, **data)
    return await disc_service.create_sanction(db, payload)


@router.delete("/api/leader/sanctions/{sanction_id}", status_code=204)
@is_authenticated
async def leader_delete_sanction_api(
    sanction_id: int,
    current_user: User = Depends(is_authenticated),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    _, leader_ctx = await _require_leader_and_subordinate(db, current_user)
    from app.modules.disciplinary.models import Sanction
    from app.modules.disciplinary import service as disc_service

    s = await db.get(Sanction, sanction_id)
    if not s:
        raise HTTPException(404, "Amonestación no encontrada.")
    if s.employee_id not in leader_ctx["subordinate_employee_ids"]:
        raise HTTPException(403, "No tienes permisos sobre este colaborador.")
    await disc_service.delete_sanction(db, sanction_id)
    return None


@router.post("/api/leader/employees/{emp_id}/recognitions")
@is_authenticated
async def leader_create_recognition_api(
    emp_id: int,
    data: dict,
    current_user: User = Depends(is_authenticated),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    await _require_leader_and_subordinate(db, current_user, emp_id)
    from app.modules.disciplinary import schemas as disc_schemas, service as disc_service

    payload = disc_schemas.RecognitionCreate(employee_id=emp_id, **data)
    return await disc_service.create_recognition(db, payload)


@router.delete("/api/leader/recognitions/{recog_id}", status_code=204)
@is_authenticated
async def leader_delete_recognition_api(
    recog_id: int,
    current_user: User = Depends(is_authenticated),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    _, leader_ctx = await _require_leader_and_subordinate(db, current_user)
    from app.modules.disciplinary.models import Recognition
    from app.modules.disciplinary import service as disc_service

    r = await db.get(Recognition, recog_id)
    if not r:
        raise HTTPException(404, "Reconocimiento no encontrado.")
    if r.employee_id not in leader_ctx["subordinate_employee_ids"]:
        raise HTTPException(403, "No tienes permisos sobre este colaborador.")
    await disc_service.delete_recognition(db, recog_id)
    return None


@router.post("/api/leader/employees/{emp_id}/documents")
@is_authenticated
async def leader_upload_document_api(
    emp_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(is_authenticated),
    name: str = Form(...),
    category: str = Form(...),
    file: UploadFile = File(...),
    notes: Optional[str] = Form(None),
    expiration_date: Optional[str] = Form(None),
):
    await _require_leader_and_subordinate(db, current_user, emp_id)
    from app.modules.employees import service as emp_service

    exp_date = None
    if expiration_date and expiration_date.strip():
        try:
            exp_date = datetime.strptime(expiration_date, "%Y-%m-%d").date()
        except ValueError:
            pass
    await emp_service.upload_document(db, emp_id, name, category, file, notes, exp_date)
    return {"message": "Documento subido correctamente"}

