"""
Modelos ORM para el módulo de Calendario.
Define las tablas para eventos, tipos de eventos y las inscripciones.
"""

import enum
from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class EnrollmentStatus(str, enum.Enum):
    """Estado de la inscripción al evento."""
    CONFIRMED = "confirmed"
    INVITED = "invited"
    DECLINED = "declined"


class CalendarEventType(Base):
    """Catálogo dinámico de tipos de eventos."""
    __tablename__ = "calendar_event_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    color: Mapped[str] = mapped_column(String, default="#3B82F6") # Hex color
    affects_sla: Mapped[bool] = mapped_column(Boolean, default=False) # Si es True, cuenta como día NO hábil
    description: Mapped[Optional[str]] = mapped_column(String)

    events: Mapped[List["CalendarEvent"]] = relationship(back_populates="event_type")


class CalendarEvent(Base):
    """Modelo que representa un evento en el calendario."""
    __tablename__ = "calendar_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(Text)
    date: Mapped[date] = mapped_column(Date)
    
    # Relación con el tipo dinámico
    event_type_id: Mapped[int] = mapped_column(ForeignKey("calendar_event_types.id"))

    is_enrollable: Mapped[bool] = mapped_column(Boolean, default=False)

    event_type: Mapped[CalendarEventType] = relationship(back_populates="events")
    
    enrollments: Mapped[List["EventEnrollment"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )


class EventEnrollment(Base):
    """Modelo que vincula a un empleado con un evento (inscripción)."""
    __tablename__ = "event_enrollments"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("calendar_events.id"))
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))

    status: Mapped[EnrollmentStatus] = mapped_column(
        SQLEnum(EnrollmentStatus, name="calendar_enrollment_status"), 
        default=EnrollmentStatus.CONFIRMED
    )
    
    invitation_token: Mapped[Optional[str]] = mapped_column(
        String, unique=True, index=True
    )
    invitation_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    response_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )

    event: Mapped[CalendarEvent] = relationship(back_populates="enrollments")
    employee: Mapped["app.modules.employees.models.Employee"] = relationship()