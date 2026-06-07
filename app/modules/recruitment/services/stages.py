from typing import Optional
from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.notifications.service import send_email_notification
from app.modules.recruitment import schemas
from app.modules.recruitment.business_calendar import add_business_days, get_holidays_set
from app.modules.recruitment.models import VacancyStage
from app.modules.recruitment.services.audit import log_audit

async def update_stage(
    db: AsyncSession,
    stage_id: int,
    stage_in: schemas.StageUpdate,
    background_tasks: Optional[BackgroundTasks] = None,
    user_id: Optional[int] = None
) -> Optional[VacancyStage]:
    """Actualiza una etapa y recalcula fechas (Efecto Dominó) con SLA real."""
    stmt = (
        select(VacancyStage)
        .options(
            selectinload(VacancyStage.vacancy),
            selectinload(VacancyStage.responsible),
        )
        .where(VacancyStage.id == stage_id)
    )
    result = await db.execute(stmt)
    stage = result.scalar_one_or_none()
    if not stage:
        return None

    old_responsible_id = stage.responsible_id
    update_data = stage_in.model_dump(exclude_unset=True)
    audit_details = []
    
    # Actualizar campos
    for key, value in update_data.items():
        if key == "edit_reason_id":
             continue # Handle separately
        if getattr(stage, key) != value:
            audit_details.append(f"Etapa '{stage.name}': {key} cambiado")
            setattr(stage, key, value)

    # --- VALIDACIÓN DE MOTIVO DE EDICIÓN ---
    if "edit_reason_id" in update_data:
        reason_id = update_data["edit_reason_id"]
        if not reason_id:
             raise ValueError("Debe seleccionar un motivo de edición.")
        
        # Validar existencia
        from app.modules.recruitment.services.stage_edit_reasons import get_stage_edit_reason_by_id
        reason = await get_stage_edit_reason_by_id(db, reason_id)
        if not reason:
             raise ValueError("Motivo de edición inválido.")
        
        audit_details.append(f"Motivo: {reason.name}")

        # Regla: Si es "Otro" (o contiene 'otro' en el nombre), notas obligatorias
        if "otro" in reason.name.lower() or "other" in reason.name.lower():
             notes = update_data.get("notes") or stage.notes
             if not notes or not notes.strip():
                 raise ValueError("Debe agregar una observación cuando el motivo es 'Otro'.")

    # --- LÓGICA DE RECÁLCULO DE FECHAS (EFECTO DOMINÓ INTELIGENTE) ---
    if "end_date" in update_data and update_data["end_date"]:
        audit_details.append(f"Etapa '{stage.name}' finalizada el {update_data['end_date']}")
        
        # Obtener etapas siguientes ordenadas
        stmt_next = (
            select(VacancyStage)
            .where(
                VacancyStage.vacancy_id == stage.vacancy_id,
                VacancyStage.order_index > stage.order_index
            )
            .order_by(VacancyStage.order_index)
        )
        next_stages = (await db.execute(stmt_next)).scalars().all()
        
        # La fecha base para la siguiente etapa es la fecha fin de la actual
        current_anchor_date = update_data["end_date"]
        
        # Pre-cargar feriados para optimizar el bucle
        holidays = await get_holidays_set(db, current_anchor_date)

        for next_stage in next_stages:
            # Actualizar inicio
            next_stage.start_date = current_anchor_date
            
            # Recalcular deadline usando SLA real (días hábiles)
            if next_stage.sla_days_snapshot:
                next_stage.deadline_date = await add_business_days(
                    db, current_anchor_date, next_stage.sla_days_snapshot, holidays
                )
            
            # La fecha base para la subsiguiente etapa será:
            # 1. Su fecha fin si YA está cerrada (caso raro de edición intermedia)
            # 2. Su deadline proyectado si está abierta
            if next_stage.end_date:
                current_anchor_date = next_stage.end_date
            else:
                current_anchor_date = next_stage.deadline_date

    if audit_details:
        await log_audit(db, stage.vacancy_id, "STAGE_UPDATE", "; ".join(audit_details), user_id)

    await db.commit()
    await db.refresh(stage, attribute_names=["responsible"])

    # Notificación de asignación
    if (
        "responsible_id" in update_data
        and stage.responsible_id != old_responsible_id
        and stage.responsible
    ):
        if stage.responsible.email:
            clean_stage_name = stage.name.replace("\n", " ").replace("\r", "")
            subject = f"Asignación de Etapa: {clean_stage_name}"
            body = (
                f"Hola {stage.responsible.full_name},\n\n"
                f"Se te ha asignado la etapa '{stage.name}' para la vacante "
                f"'{stage.vacancy.title}'.\n"
                f"Fecha límite: {stage.deadline_date}\n\n"
                f"Por favor ingresa al sistema para gestionarla."
            )
            await send_email_notification(
                db,
                stage.responsible.email,
                subject,
                body,
                background_tasks,
            )

    return stage


async def notify_stage_responsible(
    db: AsyncSession,
    stage_id: int,
    background_tasks: Optional[BackgroundTasks] = None,
) -> bool:
    """Envía un recordatorio manual al responsable de la etapa."""
    stmt = (
        select(VacancyStage)
        .options(
            selectinload(VacancyStage.vacancy),
            selectinload(VacancyStage.responsible),
        )
        .where(VacancyStage.id == stage_id)
    )
    result = await db.execute(stmt)
    stage = result.scalar_one_or_none()
    if not stage:
        return False

    recipient_email = None
    recipient_name = "Responsable"

    if stage.responsible:
        recipient_email = stage.responsible.email
        recipient_name = stage.responsible.full_name
    elif stage.owner == "area":
        await db.refresh(stage.vacancy, attribute_names=["area"])
        if stage.vacancy.area:
            recipient_email = stage.vacancy.area.responsible_email
            recipient_name = f"Jefe de {stage.vacancy.area.name}"

    if not recipient_email:
        raise ValueError(
            "No se encontró un correo electrónico para notificar."
        )

    clean_stage_name = stage.name.replace("\n", " ").replace("\r", "")
    subject = f"🔔 Recordatorio: Etapa Pendiente - {clean_stage_name}"
    body = (
        f"Hola {recipient_name},\n\n"
        f"Este es un recordatorio sobre la etapa '{stage.name}' de la vacante "
        f"'{stage.vacancy.title}'.\n\n"
        f"Estado: Pendiente\n"
        f"Vencimiento: {stage.deadline_date}\n\n"
        f"Agradecemos tu gestión."
    )

    await send_email_notification(
        db, recipient_email, subject, body, background_tasks
    )
    return True