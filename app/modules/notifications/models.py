"""
Modelos ORM para el módulo de Notificaciones.
Define la tabla de logs de correos enviados.
"""

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum as SQLEnum, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class EmailStatus(str, enum.Enum):
    """Estados posibles de un envío de correo."""
    SENT = "sent"
    FAILED = "failed"
    PENDING = "pending"


class NotificationLog(Base):
    """Registro de auditoría de notificaciones enviadas."""
    __tablename__ = "notification_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipient: Mapped[str] = mapped_column(String)
    subject: Mapped[str] = mapped_column(String)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[EmailStatus] = mapped_column(
        SQLEnum(EmailStatus), default=EmailStatus.PENDING
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )