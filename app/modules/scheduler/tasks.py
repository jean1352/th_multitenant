"""
Definición de las reglas de negocio masivas.
"""
import logging
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import select, and_, or_
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.tenants import get_tenant_base_url, get_current_tenant
from app.modules.recruitment.models import Vacancy, ProcessStatus
from app.modules.recruitment.services.vacancies import notify_vacancy_status
from app.modules.calendar.models import CalendarEvent, EventEnrollment, EnrollmentStatus
from app.modules.notifications.service import send_email_notification
from app.modules.employees.models import Employee, EmployeeDocument, EmployeePosition, DocumentCategory

logger = logging.getLogger(__name__)

# --- 1. REPORTE DE STATUS DE VACANTES ---
async def run_vacancy_weekly_report(rule_id: int, **kwargs):
    logger.info("🚀 Iniciando reporte masivo de vacantes...")
    count = 0
    async with AsyncSessionLocal() as db:
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
    async with AsyncSessionLocal() as db:
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
    
    async with AsyncSessionLocal() as db:
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
    async with AsyncSessionLocal() as db:
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
    async with AsyncSessionLocal() as db:
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

# --- REGISTRO DE FUNCIONES ---
TASK_REGISTRY = {
    "vacancy_weekly_report": run_vacancy_weekly_report,
    "vacancy_stagnation": run_vacancy_stagnation_check,
    "event_reminder": run_event_reminder,
    "contract_expiration": run_contract_expiration,
    "probation_end": run_probation_end,
    "sla_daily_check": lambda **k: "SLA Check (Simulado)"
}