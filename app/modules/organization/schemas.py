"""
Esquemas Pydantic para el módulo de Organización.
Define la estructura de datos para Sedes, Áreas, Cargos y Tipos de Contrato.
"""

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# --- CONTRACT TYPES ---

class ContractTypeBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = None
    is_active: bool = True

class ContractTypeCreate(ContractTypeBase):
    pass

class ContractTypeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None

# WORKING DAY TYPE
class WorkingDayTypeBase(BaseModel):
    name: str
    description: Optional[str] = None
    is_active: bool = True

class WorkingDayTypeCreate(WorkingDayTypeBase):
    pass

class WorkingDayTypeRead(WorkingDayTypeBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

class WorkingDayTypeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None

# SALARY TYPE
class SalaryTypeBase(BaseModel):
    name: str
    description: Optional[str] = None
    is_active: bool = True

class SalaryTypeCreate(SalaryTypeBase):
    pass

class SalaryTypeRead(SalaryTypeBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

class SalaryTypeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None

# CURRENCY
class CurrencyBase(BaseModel):
    name: str
    symbol: Optional[str] = None
    description: Optional[str] = None
    is_active: bool = True

class CurrencyCreate(CurrencyBase):
    pass

class CurrencyRead(CurrencyBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

class CurrencyUpdate(BaseModel):
    name: Optional[str] = None
    symbol: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None

# PAYMENT METHOD
class PaymentMethodBase(BaseModel):
    name: str
    description: Optional[str] = None
    is_active: bool = True

class PaymentMethodCreate(PaymentMethodBase):
    pass

class PaymentMethodRead(PaymentMethodBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

class PaymentMethodUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None

# BANK
class BankBase(BaseModel):
    name: str
    code: Optional[str] = None
    description: Optional[str] = None
    is_active: bool = True

class BankCreate(BankBase):
    pass

class BankRead(BankBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

class BankUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None

# COST CENTER
class CostCenterBase(BaseModel):
    name: str
    code: Optional[str] = None
    description: Optional[str] = None
    is_active: bool = True

class CostCenterCreate(CostCenterBase):
    pass

class CostCenterRead(CostCenterBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

class CostCenterUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None

# PROBATION DURATION
class ProbationDurationBase(BaseModel):
    name: str
    days: int
    is_active: bool = True

class ProbationDurationCreate(ProbationDurationBase):
    pass

class ProbationDurationRead(ProbationDurationBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

class ProbationDurationUpdate(BaseModel):
    name: Optional[str] = None
    days: Optional[int] = None
    is_active: Optional[bool] = None

# RELATIONSHIP TYPE
class RelationshipTypeBase(BaseModel):
    name: str
    is_active: bool = True

class RelationshipTypeCreate(RelationshipTypeBase):
    pass

class RelationshipTypeRead(RelationshipTypeBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

class RelationshipTypeUpdate(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None

class ContractTypeRead(ContractTypeBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


# --- COMPANIES ---

class CompanyBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    tax_id: Optional[str] = None

class CompanyCreate(CompanyBase):
    pass

class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    tax_id: Optional[str] = None

class CompanyRead(CompanyBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


# --- SEDES ---

class SedeBase(BaseModel):
    """Datos base para una Sede."""
    name: str = Field(..., min_length=2, max_length=100)
    address: Optional[str] = None


class SedeCreate(SedeBase):
    """Esquema para crear una Sede."""
    pass


class SedeUpdate(SedeBase):
    """Esquema para actualizar una Sede."""
    pass


class SedeRead(SedeBase):
    """Esquema de lectura para una Sede."""
    id: int
    model_config = ConfigDict(from_attributes=True)


# --- AREAS SIMPLE (Para evitar ciclos) ---

class AreaSimple(BaseModel):
    """Esquema simplificado de Área para anidar en Cargo."""
    id: int
    name: str
    sede: Optional[SedeRead] = None
    model_config = ConfigDict(from_attributes=True)


# --- POSITIONS ---

class PositionBase(BaseModel):
    """Datos base para un Cargo."""
    name: str
    area_id: int
    parent_id: Optional[int] = None
    company_id: Optional[int] = None
    is_leader: bool = False


class PositionCreate(PositionBase):
    """Esquema para crear un Cargo."""
    pass


class PositionUpdate(BaseModel):
    """Esquema para actualizar un Cargo."""
    name: Optional[str] = None
    parent_id: Optional[int] = None
    company_id: Optional[int] = None
    is_leader: Optional[bool] = None


class PositionSimple(BaseModel):
    """Esquema simplificado para evitar recursión infinita en el padre."""
    id: int
    name: str
    model_config = ConfigDict(from_attributes=True)


class PositionRead(PositionBase):
    """Esquema de lectura para un Cargo."""
    id: int
    parent: Optional[PositionSimple] = None
    area: Optional[AreaSimple] = None
    company: Optional[CompanyRead] = None
    model_config = ConfigDict(from_attributes=True)


# --- AREAS ---

class AreaBase(BaseModel):
    """Datos base para un Área."""
    name: str
    sede_id: int
    responsible_email: EmailStr


class AreaCreate(AreaBase):
    """Esquema para crear un Área."""
    pass


class AreaUpdate(AreaBase):
    """Esquema para actualizar un Área."""
    pass


class AreaRead(AreaBase):
    """Esquema de lectura para un Área con sus relaciones."""
    id: int
    sede: Optional[SedeRead] = None
    positions: List[PositionRead] = []
    model_config = ConfigDict(from_attributes=True)