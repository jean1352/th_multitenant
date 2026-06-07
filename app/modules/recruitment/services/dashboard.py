from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import case, desc, func, select, Date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload  # <--- IMPORTACIÓN AGREGADA

from app.modules.employees.models import EmployeeHistory, MovementType
from app.modules.organization.models import Area
from app.modules.recruitment.models import (
    ProcessStatus,
    Vacancy,
    VacancyStage
)
from app.modules.employees.models import (
    Employee,
    EmployeeHistory,
    MovementType
)
from app.modules.trainings.models import EnrollmentStatus, TrainingEnrollment

async def get_dashboard_metrics(db: AsyncSession) -> Dict[str, Any]:
    """Calcula métricas clave para el dashboard (KPIs generales)."""

    # 1. KPIs Básicos
    total_vacancies = await db.scalar(select(func.count(Vacancy.id))) or 0
    open_vacancies = await db.scalar(
        select(func.count(Vacancy.id)).where(
            Vacancy.status == ProcessStatus.OPEN
        )
    ) or 0
    closed_vacancies = await db.scalar(
        select(func.count(Vacancy.id)).where(
            Vacancy.status == ProcessStatus.CLOSED
        )
    ) or 0
    
    stmt_avg_time = select(
        func.avg(Vacancy.closed_at - Vacancy.created_at)
    ).where(Vacancy.status == ProcessStatus.CLOSED)
    avg_time_interval = await db.scalar(stmt_avg_time)
    avg_days = avg_time_interval.days if avg_time_interval else 0

    # 2. Gráfico: Vacantes por Área
    stmt_by_area = (
        select(Area.name, func.count(Vacancy.id))
        .join(Area, Vacancy.area_id == Area.id)
        .group_by(Area.name)
    )
    result_by_area = await db.execute(stmt_by_area)
    chart_area_data = {row[0]: row[1] for row in result_by_area}

    # 3. Gráfico: Tipo de Vacante (Cobertura)
    stmt_by_type = select(
        Vacancy.vacancy_type, func.count(Vacancy.id)
    ).group_by(Vacancy.vacancy_type)
    result_by_type = await db.execute(stmt_by_type)
    type_map = {
        "external": "Externa",
        "internal": "Interna",
        "transfer": "Traslado",
    }
    chart_type_data = {
        type_map.get(row[0].value, row[0].value): row[1]
        for row in result_by_type
        if row[0] is not None
    }

    # 4. Gráfico: Cumplimiento SLA (POR VACANTE GLOBAL)
    stmt_vac_sla = (
        select(
            Vacancy.status,
            Vacancy.created_at,
            Vacancy.closed_at,
            func.sum(VacancyStage.sla_days_snapshot).label('total_sla')
        )
        .join(VacancyStage, Vacancy.id == VacancyStage.vacancy_id)
        .where(Vacancy.status != ProcessStatus.CANCELLED)
        .group_by(Vacancy.id)
    )
    result_vac_sla = await db.execute(stmt_vac_sla)
    
    vac_sla_ok = 0
    vac_sla_overdue = 0
    now = datetime.now()
    
    for row in result_vac_sla:
        status = row.status
        created_at = row.created_at
        closed_at = row.closed_at
        total_sla = row.total_sla or 0
        
        if status == ProcessStatus.OPEN:
            if created_at.tzinfo:
                end_date = now.replace(tzinfo=created_at.tzinfo)
            else:
                end_date = now
        else:
            end_date = closed_at if closed_at else now

        if created_at.tzinfo and not end_date.tzinfo:
            created_at = created_at.replace(tzinfo=None)
        elif not created_at.tzinfo and end_date.tzinfo:
            end_date = end_date.replace(tzinfo=None)
            
        days_elapsed = (end_date - created_at).days
        
        if days_elapsed > total_sla:
            vac_sla_overdue += 1
        else:
            vac_sla_ok += 1
            
    total_vac_sla_count = vac_sla_ok + vac_sla_overdue
    sla_compliance_rate_vacancy = (
        round((vac_sla_ok / total_vac_sla_count) * 100, 1)
        if total_vac_sla_count > 0 else 0
    )

    # 5. Rotación
    six_months_ago = date.today() - timedelta(days=180)
    month_expr = func.to_char(EmployeeHistory.date, 'YYYY-MM')
    
    async def get_movement_counts(mov_type):
        stmt = (
            select(month_expr, func.count(EmployeeHistory.id))
            .where(
                EmployeeHistory.movement_type == mov_type,
                EmployeeHistory.date >= six_months_ago
            )
            .group_by(month_expr)
            .order_by(month_expr)
        )
        return {row[0]: row[1] for row in await db.execute(stmt)}

    exits = await get_movement_counts(MovementType.EXIT)
    entries = await get_movement_counts(MovementType.ENTRY)
    promotions = await get_movement_counts(MovementType.PROMOTION)

    all_months = sorted(list(set(exits.keys()) | set(entries.keys()) | set(promotions.keys())))
    
    turnover_data = {
        "labels": all_months,
        "exits": [exits.get(m, 0) for m in all_months],
        "entries": [entries.get(m, 0) for m in all_months],
        "promotions": [promotions.get(m, 0) for m in all_months]
    }

    # 6. Efectividad Capacitación
    stmt_training = select(
        TrainingEnrollment.status, func.count(TrainingEnrollment.id)
    ).group_by(TrainingEnrollment.status)
    result_training = await db.execute(stmt_training)
    training_data = {row[0].value: row[1] for row in result_training}

    total_enrolled = sum(training_data.values())
    attended = training_data.get(EnrollmentStatus.ATTENDED.value, 0)
    attendance_rate = round((attended / total_enrolled * 100), 1) if total_enrolled > 0 else 0

    # 7. Top 5 Áreas con más incumplimientos
    stmt_top_breaches = (
        select(Area.name, func.count(VacancyStage.id))
        .join(Vacancy, VacancyStage.vacancy_id == Vacancy.id)
        .join(Area, Vacancy.area_id == Area.id)
        .where(VacancyStage.end_date > VacancyStage.deadline_date)
        .group_by(Area.name)
        .order_by(desc(func.count(VacancyStage.id)))
        .limit(5)
    )
    result_breaches = await db.execute(stmt_top_breaches)
    top_breaches_data = {row[0]: row[1] for row in result_breaches}

    return {
        "kpi": {
            "total": total_vacancies,
            "open": open_vacancies,
            "closed": closed_vacancies,
            "avg_days": avg_days,
            "sla_rate_vacancy": sla_compliance_rate_vacancy,
            "attendance_rate": attendance_rate
        },
        "charts": {
            "by_area": chart_area_data,
            "by_type": chart_type_data,
            "sla_vacancy_pie": {
                "A Tiempo": vac_sla_ok,
                "Fuera de Plazo": vac_sla_overdue
            },
            "turnover": turnover_data,
            "top_breaches": top_breaches_data
        },
    }

