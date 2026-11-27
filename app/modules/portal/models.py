"""
Modelos ORM para el módulo del Portal del Colaborador.
Incluye Solicitudes Formales de Vacaciones.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base

if TYPE_CHECKING:
    from app.modules.auth.models import User
    from app.modules.employees.models import Employee


class VacationRequest(Base):
    """Registro de solicitudes formales de vacaciones."""
    __tablename__ = "vacation_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_code: Mapped[str] = mapped_column(String, unique=True, index=True)  # ej: VAC001

    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    days_requested: Mapped[int] = mapped_column(Integer)
    business_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Estados: Pendiente, Aprobada, Rechazada, Cancelada
    status: Mapped[str] = mapped_column(String, default="Pendiente", index=True)

    # Superior / Aprobador esperado y efectivo
    assigned_approver_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("employees.id"), nullable=True
    )
    approver_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("employees.id"), nullable=True
    )
    reviewer_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    decision_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    # Relaciones
    employee: Mapped["Employee"] = relationship(
        "app.modules.employees.models.Employee",
        foreign_keys=[employee_id],
    )
    assigned_approver: Mapped[Optional["Employee"]] = relationship(
        "app.modules.employees.models.Employee",
        foreign_keys=[assigned_approver_id],
    )
    approver: Mapped[Optional["Employee"]] = relationship(
        "app.modules.employees.models.Employee",
        foreign_keys=[approver_id],
    )
    reviewer_user: Mapped[Optional["User"]] = relationship(
        "app.modules.auth.models.User",
        foreign_keys=[reviewer_user_id],
    )
