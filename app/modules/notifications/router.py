"""
Router para el módulo de Notificaciones.
Define las vistas para consultar el historial de correos y herramientas de prueba.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, BackgroundTasks
from fastapi.responses import HTMLResponse
from app.core.templates import templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.notifications import service, schemas
from app.modules.auth.dependencies import is_admin
from app.core.config import settings

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/", response_class=HTMLResponse)
async def view_logs(
    request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: User = Depends(get_current_user)
):
    """Vista de historial de notificaciones enviadas."""
    logs = await service.get_logs(db)
    return templates.TemplateResponse(request=request, name="notifications/logs.html", context= {"request": request, "logs": logs, "settings": settings, "current_user": current_user}
    )

@router.get("/tester", response_class=HTMLResponse)
@is_admin
async def view_tester(request: Request, current_user: User = Depends(get_current_user)):
    """Vista para probar el envío de correos."""
    return templates.TemplateResponse(request=request, name="notifications/tester.html", context= {"request": request, "settings": settings, "current_user": current_user}
    )

@router.post("/api/test-send")
@is_admin
async def send_test_email_api(
    data: schemas.TestEmailRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    background_tasks: BackgroundTasks
):
    """API para enviar correos de prueba."""
    await service.send_test_email(db, data, background_tasks)
    return {"message": "Correo de prueba encolado correctamente."}