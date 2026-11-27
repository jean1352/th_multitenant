"""
Definición de las reglas de negocio masivas.
"""
import logging
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import select, and_, or_
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_tenant_db
from app.core.tenants import get_tenant_base_url, get_current_tenant
from app.modules.recruitment.models import Vacancy, ProcessStatus
from app.modules.recruitment.services.vacancies import notify_vacancy_status
from app.modules.recruitment.business_calendar import count_business_days, refresh_holidays_cache
from app.modules.recruitment.services.notifications import send_sla_stage_alert
from app.modules.calendar.models import CalendarEvent, EventEnrollment, EnrollmentStatus
from app.modules.notifications.models import NotificationLog
from app.modules.notifications.service import send_email_notification
from app.modules.employees.models import Employee, EmployeeDocument, EmployeePosition, DocumentCategory
from app.modules.trainings.models import Training

logger = logging.getLogger(__name__)

# --- 1. REPORTE DE STATUS DE VACANTES ---
async def run_vacancy_weekly_report(rule_id: int, **kwargs):
    logger.info("🚀 Iniciando reporte masivo de vacantes...")
    count = 0
    async with get_tenant_db() as db:
        stmt = select(Vacancy).where(Vacancy.status == ProcessStatus.OPEN)
        vacancies = (await db.execute(stmt)).scalars().all()
        for vac in vacancies:
            try:
                await notify_vacancy_status(db, vac.id, background_tasks=None)
                count += 1
            except Exception as e:
                logger.error(f"Error enviando reporte vacante {vac.id}: {e}")
    return f"Reportes enviados: {count}"

# --- 2. ALERTA DE ESTANCAMIENTO ---
async def run_vacancy_stagnation_check(rule_id: int, param_value: int = 10, **kwargs):
    days_limit = param_value or 10
    logger.info(f"🚀 Buscando vacantes estancadas (> {days_limit} días)...")
    count = 0
    async with get_tenant_db() as db:
        stmt = select(Vacancy).options(selectinload(Vacancy.area)).where(Vacancy.status == ProcessStatus.OPEN)
        vacancies = (await db.execute(stmt)).scalars().all()
        for vac in vacancies:
            days_open = (date.today() - vac.created_at.date()).days
            if days_open > 0 and days_open % days_limit == 0:
                if vac.area and vac.area.responsible_email:
                    subject = f"⚠️ Alerta de Estancamiento: {vac.title}"
                    body = f"La vacante '{vac.title}' lleva {days_open} días abierta.\nPor favor revise el estado del proceso."
                    await send_email_notification(db, vac.area.responsible_email, subject, body)
                    count += 1
    return f"Alertas enviadas: {count}"

