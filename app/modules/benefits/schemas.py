from datetime import date
from typing import Optional, List
from pydantic import BaseModel, ConfigDict

from app.modules.organization.schemas import CurrencyRead

# --- CONFIGURACIÓN DE SOLICITUDES ---
class RequestTypeBase(BaseModel):
    name: str
    is_active: bool = True

class RequestTypeCreate(RequestTypeBase): pass
class RequestTypeUpdate(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None

class RequestTypeRead(RequestTypeBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class SubtypeBase(BaseModel):
    name: str
    is_active: bool = True

class SubtypeCreate(SubtypeBase): pass
class SubtypeUpdate(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None

class SubtypeRead(SubtypeBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class GrantReasonBase(BaseModel):
    name: str
    is_active: bool = True

class GrantReasonCreate(GrantReasonBase): pass
class GrantReasonUpdate(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None

class GrantReasonRead(GrantReasonBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

class AuthorizationLevelBase(BaseModel):
    name: str
    is_active: bool = True
class AuthorizationLevelCreate(AuthorizationLevelBase): pass
class AuthorizationLevelUpdate(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None
class AuthorizationLevelRead(AuthorizationLevelBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

class BenefitModalityBase(BaseModel):
    name: str
    is_active: bool = True
class BenefitModalityCreate(BenefitModalityBase): pass
class BenefitModalityUpdate(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None
class BenefitModalityRead(BenefitModalityBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

class BenefitFrequencyBase(BaseModel):
    name: str
    is_active: bool = True
class BenefitFrequencyCreate(BenefitFrequencyBase): pass
class BenefitFrequencyUpdate(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None
class BenefitFrequencyRead(BenefitFrequencyBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

# --- CONFIGURACIÓN DE BENEFICIOS ---
class BenefitTypeBase(BaseModel):
    name: str
    description: Optional[str] = None
    fields_schema: Optional[dict] = None 
    is_active: bool = True

class BenefitTypeCreate(BenefitTypeBase):
    pass

class BenefitTypeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    fields_schema: Optional[dict] = None 
    is_active: Optional[bool] = None

class BenefitTypeRead(BenefitTypeBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

# --- ITEMS DE SOLICITUD ---
class BenefitRequestItemBase(BaseModel):
    benefit_type_id: int
    benefit_subtype_id: Optional[int] = None
    currency_id: Optional[int] = None
    custom_data: Optional[dict] = None
    description_notes: Optional[str] = None
    approved_amount: Optional[float] = None
    validity_start_date: Optional[date] = None
    validity_end_date: Optional[date] = None
    benefit_modality_id: Optional[int] = None
    benefit_frequency_id: Optional[int] = None

class BenefitRequestItemCreate(BenefitRequestItemBase):
    pass

class BenefitRequestItemRead(BenefitRequestItemBase):
    id: int
    benefit_type: BenefitTypeRead
    benefit_subtype: Optional[SubtypeRead] = None
    currency: Optional[CurrencyRead] = None
    benefit_modality: Optional[BenefitModalityRead] = None
    benefit_frequency: Optional[BenefitFrequencyRead] = None
    model_config = ConfigDict(from_attributes=True)

# --- SOLICITUD DE BENEFICIOS ---
class BenefitRequestBase(BaseModel):
    employee_id: int
    employee_position_id: Optional[int] = None
    
    request_type_id: int
    request_date: date
    
    grant_reason_id: int
    justification: str
    
    requester_id: int
    requester_position_id: Optional[int] = None

    authorization_level_id: Optional[int] = None
    authorizer_id: Optional[int] = None
    authorizer_position_id: Optional[int] = None
    grant_date: Optional[date] = None
    resolution_number: Optional[str] = None
    approval_comments: Optional[str] = None
    benefit_status: Optional[str] = "Pendiente"

class BenefitRequestCreate(BenefitRequestBase):
    items: List[BenefitRequestItemCreate]

class BenefitRequestUpdateStatus(BaseModel):
    status: str

# Para no crear importaciones circulares enormes, usamos dicts para mostrar datos reducidos
class BasicEmployeeInfo(BaseModel):
    id: int
    full_name: str
    document_id: str
    model_config = ConfigDict(from_attributes=True)

class BenefitRequestRead(BenefitRequestBase):
    id: int
    request_code: str
    status: str
    
    request_type: RequestTypeRead
    grant_reason: GrantReasonRead
    
    employee: BasicEmployeeInfo
    requester: BasicEmployeeInfo
    
    authorizer: Optional[BasicEmployeeInfo] = None
    authorization_level: Optional[AuthorizationLevelRead] = None
    
    items: List[BenefitRequestItemRead]

    model_config = ConfigDict(from_attributes=True)

# --- ASIGNACIÓN ---
class EmployeeBenefitCreate(BaseModel):
    benefit_type_id: int
    start_date: date
    details: Optional[str] = None
    custom_data: Optional[dict] = None 

class EmployeeBenefitRead(BaseModel):
    id: int
    benefit_type: BenefitTypeRead
    start_date: date
    end_date: Optional[date] = None
    details: Optional[str] = None
    custom_data: Optional[dict] = None 
    is_active: bool
    model_config = ConfigDict(from_attributes=True)
