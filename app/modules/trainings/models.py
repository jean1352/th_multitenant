"""
Modelos ORM para el módulo de Capacitaciones.
Define las tablas para cursos, inscripciones, sesiones, asistencia, proveedores,
compromisos de réplica, evidencias, notificaciones, parámetros, auditoría,
temas, plantillas de correo y encuestas de satisfacción.
"""

from __future__ import annotations

import enum
from datetime import date, datetime, time
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base

if TYPE_CHECKING:
    from app.modules.auth.models import User
    from app.modules.employees.models import Employee
    from app.modules.organization.models import Area, CostCenter, Currency, Sede


class TrainingStatus(str, enum.Enum):
    """Estados posibles de una capacitación (Sección 4)."""
    DRAFT = "draft"              # Borrador
    PLANNED = "planned"          # Programada (publicada)
    IN_PROGRESS = "in_progress"  # En curso
    COMPLETED = "completed"      # Finalizada
    CLOSED = "closed"            # Cerrada
    CANCELLED = "cancelled"      # Cancelada


class TrainingType(str, enum.Enum):
    """Tipo de capacitación."""
    INTERNAL = "internal"
    EXTERNAL = "external"
    REPLICA = "replica"


class TrainingModality(str, enum.Enum):
    """Modalidad de ejecución."""
    PRESENTIAL = "presencial"
    VIRTUAL = "virtual"
    HYBRID = "hibrida"


class EnrollmentStatus(str, enum.Enum):
    """Estados de la inscripción de un empleado."""
    PENDING_APPROVAL = "pending_approval"
    INVITED = "invited"
    ENROLLED = "enrolled"
    WAITLIST = "waitlist"
    ATTENDED = "attended"
    FAILED = "failed"
    NO_SHOW = "no_show"
    DECLINED = "declined"
    WITHDRAWN = "withdrawn"


class SessionStatus(str, enum.Enum):
    """Estados de una sesión específica."""
    PENDING = "pending"
    OPEN = "open"
    CLOSED = "closed"


class AttendanceStatus(str, enum.Enum):
    """Estados de asistencia por sesión (RF-14)."""
    PRESENT = "present"
    LATE = "late"
    ABSENT = "absent"
    JUSTIFIED = "justified"


class AttendanceMethod(str, enum.Enum):
    """Método de registro de asistencia."""
    MANUAL = "manual"
    EXCEL = "excel"
    QR = "qr"
    IMPORT = "import"


class ReplicaStatus(str, enum.Enum):
    """Estados del compromiso de réplica."""
    PENDING = "pendiente"
    PROPOSED = "propuesta"
    SCHEDULED = "programada"
    COMPLETED = "cumplida"
    OVERDUE = "vencida"
    CANCELLED_EXIT = "anulada_cese"


class TrainingProvider(Base):
    """Catálogo de Proveedores de Capacitación."""
    __tablename__ = "training_providers"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_name: Mapped[str] = mapped_column(String) # Razón Social
    ruc: Mapped[str] = mapped_column(String, unique=True)
    
    phone: Mapped[Optional[str]] = mapped_column(String)
    email: Mapped[Optional[str]] = mapped_column(String)
    contact_person: Mapped[Optional[str]] = mapped_column(String)
    address: Mapped[Optional[str]] = mapped_column(String)
    
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    trainings: Mapped[List["Training"]] = relationship(back_populates="provider_obj")