async def get_monthly_stats(db: AsyncSession, year: int) -> Dict[str, Any]:
    """Obtiene estadísticas mensuales para un año específico (Modo Flujo y Modo Backlog)."""
    
    first_stage_sub = select(
        VacancyStage.vacancy_id,
        VacancyStage.start_date.label("fs_date")
    ).where(VacancyStage.order_index == 0).subquery()

    # Subquery for LAST stage date (for closed logic)
    max_order_sub = (
        select(VacancyStage.vacancy_id, func.max(VacancyStage.order_index).label("max_ord"))
        .group_by(VacancyStage.vacancy_id)
        .subquery()
    )
    last_stage_sub = (
        select(VacancyStage.vacancy_id, VacancyStage.end_date.label("ls_date"))
        .join(
            max_order_sub,
            (VacancyStage.vacancy_id == max_order_sub.c.vacancy_id) & 
            (VacancyStage.order_index == max_order_sub.c.max_ord)
        )
        .subquery()
    )

    # Define effective start date for counts (coalesce first stage start date or created_at)
    effective_start_date = func.coalesce(
        first_stage_sub.c.fs_date,
        func.cast(Vacancy.created_at, Date)
    )

    # Define effective close date (coalesce last stage end date or closed_at)
    effective_close_date = func.coalesce(
        last_stage_sub.c.ls_date,
        func.cast(Vacancy.closed_at, Date)
    )

    # Helper para contar por mes
    async def get_counts(date_expr, extra_filter=None, join_target=None):
        stmt = select(func.extract('month', date_expr), func.count(Vacancy.id))
        
        if join_target is not None:
            # Si join_target es una lista, iteramos
            if isinstance(join_target, list):
                for t in join_target:
                    stmt = stmt.outerjoin(t, Vacancy.id == t.c.vacancy_id)
            else:
                stmt = stmt.outerjoin(join_target, Vacancy.id == join_target.c.vacancy_id)
            
        stmt = stmt.where(func.extract('year', date_expr) == year)
        
        if extra_filter is not None:
            stmt = stmt.where(extra_filter)
        stmt = stmt.group_by(func.extract('month', date_expr))
        res = await db.execute(stmt)
        return {int(row[0]): row[1] for row in res}

    # --- MODO 1: FLUJO (Actividad en el mes) ---
    # Usamos la fecha efectiva (primera etapa) para 'opened' y 'growth'
    opened = await get_counts(effective_start_date, join_target=first_stage_sub)
    
    # UPDATED: Use effective_close_date for closed activity
    closed_activity = await get_counts(
        effective_close_date, 
        Vacancy.status == ProcessStatus.CLOSED, 
        join_target=[last_stage_sub] # Join with last_stage_sub to get ls_date
    )
    
    # NEW: Starts from EmployeeHistory (Entries) instead of Vacancy.start_date
    stmt_starts = (
        select(func.extract('month', EmployeeHistory.date), func.count(EmployeeHistory.id))
        .where(
            func.extract('year', EmployeeHistory.date) == year,
            EmployeeHistory.movement_type == MovementType.ENTRY
        )
        .group_by(func.extract('month', EmployeeHistory.date))
    )
    res_starts = await db.execute(stmt_starts)
    starts = {int(row[0]): row[1] for row in res_starts}

    growth = await get_counts(effective_start_date, Vacancy.is_headcount_increase == True, join_target=first_stage_sub)

    # --- MODO 2: BACKLOG (Estado actual de lo iniciado en el mes) ---
    # Usamos la fecha efectiva también para el backlog
    still_open = await get_counts(effective_start_date, Vacancy.status == ProcessStatus.OPEN, join_target=first_stage_sub)
    
    # Vacantes iniciadas en el mes X que HOY están cerradas
    created_and_closed = await get_counts(effective_start_date, Vacancy.status == ProcessStatus.CLOSED, join_target=first_stage_sub)

    # --- DETAIL QUERIES ---
    
    # We need 3 separate detail lists:
    # 1. Opened (matches 'opened' count) -> Filter by effective_start_date
    # 2. Closed (matches 'closed' count) -> Filter by effective_close_date & status=CLOSED
    # 3. Starts (matches 'starts' count) -> FROM EMPLOYEE HISTORY

    details_opened = await _get_detail_list(db, year, effective_start_date, [first_stage_sub])
    
    details_closed = await _get_detail_list(
        db, year, effective_close_date, 
        [last_stage_sub], 
        extra_filter=(Vacancy.status == ProcessStatus.CLOSED)
    )

    details_starts = await _get_employee_entry_details(db, year)

    return {
        "flow": {
            "opened": [opened.get(m, 0) for m in range(1, 13)],
            "closed": [closed_activity.get(m, 0) for m in range(1, 13)],
            "starts": [starts.get(m, 0) for m in range(1, 13)],
            "growth": [growth.get(m, 0) for m in range(1, 13)],
        },
        "backlog": {
            "still_open": [still_open.get(m, 0) for m in range(1, 13)],
            "created_and_closed": [created_and_closed.get(m, 0) for m in range(1, 13)],
        },
        "details": {
            "opened": details_opened,
            "closed": details_closed,
            "starts": details_starts
        }
    }

