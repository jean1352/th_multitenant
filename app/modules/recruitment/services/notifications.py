"""
Notificaciones estandarizadas del módulo de Reclutamiento.

Centraliza el formato (asunto + cuerpo HTML) de los correos relacionados con
el SLA de las etapas, para que todos los mensajes sean consistentes.
"""

from datetime import date, datetime
from typing import Optional, Tuple

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.notifications.service import send_email_notification
from app.modules.recruitment.models import Vacancy, VacancyStage


def _clean(value: Optional[str]) -> str:
    """Sanitiza texto para evitar saltos de línea que rompan el HTML/cabeceras."""
    return (value or "").replace("\n", " ").replace("\r", "").strip()


def _date_str(value: Optional[date]) -> str:
    return value.strftime("%d/%m/%Y") if value else "-"


def render_sla_stage_email(
    vacancy: Vacancy,
    stage: VacancyStage,
    kind: str,
    remaining_business_days: int = 0,
    dedup_key: str = "",
) -> Tuple[str, str]:
    """Genera el (subject, html_body) de una alerta de SLA de una etapa.

    `kind` puede ser "proximo" (está por vencer) o "vencido" (ya venció).
    `dedup_key` es un marcador opcional que se agrega al asunto para poder
    evitar envíos duplicados (se consulta en NotificationLog).
    """
    vac_title = _clean(vacancy.title)
    stage_name = _clean(stage.name)
    area_name = _clean(vacancy.area.name) if vacancy.area else "-"
    deadline = _date_str(stage.deadline_date)
    start = _date_str(stage.start_date)

    if kind == "vencido":
        subject = f"SLA Vencido: {stage_name} - {vac_title}"
        status_color = "#EF4444"
        status_text = "VENCIDA"
        detail = (
            f"La etapa <strong>{stage_name}</strong> de la vacante "
            f"<strong>{vac_title}</strong> ha superado su fecha límite de "
            f"<strong>{deadline}</strong> y aún se encuentra pendiente."
        )
    else:
        subject = f"SLA Próximo a Vencer: {stage_name} - {vac_title}"
        status_color = "#F59E0B"
        status_text = "POR VENCER"
        detail = (
            f"La etapa <strong>{stage_name}</strong> de la vacante "
            f"<strong>{vac_title}</strong> vence el <strong>{deadline}</strong> "
            f"({remaining_business_days} día(s) hábil(es) restantes)."
        )

    if dedup_key:
        subject = f"{subject} [{dedup_key}]"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="margin:0; padding:0; background-color:#f1f5f9; font-family:Arial, sans-serif;">
        <div style="max-width:600px; margin:0 auto; background-color:#ffffff;">
            <div style="background-color:#003366; color:#ffffff; padding:20px; text-align:center;">
                <h2 style="margin:0; font-size:18px;">Alerta de SLA</h2>
            </div>
            <div style="padding:24px;">
                <p>Estimado solicitante,</p>
                <p>{detail}</p>

                <table style="width:100%; border-collapse:collapse; font-size:13px; margin:20px 0;">
                    <tr>
                        <td style="padding:8px; background-color:#f8fafc; font-weight:bold; width:40%;">Vacante</td>
                        <td style="padding:8px;">{vac_title}</td>
                    </tr>
                    <tr>
                        <td style="padding:8px; background-color:#f8fafc; font-weight:bold;">Área</td>
                        <td style="padding:8px;">{area_name}</td>
                    </tr>
                    <tr>
                        <td style="padding:8px; background-color:#f8fafc; font-weight:bold;">Etapa</td>
                        <td style="padding:8px;">{stage_name}</td>
                    </tr>
                    <tr>
                        <td style="padding:8px; background-color:#f8fafc; font-weight:bold;">Inicio</td>
                        <td style="padding:8px;">{start}</td>
                    </tr>
                    <tr>
                        <td style="padding:8px; background-color:#f8fafc; font-weight:bold;">Fecha límite (SLA)</td>
                        <td style="padding:8px;">{deadline}</td>
                    </tr>
                    <tr>
                        <td style="padding:8px; background-color:#f8fafc; font-weight:bold;">Estado</td>
                        <td style="padding:8px;">
                            <span style="background-color:{status_color}; color:#ffffff; padding:3px 10px; border-radius:12px; font-size:11px; font-weight:bold;">{status_text}</span>
                        </td>
                    </tr>
                </table>

                <p>Por favor ingrese al sistema para revisar y gestionar esta etapa.</p>
            </div>
            <div style="background-color:#f8fafc; padding:15px; text-align:center; font-size:11px; color:#94a3b8; border-top:1px solid #e5e7eb;">
                Este es un correo automático generado por el sistema de Talento Humano.<br>
                &copy; {datetime.now().year} {settings.BUSINESS_NAME}.
            </div>
        </div>
    </body>
    </html>
    """

    return subject, html


async def send_sla_stage_alert(
    db: AsyncSession,
    vacancy: Vacancy,
    stage: VacancyStage,
    recipient_email: str,
    kind: str,
    remaining_business_days: int = 0,
    dedup_key: str = "",
    background_tasks: Optional[BackgroundTasks] = None,
) -> bool:
    """Envía una alerta de SLA estandarizada al solicitante de la vacante."""
    subject, html = render_sla_stage_email(
        vacancy, stage, kind, remaining_business_days, dedup_key
    )
    await send_email_notification(
        db,
        recipient_email,
        subject,
        html,
        background_tasks,
        is_html=True,
    )
    return True
