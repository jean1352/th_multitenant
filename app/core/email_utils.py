import logging
import aiosmtplib
from email.message import EmailMessage
from typing import List, Optional, Tuple, Union
from app.core.config import settings

logger = logging.getLogger(__name__)


async def send_email_async(
    recipients: Union[List[str], str],
    subject: str,
    body: str,
    is_html: bool = False,
    cc: Optional[Union[List[str], str]] = None,
    attachments: Optional[List[Tuple[str, bytes, str]]] = None,
) -> bool:
    """
    Envía un correo electrónico de forma asíncrona.
    Si settings.SMTP_ENABLED es False, solo simula el envío (Mock).
    `attachments`: lista opcional de tuplas (filename, content_bytes, mime_type) ej. ("invitacion.ics", b"...", "text/calendar").
    """
    if isinstance(recipients, str):
        recipients = [r.strip() for r in recipients.split(",") if r.strip()]

    cc_list: List[str] = []
    if cc:
        if isinstance(cc, str):
            cc_list = [c.strip() for c in cc.split(",") if c.strip()]
        else:
            cc_list = [c.strip() for c in cc if c and c.strip()]

    if not settings.SMTP_ENABLED:
        logger.info(f"📨 [SMTP MOCK] Enviando correo a: {recipients} (CC: {cc_list})")
        logger.info(f"   Asunto: {subject}")
        logger.info(f"   Cuerpo: {body[:100]}...")
        if attachments:
            logger.info(f"   Adjuntos: {[a[0] for a in attachments]}")
        return True

    try:
        message = EmailMessage()
        message["From"] = f"{settings.EMAILS_FROM_NAME} <{settings.EMAILS_FROM_EMAIL}>"
        message["To"] = ", ".join(recipients)
        if cc_list:
            message["Cc"] = ", ".join(cc_list)
        message["Subject"] = subject

        if is_html:
            message.set_content(body, subtype="html")
        else:
            message.set_content(body)

        if attachments:
            for filename, content_bytes, mime_type in attachments:
                maintype, subtype = (
                    mime_type.split("/", 1)
                    if "/" in mime_type
                    else ("application", "octet-stream")
                )
                message.add_attachment(
                    content_bytes,
                    maintype=maintype,
                    subtype=subtype,
                    filename=filename,
                )

        logger.info(f"🚀 Conectando a SMTP {settings.SMTP_HOST}:{settings.SMTP_PORT}...")

        await aiosmtplib.send(
            message,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            use_tls=settings.SMTP_TLS,
            start_tls=not settings.SMTP_TLS,
        )

        logger.info(f"✅ Correo enviado exitosamente a: {recipients}")
        return True

    except Exception as e:
        logger.error(f"❌ Error enviando email SMTP: {e}")
        return False