class TrainingTopic(Base):
    """Catálogo de Temas de Capacitación (RF-32)."""
    __tablename__ = "training_topics"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Training(Base):
    """Modelo que representa una capacitación o curso."""
    __tablename__ = "trainings"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(Text)
    objective: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    type: Mapped[TrainingType] = mapped_column(
        SQLEnum(TrainingType), default=TrainingType.EXTERNAL
    )
    modality: Mapped[Optional[str]] = mapped_column(String, default=TrainingModality.PRESENTIAL.value)
    topic_id: Mapped[Optional[int]] = mapped_column(ForeignKey("training_topics.id"), nullable=True)
    topic: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Si es EXTERNA (Relación con Proveedor y datos financieros)
    provider_id: Mapped[Optional[int]] = mapped_column(ForeignKey("training_providers.id"), nullable=True)
    cost_per_person: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    company_cost: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    cost: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    currency_id: Mapped[Optional[int]] = mapped_column(ForeignKey("currencies.id"), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    cost_center_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cost_centers.id"), nullable=True)

    # Si es INTERNA o RÉPLICA
    internal_instructor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("employees.id"), nullable=True)

    # Fechas, horas, cupo y lugar
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    hours: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    capacity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sede_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sedes.id"), nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    meeting_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Reglas por capacitación
    requires_manager_approval: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    min_passing_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    min_attendance_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Vinculación de Réplica -> Externa de origen
    source_training_id: Mapped[Optional[int]] = mapped_column(ForeignKey("trainings.id"), nullable=True)
    target_area_id: Mapped[Optional[int]] = mapped_column(ForeignKey("areas.id"), nullable=True)

    status: Mapped[TrainingStatus] = mapped_column(
        SQLEnum(TrainingStatus), default=TrainingStatus.PLANNED
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relaciones
    provider_obj: Mapped[Optional[TrainingProvider]] = relationship(back_populates="trainings")
    topic_obj: Mapped[Optional[TrainingTopic]] = relationship()
    currency_obj: Mapped[Optional["Currency"]] = relationship("app.modules.organization.models.Currency")
    cost_center_obj: Mapped[Optional["CostCenter"]] = relationship("app.modules.organization.models.CostCenter")
    sede_obj: Mapped[Optional["Sede"]] = relationship("app.modules.organization.models.Sede")
    target_area_obj: Mapped[Optional["Area"]] = relationship("app.modules.organization.models.Area")

    internal_instructor: Mapped[Optional["Employee"]] = relationship(
        "app.modules.employees.models.Employee",
        foreign_keys=[internal_instructor_id],
    )
    source_training: Mapped[Optional["Training"]] = relationship(
        "Training",
        remote_side=[id],
        foreign_keys=[source_training_id],
    )

    enrollments: Mapped[List["TrainingEnrollment"]] = relationship(
        back_populates="training", cascade="all, delete-orphan"
    )
    sessions: Mapped[List["TrainingSession"]] = relationship(
        back_populates="training",
        cascade="all, delete-orphan",
        order_by="TrainingSession.date, TrainingSession.start_time",
    )


class TrainingEnrollment(Base):
    """Modelo que vincula a un empleado con una capacitación."""
    __tablename__ = "training_enrollments"

    id: Mapped[int] = mapped_column(primary_key=True)
    training_id: Mapped[int] = mapped_column(ForeignKey("trainings.id"))
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))

    status: Mapped[EnrollmentStatus] = mapped_column(
        SQLEnum(EnrollmentStatus), default=EnrollmentStatus.ENROLLED
    )

    invitation_token: Mapped[Optional[str]] = mapped_column(String, unique=True, index=True)
    invitation_sent_at: Mapped[Optional[date]] = mapped_column(Date)

    enrolled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now())
    waitlist_position: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    attendance_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    knowledge_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    result: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    certificate_file: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    feedback: Mapped[Optional[str]] = mapped_column(Text)

    approved_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    training: Mapped[Training] = relationship(back_populates="enrollments")
    employee: Mapped["Employee"] = relationship(back_populates="trainings")
    attendances: Mapped[List["TrainingAttendance"]] = relationship(
        back_populates="enrollment", cascade="all, delete-orphan"
    )
    survey: Mapped[Optional["TrainingSurvey"]] = relationship(
        back_populates="enrollment", uselist=False, cascade="all, delete-orphan"
    )


class TrainingSession(Base):
    """Modelo para una sesión individual dentro de una capacitación."""
    __tablename__ = "training_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    training_id: Mapped[int] = mapped_column(ForeignKey("trainings.id"))

    topic: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(Text)
    instructor: Mapped[Optional[str]] = mapped_column(String)

    date: Mapped[date] = mapped_column(Date)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    status: Mapped[SessionStatus] = mapped_column(
        SQLEnum(SessionStatus), default=SessionStatus.PENDING
    )

    qr_code_token: Mapped[Optional[str]] = mapped_column(String, unique=True, index=True, nullable=True)
    location_or_link: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    meeting_platform: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    training: Mapped[Training] = relationship(back_populates="sessions")
    attendances: Mapped[List["TrainingAttendance"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class TrainingAttendance(Base):
    """Registro de asistencia por sesión y participante."""
    __tablename__ = "training_attendances"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("training_sessions.id"))
    enrollment_id: Mapped[int] = mapped_column(ForeignKey("training_enrollments.id"))

    is_present: Mapped[bool] = mapped_column(Boolean, default=False)
    attendance_status: Mapped[Optional[str]] = mapped_column(String, default=AttendanceStatus.ABSENT.value)
    notes: Mapped[Optional[str]] = mapped_column(String)
    recorded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    method: Mapped[Optional[str]] = mapped_column(String, default=AttendanceMethod.MANUAL.value)
    recorded_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)

    session: Mapped[TrainingSession] = relationship(back_populates="attendances")
    enrollment: Mapped[TrainingEnrollment] = relationship(back_populates="attendances")



