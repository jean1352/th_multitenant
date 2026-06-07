"""
Router para el módulo de Reclutamiento.
Define los endpoints de la API y las vistas HTML.
"""

from datetime import date, datetime
from typing import Annotated, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
)
from fastapi.responses import HTMLResponse, StreamingResponse
from app.core.templates import templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import decode_access_token
from app.modules.auth.dependencies import get_current_user, is_recruiter, is_admin, is_manager
from app.modules.auth.models import User
from app.modules.employees.models import Employee
from app.modules.organization import schemas as org_schemas
from app.modules.organization import service as org_service # Importamos servicio de org
from app.modules.organization.models import Area, Sede
from app.modules.recruitment import schemas, service
from app.core.config import settings

router = APIRouter(prefix="/recruitment", tags=["recruitment"])


# --- FILTROS JINJA ---

def format_date(value, fmt="%d/%m/%Y"):
    """Filtro Jinja para formatear fechas."""
    if not value:
        return "-"
    if isinstance(value, str):
        try:
            if "T" in value:
                dt = datetime.fromisoformat(value)
            else:
                dt = datetime.strptime(value, "%Y-%m-%d")
            return dt.strftime(fmt)
        except ValueError:
            return value
    return value.strftime(fmt)


templates.env.filters["format_date"] = format_date


async def get_current_user_id(request: Request):
    """Obtiene el ID del usuario actual desde la cookie."""
    token = request.cookies.get("access_token")
    if not token:
        return None
    clean_token = token.split(" ")[1] if " " in token else token
    payload = decode_access_token(clean_token)
    return payload.get("id") if payload else None


# --- REPORTING ENDPOINTS ---

@router.get("/api/reports/export")
@is_recruiter
async def export_report(
    db: Annotated[AsyncSession, Depends(get_db)],
    area_id: Optional[int] = None,
    status: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
):
    """Exporta reporte de vacantes a Excel."""
    excel_file = await service.generate_excel_report(
        db, area_id, status, start_date, end_date
    )
    filename = f"reporte_vacantes_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return StreamingResponse(
        excel_file,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/api/reports/pdf")
@is_recruiter
async def export_pdf_report(
    db: Annotated[AsyncSession, Depends(get_db)],
    area_id: Optional[int] = None,
    status: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
):
    """Exporta reporte ejecutivo a PDF."""
    pdf_bytes = await service.generate_pdf_report(
        db, templates, area_id, status, start_date, end_date
    )
    filename = f"reporte_gestion_{datetime.now().strftime('%Y%m%d')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# --- DASHBOARD API ---

@router.get("/api/dashboard/chart-data")
@is_recruiter
async def get_dashboard_chart_data(
    db: Annotated[AsyncSession, Depends(get_db)],
    year: int = Query(default=datetime.now().year)
):
    """API: Obtener datos para el gráfico mensual."""
    return await service.get_monthly_stats(db, year)

@router.get("/api/dashboard/stage-stats")
@is_recruiter
async def get_stage_stats_api(
    db: Annotated[AsyncSession, Depends(get_db)],
    area_id: Optional[int] = None
):
    """API: Obtener estadísticas detalladas de etapas (SLA y Cuellos de Botella) con filtro de área."""
    return await service.get_stage_performance_stats(db, area_id)


# --- VISTAS HTML (PROTEGIDAS) ---

@router.get("/dashboard", response_class=HTMLResponse)
@is_recruiter
async def dashboard_view(
    request: Request, 
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user)
):
    """Vista del Dashboard de métricas."""
    metrics = await service.get_dashboard_metrics(db)
    result_areas = await db.execute(
        select(Area).options(
            selectinload(Area.sede), selectinload(Area.positions)
        ).order_by(Area.name)
    )
    areas = [
        org_schemas.AreaRead.model_validate(a).model_dump(mode="json")
        for a in result_areas.scalars().all()
    ]
    return templates.TemplateResponse(request=request, name="dashboard/index.html", context=
        {
            "request": request, 
            "metrics": metrics, 
            "areas": areas, 
            "settings": settings,
            "current_user": current_user
        },
    )


