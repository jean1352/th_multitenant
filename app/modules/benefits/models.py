from typing import List, Optional
from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text, JSON, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.core.database import Base

# --- CATÁLOGOS DE SOLICITUDES ---
class BenefitRequestType(Base):
    __tablename__ = "benefit_request_types"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True) # Alta, Baja, Modificación...
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class BenefitSubtype(Base):
    __tablename__ = "benefit_subtypes"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class BenefitGrantReason(Base):
    __tablename__ = "benefit_grant_reasons"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True) # Por política, cargo...
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class AuthorizationLevel(Base):
    __tablename__ = "authorization_levels"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True) # Rectorado, Gerencia...
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class BenefitModality(Base):
    __tablename__ = "benefit_modalities"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True) # Fijo, Variable...
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class BenefitFrequency(Base):
    __tablename__ = "benefit_frequencies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True) # Mensual, Único...
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

# --- MODELOS PRINCIPALES ---
class BenefitType(Base):
    """Catálogo de beneficios disponibles."""
    __tablename__ = "benefit_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    fields_schema: Mapped[Optional[dict]] = mapped_column(JSON) # Configuración de campos dinámicos
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class EmployeeBenefit(Base):
    """Asignación de un beneficio a un empleado."""
    __tablename__ = "employee_benefits"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    benefit_type_id: Mapped[int] = mapped_column(ForeignKey("benefit_types.id"))

    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[Optional[date]] = mapped_column(Date)
    details: Mapped[Optional[str]] = mapped_column(String)
    custom_data: Mapped[Optional[dict]] = mapped_column(JSON) # Valores cargados dinámicamente
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    benefit_type: Mapped["BenefitType"] = relationship("BenefitType")
    employee: Mapped["Employee"] = relationship("Employee", back_populates="benefits")

class BenefitRequest(Base):
    """Registro de Solicitudes de Beneficios."""
    __tablename__ = "benefit_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_code: Mapped[str] = mapped_column(String, unique=True, index=True) # ej: BE001

    # 1. Beneficiario
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    employee_position_id: Mapped[Optional[int]] = mapped_column(ForeignKey("employee_positions.id"), nullable=True)

    # 2. Solicitud y Clasificación
    request_type_id: Mapped[int] = mapped_column(ForeignKey("benefit_request_types.id"))
    request_date: Mapped[date] = mapped_column(Date, default=func.current_date())

    grant_reason_id: Mapped[int] = mapped_column(ForeignKey("benefit_grant_reasons.id"))
    justification: Mapped[str] = mapped_column(Text)

    # 4. Solicitante
    requester_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    requester_position_id: Mapped[Optional[int]] = mapped_column(ForeignKey("employee_positions.id"), nullable=True)

    # 5. Aprobación y Otorgamiento
    authorization_level_id: Mapped[Optional[int]] = mapped_column(ForeignKey("authorization_levels.id"), nullable=True)
    authorizer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("employees.id"), nullable=True)
    authorizer_position_id: Mapped[Optional[int]] = mapped_column(ForeignKey("employee_positions.id"), nullable=True)
    grant_date: Mapped[Optional[date]] = mapped_column(Date)
    resolution_number: Mapped[Optional[str]] = mapped_column(String)
    approval_comments: Mapped[Optional[str]] = mapped_column(Text)
    
    # 6. Estado y Control
    status: Mapped[str] = mapped_column(String, default="Pendiente") # Estado de Aprobación: Pendiente, Aprobada, Rechazada, Anulada
    benefit_status: Mapped[str] = mapped_column(String, default="Pendiente") # Activo, Suspendido, Finalizado, Pendiente, Rechazado
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relaciones
    employee: Mapped["Employee"] = relationship("Employee", foreign_keys=[employee_id])
    employee_position: Mapped[Optional["EmployeePosition"]] = relationship("app.modules.employees.models.EmployeePosition", foreign_keys=[employee_position_id])

    requester: Mapped["Employee"] = relationship("Employee", foreign_keys=[requester_id])
    requester_position: Mapped[Optional["EmployeePosition"]] = relationship("app.modules.employees.models.EmployeePosition", foreign_keys=[requester_position_id])

    authorizer: Mapped[Optional["Employee"]] = relationship("Employee", foreign_keys=[authorizer_id])
    authorizer_position: Mapped[Optional["EmployeePosition"]] = relationship("app.modules.employees.models.EmployeePosition", foreign_keys=[authorizer_position_id])

    request_type: Mapped["BenefitRequestType"] = relationship("BenefitRequestType")
    grant_reason: Mapped["BenefitGrantReason"] = relationship("BenefitGrantReason")
    authorization_level: Mapped[Optional["AuthorizationLevel"]] = relationship("AuthorizationLevel")

    items: Mapped[List["BenefitRequestItem"]] = relationship("BenefitRequestItem", back_populates="benefit_request", cascade="all, delete-orphan")

class BenefitRequestItem(Base):
    """Items individuales de una solicitud de beneficios."""
    __tablename__ = "benefit_request_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    benefit_request_id: Mapped[int] = mapped_column(ForeignKey("benefit_requests.id", ondelete="CASCADE"))
    
    benefit_type_id: Mapped[int] = mapped_column(ForeignKey("benefit_types.id"))
    benefit_subtype_id: Mapped[Optional[int]] = mapped_column(ForeignKey("benefit_subtypes.id"), nullable=True)
    
    currency_id: Mapped[Optional[int]] = mapped_column(ForeignKey("currencies.id"), nullable=True)
    custom_data: Mapped[Optional[dict]] = mapped_column(JSON)
    description_notes: Mapped[Optional[str]] = mapped_column(Text)
    
    approved_amount: Mapped[Optional[float]] = mapped_column(Numeric(15, 2))
    validity_start_date: Mapped[Optional[date]] = mapped_column(Date)
    validity_end_date: Mapped[Optional[date]] = mapped_column(Date)
    
    benefit_modality_id: Mapped[Optional[int]] = mapped_column(ForeignKey("benefit_modalities.id"), nullable=True)
    benefit_frequency_id: Mapped[Optional[int]] = mapped_column(ForeignKey("benefit_frequencies.id"), nullable=True)

    # Relaciones
    benefit_request: Mapped["BenefitRequest"] = relationship("BenefitRequest", back_populates="items")
    benefit_type: Mapped["BenefitType"] = relationship("BenefitType")
    benefit_subtype: Mapped[Optional["BenefitSubtype"]] = relationship("BenefitSubtype")
    currency: Mapped[Optional["Currency"]] = relationship("app.modules.organization.models.Currency")
    benefit_modality: Mapped[Optional["BenefitModality"]] = relationship("BenefitModality")
    benefit_frequency: Mapped[Optional["BenefitFrequency"]] = relationship("BenefitFrequency")
