from datetime import datetime
from typing import Optional, Any, Dict, List
from pydantic import BaseModel, ConfigDict, field_validator
from .models import FrequencyType, AutomationRuleType, TriggerType

class RuleUpdate(BaseModel):
    frequency: FrequencyType
    execution_time: str
    day_of_week: Optional[int] = None
    day_of_month: Optional[int] = None
    param_value: Optional[int] = None
    
    # NUEVOS CAMPOS AVANZADOS
    trigger_type: Optional[TriggerType] = None
    trigger_event: Optional[str] = None
    conditions: Optional[Dict[str, Any]] = None
    actions: Optional[List[Dict[str, Any]]] = None
    escalation_interval: Optional[str] = None

    # Validador para convertir strings vacíos del formulario a None
    @field_validator('day_of_week', 'day_of_month', 'param_value', mode='before')
    @classmethod
    def empty_str_to_none(cls, v):
        if v == "":
            return None
        return v

class RuleCreate(BaseModel):
    name: str
    description: str
    frequency: FrequencyType = FrequencyType.DAILY
    execution_time: str = "08:00"
    day_of_week: Optional[int] = None
    day_of_month: Optional[int] = None
    param_value: Optional[int] = None
    
    # NUEVOS CAMPOS AVANZADOS
    trigger_type: TriggerType = TriggerType.CRON_SCHEDULED
    trigger_event: Optional[str] = None
    conditions: Optional[Dict[str, Any]] = None
    actions: Optional[List[Dict[str, Any]]] = None
    escalation_interval: Optional[str] = None

    # Validador para convertir strings vacíos del formulario a None
    @field_validator('day_of_week', 'day_of_month', 'param_value', mode='before')
    @classmethod
    def empty_str_to_none(cls, v):
        if v == "":
            return None
        return v

class AutomationRuleRead(BaseModel):
    """Schema para serializar la regla y enviarla al frontend."""
    id: int
    rule_type: Optional[AutomationRuleType] = None
    name: str
    description: str
    frequency: FrequencyType
    execution_time: str
    day_of_week: Optional[int] = None
    day_of_month: Optional[int] = None
    param_value: Optional[int] = None
    is_active: bool
    last_run: Optional[datetime] = None
    
    # NUEVOS CAMPOS AVANZADOS
    trigger_type: TriggerType
    trigger_event: Optional[str] = None
    conditions: Optional[Dict[str, Any]] = None
    actions: Optional[List[Dict[str, Any]]] = None
    escalation_interval: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)
