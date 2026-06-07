"""
Modelos ORM para el módulo de Colaboradores.
"""
from __future__ import annotations

import enum
from datetime import date, datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, Date, DateTime, Enum as SQLEnum, ForeignKey, String, Text, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base
from app.modules.dietary.models import employee_dietary_association

if TYPE_CHECKING:
    from app.modules.organization.models import (
        Position, Company, ContractType, WorkingDayType, 
        SalaryType, Currency, PaymentMethod, Bank, CostCenter,
        ProbationDuration, RelationshipType
    )
    from app.modules.trainings.models import TrainingEnrollment
    from app.modules.benefits.models import EmployeeBenefit
    from app.modules.disciplinary.models import Sanction, Recognition
    from app.modules.dietary.models import DietaryRestriction


class MovementType(str, enum.Enum):
    ENTRY = "entry"
    PROMOTION = "promotion"
    TRANSFER = "transfer"
    EXIT = "exit"
    REHIRE = "rehire"
    ADD_ROLE = "add_role"
    REMOVE_ROLE = "remove_role"
    CONTRACT_CHANGE = "contract_change"
    SALARY_CHANGE = "salary_change"  # <--- NUEVO TIPO


class EmploymentStatus(str, enum.Enum):
    ACTIVE = "active"
    LICENSE = "license"
    VACATION = "vacation"
    SUSPENDED = "suspended"
    RETIRED = "retired"


class DocumentCategory(str, enum.Enum):
    ID = "id"
    CONTRACT = "contract"
    EDUCATION = "education"
    MEDICAL = "medical"
    OTHER = "other"


class EmergencyContact(Base):
    __tablename__ = "emergency_contacts"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String)
    relationship_id: Mapped[Optional[int]] = mapped_column(ForeignKey("relationship_types.id"), nullable=True)
    phone: Mapped[str] = mapped_column(String)
    
    employee: Mapped["Employee"] = relationship("Employee", back_populates="emergency_contacts")
    relationship: Mapped[Optional["RelationshipType"]] = relationship("app.modules.organization.models.RelationshipType")

class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str] = mapped_column(String, nullable=True)
    last_name: Mapped[str] = mapped_column(String, nullable=True)
    full_name: Mapped[str] = mapped_column(String)
    document_id: Mapped[str] = mapped_column(String, unique=True)
    position_id: Mapped[int] = mapped_column(ForeignKey("positions.id"))

    gender: Mapped[Optional[str]] = mapped_column(String)
    marital_status: Mapped[Optional[str]] = mapped_column(String)
    nationality: Mapped[Optional[str]] = mapped_column(String)
    
    # CONTACTO Y UBICACIÓN
    address: Mapped[Optional[str]] = mapped_column(String) # Dirección Particular
    personal_email: Mapped[Optional[str]] = mapped_column(String) # Email Particular
    phone: Mapped[Optional[str]] = mapped_column(String) # Telefono Personal

    internal_extension: Mapped[Optional[str]] = mapped_column(String)
    office_location: Mapped[Optional[str]] = mapped_column(String)
    
    employment_status: Mapped[EmploymentStatus] = mapped_column(
        SQLEnum(EmploymentStatus), default=EmploymentStatus.ACTIVE
    )

    institutional_email: Mapped[Optional[str]] = mapped_column(String)
    secondary_emails: Mapped[Optional[str]] = mapped_column(Text)
    personal_email: Mapped[Optional[str]] = mapped_column(String)
    photo_url: Mapped[Optional[str]] = mapped_column(String)
    birthday: Mapped[Optional[date]] = mapped_column(Date)
    blood_type: Mapped[Optional[str]] = mapped_column(String)
    
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    exit_date: Mapped[Optional[date]] = mapped_column(Date)

    company_id: Mapped[Optional[int]] = mapped_column(ForeignKey("companies.id"), nullable=True)
    
    # Relaciones
    position_obj: Mapped["Position"] = relationship("Position", back_populates="employees")
    company: Mapped[Optional["Company"]] = relationship("app.modules.organization.models.Company")
    
    emergency_contacts: Mapped[List["EmergencyContact"]] = relationship(
        "EmergencyContact", back_populates="employee", cascade="all, delete-orphan"
    )
    
    dietary_restrictions: Mapped[List["DietaryRestriction"]] = relationship(
        "DietaryRestriction",
        secondary=employee_dietary_association,
        back_populates="employees"
    )

    positions_history: Mapped[List["EmployeePosition"]] = relationship(
        "EmployeePosition", back_populates="employee", cascade="all, delete-orphan"
    )

    trainings: Mapped[List["TrainingEnrollment"]] = relationship(
        "TrainingEnrollment", back_populates="employee"
    )
    
    history: Mapped[List["EmployeeHistory"]] = relationship(
        "EmployeeHistory", back_populates="employee", order_by="desc(EmployeeHistory.date)"
    )
    
    documents: Mapped[List["EmployeeDocument"]] = relationship(
        "EmployeeDocument", back_populates="employee", cascade="all, delete-orphan"
    )
    
    benefits: Mapped[List["EmployeeBenefit"]] = relationship(
        "EmployeeBenefit", back_populates="employee", cascade="all, delete-orphan"
    )

    sanctions: Mapped[List["Sanction"]] = relationship(
        "Sanction", 
        back_populates="employee", 
        cascade="all, delete-orphan"
    )

    recognitions: Mapped[List["Recognition"]] = relationship(
        "Recognition", 
        back_populates="employee", 
        cascade="all, delete-orphan"
    )

    @property
    def all_emails(self) -> str:
        emails = []
        if self.institutional_email:
            emails.append(self.institutional_email)
        if self.secondary_emails:
            secs = [e.strip() for e in self.secondary_emails.split(",") if e.strip()]
            emails.extend(secs)
        return ", ".join(emails)


