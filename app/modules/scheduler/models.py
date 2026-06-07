import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum as SQLEnum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
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

class AutomationRule(Base):
    __tablename__ = "automation_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    
    # Identificador único del tipo de lógica
    rule_type: Mapped[AutomationRuleType] = mapped_column(SQLEnum(AutomationRuleType), unique=True)
    
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text)
    
    frequency: Mapped[FrequencyType] = mapped_column(SQLEnum(FrequencyType), default=FrequencyType.WEEKLY)
    execution_time: Mapped[str] = mapped_column(String, default="08:00")
    day_of_week: Mapped[Optional[int]] = mapped_column(Integer)
    day_of_month: Mapped[Optional[int]] = mapped_column(Integer)
    
    param_value: Mapped[Optional[int]] = mapped_column(Integer) 

    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    
    last_run: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

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