# --- 3. RECORDATORIO EVENTOS (MEJORADO) ---
async def run_event_reminder(rule_id: int, param_value: int = 2, **kwargs):
    """
    Busca eventos futuros dentro del rango de 'param_value' días.
    Envía recordatorio a los invitados pendientes con botón de confirmación.
    """
    days_range = param_value or 2
    today = date.today()
    limit_date = today + timedelta(days=days_range)
    
    logger.info(f"🚀 Buscando eventos entre {today} y {limit_date}...")
    count = 0
    
    async with get_tenant_db() as db:
        # Buscar eventos futuros dentro del rango
        stmt_events = select(CalendarEvent).where(
            CalendarEvent.date >= today,
            CalendarEvent.date <= limit_date
        )
        events = (await db.execute(stmt_events)).scalars().all()
        
        for event in events:
            days_until = (event.date - today).days
            logger.info(f"Encontrado evento: {event.title} ({days_until} días)")
            # Buscar invitados sin respuesta (INVITED)
            stmt_enroll = (
                select(EventEnrollment)
                .options(selectinload(EventEnrollment.employee))
                .where(
                    EventEnrollment.event_id == event.id,
                    EventEnrollment.status == EnrollmentStatus.INVITED
                )
            )
            pending_enrollments = (await db.execute(stmt_enroll)).scalars().all()
            
            for enroll in pending_enrollments:
                logger.info(f"Encontrado invitado: {enroll.employee.full_name}")
                if enroll.employee.institutional_email:
                    
                    # Evitar spam: Si ya se envió invitación HOY, no reenviar recordatorio
                    if enroll.invitation_sent_at and enroll.invitation_sent_at.date() == today:
                        logger.info(f"Invitación ya enviada HOY para {enroll.employee.full_name}")
                        continue

                    # Generar token si no existe
                    if not enroll.invitation_token:
                        enroll.invitation_token = str(uuid.uuid4())
                        db.add(enroll) # Marcar para update
                    
                    # Construir Link
                    base_url = get_tenant_base_url()
                    tenant = get_current_tenant()
                    business_name = tenant.name if tenant else settings.BUSINESS_NAME
                    
                    link = f"{base_url}/calendar/public/respond/{enroll.invitation_token}"
                    
                    # Construir HTML con Botón
                    subject = f"🔔 Recordatorio: Confirma tu asistencia a {event.title}"
                    
                    html_body = f"""
                    <div style="font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: 0 auto; border: 1px solid #eee; border-radius: 8px; overflow: hidden;">
                        <div style="background-color: #003366; padding: 20px; text-align: center;">
                            <h2 style="color: white; margin: 0;">Recordatorio de Evento</h2>
                        </div>
                        <div style="padding: 20px;">
                            <p>Hola <strong>{enroll.employee.full_name}</strong>,</p>
                            <p>Te recordamos que tienes una invitación pendiente para el siguiente evento:</p>
                            
                            <div style="background-color: #f8fafc; padding: 15px; border-left: 4px solid #3b82f6; margin: 20px 0;">
                                <h3 style="margin: 0 0 5px 0; color: #1e293b;">{event.title}</h3>
                                <p style="margin: 0; color: #64748b;">Fecha: {event.date.strftime('%d/%m/%Y')}</p>
                                <p style="margin: 0; color: #64748b;">Faltan: {days_until} días</p>
                            </div>

                            <p style="text-align: center; margin: 30px 0;">
                                <a href="{link}" style="background-color: #003366; color: white; padding: 12px 25px; text-decoration: none; border-radius: 5px; font-weight: bold; font-size: 16px; display: inline-block;">
                                    Confirmar Asistencia
                                </a>
                            </p>
                            
                            <p style="font-size: 12px; color: #666; text-align: center;">
                                Si no puedes asistir, por favor ingresa al enlace para rechazar la invitación y liberar el cupo.
                            </p>
                        </div>
                        <div style="background-color: #f1f5f9; padding: 15px; text-align: center; font-size: 11px; color: #94a3b8;">
                            Talento Humano - {business_name}
                        </div>
                    </div>
                    """
                    
                    await send_email_notification(
                        db, 
                        enroll.employee.institutional_email, 
                        subject, 
                        html_body, 
                        is_html=True
                    )
                    
                    # Actualizar fecha de último envío para evitar spam en el mismo día
                    enroll.invitation_sent_at = datetime.now()
                    count += 1
            
            await db.commit()
                    
    return f"Recordatorios enviados: {count}"

# --- 4. VENCIMIENTO DE CONTRATOS ---
async def run_contract_expiration(rule_id: int, param_value: int = 30, **kwargs):
    days_notice = param_value or 30
    target_date = date.today() + timedelta(days=days_notice)
    logger.info(f"🚀 Buscando contratos que vencen el {target_date}...")
    count = 0
    async with get_tenant_db() as db:
        stmt = (
            select(EmployeeDocument)
            .join(Employee)
            .options(
                selectinload(EmployeeDocument.employee)
                .selectinload(Employee.position_obj)
                .selectinload(Employee.position_obj.area)
            )
            .where(
                EmployeeDocument.category == DocumentCategory.CONTRACT,
                EmployeeDocument.expiration_date == target_date,
                Employee.is_active == True
            )
        )
        docs = (await db.execute(stmt)).scalars().all()
        for doc in docs:
            emp = doc.employee
            area_email = emp.position_obj.area.responsible_email if emp.position_obj and emp.position_obj.area else None
            if area_email:
                subject = f"⚠️ Vencimiento de Contrato: {emp.full_name}"
                html_body = f"""
                <p>Estimado responsable,</p>
                <p>El contrato del colaborador <strong>{emp.full_name}</strong> vence el <strong>{target_date.strftime('%d/%m/%Y')}</strong> (en {days_notice} días).</p>
                <p><strong>Detalles:</strong></p>
                <ul><li>Cargo: {emp.position_obj.name}</li><li>Documento: {doc.name}</li></ul>
                <p>Por favor inicie el proceso de renovación o cese correspondiente.</p>
                <br><p>Atentamente,<br>Talento Humano UP</p>
                """
                await send_email_notification(db, area_email, subject, html_body, is_html=True)
                count += 1
    return f"Alertas de contrato enviadas: {count}"

