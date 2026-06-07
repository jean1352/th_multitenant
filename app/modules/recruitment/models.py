"""
Modelos ORM para el módulo de Reclutamiento.
Define las tablas para procesos, etapas, vacantes y seguimiento.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base

if TYPE_CHECKING:
    from app.modules.auth.models import User
    from app.modules.organization.models import Area, Position


class ProcessStatus(str, enum.Enum):
    """Estados posibles de una vacante."""
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class StageOwner(str, enum.Enum):
    """Responsable genérico de una etapa."""
    RECRUITER = "reclutador"
    AREA = "area"


class VacancyType(str, enum.Enum):
    """Tipos de vacante (Cobertura)."""
    EXTERNAL = "external"
    INTERNAL = "internal"
    TRANSFER = "transfer"


class RecruitmentProcess(Base):
    """Plantilla de un proceso de selección (ej. Administrativo, Docente)."""
    __tablename__ = "recruitment_processes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    stages_config: Mapped[List["ProcessStage"]] = relationship(
        back_populates="process",
        order_by="ProcessStage.order_index",
        cascade="all, delete-orphan",
    )


class HiringReason(Base):
    """Motivos de contratación configurables (ej. Reemplazo, Aumento dotación)."""
    __tablename__ = "hiring_reasons"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class StageEditReason(Base):
    """Motivos de edición de etapas (ej. Error fecha, Otro)."""
    __tablename__ = "stage_edit_reasons"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ProcessStage(Base):
    """Configuración de una etapa dentro de una plantilla de proceso."""
    __tablename__ = "process_stages"

    id: Mapped[int] = mapped_column(primary_key=True)
    process_id: Mapped[int] = mapped_column(
        ForeignKey("recruitment_processes.id")
    )

    name: Mapped[str] = mapped_column(String)
    sla_days: Mapped[int] = mapped_column(Integer)
    owner: Mapped[StageOwner] = mapped_column(SQLEnum(StageOwner))
    responsible_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id")
    )
    order_index: Mapped[int] = mapped_column(Integer)

    process: Mapped[RecruitmentProcess] = relationship(
        back_populates="stages_config"
    )
    responsible: Mapped["User"] = relationship("User")


class Vacancy(Base):
    """Instancia de una vacante real basada en un proceso."""
    __tablename__ = "vacancies"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[ProcessStatus] = mapped_column(
        SQLEnum(ProcessStatus), default=ProcessStatus.OPEN
    )
    
    vacancy_type: Mapped[Optional[VacancyType]] = mapped_column(
        SQLEnum(VacancyType), nullable=True
    )

    is_headcount_increase: Mapped[bool] = mapped_column(Boolean, default=False)

    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    area_id: Mapped[int] = mapped_column(ForeignKey("areas.id"))
    position_id: Mapped[Optional[int]] = mapped_column(ForeignKey("positions.id"))

    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    process_id: Mapped[int] = mapped_column(
        ForeignKey("recruitment_processes.id")
    )
    hiring_reason_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("hiring_reasons.id"), nullable=True
    )
    recruiter_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    stages: Mapped[List["VacancyStage"]] = relationship(
        back_populates="vacancy",
        order_by="VacancyStage.order_index",
        cascade="all, delete-orphan",
    )
    audits: Mapped[List["RecruitmentAudit"]] = relationship(
        back_populates="vacancy",
        order_by="desc(RecruitmentAudit.timestamp)",
        cascade="all, delete-orphan"
    )
    
    process: Mapped[RecruitmentProcess] = relationship()
    area: Mapped["Area"] = relationship(
        "app.modules.organization.models.Area", back_populates="vacancies"
    )
    position: Mapped["Position"] = relationship("app.modules.organization.models.Position")
    hiring_reason: Mapped["HiringReason"] = relationship()
    recruiter: Mapped["User"] = relationship("app.modules.auth.models.User", foreign_keys=[recruiter_id])


class VacancyStage(Base):
    """Instancia de una etapa para una vacante específica."""
    __tablename__ = "vacancy_stages"

    id: Mapped[int] = mapped_column(primary_key=True)
    vacancy_id: Mapped[int] = mapped_column(ForeignKey("vacancies.id"))

    name: Mapped[str] = mapped_column(String)
    owner: Mapped[StageOwner] = mapped_column(SQLEnum(StageOwner))
    responsible_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id")
    )
    sla_days_snapshot: Mapped[int] = mapped_column(Integer)
    order_index: Mapped[int] = mapped_column(Integer)

    start_date: Mapped[date] = mapped_column(
        Date, default=func.current_date()
    )
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    deadline_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    notes: Mapped[Optional[str]] = mapped_column(Text)

    vacancy: Mapped[Vacancy] = relationship(back_populates="stages")
    responsible: Mapped["User"] = relationship("User")


class RecruitmentAudit(Base):
    """Registro de auditoría para cambios en vacantes."""
    __tablename__ = "recruitment_audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    vacancy_id: Mapped[int] = mapped_column(ForeignKey("vacancies.id"))
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    
    action: Mapped[str] = mapped_column(String) # Ej: "STATUS_CHANGE", "STAGE_UPDATE"
    details: Mapped[str] = mapped_column(Text)
    
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    vacancy: Mapped[Vacancy] = relationship(back_populates="audits")
    user: Mapped["User"] = relationship("User")