@router.get("/vacancies", response_class=HTMLResponse)
@is_recruiter
async def list_vacancies_view(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    q: Optional[str] = None,
    status: Optional[str] = "open",
    sede_id: Optional[str] = None,
    area_id: Optional[str] = None,
    sla_status: Optional[str] = None,
    scope: str = Query("mine", regex="^(mine|all)$"),
    sort: str = Query("created_at"),
    order: str = Query("desc", regex="^(asc|desc)$"),
):
    """Vista de listado de vacantes."""
    
    sede_id_int = int(sede_id) if sede_id and sede_id.strip().isdigit() else None
    area_id_int = int(area_id) if area_id and area_id.strip().isdigit() else None
    sla_status_str = sla_status if sla_status and sla_status.strip() else None

    # Determine user ID for scope filter
    current_user_id = current_user.id if scope == "mine" else None

    pagination = await service.get_vacancies_paginated(
        db, page, 10, q, status, sede_id_int, area_id_int, sla_status_str, scope, current_user_id, sort, order
    )
    vacancies_data = [
        schemas.VacancyRead.model_validate(v).model_dump(mode="json")
        for v in pagination["items"]
    ]

    counts = await service.get_vacancy_counts(db)

    result_sedes = await db.execute(select(Sede).order_by(Sede.name))
    sedes = [
        org_schemas.SedeRead.model_validate(s).model_dump(mode="json")
        for s in result_sedes.scalars().all()
    ]

    processes = await service.get_processes(db)
    processes_data = [
        schemas.ProcessRead.model_validate(p).model_dump(mode="json")
        for p in processes
    ]

    stmt_areas = select(Area).options(selectinload(Area.sede), selectinload(Area.positions)).order_by(Area.name)
    if sede_id_int:
        stmt_areas = stmt_areas.where(Area.sede_id == sede_id_int)
        
    result_areas = await db.execute(stmt_areas)
    areas = [
        org_schemas.AreaRead.model_validate(a).model_dump(mode="json")
        for a in result_areas.scalars().all()
    ]

    hiring_reasons = await service.get_hiring_reasons(db)
    hiring_reasons_data = [
        schemas.HiringReasonRead.model_validate(r).model_dump(mode="json")
        for r in hiring_reasons
        if r.is_active # Only show active reasons for creation
    ]

    recruiters = await service.get_recruiters(db)

    filters = {
        "q": q, 
        "status": status, 
        "sede_id": sede_id_int, 
        "area_id": area_id_int, 
        "sla_status": sla_status_str,
        "scope": scope,
        "sort": sort,
        "order": order
    }

    return templates.TemplateResponse(request=request, name="recruitment/index.html", context=
        {
            "request": request,
            "vacancies": vacancies_data,
            "pagination": pagination,
            "filters": filters,
            "counts": counts,
            "sedes": sedes,
            "areas": areas,
            "processes": processes_data,
            "hiring_reasons": hiring_reasons_data,
            "settings": settings,
            "current_user": current_user,
            "recruiters": recruiters
        },
    )


