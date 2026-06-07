"""
Esquemas Pydantic para el módulo de Autenticación.
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from .models import UserRole


class Token(BaseModel):
    """Esquema de respuesta para el Token JWT."""
    access_token: str
    token_type: str
    role: str
    is_superadmin: bool = False
    expires_in: Optional[int] = None


class UserLogin(BaseModel):
    """Esquema para las credenciales de inicio de sesión."""
    email: EmailStr
    password: str = Field(min_length=4)


class UserBase(BaseModel):
    """Datos base de un usuario."""
    email: EmailStr
    full_name: str
    role: UserRole = UserRole.EMPLOYEE
    is_active: bool = True
    sede_id: Optional[int] = None
    area_id: Optional[int] = None


class UserCreate(UserBase):
    """Esquema para crear un nuevo usuario (requiere password)."""
    password: str = Field(..., min_length=6)


class UserUpdate(BaseModel):
    """Esquema para actualizar un usuario existente."""
    full_name: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None
    sede_id: Optional[int] = None
    area_id: Optional[int] = None


class UserRead(UserBase):
    """Esquema de lectura de usuario (sin password)."""
    id: int
    model_config = ConfigDict(from_attributes=True)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=6)