# --- 5. FIN DE PERIODO DE PRUEBA ---
async def run_probation_end(rule_id: int, param_value: int = 90, **kwargs):
    probation_days = param_value or 90
    notice_days = 15
    days_ago = probation_days - notice_days
    target_start_date = date.today() - timedelta(days=days_ago)
    logger.info(f"🚀 Buscando ingresos del {target_start_date} (Fin prueba en {notice_days} días)...")
    count = 0
    async with get_tenant_db() as db:
        stmt = (
            select(EmployeePosition)
            .join(Employee)
            .options(
                selectinload(EmployeePosition.employee),
                selectinload(EmployeePosition.position).selectinload(Employee.position_obj.area)
            )
            .where(
                EmployeePosition.is_primary == True,
                EmployeePosition.end_date.is_(None),
                EmployeePosition.start_date == target_start_date,
                Employee.is_active == True
            )
        )
        positions = (await db.execute(stmt)).scalars().all()
        for pos in positions:
            emp = pos.employee
            area_email = pos.position.area.responsible_email if pos.position.area else None
            if area_email:
                end_probation_date = pos.start_date + timedelta(days=probation_days)
                subject = f"⏳ Fin Periodo de Prueba: {emp.full_name}"
                html_body = f"""
                <p>Estimado responsable,</p>
                <p>El periodo de prueba ({probation_days} días) del colaborador <strong>{emp.full_name}</strong> finalizará el <strong>{end_probation_date.strftime('%d/%m/%Y')}</strong>.</p>
                <p><strong>Detalles:</strong></p>
                <ul><li>Cargo: {pos.position.name}</li><li>Fecha Inicio: {pos.start_date.strftime('%d/%m/%Y')}</li></ul>
                <p>Recuerde realizar la evaluación de desempeño y confirmar su continuidad en el cargo.</p>
                <br><p>Atentamente,<br>Talento Humano UP</p>
                """
                await send_email_notification(db, area_email, subject, html_body, is_html=True)
                count += 1
    return f"Alertas de prueba enviadas: {count}"

