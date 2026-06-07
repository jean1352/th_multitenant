"""
Modelos ORM para el módulo de Organización.
Define las tablas para Sedes, Áreas, Cargos y Tipos de Contrato.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, ForeignKey, String, Text, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.modules.employees.models import Employee
    from app.modules.recruitment.models import Vacancy


class Sede(Base):
    """Modelo que representa una sede física de la institución."""
    __tablename__ = "sedes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    address: Mapped[Optional[str]] = mapped_column(String)

    areas: Mapped[List[Area]] = relationship(
        back_populates="sede", cascade="all, delete-orphan"
    )


class Area(Base):
    """Modelo que representa un área o departamento dentro de una sede."""
    __tablename__ = "areas"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    responsible_email: Mapped[str] = mapped_column(
        String, nullable=False, default="th@upacifico.edu.py"
    )
    sede_id: Mapped[int] = mapped_column(ForeignKey("sedes.id"))

    sede: Mapped[Sede] = relationship(back_populates="areas")
    vacancies: Mapped[List["Vacancy"]] = relationship(
        "app.modules.recruitment.models.Vacancy", back_populates="area"
    )
    positions: Mapped[List[Position]] = relationship(
        back_populates="area", cascade="all, delete-orphan"
    )


class Position(Base):
    """Modelo que representa un cargo o puesto de trabajo."""
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    area_id: Mapped[int] = mapped_column(ForeignKey("areas.id"))
    
    # Campo nuevo
    is_leader: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Jerarquía (Jefe Inmediato)
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("positions.id"), nullable=True)

    area: Mapped[Area] = relationship(back_populates="positions")
    
    # Hijos: Cargos que reportan a este (Subordinados)
    children: Mapped[List["Position"]] = relationship(
        "Position",
        back_populates="parent",
    )
    
    # Padre: Cargo al que reporta este (Jefe)
    parent: Mapped[Optional["Position"]] = relationship(
        "Position",
        back_populates="children",
        remote_side=[id]
    )

    employees: Mapped[List["Employee"]] = relationship(
        "app.modules.employees.models.Employee",
        back_populates="position_obj"
    )


class Company(Base):
    """Modelo que representa una Razón Social / Empresa del Grupo."""
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    tax_id: Mapped[Optional[str]] = mapped_column(String)  # RUC


class ContractType(Base):
    """Catálogo de Tipos de Contrato (Indefinido, Plazo Fijo, etc.)."""
    __tablename__ = "contract_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class WorkingDayType(Base):
    """Catálogo de Tipos de Jornada Laboral."""
    __tablename__ = "working_day_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class SalaryType(Base):
    """Catálogo de Tipos de Remuneración (Fijo, Variable, Mixto)."""
    __tablename__ = "salary_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Currency(Base):
    """Catálogo de Monedas (GS, USD, etc.)."""
    __tablename__ = "currencies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    symbol: Mapped[Optional[str]] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class PaymentMethod(Base):
    """Catálogo de Formas de Pago."""
    __tablename__ = "payment_methods"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Bank(Base):
    """Catálogo de Bancos."""
    __tablename__ = "banks"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    code: Mapped[Optional[str]] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class CostCenter(Base):
    """Catálogo de Centros de Costo."""
    __tablename__ = "cost_centers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    code: Mapped[Optional[str]] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ProbationDuration(Base):
    """Catálogo de Duración de Periodos de Prueba (ej: 30, 60, 90 días)."""
    __tablename__ = "probation_durations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True) # "30 días"
    days: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class RelationshipType(Base):
    """Catálogo de Vínculos/Parentescos para contactos de emergencia."""
    __tablename__ = "relationship_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True) # "Cónyuge", "Padre/Madre", etc.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)