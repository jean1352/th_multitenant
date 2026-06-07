from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, field_validator
from .models import FrequencyType, AutomationRuleType

class RuleUpdate(BaseModel):
    frequency: FrequencyType
    execution_time: str
    day_of_week: Optional[int] = None
    day_of_month: Optional[int] = None
    param_value: Optional[int] = None

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
    rule_type: AutomationRuleType
    name: str
    description: str
    frequency: FrequencyType
    execution_time: str
    day_of_week: Optional[int] = None
    day_of_month: Optional[int] = None
    param_value: Optional[int] = None
    is_active: bool
    last_run: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)