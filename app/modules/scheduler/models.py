import enum
from datetime import datetime
from typing import Optional, Any, Dict, List

from sqlalchemy import Boolean, DateTime, Enum as SQLEnum, Integer, String, Text, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base

class AutomationRuleType(str, enum.Enum):
    # IMPORTANTE: Los valores (derecha) deben coincidir con lo que espera la DB
    VACANCY_WEEKLY_REPORT = "vacancy_weekly_report"
    VACANCY_STAGNATION = "vacancy_stagnation"
    EVENT_REMINDER = "event_reminder"
    SLA_DAILY_CHECK = "sla_daily_check"
    CONTRACT_EXPIRATION = "contract_expiration"
    PROBATION_END = "probation_end"

class FrequencyType(str, enum.Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CUSTOM = "custom"

class TriggerType(str, enum.Enum):
    EVENT_DRIVEN = "EVENT_DRIVEN"
    CRON_SCHEDULED = "CRON_SCHEDULED"

class EscalationStatus(str, enum.Enum):
    ACTIVE_ESCALATION = "ACTIVE_ESCALATION"
    RESOLVED = "RESOLVED"

class AutomationRule(Base):
    __tablename__ = "automation_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    
    # Identificador único del tipo de lógica (opcional para reglas personalizadas)
    rule_type: Mapped[Optional[AutomationRuleType]] = mapped_column(SQLEnum(AutomationRuleType), unique=True, nullable=True)
    
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text)
    
    frequency: Mapped[FrequencyType] = mapped_column(SQLEnum(FrequencyType), default=FrequencyType.WEEKLY)
    execution_time: Mapped[str] = mapped_column(String, default="08:00")
    day_of_week: Mapped[Optional[int]] = mapped_column(Integer)
    day_of_month: Mapped[Optional[int]] = mapped_column(Integer)
    
    param_value: Mapped[Optional[int]] = mapped_column(Integer) 

    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    
    last_run: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    # NUEVOS CAMPOS PARA EL MOTOR DE AUTOMATIZACIÓN AVANZADO
    trigger_type: Mapped[TriggerType] = mapped_column(SQLEnum(TriggerType), default=TriggerType.CRON_SCHEDULED)
    trigger_event: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    conditions: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    actions: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSON, nullable=True)
    escalation_interval: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

class AutomationState(Base):
    __tablename__ = "automation_states"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(Integer, ForeignKey("automation_rules.id", ondelete="CASCADE"))
    target_entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[EscalationStatus] = mapped_column(SQLEnum(EscalationStatus), default=EscalationStatus.ACTIVE_ESCALATION)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    rule = relationship("AutomationRule")

class TaskExecutionLog(Base):
    __tablename__ = "task_execution_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(Integer)
    task_name: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    message: Mapped[Optional[str]] = mapped_column(Text)
    items_processed: Mapped[int] = mapped_column(Integer, default=0)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )