"""
Esquemas Pydantic para el módulo de Capacitaciones.
"""

from datetime import date, datetime, time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.modules.employees.schemas import EmployeeList
from .models import (
    AttendanceMethod,
    AttendanceStatus,
    EnrollmentStatus,
    ReplicaStatus,
    SessionStatus,
    TrainingModality,
    TrainingStatus,
    TrainingType,
)


# --- PROVIDER SCHEMAS ---

class ProviderBase(BaseModel):
    business_name: str
    ruc: str
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    contact_person: Optional[str] = None
    address: Optional[str] = None
    is_active: bool = True

    @field_validator("email", mode="before")
    @classmethod
    def empty_email_to_none(cls, v):
        if v == "":
            return None
        return v


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

    @field_validator("email", mode="before")
    @classmethod
    def empty_email_to_none(cls, v):
        if v == "":
            return None
        return v


class ProviderRead(ProviderBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


# --- TOPIC SCHEMAS (RF-32) ---

class TopicBase(BaseModel):
    name: str
    description: Optional[str] = None
    is_active: bool = True


class TopicCreate(TopicBase):
    pass


class TopicUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class TopicRead(TopicBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


# --- TRAINING SCHEMAS ---

class TrainingBase(BaseModel):
    """Datos base para una capacitación."""
    name: str
    description: Optional[str] = None
    objective: Optional[str] = None
    start_date: date
    end_date: date

    type: TrainingType = TrainingType.EXTERNAL
    modality: str = TrainingModality.PRESENTIAL.value
    topic_id: Optional[int] = None
    topic: Optional[str] = None
    hours: Optional[float] = 0.0
    capacity: Optional[int] = None
    sede_id: Optional[int] = None
    location: Optional[str] = None
    meeting_url: Optional[str] = None

    # Campos condicionales externas
    provider_id: Optional[int] = None
    cost_per_person: Optional[float] = 0.0
    company_cost: Optional[float] = 0.0
    cost: Optional[float] = 0.0
    currency_id: Optional[int] = None
    currency: Optional[str] = None
    cost_center_id: Optional[int] = None

    # Campos internas / réplica
    internal_instructor_id: Optional[int] = None
    source_training_id: Optional[int] = None
    target_area_id: Optional[int] = None

    requires_manager_approval: bool = False
    min_passing_score: Optional[float] = None
    min_attendance_pct: Optional[float] = None

    @field_validator(
        "internal_instructor_id",
        "provider_id",
        "topic_id",
        "currency_id",
        "cost_center_id",
        "sede_id",
        "capacity",
        "source_training_id",
        "target_area_id",
        "min_passing_score",
        "min_attendance_pct",
        "hours",
        "cost",
        "cost_per_person",
        "company_cost",
        mode="before",
    )
    @classmethod
    def empty_to_none(cls, v):
        if v == "":
            return None
        return v


class TrainingCreate(TrainingBase):
    """Esquema para crear una capacitación."""
    status: TrainingStatus = TrainingStatus.DRAFT


class TrainingUpdate(BaseModel):
    """Esquema para actualizar una capacitación."""
    name: Optional[str] = None
    description: Optional[str] = None
    objective: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: Optional[TrainingStatus] = None

    type: Optional[TrainingType] = None
    modality: Optional[str] = None
    topic_id: Optional[int] = None
    topic: Optional[str] = None
    hours: Optional[float] = None
    capacity: Optional[int] = None
    sede_id: Optional[int] = None
    location: Optional[str] = None
    meeting_url: Optional[str] = None

    provider_id: Optional[int] = None
    cost_per_person: Optional[float] = None
    company_cost: Optional[float] = None
    cost: Optional[float] = None
    currency_id: Optional[int] = None
    currency: Optional[str] = None
    cost_center_id: Optional[int] = None
    internal_instructor_id: Optional[int] = None
    target_area_id: Optional[int] = None

    requires_manager_approval: Optional[bool] = None
    min_passing_score: Optional[float] = None
    min_attendance_pct: Optional[float] = None
    correction_reason: Optional[str] = None

    @field_validator(
        "internal_instructor_id",
        "provider_id",
        "topic_id",
        "currency_id",
        "cost_center_id",
        "sede_id",
        "capacity",
        "target_area_id",
        "min_passing_score",
        "min_attendance_pct",
        "hours",
        "cost",
        "cost_per_person",
        "company_cost",
        mode="before",
    )
    @classmethod
    def empty_to_none(cls, v):
        if v == "":
            return None
        return v


class TrainingRead(TrainingBase):
    """Esquema de lectura para una capacitación."""
    id: int
    code: Optional[str] = None
    status: TrainingStatus
    published_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    internal_instructor: Optional[EmployeeList] = None
    provider_obj: Optional[ProviderRead] = None
    model_config = ConfigDict(from_attributes=True)


# --- ENROLLMENT SCHEMAS ---

class EnrollmentCreate(BaseModel):
    employee_id: int


class BulkEnrollPayload(BaseModel):
    employee_ids: List[int] = []
    area_ids: List[int] = []
    position_ids: List[int] = []


class EnrollmentScoreUpdate(BaseModel):
    knowledge_score: Optional[float] = None
    feedback: Optional[str] = None


class EnrollmentRead(BaseModel):
    id: int
    training_id: Optional[int] = None
    employee_id: Optional[int] = None
    employee_name: str
    status: EnrollmentStatus
    waitlist_position: Optional[int] = None
    attendance_pct: Optional[float] = None
    knowledge_score: Optional[float] = None
    result: Optional[str] = None
    certificate_file: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


# --- SESSION SCHEMAS ---

class SessionCreate(BaseModel):
    topic: str
    description: Optional[str] = None
    instructor: Optional[str] = None
    date: date
    start_time: time
    end_time: time
    location_or_link: Optional[str] = None
    meeting_platform: Optional[str] = None


class SessionGenerator(BaseModel):
    topic: str
    description: Optional[str] = None
    instructor: Optional[str] = None
    start_date: date
    end_date: date
    start_time: time
    end_time: time
    days_of_week: List[int]
    location_or_link: Optional[str] = None


class SessionUpdate(BaseModel):
    topic: Optional[str] = None
    description: Optional[str] = None
    instructor: Optional[str] = None
    date: Optional[date] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    location_or_link: Optional[str] = None
    meeting_platform: Optional[str] = None


class SessionRead(BaseModel):
    id: int
    training_id: int
    topic: str
    description: Optional[str] = None
    instructor: Optional[str] = None
    date: date
    start_time: time
    end_time: time
    status: SessionStatus
    qr_code_token: Optional[str] = None
    location_or_link: Optional[str] = None
    meeting_platform: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


# --- ATTENDANCE SCHEMAS ---

class AttendanceUpdate(BaseModel):
    enrollment_id: int
    is_present: bool = False
    attendance_status: Optional[str] = None  # present, late, absent, justified
    notes: Optional[str] = None


class AttendanceList(BaseModel):
    attendances: List[AttendanceUpdate]
    method: str = AttendanceMethod.MANUAL.value


class QRCheckinPayload(BaseModel):
    token: str


# --- INVITATION & RESPONSE ---

class InvitationPayload(BaseModel):
    sede_ids: List[int] = []
    area_ids: List[int] = []
    subject: str
    html_body: str


class PublicResponse(BaseModel):
    action: str


# --- REPLICA COMMITMENT SCHEMAS (RF-23..RF-29) ---

class ReplicaProposalCreate(BaseModel):
    topic: str
    proposed_date: date
    start_time: time = time(9, 0)
    end_time: time = time(10, 0)
    duration_hours: float = 1.0
    audience: Optional[str] = None
    target_area_id: Optional[int] = None
    modality: str = TrainingModality.PRESENTIAL.value
    location: Optional[str] = None
    joint_commitment_ids: List[int] = []  # RN-10 réplica conjunta


class ReplicaApprovalPayload(BaseModel):
    approved: bool
    rejection_reason: Optional[str] = None


class ReplicaExtensionPayload(BaseModel):
    extended_due_date: date
    justification: str


class ReplicaCommitmentRead(BaseModel):
    id: int
    source_enrollment_id: int
    source_training_id: int
    employee_id: int
    due_date: date
    extended_due_date: Optional[date] = None
    extension_justification: Optional[str] = None
    replica_training_id: Optional[int] = None
    status: str
    proposed_topic: Optional[str] = None
    proposed_date: Optional[date] = None
    proposed_start_time: Optional[time] = None
    proposed_end_time: Optional[time] = None
    proposed_duration_hours: Optional[float] = None
    proposed_audience: Optional[str] = None
    proposed_target_area_id: Optional[int] = None
    proposed_modality: Optional[str] = None
    proposed_location: Optional[str] = None
    completed_at: Optional[date] = None
    model_config = ConfigDict(from_attributes=True)


# --- EVIDENCE, SURVEY, PARAMETER, TEMPLATE, AUDIT SCHEMAS ---

class EvidenceLinkCreate(BaseModel):
    file_name: str
    file_url: str
    evidence_type: str = "material"


class EvidenceRead(BaseModel):
    id: int
    entity_type: str
    entity_id: int
    file_name: str
    file_url: str
    evidence_type: str
    uploaded_at: datetime
    model_config = ConfigDict(from_attributes=True)


class SurveyCreate(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    content_rating: Optional[int] = Field(None, ge=1, le=5)
    instructor_rating: Optional[int] = Field(None, ge=1, le=5)
    comments: Optional[str] = None


class SurveyRead(SurveyCreate):
    id: int
    enrollment_id: int
    submitted_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ParameterUpdate(BaseModel):
    value: str


class ParameterRead(BaseModel):
    key: str
    value: str
    description: str
    value_type: str
    model_config = ConfigDict(from_attributes=True)


class EmailTemplateUpdate(BaseModel):
    subject_template: str
    body_template: str
    is_active: bool = True


class EmailTemplateRead(BaseModel):
    id: int
    event_code: str
    name: str
    subject_template: str
    body_template: str
    is_active: bool
    model_config = ConfigDict(from_attributes=True)


class TrainingClosePayload(BaseModel):
    force: bool = False


class StatusTransitionPayload(BaseModel):
    status: TrainingStatus
    reason: Optional[str] = None
