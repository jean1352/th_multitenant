"""
Esquemas Pydantic para el Portal del Colaborador y Solicitudes de Vacaciones.
"""

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class VacationRequestCreate(BaseModel):
    start_date: date
    end_date: date
    reason: Optional[str] = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("La fecha de fin no puede ser anterior a la fecha de inicio.")
        return self


class VacationRequestDecision(BaseModel):
    status: Literal["Aprobada", "Rechazada"]
    decision_reason: Optional[str] = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_rejection_reason(self):
        cleaned = (self.decision_reason or "").strip()
        if self.status == "Rechazada" and not cleaned:
            raise ValueError("Debe ingresar un motivo para rechazar la solicitud de vacaciones.")
        self.decision_reason = cleaned or None
        return self


class EmployeeMini(BaseModel):
    id: int
    full_name: str
    document_id: str
    institutional_email: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class VacationRequestRead(BaseModel):
    id: int
    request_code: str
    employee_id: int
    start_date: date
    end_date: date
    days_requested: int
    business_days: Optional[int] = None
    reason: Optional[str] = None
    status: str
    assigned_approver_id: Optional[int] = None
    approver_id: Optional[int] = None
    decision_reason: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    created_at: datetime
    employee: Optional[EmployeeMini] = None
    approver: Optional[EmployeeMini] = None
    assigned_approver: Optional[EmployeeMini] = None

    model_config = ConfigDict(from_attributes=True)
