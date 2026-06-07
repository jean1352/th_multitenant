"""
Modelos ORM para el módulo de Autenticación.
Define la tabla de usuarios y roles.
"""

from __future__ import annotations

import enum
from typing import Optional

from sqlalchemy import Boolean, Enum as SQLEnum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class UserRole(str, enum.Enum):
    """Roles de usuario disponibles en el sistema."""
    ADMIN = "admin"
    TH = "th"
    MANAGER = "manager"
    EMPLOYEE = "employee"


class User(Base):
    """Modelo que representa a un usuario del sistema (login)."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String)
    hashed_password: Mapped[str] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    role: Mapped[UserRole] = mapped_column(
        SQLEnum(UserRole), default=UserRole.EMPLOYEE
    )

    # Foreign Keys
    sede_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sedes.id"))
    area_id: Mapped[Optional[int]] = mapped_column(ForeignKey("areas.id"))
    
    # NUEVO: Vinculación con la tabla de empleados
    employee_id: Mapped[Optional[int]] = mapped_column(ForeignKey("employees.id"), nullable=True)

    # Relaciones (Strings para evitar importaciones circulares)
    area = relationship("app.modules.organization.models.Area")
    sede = relationship("app.modules.organization.models.Sede")
    employee = relationship("app.modules.employees.models.Employee")