class EmployeeDocument(Base):
    __tablename__ = "employee_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    name: Mapped[str] = mapped_column(String)
    category: Mapped[DocumentCategory] = mapped_column(SQLEnum(DocumentCategory))
    file_url: Mapped[str] = mapped_column(String)
    upload_date: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    
    expiration_date: Mapped[Optional[date]] = mapped_column(Date)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    
    employee: Mapped["Employee"] = relationship("Employee", back_populates="documents")


class EmployeePosition(Base):
    __tablename__ = "employee_positions"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    position_id: Mapped[int] = mapped_column(ForeignKey("positions.id"))
    company_id: Mapped[Optional[int]] = mapped_column(ForeignKey("companies.id"), nullable=True)
    
    # NUEVO: Tipo de Contrato asociado a este cargo
    contract_type_id: Mapped[Optional[int]] = mapped_column(ForeignKey("contract_types.id"), nullable=True)
    
    # NUEVOS CAMPOS DE CONTRATACIÓN
    contract_end_date: Mapped[Optional[date]] = mapped_column(Date)
    working_day_type_id: Mapped[Optional[int]] = mapped_column(ForeignKey("working_day_types.id"), nullable=True)
    work_schedule: Mapped[Optional[str]] = mapped_column(String)
    work_days: Mapped[Optional[str]] = mapped_column(String)
    salary_type_id: Mapped[Optional[int]] = mapped_column(ForeignKey("salary_types.id"), nullable=True)
    base_salary: Mapped[Optional[float]] = mapped_column(Numeric(15, 2))
    currency_id: Mapped[Optional[int]] = mapped_column(ForeignKey("currencies.id"), nullable=True)
    payment_method_id: Mapped[Optional[int]] = mapped_column(ForeignKey("payment_methods.id"), nullable=True)
    bank_id: Mapped[Optional[int]] = mapped_column(ForeignKey("banks.id"), nullable=True)
    cost_center_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cost_centers.id"), nullable=True)

    # PERIODO DE PRUEBA
    probation_duration_id: Mapped[Optional[int]] = mapped_column(ForeignKey("probation_durations.id"), nullable=True)
    probation_start_date: Mapped[Optional[date]] = mapped_column(Date)
    probation_end_date: Mapped[Optional[date]] = mapped_column(Date)
    probation_evaluation: Mapped[Optional[str]] = mapped_column(String) # Aprobado / No aprobado / Pendiente
    probation_status: Mapped[Optional[str]] = mapped_column(String, default="Pendiente") # Pendiente / Finalizado

    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    start_date: Mapped[date] = mapped_column(Date, default=func.current_date())
    end_date: Mapped[Optional[date]] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    
    employee: Mapped["Employee"] = relationship("Employee", back_populates="positions_history")
    position: Mapped["Position"] = relationship("Position")
    company: Mapped[Optional["Company"]] = relationship("app.modules.organization.models.Company")
    contract_type: Mapped[Optional["ContractType"]] = relationship("app.modules.organization.models.ContractType")
    
    working_day_type: Mapped[Optional["WorkingDayType"]] = relationship("app.modules.organization.models.WorkingDayType")
    salary_type: Mapped[Optional["SalaryType"]] = relationship("app.modules.organization.models.SalaryType")
    currency: Mapped[Optional["Currency"]] = relationship("app.modules.organization.models.Currency")
    payment_method: Mapped[Optional["PaymentMethod"]] = relationship("app.modules.organization.models.PaymentMethod")
    bank: Mapped[Optional["Bank"]] = relationship("app.modules.organization.models.Bank")
    cost_center: Mapped[Optional["CostCenter"]] = relationship("app.modules.organization.models.CostCenter")
    probation_duration: Mapped[Optional["ProbationDuration"]] = relationship("app.modules.organization.models.ProbationDuration")


class EmployeeHistory(Base):
    __tablename__ = "employee_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    movement_type: Mapped[MovementType] = mapped_column(SQLEnum(MovementType, native_enum=True))
    date: Mapped[date] = mapped_column(Date, default=func.current_date())
    previous_position_name: Mapped[Optional[str]] = mapped_column(String)
    previous_area_name: Mapped[Optional[str]] = mapped_column(String)
    new_position_id: Mapped[Optional[int]] = mapped_column(ForeignKey("positions.id"))
    company_id: Mapped[Optional[int]] = mapped_column(ForeignKey("companies.id"), nullable=True)

    # NUEVO: Registro del tipo de contrato en el momento del movimiento
    contract_type_id: Mapped[Optional[int]] = mapped_column(ForeignKey("contract_types.id"), nullable=True)

    # NUEVO: Registro de salario en el momento del movimiento
    base_salary: Mapped[Optional[float]] = mapped_column(Numeric(15, 2))
    currency_id: Mapped[Optional[int]] = mapped_column(ForeignKey("currencies.id"), nullable=True)

    notes: Mapped[Optional[str]] = mapped_column(Text)

    employee: Mapped["Employee"] = relationship("Employee", back_populates="history")
    new_position: Mapped["Position"] = relationship("Position")
    company: Mapped[Optional["Company"]] = relationship("app.modules.organization.models.Company")
    contract_type: Mapped[Optional["ContractType"]] = relationship("app.modules.organization.models.ContractType")
    currency: Mapped[Optional["Currency"]] = relationship("app.modules.organization.models.Currency")