async def _get_detail_list(
    db: AsyncSession, 
    year: int, 
    date_column, 
    joins: List[Any], 
    extra_filter=None
) -> List[Dict[str, Any]]:
    """Helper genérico para obtener detalles de vacantes filtradas por año en una columna de fecha."""
    
    stmt = select(
        Vacancy.id,
        Vacancy.title,
        Vacancy.created_at,
        Vacancy.status,
        date_column.label("relevant_date")
    )

    for j in joins:
        stmt = stmt.outerjoin(j, Vacancy.id == j.c.vacancy_id)

    stmt = stmt.where(func.extract('year', date_column) == year)
    
    if extra_filter is not None:
        stmt = stmt.where(extra_filter)
        
    stmt = stmt.order_by(date_column.desc())
    
    res = await db.execute(stmt)
    return [
        {
            "id": r.id,
            "title": r.title,
            "created_at": r.created_at.strftime("%d/%m/%Y") if r.created_at else "-",
            "status": r.status.value,
            "date": r.relevant_date.strftime("%d/%m/%Y") if r.relevant_date else "-",
        }
        for r in res
    ]

async def _get_employee_entry_details(db: AsyncSession, year: int) -> List[Dict[str, Any]]:
    """Obtiene detalles de INGRESO de empleados (Starts) desde el historial."""
    stmt = (
        select(
            Employee.id,
            Employee.full_name,
            EmployeeHistory.date,
            Employee.document_id
        )
        .join(Employee, EmployeeHistory.employee_id == Employee.id)
        .where(
            func.extract('year', EmployeeHistory.date) == year,
            EmployeeHistory.movement_type == MovementType.ENTRY
        )
        .order_by(EmployeeHistory.date.desc())
    )
    
    res = await db.execute(stmt)
    return [
        {
            "id": r.id,
            "title": r.full_name,          # Mapped to 'title' for frontend compatibility
            "created_at": r.document_id,   # Mapped to 'created_at' (showing doc ID)
            "status": "active",            # Constant or derived
            "date": r.date.strftime("%d/%m/%Y"),
        }
        for r in res
    ]

