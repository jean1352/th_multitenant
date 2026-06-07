from typing import Optional
from pydantic import BaseModel, ConfigDict

class DietaryRestrictionBase(BaseModel):
    name: str
    description: Optional[str] = None

class DietaryRestrictionCreate(DietaryRestrictionBase):
    pass

class DietaryRestrictionRead(DietaryRestrictionBase):
    id: int
    employee_count: Optional[int] = 0
    model_config = ConfigDict(from_attributes=True)