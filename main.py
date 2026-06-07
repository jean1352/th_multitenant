import sys
import logging
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import HTTPException
from contextlib import asynccontextmanager

# --- CONFIGURACIÓN DE LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True 
)
logger = logging.getLogger(__name__)

from app.core.config import settings
from app.core.database import engine, Base, AsyncSessionLocal
from app.core.exceptions import RolePermissionError
from app.core.middleware import TenantMiddleware
from app.modules.auth.dependencies import NeedsLoginException

# Importar modelos
import app.modules.auth.models
import app.modules.organization.models 
import app.modules.recruitment.models
import app.modules.employees.models
import app.modules.trainings.models
import app.modules.notifications.models
import app.modules.calendar.models
import app.modules.benefits.models
import app.modules.disciplinary.models
import app.modules.dietary.models
import app.modules.scheduler.models
import app.modules.tenants.models

# Importar Routers
from app.modules.auth.router import router as auth_router
from app.modules.recruitment.router import router as recruitment_router
from app.modules.organization.router import router as organization_router
from app.modules.employees.router import router as employees_router
from app.modules.trainings.router import router as trainings_router
from app.modules.notifications.router import router as notifications_router
from app.modules.calendar.router import router as calendar_router
from app.modules.benefits.router import router as benefits_router
from app.modules.disciplinary.router import router as disciplinary_router
from app.modules.dietary.router import router as dietary_router
from app.modules.scheduler.router import router as scheduler_router
from app.modules.portal.router import router as portal_router
from app.modules.tenants.router import router as tenants_router
from app.modules.tenants.admin_router import router as admin_router

# Importar Servicio Scheduler
from app.modules.scheduler.service import start_scheduler, sync_jobs_from_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Iniciando aplicación y servicios...")
    # NOTA: En multi-tenant, Base.metadata.create_all creará las tablas en el esquema 'public' 
    # (o donde esté configurado por defecto). Las tablas del tenant se crearán al aprovisionar.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    start_scheduler()
    logger.info("✅ Scheduler iniciado.")
    
    async with AsyncSessionLocal() as db:
        await sync_jobs_from_db(db)
        from app.modules.auth.service import ensure_superadmin
        await ensure_superadmin(db)
        
    yield
    logger.info("🛑 Apagando aplicación...")

app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)

# Middleware de Tenant (Debe ir temprano para setear el contexto)
app.add_middleware(TenantMiddleware)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

from app.core.templates import templates

# --- EXCEPTION HANDLERS ---

@app.exception_handler(404)
async def not_found_exception_handler(request: Request, exc: HTTPException):
    return templates.TemplateResponse(request=request, name="404.html", context= {"request": request, "settings": settings}, status_code=404)

@app.exception_handler(RolePermissionError)
async def permission_exception_handler(request: Request, exc: RolePermissionError):
    accept = request.headers.get("accept", "")
    x_requested_with = request.headers.get("x-requested-with", "")
    is_ajax = "application/json" in accept or x_requested_with == "XMLHttpRequest"

    if is_ajax:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": exc.message}
        )
    else:
        return templates.TemplateResponse(request=request, name="403.html", context= 
            {"request": request, "message": exc.message, "settings": settings}, 
            status_code=403
        )

@app.exception_handler(NeedsLoginException)
async def auth_exception_handler(request: Request, exc: NeedsLoginException):
    # Redirige a la ruta de login de tu aplicación
    return RedirectResponse(url="/login", status_code=303)

# --- ROUTERS ---
app.include_router(auth_router)
app.include_router(recruitment_router)
app.include_router(organization_router)
app.include_router(employees_router)
app.include_router(trainings_router)
app.include_router(notifications_router)
app.include_router(calendar_router)
app.include_router(benefits_router)
app.include_router(disciplinary_router)
app.include_router(dietary_router)
app.include_router(scheduler_router)
app.include_router(portal_router)
app.include_router(tenants_router)
app.include_router(admin_router)

@app.get("/")
async def root():
    return RedirectResponse(url="/login")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, log_config=None)