async def get_stage_performance_stats(db: AsyncSession, area_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Calcula estadísticas detalladas por etapa (SLA y Tiempos).
    Soporta filtrado por Área.
    """
    # Filtros comunes
    conditions = [VacancyStage.end_date.is_not(None)]
    if area_id:
        conditions.append(Vacancy.area_id == area_id)

    # 1. SLA por Etapa (Conteo OK vs Overdue)
    stmt_sla = (
        select(
            VacancyStage.name,
            func.sum(case((VacancyStage.end_date > VacancyStage.deadline_date, 1), else_=0)).label("overdue"),
            func.sum(case((VacancyStage.end_date <= VacancyStage.deadline_date, 1), else_=0)).label("ok")
        )
        .join(Vacancy, VacancyStage.vacancy_id == Vacancy.id)
        .where(*conditions)
        .group_by(VacancyStage.name)
    )
    
    result_sla = await db.execute(stmt_sla)
    sla_data = {"labels": [], "ok": [], "overdue": []}
    
    for row in result_sla:
        sla_data["labels"].append(row.name)
        sla_data["overdue"].append(row.overdue or 0)
        sla_data["ok"].append(row.ok or 0)

    # 2. Cuellos de Botella (Tiempo Real vs SLA Objetivo)
    stmt_bottleneck = (
        select(
            VacancyStage.name,
            func.avg(VacancyStage.end_date - VacancyStage.start_date).label("avg_real"),
            func.avg(VacancyStage.sla_days_snapshot).label("avg_target")
        )
        .join(Vacancy, VacancyStage.vacancy_id == Vacancy.id)
        .where(*conditions)
        .group_by(VacancyStage.name)
        .order_by(desc(func.avg(VacancyStage.end_date - VacancyStage.start_date)))
        .limit(10) # Top 10 etapas más lentas
    )
    
    result_bottleneck = await db.execute(stmt_bottleneck)
    bottleneck_data = {"labels": [], "real": [], "target": []}
    
    for row in result_bottleneck:
        bottleneck_data["labels"].append(row.name)
        bottleneck_data["real"].append(round(row.avg_real, 1) if row.avg_real else 0)
        bottleneck_data["target"].append(round(row.avg_target, 1) if row.avg_target else 0)

    # 3. SLA Global por Vacante (Calculado dinámicamente con filtro)
    stmt_vac = (
        select(Vacancy)
        .options(selectinload(Vacancy.stages))
        .where(Vacancy.status != ProcessStatus.CANCELLED)
    )
    if area_id:
        stmt_vac = stmt_vac.where(Vacancy.area_id == area_id)
        
    vacancies = (await db.execute(stmt_vac)).scalars().all()
    
    vac_ok = 0
    vac_overdue = 0
    now = datetime.now()

    for vac in vacancies:
        # Calcular SLA total
        total_sla = sum(s.sla_days_snapshot for s in vac.stages)
        
        # Calcular días transcurridos
        start = vac.created_at
        end = vac.closed_at or now
        
        # Normalizar timezones
        if start.tzinfo and not end.tzinfo:
            if isinstance(end, datetime): end = end.replace(tzinfo=start.tzinfo)
        elif not start.tzinfo and end.tzinfo:
            start = start.replace(tzinfo=end.tzinfo)
            
        if isinstance(end, date) and not isinstance(end, datetime):
             end = datetime.combine(end, datetime.min.time())

        days_elapsed = (end - start).days
        
        if days_elapsed > total_sla:
            vac_overdue += 1
        else:
            vac_ok += 1

    sla_vacancy_data = {
        "A Tiempo": vac_ok,
        "Fuera de Plazo": vac_overdue
    }

    return {
        "sla_stages": sla_data,
        "bottleneck": bottleneck_data,
        "sla_vacancy": sla_vacancy_data
    }