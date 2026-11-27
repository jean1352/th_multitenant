"""
Gestión de parámetros configurables (RF-30) y plantillas de correo N-01..N-11 (RF-31).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.trainings.models import TrainingEmailTemplate, TrainingParameter
from app.modules.trainings.utils import log_training_audit

DEFAULT_PARAMETERS: List[Dict[str, str]] = [
    {
        "key": "min_attendance_pct",
        "value": "80",
        "description": "Porcentaje mínimo de asistencia requerido para aprobar.",
        "value_type": "float",
    },
    {
        "key": "late_counts_as_present",
        "value": "true",
        "description": "Si Tardanza cuenta como presente para el cálculo de asistencia.",
        "value_type": "bool",
    },
    {
        "key": "justified_counts_as_present",
        "value": "true",
        "description": "Si Justificado cuenta como presente para el cálculo de asistencia.",
        "value_type": "bool",
    },
    {
        "key": "replica_deadline_months",
        "value": "3",
        "description": "Plazo máximo en meses calendario para cumplir la réplica.",
        "value_type": "int",
    },
    {
        "key": "replica_min_attendees",
        "value": "3",
        "description": "Mínimo de asistentes presentes requeridos para cumplir una réplica.",
        "value_type": "int",
    },
    {
        "key": "qr_window_minutes",
        "value": "30",
        "description": "Ventana de tiempo en minutos desde el inicio de la sesión para marcar asistencia por QR.",
        "value_type": "int",
    },
    {
        "key": "alert_days_start",
        "value": "7",
        "description": "Días de anticipación antes del inicio para enviar la alerta de próximo inicio.",
        "value_type": "int",
    },
    {
        "key": "alert_days_reminder",
        "value": "1",
        "description": "Días de anticipación para el recordatorio final.",
        "value_type": "int",
    },
    {
        "key": "alert_days_ending",
        "value": "3",
        "description": "Días de anticipación antes de la fecha de fin para la alerta de próxima conclusión.",
        "value_type": "int",
    },
    {
        "key": "alert_days_cert_pending",
        "value": "7",
        "description": "Días después del cierre de una externa para alertar certificado pendiente del proveedor.",
        "value_type": "int",
    },
    {
        "key": "alert_days_replica",
        "value": "60,30,15,7",
        "description": "Días antes de la fecha límite de réplica para enviar recordatorios (separados por coma).",
        "value_type": "str",
    },
]


DEFAULT_EMAIL_TEMPLATES: List[Dict[str, str]] = [
    {
        "event_code": "N-01",
        "name": "Convocatoria / Inscripción",
        "subject_template": "Convocatoria: {{capacitacion}}",
        "body_template": (
            "<p>Hola <strong>{{nombre}}</strong>,</p>"
            "<p>Has sido convocado/inscrito a la capacitación <strong>{{capacitacion}}</strong>.</p>"
            "<p>Fechas: {{fecha_inicio}} al {{fecha_fin}} | Modalidad: {{modalidad}} | Lugar/Enlace: {{sede_o_enlace}}</p>"
            "<p>Adjuntamos la invitación de calendario (.ics). Puedes confirmar o declinar tu asistencia aquí: "
            "<a href='{{enlace}}'>Responder Invitación</a></p>"
        ),
    },
    {
        "event_code": "N-02",
        "name": "Próximo inicio",
        "subject_template": "Próximo inicio: {{capacitacion}}",
        "body_template": (
            "<p>Hola <strong>{{nombre}}</strong>,</p>"
            "<p>Te recordamos que la capacitación <strong>{{capacitacion}}</strong> inicia el <strong>{{fecha_inicio}}</strong>.</p>"
            "<p>Lugar o enlace: {{sede_o_enlace}}</p>"
        ),
    },
    {
        "event_code": "N-03",
        "name": "Recordatorio final",
        "subject_template": "Recordatorio final: {{capacitacion}}",
        "body_template": (
            "<p>Hola <strong>{{nombre}}</strong>,</p>"
            "<p>Mañana inicia <strong>{{capacitacion}}</strong> ({{fecha_inicio}}).</p>"
            "<p>Lugar o enlace: {{sede_o_enlace}}</p>"
            "<p>{{detalle_extra}}</p>"
        ),
    },
    {
        "event_code": "N-04",
        "name": "Próxima conclusión",
        "subject_template": "Próxima conclusión: {{capacitacion}}",
        "body_template": (
            "<p>Hola <strong>{{nombre}}</strong>,</p>"
            "<p>La capacitación <strong>{{capacitacion}}</strong> finaliza el <strong>{{fecha_fin}}</strong>.</p>"
            "<p>Tu asistencia actual es del <strong>{{porcentaje_asistencia}}%</strong> (mínimo requerido: {{minimo_asistencia}}%).</p>"
        ),
    },
    {
        "event_code": "N-05",
        "name": "Riesgo por asistencia",
        "subject_template": "Alerta de riesgo por asistencia: {{capacitacion}}",
        "body_template": (
            "<p>Hola <strong>{{nombre}}</strong>,</p>"
            "<p>Tu porcentaje máximo alcanzable de asistencia en <strong>{{capacitacion}}</strong> cayó por debajo del mínimo requerido ({{minimo_asistencia}}%).</p>"
            "<p>Asistencia actual: {{porcentaje_asistencia}}%.</p>"
        ),
    },
    {
        "event_code": "N-06",
        "name": "Conclusión y resultados",
        "subject_template": "Cierre y resultados: {{capacitacion}}",
        "body_template": (
            "<p>Hola <strong>{{nombre}}</strong>,</p>"
            "<p>La capacitación <strong>{{capacitacion}}</strong> ha sido cerrada.</p>"
            "<p>Resultado: <strong>{{resultado}}</strong> | Asistencia: <strong>{{porcentaje_asistencia}}%</strong></p>"
            "<p>{{detalle_extra}}</p>"
            "<p>Completa la encuesta de satisfacción y descarga tu certificado en tu portal: <a href='{{enlace}}'>Ir a Mis Capacitaciones</a></p>"
        ),
    },
    {
        "event_code": "N-07",
        "name": "Certificado pendiente (externa)",
        "subject_template": "Certificado pendiente: {{capacitacion}}",
        "body_template": (
            "<p>Hola <strong>{{nombre}}</strong>,</p>"
            "<p>La capacitación externa <strong>{{capacitacion}}</strong> fue cerrada hace más de 7 días y aún no tiene certificado del proveedor cargado.</p>"
            "<p>Por favor gestiona la carga del certificado en el sistema: <a href='{{enlace}}'>Ir al sistema</a></p>"
        ),
    },
    {
        "event_code": "N-08",
        "name": "Recordatorio de réplica",
        "subject_template": "Recordatorio de réplica ({{dias_restantes}} días): {{capacitacion}}",
        "body_template": (
            "<p>Hola <strong>{{nombre}}</strong>,</p>"
            "<p>Tienes un compromiso de réplica pendiente de la capacitación externa <strong>{{capacitacion}}</strong>.</p>"
            "<p>Fecha límite: <strong>{{fecha_limite}}</strong> (faltan <strong>{{dias_restantes}} días</strong>).</p>"
            "<p>Propón tu réplica aquí: <a href='{{enlace}}'>Mis Réplicas</a></p>"
        ),
    },
    {
        "event_code": "N-09",
        "name": "Convocatoria de réplica",
        "subject_template": "Convocatoria a Réplica: {{capacitacion}}",
        "body_template": (
            "<p>Hola <strong>{{nombre}}</strong>,</p>"
            "<p>Has sido convocado a la <strong>Réplica Interna</strong>: <strong>{{capacitacion}}</strong>.</p>"
            "<p>Fecha: {{fecha_inicio}} | Modalidad: {{modalidad}} | Lugar/Enlace: {{sede_o_enlace}}</p>"
            "<p>Adjuntamos la invitación de calendario (.ics).</p>"
        ),
    },
    {
        "event_code": "N-10",
        "name": "Réplica vencida (Escalamiento)",
        "subject_template": "ALERTA: Compromiso de réplica vencido - {{nombre}}",
        "body_template": (
            "<p>Se informa que el compromiso de réplica de <strong>{{nombre}}</strong> para la capacitación <strong>{{capacitacion}}</strong> ha pasado a estado <strong>VENCIDO</strong>.</p>"
            "<p>Fecha límite: {{fecha_limite}}. Siguiente paso: revisar con Jefe de Área y Talento Humano (o registrar prórroga justificada si aplica).</p>"
        ),
    },
    {
        "event_code": "N-11",
        "name": "Resumen semanal TH",
        "subject_template": "Resumen semanal de Capacitaciones - Talento Humano",
        "body_template": (
            "<h3>Resumen Semanal de Capacitaciones</h3>"
            "<p>{{detalle_extra}}</p>"
            "<p><a href='{{enlace}}'>Abrir Módulo de Capacitaciones</a></p>"
        ),
    },
]

async def ensure_default_parameters_and_templates(db: AsyncSession) -> None:
    """Siembra parámetros y plantillas por defecto si no existen."""
    existing_keys = set((await db.execute(select(TrainingParameter.key))).scalars().all())
    added = False
    for p in DEFAULT_PARAMETERS:
        if p["key"] not in existing_keys:
            db.add(TrainingParameter(**p))
            added = True

    existing_codes = set((await db.execute(select(TrainingEmailTemplate.event_code))).scalars().all())
    for t in DEFAULT_EMAIL_TEMPLATES:
        if t["event_code"] not in existing_codes:
            db.add(TrainingEmailTemplate(**t))
            added = True

    if added:
        await db.commit()


async def get_all_parameters(db: AsyncSession) -> List[TrainingParameter]:
    await ensure_default_parameters_and_templates(db)
    return (await db.execute(select(TrainingParameter).order_by(TrainingParameter.key))).scalars().all()


async def get_parameters_dict(db: AsyncSession) -> Dict[str, Any]:
    params = await get_all_parameters(db)
    result: Dict[str, Any] = {}
    for p in params:
        if p.value_type == "int":
            try:
                result[p.key] = int(p.value)
            except ValueError:
                result[p.key] = 0
        elif p.value_type == "float":
            try:
                result[p.key] = float(p.value)
            except ValueError:
                result[p.key] = 0.0
        elif p.value_type == "bool":
            result[p.key] = str(p.value).strip().lower() in ("true", "1", "si", "yes")
        else:
            result[p.key] = p.value
    return result


async def update_parameter(
    db: AsyncSession, key: str, value: str, user_id: Optional[int] = None
) -> Optional[TrainingParameter]:
    await ensure_default_parameters_and_templates(db)
    param = await db.get(TrainingParameter, key)
    if not param:
        return None
    old_val = param.value
    param.value = str(value).strip()
    await log_training_audit(
        db, "parameter", 0, "UPDATE", field=key, old_value=old_val, new_value=param.value, user_id=user_id
    )
    await db.commit()
    await db.refresh(param)
    return param


async def get_all_templates(db: AsyncSession) -> List[TrainingEmailTemplate]:
    await ensure_default_parameters_and_templates(db)
    return (
        await db.execute(select(TrainingEmailTemplate).order_by(TrainingEmailTemplate.event_code))
    ).scalars().all()


async def update_template(
    db: AsyncSession,
    event_code: str,
    subject_template: str,
    body_template: str,
    is_active: bool = True,
    user_id: Optional[int] = None,
) -> Optional[TrainingEmailTemplate]:
    await ensure_default_parameters_and_templates(db)
    tpl = (
        await db.execute(
            select(TrainingEmailTemplate).where(TrainingEmailTemplate.event_code == event_code)
        )
    ).scalar_one_or_none()
    if not tpl:
        return None
    old_subj = tpl.subject_template
    tpl.subject_template = subject_template
    tpl.body_template = body_template
    tpl.is_active = is_active
    await log_training_audit(
        db,
        "template",
        tpl.id,
        "UPDATE",
        field=event_code,
        old_value=old_subj,
        new_value=subject_template,
        user_id=user_id,
    )
    await db.commit()
    await db.refresh(tpl)
    return tpl


def render_template_text(template_str: str, variables: Dict[str, Any]) -> str:
    rendered = template_str or ""
    for k, v in variables.items():
        rendered = rendered.replace("{{" + str(k) + "}}", str(v if v is not None else ""))
    return rendered


async def render_event_email(
    db: AsyncSession, event_code: str, variables: Dict[str, Any]
) -> Dict[str, Any]:
    await ensure_default_parameters_and_templates(db)
    tpl = (
        await db.execute(
            select(TrainingEmailTemplate).where(TrainingEmailTemplate.event_code == event_code)
        )
    ).scalar_one_or_none()
    if not tpl:
        return {"subject": f"[{event_code}] Notificación", "body": "", "is_active": True}

    subject = render_template_text(tpl.subject_template, variables)
    body_inner = render_template_text(tpl.body_template, variables)
    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="margin:0; padding:0; background-color:#f1f5f9; font-family:Arial, sans-serif;">
        <div style="max-width:620px; margin:20px auto; background-color:#ffffff; border-radius:8px; overflow:hidden; border:1px solid #e2e8f0;">
            <div style="background-color:#003366; color:#ffffff; padding:18px 24px;">
                <h2 style="margin:0; font-size:18px;">{settings.BUSINESS_NAME} · Capacitaciones</h2>
            </div>
            <div style="padding:24px; color:#334155; font-size:14px; line-height:1.6;">
                {body_inner}
            </div>
            <div style="background-color:#f8fafc; padding:14px 24px; text-align:center; font-size:11px; color:#94a3b8; border-top:1px solid #e2e8f0;">
                Mensaje automático del Sistema de Gestión de Talento Humano ({event_code})
            </div>
        </div>
    </body>
    </html>
    """
    return {"subject": subject, "body": html, "is_active": tpl.is_active}

