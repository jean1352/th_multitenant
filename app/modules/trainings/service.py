"""
Lógica de negocio principal para el módulo de Capacitaciones.
Maneja proveedores, temas, capacitaciones, ciclo de vida, inscripciones,
cupos/lista de espera, sesiones, asistencia (manual, Excel, QR, Teams/Zoom),
cierre con cálculo de resultados, evidencias, certificados, encuestas y sincronización.
"""

from __future__ import annotations

import io
import os
import re
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import BackgroundTasks, Request, UploadFile
from sqlalchemy import delete, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from weasyprint import HTML

from app.core.config import settings
from app.modules.auth.models import User, UserRole
from app.modules.employees.models import Employee
from app.modules.notifications.service import send_email_notification
from app.modules.organization.models import Area, Currency, Position
from app.modules.trainings import schemas
from app.modules.trainings.models import (
    AttendanceMethod,
    AttendanceStatus,
    EnrollmentStatus,
    ReplicaCommitment,
    SessionStatus,
    Training,
    TrainingAttendance,
    TrainingAudit,
    TrainingEnrollment,
    TrainingEvidence,
    TrainingProvider,
    TrainingSession,
    TrainingStatus,
    TrainingSurvey,
    TrainingTopic,
    TrainingType,
)
from app.modules.trainings.notifications_service import (
    _effective_presence,
    cancel_pending_notifications_for_training,
    send_n01_convocation,
    send_n06_closure,
)
from app.modules.trainings.parameters_service import get_parameters_dict
from app.modules.trainings.replicas_service import (
    cancel_commitments_on_exit,
    evaluate_replica_on_close,
)
from app.modules.trainings.utils import (
    add_calendar_months,
    ensure_upload_dir,
    get_employee_manager_emails,
    log_training_audit,
)

_INSTRUCTOR_LOAD_OPTIONS = (
    selectinload(Training.internal_instructor)
    .selectinload(Employee.position_obj)
    .selectinload(Position.area)
    .selectinload(Area.sede),
    selectinload(Training.internal_instructor)
    .selectinload(Employee.position_obj)
    .selectinload(Position.parent),
    selectinload(Training.internal_instructor).selectinload(Employee.company),
)


# --- PROVIDER CRUD ---

async def get_providers(db: AsyncSession, active_only: bool = False) -> List[TrainingProvider]:
    stmt = select(TrainingProvider).order_by(TrainingProvider.business_name)
    if active_only:
        stmt = stmt.where(TrainingProvider.is_active == True)  # noqa
    return (await db.execute(stmt)).scalars().all()


async def create_provider(
    db: AsyncSession, data: schemas.ProviderCreate, user_id: Optional[int] = None
) -> TrainingProvider:
    exists = await db.scalar(select(TrainingProvider).where(TrainingProvider.ruc == data.ruc))
    if exists:
        raise ValueError("Ya existe un proveedor con este RUC.")

    provider = TrainingProvider(**data.model_dump())
    db.add(provider)
    await db.flush()
    await log_training_audit(db, "catalog", provider.id, "CREATE", "provider", None, provider.business_name, user_id=user_id)
    await db.commit()
    await db.refresh(provider)
    return provider


async def update_provider(
    db: AsyncSession, id: int, data: schemas.ProviderUpdate, user_id: Optional[int] = None
) -> Optional[TrainingProvider]:
    provider = await db.get(TrainingProvider, id)
    if not provider:
        return None
    for k, v in data.model_dump(exclude_unset=True).items():
        old_v = getattr(provider, k)
        if old_v != v:
            await log_training_audit(db, "catalog", provider.id, "UPDATE", k, old_v, v, user_id=user_id)
            setattr(provider, k, v)
    await db.commit()
    await db.refresh(provider)
    return provider


async def delete_provider(db: AsyncSession, id: int, user_id: Optional[int] = None) -> bool:
    provider = await db.get(TrainingProvider, id)
    if not provider:
        return False
    usage = await db.scalar(select(func.count(Training.id)).where(Training.provider_id == id))
    if usage and usage > 0:
        raise ValueError(f"No se puede eliminar: Este proveedor tiene {usage} capacitaciones asociadas.")
    await log_training_audit(db, "catalog", provider.id, "DELETE", "provider", provider.business_name, None, user_id=user_id)
    await db.delete(provider)
    await db.commit()
    return True



# --- TOPICS CRUD (RF-32) ---

async def get_topics(db: AsyncSession, active_only: bool = False) -> List[TrainingTopic]:
    stmt = select(TrainingTopic).order_by(TrainingTopic.name)
    if active_only:
        stmt = stmt.where(TrainingTopic.is_active == True)  # noqa
    return (await db.execute(stmt)).scalars().all()


async def create_topic(
    db: AsyncSession, data: schemas.TopicCreate, user_id: Optional[int] = None
) -> TrainingTopic:
    exists = await db.scalar(select(TrainingTopic).where(TrainingTopic.name == data.name))
    if exists:
        raise ValueError("Ya existe un tema con ese nombre.")
    topic = TrainingTopic(**data.model_dump())
    db.add(topic)
    await db.flush()
    await log_training_audit(db, "catalog", topic.id, "CREATE", "topic", None, topic.name, user_id=user_id)
    await db.commit()
    await db.refresh(topic)
    return topic


async def update_topic(
    db: AsyncSession, id: int, data: schemas.TopicUpdate, user_id: Optional[int] = None
) -> Optional[TrainingTopic]:
    topic = await db.get(TrainingTopic, id)
    if not topic:
        return None
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(topic, k, v)
    await log_training_audit(db, "catalog", topic.id, "UPDATE", "topic", None, topic.name, user_id=user_id)
    await db.commit()
    await db.refresh(topic)
    return topic


async def delete_topic(db: AsyncSession, id: int) -> bool:
    topic = await db.get(TrainingTopic, id)
    if not topic:
        return False
    await db.delete(topic)
    await db.commit()
    return True


# --- VALIDACIONES DE NEGOCIO (RN-01, RN-02, RN-13) ---

def _validate_external_publish(training: Training) -> None:
    """RN-02 / CA-01: Externa no se publica sin proveedor, costo, moneda y centro de costo."""
    if training.type != TrainingType.EXTERNAL:
        return
    missing = []
    if not training.provider_id:
        missing.append("proveedor")
    total_cost = float(training.cost or 0.0) or float(training.company_cost or 0.0) or float(training.cost_per_person or 0.0)
    if total_cost <= 0:
        missing.append("costo")
    if not training.currency_id and not (training.currency and training.currency.strip()):
        missing.append("moneda")
    if not training.cost_center_id:
        missing.append("centro de costo")
    if missing:
        raise ValueError(
            f"Una capacitación externa no se puede publicar sin: {', '.join(missing)}."
        )


def _check_closed_edit_permission(training: Training, current_user: Optional[User]) -> None:
    """RN-13 / RF-17: Una capacitación cerrada no se edita, salvo por Administrador TH."""
    if training.status == TrainingStatus.CLOSED:
        if not current_user or current_user.role != UserRole.ADMIN:
            raise ValueError("Una capacitación cerrada no se puede editar, salvo por Administrador TH.")


# --- TRAINING CRUD ---