# --- 6. MOTOR DE AUTOMATIZACIONES AVANZADAS (NUEVO) ---
async def run_advanced_automations(rule_id: int = None, **kwargs):
    """
    Escanea reglas de automatización activas, evalúa dinámicamente sus condiciones
    y ejecuta acciones aplicando ciclo cerrado y escalamiento.
    """
    from app.modules.scheduler.models import AutomationRule, AutomationState, EscalationStatus, TriggerType
    from app.modules.scheduler.evaluator import AdvancedConditionEvaluator, ActionExecutor
    import traceback
    
    logger.info("🚀 Iniciando motor de automatizaciones avanzadas y escaneo de escalamientos...")
    rules_run = 0
    actions_fired = 0
    states_updated = 0
    
    async with get_tenant_db() as db:
        # Cargar reglas
        if rule_id:
            stmt = select(AutomationRule).where(AutomationRule.id == rule_id, AutomationRule.is_active == True)
        else:
            stmt = select(AutomationRule).where(AutomationRule.is_active == True)
            
        rules = (await db.execute(stmt)).scalars().all()
        
        for rule in rules:
            # Saltar si no tiene condiciones JSON configuradas
            if not rule.conditions:
                continue
                
            try:
                # 1. Evaluar condiciones dinámicas
                matched_entities = await AdvancedConditionEvaluator.evaluate_rule(db, rule)
                matched_ids = {entity.id for entity in matched_entities}
                
                # 2. Cargar estados de escalamiento activos para esta regla
                stmt_states = select(AutomationState).where(
                    AutomationState.rule_id == rule.id,
                    AutomationState.status == EscalationStatus.ACTIVE_ESCALATION
                )
                active_states = (await db.execute(stmt_states)).scalars().all()
                active_state_map = {state.target_entity_id: state for state in active_states}
                
                # 3. Procesar nuevas alertas y escalamientos pendientes
                for entity in matched_entities:
                    entity_id = entity.id
                    
                    # Parsear intervalo de escalamiento (ej. "6h", "1d")
                    interval_str = rule.escalation_interval or "1d"
                    hours = 24
                    if interval_str.endswith("h"):
                        hours = int(interval_str[:-1])
                    elif interval_str.endswith("d"):
                        hours = int(interval_str[:-1]) * 24
                    interval_td = timedelta(hours=hours)
                    
                    if entity_id not in active_state_map:
                        # NUEVA ALERTA: Ejecutar acciones e insertar estado
                        fired = await ActionExecutor.execute_actions(db, rule, [entity])
                        actions_fired += fired
                        
                        next_run = datetime.now() + interval_td
                        new_state = AutomationState(
                            rule_id=rule.id,
                            target_entity_id=entity_id,
                            status=EscalationStatus.ACTIVE_ESCALATION,
                            next_run_at=next_run
                        )
                        db.add(new_state)
                        states_updated += 1
                    else:
                        # RE-ALERTA / ESCALAMIENTO: Si ya se cumplió next_run_at, ejecutar y postergar
                        state = active_state_map[entity_id]
                        if datetime.now() >= state.next_run_at:
                            fired = await ActionExecutor.execute_actions(db, rule, [entity])
                            actions_fired += fired
                            
                            state.next_run_at = datetime.now() + interval_td
                            db.add(state)
                            states_updated += 1
                            
                # 4. CICLO CERRADO: Resolver alertas que ya NO cumplen la condición
                for entity_id, state in active_state_map.items():
                    if entity_id not in matched_ids:
                        state.status = EscalationStatus.RESOLVED
                        db.add(state)
                        states_updated += 1
                        logger.info(f"Ciclo cerrado: Alerta resuelta para regla {rule.id}, entidad {entity_id}")
                        
                rules_run += 1
            except Exception as e:
                logger.error(f"Error procesando regla avanzada {rule.id} ({rule.name}): {e}")
                traceback.print_exc()
                
        await db.commit()
        
    return f"Reglas: {rules_run}, Disparos: {actions_fired}, Estados actualizados: {states_updated}"

# --- 7. VERIFICACIÓN DIARIA DE SLA (por etapa) ---
async def _already_notified(db, marker: str) -> bool:
    """Verifica si ya se envió una notificación cuyo asunto contiene `marker`."""
    stmt = select(NotificationLog.id).where(
        NotificationLog.subject.like(f"%{marker}%")
    )
    return await db.scalar(stmt) is not None


