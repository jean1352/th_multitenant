"""
Lógica de negocio para Compromisos de Réplica (RF-23..RF-29, RN-05..RN-11).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.auth.models import User, UserRole
from app.modules.employees.models import Employee
from app.modules.organization.models import Area, Position
from app.modules.trainings import schemas
from app.modules.trainings.models import (
    EnrollmentStatus,
    ReplicaCommitment,
    ReplicaStatus,
    SessionStatus,
    Training,
    TrainingAttendance,
    TrainingEnrollment,
    TrainingEvidence,
    TrainingSession,
    TrainingStatus,
    TrainingType,
)
from app.modules.trainings.notifications_service import _effective_presence, send_n01_convocation
from app.modules.trainings.parameters_service import get_parameters_dict
from app.modules.trainings.utils import get_manager_area_ids, log_training_audit


def compute_traffic_light(commitment: ReplicaCommitment, today: Optional[date] = None) -> str:
    """Semáforo (RF-24): green (>30d), yellow (<=30d), red (vencida / <0d)."""
    ref = today or date.today()
    if commitment.status == ReplicaStatus.COMPLETED.value:
        return "green"
    if commitment.status == ReplicaStatus.CANCELLED_EXIT.value:
        return "gray"
    if commitment.status == ReplicaStatus.OVERDUE.value:
        return "red"
    eff_due = commitment.extended_due_date or commitment.due_date
    days_left = (eff_due - ref).days
    if days_left < 0:
        return "red"
    if days_left <= 30:
        return "yellow"
    return "green"


async def get_employee_commitments(db: AsyncSession, employee_id: int) -> List[Dict[str, Any]]:
    stmt = (
        select(ReplicaCommitment)
        .options(
            selectinload(ReplicaCommitment.source_training),
            selectinload(ReplicaCommitment.replica_training),
            selectinload(ReplicaCommitment.target_area),
        )
        .where(ReplicaCommitment.employee_id == employee_id)
        .order_by(ReplicaCommitment.due_date)
    )
    items = (await db.execute(stmt)).scalars().all()
    today = date.today()
    result = []
    for c in items:
        eff_due = c.extended_due_date or c.due_date
        result.append({
            "commitment": c,
            "effective_due_date": eff_due,
            "days_remaining": (eff_due - today).days,
            "traffic_light": compute_traffic_light(c, today),
        })
    return result


async def get_replicas_inbox(
    db: AsyncSession,
    status_filter: Optional[str] = None,
    traffic_light: Optional[str] = None,
    area_id: Optional[int] = None,
    allowed_area_ids: Optional[List[int]] = None,
    search: Optional[str] = None,
) -> List[Dict[str, Any]]:
    stmt = (
        select(ReplicaCommitment)
        .join(Employee, ReplicaCommitment.employee_id == Employee.id)
        .join(Position, Employee.position_id == Position.id)
        .join(Area, Position.area_id == Area.id)
        .options(
            selectinload(ReplicaCommitment.employee)
            .selectinload(Employee.position_obj)
            .selectinload(Position.area),
            selectinload(ReplicaCommitment.source_training),
            selectinload(ReplicaCommitment.replica_training),
            selectinload(ReplicaCommitment.target_area),
        )
        .order_by(ReplicaCommitment.due_date)
    )
    if allowed_area_ids is not None:
        if not allowed_area_ids:
            return []
        stmt = stmt.where(Area.id.in_(allowed_area_ids))
    if area_id:
        stmt = stmt.where(Area.id == area_id)
    if status_filter and status_filter != "all":
        stmt = stmt.where(ReplicaCommitment.status == status_filter)
    if search:
        term = f"%{search}%"
        stmt = stmt.where(Employee.full_name.ilike(term))

    rows = (await db.execute(stmt)).scalars().all()
    today = date.today()
    out = []
    for c in rows:
        tl = compute_traffic_light(c, today)
        if traffic_light and traffic_light != "all" and tl != traffic_light:
            continue
        eff_due = c.extended_due_date or c.due_date
        out.append({
            "commitment": c,
            "effective_due_date": eff_due,
            "days_remaining": (eff_due - today).days,
            "traffic_light": tl,
            "area_name": (
                c.employee.position_obj.area.name
                if c.employee and c.employee.position_obj and c.employee.position_obj.area
                else "-"
            ),
        })
    return out



async def propose_replica(
    db: AsyncSession,
    commitment_id: int,
    employee_id: int,
    payload: schemas.ReplicaProposalCreate,
    user_id: Optional[int] = None,
    is_th_or_admin: bool = False,
) -> ReplicaCommitment:
    c = await db.get(ReplicaCommitment, commitment_id)
    if not c:
        raise ValueError("Compromiso de réplica no encontrado.")
    if not is_th_or_admin and c.employee_id != employee_id:
        raise ValueError("No tienes permiso para proponer sobre este compromiso.")
    if c.status in (ReplicaStatus.COMPLETED.value, ReplicaStatus.CANCELLED_EXIT.value):
        raise ValueError("Este compromiso ya no admite propuestas.")

    emp = (
        await db.execute(
            select(Employee).options(selectinload(Employee.position_obj)).where(Employee.id == c.employee_id)
        )
    ).scalar_one()
    target_area_id = payload.target_area_id or (emp.position_obj.area_id if emp.position_obj else None)

    target_commitments = [c]
    # RN-10: Réplica conjunta (mismos source_training_id)
    if payload.joint_commitment_ids:
        for jid in payload.joint_commitment_ids:
            if jid == c.id:
                continue
            jc = await db.get(ReplicaCommitment, jid)
            if not jc:
                raise ValueError(f"Compromiso conjunto #{jid} no encontrado.")
            if jc.source_training_id != c.source_training_id:
                raise ValueError("La réplica conjunta solo aplica a la misma capacitación externa.")
            if jc.status in (ReplicaStatus.COMPLETED.value, ReplicaStatus.CANCELLED_EXIT.value):
                raise ValueError(f"El compromiso #{jid} ya no está disponible para réplica conjunta.")
            target_commitments.append(jc)

    now = datetime.now()
    for item in target_commitments:
        old_st = item.status
        item.proposed_topic = payload.topic
        item.proposed_date = payload.proposed_date
        item.proposed_start_time = payload.start_time
        item.proposed_end_time = payload.end_time
        item.proposed_duration_hours = payload.duration_hours
        item.proposed_audience = payload.audience
        item.proposed_target_area_id = target_area_id
        item.proposed_modality = payload.modality
        item.proposed_location = payload.location
        item.proposed_at = now
        item.rejection_reason = None
        item.status = ReplicaStatus.PROPOSED.value
        await log_training_audit(
            db, "commitment", item.id, "PROPOSE", "status", old_st, item.status, payload.topic, user_id=user_id
        )

    await db.commit()
    await db.refresh(c)
    return c


async def approve_or_reject_replica(
    db: AsyncSession,
    commitment_id: int,
    payload: schemas.ReplicaApprovalPayload,
    approver_user: User,
    base_url: Optional[str] = None,
) -> ReplicaCommitment:
    """Aprueba o rechaza una propuesta de réplica (RF-25, RF-26, CA-08, CA-13)."""
    c = (
        await db.execute(
            select(ReplicaCommitment)
            .options(
                selectinload(ReplicaCommitment.employee).selectinload(Employee.position_obj),
                selectinload(ReplicaCommitment.source_training),
            )
            .where(ReplicaCommitment.id == commitment_id)
        )
    ).scalar_one_or_none()
    if not c:
        raise ValueError("Compromiso de réplica no encontrado.")

    if approver_user.role == UserRole.MANAGER:
        allowed_areas = await get_manager_area_ids(db, approver_user)
        emp_area = c.employee.position_obj.area_id if c.employee and c.employee.position_obj else None
        if emp_area not in allowed_areas:
            raise PermissionError("No tienes permiso para gestionar réplicas de otra área.")

    if c.status != ReplicaStatus.PROPOSED.value:
        raise ValueError("El compromiso debe estar en estado Propuesta para aprobar/rechazar.")

    sibling_commitments = (
        await db.execute(
            select(ReplicaCommitment)
            .options(selectinload(ReplicaCommitment.employee))
            .where(
                ReplicaCommitment.source_training_id == c.source_training_id,
                ReplicaCommitment.status == ReplicaStatus.PROPOSED.value,
                ReplicaCommitment.proposed_topic == c.proposed_topic,
                ReplicaCommitment.proposed_date == c.proposed_date,
                ReplicaCommitment.proposed_at == c.proposed_at,
            )
        )
    ).scalars().all()
    if c not in sibling_commitments:
        sibling_commitments = [c]

    if not payload.approved:
        for item in sibling_commitments:
            old_st = item.status
            item.status = ReplicaStatus.PENDING.value
            item.rejection_reason = payload.rejection_reason or "Propuesta rechazada"
            await log_training_audit(
                db, "commitment", item.id, "REJECT", "status", old_st, item.status, item.rejection_reason, user_id=approver_user.id
            )
        await db.commit()
        await db.refresh(c)
        return c

    target_area_id = c.proposed_target_area_id or (
        c.employee.position_obj.area_id if c.employee and c.employee.position_obj else None
    )
    prop_date = c.proposed_date or date.today()
    s_time = c.proposed_start_time or time(9, 0)
    e_time = c.proposed_end_time or time(10, 0)

    replica_training = Training(
        code=f"REP-{prop_date.year}-{uuid.uuid4().hex[:4].upper()}",
        name=f"Réplica: {c.proposed_topic or (c.source_training.name if c.source_training else 'Interna')}",
        description=f"Réplica interna de '{c.source_training.name if c.source_training else ''}'. Público: {c.proposed_audience or 'Área'}",
        objective=f"Transferir conocimientos de {c.source_training.name if c.source_training else ''}",
        type=TrainingType.REPLICA,
        modality=c.proposed_modality or "presencial",
        topic=c.proposed_topic,
        internal_instructor_id=c.employee_id,
        start_date=prop_date,
        end_date=prop_date,
        hours=c.proposed_duration_hours or 1.0,
        location=c.proposed_location,
        source_training_id=c.source_training_id,
        target_area_id=target_area_id,
        status=TrainingStatus.PLANNED,
        published_at=datetime.now(),
        created_by_user_id=approver_user.id,
    )
    db.add(replica_training)
    await db.flush()

    session = TrainingSession(
        training_id=replica_training.id,
        topic=c.proposed_topic or replica_training.name,
        description=c.proposed_audience,
        instructor=c.employee.full_name if c.employee else None,
        date=prop_date,
        start_time=s_time,
        end_time=e_time,
        status=SessionStatus.PENDING,
        qr_code_token=str(uuid.uuid4()),
        location_or_link=c.proposed_location,
    )
    db.add(session)
    await db.flush()

    facilitator_ids = {item.employee_id for item in sibling_commitments}
    now = datetime.now()
    for item in sibling_commitments:
        old_st = item.status
        item.replica_training_id = replica_training.id
        item.status = ReplicaStatus.SCHEDULED.value
        item.approved_by_user_id = approver_user.id
        item.approved_at = now
        await log_training_audit(
            db, "commitment", item.id, "APPROVE", "replica_training_id", old_st, str(replica_training.id), user_id=approver_user.id
        )

    enrolled_pairs: List[tuple] = []
    if target_area_id:
        area_emps = (
            await db.execute(
                select(Employee)
                .join(Position, Employee.position_id == Position.id)
                .options(selectinload(Employee.position_obj).selectinload(Position.area))
                .where(Position.area_id == target_area_id, Employee.is_active == True)  # noqa
            )
        ).scalars().all()
        for emp in area_emps:
            if emp.id in facilitator_ids:
                continue
            enroll = TrainingEnrollment(
                training_id=replica_training.id,
                employee_id=emp.id,
                status=EnrollmentStatus.ENROLLED,
                invitation_token=str(uuid.uuid4()),
            )
            db.add(enroll)
            enrolled_pairs.append((enroll, emp))

    await log_training_audit(
        db, "training", replica_training.id, "CREATE", "type", None, "replica",
        f"Aprobación compromiso #{c.id}", user_id=approver_user.id
    )
    await db.commit()

    for enroll, emp in enrolled_pairs:
        await send_n01_convocation(db, replica_training, enroll, emp, base_url=base_url, is_replica=True)

    await db.refresh(c)
    return c

async def extend_replica_commitment(
    db: AsyncSession,
    commitment_id: int,
    payload: schemas.ReplicaExtensionPayload,
    user_id: Optional[int] = None,
) -> ReplicaCommitment:
    """Otorga una única prórroga por compromiso con justificación obligatoria (RN-09, RF-28)."""
    c = await db.get(ReplicaCommitment, commitment_id)
    if not c:
        raise ValueError("Compromiso de réplica no encontrado.")
    if c.extended_due_date is not None:
        raise ValueError("Solo se permite una prórroga por compromiso.")
    if not payload.justification or not payload.justification.strip():
        raise ValueError("La justificación es obligatoria para otorgar una prórroga.")
    if payload.extended_due_date <= c.due_date:
        raise ValueError("La nueva fecha límite debe ser posterior a la fecha límite original.")
    if c.status in (ReplicaStatus.COMPLETED.value, ReplicaStatus.CANCELLED_EXIT.value):
        raise ValueError("No se puede prorrogar un compromiso ya cumplido o anulado.")

    old_due = c.due_date
    old_st = c.status
    c.extended_due_date = payload.extended_due_date
    c.extension_justification = payload.justification.strip()
    c.extension_approved_by_id = user_id
    c.extension_approved_at = datetime.now()
    if c.status == ReplicaStatus.OVERDUE.value and payload.extended_due_date >= date.today():
        c.status = ReplicaStatus.SCHEDULED.value if c.replica_training_id else ReplicaStatus.PENDING.value

    await log_training_audit(
        db, "commitment", c.id, "EXTENSION", "extended_due_date",
        f"{old_due} ({old_st})", f"{c.extended_due_date} ({c.status})",
        reason=c.extension_justification, user_id=user_id,
    )
    await db.commit()
    await db.refresh(c)
    return c


async def evaluate_replica_on_close(
    db: AsyncSession,
    replica_training: Training,
    close_date: date,
    user_id: Optional[int] = None,
) -> int:
    """Evalúa RN-07 al cerrar una capacitación tipo Réplica (CA-09)."""
    if replica_training.type != TrainingType.REPLICA:
        return 0

    commitments = (
        await db.execute(
            select(ReplicaCommitment).where(ReplicaCommitment.replica_training_id == replica_training.id)
        )
    ).scalars().all()
    if not commitments:
        return 0

    params = await get_parameters_dict(db)
    min_attendees = int(params.get("replica_min_attendees", 3))

    # Contar asistentes únicos presentes en las sesiones de la réplica
    present_enrollments = set()
    for sess in replica_training.sessions:
        atts = (
            await db.execute(
                select(TrainingAttendance).where(TrainingAttendance.session_id == sess.id)
            )
        ).scalars().all()
        for a in atts:
            if _effective_presence(a, params):
                present_enrollments.add(a.enrollment_id)

    attendees_count = len(present_enrollments)

    # Verificar evidencia cargada en la capacitación o en cualquiera de los compromisos
    ev_training = (
        await db.execute(
            select(TrainingEvidence.id).where(
                TrainingEvidence.entity_type == "training",
                TrainingEvidence.entity_id == replica_training.id,
            )
        )
    ).scalar_one_or_none()

    fulfilled = 0
    for c in commitments:
        ev_commit = (
            await db.execute(
                select(TrainingEvidence.id).where(
                    TrainingEvidence.entity_type == "commitment",
                    TrainingEvidence.entity_id == c.id,
                )
            )
        ).scalar_one_or_none()
        has_evidence = (ev_training is not None) or (ev_commit is not None)
        eff_due = c.extended_due_date or c.due_date
        within_deadline = close_date <= eff_due

        if within_deadline and attendees_count >= min_attendees and has_evidence:
            old_st = c.status
            c.status = ReplicaStatus.COMPLETED.value
            c.completed_at = close_date
            await log_training_audit(
                db, "commitment", c.id, "COMPLETE", "status", old_st, c.status,
                f"Réplica #{replica_training.id} cerrada con {attendees_count} asistentes y evidencia.",
                user_id=user_id,
            )
            fulfilled += 1
        elif not within_deadline and c.status != ReplicaStatus.COMPLETED.value:
            old_st = c.status
            c.status = ReplicaStatus.OVERDUE.value
            await log_training_audit(
                db, "commitment", c.id, "STATUS_CHANGE", "status", old_st, c.status,
                "Réplica cerrada fuera de plazo.",
                user_id=user_id,
            )

    await db.commit()
    return fulfilled


async def cancel_commitments_on_exit(
    db: AsyncSession, employee_id: int, user_id: Optional[int] = None
) -> int:
    """Marca compromisos pendientes como Anulada por cese (RN-11)."""
    commitments = (
        await db.execute(
            select(ReplicaCommitment).where(
                ReplicaCommitment.employee_id == employee_id,
                ReplicaCommitment.status.in_([
                    ReplicaStatus.PENDING.value,
                    ReplicaStatus.PROPOSED.value,
                    ReplicaStatus.SCHEDULED.value,
                ]),
            )
        )
    ).scalars().all()
    count = 0
    for c in commitments:
        old_st = c.status
        c.status = ReplicaStatus.CANCELLED_EXIT.value
        await log_training_audit(
            db, "commitment", c.id, "STATUS_CHANGE", "status", old_st, c.status,
            "Anulada por cese del colaborador", user_id=user_id
        )
        count += 1
    if count:
        await db.commit()
    return count


