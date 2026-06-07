from typing import List, Optional
from pydantic import BaseModel, EmailStr, field_validator

class TestEmailRequest(BaseModel):
    email_type: str
    recipients: str  # Recibimos string separado por comas

    @field_validator('recipients')
    @classmethod
    def validate_recipients(cls, v):
        if not v or not v.strip():
            raise ValueError("Debe ingresar al menos un destinatario")
        return v