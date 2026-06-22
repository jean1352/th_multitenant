"""
Router para el módulo de Capacitaciones.
Define los endpoints de la API y las vistas HTML.
"""

from typing import Annotated, Optional, List

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
)
from fastapi.responses import HTMLResponse
from app.core.templates import templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.auth.dependencies import is_admin, is_authenticated, is_recruiter, is_manager
from app.modules.employees.models import Employee
from app.modules.organization.models import Area, Sede
from app.modules.trainings import schemas, service
from app.core.config import settings

router = APIRouter(prefix="/trainings", tags=["trainings"])


# --- FILTROS JINJA ---

STATUS_MAP = {
    "planned": "Planificado",
    "in_progress": "En Curso",
    "completed": "Finalizado",
    "cancelled": "Cancelado",
    "enrolled": "Inscrito",
    "invited": "Invitado",
    "attended": "Asistió",
    "no_show": "No Asistió",
    "failed": "Reprobado",
    "declined": "Rechazado",
}


def translate_status(value):
    """Filtro Jinja para traducir estados."""
    return STATUS_MAP.get(value, value)


templates.env.filters["translate_status"] = translate_status


# --- VISTAS ---

@router.get("/", response_class=HTMLResponse)
@is_recruiter
async def list_trainings(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(1, ge=1),
    q: Optional[str] = None,
    status: Optional[str] = "all",
    current_user: User = Depends(get_current_user),
):
    """Vista principal: Listado de capacitaciones."""
    pagination = await service.get_trainings_paginated(db, page, 9, q, status)
    
    # Convertir a dicts para Jinja
    trainings_data = [
        schemas.TrainingRead.model_validate(t).model_dump(mode="json")
        for t in pagination["data"]
    ]
    pagination["data"] = trainings_data

    return templates.TemplateResponse(request=request, name="trainings/index.html", context=
        {
            "request": request,
            "pagination": pagination,
            "filters": {"q": q, "status": status},
            "current_user": current_user,
            "settings": settings
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
    return templates.TemplateResponse(request=request, name="trainings/providers.html", context=
        {"request": request, "providers": providers_data, "current_user": current_user, "settings": settings}
    )


@router.get("/{id}", response_class=HTMLResponse)
@is_recruiter
async def detail_training(
    id: int,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(1, ge=1),
    q: Optional[str] = None,
    area_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """Vista detalle: Información, inscritos y sesiones."""
    area_id_int = int(area_id) if area_id and area_id.strip().isdigit() else None

    training = await service.get_training_detail(db, id)
    if not training:
        return templates.TemplateResponse(request=request, name="404.html", context= {"request": request, "current_user": current_user, "settings": settings}, status_code=404
        )

    enrollments_pag = await service.get_enrollments_paginated(
        db, id, page, 10, q, area_id_int
    )
    employees = []
    areas = (await db.execute(select(Area))).scalars().all()
    sedes = (await db.execute(select(Sede))).scalars().all()
    
    sessions_data = [
        schemas.SessionRead.model_validate(s).model_dump(mode="json")
        for s in training.sessions
    ]

    return templates.TemplateResponse(request=request, name="trainings/detail.html", context=
        {
            "request": request,
            "training": training,
            "enrollments": enrollments_pag,
            "employees": employees,
            "areas": areas,
            "sedes": sedes,
            "sessions": sessions_data,
            "filters": {"q": q, "area_id": area_id_int},
            "current_user": current_user,
            "settings": settings
        },
    )


# --- API PROVIDERS ---

@router.get("/api/providers", response_model=List[schemas.ProviderRead])
@is_recruiter
async def get_providers_api(
    db: Annotated[AsyncSession, Depends(get_db)],
    active_only: bool = False
):
    return await service.get_providers(db, active_only)

@router.post("/api/providers", response_model=schemas.ProviderRead)
@is_recruiter
async def create_provider_api(
    data: schemas.ProviderCreate, db: Annotated[AsyncSession, Depends(get_db)]
):
    try:
        return await service.create_provider(db, data)
    except ValueError as e:
        raise HTTPException(400, str(e))

@router.put("/api/providers/{id}", response_model=schemas.ProviderRead)
@is_recruiter
async def update_provider_api(
    id: int, data: schemas.ProviderUpdate, db: Annotated[AsyncSession, Depends(get_db)]
):
    updated = await service.update_provider(db, id, data)
    if not updated: raise HTTPException(404, "Proveedor no encontrado")
    return updated

@router.delete("/api/providers/{id}", status_code=204)
@is_recruiter
async def delete_provider_api(
    id: int, db: Annotated[AsyncSession, Depends(get_db)]
):
    try:
        if not await service.delete_provider(db, id):
            raise HTTPException(404, "Proveedor no encontrado")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return None


# --- API TRAININGS ---

@router.post("/api", response_model=schemas.TrainingRead)
@is_recruiter
async def create_training(
    t: schemas.TrainingCreate, db: Annotated[AsyncSession, Depends(get_db)]
):
    """API: Crear nueva capacitación."""
    return await service.create_training(db, t)


@router.put("/api/{id}", response_model=schemas.TrainingRead)
@is_recruiter
async def update_training(
    id: int,
    t: schemas.TrainingUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """API: Actualizar capacitación."""
    updated = await service.update_training(db, id, t)
    if not updated:
        raise HTTPException(404, "Capacitación no encontrada")
    return updated


@router.delete("/api/{id}", status_code=204)
@is_recruiter
async def delete_training(
    id: int, db: Annotated[AsyncSession, Depends(get_db)]
):
    """API: Eliminar capacitación."""
    if not await service.delete_training(db, id):
        raise HTTPException(404, "Capacitación no encontrada")
    return None


@router.post("/api/{id}/enroll", response_model=schemas.EnrollmentRead)
@is_recruiter
async def enroll_employee(
    id: int,
    data: schemas.EnrollmentCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """API: Inscribir empleado."""
    try:
        enrollment = await service.enroll_employee(db, id, data.employee_id)
        return {
            "id": enrollment.id,
            "employee_name": "...",
            "status": "enrolled",
            "knowledge_score": None,
        }
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
        db, id, payload, request, background_tasks, AsyncSessionLocal
    )
    return {"message": f"Se han encolado {count} invitaciones."}


@router.post("/api/{id}/remind_all")
@is_recruiter
async def remind_all_api(id: int, background_tasks: BackgroundTasks):
    """API: Enviar recordatorios masivos (Background Task)."""
    await service.send_reminder_to_enrolled(
        background_tasks, AsyncSessionLocal, id
    )
    return {
        "message": "El envío de recordatorios se ha iniciado en segundo plano."
    }


# --- PUBLIC RESPONSE ENDPOINTS ---

@router.get("/public/respond/{token}", response_class=HTMLResponse)
@is_recruiter
async def public_respond_view(
    token: str, request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: User = Depends(get_current_user)
):
    training = await service.get_training_by_token(db, token)
    if not training:
        return templates.TemplateResponse(request=request, name="404.html", context= {"request": request, "current_user": current_user, "settings": settings}, status_code=404
        )
    return templates.TemplateResponse(request=request, name="calendar/public_respond.html", context= 
        {"request": request, "event": training, "token": token, "is_training": True, "current_user": current_user, "settings": settings},
    )


@router.post("/public/respond/{token}")
@is_recruiter
async def public_respond_api(
    token: str,
    data: schemas.PublicResponse,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    training = await service.process_public_response(db, token, data.action)
    if not training:
        raise HTTPException(404, "Invitación no válida")
    return {"message": "Respuesta registrada correctamente"}


# --- SESSION ENDPOINTS ---

@router.post("/api/{id}/sessions/generate")
@is_recruiter
async def generate_sessions_api(
    id: int,
    gen: schemas.SessionGenerator,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """API: Generar sesiones automáticamente."""
    count = await service.generate_sessions(db, id, gen)
    return {"message": f"{count} sesiones generadas"}


@router.put(
    "/api/sessions/{session_id}", response_model=schemas.SessionRead
)
@is_recruiter
async def update_session_api(
    session_id: int,
    data: schemas.SessionUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """API: Actualizar sesión."""
    updated = await service.update_session(db, session_id, data)
    if not updated:
        raise HTTPException(404, "Sesión no encontrada")
    return updated


@router.delete("/api/sessions/{session_id}", status_code=204)
@is_recruiter
async def delete_session_api(
    session_id: int, db: Annotated[AsyncSession, Depends(get_db)]
):
    """API: Eliminar sesión."""
    if not await service.delete_session(db, session_id):
        raise HTTPException(404, "Sesión no encontrada")
    return None


@router.get("/api/sessions/{session_id}/attendance")
@is_recruiter
async def get_attendance_api(
    session_id: int, db: Annotated[AsyncSession, Depends(get_db)]
):
    """API: Obtener lista de asistencia."""
    data = await service.get_session_attendance(db, session_id)
    if data is None:
        raise HTTPException(404, "Sesión no encontrada")
    return data


@router.post("/api/sessions/{session_id}/attendance")
@is_recruiter
async def save_attendance_api(
    session_id: int,
    data: schemas.AttendanceList,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """API: Guardar asistencia."""
    if not await service.save_attendance(db, session_id, data):
        raise HTTPException(404, "Sesión no encontrada")
    return {"message": "Asistencia guardada"}


@router.put("/api/sessions/{session_id}/status")
@is_recruiter
async def toggle_status_api(
    session_id: int,
    status: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """API: Cambiar estado de sesión."""
    await service.toggle_session_status(db, session_id, status)
    return {"message": "Estado actualizado"}