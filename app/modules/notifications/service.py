"""
Lógica de negocio para el módulo de Notificaciones.
Maneja el envío asíncrono de correos y el registro en base de datos.
"""

import logging
from datetime import datetime, date
from typing import Optional, List, Union

from fastapi import BackgroundTasks
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.email_utils import send_email_async
from app.modules.notifications.models import EmailStatus, NotificationLog
from app.modules.notifications import schemas

logger = logging.getLogger(__name__)


async def _process_email_task(
    recipient: str, subject: str, body: str, is_html: bool = False
):
    """
    Lógica interna de envío y logueo con su propia sesión de DB.
    Se ejecuta en segundo plano.
    """
    async with AsyncSessionLocal() as db:
        log_entry = NotificationLog(
            recipient=recipient,
            subject=subject,
            body=body,
            status=EmailStatus.PENDING,
        )
        db.add(log_entry)
        await db.commit()  # Guardar estado pendiente

        # LÓGICA MULTI-CORREO:
        recipients_list = [r.strip() for r in recipient.split(",")] if "," in recipient else [recipient]

        # Pasamos el flag is_html al utilitario de correo
        success = await send_email_async(
            recipients_list, subject, body, is_html=is_html
        )

        log_entry.status = EmailStatus.SENT if success else EmailStatus.FAILED
        if success:
            log_entry.sent_at = datetime.now()
        else:
            log_entry.error_message = "Error en transporte SMTP"

        await db.commit()


async def send_email_notification(
    db: AsyncSession,
    recipient: str,
    subject: str,
    body: str,
    background_tasks: Optional[BackgroundTasks] = None,
    is_html: bool = False,
) -> Optional[NotificationLog]:
    """
    Envía una notificación por correo electrónico.
    """
    if background_tasks:
        background_tasks.add_task(
            _process_email_task, recipient, subject, body, is_html
        )
        return None

    # Ejecución síncrona
    log_entry = NotificationLog(
        recipient=recipient,
        subject=subject,
        body=body,
        status=EmailStatus.PENDING,
    )
    db.add(log_entry)
    await db.flush()

    recipients_list = [r.strip() for r in recipient.split(",")] if "," in recipient else [recipient]

    success = await send_email_async(
        recipients_list, subject, body, is_html=is_html
    )

    if success:
        log_entry.status = EmailStatus.SENT
        log_entry.sent_at = datetime.now()
    else:
        log_entry.status = EmailStatus.FAILED
        log_entry.error_message = "Error en transporte SMTP"

    await db.commit()
    await db.refresh(log_entry)
    return log_entry


async def get_logs(db: AsyncSession, limit: int = 50):
    """Obtiene los últimos logs de notificaciones."""
    stmt = (
        select(NotificationLog)
        .order_by(desc(NotificationLog.created_at))
        .limit(limit)
    )
    return (await db.execute(stmt)).scalars().all()


# --- LÓGICA DE PRUEBAS (MOCK DATA) ---

