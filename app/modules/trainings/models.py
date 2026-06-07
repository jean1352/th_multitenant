"""
Modelos ORM para el módulo de Capacitaciones.
Define las tablas para cursos, inscripciones, sesiones, asistencia y proveedores.
"""

import enum
from datetime import date, time
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Date,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    String,
    Text,
    Time,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TrainingStatus(str, enum.Enum):
    """Estados posibles de una capacitación."""
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TrainingType(str, enum.Enum):
    """Tipo de capacitación."""
    INTERNAL = "internal"
    EXTERNAL = "external"


class EnrollmentStatus(str, enum.Enum):
    """Estados de la inscripción de un empleado."""
    INVITED = "invited"
    ENROLLED = "enrolled"
    ATTENDED = "attended"
    NO_SHOW = "no_show"
    FAILED = "failed"
    DECLINED = "declined"


class SessionStatus(str, enum.Enum):
    """Estados de una sesión específica."""
    PENDING = "pending"
    OPEN = "open"
    CLOSED = "closed"


class TrainingProvider(Base):
    """Catálogo de Proveedores de Capacitación."""
    __tablename__ = "training_providers"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_name: Mapped[str] = mapped_column(String) # Razón Social
    ruc: Mapped[str] = mapped_column(String, unique=True)
    
    phone: Mapped[Optional[str]] = mapped_column(String)
    email: Mapped[Optional[str]] = mapped_column(String)
    contact_person: Mapped[Optional[str]] = mapped_column(String)
    address: Mapped[Optional[str]] = mapped_column(String)
    
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    trainings: Mapped[List["Training"]] = relationship(back_populates="provider_obj")


class Training(Base):
    """Modelo que representa una capacitación o curso."""
    __tablename__ = "trainings"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(Text)

    type: Mapped[TrainingType] = mapped_column(
        SQLEnum(TrainingType), default=TrainingType.EXTERNAL
    )
    
    # Si es EXTERNA (Relación con Proveedor)
    provider_id: Mapped[Optional[int]] = mapped_column(ForeignKey("training_providers.id"))
    
    cost_per_person: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    company_cost: Mapped[Optional[float]] = mapped_column(Float, default=0.0)

    # Si es INTERNA
    internal_instructor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("employees.id"))

    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)

    status: Mapped[TrainingStatus] = mapped_column(
        SQLEnum(TrainingStatus), default=TrainingStatus.PLANNED
    )

    # Relaciones
    provider_obj: Mapped[Optional[TrainingProvider]] = relationship(back_populates="trainings")
    
    internal_instructor: Mapped[Optional["app.modules.employees.models.Employee"]] = relationship(
        "app.modules.employees.models.Employee"
    )

    enrollments: Mapped[List["TrainingEnrollment"]] = relationship(
        back_populates="training", cascade="all, delete-orphan"
    )
    sessions: Mapped[List["TrainingSession"]] = relationship(
        back_populates="training",
        cascade="all, delete-orphan",
        order_by="TrainingSession.date, TrainingSession.start_time",
    )


class TrainingEnrollment(Base):
    """Modelo que vincula a un empleado con una capacitación."""
    __tablename__ = "training_enrollments"

    id: Mapped[int] = mapped_column(primary_key=True)
    training_id: Mapped[int] = mapped_column(ForeignKey("trainings.id"))
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))

    status: Mapped[EnrollmentStatus] = mapped_column(
        SQLEnum(EnrollmentStatus), default=EnrollmentStatus.ENROLLED
    )
    
    invitation_token: Mapped[Optional[str]] = mapped_column(String, unique=True, index=True)
    invitation_sent_at: Mapped[Optional[date]] = mapped_column(Date)

    knowledge_score: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    feedback: Mapped[Optional[str]] = mapped_column(Text)

    training: Mapped[Training] = relationship(back_populates="enrollments")
    employee: Mapped["app.modules.employees.models.Employee"] = relationship(
        back_populates="trainings"
    )
    attendances: Mapped[List["TrainingAttendance"]] = relationship(
        back_populates="enrollment", cascade="all, delete-orphan"
    )


class TrainingSession(Base):
    """Modelo para una sesión individual dentro de una capacitación."""
    __tablename__ = "training_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    training_id: Mapped[int] = mapped_column(ForeignKey("trainings.id"))

    topic: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(Text)
    instructor: Mapped[Optional[str]] = mapped_column(String)

    date: Mapped[date] = mapped_column(Date)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    status: Mapped[SessionStatus] = mapped_column(
        SQLEnum(SessionStatus), default=SessionStatus.PENDING
    )

    training: Mapped[Training] = relationship(back_populates="sessions")
    attendances: Mapped[List["TrainingAttendance"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class TrainingAttendance(Base):
    """Registro de asistencia."""
    __tablename__ = "training_attendances"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("training_sessions.id")
    )
    enrollment_id: Mapped[int] = mapped_column(
        ForeignKey("training_enrollments.id")
    )

    is_present: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[Optional[str]] = mapped_column(String)

    session: Mapped[TrainingSession] = relationship(
        back_populates="attendances"
    )
    enrollment: Mapped[TrainingEnrollment] = relationship(
        back_populates="attendances"
    )