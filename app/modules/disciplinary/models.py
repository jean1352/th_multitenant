from __future__ import annotations

import enum
from datetime import date
from typing import Optional, TYPE_CHECKING

from sqlalchemy import Boolean, Date, Enum as SQLEnum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.modules.employees.models import Employee

class SanctionType(str, enum.Enum):
    VERBAL = "verbal"
    WRITTEN = "written"
    SUSPENSION = "suspension"
    DISMISSAL = "dismissal"

class RecognitionType(str, enum.Enum):
    ACHIEVEMENT = "achievement"
    SERVICE = "service"
    EXCELLENCE = "excellence"
    INNOVATION = "innovation"
    OTHER = "other"

class Sanction(Base):
    """Registro de amonestaciones y sanciones."""
    __tablename__ = "sanctions"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    
    type: Mapped[SanctionType] = mapped_column(SQLEnum(SanctionType))
    date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(Text)
    
    sent_to_ministry: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    # Uso de string simple para evitar problemas de importación
    employee: Mapped["Employee"] = relationship(
        "Employee", back_populates="sanctions"
    )

class Recognition(Base):
    """Registro de reconocimientos y premios."""
    __tablename__ = "recognitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    
    type: Mapped[RecognitionType] = mapped_column(SQLEnum(RecognitionType))
    date: Mapped[date] = mapped_column(Date)
    title: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(Text)

    employee: Mapped["Employee"] = relationship(
        "Employee", back_populates="recognitions"
    )