@router.get("/vacancies/{vacancy_id}", response_class=HTMLResponse)
@is_recruiter
async def detail_vacancy_view(
    vacancy_id: int,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user)
):
    """Vista de detalle de vacante."""
    vacancy = await service.get_vacancy_detail(db, vacancy_id)
    if not vacancy:
        return templates.TemplateResponse(request=request, name="404.html", context= {"request": request, "settings": settings}, status_code=404
        )
    vacancy_dto = schemas.VacancyDetail.model_validate(vacancy)
    vacancy_dict = vacancy_dto.model_dump(mode="json")

    # Cargar empleados para asignación
    employees_orm = await db.execute(
        select(Employee).where(Employee.is_active == True).order_by(Employee.full_name)
    )
    employees = employees_orm.scalars().all()

    # Cargar Sedes para el modal de edición
    sedes_orm = await db.execute(select(Sede).order_by(Sede.name))
    sedes = [
        org_schemas.SedeRead.model_validate(s).model_dump(mode="json")
        for s in sedes_orm.scalars().all()
    ]

    hiring_reasons = await service.get_hiring_reasons(db)
    hiring_reasons_data = [
        schemas.HiringReasonRead.model_validate(r).model_dump(mode="json")
        for r in hiring_reasons
    ]

    recruiters = await service.get_recruiters(db)

    # Motivos de edición de etapas
    stage_edit_reasons = await service.get_stage_edit_reasons(db, active_only=True)
    edit_reasons_data = [
        schemas.StageEditReasonRead.model_validate(r).model_dump(mode="json")
        for r in stage_edit_reasons
    ]
    
    # NUEVO: Cargar Tipos de Contrato para el modal de cierre
    contract_types_orm = await org_service.get_contract_types(db, active_only=True)
    contract_types_data = [
        org_schemas.ContractTypeRead.model_validate(c).model_dump(mode="json")
        for c in contract_types_orm
    ]

    # NUEVO: Cargar Empresas para el modal de cierre
    companies_orm = await org_service.get_companies(db)
    companies_data = [
        org_schemas.CompanyRead.model_validate(c).model_dump(mode="json")
        for c in companies_orm
    ]

    return templates.TemplateResponse(request=request, name="recruitment/detail.html", context=
        {
            "request": request, 
            "vacancy": vacancy_dict,
            "employees": employees,
            "sedes": sedes,
            "hiring_reasons": hiring_reasons_data,
            "recruiters": recruiters,
            "edit_reasons": edit_reasons_data,
            "contract_types": contract_types_data,
            "companies": companies_data, # <--- Pasamos las empresas
            "current_user": current_user,
            "settings": settings
        },
    )


@router.get("/processes", response_class=HTMLResponse)
@is_recruiter
async def list_processes_view(
    request: Request, 
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user)
):
    """Vista de listado de procesos."""
    processes = await service.get_processes(db)
    processes_data = [
        schemas.ProcessRead.model_validate(p).model_dump(mode="json")
        for p in processes
    ]
    return templates.TemplateResponse(request=request, name="recruitment/processes.html", context=
        {
            "request": request, 
            "processes": processes_data, 
            "settings": settings,
            "current_user": current_user
        },
    )


@router.get("/processes/{process_id}", response_class=HTMLResponse)
@is_recruiter
async def detail_process_view(
    process_id: int,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user)
):
    """Vista de configuración de un proceso."""
    process = await service.get_process_detail(db, process_id)
    if not process:
        return templates.TemplateResponse(request=request, name="404.html", context= {"request": request, "settings": settings}, status_code=404
        )

    process_dto = schemas.ProcessRead.model_validate(process)
    process_dict = process_dto.model_dump(mode="json")

    users_orm = await service.get_users_for_assignment(db)
    users_data = []
    for u in users_orm:
        sede_name = (
            u.sede.name
            if u.sede
            else (
                u.area.sede.name if u.area and u.area.sede else "Sin Sede"
            )
        )
        users_data.append(
            {
                "id": u.id,
                "full_name": u.full_name,
                "area_name": u.area.name if u.area else "Sin Área",
                "sede_name": sede_name,
            }
        )

    return templates.TemplateResponse(request=request, name="recruitment/process_detail.html", context=
        {
            "request": request,
            "process": process_dict,
            "users": users_data,
            "settings": settings,
            "current_user": current_user
        },
    )


# --- API ENDPOINTS ---

@router.get("/api/vacancies", response_model=schemas.VacancyPagination)
@is_recruiter
async def list_vacancies_api(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    q: Optional[str] = None,
    status: Optional[str] = "open",
    sede_id: Optional[int] = None,
    area_id: Optional[int] = None,
    sla_status: Optional[str] = None,
    scope: str = Query("all", regex="^(mine|all)$"),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc", regex="^(asc|desc)$"),
):
    """API: Listado paginado de vacantes."""
    # Determine user ID for scope filter
    current_user_id = current_user.id if scope == "mine" else None

    return await service.get_vacancies_paginated(
        db, page, 20, q, status, sede_id, area_id, sla_status, scope, current_user_id, sort_by, sort_order
    )


