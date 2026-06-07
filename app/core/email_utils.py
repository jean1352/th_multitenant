import logging
import aiosmtplib
from email.message import EmailMessage
from typing import List, Union
from app.core.config import settings

logger = logging.getLogger(__name__)

async def send_email_async(
    recipients: Union[List[str], str],
    subject: str,
    body: str,
    is_html: bool = False
) -> bool:
    """
    Envía un correo electrónico de forma asíncrona.
    Si settings.SMTP_ENABLED es False, solo simula el envío (Mock).
    """
    if isinstance(recipients, str):
        recipients = [recipients]

    if not settings.SMTP_ENABLED:
        logger.info(f"📨 [SMTP MOCK] Enviando correo a: {recipients}")
        logger.info(f"   Asunto: {subject}")
        logger.info(f"   Cuerpo: {body[:100]}...")
        return True

    try:
        message = EmailMessage()
        message["From"] = f"{settings.EMAILS_FROM_NAME} <{settings.EMAILS_FROM_EMAIL}>"
        message["To"] = ", ".join(recipients)
        message["Subject"] = subject
        
        if is_html:
            message.set_content(body, subtype="html")
        else:
            message.set_content(body)

        logger.info(f"🚀 Conectando a SMTP {settings.SMTP_HOST}:{settings.SMTP_PORT}...")
        
        await aiosmtplib.send(
            message,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            use_tls=settings.SMTP_TLS,
            start_tls=not settings.SMTP_TLS # Si no es TLS directo, usa STARTTLS
        )
        
        logger.info(f"✅ Correo enviado exitosamente a: {recipients}")
        return True

    except Exception as e:
        logger.error(f"❌ Error enviando email SMTP: {e}")
        return False