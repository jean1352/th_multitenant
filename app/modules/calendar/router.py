"""
Router para el módulo de Calendario.
"""

from datetime import date, datetime
from typing import Annotated, List

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
)
from fastapi.responses import HTMLResponse, StreamingResponse
from app.core.templates import templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.auth.dependencies import is_admin, is_authenticated, is_recruiter, is_manager
from app.modules.calendar import schemas, service
from app.modules.organization.models import Sede, Area
from app.core.config import settings

router = APIRouter(prefix="/calendar", tags=["calendar"])


# --- VISTAS ---

@router.get("/", response_class=HTMLResponse)
@is_recruiter
async def view_calendar(request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: User = Depends(get_current_user)):
    """Vista principal del calendario."""
    event_types = await service.get_event_types(db)
    return templates.TemplateResponse(request=request, name="calendar/index.html", context= 
        {"request": request, "event_types": event_types, "settings": settings, "current_user": current_user}
    )


@router.get("/events/{id}", response_class=HTMLResponse)
@is_recruiter
async def view_event_detail(
    id: int, request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: User = Depends(get_current_user)
):
    """Vista de detalle de un evento específico."""
    event = await service.get_event_detail(db, id)
    if not event:
        return templates.TemplateResponse(request=request, name="404.html", context= {"request": request, "settings": settings, "current_user": current_user}, status_code=404)
    
    # Cargar datos para los selectores en cascada
    sedes = (await db.execute(select(Sede).order_by(Sede.name))).scalars().all()
    
    return templates.TemplateResponse(request=request, name="calendar/detail.html", context=
        {
            "request": request, 
            "event": event, 
            "sedes": sedes,
            "settings": settings,
            "current_user": current_user
        },
    )


# --- API EVENT TYPES ---

@router.get("/api/types", response_model=List[schemas.EventTypeRead])
@is_recruiter
async def get_types_api(db: Annotated[AsyncSession, Depends(get_db)], current_user: User = Depends(get_current_user)):
    return await service.get_event_types(db)

@router.post("/api/types", response_model=schemas.EventTypeRead)
@is_admin
async def create_type_api(data: schemas.EventTypeCreate, db: Annotated[AsyncSession, Depends(get_db)], current_user: User = Depends(get_current_user)):
    return await service.create_event_type(db, data)

@router.delete("/api/types/{id}", status_code=204)
@is_admin
async def delete_type_api(id: int, db: Annotated[AsyncSession, Depends(get_db)], current_user: User = Depends(get_current_user)):
    try:
        await service.delete_event_type(db, id)
    except ValueError as e:
        raise HTTPException(400, str(e))


# --- API EVENTS ---

@router.get("/api/events", response_model=List[schemas.FullCalendarEvent])
@is_recruiter
async def get_events_api(
    start: date, end: date, db: Annotated[AsyncSession, Depends(get_db)]
):
    return await service.get_all_events(db, start, end)


@router.post("/api/events", response_model=schemas.CalendarEventRead)
@is_admin
async def create_event_api(
    evt: schemas.CalendarEventCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await service.create_event(db, evt)


@router.delete("/api/events/{id}", status_code=204)
@is_admin
async def delete_event_api(
    id: int, db: Annotated[AsyncSession, Depends(get_db)]
):
    if not await service.delete_event(db, id):
        raise HTTPException(404, "Evento no encontrado")
    return None


# --- API ENROLLMENT & INVITATIONS ---

@router.post(
    "/api/events/{id}/enroll", response_model=schemas.EventEnrollmentRead
)
@is_recruiter
async def enroll_employee_api(
    id: int,
    data: schemas.EventEnrollmentCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    background_tasks: BackgroundTasks,
):
    try:
        enroll = await service.enroll_employee_to_event(
            db, id, data.employee_id, background_tasks, AsyncSessionLocal
        )
        return {
            "id": enroll.id,
            "employee_name": "...",
            "employee_area": "...",
            "status": "confirmed",
        }
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/api/enrollments/{id}", status_code=204)
@is_admin
async def delete_enrollment_api(
    id: int, db: Annotated[AsyncSession, Depends(get_db)]
):
    if not await service.remove_event_enrollment(db, id):
        raise HTTPException(404, "Inscripción no encontrada")
    return None


@router.get("/api/events/{id}/export")
@is_recruiter
async def export_event_enrollments_api(
    id: int, db: Annotated[AsyncSession, Depends(get_db)]
):
    excel_file = await service.generate_event_enrollment_report(db, id)
    if not excel_file:
        raise HTTPException(404, "Evento no encontrado")

    filename = f"asistentes_evento_{id}_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return StreamingResponse(
        excel_file,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/api/events/{id}/invite")
@is_recruiter
async def send_invitations_api(
    id: int,
    payload: schemas.InvitationPayload,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    background_tasks: BackgroundTasks,
):
    count = await service.send_mass_invitations(
        db, id, payload, request, background_tasks, AsyncSessionLocal
    )
    return {"message": f"Se han encolado {count} invitaciones."}


@router.get("/public/respond/{token}", response_class=HTMLResponse)
@is_recruiter
async def public_respond_view(
    token: str, request: Request, db: Annotated[AsyncSession, Depends(get_db)]
):
    event = await service.get_event_by_token(db, token)
    if not event:
        return templates.TemplateResponse(request=request, name="404.html", context= {"request": request, "settings": settings}, status_code=404
        )
    return templates.TemplateResponse(request=request, name="calendar/public_respond.html", context=
        {"request": request, "event": event, "token": token, "is_training": False, "settings": settings},
    )


@router.post("/public/respond/{token}")
@is_recruiter
async def public_respond_api(
    token: str,
    data: schemas.PublicResponse,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    event = await service.process_public_response(db, token, data.action)
    if not event:
        raise HTTPException(404, "Invitación no válida")
    return {"message": "Respuesta registrada correctamente"}