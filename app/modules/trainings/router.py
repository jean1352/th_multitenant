"""
Router para el módulo de Capacitaciones.
Define las vistas HTML y endpoints API para el ciclo completo.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from typing import Annotated, Dict, List, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db, tenant_db_factory
from app.core.exceptions import RolePermissionError
from app.modules.auth.dependencies import (
    get_current_user,
    is_admin,
    is_authenticated,
    is_recruiter,
)
from app.modules.auth.models import User, UserRole
from app.modules.employees.models import Employee
from app.modules.organization.models import Area, CostCenter, Currency, Position, Sede
from app.modules.trainings import (
    analytics_service,
    notifications_service,
    parameters_service,
    replicas_service,
    schemas,
    service,
)
from app.modules.trainings.models import (
    EnrollmentStatus,
    ReplicaCommitment,
    SessionStatus,
    Training,
    TrainingEnrollment,
    TrainingEvidence,
    TrainingNotification,
    TrainingSession,
    TrainingStatus,
    TrainingType,
)
from app.modules.trainings.utils import (
    ensure_upload_dir,
    get_manager_area_ids,
    is_facilitator_of_training,
    legacy_upload_dir,
)

router = APIRouter(prefix="/trainings", tags=["trainings"])
from app.core.templates import templates

STATUS_MAP = {
    "draft": "Borrador",
    "planned": "Programada",
    "in_progress": "En Curso",
    "completed": "Finalizada",
    "closed": "Cerrada",
    "cancelled": "Cancelada",
    "pending_approval": "Pendiente Aprobación",
    "invited": "Invitado",
    "enrolled": "Inscrito",
    "waitlist": "Lista de Espera",
    "attended": "Aprobado",
    "failed": "No Aprobado",
    "no_show": "No Asistió",
    "declined": "Declinado",
    "withdrawn": "Baja",
    "pendiente": "Pendiente",
    "propuesta": "Propuesta",
    "programada": "Programada",
    "cumplida": "Cumplida",
    "vencida": "Vencida",
    "anulada_cese": "Anulada por cese",
}


def translate_status(value):
    return STATUS_MAP.get(value, value)


templates.env.filters["translate_status"] = translate_status


def _require_th_or_admin(user: User) -> None:
    if user.role not in (UserRole.ADMIN, UserRole.TH):
        raise RolePermissionError("Esta acción requiere rol de Gestor de Capacitaciones (TH) o Administrador.")


async def _scoped_area_ids(db: AsyncSession, user: User) -> Optional[List[int]]:
    if user.role == UserRole.MANAGER:
        return await get_manager_area_ids(db, user)
    return None


async def _ensure_training_view_access(db: AsyncSession, user: User, training: Training) -> None:
    if user.role in (UserRole.ADMIN, UserRole.TH):
        return
    if is_facilitator_of_training(user, training):
        return
    if user.role == UserRole.MANAGER:
        allowed = await get_manager_area_ids(db, user)
        if training.target_area_id in allowed:
            return
        enroll_areas = (
            await db.execute(
                select(Position.area_id)
                .join(Employee, Employee.position_id == Position.id)
                .join(TrainingEnrollment, TrainingEnrollment.employee_id == Employee.id)
                .where(TrainingEnrollment.training_id == training.id)
            )
        ).scalars().all()
        if any(a in allowed for a in enroll_areas):
            return
        raise RolePermissionError("No tiene permisos para ver capacitaciones fuera de su área.")
    raise RolePermissionError("Permisos insuficientes.")



# --- VISTAS HTML ---

@router.get("/", response_class=HTMLResponse)
@is_recruiter
async def list_trainings(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(1, ge=1),
    q: Optional[str] = None,
    status: Optional[str] = "all",
    training_type: Optional[str] = "all",
    modality: Optional[str] = "all",
    area_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """Vista principal: Plan de Capacitaciones."""
    area_id_int = int(area_id) if area_id and area_id.strip().isdigit() else None
    allowed_areas = await _scoped_area_ids(db, current_user)
    pagination = await service.get_trainings_paginated(
        db, page, 9, q, status, training_type, modality, area_id_int, allowed_area_ids=allowed_areas
    )
    trainings_data = [
        schemas.TrainingRead.model_validate(t).model_dump(mode="json")
        for t in pagination["data"]
    ]
    pagination["data"] = trainings_data

    currencies = (await db.execute(select(Currency).where(Currency.is_active == True).order_by(Currency.name))).scalars().all()  # noqa
    cost_centers = (await db.execute(select(CostCenter).where(CostCenter.is_active == True).order_by(CostCenter.name))).scalars().all()  # noqa
    sedes = (await db.execute(select(Sede).order_by(Sede.name))).scalars().all()
    areas = (await db.execute(select(Area).order_by(Area.name))).scalars().all()
    topics = await service.get_topics(db, active_only=True)

    return templates.TemplateResponse(
        request=request,
        name="trainings/index.html",
        context={
            "request": request,
            "pagination": pagination,
            "filters": {
                "q": q,
                "status": status,
                "training_type": training_type,
                "modality": modality,
                "area_id": area_id_int,
            },
            "currencies": currencies,
            "cost_centers": cost_centers,
            "sedes": sedes,
            "areas": areas,
            "topics": topics,
            "current_user": current_user,
            "settings": settings,
        },
    )


@router.get("/dashboard", response_class=HTMLResponse)
@is_recruiter
async def trainings_dashboard_view(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    area_id: Optional[str] = None,
    training_type: Optional[str] = "all",
    modality: Optional[str] = "all",
    current_user: User = Depends(get_current_user),
):
    """Tablero de KPIs y reportes exportables (RF-35, RF-36)."""
    s_date = date.fromisoformat(start_date) if start_date else None
    e_date = date.fromisoformat(end_date) if end_date else None
    area_int = int(area_id) if area_id and area_id.strip().isdigit() else None
    allowed_areas = await _scoped_area_ids(db, current_user)

    dashboard = await analytics_service.get_dashboard_data(
        db, s_date, e_date, area_int, training_type, modality, allowed_area_ids=allowed_areas
    )
    areas = (await db.execute(select(Area).order_by(Area.name))).scalars().all()
    trainings_all = (await db.execute(select(Training).order_by(Training.start_date.desc()))).scalars().all()
    employees_all = (await db.execute(select(Employee).order_by(Employee.full_name))).scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="trainings/dashboard.html",
        context={
            "request": request,
            "dashboard": dashboard,
            "areas": areas,
            "trainings_all": trainings_all,
            "employees_all": employees_all,
            "filters": {
                "start_date": start_date or "",
                "end_date": end_date or "",
                "area_id": area_int,
                "training_type": training_type,
                "modality": modality,
            },
            "current_user": current_user,
            "settings": settings,
        },
    )


@router.get("/replicas", response_class=HTMLResponse)
@is_recruiter
async def replicas_inbox_view(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    status: Optional[str] = "all",
    traffic_light: Optional[str] = "all",
    area_id: Optional[str] = None,
    q: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """Bandeja de control de réplicas con semáforo (RF-24, RF-25, RF-28)."""
    area_int = int(area_id) if area_id and area_id.strip().isdigit() else None
    allowed_areas = await _scoped_area_ids(db, current_user)
    items = await replicas_service.get_replicas_inbox(
        db, status, traffic_light, area_int, allowed_area_ids=allowed_areas, search=q
    )
    areas = (await db.execute(select(Area).order_by(Area.name))).scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="trainings/replicas.html",
        context={
            "request": request,
            "items": items,
            "areas": areas,
            "filters": {"status": status, "traffic_light": traffic_light, "area_id": area_int, "q": q or ""},
            "current_user": current_user,
            "settings": settings,
        },
    )


@router.get("/calendar", response_class=HTMLResponse)
@is_recruiter
async def trainings_calendar_view(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    """Calendario mensual de capacitaciones con filtros por tipo y área (RF-07)."""
    areas = (await db.execute(select(Area).order_by(Area.name))).scalars().all()
    return templates.TemplateResponse(
        request=request,
        name="trainings/calendar.html",
        context={"request": request, "areas": areas, "current_user": current_user, "settings": settings},
    )


PARAMETER_DISPLAY = {
    "min_attendance_pct": {
        "label": "Asistencia mínima para aprobar",
        "description": "Porcentaje mínimo de asistencia requerido para aprobar una capacitación.",
    },
    "late_counts_as_present": {
        "label": "Tardanza cuenta como presente",
        "description": "Considerar la tardanza como asistencia presente en el cálculo.",
    },
    "justified_counts_as_present": {
        "label": "Justificado cuenta como presente",
        "description": "Considerar la inasistencia justificada como presente en el cálculo.",
    },
    "replica_deadline_months": {
        "label": "Plazo de réplica (meses)",
        "description": "Plazo máximo en meses para cumplir un compromiso de réplica.",
    },
    "replica_min_attendees": {
        "label": "Mínimo de asistentes para réplica",
        "description": "Cantidad mínima de asistentes presentes para dar por cumplida una réplica.",
    },
    "qr_window_minutes": {
        "label": "Ventana de registro QR (minutos)",
        "description": "Minutos desde el inicio de la sesión para registrar asistencia por QR.",
    },
    "alert_days_start": {
        "label": "Anticipación del aviso de inicio",
        "description": "Días de anticipación antes del inicio para enviar el aviso de próximo inicio.",
    },
    "alert_days_reminder": {
        "label": "Anticipación del recordatorio final",
        "description": "Días de anticipación para enviar el recordatorio final.",
    },
    "alert_days_ending": {
        "label": "Anticipación del aviso de cierre",
        "description": "Días de anticipación antes de la fecha de fin para el aviso de próxima conclusión.",
    },
    "alert_days_cert_pending": {
        "label": "Días para certificado pendiente",
        "description": "Días tras el cierre de una externa para alertar el certificado pendiente del proveedor.",
    },
    "alert_days_replica": {
        "label": "Días de recordatorio de réplica",
        "description": "Días antes de la fecha límite de réplica para enviar recordatorios (separados por coma).",
    },
}


@router.get("/config", response_class=HTMLResponse)
@is_recruiter
async def trainings_config_view(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    """Configuración: parámetros, plantillas de correo y catálogo de temas."""
    params = await parameters_service.get_all_parameters(db)
    email_templates = await parameters_service.get_all_templates(db)
    topics = await service.get_topics(db)

    parameters_data = []
    for p in params:
        meta = PARAMETER_DISPLAY.get(p.key, {})
        parameters_data.append(
            {
                "key": p.key,
                "value": p.value,
                "label": meta.get("label") or p.key.replace("_", " ").title(),
                "description": meta.get("description") or p.description,
            }
        )

    return templates.TemplateResponse(
        request=request,
        name="trainings/config.html",
        context={
            "request": request,
            "parameters": parameters_data,
            "email_templates": email_templates,
            "topics": topics,
            "current_user": current_user,
            "settings": settings,
        },
    )


@router.get("/audit", response_class=HTMLResponse)
@is_recruiter
async def trainings_audit_view(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    entity_type: Optional[str] = "all",
    current_user: User = Depends(get_current_user),
):
    """Bitácora de auditoría del módulo (RF-33)."""
    audits = await service.get_training_audits(db, entity_type=entity_type)
    return templates.TemplateResponse(
        request=request,
        name="trainings/audit.html",
        context={
            "request": request,
            "audits": audits,
            "entity_type": entity_type,
            "current_user": current_user,
            "settings": settings,
        },
    )


@router.get("/providers", response_class=HTMLResponse)
@is_recruiter
async def list_providers_view(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    """Vista de gestión de proveedores."""
    providers = await service.get_providers(db)
    providers_data = [
        schemas.ProviderRead.model_validate(p).model_dump(mode="json")
        for p in providers
    ]
    return templates.TemplateResponse(
        request=request,
        name="trainings/providers.html",
        context={"request": request, "providers": providers_data, "current_user": current_user, "settings": settings},
    )


@router.get("/qr/{token}", response_class=HTMLResponse)
@is_authenticated
async def qr_checkin_view(
    token: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    """Vista móvil para registrar asistencia por código QR (RF-13, RNF-05)."""
    session = (
        await db.execute(
            select(TrainingSession)
            .options(selectinload(TrainingSession.training))
            .where(TrainingSession.qr_code_token == token)
        )
    ).scalar_one_or_none()
    if not session:
        return templates.TemplateResponse(
            request=request, name="404.html",
            context={"request": request, "current_user": current_user, "settings": settings},
            status_code=404,
        )
    return templates.TemplateResponse(
        request=request,
        name="trainings/qr_checkin.html",
        context={
            "request": request,
            "session": session,
            "training": session.training,
            "token": token,
            "current_user": current_user,
            "settings": settings,
        },
    )


@router.get("/{id:int}", response_class=HTMLResponse)
@is_authenticated
async def detail_training(
    id: int,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(1, ge=1),
    q: Optional[str] = None,
    area_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """Vista detalle: Información, inscritos, sesiones, evidencias y auditoría."""
    training = await service.get_training_detail(db, id)
    if not training:
        return templates.TemplateResponse(
            request=request,
            name="404.html",
            context={"request": request, "current_user": current_user, "settings": settings},
            status_code=404,
        )
    await _ensure_training_view_access(db, current_user, training)

    area_id_int = int(area_id) if area_id and area_id.strip().isdigit() else None
    allowed_areas = await _scoped_area_ids(db, current_user)
    enrollments_pag = await service.get_enrollments_paginated(
        db, id, page, 10, q, area_id_int, allowed_area_ids=allowed_areas
    )
    employees = (await db.execute(select(Employee).where(Employee.is_active == True).order_by(Employee.full_name))).scalars().all()  # noqa
    areas = (await db.execute(select(Area).order_by(Area.name))).scalars().all()
    sedes = (await db.execute(select(Sede).order_by(Sede.name))).scalars().all()
    positions = (await db.execute(select(Position).order_by(Position.name))).scalars().all()
    evidences = await service.get_evidences(db, "training", id)
    audits = await service.get_training_audits(db, entity_type="training", entity_id=id, limit=50)

    sessions_data = [
        schemas.SessionRead.model_validate(s).model_dump(mode="json")
        for s in training.sessions
    ]

    return templates.TemplateResponse(
        request=request,
        name="trainings/detail.html",
        context={
            "request": request,
            "training": training,
            "enrollments": enrollments_pag,
            "employees": employees,
            "areas": areas,
            "sedes": sedes,
            "positions": positions,
            "sessions": sessions_data,
            "evidences": evidences,
            "audits": audits,
            "is_facilitator": is_facilitator_of_training(current_user, training),
            "filters": {"q": q, "area_id": area_id_int},
            "current_user": current_user,
            "settings": settings,
        },
    )


# --- API PROVIDERS & TOPICS ---

@router.get("/api/providers", response_model=List[schemas.ProviderRead])
@is_recruiter
async def get_providers_api(db: Annotated[AsyncSession, Depends(get_db)], active_only: bool = False):
    return await service.get_providers(db, active_only)


@router.post("/api/providers", response_model=schemas.ProviderRead)
@is_recruiter
async def create_provider_api(
    data: schemas.ProviderCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    _require_th_or_admin(current_user)
    try:
        return await service.create_provider(db, data, user_id=current_user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/api/providers/{id}", response_model=schemas.ProviderRead)
@is_recruiter
async def update_provider_api(
    id: int,
    data: schemas.ProviderUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    _require_th_or_admin(current_user)
    updated = await service.update_provider(db, id, data, user_id=current_user.id)
    if not updated:
        raise HTTPException(404, "Proveedor no encontrado")
    return updated


@router.delete("/api/providers/{id}", status_code=204)
@is_recruiter
async def delete_provider_api(
    id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    _require_th_or_admin(current_user)
    try:
        if not await service.delete_provider(db, id, user_id=current_user.id):
            raise HTTPException(404, "Proveedor no encontrado")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return None


@router.get("/api/topics", response_model=List[schemas.TopicRead])
@is_recruiter
async def get_topics_api(db: Annotated[AsyncSession, Depends(get_db)], active_only: bool = False):
    return await service.get_topics(db, active_only)


@router.post("/api/topics", response_model=schemas.TopicRead)
@is_recruiter
async def create_topic_api(
    data: schemas.TopicCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    _require_th_or_admin(current_user)
    try:
        return await service.create_topic(db, data, user_id=current_user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/api/topics/{id}", status_code=204)
@is_recruiter
async def delete_topic_api(
    id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    _require_th_or_admin(current_user)
    if not await service.delete_topic(db, id):
        raise HTTPException(404, "Tema no encontrado")
    return None


# --- API TRAININGS & LIFECYCLE ---

@router.get("/api/calendar-events")
@is_recruiter
async def get_calendar_events_api(
    db: Annotated[AsyncSession, Depends(get_db)],
    training_type: Optional[str] = "all",
    area_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
):
    """Eventos mensuales de capacitaciones para FullCalendar con filtros (RF-07)."""
    allowed = await _scoped_area_ids(db, current_user)
    pag = await service.get_trainings_paginated(
        db, page=1, limit=500, training_type=training_type, area_id=area_id, allowed_area_ids=allowed
    )
    color_map = {"internal": "#7C3AED", "external": "#EA580C", "replica": "#0D9488"}
    events = []
    for t in pag["data"]:
        c = color_map.get(t.type.value, "#2563EB")
        events.append({
            "id": t.id,
            "title": f"[{t.type.value.upper()}] {t.name}",
            "start": t.start_date.isoformat(),
            "end": t.end_date.isoformat(),
            "backgroundColor": c,
            "borderColor": c,
            "url": f"/trainings/{t.id}",
            "extendedProps": {"status": t.status.value, "modality": t.modality},
        })
    return events


@router.post("/api", response_model=schemas.TrainingRead)
@is_recruiter
async def create_training(
    t: schemas.TrainingCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    """API: Crear nueva capacitación."""
    _require_th_or_admin(current_user)
    try:
        return await service.create_training(db, t, user_id=current_user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/api/{id}", response_model=schemas.TrainingRead)
@is_recruiter
async def update_training(
    id: int,
    t: schemas.TrainingUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    """API: Actualizar capacitación (RN-01, RN-02, RN-13)."""
    _require_th_or_admin(current_user)
    try:
        updated = await service.update_training(db, id, t, current_user=current_user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not updated:
        raise HTTPException(404, "Capacitación no encontrada")
    return updated


@router.post("/api/{id}/publish", response_model=schemas.TrainingRead)
@is_recruiter
async def publish_training_api(
    id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    """Publica capacitación en Borrador (valida RN-02 / CA-01)."""
    _require_th_or_admin(current_user)
    try:
        return await service.publish_training(db, id, user_id=current_user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/{id}/cancel", response_model=schemas.TrainingRead)
@is_recruiter
async def cancel_training_api(
    id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: Optional[schemas.StatusTransitionPayload] = None,
    current_user: User = Depends(get_current_user),
):
    _require_th_or_admin(current_user)
    try:
        return await service.cancel_training(db, id, reason=(payload.reason if payload else None), user_id=current_user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/{id}/duplicate", response_model=schemas.TrainingRead)
@is_recruiter
async def duplicate_training_api(
    id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    _require_th_or_admin(current_user)
    try:
        return await service.duplicate_training(db, id, user_id=current_user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/{id}/close")
@is_recruiter
async def close_training_api(
    id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    """Cierra la capacitación, calcula resultados, genera compromisos de réplica y envía N-06."""
    _require_th_or_admin(current_user)
    try:
        return await service.close_training(db, id, current_user=current_user)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/api/{id}", status_code=204)
@is_recruiter
async def delete_training(
    id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    _require_th_or_admin(current_user)
    try:
        if not await service.delete_training(db, id, current_user=current_user):
            raise HTTPException(404, "Capacitación no encontrada")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return None


# --- API ENROLLMENTS & INVITATIONS ---

@router.post("/api/{id}/enroll", response_model=schemas.EnrollmentRead)
@is_recruiter
async def enroll_employee(
    id: int,
    data: schemas.EnrollmentCreate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    """API: Inscribir empleado (respeta cupo/lista de espera y envía N-01 + .ics)."""
    _require_th_or_admin(current_user)
    base_url = str(request.base_url).rstrip("/")
    try:
        enrollment = await service.enroll_employee(
            db, id, data.employee_id, base_url=base_url, user_id=current_user.id
        )
        emp = await db.get(Employee, enrollment.employee_id)
        return {
            "id": enrollment.id,
            "training_id": enrollment.training_id,
            "employee_id": enrollment.employee_id,
            "employee_name": emp.full_name if emp else "...",
            "status": enrollment.status,
            "waitlist_position": enrollment.waitlist_position,
            "attendance_pct": enrollment.attendance_pct,
            "knowledge_score": enrollment.knowledge_score,
            "result": enrollment.result,
            "certificate_file": enrollment.certificate_file,
        }
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/{id}/enroll/bulk")
@is_recruiter
async def bulk_enroll_api(
    id: int,
    payload: schemas.BulkEnrollPayload,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    _require_th_or_admin(current_user)
    try:
        return await service.bulk_enroll(
            db, id, payload, base_url=str(request.base_url).rstrip("/"), user_id=current_user.id
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/{id}/enroll/excel")
@is_recruiter
async def bulk_enroll_excel_api(
    id: int,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    _require_th_or_admin(current_user)
    try:
        content = await file.read()
        return await service.bulk_enroll_from_excel(
            db, id, content, base_url=str(request.base_url).rstrip("/"), user_id=current_user.id
        )
    except Exception as e:
        raise HTTPException(400, str(e))


@router.post("/api/{id}/request-enroll", response_model=schemas.EnrollmentRead)
@is_authenticated
async def request_enroll_api(
    id: int,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    """RF-10: Colaborador solicita su inscripción."""
    if not current_user.employee_id:
        raise HTTPException(400, "Tu usuario no tiene un colaborador vinculado.")
    try:
        enrollment = await service.enroll_employee(
            db,
            id,
            current_user.employee_id,
            request_approval=True,
            base_url=str(request.base_url).rstrip("/"),
            user_id=current_user.id,
        )
        emp = await db.get(Employee, enrollment.employee_id)
        return {
            "id": enrollment.id,
            "training_id": enrollment.training_id,
            "employee_id": enrollment.employee_id,
            "employee_name": emp.full_name if emp else "...",
            "status": enrollment.status,
            "waitlist_position": enrollment.waitlist_position,
            "attendance_pct": enrollment.attendance_pct,
            "knowledge_score": enrollment.knowledge_score,
            "result": enrollment.result,
            "certificate_file": enrollment.certificate_file,
        }
    except ValueError as e:
        raise HTTPException(400, str(e))



@router.post("/api/enrollments/{enrollment_id}/approve")
@is_recruiter
async def approve_enrollment_api(
    enrollment_id: int,
    payload: schemas.ReplicaApprovalPayload,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    """RF-10: Jefe de área o TH aprueba/rechaza solicitud de inscripción."""
    if current_user.role == UserRole.MANAGER:
        enroll = await db.get(TrainingEnrollment, enrollment_id)
        if not enroll:
            raise HTTPException(404, "Inscripción no encontrada")
        emp = (
            await db.execute(
                select(Employee).options(selectinload(Employee.position_obj)).where(Employee.id == enroll.employee_id)
            )
        ).scalar_one_or_none()
        allowed = await get_manager_area_ids(db, current_user)
        if not emp or not emp.position_obj or emp.position_obj.area_id not in allowed:
            raise RolePermissionError("Solo puedes aprobar inscripciones de tu área.")
    try:
        updated = await service.approve_enrollment_request(
            db, enrollment_id, payload.approved, current_user, base_url=str(request.base_url).rstrip("/")
        )
        return {"id": updated.id, "status": updated.status.value}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/enrollments/{enrollment_id}/withdraw")
@is_authenticated
async def withdraw_enrollment_api(
    enrollment_id: int,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    """RN-12: Da de baja antes del inicio y promueve lista de espera."""
    enroll = await db.get(TrainingEnrollment, enrollment_id)
    if not enroll:
        raise HTTPException(404, "Inscripción no encontrada")
    if current_user.role not in (UserRole.ADMIN, UserRole.TH) and current_user.employee_id != enroll.employee_id:
        raise RolePermissionError("No puedes dar de baja a otro colaborador.")
    try:
        updated = await service.withdraw_enrollment(
            db, enrollment_id, user_id=current_user.id, base_url=str(request.base_url).rstrip("/")
        )
        return {"id": updated.id, "status": updated.status.value}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/api/enrollments/{enrollment_id}/score")
@is_recruiter
async def update_enrollment_score_api(
    enrollment_id: int,
    data: schemas.EnrollmentScoreUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    _require_th_or_admin(current_user)
    try:
        updated = await service.update_enrollment_score(db, enrollment_id, data, current_user=current_user)
        return {"id": updated.id, "knowledge_score": updated.knowledge_score}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/{id}/invite")
@is_recruiter
async def send_invitations_api(
    id: int,
    payload: schemas.InvitationPayload,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    background_tasks: BackgroundTasks,
):
    """API: Enviar invitaciones masivas."""
    count = await service.send_mass_invitations(
        db, id, payload, request, background_tasks, tenant_db_factory()
    )
    return {"message": f"Se han encolado {count} invitaciones."}


@router.post("/api/{id}/remind_all")
@is_recruiter
async def remind_all_api(id: int, background_tasks: BackgroundTasks):
    """API: Enviar recordatorios masivos (Background Task)."""
    await service.send_reminder_to_enrolled(
        background_tasks, tenant_db_factory(), id
    )
    return {
        "message": "El envío de recordatorios se ha iniciado en segundo plano."
    }


# --- PUBLIC RESPONSE ENDPOINTS (RF-12) ---

@router.get("/public/respond/{token}", response_class=HTMLResponse)
async def public_respond_view(
    token: str, request: Request, db: Annotated[AsyncSession, Depends(get_db)]
):
    training = await service.get_training_by_token(db, token)
    if not training:
        return templates.TemplateResponse(
            request=request,
            name="404.html",
            context={"request": request, "settings": settings},
            status_code=404,
        )
    return templates.TemplateResponse(
        request=request,
        name="trainings/public_respond.html",
        context={"request": request, "training": training, "token": token, "settings": settings},
    )


@router.post("/public/respond/{token}")
async def public_respond_api(
    token: str,
    data: schemas.PublicResponse,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    training = await service.process_public_response(
        db, token, data.action, base_url=str(request.base_url).rstrip("/")
    )
    if not training:
        raise HTTPException(404, "Invitación no válida")
    return {"message": "Respuesta registrada correctamente"}


# --- SESSION & ATTENDANCE ENDPOINTS ---

@router.post("/api/{id}/sessions", response_model=schemas.SessionRead)
@is_recruiter
async def create_session_api(
    id: int,
    data: schemas.SessionCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    _require_th_or_admin(current_user)
    try:
        return await service.create_session(db, id, data, current_user=current_user)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/{id}/sessions/generate")
@is_recruiter
async def generate_sessions_api(
    id: int,
    gen: schemas.SessionGenerator,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    _require_th_or_admin(current_user)
    try:
        count = await service.generate_sessions(db, id, gen, current_user=current_user)
        return {"message": f"{count} sesiones generadas"}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/api/sessions/{session_id}", response_model=schemas.SessionRead)
@is_recruiter
async def update_session_api(
    session_id: int,
    data: schemas.SessionUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    _require_th_or_admin(current_user)
    try:
        updated = await service.update_session(db, session_id, data, current_user=current_user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not updated:
        raise HTTPException(404, "Sesión no encontrada")
    return updated


@router.delete("/api/sessions/{session_id}", status_code=204)
@is_recruiter
async def delete_session_api(
    session_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    _require_th_or_admin(current_user)
    try:
        if not await service.delete_session(db, session_id, current_user=current_user):
            raise HTTPException(404, "Sesión no encontrada")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return None


@router.get("/api/sessions/{session_id}/attendance")
@is_authenticated
async def get_attendance_api(
    session_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    """API: Obtener lista de asistencia."""
    sess = await db.get(TrainingSession, session_id)
    if not sess:
        raise HTTPException(404, "Sesión no encontrada")
    training = await db.get(Training, sess.training_id)
    await _ensure_training_view_access(db, current_user, training)
    return await service.get_session_attendance(db, session_id)


@router.post("/api/sessions/{session_id}/attendance")
@is_authenticated
async def save_attendance_api(
    session_id: int,
    data: schemas.AttendanceList,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    """API: Guardar asistencia (TH, Admin o Facilitador interno)."""
    sess = await db.get(TrainingSession, session_id)
    if not sess:
        raise HTTPException(404, "Sesión no encontrada")
    training = await db.get(Training, sess.training_id)
    if current_user.role not in (UserRole.ADMIN, UserRole.TH) and not is_facilitator_of_training(current_user, training):
        raise RolePermissionError("Solo TH, Admin o el Facilitador interno pueden registrar asistencia.")
    try:
        await service.save_attendance(db, session_id, data, current_user=current_user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"message": "Asistencia guardada"}


@router.post("/api/sessions/{session_id}/attendance/import")
@is_authenticated
async def import_attendance_api(
    session_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
    method: str = Form("excel"),
    current_user: User = Depends(get_current_user),
):
    """RF-13 / RF-16: Importa asistencia desde Excel o Teams/Zoom."""
    sess = await db.get(TrainingSession, session_id)
    if not sess:
        raise HTTPException(404, "Sesión no encontrada")
    training = await db.get(Training, sess.training_id)
    if current_user.role not in (UserRole.ADMIN, UserRole.TH) and not is_facilitator_of_training(current_user, training):
        raise RolePermissionError("Solo TH, Admin o el Facilitador interno pueden importar asistencia.")
    try:
        content = await file.read()
        return await service.import_attendance_file(
            db, session_id, content, filename=(file.filename or "attendance.xlsx"), method=method, current_user=current_user
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/qr/checkin")
@is_authenticated
async def qr_checkin_api(
    payload: schemas.QRCheckinPayload,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    """RF-13 / CA-06: Marca asistencia por QR dentro de ventana configurable y para inscritos."""
    if not current_user.employee_id:
        raise HTTPException(400, "Tu usuario no está vinculado a un colaborador.")
    try:
        return await service.checkin_qr(db, payload.token, current_user.employee_id, user_id=current_user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/api/sessions/{session_id}/status")
@is_recruiter
async def toggle_status_api(
    session_id: int,
    status: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    _require_th_or_admin(current_user)
    await service.toggle_session_status(db, session_id, status)
    return {"message": "Estado actualizado"}



# --- EVIDENCIAS, MATERIALES, CERTIFICADOS Y ENCUESTA ---

@router.get("/api/{id}/evidences", response_model=List[schemas.EvidenceRead])
@is_authenticated
async def list_training_evidences_api(
    id: int, db: Annotated[AsyncSession, Depends(get_db)]
):
    return await service.get_evidences(db, "training", id)


@router.post("/api/{id}/evidences", response_model=schemas.EvidenceRead)
@is_authenticated
async def upload_training_evidence_api(
    id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    evidence_type: str = Form("material"),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    training = await db.get(Training, id)
    if not training:
        raise HTTPException(404, "Capacitación no encontrada")
    if current_user.role not in (UserRole.ADMIN, UserRole.TH) and not is_facilitator_of_training(current_user, training):
        raise RolePermissionError("Solo TH, Admin o el Facilitador interno pueden cargar evidencias/materiales.")
    return await service.upload_evidence_file(db, "training", id, file, evidence_type, user_id=current_user.id)


@router.post("/api/{id}/evidences/link", response_model=schemas.EvidenceRead)
@is_authenticated
async def add_training_evidence_link_api(
    id: int,
    payload: schemas.EvidenceLinkCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    training = await db.get(Training, id)
    if not training:
        raise HTTPException(404, "Capacitación no encontrada")
    if current_user.role not in (UserRole.ADMIN, UserRole.TH) and not is_facilitator_of_training(current_user, training):
        raise RolePermissionError("Solo TH, Admin o el Facilitador interno pueden adjuntar enlaces.")
    return await service.add_evidence_link(db, "training", id, payload, user_id=current_user.id)


@router.delete("/api/evidences/{evidence_id}", status_code=204)
@is_recruiter
async def delete_evidence_api(
    evidence_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    _require_th_or_admin(current_user)
    if not await service.delete_evidence(db, evidence_id, user_id=current_user.id):
        raise HTTPException(404, "Evidencia no encontrada")
    return None


@router.get("/api/evidences/download/{entity_type}/{filename}")
@is_authenticated
async def download_protected_evidence(
    entity_type: str,
    filename: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    """RNF-07: Archivos adjuntos protegidos y verificados en la BD del tenant actual."""
    if entity_type not in ("training", "enrollment", "commitment"):
        raise HTTPException(400, "Tipo de entidad inválido")
    safe_name = os.path.basename(filename)
    expected_url = f"/trainings/api/evidences/download/{entity_type}/{safe_name}"

    ev_id = await db.scalar(
        select(TrainingEvidence.id).where(TrainingEvidence.file_url == expected_url)
    )
    if not ev_id and entity_type == "enrollment":
        ev_id = await db.scalar(
            select(TrainingEnrollment.id).where(
                (TrainingEnrollment.certificate_file == safe_name)
                | (TrainingEnrollment.certificate_file.like(f"%/{safe_name}"))
            )
        )
    if not ev_id:
        raise HTTPException(404, "Archivo no encontrado")

    abs_path = os.path.join(ensure_upload_dir(entity_type), safe_name)
    if not os.path.exists(abs_path):
        legacy_path = os.path.join(legacy_upload_dir(entity_type), safe_name)
        if os.path.exists(legacy_path):
            abs_path = legacy_path
        else:
            raise HTTPException(404, "Archivo no encontrado")
    return FileResponse(abs_path, filename=safe_name)


@router.get("/api/templates/enroll-excel")
@is_recruiter
async def download_enroll_excel_template():
    """Descarga plantilla Excel de ejemplo para carga masiva de inscritos (RF-08)."""
    import io
    import pandas as pd

    df = pd.DataFrame([{"documento": "1234567", "correo": "colaborador@institucion.edu"}])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Inscritos")
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=plantilla_inscripcion_masiva.xlsx"},
    )


@router.get("/api/templates/attendance-excel")
@is_authenticated
async def download_attendance_excel_template():
    """Descarga plantilla Excel de ejemplo para carga de asistencia (RF-13)."""
    import io
    import pandas as pd

    df = pd.DataFrame([
        {"documento": "1234567", "correo": "colaborador@institucion.edu", "estado": "Presente"},
        {"documento": "7654321", "correo": "otro@institucion.edu", "estado": "Tardanza"},
    ])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Asistencia")
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=plantilla_asistencia.xlsx"},
    )


@router.post("/api/enrollments/{enrollment_id}/certificate")
@is_recruiter
async def upload_provider_certificate_api(
    enrollment_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """RF-19: Cargar certificado de proveedor para capacitación externa."""
    _require_th_or_admin(current_user)
    try:
        updated = await service.upload_provider_certificate(db, enrollment_id, file, user_id=current_user.id)
        return {"id": updated.id, "certificate_file": updated.certificate_file}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/api/enrollments/{enrollment_id}/certificate-pdf")
@is_authenticated
async def download_certificate_pdf_api(
    enrollment_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    """RF-20: Genera y descarga certificado PDF automático para internas y réplicas aprobadas."""
    enroll = await db.get(TrainingEnrollment, enrollment_id)
    if not enroll:
        raise HTTPException(404, "Inscripción no encontrada")
    if current_user.role not in (UserRole.ADMIN, UserRole.TH, UserRole.MANAGER) and current_user.employee_id != enroll.employee_id:
        raise RolePermissionError("No tienes permiso para descargar este certificado.")
    try:
        pdf_io = await service.generate_certificate_pdf(db, enrollment_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return StreamingResponse(
        pdf_io,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=certificado_{enrollment_id}.pdf"},
    )


@router.post("/api/enrollments/{enrollment_id}/survey", response_model=schemas.SurveyRead)
@is_authenticated
async def submit_survey_api(
    enrollment_id: int,
    payload: schemas.SurveyCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    """RF-21: Encuesta de satisfacción al cierre."""
    if not current_user.employee_id:
        raise HTTPException(400, "Tu usuario no está vinculado a un colaborador.")
    try:
        return await service.submit_survey(db, enrollment_id, current_user.employee_id, payload)
    except ValueError as e:
        raise HTTPException(400, str(e))



# --- COMPROMISOS DE RÉPLICA (RF-23..RF-29) ---

@router.get("/api/replicas/my")
@is_authenticated
async def my_replicas_api(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    if not current_user.employee_id:
        return []
    items = await replicas_service.get_employee_commitments(db, current_user.employee_id)
    return [
        {
            "id": x["commitment"].id,
            "source_training_id": x["commitment"].source_training_id,
            "source_training_name": x["commitment"].source_training.name if x["commitment"].source_training else "-",
            "replica_training_id": x["commitment"].replica_training_id,
            "status": x["commitment"].status,
            "due_date": x["commitment"].due_date.isoformat(),
            "effective_due_date": x["effective_due_date"].isoformat(),
            "days_remaining": x["days_remaining"],
            "traffic_light": x["traffic_light"],
            "proposed_topic": x["commitment"].proposed_topic,
            "proposed_date": x["commitment"].proposed_date.isoformat() if x["commitment"].proposed_date else None,
        }
        for x in items
    ]


@router.get("/api/replicas")
@is_recruiter
async def list_replicas_api(
    db: Annotated[AsyncSession, Depends(get_db)],
    status: Optional[str] = "all",
    traffic_light: Optional[str] = "all",
    area_id: Optional[int] = None,
    q: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    allowed = await _scoped_area_ids(db, current_user)
    items = await replicas_service.get_replicas_inbox(db, status, traffic_light, area_id, allowed_area_ids=allowed, search=q)
    return [
        {
            "id": x["commitment"].id,
            "employee_id": x["commitment"].employee_id,
            "employee_name": x["commitment"].employee.full_name if x["commitment"].employee else "-",
            "area_name": x["area_name"],
            "source_training_id": x["commitment"].source_training_id,
            "source_training_name": x["commitment"].source_training.name if x["commitment"].source_training else "-",
            "replica_training_id": x["commitment"].replica_training_id,
            "status": x["commitment"].status,
            "due_date": x["commitment"].due_date.isoformat(),
            "effective_due_date": x["effective_due_date"].isoformat(),
            "days_remaining": x["days_remaining"],
            "traffic_light": x["traffic_light"],
            "proposed_topic": x["commitment"].proposed_topic,
            "proposed_date": x["commitment"].proposed_date.isoformat() if x["commitment"].proposed_date else None,
        }
        for x in items
    ]


@router.post("/api/replicas/{commitment_id}/propose", response_model=schemas.ReplicaCommitmentRead)
@is_authenticated
async def propose_replica_api(
    commitment_id: int,
    payload: schemas.ReplicaProposalCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    is_th = current_user.role in (UserRole.ADMIN, UserRole.TH)
    if not is_th and not current_user.employee_id:
        raise HTTPException(400, "Tu usuario no está vinculado a un colaborador.")
    try:
        return await replicas_service.propose_replica(
            db, commitment_id, current_user.employee_id or 0, payload, user_id=current_user.id, is_th_or_admin=is_th
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/replicas/{commitment_id}/approve", response_model=schemas.ReplicaCommitmentRead)
@is_recruiter
async def approve_replica_api(
    commitment_id: int,
    payload: schemas.ReplicaApprovalPayload,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    try:
        return await replicas_service.approve_or_reject_replica(
            db, commitment_id, payload, current_user, base_url=str(request.base_url).rstrip("/")
        )
    except PermissionError as e:
        raise RolePermissionError(str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/replicas/{commitment_id}/extend", response_model=schemas.ReplicaCommitmentRead)
@is_recruiter
async def extend_replica_api(
    commitment_id: int,
    payload: schemas.ReplicaExtensionPayload,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    _require_th_or_admin(current_user)
    try:
        return await replicas_service.extend_replica_commitment(db, commitment_id, payload, user_id=current_user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/replicas/{commitment_id}/evidence", response_model=schemas.EvidenceRead)
@is_authenticated
async def upload_replica_evidence_api(
    commitment_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    c = await db.get(ReplicaCommitment, commitment_id)
    if not c:
        raise HTTPException(404, "Compromiso no encontrado")
    if current_user.role not in (UserRole.ADMIN, UserRole.TH) and current_user.employee_id != c.employee_id:
        raise RolePermissionError("No puedes subir evidencia a un compromiso ajeno.")
    return await service.upload_evidence_file(db, "commitment", commitment_id, file, "evidencia_replica", user_id=current_user.id)


# --- CONFIGURACIÓN, PLANTILLAS, SINCRONIZACIÓN Y AUTOMATIZACIÓN ---

@router.get("/api/parameters", response_model=List[schemas.ParameterRead])
@is_recruiter
async def list_parameters_api(db: Annotated[AsyncSession, Depends(get_db)]):
    return await parameters_service.get_all_parameters(db)


@router.put("/api/parameters/{key}", response_model=schemas.ParameterRead)
@is_admin
async def update_parameter_api(
    key: str,
    payload: schemas.ParameterUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    updated = await parameters_service.update_parameter(db, key, payload.value, user_id=current_user.id)
    if not updated:
        raise HTTPException(404, "Parámetro no encontrado")
    return updated


@router.get("/api/templates", response_model=List[schemas.EmailTemplateRead])
@is_recruiter
async def list_templates_api(db: Annotated[AsyncSession, Depends(get_db)]):
    return await parameters_service.get_all_templates(db)


@router.put("/api/templates/{event_code}", response_model=schemas.EmailTemplateRead)
@is_admin
async def update_template_api(
    event_code: str,
    payload: schemas.EmailTemplateUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    updated = await parameters_service.update_template(
        db, event_code, payload.subject_template, payload.body_template, payload.is_active, user_id=current_user.id
    )
    if not updated:
        raise HTTPException(404, "Plantilla no encontrada")
    return updated


@router.post("/api/sync-personnel")
@is_recruiter
async def sync_personnel_api(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    _require_th_or_admin(current_user)
    return await service.sync_personnel_and_commitments(db, user_id=current_user.id)


@router.post("/api/run-daily-automation")
@is_recruiter
async def run_daily_automation_api(
    db: Annotated[AsyncSession, Depends(get_db)],
    include_weekly: Optional[bool] = None,
    current_user: User = Depends(get_current_user),
):
    _require_th_or_admin(current_user)
    return await notifications_service.run_daily_training_automation(db, include_weekly=include_weekly)


# --- TABLERO KPIs Y REPORTES EXPORTABLES (RF-35, RF-36) ---

@router.get("/api/dashboard")
@is_recruiter
async def dashboard_api(
    db: Annotated[AsyncSession, Depends(get_db)],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    area_id: Optional[int] = None,
    training_type: Optional[str] = "all",
    modality: Optional[str] = "all",
    current_user: User = Depends(get_current_user),
):
    s_date = date.fromisoformat(start_date) if start_date else None
    e_date = date.fromisoformat(end_date) if end_date else None
    allowed = await _scoped_area_ids(db, current_user)
    return await analytics_service.get_dashboard_data(
        db, s_date, e_date, area_id, training_type, modality, allowed_area_ids=allowed
    )


@router.get("/api/reports/{report_type}/excel")
@is_recruiter
async def export_report_excel_api(
    report_type: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    training_id: Optional[int] = None,
    employee_id: Optional[int] = None,
    area_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
):
    allowed = await _scoped_area_ids(db, current_user)
    try:
        buf = await analytics_service.export_report_excel(
            db, report_type, training_id, employee_id, area_id, allowed_area_ids=allowed
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=reporte_{report_type}_{date.today().isoformat()}.xlsx"},
    )


@router.get("/api/reports/{report_type}/pdf")
@is_recruiter
async def export_report_pdf_api(
    report_type: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    training_id: Optional[int] = None,
    employee_id: Optional[int] = None,
    area_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
):
    allowed = await _scoped_area_ids(db, current_user)
    try:
        buf = await analytics_service.export_report_pdf(
            db, report_type, training_id, employee_id, area_id, allowed_area_ids=allowed
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=reporte_{report_type}_{date.today().isoformat()}.pdf"},
    )