async def run_sla_daily_check(rule_id: int, param_value: int = 1, **kwargs):
    """
    Revisa las etapas abiertas de las vacantes y notifica al SOLICITANTE
    (requester) cuando una etapa está próxima a vencer o ya venció su SLA.

    `param_value` = días hábiles de anticipación para la alerta "próxima a vencer".
    """
    notice_business_days = param_value if param_value and param_value > 0 else 1
    today = date.today()
    logger.info(
        f"🚀 Revisando SLA de etapas (anticipación: {notice_business_days} días hábiles)..."
    )
    count = 0
    async with get_tenant_db() as db:
        await refresh_holidays_cache(db)
        stmt = (
            select(Vacancy)
            .options(
                selectinload(Vacancy.stages),
                selectinload(Vacancy.requester),
                selectinload(Vacancy.area),
            )
            .where(Vacancy.status == ProcessStatus.OPEN)
        )
        vacancies = (await db.execute(stmt)).scalars().all()

        for vac in vacancies:
            requester_email = (
                vac.requester.email if vac.requester and vac.requester.email else None
            )
            if not requester_email:
                continue

            for stage in sorted(vac.stages, key=lambda s: s.order_index):
                if stage.end_date is not None or not stage.deadline_date:
                    continue

                if stage.deadline_date < today:
                    marker = f"SLA-vencido:{stage.id}"
                    if await _already_notified(db, marker):
                        continue
                    await send_sla_stage_alert(
                        db, vac, stage, requester_email,
                        kind="vencido", dedup_key=marker,
                    )
                    count += 1
                else:
                    remaining = count_business_days(today, stage.deadline_date)
                    if remaining == notice_business_days:
                        marker = f"SLA-proximo:{stage.id}"
                        if await _already_notified(db, marker):
                            continue
                        await send_sla_stage_alert(
                            db, vac, stage, requester_email,
                            kind="proximo", remaining_business_days=remaining,
                            dedup_key=marker,
                        )
                        count += 1

    return f"Alertas SLA enviadas: {count}"


# --- 8. RECORDATORIO DE CAPACITACIONES (inicio/cierre) ---
def _training_reminder_html(training: Training, employee: Employee, kind: str) -> str:
    """Genera el cuerpo HTML estandarizado para recordatorios de capacitación."""
    training_name = (training.name or "").replace("\n", " ").replace("\r", "").strip()
    if kind == "start":
        headline = "Capacitación próxima a iniciar"
        detail = (
            f"Te recordamos tu participación en la capacitación "
            f"<strong>{training_name}</strong> que inicia el "
            f"<strong>{training.start_date.strftime('%d/%m/%Y')}</strong>."
        )
    else:
        headline = "Capacitación próxima a finalizar"
        detail = (
            f"La capacitación <strong>{training_name}</strong> en la que participas "
            f"finaliza el <strong>{training.end_date.strftime('%d/%m/%Y')}</strong>."
        )

    return f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="margin:0; padding:0; background-color:#f1f5f9; font-family:Arial, sans-serif;">
        <div style="max-width:600px; margin:0 auto; background-color:#ffffff;">
            <div style="background-color:#003366; color:#ffffff; padding:20px; text-align:center;">
                <h2 style="margin:0; font-size:18px;">{headline}</h2>
            </div>
            <div style="padding:24px;">
                <p>Hola {employee.full_name},</p>
                <p>{detail}</p>
                <p>Por favor ingresa al sistema para más información.</p>
            </div>
            <div style="background-color:#f8fafc; padding:15px; text-align:center; font-size:11px; color:#94a3b8; border-top:1px solid #e5e7eb;">
                Este es un correo automático generado por el sistema de Talento Humano.<br>
                &copy; {datetime.now().year} {(get_current_tenant().name if get_current_tenant() else settings.BUSINESS_NAME)}.
            </div>
        </div>
    </body>
    </html>
    """


async def run_training_reminder(rule_id: int, param_value: int = 3, **kwargs):
    """
    Tarea diaria programada para el módulo de Capacitaciones:
    transiciones de estado por fecha, alertas N-02..N-11, reintentos y control de réplicas.
    """
    from app.modules.trainings.notifications_service import run_daily_training_automation

    async with get_tenant_db() as db:
        stats = await run_daily_training_automation(db)
    return f"Automatización capacitaciones: {stats}"


# --- REGISTRO DE FUNCIONES ---
# Las claves deben coincidir con los valores (.value) de AutomationRuleType (MAYÚSCULAS).
TASK_REGISTRY = {
    "VACANCY_WEEKLY_REPORT": run_vacancy_weekly_report,
    "VACANCY_STAGNATION": run_vacancy_stagnation_check,
    "EVENT_REMINDER": run_event_reminder,
    "CONTRACT_EXPIRATION": run_contract_expiration,
    "PROBATION_END": run_probation_end,
    "SLA_DAILY_CHECK": run_sla_daily_check,
    "TRAINING_REMINDER": run_training_reminder,
    "advanced_automations": run_advanced_automations,
}