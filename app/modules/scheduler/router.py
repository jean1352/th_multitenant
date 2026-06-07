from typing import Annotated
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse
from app.core.templates import templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.auth.dependencies import is_admin, is_authenticated, is_recruiter, is_manager
from app.modules.scheduler import service, schemas
from app.core.config import settings

router = APIRouter(prefix="/scheduler", tags=["scheduler"])

@router.get("/", response_class=HTMLResponse)
@is_authenticated
async def index(request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: User = Depends(get_current_user)):
    # Asegurar que existan las reglas por defecto
    await service.seed_default_rules(db)
    
    rules_orm = await service.get_rules(db)
    logs = await service.get_logs(db)
    
    # SERIALIZACIÓN: Convertir ORM a Diccionarios JSON-safe
    rules_data = [
        schemas.AutomationRuleRead.model_validate(r).model_dump(mode="json")
        for r in rules_orm
    ]
    
    return templates.TemplateResponse(request=request, name="scheduler/index.html", context=
        {"request": request, "rules": rules_data, "logs": logs, "settings": settings, "current_user": current_user}
    )

# CORRECCIÓN: Usar Pydantic Schema en lugar de Form(...)
@router.post("/api/rules/{id}/update")
@is_admin
async def update_rule_api(
    id: int,
    rule_data: schemas.RuleUpdate, # <--- FastAPI leerá el JSON aquí
    db: Annotated[AsyncSession, Depends(get_db)]
):
    # Convertimos el modelo a dict excluyendo nulos si es necesario, 
    # o pasamos el dump completo al servicio.
    await service.update_rule(db, id, rule_data.model_dump())
    return {"message": "Configuración guardada"}

@router.post("/api/rules/{id}/toggle")
@is_admin
async def toggle_rule_api(id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    active = await service.toggle_rule(db, id)
    return {"message": "Estado cambiado", "is_active": active}

@router.post("/api/rules/{id}/run")
@is_admin
async def run_rule_api(id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    await service.run_rule_now(db, id)
    return {"message": "Ejecución iniciada"}