async def get_trainings_paginated(
    db: AsyncSession,
    page: int = 1,
    limit: int = 9,
    search: Optional[str] = None,
    status: Optional[str] = None,
    training_type: Optional[str] = None,
    modality: Optional[str] = None,
    area_id: Optional[int] = None,
    allowed_area_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """Obtiene lista paginada de capacitaciones con filtros y alcance por área (CA-13)."""
    offset = (page - 1) * limit
    query = select(Training).options(
        *_INSTRUCTOR_LOAD_OPTIONS,
        selectinload(Training.provider_obj),
        selectinload(Training.currency_obj),
        selectinload(Training.cost_center_obj),
        selectinload(Training.sede_obj),
        selectinload(Training.target_area_obj),
    )

    if status and status != "all":
        query = query.where(Training.status == status)
    if training_type and training_type != "all":
        query = query.where(Training.type == training_type)
    if modality and modality != "all":
        query = query.where(Training.modality == modality)

    eff_areas = set(allowed_area_ids) if allowed_area_ids is not None else None
    if area_id:
        eff_areas = {area_id} if eff_areas is None else (eff_areas & {area_id})

    if eff_areas is not None:
        if not eff_areas:
            return {"data": [], "total": 0, "page": page, "limit": limit, "total_pages": 0, "has_next": False, "has_prev": False}
        area_enroll_subq = (
            select(TrainingEnrollment.training_id)
            .join(Employee, TrainingEnrollment.employee_id == Employee.id)
            .join(Position, Employee.position_id == Position.id)
            .where(Position.area_id.in_(eff_areas))
        )
        query = query.where(
            or_(
                Training.target_area_id.in_(eff_areas),
                Training.id.in_(area_enroll_subq),
            )
        )

    if search:
        term = f"%{search}%"
        query = query.join(TrainingProvider, isouter=True).where(
            or_(
                Training.name.ilike(term),
                Training.code.ilike(term),
                Training.topic.ilike(term),
                TrainingProvider.business_name.ilike(term),
            )
        )

    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0

    query = query.order_by(desc(Training.start_date), desc(Training.id)).offset(offset).limit(limit)
    items = (await db.execute(query)).scalars().all()
    total_pages = (total + limit - 1) // limit

    return {
        "data": items,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    }


async def get_training_detail(db: AsyncSession, id: int) -> Optional[Training]:
    """Obtiene el detalle completo de una capacitación."""
    stmt = (
        select(Training)
        .options(
            selectinload(Training.sessions),
            selectinload(Training.enrollments).selectinload(TrainingEnrollment.employee),
            *_INSTRUCTOR_LOAD_OPTIONS,
            selectinload(Training.provider_obj),
            selectinload(Training.currency_obj),
            selectinload(Training.cost_center_obj),
            selectinload(Training.sede_obj),
            selectinload(Training.target_area_obj),
            selectinload(Training.source_training),
        )
        .execution_options(populate_existing=True)
        .where(Training.id == id)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def create_training(
    db: AsyncSession, t: schemas.TrainingCreate, user_id: Optional[int] = None
) -> Training:
    """Crea una nueva capacitación."""
    if t.end_date < t.start_date:
        raise ValueError("La fecha de fin no puede ser anterior a la fecha de inicio.")
    data = t.model_dump()
    if data["type"] in (TrainingType.INTERNAL, TrainingType.REPLICA):
        data["provider_id"] = None
        data["cost_per_person"] = 0.0
        data["company_cost"] = 0.0
        data["cost"] = 0.0
    else:
        data["internal_instructor_id"] = None
        cost_val = float(data.get("cost") or 0.0)
        comp_cost = float(data.get("company_cost") or 0.0)
        if cost_val > 0 and comp_cost == 0:
            data["company_cost"] = cost_val
        elif comp_cost > 0 and cost_val == 0:
            data["cost"] = comp_cost

    if data.get("currency_id") and not data.get("currency"):
        curr = await db.get(Currency, data["currency_id"])
        if curr:
            data["currency"] = curr.name
    if data.get("topic_id") and not data.get("topic"):
        tp = await db.get(TrainingTopic, data["topic_id"])
        if tp:
            data["topic"] = tp.name

    new_t = Training(**data, created_by_user_id=user_id)
    if new_t.status == TrainingStatus.PLANNED:
        _validate_external_publish(new_t)
        new_t.published_at = datetime.now()

    db.add(new_t)
    await db.flush()
    if not new_t.code:
        prefix = "REP" if new_t.type == TrainingType.REPLICA else "CAP"
        new_t.code = f"{prefix}-{new_t.start_date.year}-{new_t.id:04d}"

    await log_training_audit(
        db, "training", new_t.id, "CREATE", "status", None, new_t.status.value, user_id=user_id
    )
    await db.commit()
    return await get_training_detail(db, new_t.id)


async def update_training(
    db: AsyncSession,
    id: int,
    t: schemas.TrainingUpdate,
    current_user: Optional[User] = None,
) -> Optional[Training]:
    """Actualiza una capacitación respetando RN-01, RN-02, RN-13 y auditoría."""
    training = await db.get(Training, id)
    if not training:
        return None

    _check_closed_edit_permission(training, current_user)
    is_closed_correction = training.status == TrainingStatus.CLOSED

    data = t.model_dump(exclude_unset=True)
    correction_reason = data.pop("correction_reason", None)

    if "type" in data and data["type"] != training.type:
        if training.status != TrainingStatus.DRAFT:
            raise ValueError("El tipo de capacitación no se puede cambiar después de publicarla.")

    if "type" in data:
        if data["type"] in (TrainingType.INTERNAL, TrainingType.REPLICA):
            data["provider_id"] = None
            data["cost_per_person"] = 0.0
            data["company_cost"] = 0.0
            data["cost"] = 0.0
        else:
            data["internal_instructor_id"] = None

    if "cost" in data and data["cost"] is not None and "company_cost" not in data:
        data["company_cost"] = data["cost"]
    elif "company_cost" in data and data["company_cost"] is not None and "cost" not in data:
        data["cost"] = data["company_cost"]

    if data.get("currency_id") and not data.get("currency"):
        curr = await db.get(Currency, data["currency_id"])
        if curr:
            data["currency"] = curr.name

    dates_changed = (
        ("start_date" in data and data["start_date"] != training.start_date)
        or ("end_date" in data and data["end_date"] != training.end_date)
    )
    eff_start = data.get("start_date", training.start_date)
    eff_end = data.get("end_date", training.end_date)
    if eff_end < eff_start:
        raise ValueError("La fecha de fin no puede ser anterior a la fecha de inicio.")
    old_status = training.status

    for key, value in data.items():
        old_val = getattr(training, key)
        if old_val != value:
            await log_training_audit(
                db,
                "training",
                training.id,
                "CORRECTION" if is_closed_correction else "UPDATE",
                field=key,
                old_value=old_val.value if hasattr(old_val, "value") else old_val,
                new_value=value.value if hasattr(value, "value") else value,
                reason=correction_reason,
                user_id=current_user.id if current_user else None,
            )
            setattr(training, key, value)

    if old_status == TrainingStatus.DRAFT and training.status == TrainingStatus.PLANNED:
        _validate_external_publish(training)
        training.published_at = datetime.now()

    await db.commit()

    if training.status == TrainingStatus.CANCELLED or dates_changed:
        await cancel_pending_notifications_for_training(db, training.id)

    return await get_training_detail(db, id)



async def publish_training(
    db: AsyncSession, id: int, user_id: Optional[int] = None
) -> Training:
    """Publica una capacitación (DRAFT -> PLANNED) validando RN-02."""
    training = await db.get(Training, id)
    if not training:
        raise ValueError("Capacitación no encontrada.")
    if training.status != TrainingStatus.DRAFT:
        raise ValueError("Solo se pueden publicar capacitaciones en estado Borrador.")
    _validate_external_publish(training)
    old_st = training.status.value
    training.status = TrainingStatus.PLANNED
    training.published_at = datetime.now()
    await log_training_audit(
        db, "training", training.id, "STATUS_CHANGE", "status", old_st, training.status.value, "Publicación", user_id=user_id
    )
    await db.commit()
    return await get_training_detail(db, id)


async def cancel_training(
    db: AsyncSession, id: int, reason: Optional[str] = None, user_id: Optional[int] = None
) -> Training:
    """Cancela una capacitación, anula alertas pendientes y avisa a inscritos."""
    training = await get_training_detail(db, id)
    if not training:
        raise ValueError("Capacitación no encontrada.")
    if training.status == TrainingStatus.CLOSED:
        raise ValueError("No se puede cancelar una capacitación ya cerrada.")
    old_st = training.status.value
    training.status = TrainingStatus.CANCELLED
    await log_training_audit(
        db, "training", training.id, "CANCEL", "status", old_st, training.status.value, reason=reason, user_id=user_id
    )
    await db.commit()
    await cancel_pending_notifications_for_training(db, training.id)

    enrolls = (
        await db.execute(
            select(TrainingEnrollment)
            .options(selectinload(TrainingEnrollment.employee))
            .where(
                TrainingEnrollment.training_id == id,
                TrainingEnrollment.status.in_([EnrollmentStatus.ENROLLED, EnrollmentStatus.INVITED]),
            )
        )
    ).scalars().all()
    for e in enrolls:
        if e.employee and e.employee.institutional_email:
            await send_email_notification(
                db,
                e.employee.institutional_email,
                f"Capacitación cancelada: {training.name}",
                f"<p>Hola {e.employee.full_name},</p><p>Informamos que la capacitación <strong>{training.name}</strong> ha sido cancelada. {reason or ''}</p>",
                is_html=True,
            )
    return await get_training_detail(db, id)


async def duplicate_training(
    db: AsyncSession, id: int, user_id: Optional[int] = None
) -> Training:
    """Duplica una capacitación para crear una nueva edición en Borrador (RF-05)."""
    orig = await get_training_detail(db, id)
    if not orig:
        raise ValueError("Capacitación no encontrada.")
    copy_t = Training(
        name=f"{orig.name} (Nueva Edición)",
        description=orig.description,
        objective=orig.objective,
        type=orig.type,
        modality=orig.modality,
        topic_id=orig.topic_id,
        topic=orig.topic,
        provider_id=orig.provider_id,
        cost_per_person=orig.cost_per_person,
        company_cost=orig.company_cost,
        cost=orig.cost,
        currency_id=orig.currency_id,
        currency=orig.currency,
        cost_center_id=orig.cost_center_id,
        internal_instructor_id=orig.internal_instructor_id,
        start_date=orig.start_date,
        end_date=orig.end_date,
        hours=orig.hours,
        capacity=orig.capacity,
        sede_id=orig.sede_id,
        location=orig.location,
        meeting_url=orig.meeting_url,
        requires_manager_approval=orig.requires_manager_approval,
        min_passing_score=orig.min_passing_score,
        min_attendance_pct=orig.min_attendance_pct,
        target_area_id=orig.target_area_id,
        status=TrainingStatus.DRAFT,
        created_by_user_id=user_id,
    )
    db.add(copy_t)
    await db.flush()
    copy_t.code = f"CAP-{copy_t.start_date.year}-{copy_t.id:04d}"
    await log_training_audit(
        db, "training", copy_t.id, "DUPLICATE", "source_id", str(orig.id), str(copy_t.id), user_id=user_id
    )
    await db.commit()
    return await get_training_detail(db, copy_t.id)


async def delete_training(db: AsyncSession, id: int, current_user: Optional[User] = None) -> bool:
    """Elimina una capacitación (protegida si está cerrada salvo Admin)."""
    training = await db.get(Training, id)
    if not training:
        return False
    _check_closed_edit_permission(training, current_user)
    await db.delete(training)
    await db.commit()
    return True


# --- ENROLLMENT & INVITATIONS ---

async def get_enrollments_paginated(
    db: AsyncSession,
    training_id: int,
    page: int = 1,
    limit: int = 10,
    search: Optional[str] = None,
    area_id: Optional[int] = None,
    allowed_area_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """Obtiene lista paginada de inscritos con filtros de área y búsqueda."""
    offset = (page - 1) * limit
    query = (
        select(TrainingEnrollment)
        .join(Employee)
        .join(Position, Employee.position_id == Position.id)
        .join(Area, Position.area_id == Area.id)
        .options(
            selectinload(TrainingEnrollment.employee)
            .selectinload(Employee.position_obj)
            .selectinload(Position.area),
            selectinload(TrainingEnrollment.survey),
        )
        .where(TrainingEnrollment.training_id == training_id)
    )

    if allowed_area_ids is not None:
        if not allowed_area_ids:
            return {"data": [], "total": 0, "page": page, "limit": limit, "total_pages": 0, "has_next": False, "has_prev": False}
        query = query.where(Area.id.in_(allowed_area_ids))
    if area_id:
        query = query.where(Area.id == area_id)

    if search:
        term = f"%{search}%"
        query = query.where(
            or_(
                Employee.full_name.ilike(term),
                Employee.document_id.ilike(term),
            )
        )

    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0

    query = query.order_by(Employee.full_name).offset(offset).limit(limit)
    items = (await db.execute(query)).scalars().all()
    total_pages = (total + limit - 1) // limit

    return {
        "data": items,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    }


async def _active_seats_count(db: AsyncSession, training_id: int) -> int:
    return await db.scalar(
        select(func.count(TrainingEnrollment.id)).where(
            TrainingEnrollment.training_id == training_id,
            TrainingEnrollment.status.in_([
                EnrollmentStatus.ENROLLED,
                EnrollmentStatus.INVITED,
                EnrollmentStatus.PENDING_APPROVAL,
            ]),
        )
    ) or 0


async def _promote_waitlist(db: AsyncSession, training: Training, base_url: Optional[str] = None) -> Optional[TrainingEnrollment]:
    """RN-12: Sube al primero en lista de espera si se libera un cupo."""
    if training.capacity is not None:
        seats = await _active_seats_count(db, training.id)
        if seats >= training.capacity:
            return None

    next_enroll = (
        await db.execute(
            select(TrainingEnrollment)
            .options(selectinload(TrainingEnrollment.employee).selectinload(Employee.position_obj).selectinload(Position.area))
            .where(
                TrainingEnrollment.training_id == training.id,
                TrainingEnrollment.status == EnrollmentStatus.WAITLIST,
            )
            .order_by(TrainingEnrollment.waitlist_position.asc(), TrainingEnrollment.id.asc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if not next_enroll:
        return None

    next_enroll.status = EnrollmentStatus.ENROLLED
    next_enroll.waitlist_position = None
    await log_training_audit(
        db, "enrollment", next_enroll.id, "PROMOTE_WAITLIST", "status", "waitlist", "enrolled"
    )
    await db.commit()
    if next_enroll.employee:
        await send_n01_convocation(db, training, next_enroll, next_enroll.employee, base_url=base_url)
    return next_enroll


async def enroll_employee(
    db: AsyncSession,
    training_id: int,
    employee_id: int,
    request_approval: bool = False,
    send_n01: bool = True,
    base_url: Optional[str] = None,
    user_id: Optional[int] = None,
) -> TrainingEnrollment:
    """Inscribe a un colaborador respetando cupo/lista de espera (RN-12) y enviando N-01 + .ics (CA-02)."""
    training = await db.get(Training, training_id)
    if not training:
        raise ValueError("Capacitación no encontrada")
    if training.status in (TrainingStatus.CLOSED, TrainingStatus.CANCELLED):
        raise ValueError("No se puede inscribir en una capacitación cerrada o cancelada.")

    exists = await db.scalar(
        select(TrainingEnrollment).where(
            TrainingEnrollment.training_id == training_id,
            TrainingEnrollment.employee_id == employee_id,
            TrainingEnrollment.status.notin_([EnrollmentStatus.WITHDRAWN, EnrollmentStatus.DECLINED]),
        )
    )
    if exists:
        raise ValueError("Empleado ya inscrito")

    emp = (
        await db.execute(
            select(Employee)
            .options(selectinload(Employee.position_obj).selectinload(Position.area))
            .where(Employee.id == employee_id)
        )
    ).scalar_one_or_none()
    if not emp:
        raise ValueError("Colaborador no encontrado")

    waitlist_pos = None
    if request_approval and training.requires_manager_approval:
        target_status = EnrollmentStatus.PENDING_APPROVAL
    elif training.capacity is not None and (await _active_seats_count(db, training_id)) >= training.capacity:
        target_status = EnrollmentStatus.WAITLIST
        max_pos = await db.scalar(
            select(func.max(TrainingEnrollment.waitlist_position)).where(
                TrainingEnrollment.training_id == training_id
            )
        ) or 0
        waitlist_pos = max_pos + 1
    else:
        target_status = EnrollmentStatus.ENROLLED

    enrollment = TrainingEnrollment(
        training_id=training_id,
        employee_id=employee_id,
        status=target_status,
        waitlist_position=waitlist_pos,
        invitation_token=str(uuid.uuid4()),
    )
    db.add(enrollment)
    await db.flush()
    await log_training_audit(
        db, "enrollment", enrollment.id, "CREATE", "status", None, target_status.value, user_id=user_id
    )
    await db.commit()

    if target_status == EnrollmentStatus.ENROLLED and send_n01:
        await send_n01_convocation(db, training, enrollment, emp, base_url=base_url)
    elif target_status == EnrollmentStatus.PENDING_APPROVAL:
        mgrs = await get_employee_manager_emails(db, emp)
        if mgrs:
            await send_email_notification(
                db,
                ", ".join(mgrs),
                f"Solicitud de inscripción: {emp.full_name} - {training.name}",
                f"<p>{emp.full_name} solicitó inscripción a <strong>{training.name}</strong>. Ingresa al sistema para aprobar o rechazar.</p>",
                is_html=True,
            )

    await db.refresh(enrollment)
    return enrollment


async def bulk_enroll(
    db: AsyncSession,
    training_id: int,
    payload: schemas.BulkEnrollPayload,
    base_url: Optional[str] = None,
    user_id: Optional[int] = None,
) -> Dict[str, int]:
    """Inscripción masiva por lista de empleados, áreas o cargos (RF-08)."""
    emp_ids = set(payload.employee_ids)
    if payload.area_ids:
        rows = (
            await db.execute(
                select(Employee.id)
                .join(Position, Employee.position_id == Position.id)
                .where(Position.area_id.in_(payload.area_ids), Employee.is_active == True)  # noqa
            )
        ).scalars().all()
        emp_ids.update(rows)
    if payload.position_ids:
        rows = (
            await db.execute(
                select(Employee.id).where(
                    Employee.position_id.in_(payload.position_ids), Employee.is_active == True  # noqa
                )
            )
        ).scalars().all()
        emp_ids.update(rows)

    enrolled_cnt = 0
    waitlist_cnt = 0
    skipped_cnt = 0
    for eid in sorted(emp_ids):
        try:
            res = await enroll_employee(db, training_id, eid, base_url=base_url, user_id=user_id)
            if res.status == EnrollmentStatus.WAITLIST:
                waitlist_cnt += 1
            else:
                enrolled_cnt += 1
        except ValueError:
            skipped_cnt += 1
    return {"enrolled": enrolled_cnt, "waitlist": waitlist_cnt, "skipped": skipped_cnt}



async def bulk_enroll_from_excel(
    db: AsyncSession,
    training_id: int,
    file_bytes: bytes,
    base_url: Optional[str] = None,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Carga masiva de inscritos desde Excel por documento o correo (RF-08)."""
    df = pd.read_excel(io.BytesIO(file_bytes))
    cols = {str(c).strip().lower(): c for c in df.columns}
    doc_col = cols.get("documento") or cols.get("document_id") or cols.get("ci") or cols.get("dni")
    email_col = cols.get("correo") or cols.get("email") or cols.get("institutional_email")
    if not doc_col and not email_col:
        raise ValueError("El Excel debe contener una columna 'documento' o 'correo'.")

    emp_ids: List[int] = []
    not_found: List[str] = []
    for _, row in df.iterrows():
        emp = None
        if doc_col and pd.notna(row[doc_col]):
            doc = str(row[doc_col]).strip()
            emp = await db.scalar(select(Employee).where(Employee.document_id == doc, Employee.is_active == True))  # noqa
        if not emp and email_col and pd.notna(row[email_col]):
            em = str(row[email_col]).strip()
            emp = await db.scalar(select(Employee).where(Employee.institutional_email == em, Employee.is_active == True))  # noqa
        if emp:
            emp_ids.append(emp.id)
        else:
            not_found.append(str(row[doc_col] if doc_col else row[email_col]))

    res = await bulk_enroll(
        db, training_id, schemas.BulkEnrollPayload(employee_ids=emp_ids), base_url=base_url, user_id=user_id
    )
    res["not_found"] = not_found
    return res


async def approve_enrollment_request(
    db: AsyncSession,
    enrollment_id: int,
    approved: bool,
    approver_user: User,
    base_url: Optional[str] = None,
) -> TrainingEnrollment:
    """Aprueba o rechaza una solicitud de inscripción (RF-10)."""
    enroll = (
        await db.execute(
            select(TrainingEnrollment)
            .options(
                selectinload(TrainingEnrollment.training),
                selectinload(TrainingEnrollment.employee).selectinload(Employee.position_obj).selectinload(Position.area),
            )
            .where(TrainingEnrollment.id == enrollment_id)
        )
    ).scalar_one_or_none()
    if not enroll:
        raise ValueError("Inscripción no encontrada")
    if enroll.status != EnrollmentStatus.PENDING_APPROVAL:
        raise ValueError("La inscripción no está pendiente de aprobación.")

    old_st = enroll.status.value
    if not approved:
        enroll.status = EnrollmentStatus.DECLINED
    else:
        t = enroll.training
        if t.capacity is not None and (await _active_seats_count(db, t.id)) > t.capacity:
            enroll.status = EnrollmentStatus.WAITLIST
            max_pos = await db.scalar(
                select(func.max(TrainingEnrollment.waitlist_position)).where(TrainingEnrollment.training_id == t.id)
            ) or 0
            enroll.waitlist_position = max_pos + 1
        else:
            enroll.status = EnrollmentStatus.ENROLLED
            enroll.approved_by_user_id = approver_user.id
            enroll.approved_at = datetime.now()

    await log_training_audit(
        db, "enrollment", enroll.id, "APPROVE" if approved else "REJECT", "status", old_st, enroll.status.value, user_id=approver_user.id
    )
    await db.commit()
    if enroll.status == EnrollmentStatus.ENROLLED and enroll.employee:
        await send_n01_convocation(db, enroll.training, enroll, enroll.employee, base_url=base_url)
    await db.refresh(enroll)
    return enroll


async def withdraw_enrollment(
    db: AsyncSession,
    enrollment_id: int,
    user_id: Optional[int] = None,
    base_url: Optional[str] = None,
) -> TrainingEnrollment:
    """Da de baja una inscripción antes del inicio y promueve lista de espera (RN-12)."""
    enroll = (
        await db.execute(
            select(TrainingEnrollment)
            .options(selectinload(TrainingEnrollment.training))
            .where(TrainingEnrollment.id == enrollment_id)
        )
    ).scalar_one_or_none()
    if not enroll:
        raise ValueError("Inscripción no encontrada")
    if enroll.training.status == TrainingStatus.CLOSED:
        raise ValueError("No se puede dar de baja en una capacitación cerrada.")

    old_st = enroll.status.value
    enroll.status = EnrollmentStatus.WITHDRAWN
    enroll.waitlist_position = None
    await log_training_audit(
        db, "enrollment", enroll.id, "WITHDRAW", "status", old_st, enroll.status.value, user_id=user_id
    )
    await db.commit()
    await _promote_waitlist(db, enroll.training, base_url=base_url)
    await db.refresh(enroll)
    return enroll


async def update_enrollment_score(
    db: AsyncSession,
    enrollment_id: int,
    data: schemas.EnrollmentScoreUpdate,
    current_user: Optional[User] = None,
) -> TrainingEnrollment:
    enroll = (
        await db.execute(
            select(TrainingEnrollment)
            .options(selectinload(TrainingEnrollment.training))
            .where(TrainingEnrollment.id == enrollment_id)
        )
    ).scalar_one_or_none()
    if not enroll:
        raise ValueError("Inscripción no encontrada")
    _check_closed_edit_permission(enroll.training, current_user)
    old_score = enroll.knowledge_score
    enroll.knowledge_score = data.knowledge_score
    if data.feedback is not None:
        enroll.feedback = data.feedback
    await log_training_audit(
        db, "enrollment", enroll.id, "UPDATE", "knowledge_score", old_score, data.knowledge_score,
        user_id=current_user.id if current_user else None,
    )
    await db.commit()
    await db.refresh(enroll)
    return enroll


async def _send_invitation_email_bg(
    db_session_factory,
    recipient_email: str,
    subject: str,
    body: str,
    enrollment_id: int,
    ics_bytes: Optional[bytes] = None,
    training_id: Optional[int] = None,
    cc: Optional[List[str]] = None,
):
    """Worker para enviar invitaciones en background con adjunto .ics."""
    async with db_session_factory() as db:
        attachments = [(f"capacitacion_{training_id or enrollment_id}.ics", ics_bytes, "text/calendar")] if ics_bytes else None
        log_entry = await send_email_notification(
            db, recipient_email, subject, body, is_html=True, cc=cc, attachments=attachments
        )
        if log_entry and log_entry.status.value == "sent":
            enroll = await db.get(TrainingEnrollment, enrollment_id)
            if enroll:
                enroll.invitation_sent_at = date.today()
                await db.commit()


async def send_mass_invitations(
    db: AsyncSession,
    training_id: int,
    payload: schemas.InvitationPayload,
    request: Request,
    background_tasks: BackgroundTasks,
    db_session_factory,
) -> int:
    """
    Envía invitaciones masivas para una capacitación con adjunto .ics.
    Respeta el cupo (RN-12): si se llena el cupo, quedan en lista de espera.
    """
    training = await get_training_detail(db, training_id)
    if not training:
        raise ValueError("Capacitación no encontrada.")

    query = (
        select(Employee)
        .join(Position)
        .join(Area)
        .options(selectinload(Employee.position_obj).selectinload(Position.area))
        .where(Employee.is_active == True, Employee.institutional_email.is_not(None))  # noqa
    )

    if payload.sede_ids:
        query = query.where(Area.sede_id.in_(payload.sede_ids))
    if payload.area_ids:
        query = query.where(Area.id.in_(payload.area_ids))

    employees = (await db.execute(query)).scalars().all()
    count = 0
    base_url = str(request.base_url).rstrip("/")
    from app.modules.trainings.utils import generate_training_ics

    for emp in employees:
        existing = await db.scalar(
            select(TrainingEnrollment).where(
                TrainingEnrollment.training_id == training_id,
                TrainingEnrollment.employee_id == emp.id,
            )
        )

        enrollment = existing
        token = str(uuid.uuid4())
        is_waitlist = False

        if not existing:
            if training.capacity is not None and (await _active_seats_count(db, training_id)) >= training.capacity:
                max_pos = await db.scalar(
                    select(func.max(TrainingEnrollment.waitlist_position)).where(
                        TrainingEnrollment.training_id == training_id
                    )
                ) or 0
                enrollment = TrainingEnrollment(
                    training_id=training_id,
                    employee_id=emp.id,
                    status=EnrollmentStatus.WAITLIST,
                    waitlist_position=max_pos + 1,
                    invitation_token=token,
                )
                is_waitlist = True
            else:
                enrollment = TrainingEnrollment(
                    training_id=training_id,
                    employee_id=emp.id,
                    status=EnrollmentStatus.INVITED,
                    invitation_token=token,
                )
            db.add(enrollment)
        elif existing.status == EnrollmentStatus.INVITED:
            existing.invitation_token = token
            enrollment = existing
        else:
            continue

        await db.flush()
        if is_waitlist:
            continue

        link = f"{base_url}/trainings/public/respond/{token}"
        personal_body = (
            payload.html_body.replace("{{name}}", emp.full_name)
            .replace("{{link}}", link)
        )
        ics_bytes = generate_training_ics(
            training,
            sessions=training.sessions,
            attendee_email=emp.institutional_email,
            attendee_name=emp.full_name,
        )
        cc_emails = await get_employee_manager_emails(db, emp)

        if emp.all_emails:
            background_tasks.add_task(
                _send_invitation_email_bg,
                db_session_factory,
                emp.all_emails,
                payload.subject,
                personal_body,
                enrollment.id,
                ics_bytes,
                training.id,
                cc_emails,
            )
            count += 1

    await db.commit()
    return count


async def process_public_response(
    db: AsyncSession, token: str, action: str, base_url: Optional[str] = None
) -> Optional[Training]:
    """Procesa la respuesta del empleado a la invitación (RF-12)."""
    stmt = (
        select(TrainingEnrollment)
        .options(selectinload(TrainingEnrollment.training))
        .where(TrainingEnrollment.invitation_token == token)
    )
    enrollment = (await db.execute(stmt)).scalar_one_or_none()

    if not enrollment:
        return None

    training = enrollment.training
    if action == "confirm":
        enrollment.status = EnrollmentStatus.ENROLLED
        enrollment.confirmed_at = datetime.now()
        await db.commit()
    elif action == "decline":
        enrollment.status = EnrollmentStatus.DECLINED
        await db.commit()
        await _promote_waitlist(db, training, base_url=base_url)
    return training


async def get_training_by_token(
    db: AsyncSession, token: str
) -> Optional[Training]:
    stmt = (
        select(TrainingEnrollment)
        .options(selectinload(TrainingEnrollment.training))
        .where(TrainingEnrollment.invitation_token == token)
    )
    enrollment = (await db.execute(stmt)).scalar_one_or_none()
    return enrollment.training if enrollment else None


async def send_reminder_to_enrolled(
    background_tasks: BackgroundTasks,
    db_session_factory,
    training_id: int,
) -> int:
    """Encola la tarea de envío de recordatorios masivos."""
    background_tasks.add_task(
        _process_reminders_bg, db_session_factory, training_id
    )
    return 1


async def _process_reminders_bg(db_session_factory, training_id: int):
    """Tarea en segundo plano para enviar correos de recordatorio."""
    async with db_session_factory() as db:
        stmt = (
            select(Employee)
            .join(TrainingEnrollment)
            .where(
                TrainingEnrollment.training_id == training_id,
                TrainingEnrollment.status == EnrollmentStatus.ENROLLED, # Solo a confirmados
                Employee.institutional_email.is_not(None),
            )
        )
        employees = (await db.execute(stmt)).scalars().all()
        training = await db.get(Training, training_id)

        if not training:
            return

        for emp in employees:
            if emp.all_emails:
                await send_email_notification(
                    db,
                    emp.all_emails,
                    f"🔔 Recordatorio: {training.name}",
                    f"Hola {emp.full_name},\n\n"
                    f"Te recordamos tu participación en la capacitación "
                    f"'{training.name}' que inicia el {training.start_date}.\n\n"
                    f"¡Te esperamos!",
                )


# --- SESSIONS & ATTENDANCE ---

async def create_session(
    db: AsyncSession,
    training_id: int,
    data: schemas.SessionCreate,
    current_user: Optional[User] = None,
) -> TrainingSession:
    training = await db.get(Training, training_id)
    if not training:
        raise ValueError("Capacitación no encontrada")
    _check_closed_edit_permission(training, current_user)
    session = TrainingSession(
        training_id=training_id,
        **data.model_dump(),
        status=SessionStatus.PENDING,
        qr_code_token=str(uuid.uuid4()),
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def generate_sessions(
    db: AsyncSession,
    training_id: int,
    gen: schemas.SessionGenerator,
    current_user: Optional[User] = None,
):
    """Genera sesiones automáticamente según rango de fechas y días."""
    training = await db.get(Training, training_id)
    if not training:
        raise ValueError("Capacitación no encontrada")
    _check_closed_edit_permission(training, current_user)

    sessions = []
    current_date = gen.start_date
    while current_date <= gen.end_date:
        if current_date.weekday() in gen.days_of_week:
            session = TrainingSession(
                training_id=training_id,
                topic=gen.topic,
                description=gen.description,
                instructor=gen.instructor,
                date=current_date,
                start_time=gen.start_time,
                end_time=gen.end_time,
                status=SessionStatus.PENDING,
                qr_code_token=str(uuid.uuid4()),
                location_or_link=gen.location_or_link,
            )
            sessions.append(session)
        current_date += timedelta(days=1)

    if sessions:
        db.add_all(sessions)
        await db.commit()
    return len(sessions)


async def update_session(
    db: AsyncSession,
    session_id: int,
    data: schemas.SessionUpdate,
    current_user: Optional[User] = None,
) -> Optional[TrainingSession]:
    """Actualiza los datos de una sesión."""
    session = await db.get(TrainingSession, session_id)
    if not session:
        return None
    training = await db.get(Training, session.training_id)
    if training:
        _check_closed_edit_permission(training, current_user)

    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(session, key, value)

    await db.commit()
    await db.refresh(session)
    return session


async def delete_session(
    db: AsyncSession, session_id: int, current_user: Optional[User] = None
) -> bool:
    """Elimina una sesión."""
    session = await db.get(TrainingSession, session_id)
    if not session:
        return False
    training = await db.get(Training, session.training_id)
    if training:
        _check_closed_edit_permission(training, current_user)
    await db.delete(session)
    await db.commit()
    return True


async def _recalculate_training_attendance_pct(db: AsyncSession, training_id: int) -> None:
    """RF-15 / RN-03: Recalcula el % de asistencia por participante."""
    params = await get_parameters_dict(db)
    sessions = (
        await db.execute(select(TrainingSession).where(TrainingSession.training_id == training_id))
    ).scalars().all()
    total_sessions = len(sessions)
    enrollments = (
        await db.execute(
            select(TrainingEnrollment)
            .options(selectinload(TrainingEnrollment.attendances))
            .execution_options(populate_existing=True)
            .where(TrainingEnrollment.training_id == training_id)
        )
    ).scalars().all()

    for enroll in enrollments:
        if total_sessions == 0:
            enroll.attendance_pct = 0.0
            continue
        present_cnt = sum(1 for a in enroll.attendances if _effective_presence(a, params))
        enroll.attendance_pct = round((present_cnt / total_sessions) * 100.0, 2)


async def get_session_attendance(db: AsyncSession, session_id: int):
    """Obtiene la lista de asistencia para una sesión."""
    session = await db.get(TrainingSession, session_id)
    if not session:
        return None

    enrollments = (
        await db.execute(
            select(TrainingEnrollment)
            .options(selectinload(TrainingEnrollment.employee))
            .where(
                TrainingEnrollment.training_id == session.training_id,
                TrainingEnrollment.status.in_([
                    EnrollmentStatus.ENROLLED,
                    EnrollmentStatus.ATTENDED,
                    EnrollmentStatus.FAILED,
                ]),
            )
        )
    ).scalars().all()

    attendances = (
        await db.execute(
            select(TrainingAttendance).where(TrainingAttendance.session_id == session_id)
        )
    ).scalars().all()

    att_map = {a.enrollment_id: a for a in attendances}
    result = []

    for enroll in enrollments:
        att = att_map.get(enroll.id)
        st_val = (
            att.attendance_status
            if att and att.attendance_status
            else (AttendanceStatus.PRESENT.value if att and att.is_present else AttendanceStatus.ABSENT.value)
        )
        result.append(
            {
                "enrollment_id": enroll.id,
                "employee_name": enroll.employee.full_name,
                "document_id": enroll.employee.document_id,
                "is_present": att.is_present if att else False,
                "attendance_status": st_val,
                "method": att.method if att else None,
                "notes": att.notes if att else "",
            }
        )
    return result


async def save_attendance(
    db: AsyncSession,
    session_id: int,
    data: schemas.AttendanceList,
    current_user: Optional[User] = None,
):
    """Guarda o actualiza la asistencia de una sesión (RF-13, RF-14, RF-15, RF-17)."""
    session = await db.get(TrainingSession, session_id)
    if not session:
        return False
    training = await db.get(Training, session.training_id)
    if training:
        _check_closed_edit_permission(training, current_user)

    params = await get_parameters_dict(db)
    await db.execute(delete(TrainingAttendance).where(TrainingAttendance.session_id == session_id))

    now = datetime.now()
    new_records = []
    for item in data.attendances:
        att_status = item.attendance_status or (
            AttendanceStatus.PRESENT.value if item.is_present else AttendanceStatus.ABSENT.value
        )
        tmp = TrainingAttendance(is_present=item.is_present, attendance_status=att_status)
        effective_pres = _effective_presence(tmp, params)
        new_records.append(
            TrainingAttendance(
                session_id=session_id,
                enrollment_id=item.enrollment_id,
                is_present=effective_pres,
                attendance_status=att_status,
                notes=item.notes,
                recorded_at=now,
                method=data.method or AttendanceMethod.MANUAL.value,
                recorded_by_user_id=current_user.id if current_user else None,
            )
        )

    db.add_all(new_records)
    session.status = SessionStatus.CLOSED
    await db.flush()
    await _recalculate_training_attendance_pct(db, session.training_id)
    if training and training.status == TrainingStatus.CLOSED:
        await log_training_audit(
            db, "attendance", session_id, "CORRECTION", "session_attendance", None,
            f"{len(new_records)} registros", reason="Corrección Admin TH",
            user_id=current_user.id if current_user else None,
        )
    await db.commit()
    return True


async def toggle_session_status(
    db: AsyncSession, session_id: int, status: SessionStatus
):
    """Cambia el estado de una sesión manualmente."""
    session = await db.get(TrainingSession, session_id)
    if not session:
        return False
    session.status = status
    await db.commit()
    return True



async def checkin_qr(
    db: AsyncSession,
    token: str,
    employee_id: int,
    now_override: Optional[datetime] = None,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Registra asistencia vía QR validando ventana de tiempo e inscripción (RF-13, CA-06)."""
    session = (
        await db.execute(
            select(TrainingSession)
            .options(selectinload(TrainingSession.training))
            .where(TrainingSession.qr_code_token == token)
        )
    ).scalar_one_or_none()
    if not session:
        raise ValueError("Código QR inválido o sesión no encontrada.")

    training = session.training
    if training.status in (TrainingStatus.CLOSED, TrainingStatus.CANCELLED):
        raise ValueError("No se puede registrar asistencia en una capacitación cerrada o cancelada.")

    enroll = (
        await db.execute(
            select(TrainingEnrollment).where(
                TrainingEnrollment.training_id == training.id,
                TrainingEnrollment.employee_id == employee_id,
                TrainingEnrollment.status.in_([EnrollmentStatus.ENROLLED, EnrollmentStatus.ATTENDED]),
            )
        )
    ).scalar_one_or_none()
    if not enroll:
        raise ValueError("No estás inscrito en esta capacitación.")

    params = await get_parameters_dict(db)
    window_minutes = int(params.get("qr_window_minutes", 30))
    now = now_override or datetime.now()
    session_start = datetime.combine(session.date, session.start_time)
    window_end = session_start + timedelta(minutes=window_minutes)

    if now < session_start or now > window_end:
        raise ValueError(
            f"Fuera de la ventana de asistencia QR ({session_start.strftime('%d/%m %H:%M')} - {window_end.strftime('%H:%M')})."
        )

    att = (
        await db.execute(
            select(TrainingAttendance).where(
                TrainingAttendance.session_id == session.id,
                TrainingAttendance.enrollment_id == enroll.id,
            )
        )
    ).scalar_one_or_none()

    if not att:
        att = TrainingAttendance(
            session_id=session.id,
            enrollment_id=enroll.id,
        )
        db.add(att)

    att.is_present = True
    att.attendance_status = AttendanceStatus.PRESENT.value
    att.recorded_at = now
    att.method = AttendanceMethod.QR.value
    att.recorded_by_user_id = user_id
    await db.flush()
    await _recalculate_training_attendance_pct(db, training.id)
    await db.commit()

    return {
        "training_name": training.name,
        "session_topic": session.topic,
        "recorded_at": now.isoformat(),
        "attendance_pct": enroll.attendance_pct,
    }



async def import_attendance_file(
    db: AsyncSession,
    session_id: int,
    file_bytes: bytes,
    filename: str = "attendance.xlsx",
    method: str = AttendanceMethod.EXCEL.value,
    current_user: Optional[User] = None,
) -> Dict[str, Any]:
    """Importa asistencia desde Excel o reporte CSV/XLSX de Teams/Zoom (RF-13, RF-16)."""
    session = await db.get(TrainingSession, session_id)
    if not session:
        raise ValueError("Sesión no encontrada.")
    training = await db.get(Training, session.training_id)
    if training:
        _check_closed_edit_permission(training, current_user)

    if filename.lower().endswith(".csv"):
        df = pd.read_csv(io.BytesIO(file_bytes))
    else:
        df = pd.read_excel(io.BytesIO(file_bytes))

    cols = {str(c).strip().lower(): c for c in df.columns}
    doc_col = cols.get("documento") or cols.get("document_id") or cols.get("ci")
    email_col = cols.get("correo") or cols.get("email") or cols.get("user email") or cols.get("email address")
    name_col = cols.get("nombre") or cols.get("name") or cols.get("full name")
    status_col = cols.get("estado") or cols.get("status") or cols.get("asistencia")

    enrolls = (
        await db.execute(
            select(TrainingEnrollment)
            .options(selectinload(TrainingEnrollment.employee))
            .where(
                TrainingEnrollment.training_id == session.training_id,
                TrainingEnrollment.status.in_([
                    EnrollmentStatus.ENROLLED,
                    EnrollmentStatus.ATTENDED,
                    EnrollmentStatus.FAILED,
                ]),
            )
        )
    ).scalars().all()

    by_doc = {e.employee.document_id: e for e in enrolls if e.employee and e.employee.document_id}
    by_email = {e.employee.institutional_email.lower(): e for e in enrolls if e.employee and e.employee.institutional_email}
    by_name = {e.employee.full_name.strip().lower(): e for e in enrolls if e.employee and e.employee.full_name}

    status_map = {
        "presente": AttendanceStatus.PRESENT.value,
        "present": AttendanceStatus.PRESENT.value,
        "1": AttendanceStatus.PRESENT.value,
        "si": AttendanceStatus.PRESENT.value,
        "sí": AttendanceStatus.PRESENT.value,
        "tardanza": AttendanceStatus.LATE.value,
        "late": AttendanceStatus.LATE.value,
        "justificado": AttendanceStatus.JUSTIFIED.value,
        "justified": AttendanceStatus.JUSTIFIED.value,
        "ausente": AttendanceStatus.ABSENT.value,
        "absent": AttendanceStatus.ABSENT.value,
        "0": AttendanceStatus.ABSENT.value,
        "no": AttendanceStatus.ABSENT.value,
    }

    updates: Dict[int, schemas.AttendanceUpdate] = {}
    for _, row in df.iterrows():
        matched = None
        if doc_col and pd.notna(row[doc_col]):
            matched = by_doc.get(str(row[doc_col]).strip())
        if not matched and email_col and pd.notna(row[email_col]):
            matched = by_email.get(str(row[email_col]).strip().lower())
        if not matched and name_col and pd.notna(row[name_col]):
            matched = by_name.get(str(row[name_col]).strip().lower())
        if not matched:
            continue

        raw_st = str(row[status_col]).strip().lower() if (status_col and pd.notna(row[status_col])) else "present"
        att_st = status_map.get(raw_st, AttendanceStatus.PRESENT.value)
        updates[matched.id] = schemas.AttendanceUpdate(
            enrollment_id=matched.id,
            is_present=(att_st != AttendanceStatus.ABSENT.value),
            attendance_status=att_st,
        )

    for e in enrolls:
        if e.id not in updates:
            updates[e.id] = schemas.AttendanceUpdate(
                enrollment_id=e.id,
                is_present=False,
                attendance_status=AttendanceStatus.ABSENT.value,
            )

    await save_attendance(
        db,
        session_id,
        schemas.AttendanceList(attendances=list(updates.values()), method=method),
        current_user=current_user,
    )
    return {"matched": len([u for u in updates.values() if u.is_present]), "total_enrolled": len(enrolls)}



# --- CIERRE, EVALUACIÓN, EVIDENCIAS, CERTIFICADOS, ENCUESTA ---

async def close_training(
    db: AsyncSession,
    training_id: int,
    current_user: Optional[User] = None,
    close_date_override: Optional[date] = None,
) -> Dict[str, Any]:
    """
    Cierra la capacitación (RF-18, RN-04, RN-05, RN-07, CA-05, CA-07, CA-09):
    - Impide cerrar si faltan sesiones sin asistencia registrada.
    - Calcula % de asistencia y resultado (aprobado / no_aprobado) por participante.
    - Si es externa, crea ReplicaCommitment (fecha_limite = end_date + N meses calendario) para aprobados.
    - Si es réplica, evalúa cumplimiento de compromisos vinculados.
    - Envía N-06 a participantes cerrados.
    """
    training = (
        await db.execute(
            select(Training)
            .options(
                selectinload(Training.sessions).selectinload(TrainingSession.attendances),
                selectinload(Training.enrollments).selectinload(TrainingEnrollment.employee),
                selectinload(Training.enrollments).selectinload(TrainingEnrollment.attendances),
            )
            .execution_options(populate_existing=True)
            .where(Training.id == training_id)
        )
    ).scalar_one_or_none()

    if not training:
        raise ValueError("Capacitación no encontrada.")
    if training.status == TrainingStatus.CLOSED:
        raise ValueError("La capacitación ya está cerrada.")
    if training.status == TrainingStatus.CANCELLED:
        raise ValueError("No se puede cerrar una capacitación cancelada.")

    # RF-18: No permitir cerrar si hay sesiones sin asistencia registrada (cuando hay inscritos)
    active_enrolls = [
        e for e in training.enrollments
        if e.status in (EnrollmentStatus.ENROLLED, EnrollmentStatus.INVITED, EnrollmentStatus.ATTENDED, EnrollmentStatus.FAILED)
    ]
    if training.sessions and active_enrolls:
        missing_sessions = [
            s for s in training.sessions
            if s.status != SessionStatus.CLOSED and len(s.attendances) == 0
        ]
        if missing_sessions:
            raise ValueError(
                f"No se puede cerrar: faltan {len(missing_sessions)} sesión(es) sin asistencia registrada."
            )

    params = await get_parameters_dict(db)
    min_att_req = float(
        training.min_attendance_pct if training.min_attendance_pct is not None else params.get("min_attendance_pct", 80)
    )
    replica_months = int(params.get("replica_deadline_months", 3))
    total_sessions = len(training.sessions)
    close_dt = close_date_override or date.today()

    approved_count = 0
    failed_count = 0
    commitments_created = 0
    created_commitments_by_enroll: Dict[int, ReplicaCommitment] = {}

    for e in active_enrolls:
        if total_sessions > 0:
            present_cnt = sum(1 for a in e.attendances if _effective_presence(a, params))
            att_pct = round((present_cnt / total_sessions) * 100.0, 2)
        else:
            att_pct = 100.0 if e.status == EnrollmentStatus.ENROLLED else 0.0

        e.attendance_pct = att_pct

        meets_att = att_pct >= min_att_req
        meets_score = True
        if training.min_passing_score is not None:
            meets_score = e.knowledge_score is not None and e.knowledge_score >= training.min_passing_score

        if meets_att and meets_score:
            e.status = EnrollmentStatus.ATTENDED
            e.result = "aprobado"
            approved_count += 1

            # RN-05 / CA-07: Crear compromiso de réplica si la capacitación es EXTERNA
            if training.type == TrainingType.EXTERNAL:
                existing_comm = await db.scalar(
                    select(ReplicaCommitment.id).where(ReplicaCommitment.source_enrollment_id == e.id)
                )
                if not existing_comm:
                    due_dt = add_calendar_months(training.end_date, replica_months)
                    comm = ReplicaCommitment(
                        source_enrollment_id=e.id,
                        source_training_id=training.id,
                        employee_id=e.employee_id,
                        due_date=due_dt,
                        status="pendiente",
                    )
                    db.add(comm)
                    await db.flush()
                    created_commitments_by_enroll[e.id] = comm
                    commitments_created += 1
        else:
            e.status = EnrollmentStatus.FAILED
            e.result = "no_aprobado"
            failed_count += 1

    old_status = training.status.value
    training.status = TrainingStatus.CLOSED
    training.closed_at = datetime.combine(close_dt, datetime.now().time())

    await log_training_audit(
        db,
        "training",
        training.id,
        "CLOSE",
        "status",
        old_status,
        training.status.value,
        f"Aprobados: {approved_count}, No aprobados: {failed_count}, Compromisos: {commitments_created}",
        user_id=current_user.id if current_user else None,
    )
    await db.commit()

    # RN-07 / CA-09: Evaluar cumplimiento de réplica si es tipo REPLICA
    replicas_fulfilled = 0
    if training.type == TrainingType.REPLICA:
        replicas_fulfilled = await evaluate_replica_on_close(
            db, training, close_dt, user_id=current_user.id if current_user else None
        )

    # N-06: Notificar conclusión a cada participante
    for e in active_enrolls:
        if e.employee:
            await send_n06_closure(
                db, training, e, e.employee, commitment=created_commitments_by_enroll.get(e.id)
            )

    return {
        "training_id": training.id,
        "status": training.status.value,
        "approved": approved_count,
        "failed": failed_count,
        "commitments_created": commitments_created,
        "replicas_fulfilled": replicas_fulfilled,
    }



async def get_evidences(db: AsyncSession, entity_type: str, entity_id: int) -> List[TrainingEvidence]:
    stmt = (
        select(TrainingEvidence)
        .where(TrainingEvidence.entity_type == entity_type, TrainingEvidence.entity_id == entity_id)
        .order_by(desc(TrainingEvidence.uploaded_at))
    )
    return (await db.execute(stmt)).scalars().all()


async def upload_evidence_file(
    db: AsyncSession,
    entity_type: str,
    entity_id: int,
    file: UploadFile,
    evidence_type: str,
    user_id: Optional[int] = None,
) -> TrainingEvidence:
    upload_dir = ensure_upload_dir(entity_type)
    raw_ext = file.filename.rsplit(".", 1)[-1] if file.filename and "." in file.filename else "bin"
    ext = re.sub(r"[^a-zA-Z0-9]", "", raw_ext)[:10] or "bin"
    stored_name = f"{entity_type}_{entity_id}_{uuid.uuid4().hex}.{ext}"
    abs_path = os.path.join(upload_dir, stored_name)
    content = await file.read()
    max_bytes = 15 * 1024 * 1024
    if len(content) > max_bytes:
        raise ValueError("El archivo supera el tamaño máximo permitido (15 MB).")
    with open(abs_path, "wb") as f:
        f.write(content)

    ev = TrainingEvidence(
        entity_type=entity_type,
        entity_id=entity_id,
        file_name=file.filename or stored_name,
        file_url=f"/trainings/api/evidences/download/{entity_type}/{stored_name}",
        evidence_type=evidence_type,
        uploaded_by_user_id=user_id,
    )
    db.add(ev)
    await db.flush()
    await log_training_audit(
        db, "evidence", ev.id, "UPLOAD", evidence_type, None, ev.file_name, user_id=user_id
    )
    await db.commit()
    await db.refresh(ev)
    return ev


async def add_evidence_link(
    db: AsyncSession,
    entity_type: str,
    entity_id: int,
    payload: schemas.EvidenceLinkCreate,
    user_id: Optional[int] = None,
) -> TrainingEvidence:
    ev = TrainingEvidence(
        entity_type=entity_type,
        entity_id=entity_id,
        file_name=payload.file_name,
        file_url=payload.file_url,
        evidence_type=payload.evidence_type,
        uploaded_by_user_id=user_id,
    )
    db.add(ev)
    await db.flush()
    await log_training_audit(
        db, "evidence", ev.id, "CREATE", payload.evidence_type, None, payload.file_name, user_id=user_id
    )
    await db.commit()
    await db.refresh(ev)
    return ev


async def delete_evidence(db: AsyncSession, evidence_id: int, user_id: Optional[int] = None) -> bool:
    ev = await db.get(TrainingEvidence, evidence_id)
    if not ev:
        return False
    await log_training_audit(db, "evidence", ev.id, "DELETE", ev.evidence_type, ev.file_name, None, user_id=user_id)
    await db.delete(ev)
    await db.commit()
    return True


async def upload_provider_certificate(
    db: AsyncSession,
    enrollment_id: int,
    file: UploadFile,
    user_id: Optional[int] = None,
) -> TrainingEnrollment:
    """RF-19: Carga el certificado del proveedor por participante (externas)."""
    enroll = await db.get(TrainingEnrollment, enrollment_id)
    if not enroll:
        raise ValueError("Inscripción no encontrada")
    ev = await upload_evidence_file(db, "enrollment", enrollment_id, file, "certificado", user_id=user_id)
    enroll.certificate_file = ev.file_url
    await db.commit()
    await db.refresh(enroll)
    return enroll



async def generate_certificate_pdf(db: AsyncSession, enrollment_id: int) -> io.BytesIO:
    """RF-20: Genera certificado PDF automático para internas y réplicas aprobadas."""
    enroll = (
        await db.execute(
            select(TrainingEnrollment)
            .options(
                selectinload(TrainingEnrollment.training).selectinload(Training.internal_instructor),
                selectinload(TrainingEnrollment.employee),
            )
            .where(TrainingEnrollment.id == enrollment_id)
        )
    ).scalar_one_or_none()
    if not enroll:
        raise ValueError("Inscripción no encontrada.")
    if enroll.status != EnrollmentStatus.ATTENDED:
        raise ValueError("El certificado automático solo se emite a participantes aprobados.")

    t = enroll.training
    emp = enroll.employee
    instructor_name = t.internal_instructor.full_name if t.internal_instructor else settings.BUSINESS_NAME
    kind_label = "RÉPLICA INTERNA" if t.type == TrainingType.REPLICA else "CAPACITACIÓN INTERNA"

    html = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="utf-8">
        <style>
            @page {{ size: A4 landscape; margin: 1.5cm; }}
            body {{ font-family: Georgia, serif; border: 8px solid #003366; padding: 40px; text-align: center; color: #1e293b; }}
            .inst {{ font-size: 16px; letter-spacing: 3px; color: #003366; font-weight: bold; text-transform: uppercase; }}
            .title {{ font-size: 38px; color: #003366; margin: 20px 0 10px 0; }}
            .sub {{ font-size: 14px; color: #64748b; text-transform: uppercase; letter-spacing: 2px; }}
            .name {{ font-size: 30px; font-weight: bold; margin: 25px 0; color: #0f172a; border-bottom: 2px solid #D4AF37; display: inline-block; padding: 0 30px 6px 30px; }}
            .desc {{ font-size: 16px; line-height: 1.6; max-width: 720px; margin: 15px auto; }}
            .meta {{ margin-top: 40px; font-size: 13px; color: #475569; }}
            .sig {{ margin-top: 50px; display: flex; justify-content: space-around; font-size: 13px; }}
            .sig-line {{ border-top: 1px solid #334155; width: 220px; padding-top: 6px; }}
        </style>
    </head>
    <body>
        <div class="inst">{settings.BUSINESS_NAME} · Talento Humano</div>
        <div class="title">CERTIFICADO DE APROBACIÓN</div>
        <div class="sub">{kind_label}</div>
        <p style="margin-top: 25px; font-size: 15px;">Se otorga el presente certificado a:</p>
        <div class="name">{emp.full_name}</div>
        <p class="desc">
            Por haber aprobado satisfactoriamente la actividad formativa
            <strong>&ldquo;{t.name}&rdquo;</strong>, realizada del
            {t.start_date.strftime('%d/%m/%Y')} al {t.end_date.strftime('%d/%m/%Y')}
            con una duración de <strong>{t.hours or 0} horas</strong> y una asistencia del
            <strong>{round(enroll.attendance_pct or 0, 1)}%</strong>.
        </p>
        <div class="sig">
            <div class="sig-line">{instructor_name}<br>Facilitador</div>
            <div class="sig-line">Talento Humano<br>{settings.BUSINESS_NAME}</div>
        </div>
        <div class="meta">Código: {t.code or t.id} · Emitido el {date.today().strftime('%d/%m/%Y')}</div>
    </body>
    </html>
    """
    pdf_bytes = HTML(string=html).write_pdf()
    buf = io.BytesIO(pdf_bytes)
    buf.seek(0)
    return buf


async def submit_survey(
    db: AsyncSession,
    enrollment_id: int,
    employee_id: int,
    payload: schemas.SurveyCreate,
) -> TrainingSurvey:
    """RF-21: Guarda la encuesta de satisfacción al cierre."""
    enroll = (
        await db.execute(
            select(TrainingEnrollment)
            .options(selectinload(TrainingEnrollment.training), selectinload(TrainingEnrollment.survey))
            .where(TrainingEnrollment.id == enrollment_id)
        )
    ).scalar_one_or_none()
    if not enroll:
        raise ValueError("Inscripción no encontrada")
    if enroll.employee_id != employee_id:
        raise ValueError("No puedes responder la encuesta de otro colaborador.")
    if enroll.training.status != TrainingStatus.CLOSED:
        raise ValueError("La encuesta está disponible una vez cerrada la capacitación.")
    if enroll.survey:
        raise ValueError("Ya completaste la encuesta de esta capacitación.")

    survey = TrainingSurvey(enrollment_id=enrollment_id, **payload.model_dump())
    db.add(survey)
    await db.commit()
    await db.refresh(survey)
    return survey



async def sync_personnel_and_commitments(
    db: AsyncSession, user_id: Optional[int] = None
) -> Dict[str, int]:
    """RF-34: Sincroniza colaboradores/áreas/jefes desde maestros y anula compromisos de cesados (RN-11)."""
    ceased_emps = (
        await db.execute(select(Employee).where(Employee.is_active == False))  # noqa
    ).scalars().all()
    cancelled_commitments = 0
    for emp in ceased_emps:
        cancelled_commitments += await cancel_commitments_on_exit(db, emp.id, user_id=user_id)

    active_emps_cnt = await db.scalar(select(func.count(Employee.id)).where(Employee.is_active == True)) or 0  # noqa
    areas_cnt = await db.scalar(select(func.count(Area.id))) or 0

    await log_training_audit(
        db, "system", 0, "SYNC_PERSONNEL", "employees", None,
        f"Activos: {active_emps_cnt}, Áreas: {areas_cnt}, Compromisos anulados: {cancelled_commitments}",
        user_id=user_id,
    )
    await db.commit()
    return {
        "active_employees": active_emps_cnt,
        "areas": areas_cnt,
        "cancelled_commitments": cancelled_commitments,
    }


async def get_training_audits(
    db: AsyncSession, entity_type: Optional[str] = None, entity_id: Optional[int] = None, limit: int = 200
) -> List[TrainingAudit]:
    stmt = (
        select(TrainingAudit)
        .options(selectinload(TrainingAudit.user))
        .order_by(desc(TrainingAudit.created_at), desc(TrainingAudit.id))
        .limit(limit)
    )
    if entity_type and entity_type != "all":
        stmt = stmt.where(TrainingAudit.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(TrainingAudit.entity_id == entity_id)
    return (await db.execute(stmt)).scalars().all()

