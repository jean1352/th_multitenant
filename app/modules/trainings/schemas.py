"""
Esquemas Pydantic para el módulo de Capacitaciones.
"""

from datetime import date, time
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_validator, EmailStr

from .models import EnrollmentStatus, SessionStatus, TrainingStatus, TrainingType
from app.modules.employees.schemas import EmployeeList


# --- PROVIDER SCHEMAS ---

class ProviderBase(BaseModel):
    business_name: str
    ruc: str
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    contact_person: Optional[str] = None
    address: Optional[str] = None
    is_active: bool = True

class ProviderCreate(ProviderBase):
    pass

class ProviderUpdate(BaseModel):
    business_name: Optional[str] = None
    ruc: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    contact_person: Optional[str] = None
    address: Optional[str] = None
    is_active: Optional[bool] = None

class ProviderRead(ProviderBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


# --- TRAINING SCHEMAS ---

class TrainingBase(BaseModel):
    """Datos base para una capacitación."""
    name: str
    description: Optional[str] = None
    start_date: date
    end_date: date
    
    type: TrainingType = TrainingType.EXTERNAL
    
    # Campos condicionales
    provider_id: Optional[int] = None
    cost_per_person: Optional[float] = 0.0
    company_cost: Optional[float] = 0.0
    internal_instructor_id: Optional[int] = None

    @field_validator('internal_instructor_id', 'provider_id', mode='before')
    @classmethod
    def empty_to_none(cls, v):
        if v == "": return None
        return v


class TrainingCreate(TrainingBase):
    """Esquema para crear una capacitación."""
    pass


class TrainingUpdate(BaseModel):
    """Esquema para actualizar una capacitación."""
    name: Optional[str] = None
    description: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: Optional[TrainingStatus] = None
    
    type: Optional[TrainingType] = None
    provider_id: Optional[int] = None
    cost_per_person: Optional[float] = None
    company_cost: Optional[float] = None
    internal_instructor_id: Optional[int] = None

    @field_validator('internal_instructor_id', 'provider_id', mode='before')
    @classmethod
    def empty_to_none(cls, v):
        if v == "": return None
        return v


class TrainingRead(TrainingBase):
    """Esquema de lectura para una capacitación."""
    id: int
    status: TrainingStatus
    internal_instructor: Optional[EmployeeList] = None
    provider_obj: Optional[ProviderRead] = None
    model_config = ConfigDict(from_attributes=True)


# --- ENROLLMENT SCHEMAS ---

class EnrollmentCreate(BaseModel):
    employee_id: int

class EnrollmentRead(BaseModel):
    id: int
    employee_name: str
    status: EnrollmentStatus
    knowledge_score: Optional[float]
    model_config = ConfigDict(from_attributes=True)


# --- SESSION SCHEMAS ---

class SessionGenerator(BaseModel):
    topic: str
    description: Optional[str] = None
    instructor: Optional[str] = None
    start_date: date
    end_date: date
    start_time: time
    end_time: time
    days_of_week: List[int]

class SessionUpdate(BaseModel):
    topic: Optional[str] = None
    description: Optional[str] = None
    instructor: Optional[str] = None
    date: Optional[date] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None

class SessionRead(BaseModel):
    id: int
    topic: str
    description: Optional[str] = None
    instructor: Optional[str] = None
    date: date
    start_time: time
    end_time: time
    status: SessionStatus
    model_config = ConfigDict(from_attributes=True)


# --- ATTENDANCE SCHEMAS ---

class AttendanceUpdate(BaseModel):
    enrollment_id: int
    is_present: bool
    notes: Optional[str] = None

class AttendanceList(BaseModel):
    attendances: List[AttendanceUpdate]

# --- INVITATION & RESPONSE ---

class InvitationPayload(BaseModel):
    sede_ids: List[int] = []
    area_ids: List[int] = []
    subject: str
    html_body: str 

class PublicResponse(BaseModel):
    action: str