async def send_test_email(
    db: AsyncSession, 
    data: schemas.TestEmailRequest, 
    background_tasks: BackgroundTasks
):
    subject = ""
    body = ""
    
    if data.email_type == "vacancy_closed":
        subject = "✅ [TEST] Vacante Cerrada: Analista de Datos Senior"
        body = """
            <!DOCTYPE html>
            <html>
            <body style="font-family: 'Helvetica', Arial, sans-serif; line-height: 1.6; color: #333; background-color: #f4f4f4; margin: 0; padding: 20px;">
                <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <div style="background-color: #003366; padding: 20px; text-align: center;">
                        <h2 style="color: #ffffff; margin: 0; font-size: 20px;">Proceso Finalizado</h2>
                    </div>
                    <div style="padding: 30px;">
                        <p style="margin-top: 0; color: #666; font-size: 14px;">
                            Se informa que el proceso de selección para la siguiente vacante ha concluido exitosamente:
                        </p>
                        <h3 style="color: #003366; margin: 15px 0; font-size: 18px; border-bottom: 2px solid #f0f0f0; padding-bottom: 10px;">
                            Analista de Datos Senior (TI)
                        </h3>
                        <table style="width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 14px;">
                            <tr>
                                <td style="padding: 10px 0; color: #666; border-bottom: 1px solid #eee; width: 40%;">Fecha de Cierre:</td>
                                <td style="padding: 10px 0; font-weight: 600; color: #333; border-bottom: 1px solid #eee;">""" + date.today().strftime('%d/%m/%Y') + """</td>
                            </tr>
                            <tr>
                                <td style="padding: 10px 0; color: #666; border-bottom: 1px solid #eee;">Inicio Colaborador:</td>
                                <td style="padding: 10px 0; font-weight: 600; color: #333; border-bottom: 1px solid #eee;">01/02/2026</td>
                            </tr>
                            <tr>
                                <td style="padding: 10px 0; color: #666; border-bottom: 1px solid #eee;">Modalidad:</td>
                                <td style="padding: 10px 0; font-weight: 600; color: #333; border-bottom: 1px solid #eee;">
                                    <span style="background-color: #e0f2fe; color: #0369a1; padding: 4px 8px; border-radius: 4px; font-size: 12px;">
                                        Contratación Externa
                                    </span>
                                </td>
                            </tr>
                        </table>
                        <div style="margin-top: 25px; padding: 15px; background-color: #f0fdf4; border-left: 4px solid #22c55e; border-radius: 4px;">
                            <p style="margin: 0; color: #166534; font-size: 13px;">
                                <strong>Estado:</strong> Cerrada Exitosamente
                            </p>
                        </div>
                    </div>
                    <div style="background-color: #f8fafc; padding: 15px; text-align: center; border-top: 1px solid #e2e8f0;">
                        <p style="margin: 0; font-size: 12px; color: #94a3b8;">
                            Talento Humano {settings.BUSINESS_NAME}
                        </p>
                    </div>
                </div>
            </body>
            </html>
        """

    elif data.email_type == "event_invite":
        subject = "🔔 [TEST] Invitación: Capacitación de Liderazgo"
        body = """
            <div style="font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: 0 auto; border: 1px solid #eee; border-radius: 8px; overflow: hidden;">
                <div style="background-color: #003366; padding: 20px; text-align: center;">
                    <h2 style="color: white; margin: 0;">Invitación a Evento</h2>
                </div>
                <div style="padding: 20px;">
                    <p>Hola <strong>Juan Pérez</strong>,</p>
                    <p>Estás cordialmente invitado al evento <strong>Taller de Liderazgo Ágil</strong>.</p>
                    
                    <div style="background-color: #f8fafc; padding: 15px; border-left: 4px solid #3b82f6; margin: 20px 0;">
                        <p style="margin: 0; color: #64748b;">Fecha: <strong>15/03/2026</strong></p>
                        <p style="margin: 5px 0 0 0; color: #64748b;">Lugar: Auditorio Central</p>
                    </div>

                    <p style="text-align: center; margin: 30px 0;">
                        <a href="#" style="background-color: #003366; color: white; padding: 12px 25px; text-decoration: none; border-radius: 5px; font-weight: bold; font-size: 16px; display: inline-block;">
                            Confirmar Asistencia
                        </a>
                    </p>
                    
                    <p style="font-size: 12px; color: #666; text-align: center;">
                        Si no puedes asistir, por favor ignora este correo.
                    </p>
                </div>
            </div>
        """

    elif data.email_type == "vacancy_status":
        subject = "📊 [TEST] Estado de Vacante: Gerente de Marketing"
        body = """
        <!DOCTYPE html>
        <html>
        <body style="font-family: 'Helvetica', 'Arial', sans-serif; color: #333; line-height: 1.6;">
            <div style="max-width: 700px; margin: 0 auto; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden;">
                <div style="background-color: #003366; color: white; padding: 20px; text-align: center;">
                    <h2 style="margin:0;">Reporte de Estado de Vacante</h2>
                </div>
                <div style="padding: 20px; background-color: #ffffff;">
                    <div style="display: table; width: 100%; margin-bottom: 20px; background-color: #f8fafc; padding: 15px; border-radius: 6px;">
                        <div style="display: table-cell; width: 33%;">
                            <span style="font-size: 11px; text-transform: uppercase; color: #64748b; font-weight: bold; display: block;">Vacante</span>
                            <span style="font-size: 14px; font-weight: 600;">Gerente de Marketing</span>
                        </div>
                        <div style="display: table-cell; width: 33%;">
                            <span style="font-size: 11px; text-transform: uppercase; color: #64748b; font-weight: bold; display: block;">Estado Global</span>
                            <span style="font-size: 14px; font-weight: 600; color: #10B981;">12 / 45 días</span>
                        </div>
                    </div>
                    <h3 style="color: #003366; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px;">Detalle de Etapas</h3>
                    <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                        <thead>
                            <tr>
                                <th style="text-align: left; background-color: #f1f5f9; padding: 10px;">Etapa</th>
                                <th style="text-align: center; background-color: #f1f5f9; padding: 10px;">Estado</th>
                                <th style="text-align: center; background-color: #f1f5f9; padding: 10px;">SLA</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr style="border-bottom: 1px solid #eee;">
                                <td style="padding: 10px;">Revisión de CVs</td>
                                <td style="padding: 10px; text-align: center;"><span style="background-color: #d1fae5; color: #065f46; padding: 3px 8px; border-radius: 10px; font-size: 11px; font-weight: bold;">Completado</span></td>
                                <td style="padding: 10px; text-align: center;"><span style="color: #10B981; font-weight: bold;">En Tiempo</span></td>
                            </tr>
                            <tr style="border-bottom: 1px solid #eee;">
                                <td style="padding: 10px;">Entrevista Técnica</td>
                                <td style="padding: 10px; text-align: center;"><span style="background-color: #fef3c7; color: #92400e; padding: 3px 8px; border-radius: 10px; font-size: 11px; font-weight: bold;">Pendiente</span></td>
                                <td style="padding: 10px; text-align: center;"><span style="color: #EF4444; font-weight: bold;">Retrasado</span></td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </body>
        </html>
        """
    
    else: # Simple
        subject = "📧 [TEST] Prueba de Configuración SMTP"
        body = f"""
        <p>Hola,</p>
        <p>Este es un correo de prueba enviado desde el <strong>Sistema de Talento Humano UP</strong>.</p>
        <p>Si estás leyendo esto, la configuración SMTP es correcta.</p>
        <br>
        <p>Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</p>
        """

    await send_email_notification(
        db, data.recipients, subject, body, background_tasks, is_html=True
    )