class ReplicaCommitment(Base):
    """Compromiso de réplica obligatoria nacido de una capacitación externa aprobada."""
    __tablename__ = "training_replica_commitments"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_enrollment_id: Mapped[int] = mapped_column(ForeignKey("training_enrollments.id"), index=True)
    source_training_id: Mapped[int] = mapped_column(ForeignKey("trainings.id"), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)

    due_date: Mapped[date] = mapped_column(Date)
    extended_due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    extension_justification: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extension_approved_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    extension_approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    replica_training_id: Mapped[Optional[int]] = mapped_column(ForeignKey("trainings.id"), nullable=True)
    status: Mapped[str] = mapped_column(String, default=ReplicaStatus.PENDING.value, index=True)

    # Propuesta del colaborador (RF-25)
    proposed_topic: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    proposed_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    proposed_start_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    proposed_end_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    proposed_duration_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    proposed_audience: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    proposed_target_area_id: Mapped[Optional[int]] = mapped_column(ForeignKey("areas.id"), nullable=True)
    proposed_modality: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    proposed_location: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    proposed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    approved_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    completed_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    source_enrollment: Mapped[TrainingEnrollment] = relationship(foreign_keys=[source_enrollment_id])
    source_training: Mapped[Training] = relationship(foreign_keys=[source_training_id])
    replica_training: Mapped[Optional[Training]] = relationship(foreign_keys=[replica_training_id])
    employee: Mapped["Employee"] = relationship(foreign_keys=[employee_id])
    target_area: Mapped[Optional["Area"]] = relationship("app.modules.organization.models.Area", foreign_keys=[proposed_target_area_id])


class TrainingEvidence(Base):
    """Evidencias y materiales adjuntos (facturas, cotizaciones, certificados, materiales, listas)."""
    __tablename__ = "training_evidences"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String, index=True)  # training, enrollment, commitment
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    file_name: Mapped[str] = mapped_column(String)
    file_url: Mapped[str] = mapped_column(String)  # URL local o enlace externo (RF-06)
    evidence_type: Mapped[str] = mapped_column(String)  # factura, cotizacion, certificado, material, lista, evidencia_replica
    uploaded_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    uploaded_by: Mapped[Optional["User"]] = relationship("app.modules.auth.models.User", foreign_keys=[uploaded_by_user_id])


class TrainingNotification(Base):
    """Registro de alertas N-01..N-11 enviadas/programadas para trazabilidad, reintentos e idempotencia."""
    __tablename__ = "training_notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_code: Mapped[str] = mapped_column(String, index=True)  # N-01 .. N-11
    recipient_id: Mapped[Optional[int]] = mapped_column(ForeignKey("employees.id"), nullable=True)
    recipient_email: Mapped[str] = mapped_column(String)
    entity_type: Mapped[str] = mapped_column(String)  # training, enrollment, commitment, system
    entity_id: Mapped[int] = mapped_column(Integer)
    dedup_key: Mapped[str] = mapped_column(String, index=True)
    scheduled_date: Mapped[date] = mapped_column(Date)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    channel: Mapped[str] = mapped_column(String, default="email")
    status: Mapped[str] = mapped_column(String, default="pending")  # pending, sent, failed, cancelled
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    subject: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    recipient: Mapped[Optional["Employee"]] = relationship(foreign_keys=[recipient_id])



class TrainingParameter(Base):
    """Parámetros configurables del módulo de Capacitaciones (RF-30)."""
    __tablename__ = "training_parameters"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text)
    value_type: Mapped[str] = mapped_column(String, default="str")  # int, float, bool, str
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TrainingEmailTemplate(Base):
    """Plantillas editables de correo para alertas N-01..N-11 (RF-31)."""
    __tablename__ = "training_email_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_code: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String)
    subject_template: Mapped[str] = mapped_column(String)
    body_template: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TrainingAudit(Base):
    """Bitácora de auditoría del módulo de Capacitaciones (RF-33, RN-09, RN-13)."""
    __tablename__ = "training_audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String, index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String)
    field: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    old_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[Optional["User"]] = relationship("app.modules.auth.models.User", foreign_keys=[user_id])


class TrainingSurvey(Base):
    """Encuesta de satisfacción al cierre de la capacitación (RF-21)."""
    __tablename__ = "training_surveys"

    id: Mapped[int] = mapped_column(primary_key=True)
    enrollment_id: Mapped[int] = mapped_column(ForeignKey("training_enrollments.id"), unique=True)
    rating: Mapped[int] = mapped_column(Integer)  # 1..5
    content_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    instructor_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    comments: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    enrollment: Mapped[TrainingEnrollment] = relationship(back_populates="survey")

