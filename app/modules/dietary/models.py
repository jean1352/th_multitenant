from __future__ import annotations
from typing import List, Optional, TYPE_CHECKING
from sqlalchemy import Column, ForeignKey, Integer, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

if TYPE_CHECKING:
    from app.modules.employees.models import Employee

# Tabla intermedia
employee_dietary_association = Table(
    "employee_dietary_association",
    Base.metadata,
    Column("employee_id", Integer, ForeignKey("employees.id"), primary_key=True),
    Column("dietary_restriction_id", Integer, ForeignKey("dietary_restrictions.id"), primary_key=True),
)

class DietaryRestriction(Base):
    """Catálogo de restricciones alimenticias."""
    __tablename__ = "dietary_restrictions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    description: Mapped[Optional[str]] = mapped_column(String)
    
    # Uso de string simple
    employees: Mapped[List["Employee"]] = relationship(
        "Employee",
        secondary=employee_dietary_association,
        back_populates="dietary_restrictions"
    )