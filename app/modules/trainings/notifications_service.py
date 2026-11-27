"""
Motor de notificaciones y automatización diaria para Capacitaciones (N-01..N-11).
Garantiza idempotencia (CA-11), adjuntos .ics (CA-02), reintentos y escalamientos.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.tenants import get_tenant_base_url
from app.modules.employees.models import Employee
from app.modules.notifications.models import EmailStatus
from app.modules.notifications.service import send_email_notification
from app.modules.trainings.models import (
    AttendanceStatus,
    EnrollmentStatus,
    ReplicaCommitment,
    ReplicaStatus,
    SessionStatus,
    Training,
    TrainingAttendance,
    TrainingEnrollment,
    TrainingNotification,
    TrainingSession,
    TrainingStatus,
    TrainingType,
)
from app.modules.trainings.parameters_service import get_parameters_dict, render_event_email
from app.modules.trainings.utils import (
    generate_training_ics,
    get_employee_manager_emails,
    get_th_emails,
    log_training_audit,
)

logger = logging.getLogger(__name__)


def _effective_presence(att: TrainingAttendance, params: Dict[str, Any]) -> bool:
    status = att.attendance_status or (
        AttendanceStatus.PRESENT.value if att.is_present else AttendanceStatus.ABSENT.value
    )
    if status == AttendanceStatus.PRESENT.value:
        return True
    if status == AttendanceStatus.LATE.value:
        return bool(params.get("late_counts_as_present", True))
    if status == AttendanceStatus.JUSTIFIED.value:
        return bool(params.get("justified_counts_as_present", True))
    return False


async def dispatch_training_notification(
    db: AsyncSession,
    event_code: str,
    recipient_email: str,
    entity_type: str,
    entity_id: int,
    dedup_key: str,
    variables: Dict[str, Any],
    scheduled_date: Optional[date] = None,
    recipient_id: Optional[int] = None,
    cc: Optional[List[str]] = None,
    attachments: Optional[List[Tuple[str, bytes, str]]] = None,
    allow_duplicate: bool = False,
) -> Optional[TrainingNotification]:
    """Envía y registra una notificación de forma idempotente."""
    if not recipient_email:
        return None

    if not allow_duplicate:
        existing = (
            await db.execute(
                select(TrainingNotification).where(
                    TrainingNotification.dedup_key == dedup_key,
                    TrainingNotification.status.in_(["sent", "pending"]),
                )
            )
        ).scalar_one_or_none()
        if existing:
            return None

    rendered = await render_event_email(db, event_code, variables)
    if not rendered.get("is_active", True):
        return None

    notif = TrainingNotification(
        event_code=event_code,
        recipient_id=recipient_id,
        recipient_email=recipient_email,
        entity_type=entity_type,
        entity_id=entity_id,
        dedup_key=dedup_key,
        scheduled_date=scheduled_date or date.today(),
        channel="email",
        status="pending",
        subject=rendered["subject"],
    )
    db.add(notif)
    await db.flush()

    log_entry = await send_email_notification(
        db=db,
        recipient=recipient_email,
        subject=rendered["subject"],
        body=rendered["body"],
        background_tasks=None,
        is_html=True,
        cc=cc,
        attachments=attachments,
    )

    if log_entry and log_entry.status == EmailStatus.SENT:
        notif.status = "sent"
        notif.sent_at = datetime.now()
    else:
        notif.status = "failed"
        notif.error_message = log_entry.error_message if log_entry else "Error al enviar"

    await db.commit()
    return notif



def _training_place(training: Training) -> str:
    parts = []
    if training.location:
        parts.append(training.location)
    if training.meeting_url:
        parts.append(training.meeting_url)
    return " | ".join(parts) if parts else "Por confirmar"


async def send_n01_convocation(
    db: AsyncSession,
    training: Training,
    enrollment: TrainingEnrollment,
    employee: Employee,
    base_url: Optional[str] = None,
    is_replica: bool = False,
) -> Optional[TrainingNotification]:
    """Envía N-01 (o N-09 si es réplica) al inscribir con adjunto .ics y jefe en copia."""
    if not employee.institutional_email:
        return None

    if not enrollment.invitation_token:
        enrollment.invitation_token = str(uuid.uuid4())
        await db.flush()

    sessions = (
        await db.execute(
            select(TrainingSession)
            .where(TrainingSession.training_id == training.id)
            .order_by(TrainingSession.date, TrainingSession.start_time)
        )
    ).scalars().all()

    ics_bytes = generate_training_ics(
        training,
        sessions=sessions,
        attendee_email=employee.institutional_email,
        attendee_name=employee.full_name,
    )
    attachments = [(f"capacitacion_{training.id}.ics", ics_bytes, "text/calendar")]

    cc_emails = await get_employee_manager_emails(db, employee)
    root = (base_url or get_tenant_base_url()).rstrip("/")
    respond_link = f"{root}/trainings/public/respond/{enrollment.invitation_token}"
    event_code = "N-09" if is_replica or training.type == TrainingType.REPLICA else "N-01"

    variables = {
        "nombre": employee.full_name,
        "capacitacion": training.name,
        "fecha_inicio": training.start_date.strftime("%d/%m/%Y"),
        "fecha_fin": training.end_date.strftime("%d/%m/%Y"),
        "modalidad": training.modality or "presencial",
        "sede_o_enlace": _training_place(training),
        "enlace": respond_link,
    }
    dedup_key = f"{event_code}:enrollment:{enrollment.id}"
    notif = await dispatch_training_notification(
        db=db,
        event_code=event_code,
        recipient_email=employee.institutional_email,
        entity_type="enrollment",
        entity_id=enrollment.id,
        dedup_key=dedup_key,
        variables=variables,
        recipient_id=employee.id,
        cc=cc_emails,
        attachments=attachments,
    )
    if notif and notif.status == "sent":
        enrollment.invitation_sent_at = date.today()
        await db.commit()
    return notif


async def send_n06_closure(
    db: AsyncSession,
    training: Training,
    enrollment: TrainingEnrollment,
    employee: Employee,
    commitment: Optional[ReplicaCommitment] = None,
) -> Optional[TrainingNotification]:
    """Envía N-06 al cerrar la capacitación."""
    if not employee.institutional_email:
        return None
    extra = ""
    if commitment:
        extra = (
            f"Se ha generado tu compromiso de réplica con fecha límite: "
            f"<strong>{commitment.due_date.strftime('%d/%m/%Y')}</strong>."
        )
    portal_link = f"{get_tenant_base_url().rstrip('/')}/portal/trainings"
    variables = {
        "nombre": employee.full_name,
        "capacitacion": training.name,
        "resultado": (enrollment.result or enrollment.status.value).upper(),
        "porcentaje_asistencia": round(enrollment.attendance_pct or 0, 1),
        "detalle_extra": extra,
        "enlace": portal_link,
    }
    return await dispatch_training_notification(
        db=db,
        event_code="N-06",
        recipient_email=employee.institutional_email,
        entity_type="enrollment",
        entity_id=enrollment.id,
        dedup_key=f"N-06:enrollment:{enrollment.id}",
        variables=variables,
        recipient_id=employee.id,
    )


async def cancel_pending_notifications_for_training(
    db: AsyncSession, training_id: int
) -> None:
    """Anula notificaciones pendientes al cancelar o reprogramar una capacitación."""
    enroll_ids = (
        await db.execute(
            select(TrainingEnrollment.id).where(TrainingEnrollment.training_id == training_id)
        )
    ).scalars().all()
    await db.execute(
        update(TrainingNotification)
        .where(
            TrainingNotification.status == "pending",
            TrainingNotification.entity_type == "training",
            TrainingNotification.entity_id == training_id,
        )
        .values(status="cancelled")
    )
    if enroll_ids:
        await db.execute(
            update(TrainingNotification)
            .where(
                TrainingNotification.status == "pending",
                TrainingNotification.entity_type == "enrollment",
                TrainingNotification.entity_id.in_(enroll_ids),
            )
            .values(status="cancelled")
        )
    await db.commit()


async def retry_failed_notifications(db: AsyncSession, max_retries: int = 3) -> int:
    """Reintenta envíos fallidos pendientes."""
    failed = (
        await db.execute(
            select(TrainingNotification).where(
                TrainingNotification.status == "failed",
                TrainingNotification.retry_count < max_retries,
            )
        )
    ).scalars().all()
    retried = 0
    for notif in failed:
        notif.retry_count += 1
        log_entry = await send_email_notification(
            db=db,
            recipient=notif.recipient_email,
            subject=notif.subject or f"[{notif.event_code}] Reintento de notificación",
            body="<p>Reintento automático de notificación del sistema de Capacitaciones.</p>",
            background_tasks=None,
            is_html=True,
        )
        if log_entry and log_entry.status == EmailStatus.SENT:
            notif.status = "sent"
            notif.sent_at = datetime.now()
            notif.error_message = None
            retried += 1
        else:
            notif.error_message = log_entry.error_message if log_entry else "Error al reintentar"
    if failed:
        await db.commit()
    return retried


async def _compute_enrollment_progress(
    db: AsyncSession, training: Training, enrollment: TrainingEnrollment, params: Dict[str, Any]
) -> Tuple[float, float, int, int]:
    """Devuelve (current_pct, max_achievable_pct, present_count, total_sessions)."""
    sessions = training.sessions or []
    total_sessions = len(sessions)
    if total_sessions == 0:
        return 0.0, 100.0, 0, 0

    att_map = {a.session_id: a for a in enrollment.attendances}
    present_count = 0
    closed_or_marked_sessions = 0
    for s in sessions:
        att = att_map.get(s.id)
        if att is not None:
            closed_or_marked_sessions += 1
            if _effective_presence(att, params):
                present_count += 1
        elif s.status == SessionStatus.CLOSED:
            closed_or_marked_sessions += 1

    remaining_sessions = max(0, total_sessions - closed_or_marked_sessions)
    current_pct = round((present_count / total_sessions) * 100.0, 1)
    max_achievable_pct = round(((present_count + remaining_sessions) / total_sessions) * 100.0, 1)
    return current_pct, max_achievable_pct, present_count, total_sessions


async def run_daily_training_automation(
    db: AsyncSession,
    today_override: Optional[date] = None,
    include_weekly: Optional[bool] = None,
) -> Dict[str, int]:
    """
    Tarea programada diaria (RNF-03, CA-03, CA-04, CA-10, CA-11):
    1. Transiciones automáticas de estado por fecha (PLANNED -> IN_PROGRESS -> COMPLETED)
    2. Reintentos de notificaciones fallidas
    3. Alertas N-02, N-03, N-04, N-05, N-07, N-08
    4. Vencimiento de compromisos de réplica (RN-08) y envío de N-10
    5. Resumen semanal N-11 (lunes)
    """
    today = today_override or date.today()
    params = await get_parameters_dict(db)
    stats = {
        "started": 0,
        "finished": 0,
        "retried": 0,
        "n02": 0,
        "n03": 0,
        "n04": 0,
        "n05": 0,
        "n07": 0,
        "n08": 0,
        "expired_replicas": 0,
        "n10": 0,
        "n11": 0,
    }

    # 1. Transiciones automáticas por fecha
    trainings_all = (
        await db.execute(
            select(Training)
            .options(
                selectinload(Training.sessions),
                selectinload(Training.enrollments).selectinload(TrainingEnrollment.employee),
                selectinload(Training.enrollments).selectinload(TrainingEnrollment.attendances),
                selectinload(Training.internal_instructor),
            )
            .where(Training.status.in_([TrainingStatus.PLANNED, TrainingStatus.IN_PROGRESS, TrainingStatus.CLOSED]))
        )
    ).scalars().all()

    for t in trainings_all:
        if t.status == TrainingStatus.PLANNED and t.start_date <= today:
            old_st = t.status.value
            t.status = TrainingStatus.IN_PROGRESS
            await log_training_audit(db, "training", t.id, "STATUS_CHANGE", "status", old_st, t.status.value, "Cambio automático por fecha de inicio")
            stats["started"] += 1
        if t.status == TrainingStatus.IN_PROGRESS and t.end_date < today:
            old_st = t.status.value
            t.status = TrainingStatus.COMPLETED
            await log_training_audit(db, "training", t.id, "STATUS_CHANGE", "status", old_st, t.status.value, "Cambio automático por fecha de fin")
            stats["finished"] += 1
    await db.commit()

    stats["retried"] = await retry_failed_notifications(db)


    days_n02 = int(params.get("alert_days_start", 7))
    days_n03 = int(params.get("alert_days_reminder", 1))
    days_n04 = int(params.get("alert_days_ending", 3))
    days_n07 = int(params.get("alert_days_cert_pending", 7))
    global_min_att = float(params.get("min_attendance_pct", 80))

    # 3. Alertas sobre capacitaciones
    for t in trainings_all:
        if t.status in (TrainingStatus.CANCELLED, TrainingStatus.DRAFT):
            continue

        days_to_start = (t.start_date - today).days
        days_to_end = (t.end_date - today).days
        min_req = float(t.min_attendance_pct if t.min_attendance_pct is not None else global_min_att)

        active_enrollments = [
            e for e in t.enrollments
            if e.status in (EnrollmentStatus.ENROLLED, EnrollmentStatus.INVITED)
        ]

        # N-02: Próximo inicio (D - 7)
        if t.status == TrainingStatus.PLANNED and days_to_start == days_n02:
            for e in active_enrollments:
                emp = e.employee
                if not emp or not emp.institutional_email:
                    continue
                res = await dispatch_training_notification(
                    db=db,
                    event_code="N-02",
                    recipient_email=emp.institutional_email,
                    entity_type="enrollment",
                    entity_id=e.id,
                    dedup_key=f"N-02:training:{t.id}:enroll:{e.id}:{today.isoformat()}",
                    scheduled_date=today,
                    recipient_id=emp.id,
                    variables={
                        "nombre": emp.full_name,
                        "capacitacion": t.name,
                        "fecha_inicio": t.start_date.strftime("%d/%m/%Y"),
                        "sede_o_enlace": _training_place(t),
                    },
                )
                if res:
                    stats["n02"] += 1

        # N-03: Recordatorio final (D - 1)
        if t.status in (TrainingStatus.PLANNED, TrainingStatus.IN_PROGRESS) and days_to_start == days_n03:
            qr_info = ""
            if t.sessions and t.sessions[0].qr_code_token:
                qr_info = f"Enlace QR de asistencia: {get_tenant_base_url().rstrip('/')}/trainings/qr/{t.sessions[0].qr_code_token}"
            for e in active_enrollments:
                emp = e.employee
                if not emp or not emp.institutional_email:
                    continue
                res = await dispatch_training_notification(
                    db=db,
                    event_code="N-03",
                    recipient_email=emp.institutional_email,
                    entity_type="enrollment",
                    entity_id=e.id,
                    dedup_key=f"N-03:training:{t.id}:enroll:{e.id}:{today.isoformat()}",
                    scheduled_date=today,
                    recipient_id=emp.id,
                    variables={
                        "nombre": emp.full_name,
                        "capacitacion": t.name,
                        "fecha_inicio": t.start_date.strftime("%d/%m/%Y"),
                        "sede_o_enlace": _training_place(t),
                        "detalle_extra": qr_info,
                    },
                )
                if res:
                    stats["n03"] += 1
            if t.internal_instructor and t.internal_instructor.institutional_email:
                await dispatch_training_notification(
                    db=db,
                    event_code="N-03",
                    recipient_email=t.internal_instructor.institutional_email,
                    entity_type="training",
                    entity_id=t.id,
                    dedup_key=f"N-03:training:{t.id}:instructor:{t.internal_instructor.id}:{today.isoformat()}",
                    scheduled_date=today,
                    recipient_id=t.internal_instructor.id,
                    variables={
                        "nombre": t.internal_instructor.full_name,
                        "capacitacion": t.name,
                        "fecha_inicio": t.start_date.strftime("%d/%m/%Y"),
                        "sede_o_enlace": _training_place(t),
                        "detalle_extra": "Recordatorio como facilitador de la capacitación.",
                    },
                )

        # N-04: Próxima conclusión (F - 3)
        if t.status in (TrainingStatus.PLANNED, TrainingStatus.IN_PROGRESS) and days_to_end == days_n04:
            for e in active_enrollments:
                emp = e.employee
                if not emp or not emp.institutional_email:
                    continue
                cur_pct, _, _, _ = await _compute_enrollment_progress(db, t, e, params)
                res = await dispatch_training_notification(
                    db=db,
                    event_code="N-04",
                    recipient_email=emp.institutional_email,
                    entity_type="enrollment",
                    entity_id=e.id,
                    dedup_key=f"N-04:training:{t.id}:enroll:{e.id}:{today.isoformat()}",
                    scheduled_date=today,
                    recipient_id=emp.id,
                    variables={
                        "nombre": emp.full_name,
                        "capacitacion": t.name,
                        "fecha_fin": t.end_date.strftime("%d/%m/%Y"),
                        "porcentaje_asistencia": cur_pct,
                        "minimo_asistencia": min_req,
                    },
                )
                if res:
                    stats["n04"] += 1

        # N-05: Riesgo por asistencia
        if t.status == TrainingStatus.IN_PROGRESS and t.sessions:
            for e in active_enrollments:
                emp = e.employee
                if not emp or not emp.institutional_email:
                    continue
                cur_pct, max_pct, _, _ = await _compute_enrollment_progress(db, t, e, params)
                if max_pct < min_req:
                    mgr_emails = await get_employee_manager_emails(db, emp)
                    res = await dispatch_training_notification(
                        db=db,
                        event_code="N-05",
                        recipient_email=emp.institutional_email,
                        entity_type="enrollment",
                        entity_id=e.id,
                        dedup_key=f"N-05:training:{t.id}:enroll:{e.id}",
                        scheduled_date=today,
                        recipient_id=emp.id,
                        cc=mgr_emails,
                        variables={
                            "nombre": emp.full_name,
                            "capacitacion": t.name,
                            "porcentaje_asistencia": cur_pct,
                            "minimo_asistencia": min_req,
                        },
                    )
                    if res:
                        stats["n05"] += 1

        # N-07: Certificado pendiente (externa cerrada + 7 días sin certificado)
        if (
            t.type == TrainingType.EXTERNAL
            and t.status == TrainingStatus.CLOSED
            and t.closed_at
            and (today - t.closed_at.date()).days >= days_n07
        ):
            th_emails = await get_th_emails(db)
            for e in t.enrollments:
                if e.status == EnrollmentStatus.ATTENDED and not e.certificate_file:
                    emp = e.employee
                    if not emp or not emp.institutional_email:
                        continue
                    res = await dispatch_training_notification(
                        db=db,
                        event_code="N-07",
                        recipient_email=emp.institutional_email,
                        entity_type="enrollment",
                        entity_id=e.id,
                        dedup_key=f"N-07:enroll:{e.id}",
                        scheduled_date=today,
                        recipient_id=emp.id,
                        cc=th_emails,
                        variables={
                            "nombre": emp.full_name,
                            "capacitacion": t.name,
                            "enlace": f"{get_tenant_base_url().rstrip('/')}/trainings/{t.id}",
                        },
                    )
                    if res:
                        stats["n07"] += 1


    # 4. Compromisos de réplica: N-08, RN-11 (cese), RN-08 + N-10 (vencimiento)
    raw_replica_days = str(params.get("alert_days_replica", "60,30,15,7"))
    replica_alert_days = {
        int(x.strip()) for x in raw_replica_days.split(",") if x.strip().isdigit()
    }
    commitments = (
        await db.execute(
            select(ReplicaCommitment)
            .options(
                selectinload(ReplicaCommitment.employee),
                selectinload(ReplicaCommitment.source_training),
            )
            .where(
                ReplicaCommitment.status.in_([
                    ReplicaStatus.PENDING.value,
                    ReplicaStatus.PROPOSED.value,
                    ReplicaStatus.SCHEDULED.value,
                ])
            )
        )
    ).scalars().all()

    th_emails = await get_th_emails(db)
    portal_replicas_url = f"{get_tenant_base_url().rstrip('/')}/portal/trainings#replicas"

    for c in commitments:
        emp = c.employee
        if emp and not emp.is_active:
            old_st = c.status
            c.status = ReplicaStatus.CANCELLED_EXIT.value
            await log_training_audit(
                db, "commitment", c.id, "STATUS_CHANGE", "status", old_st, c.status, "Colaborador cesado"
            )
            continue

        effective_due = c.extended_due_date or c.due_date
        days_left = (effective_due - today).days

        # RN-08 + N-10: Vencimiento al día siguiente de la fecha límite
        if today > effective_due:
            old_st = c.status
            c.status = ReplicaStatus.OVERDUE.value
            await log_training_audit(
                db, "commitment", c.id, "STATUS_CHANGE", "status", old_st, c.status, "Fecha límite vencida"
            )
            stats["expired_replicas"] += 1

            recipients: List[str] = []
            if emp and emp.institutional_email:
                recipients.append(emp.institutional_email)
            if emp:
                recipients.extend(await get_employee_manager_emails(db, emp))
            recipients.extend(th_emails)
            unique_recipients = list(dict.fromkeys([r for r in recipients if r]))
            if unique_recipients:
                res = await dispatch_training_notification(
                    db=db,
                    event_code="N-10",
                    recipient_email=", ".join(unique_recipients),
                    entity_type="commitment",
                    entity_id=c.id,
                    dedup_key=f"N-10:commitment:{c.id}",
                    scheduled_date=today,
                    recipient_id=emp.id if emp else None,
                    variables={
                        "nombre": emp.full_name if emp else "Colaborador",
                        "capacitacion": c.source_training.name if c.source_training else "Capacitación externa",
                        "fecha_limite": effective_due.strftime("%d/%m/%Y"),
                    },
                )
                if res:
                    stats["n10"] += 1
            continue

        # N-08: Recordatorio escalonado (60, 30, 15, 7 días) SOLO si no está programada
        if (
            c.status in (ReplicaStatus.PENDING.value, ReplicaStatus.PROPOSED.value)
            and days_left in replica_alert_days
            and emp
            and emp.institutional_email
        ):
            cc = await get_employee_manager_emails(db, emp) if days_left <= 30 else []
            res = await dispatch_training_notification(
                db=db,
                event_code="N-08",
                recipient_email=emp.institutional_email,
                entity_type="commitment",
                entity_id=c.id,
                dedup_key=f"N-08:commitment:{c.id}:d{days_left}",
                scheduled_date=today,
                recipient_id=emp.id,
                cc=cc,
                variables={
                    "nombre": emp.full_name,
                    "capacitacion": c.source_training.name if c.source_training else "Capacitación externa",
                    "fecha_limite": effective_due.strftime("%d/%m/%Y"),
                    "dias_restantes": days_left,
                    "enlace": portal_replicas_url,
                },
            )
            if res:
                stats["n08"] += 1

    await db.commit()

    # 5. N-11: Resumen semanal (lunes o forzado)
    should_send_weekly = include_weekly if include_weekly is not None else (today.weekday() == 0)
    if should_send_weekly and th_emails:
        week_end = today + timedelta(days=7)
        upcoming_cnt = len([
            t for t in trainings_all
            if t.status in (TrainingStatus.PLANNED, TrainingStatus.IN_PROGRESS)
            and today <= t.start_date <= week_end
        ])
        pending_close_cnt = len([t for t in trainings_all if t.status == TrainingStatus.COMPLETED])
        all_active_reps = (
            await db.execute(
                select(ReplicaCommitment).where(
                    ReplicaCommitment.status.in_([
                        ReplicaStatus.PENDING.value,
                        ReplicaStatus.PROPOSED.value,
                        ReplicaStatus.SCHEDULED.value,
                        ReplicaStatus.OVERDUE.value,
                    ])
                )
            )
        ).scalars().all()
        yellow_cnt = sum(
            1 for r in all_active_reps
            if r.status != ReplicaStatus.OVERDUE.value and ((r.extended_due_date or r.due_date) - today).days <= 30
        )
        red_cnt = sum(1 for r in all_active_reps if r.status == ReplicaStatus.OVERDUE.value)
        failed_cnt = len(
            (await db.execute(select(TrainingNotification).where(TrainingNotification.status == "failed"))).scalars().all()
        )
        summary_html = (
            f"<ul>"
            f"<li>Capacitaciones que inician esta semana: <strong>{upcoming_cnt}</strong></li>"
            f"<li>Capacitaciones finalizadas pendientes de cierre: <strong>{pending_close_cnt}</strong></li>"
            f"<li>Réplicas en amarillo (&le;30 días): <strong>{yellow_cnt}</strong></li>"
            f"<li>Réplicas vencidas (rojo): <strong>{red_cnt}</strong></li>"
            f"<li>Notificaciones fallidas pendientes: <strong>{failed_cnt}</strong></li>"
            f"</ul>"
        )
        res = await dispatch_training_notification(
            db=db,
            event_code="N-11",
            recipient_email=", ".join(th_emails),
            entity_type="system",
            entity_id=0,
            dedup_key=f"N-11:weekly:{today.isoformat()}",
            scheduled_date=today,
            variables={
                "detalle_extra": summary_html,
                "enlace": f"{get_tenant_base_url().rstrip('/')}/trainings/dashboard",
            },
        )
        if res:
            stats["n11"] += 1

    return stats


