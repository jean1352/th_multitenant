from datetime import date
from typing import Optional
from pydantic import BaseModel, ConfigDict
from .models import SanctionType, RecognitionType

# --- SANCTIONS ---
class SanctionBase(BaseModel):
    type: SanctionType
    date: date
    reason: str
    sent_to_ministry: bool = False
    notes: Optional[str] = None

class SanctionCreate(SanctionBase):
    employee_id: int

class SanctionRead(SanctionBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

# --- RECOGNITIONS ---
class RecognitionBase(BaseModel):
    type: RecognitionType
    date: date
    title: str
    description: Optional[str] = None

class RecognitionCreate(RecognitionBase):
    employee_id: int

class RecognitionRead(RecognitionBase):
    id: int
    model_config = ConfigDict(from_attributes=True)