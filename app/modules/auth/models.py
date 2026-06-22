"""
Modelos ORM para el módulo de Autenticación.
Define la tabla de usuarios, roles y permisos (RBAC).
"""

from __future__ import annotations

import enum
from typing import Optional

from sqlalchemy import Boolean, Enum as SQLEnum, ForeignKey, String, Table, Column, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class UserRole(str, enum.Enum):
    """Roles de usuario estándar disponibles en el sistema (compatibilidad)."""
    ADMIN = "admin"
    TH = "th"
    MANAGER = "manager"
    EMPLOYEE = "employee"


class Permission(Base):
    """Modelo que representa un permiso granular del sistema."""
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    code: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    module: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class Role(Base):
    """Modelo que representa un rol personalizado de usuario."""
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    is_custom: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relaciones
    permissions = relationship("Permission", secondary="role_permissions", backref="roles")


# Tabla asociativa muchos a muchos para Roles y Permisos
role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", Integer, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True)
)


class User(Base):
    """Modelo que representa a un usuario del sistema (login)."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String)
    hashed_password: Mapped[str] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # Campo estático original para mantener retrocompatibilidad total
    role: Mapped[UserRole] = mapped_column(
        SQLEnum(UserRole), default=UserRole.EMPLOYEE
    )

    # Nuevos campos relacionales para el sistema RBAC dinámico
    role_id: Mapped[Optional[int]] = mapped_column(ForeignKey("roles.id"), nullable=True)

    # Foreign Keys
    sede_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sedes.id"))
    area_id: Mapped[Optional[int]] = mapped_column(ForeignKey("areas.id"))
    
    # NUEVO: Vinculación con la tabla de empleados
    employee_id: Mapped[Optional[int]] = mapped_column(ForeignKey("employees.id"), nullable=True)

    # Relaciones (Strings para evitar importaciones circulares)
    area = relationship("app.modules.organization.models.Area")
    sede = relationship("app.modules.organization.models.Sede")
    employee = relationship("app.modules.employees.models.Employee")
    role_obj = relationship("Role")