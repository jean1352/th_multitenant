"""
Analítica, KPIs del Tablero (Sección 8, RF-35, CA-12) y Reportes Exportables Excel/PDF (RF-36).
"""

from __future__ import annotations

import io
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from weasyprint import HTML

from app.core.config import settings
from app.modules.employees.models import Employee
from app.modules.organization.models import Area, Position
from app.modules.trainings.models import (
    EnrollmentStatus,
    ReplicaCommitment,
    ReplicaStatus,
    Training,
    TrainingEnrollment,
    TrainingNotification,
    TrainingSession,
    TrainingStatus,
    TrainingType,
)
from app.modules.trainings.notifications_service import _effective_presence
from app.modules.trainings.parameters_service import get_parameters_dict
from app.modules.trainings.replicas_service import compute_traffic_light


async def get_dashboard_data(
    db: AsyncSession,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    area_id: Optional[int] = None,
    training_type: Optional[str] = None,
    modality: Optional[str] = None,
    allowed_area_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """Calcula los 9 KPIs de la Sección 8 y los widgets del tablero."""
    params = await get_parameters_dict(db)
    today = date.today()

    stmt_t = select(Training).options(
        selectinload(Training.sessions).selectinload(TrainingSession.attendances),
        selectinload(Training.enrollments)
        .selectinload(TrainingEnrollment.employee)
        .selectinload(Employee.position_obj)
        .selectinload(Position.area),
        selectinload(Training.enrollments).selectinload(TrainingEnrollment.survey),
        selectinload(Training.provider_obj),
        selectinload(Training.target_area_obj),
    ).execution_options(populate_existing=True)
    if start_date:
        stmt_t = stmt_t.where(Training.end_date >= start_date)
    if end_date:
        stmt_t = stmt_t.where(Training.start_date <= end_date)
    if training_type and training_type != "all":
        stmt_t = stmt_t.where(Training.type == training_type)
    if modality and modality != "all":
        stmt_t = stmt_t.where(Training.modality == modality)

    trainings = (await db.execute(stmt_t)).scalars().all()

    effective_area_filter: Optional[set] = None
    if allowed_area_ids is not None:
        effective_area_filter = set(allowed_area_ids)
    if area_id:
        effective_area_filter = (
            {area_id} if effective_area_filter is None else (effective_area_filter & {area_id})
        )

    def _enroll_area_id(e: TrainingEnrollment) -> Optional[int]:
        if e.employee and e.employee.position_obj:
            return e.employee.position_obj.area_id
        return None

    filtered_trainings: List[Training] = []
    filtered_enrollments: List[TrainingEnrollment] = []
    for t in trainings:
        enrolls = list(t.enrollments)
        if effective_area_filter is not None:
            enrolls = [e for e in enrolls if _enroll_area_id(e) in effective_area_filter]
            if not enrolls and (t.target_area_id not in effective_area_filter):
                continue
        filtered_trainings.append(t)
        filtered_enrollments.extend(enrolls)

    # 1. % de asistencia
    scheduled_records = 0
    present_records = 0
    area_att_stats: Dict[str, Dict[str, int]] = {}

    for t in filtered_trainings:
        enrolls = [
            e for e in t.enrollments
            if (effective_area_filter is None or _enroll_area_id(e) in effective_area_filter)
            and e.status not in (
                EnrollmentStatus.DECLINED,
                EnrollmentStatus.WITHDRAWN,
                EnrollmentStatus.WAITLIST,
                EnrollmentStatus.PENDING_APPROVAL,
            )
        ]
        enroll_map = {e.id: e for e in enrolls}
        for s in t.sessions:
            att_by_e = {a.enrollment_id: a for a in s.attendances}
            for eid, e in enroll_map.items():
                if s.status.value != "closed" and eid not in att_by_e:
                    continue
                scheduled_records += 1
                a = att_by_e.get(eid)
                is_pres = bool(a and _effective_presence(a, params))
                if is_pres:
                    present_records += 1
                area_name = (
                    e.employee.position_obj.area.name
                    if e.employee and e.employee.position_obj and e.employee.position_obj.area
                    else "Sin Área"
                )
                area_att_stats.setdefault(area_name, {"present": 0, "total": 0})
                area_att_stats[area_name]["total"] += 1
                if is_pres:
                    area_att_stats[area_name]["present"] += 1

    attendance_rate = round((present_records / scheduled_records) * 100, 1) if scheduled_records > 0 else 0.0


    # 2. % participantes aprobados
    closed_enrollments = [
        e for e in filtered_enrollments
        if e.status in (EnrollmentStatus.ATTENDED, EnrollmentStatus.FAILED, EnrollmentStatus.NO_SHOW)
    ]
    approved_enrollments = [e for e in closed_enrollments if e.status == EnrollmentStatus.ATTENDED]
    approval_rate = round((len(approved_enrollments) / len(closed_enrollments)) * 100, 1) if closed_enrollments else 0.0

    # 3. % alertas enviadas a tiempo
    stmt_n = select(TrainingNotification).where(TrainingNotification.status != "cancelled")
    if start_date:
        stmt_n = stmt_n.where(TrainingNotification.scheduled_date >= start_date)
    if end_date:
        stmt_n = stmt_n.where(TrainingNotification.scheduled_date <= end_date)
    notifs = (await db.execute(stmt_n)).scalars().all()
    total_notifs = len(notifs)
    ontime_notifs = sum(
        1 for n in notifs
        if n.status == "sent" and n.sent_at and n.sent_at.date() <= n.scheduled_date
    )
    alerts_ontime_rate = round((ontime_notifs / total_notifs) * 100, 1) if total_notifs > 0 else 0.0

    # 4 & 5. % cumplimiento de réplicas y réplicas vencidas
    stmt_rep = select(ReplicaCommitment).options(
        selectinload(ReplicaCommitment.employee)
        .selectinload(Employee.position_obj)
        .selectinload(Position.area)
    ).execution_options(populate_existing=True)
    commitments = (await db.execute(stmt_rep)).scalars().all()
    filtered_commitments: List[ReplicaCommitment] = []
    for c in commitments:
        c_area = c.employee.position_obj.area_id if c.employee and c.employee.position_obj else None
        if effective_area_filter is not None and c_area not in effective_area_filter:
            continue
        eff_due = c.extended_due_date or c.due_date
        if start_date and eff_due < start_date and (not c.completed_at or c.completed_at < start_date):
            continue
        if end_date and eff_due > end_date and (not c.completed_at or c.completed_at > end_date):
            continue
        filtered_commitments.append(c)

    completed_on_time = sum(
        1 for c in filtered_commitments
        if c.status == ReplicaStatus.COMPLETED.value
        and c.completed_at
        and c.completed_at <= (c.extended_due_date or c.due_date)
    )
    overdue_count = sum(1 for c in filtered_commitments if c.status == ReplicaStatus.OVERDUE.value)
    denom_rep = completed_on_time + overdue_count
    replica_compliance_rate = round((completed_on_time / denom_rep) * 100, 1) if denom_rep > 0 else 0.0

    # Semáforo de réplicas por área
    replica_traffic_by_area: Dict[str, Dict[str, int]] = {}
    for c in filtered_commitments:
        if c.status == ReplicaStatus.CANCELLED_EXIT.value:
            continue
        area_name = (
            c.employee.position_obj.area.name
            if c.employee and c.employee.position_obj and c.employee.position_obj.area
            else "Sin Área"
        )
        replica_traffic_by_area.setdefault(area_name, {"green": 0, "yellow": 0, "red": 0, "overdue": 0})
        tl = compute_traffic_light(c, today)
        if tl in ("green", "yellow", "red"):
            replica_traffic_by_area[area_name][tl] += 1
        if c.status == ReplicaStatus.OVERDUE.value:
            replica_traffic_by_area[area_name]["overdue"] += 1

    # 6. Personas alcanzadas por réplicas
    reached_employees = set()
    for t in filtered_trainings:
        if t.type != TrainingType.REPLICA:
            continue
        enroll_emp = {
            e.id: e.employee_id
            for e in t.enrollments
            if effective_area_filter is None or _enroll_area_id(e) in effective_area_filter
        }
        for s in t.sessions:
            for a in s.attendances:
                if a.enrollment_id in enroll_emp and _effective_presence(a, params):
                    reached_employees.add(enroll_emp[a.enrollment_id])
    people_reached_replicas = len(reached_employees)

    # 7. Horas de capacitación por colaborador
    stmt_active_emps = (
        select(Employee)
        .join(Position, Employee.position_id == Position.id)
        .where(Employee.is_active == True)  # noqa
    )
    if effective_area_filter is not None:
        if effective_area_filter:
            stmt_active_emps = stmt_active_emps.where(Position.area_id.in_(effective_area_filter))
        else:
            stmt_active_emps = stmt_active_emps.where(Employee.id == -1)
    active_emps_count = len((await db.execute(stmt_active_emps)).scalars().all())
    training_map = {t.id: t for t in filtered_trainings}
    total_approved_hours = sum(
        float(training_map[e.training_id].hours or 0.0)
        for e in approved_enrollments
        if e.training_id in training_map
    )
    hours_per_employee = round(total_approved_hours / active_emps_count, 2) if active_emps_count > 0 else 0.0

    # 8. Inversión en capacitación externa
    closed_externals = [
        t for t in filtered_trainings
        if t.type == TrainingType.EXTERNAL and t.status == TrainingStatus.CLOSED
    ]
    total_investment = round(sum(float(t.cost or t.company_cost or 0.0) for t in closed_externals), 2)
    ext_hours = sum(float(t.hours or 0.0) for t in closed_externals)
    ext_participants = sum(
        len([e for e in t.enrollments if e.status in (EnrollmentStatus.ATTENDED, EnrollmentStatus.FAILED)])
        for t in closed_externals
    )
    investment_per_employee = round(total_investment / ext_participants, 2) if ext_participants > 0 else 0.0
    investment_per_hour = round(total_investment / ext_hours, 2) if ext_hours > 0 else 0.0

    # 9. Satisfacción promedio
    ratings = [e.survey.rating for e in filtered_enrollments if e.survey is not None]
    avg_satisfaction = round(sum(ratings) / len(ratings), 2) if ratings else 0.0

    area_ranking = sorted(
        [
            {
                "area": area_name,
                "present": vals["present"],
                "total": vals["total"],
                "rate": round((vals["present"] / vals["total"]) * 100, 1) if vals["total"] > 0 else 0.0,
            }
            for area_name, vals in area_att_stats.items()
        ],
        key=lambda x: (-x["rate"], -x["present"]),
    )

    upcoming_trainings = sorted(
        [
            {
                "id": t.id,
                "name": t.name,
                "type": t.type.value,
                "status": t.status.value,
                "start_date": t.start_date,
                "end_date": t.end_date,
            }
            for t in filtered_trainings
            if t.status in (TrainingStatus.PLANNED, TrainingStatus.IN_PROGRESS)
            and (t.start_date >= today or t.end_date >= today)
        ],
        key=lambda x: x["start_date"],
    )[:10]

    return {
        "kpis": {
            "attendance_rate": attendance_rate,
            "present_records": present_records,
            "scheduled_records": scheduled_records,
            "approval_rate": approval_rate,
            "approved_count": len(approved_enrollments),
            "closed_enrollments_count": len(closed_enrollments),
            "alerts_ontime_rate": alerts_ontime_rate,
            "ontime_notifs": ontime_notifs,
            "total_notifs": total_notifs,
            "replica_compliance_rate": replica_compliance_rate,
            "replicas_completed_on_time": completed_on_time,
            "replicas_overdue": overdue_count,
            "people_reached_replicas": people_reached_replicas,
            "hours_per_employee": hours_per_employee,
            "total_approved_hours": round(total_approved_hours, 1),
            "total_investment": total_investment,
            "investment_per_employee": investment_per_employee,
            "investment_per_hour": investment_per_hour,
            "avg_satisfaction": avg_satisfaction,
            "surveys_count": len(ratings),
        },
        "replica_traffic_by_area": replica_traffic_by_area,
        "area_ranking": area_ranking,
        "upcoming_trainings": upcoming_trainings,
    }


async def get_report_rows(
    db: AsyncSession,
    report_type: str,
    training_id: Optional[int] = None,
    employee_id: Optional[int] = None,
    area_id: Optional[int] = None,
    allowed_area_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """Genera filas estructuradas para los 5 reportes exportables (RF-36)."""
    eff_areas = set(allowed_area_ids) if allowed_area_ids is not None else None
    if area_id:
        eff_areas = {area_id} if eff_areas is None else (eff_areas & {area_id})

    if report_type == "attendance_list":
        stmt = (
            select(TrainingEnrollment)
            .join(Training)
            .join(Employee)
            .options(
                selectinload(TrainingEnrollment.training).selectinload(Training.sessions),
                selectinload(TrainingEnrollment.employee)
                .selectinload(Employee.position_obj)
                .selectinload(Position.area),
                selectinload(TrainingEnrollment.attendances),
            )
            .order_by(Training.start_date.desc(), Employee.full_name)
        )
        if training_id:
            stmt = stmt.where(TrainingEnrollment.training_id == training_id)
        rows = []
        for e in (await db.execute(stmt)).scalars().all():
            emp_area = e.employee.position_obj.area_id if e.employee and e.employee.position_obj else None
            if eff_areas is not None and emp_area not in eff_areas:
                continue
            rows.append({
                "Capacitación": e.training.name if e.training else "-",
                "Documento": e.employee.document_id if e.employee else "-",
                "Colaborador": e.employee.full_name if e.employee else "-",
                "Área": e.employee.position_obj.area.name if e.employee and e.employee.position_obj and e.employee.position_obj.area else "-",
                "Estado": e.status.value,
                "% Asistencia": round(e.attendance_pct or 0.0, 1),
                "Nota": e.knowledge_score if e.knowledge_score is not None else "-",
                "Resultado": e.result or "-",
            })
        return {"title": "Lista de Asistencia por Capacitación", "rows": rows}

    if report_type == "employee_history":
        stmt = (
            select(TrainingEnrollment)
            .join(Training)
            .join(Employee)
            .options(
                selectinload(TrainingEnrollment.training),
                selectinload(TrainingEnrollment.employee)
                .selectinload(Employee.position_obj)
                .selectinload(Position.area),
            )
            .order_by(Employee.full_name, Training.start_date.desc())
        )
        if employee_id:
            stmt = stmt.where(TrainingEnrollment.employee_id == employee_id)
        rows = []
        for e in (await db.execute(stmt)).scalars().all():
            emp_area = e.employee.position_obj.area_id if e.employee and e.employee.position_obj else None
            if eff_areas is not None and emp_area not in eff_areas:
                continue
            rows.append({
                "Colaborador": e.employee.full_name if e.employee else "-",
                "Área": e.employee.position_obj.area.name if e.employee and e.employee.position_obj and e.employee.position_obj.area else "-",
                "Capacitación": e.training.name if e.training else "-",
                "Tipo": e.training.type.value if e.training else "-",
                "Horas": e.training.hours if e.training else 0,
                "Inicio": e.training.start_date.isoformat() if e.training else "-",
                "Fin": e.training.end_date.isoformat() if e.training else "-",
                "% Asistencia": round(e.attendance_pct or 0.0, 1),
                "Resultado": e.result or e.status.value,
                "Certificado": "Sí" if e.certificate_file else "No",
            })
        return {"title": "Historial de Capacitaciones por Colaborador", "rows": rows}

    if report_type == "replicas_status":
        stmt = (
            select(ReplicaCommitment)
            .options(
                selectinload(ReplicaCommitment.employee)
                .selectinload(Employee.position_obj)
                .selectinload(Position.area),
                selectinload(ReplicaCommitment.source_training),
            )
            .order_by(ReplicaCommitment.due_date)
        )
        rows = []
        today = date.today()
        for c in (await db.execute(stmt)).scalars().all():
            emp_area = c.employee.position_obj.area_id if c.employee and c.employee.position_obj else None
            if eff_areas is not None and emp_area not in eff_areas:
                continue
            eff_due = c.extended_due_date or c.due_date
            rows.append({
                "Colaborador": c.employee.full_name if c.employee else "-",
                "Área": c.employee.position_obj.area.name if c.employee and c.employee.position_obj and c.employee.position_obj.area else "-",
                "Capacitación Origen": c.source_training.name if c.source_training else "-",
                "Estado": c.status,
                "Semáforo": compute_traffic_light(c, today),
                "Fecha Límite": eff_due.isoformat(),
                "Prórroga": c.extended_due_date.isoformat() if c.extended_due_date else "-",
                "Fecha Cumplimiento": c.completed_at.isoformat() if c.completed_at else "-",
            })
        return {"title": "Estado de Compromisos de Réplica", "rows": rows}

    if report_type == "external_investment":
        stmt = (
            select(Training)
            .options(
                selectinload(Training.provider_obj),
                selectinload(Training.currency_obj),
                selectinload(Training.cost_center_obj),
                selectinload(Training.target_area_obj),
                selectinload(Training.enrollments)
                .selectinload(TrainingEnrollment.employee)
                .selectinload(Employee.position_obj)
                .selectinload(Position.area),
            )
            .where(Training.type == TrainingType.EXTERNAL)
            .order_by(Training.start_date.desc())
        )
        rows = []
        for t in (await db.execute(stmt)).scalars().all():
            areas_in_t = {
                e.employee.position_obj.area.name
                for e in t.enrollments
                if e.employee and e.employee.position_obj and e.employee.position_obj.area
            }
            if eff_areas is not None:
                area_ids_in_t = {
                    e.employee.position_obj.area_id
                    for e in t.enrollments
                    if e.employee and e.employee.position_obj
                }
                if not (area_ids_in_t & eff_areas) and t.target_area_id not in eff_areas:
                    continue
            rows.append({
                "Capacitación": t.name,
                "Proveedor": t.provider_obj.business_name if t.provider_obj else "-",
                "Centro de Costo": t.cost_center_obj.name if t.cost_center_obj else "-",
                "Moneda": t.currency or (t.currency_obj.name if t.currency_obj else "-"),
                "Costo Total": float(t.cost or t.company_cost or 0.0),
                "Horas": float(t.hours or 0.0),
                "Estado": t.status.value,
                "Áreas": ", ".join(sorted(areas_in_t)) or (t.target_area_obj.name if t.target_area_obj else "-"),
            })
        return {"title": "Inversión en Capacitaciones Externas", "rows": rows}

    if report_type == "notifications_log":
        stmt = select(TrainingNotification).order_by(TrainingNotification.created_at.desc())
        rows = []
        for n in (await db.execute(stmt)).scalars().all():
            rows.append({
                "Evento": n.event_code,
                "Destinatario": n.recipient_email,
                "Asunto": n.subject or "-",
                "Fecha Programada": n.scheduled_date.isoformat(),
                "Fecha Envío": n.sent_at.strftime("%Y-%m-%d %H:%M") if n.sent_at else "-",
                "Estado": n.status,
                "Reintentos": n.retry_count,
                "Error": n.error_message or "-",
            })
        return {"title": "Registro de Alertas Enviadas y Fallidas", "rows": rows}

    raise ValueError(f"Tipo de reporte desconocido: {report_type}")


async def export_report_excel(
    db: AsyncSession,
    report_type: str,
    training_id: Optional[int] = None,
    employee_id: Optional[int] = None,
    area_id: Optional[int] = None,
    allowed_area_ids: Optional[List[int]] = None,
) -> io.BytesIO:
    report = await get_report_rows(db, report_type, training_id, employee_id, area_id, allowed_area_ids)
    df = pd.DataFrame(report["rows"])
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Reporte")
    output.seek(0)
    return output


async def export_report_pdf(
    db: AsyncSession,
    report_type: str,
    training_id: Optional[int] = None,
    employee_id: Optional[int] = None,
    area_id: Optional[int] = None,
    allowed_area_ids: Optional[List[int]] = None,
) -> io.BytesIO:
    report = await get_report_rows(db, report_type, training_id, employee_id, area_id, allowed_area_ids)
    rows = report["rows"]
    headers = list(rows[0].keys()) if rows else ["Información"]
    th_html = "".join(f"<th>{h}</th>" for h in headers)
    if rows:
        tr_html = "".join(
            "<tr>" + "".join(f"<td>{r.get(h, '')}</td>" for h in headers) + "</tr>"
            for r in rows
        )
    else:
        tr_html = f"<tr><td colspan='{len(headers)}' style='text-align:center;'>Sin registros para los filtros seleccionados.</td></tr>"

    html = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="utf-8">
        <style>
            @page {{ size: A4 landscape; margin: 1.5cm; }}
            body {{ font-family: Helvetica, Arial, sans-serif; font-size: 10px; color: #1e293b; }}
            .header {{ border-bottom: 2px solid #003366; padding-bottom: 8px; margin-bottom: 16px; display: flex; justify-content: space-between; }}
            h1 {{ color: #003366; font-size: 18px; margin: 0; }}
            table {{ width: 100%; border-collapse: collapse; }}
            th {{ background-color: #003366; color: #fff; text-align: left; padding: 6px; font-size: 9px; }}
            td {{ border-bottom: 1px solid #e2e8f0; padding: 5px 6px; }}
            tr:nth-child(even) {{ background-color: #f8fafc; }}
        </style>
    </head>
    <body>
        <div class="header">
            <div>
                <h1>{report['title']}</h1>
                <div>{settings.BUSINESS_NAME} · Módulo de Capacitaciones</div>
            </div>
            <div>Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}</div>
        </div>
        <table>
            <thead><tr>{th_html}</tr></thead>
            <tbody>{tr_html}</tbody>
        </table>
    </body>
    </html>
    """
    pdf_bytes = HTML(string=html).write_pdf()
    buf = io.BytesIO(pdf_bytes)
    buf.seek(0)
    return buf


