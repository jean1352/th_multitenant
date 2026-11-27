import io
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
from sqlalchemy import case, desc, func, select, Date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload  # <--- IMPORTACIÓN AGREGADA

from app.modules.employees.models import (
    Employee,
    EmployeeHistory,
    EmployeePosition,
    MovementType,
)
from app.modules.organization.models import Area
from app.modules.recruitment.models import (
    ProcessStatus,
    StageOwner,
    Vacancy,
    VacancyStage,
)
from app.modules.trainings.models import EnrollmentStatus, TrainingEnrollment
from app.modules.recruitment.business_calendar import count_business_days, refresh_holidays_cache

async def get_dashboard_metrics(db: AsyncSession) -> Dict[str, Any]:
    """Calcula métricas clave para el dashboard (KPIs generales)."""
    await refresh_holidays_cache(db)

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
            
        days_elapsed = count_business_days(created_at.date(), end_date.date())
        
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
    
    # NEW: Starts from EmployeePosition (primary) = fecha real de ingreso.
    # Usamos la posición primaria en lugar del historial porque el historial
    # de creación manual de empleados guarda la fecha de hoy por defecto,
    # mientras que EmployeePosition.start_date refleja el ingreso real.
    stmt_starts = (
        select(
            func.extract('month', EmployeePosition.start_date),
            func.count(EmployeePosition.id),
        )
        .where(
            func.extract('year', EmployeePosition.start_date) == year,
            EmployeePosition.is_primary == True,
        )
        .group_by(func.extract('month', EmployeePosition.start_date))
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
    """Obtiene detalles de INGRESO de empleados (Starts) usando la fecha real
    de ingreso (EmployeePosition.start_date de la posición primaria)."""
    stmt = (
        select(
            Employee.id,
            Employee.full_name,
            EmployeePosition.start_date,
            Employee.document_id,
        )
        .join(Employee, EmployeePosition.employee_id == Employee.id)
        .where(
            func.extract('year', EmployeePosition.start_date) == year,
            EmployeePosition.is_primary == True,
        )
        .order_by(EmployeePosition.start_date.desc())
    )

    res = await db.execute(stmt)
    return [
        {
            "id": r.id,
            "title": r.full_name,          # Mapped to 'title' for frontend compatibility
            "created_at": r.document_id,   # Mapped to 'created_at' (showing doc ID)
            "status": "active",            # Constant or derived
            "date": r.start_date.strftime("%d/%m/%Y"),
        }
        for r in res
    ]

async def get_stage_performance_stats(
    db: AsyncSession,
    area_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> Dict[str, Any]:
    """
    Calcula estadísticas detalladas por etapa (SLA, Tiempos y Cuellos de Botella).
    Soporta filtrado por Área y por Periodo (fechas).
    """
    await refresh_holidays_cache(db)

    # Filtros comunes a nivel de etapa
    conditions = [VacancyStage.end_date.is_not(None)]
    if area_id:
        conditions.append(Vacancy.area_id == area_id)
    if start_date:
        conditions.append(VacancyStage.start_date >= start_date)
    if end_date:
        conditions.append(VacancyStage.start_date <= end_date)

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

    # 2. Cuellos de Botella (Embudo) + Informe por etapa
    bottleneck_data, bottleneck_report = await _compute_bottleneck_data(db, conditions)

    # 3. SLA Global por Vacante (Calculado dinámicamente con filtro)
    stmt_vac = (
        select(Vacancy)
        .options(selectinload(Vacancy.stages))
        .where(Vacancy.status != ProcessStatus.CANCELLED)
    )
    if area_id:
        stmt_vac = stmt_vac.where(Vacancy.area_id == area_id)
    if start_date or end_date:
        stage_in_period = select(VacancyStage.vacancy_id)
        if start_date:
            stage_in_period = stage_in_period.where(VacancyStage.start_date >= start_date)
        if end_date:
            stage_in_period = stage_in_period.where(VacancyStage.start_date <= end_date)
        stmt_vac = stmt_vac.where(Vacancy.id.in_(stage_in_period))

    vacancies = (await db.execute(stmt_vac)).scalars().all()
    
    vac_ok = 0
    vac_overdue = 0
    rs_ok = 0
    rs_overdue = 0
    area_ok = 0
    area_overdue = 0
    now = datetime.now()

    for vac in vacancies:
        stages = sorted(vac.stages, key=lambda s: s.order_index)

        # Calcular SLA total
        total_sla = sum(s.sla_days_snapshot for s in stages)
        
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

        days_elapsed = count_business_days(start.date(), end.date())
        
        if days_elapsed > total_sla:
            vac_overdue += 1
        else:
            vac_ok += 1

        # SLA por forma (R&S / Área) usando el mismo criterio que los schemas
        # rs_sla_status / area_sla_status (vencida si alguna etapa lo está).
        # Solo se consideran etapas dentro del periodo seleccionado.
        period_stages = [s for s in stages if _stage_in_period(s, start_date, end_date)]
        rs_stages = [s for s in period_stages if s.owner == StageOwner.RECRUITER]
        area_stages = [s for s in period_stages if s.owner == StageOwner.AREA]

        if rs_stages:
            if any(_stage_is_overdue(s) for s in rs_stages):
                rs_overdue += 1
            else:
                rs_ok += 1

        if area_stages:
            if any(_stage_is_overdue(s) for s in area_stages):
                area_overdue += 1
            else:
                area_ok += 1

    rs_total = rs_ok + rs_overdue
    area_total = area_ok + area_overdue
    sla_comparison = {
        "labels": ["R&S", "Área"],
        "values": [
            round((rs_ok / rs_total) * 100, 1) if rs_total > 0 else 0,
            round((area_ok / area_total) * 100, 1) if area_total > 0 else 0,
        ],
        "ok": [rs_ok, area_ok],
        "overdue": [rs_overdue, area_overdue],
        "total": [rs_total, area_total],
    }

    return {
        "sla_stages": sla_data,
        "bottleneck": bottleneck_data,
        "bottleneck_report": bottleneck_report,
        "sla_vacancy": {"A Tiempo": vac_ok, "Fuera de Plazo": vac_overdue},
        "sla_rs": {"A Tiempo": rs_ok, "Fuera de Plazo": rs_overdue},
        "sla_area": {"A Tiempo": area_ok, "Fuera de Plazo": area_overdue},
        "sla_comparison": sla_comparison,
    }


def _stage_is_overdue(stage: VacancyStage) -> bool:
    """Determina si una etapa está vencida (consistente con StageRead.sla_status)."""
    if stage.deadline_date:
        compare_date = stage.end_date or date.today()
        if compare_date > stage.deadline_date:
            return True
    return False


def _stage_in_period(stage: VacancyStage, start_date: Optional[date], end_date: Optional[date]) -> bool:
    """Indica si la etapa inicia dentro del periodo seleccionado."""
    if start_date and stage.start_date < start_date:
        return False
    if end_date and stage.start_date > end_date:
        return False
    return True


def _vacancy_days_elapsed(vac: Vacancy, now: datetime) -> int:
    """Días hábiles transcurridos de una vacante (desde la primera etapa o creación)."""
    stages = sorted(vac.stages, key=lambda s: s.order_index) if vac.stages else []
    start_date = (
        stages[0].start_date
        if stages
        else (vac.created_at.date() if vac.created_at else date.today())
    )
    end = vac.closed_at or now
    end_date = end.date() if isinstance(end, datetime) else end
    return count_business_days(start_date, end_date)


def _stage_days_taken(stage: VacancyStage) -> int:
    """Días hábiles consumidos en una etapa (hasta su fin o hasta hoy)."""
    end = stage.end_date or date.today()
    return count_business_days(stage.start_date, end)


def _owner_label(owner) -> str:
    """Devuelve la etiqueta legible del responsable de una etapa."""
    if isinstance(owner, StageOwner):
        return "R&S" if owner == StageOwner.RECRUITER else "Área"
    # Por si llega como cadena (nombre o valor del enum).
    return "R&S" if owner in ("RECRUITER", "reclutador") else "Área"


async def _compute_bottleneck_data(db: AsyncSession, conditions: List[Any]):
    """Calcula los datos del embudo de cuellos de botella y su informe por etapa."""
    stmt = (
        select(
            VacancyStage.name,
            VacancyStage.owner,
            func.min(VacancyStage.order_index).label("min_order"),
            func.count(VacancyStage.id).label("count"),
            func.avg(VacancyStage.end_date - VacancyStage.start_date).label("avg_real"),
            func.avg(VacancyStage.sla_days_snapshot).label("avg_target"),
            func.sum(case((VacancyStage.end_date > VacancyStage.deadline_date, 1), else_=0)).label("overdue"),
        )
        .join(Vacancy, VacancyStage.vacancy_id == Vacancy.id)
        .where(*conditions)
        .group_by(VacancyStage.name, VacancyStage.owner)
        .order_by(func.min(VacancyStage.order_index), VacancyStage.name)
    )
    result = await db.execute(stmt)

    funnel_data = {"labels": [], "real": [], "target": [], "overdue": [], "count": [], "owner": []}
    report: List[Dict[str, Any]] = []

    for row in result:
        avg_real = round(row.avg_real, 1) if row.avg_real else 0
        avg_target = round(row.avg_target, 1) if row.avg_target else 0
        count = row.count or 0
        overdue = row.overdue or 0
        ok = count - overdue
        compliance_pct = round((ok / count) * 100, 1) if count > 0 else 0
        owner_label = _owner_label(row.owner)

        funnel_data["labels"].append(row.name)
        funnel_data["real"].append(avg_real)
        funnel_data["target"].append(avg_target)
        funnel_data["overdue"].append(overdue)
        funnel_data["count"].append(count)
        funnel_data["owner"].append(owner_label)

        report.append(
            {
                "stage": row.name,
                "owner": owner_label,
                "count": count,
                "avg_real_days": avg_real,
                "avg_target_days": avg_target,
                "ok": ok,
                "overdue": overdue,
                "compliance_pct": compliance_pct,
            }
        )

    return funnel_data, report


async def get_bottleneck_report(
    db: AsyncSession,
    area_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """Reporte de cuellos de botella por etapa (filas listas para tabla/exportación)."""
    await refresh_holidays_cache(db)

    conditions = [VacancyStage.end_date.is_not(None)]
    if area_id:
        conditions.append(Vacancy.area_id == area_id)
    if start_date:
        conditions.append(VacancyStage.start_date >= start_date)
    if end_date:
        conditions.append(VacancyStage.start_date <= end_date)

    _, report = await _compute_bottleneck_data(db, conditions)
    return report


async def generate_bottleneck_excel_report(
    db: AsyncSession,
    area_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> io.BytesIO:
    """Genera un informe Excel de cuellos de botella."""
    report = await get_bottleneck_report(db, area_id, start_date, end_date)

    rows = [
        {
            "Etapa": r["stage"],
            "Responsable": r["owner"],
            "Casos": r["count"],
            "Días Promedio Real": r["avg_real_days"],
            "SLA Objetivo (días)": r["avg_target_days"],
            "A Tiempo": r["ok"],
            "Fuera de Plazo": r["overdue"],
            "% Cumplimiento": r["compliance_pct"],
        }
        for r in report
    ]

    df = pd.DataFrame(rows)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Cuellos de Botella")
    buffer.seek(0)
    return buffer


async def get_sla_details(
    db: AsyncSession,
    form: str,
    area_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> Dict[str, Any]:
    """
    Devuelve el detalle (casos A Tiempo / Fuera de Plazo) de una de las tres
    formas de SLA: 'global', 'rs' (R&S) o 'area' (Área solicitante).

    Cada item es un caso con su vacante, área, etapa, fechas, SLA, días
    transcurridos, responsable y estado, listo para renderizar en un modal.
    """
    if form not in ("global", "rs", "area"):
        raise ValueError("Forma de SLA inválida. Use 'global', 'rs' o 'area'.")

    await refresh_holidays_cache(db)

    stmt = (
        select(Vacancy)
        .options(
            selectinload(Vacancy.stages).selectinload(VacancyStage.responsible),
            selectinload(Vacancy.area),
        )
        .where(Vacancy.status != ProcessStatus.CANCELLED)
    )
    if area_id:
        stmt = stmt.where(Vacancy.area_id == area_id)

    vacancies = (await db.execute(stmt)).scalars().all()
    now = datetime.now()
    items: List[Dict[str, Any]] = []

    for vac in vacancies:
        stages = sorted(vac.stages, key=lambda s: s.order_index)
        if form != "global":
            stages = [s for s in stages if _stage_in_period(s, start_date, end_date)]
            if not stages:
                continue
        area_name = vac.area.name if vac.area else "-"

        if form == "global":
            total_sla = sum(s.sla_days_snapshot for s in stages)
            days_elapsed = _vacancy_days_elapsed(vac, now)
            status = "Fuera de Plazo" if days_elapsed > total_sla else "A Tiempo"

            start = stages[0].start_date if stages else None
            deadline = stages[-1].deadline_date if stages else None

            items.append({
                "vacancy_id": vac.id,
                "vacancy_title": vac.title,
                "area_name": area_name,
                "stage_name": "Proceso completo",
                "owner": "Global",
                "sla_days": total_sla,
                "days_taken": days_elapsed,
                "start_date": start.strftime("%d/%m/%Y") if start else "-",
                "deadline_date": deadline.strftime("%d/%m/%Y") if deadline else "-",
                "end_date": vac.closed_at.strftime("%d/%m/%Y") if vac.closed_at else "En curso",
                "status": status,
                "responsible": None,
            })
            continue

        owner = StageOwner.RECRUITER if form == "rs" else StageOwner.AREA
        owner_label = "R&S" if form == "rs" else "Área"

        # Agregado a nivel de vacante: una fila por vacante (no por etapa).
        owner_stages = [s for s in stages if s.owner == owner]
        if not owner_stages:
            continue

        sla_days = sum(s.sla_days_snapshot for s in owner_stages)
        days_taken = sum(_stage_days_taken(s) for s in owner_stages)
        status = "Fuera de Plazo" if any(_stage_is_overdue(s) for s in owner_stages) else "A Tiempo"

        start = owner_stages[0].start_date
        deadline = owner_stages[-1].deadline_date if owner_stages[-1].deadline_date else None

        if any(s.end_date is None for s in owner_stages):
            end_str = "En curso"
        else:
            last_end = max(s.end_date for s in owner_stages if s.end_date)
            end_str = last_end.strftime("%d/%m/%Y")

        responsibles = [s.responsible.full_name for s in owner_stages if s.responsible]
        responsible_str = ", ".join(dict.fromkeys(responsibles)) or None

        items.append({
            "vacancy_id": vac.id,
            "vacancy_title": vac.title,
            "area_name": area_name,
            "stage_name": "Etapas R&S" if form == "rs" else "Etapas Área",
            "owner": owner_label,
            "sla_days": sla_days,
            "days_taken": days_taken,
            "start_date": start.strftime("%d/%m/%Y") if start else "-",
            "deadline_date": deadline.strftime("%d/%m/%Y") if deadline else "-",
            "end_date": end_str,
            "status": status,
            "responsible": responsible_str,
        })

    # Ordenar: primero los fuera de plazo, luego por nombre de vacante
    items.sort(key=lambda i: (0 if i["status"] == "Fuera de Plazo" else 1, i["vacancy_title"].lower()))

    return {
        "form": form,
        "total": len(items),
        "ok": sum(1 for i in items if i["status"] == "A Tiempo"),
        "overdue": sum(1 for i in items if i["status"] == "Fuera de Plazo"),
        "items": items,
    }