@router.get("/api/vacancies/{vacancy_id}", response_model=schemas.VacancyRead)
@is_recruiter
async def get_vacancy_api(
    vacancy_id: int, db: Annotated[AsyncSession, Depends(get_db)]
):
    """API: Obtener detalle de vacante (para edición)."""
    vacancy = await service.get_vacancy_by_id(db, vacancy_id)
    if not vacancy:
        raise HTTPException(404, "Vacante no encontrada")
    return vacancy


@router.post("/api/vacancies", response_model=schemas.VacancyRead, status_code=201)
@is_recruiter
async def create_vacancy_api(
    vacancy_data: schemas.VacancyCreate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    user_id = await get_current_user_id(request) or 1
    try:
        return await service.create_vacancy(db, vacancy_data, user_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/api/vacancies/{vacancy_id}", response_model=schemas.VacancyRead)
@is_recruiter
async def update_vacancy_api(
    vacancy_id: int,
    vacancy_data: schemas.VacancyUpdate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    background_tasks: BackgroundTasks,
):
    user_id = await get_current_user_id(request)
    try:
        updated = await service.update_vacancy(
            db, vacancy_id, vacancy_data, background_tasks, user_id
        )
        if not updated:
            raise HTTPException(404, "Vacante no encontrada")
        return updated
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/api/vacancies/{vacancy_id}", status_code=204)
@is_admin
async def delete_vacancy_api(
    vacancy_id: int, db: Annotated[AsyncSession, Depends(get_db)]
):
    if not await service.delete_vacancy(db, vacancy_id):
        raise HTTPException(404, "Vacante no encontrada")
    return None


@router.post("/api/vacancies/{vacancy_id}/notify-status")
@is_recruiter
async def notify_vacancy_status_api(
    vacancy_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    background_tasks: BackgroundTasks,
):
    try:
        success = await service.notify_vacancy_status(db, vacancy_id, background_tasks)
        if not success:
            raise HTTPException(404, "Vacante no encontrada")
        return {"message": "Reporte enviado correctamente"}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/api/stages/{stage_id}", response_model=schemas.StageRead)
@is_recruiter
async def update_stage_api(
    stage_id: int,
    stage_data: schemas.StageUpdate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    background_tasks: BackgroundTasks,
):
    user_id = await get_current_user_id(request)
    try:
        updated = await service.update_stage(
            db, stage_id, stage_data, background_tasks, user_id
        )
        if not updated:
            raise HTTPException(404, "Etapa no encontrada")
        return updated
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/stages/{stage_id}/notify", status_code=200)
@is_recruiter
async def notify_stage_owner_api(
    stage_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    background_tasks: BackgroundTasks,
):
    try:
        success = await service.notify_stage_responsible(
            db, stage_id, background_tasks
        )
        if not success:
            raise HTTPException(404, "Etapa no encontrada")
        return {
            "message": "Notificación enviada correctamente (en segundo plano)"
        }
    except ValueError as e:
        raise HTTPException(400, str(e))


# --- PROCESS API ---

@router.post("/api/processes", response_model=schemas.ProcessRead)
@is_admin
async def create_process_api(
    proc: schemas.ProcessCreate, db: Annotated[AsyncSession, Depends(get_db)]
):
    return await service.create_process(db, proc)


@router.put("/api/processes/{process_id}", response_model=schemas.ProcessRead)
@is_admin
async def update_process_api(
    process_id: int,
    proc: schemas.ProcessCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    updated = await service.update_process(db, process_id, proc)
    if not updated:
        raise HTTPException(404, "Proceso no encontrado")
    return updated


@router.delete("/api/processes/{process_id}", status_code=204)
@is_admin
async def delete_process_api(
    process_id: int, db: Annotated[AsyncSession, Depends(get_db)]
):
    try:
        success = await service.delete_process(db, process_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not success:
        raise HTTPException(404, "Proceso no encontrado")
    return None


@router.post(
    "/api/processes/{process_id}/stages",
    response_model=schemas.ProcessStageRead,
)
@is_recruiter
async def add_process_stage_api(
    process_id: int,
    stage: schemas.ProcessStageCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await service.add_stage_to_process(db, process_id, stage)


@router.put(
    "/api/processes/stages/{stage_id}", response_model=schemas.ProcessStageRead
)
@is_recruiter
async def update_process_stage_api(
    stage_id: int,
    stage: schemas.ProcessStageCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    updated = await service.update_process_stage(db, stage_id, stage)
    if not updated:
        raise HTTPException(404, "Etapa no encontrada")
    return updated


@router.delete("/api/processes/stages/{stage_id}", status_code=204)
@is_admin
async def delete_process_stage_api(
    stage_id: int, db: Annotated[AsyncSession, Depends(get_db)]
):
    """
    Elimina una etapa del proceso.
    Requiere rol de ADMIN.
    """
    try:
        if not await service.delete_process_stage(db, stage_id):
            raise HTTPException(404, "Etapa no encontrada")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return None


# --- HIRING REASONS CONFIGURATION ---

@router.get("/config/hiring-reasons", response_class=HTMLResponse)
@is_recruiter
async def config_hiring_reasons_view(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    """Vista de configuración de motivos de contratación."""
    reasons = await service.get_hiring_reasons(db)
    reasons_data = [
        schemas.HiringReasonRead.model_validate(r).model_dump(mode="json")
        for r in reasons
    ]
    return templates.TemplateResponse(request=request, name="recruitment/config/hiring_reasons.html", context=
        {
            "request": request,
            "reasons": reasons_data,
            "settings": settings,
            "current_user": current_user
        },
    )


@router.post("/api/config/hiring-reasons", response_model=schemas.HiringReasonRead)
@is_recruiter
async def create_hiring_reason_api(
    reason: schemas.HiringReasonCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        return await service.create_hiring_reason(db, reason)
    except Exception as e: # Handle unique constraint violation properly in real app
        raise HTTPException(400, str(e))


@router.put("/api/config/hiring-reasons/{reason_id}", response_model=schemas.HiringReasonRead)
@is_recruiter
async def update_hiring_reason_api(
    reason_id: int,
    reason: schemas.HiringReasonUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    updated = await service.update_hiring_reason(db, reason_id, reason)
    if not updated:
        raise HTTPException(404, "Motivo no encontrado")
    return updated


@router.delete("/api/config/hiring-reasons/{reason_id}", status_code=204)
@is_recruiter
async def delete_hiring_reason_api(
    reason_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    success = await service.delete_hiring_reason(db, reason_id)
    if not success:
        raise HTTPException(404, "Motivo no encontrado")
    return None


# --- STAGE EDIT REASONS CONFIGURATION ---

@router.get("/config/stage-edit-reasons", response_class=HTMLResponse)
@is_recruiter
async def config_stage_edit_reasons_view(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
):
    """Vista de configuración de motivos de edición de etapas."""
    reasons = await service.get_stage_edit_reasons(db)
    reasons_data = [
        schemas.StageEditReasonRead.model_validate(r).model_dump(mode="json")
        for r in reasons
    ]
    return templates.TemplateResponse(request=request, name="recruitment/config/stage_edit_reasons.html", context=
        {
            "request": request,
            "reasons": reasons_data,
            "settings": settings,
            "current_user": current_user
        },
    )


@router.post("/api/config/stage-edit-reasons", response_model=schemas.StageEditReasonRead)
@is_recruiter
async def create_stage_edit_reason_api(
    reason: schemas.StageEditReasonCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        return await service.create_stage_edit_reason(db, reason)
    except Exception as e:
        raise HTTPException(400, str(e))


@router.put("/api/config/stage-edit-reasons/{reason_id}", response_model=schemas.StageEditReasonRead)
@is_recruiter
async def update_stage_edit_reason_api(
    reason_id: int,
    reason: schemas.StageEditReasonUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    updated = await service.update_stage_edit_reason(db, reason_id, reason)
    if not updated:
        raise HTTPException(404, "Motivo no encontrado")
    return updated


@router.delete("/api/config/stage-edit-reasons/{reason_id}", status_code=204)
@is_recruiter
async def delete_stage_edit_reason_api(
    reason_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    success = await service.delete_stage_edit_reason(db, reason_id)
    if not success:
        raise HTTPException(404, "Motivo no encontrado")
    return None