"""
Esquemas Pydantic para el módulo de Colaboradores.
"""
import json
from datetime import date, datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from app.modules.employees.models import MovementType, EmploymentStatus, DocumentCategory
from app.modules.organization.schemas import (
    PositionRead, CompanyRead, ContractTypeRead, WorkingDayTypeRead,
    SalaryTypeRead, CurrencyRead, PaymentMethodRead, BankRead, CostCenterRead,
    ProbationDurationRead, RelationshipTypeRead
)
from app.modules.trainings.models import EnrollmentStatus, TrainingStatus
from app.modules.benefits.schemas import EmployeeBenefitRead
from app.modules.disciplinary.schemas import SanctionRead, RecognitionRead
from app.modules.dietary.schemas import DietaryRestrictionRead

# --- TIMELINE SCHEMA ---
class TimelineEvent(BaseModel):
    date: date
    category: str
    type_label: str
    title: str
    description: Optional[str] = None
    color: str
    icon: str

# --- TRAINING SCHEMAS ---
class TrainingSimple(BaseModel):
    id: int
    name: str
    start_date: date
    status: TrainingStatus
    model_config = ConfigDict(from_attributes=True)

class EnrollmentSimple(BaseModel):
    id: int
    status: EnrollmentStatus
    training: TrainingSimple
    model_config = ConfigDict(from_attributes=True)

# --- HISTORY SCHEMAS ---
class HistoryBase(BaseModel):
    movement_type: MovementType
    date: date
    notes: Optional[str] = None

class HistoryCreate(HistoryBase):
    new_position_id: Optional[int] = None

class HistoryRead(HistoryBase):
    id: int
    movement_type: MovementType
    date: date
    notes: Optional[str] = None
    previous_position_name: Optional[str] = None
    previous_area_name: Optional[str] = None
    new_position: Optional[PositionRead] = None
    contract_type: Optional[ContractTypeRead] = None
    base_salary: Optional[float] = None
    currency: Optional[CurrencyRead] = None
    model_config = ConfigDict(from_attributes=True)

# --- EMPLOYEE POSITION SCHEMA ---
class EmployeePositionRead(BaseModel):
    id: int
    position: PositionRead
    company: Optional[CompanyRead] = None
    contract_type: Optional[ContractTypeRead] = None
    
    contract_end_date: Optional[date] = None
    working_day_type: Optional[WorkingDayTypeRead] = None
    work_schedule: Optional[str] = None
    work_days: Optional[str] = None
    salary_type: Optional[SalaryTypeRead] = None
    base_salary: Optional[float] = None
    currency: Optional[CurrencyRead] = None
    payment_method: Optional[PaymentMethodRead] = None
    bank: Optional[BankRead] = None
    cost_center: Optional[CostCenterRead] = None

    # PERIODO DE PRUEBA
    probation_duration: Optional[ProbationDurationRead] = None
    probation_start_date: Optional[date] = None
    probation_end_date: Optional[date] = None
    probation_evaluation: Optional[str] = None
    probation_status: Optional[str] = None

    is_primary: bool
    start_date: date
    end_date: Optional[date] = None
    model_config = ConfigDict(from_attributes=True)

# --- DOCUMENT SCHEMA ---
class DocumentRead(BaseModel):
    id: int
    name: str
    category: DocumentCategory
    file_url: str
    upload_date: datetime
    expiration_date: Optional[date] = None
    notes: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

# --- EMPLOYEE SCHEMAS ---
# --- EMERGENCY CONTACT SCHEMAS ---
class EmergencyContactBase(BaseModel):
    name: str
    relationship_id: Optional[int] = None
    phone: str

class EmergencyContactCreate(EmergencyContactBase):
    pass

class EmergencyContactRead(EmergencyContactBase):
    id: int
    relationship: Optional[RelationshipTypeRead] = None
    model_config = ConfigDict(from_attributes=True)

class EmployeeBase(BaseModel):
    first_name: str
    last_name: str
    document_id: str
    position_id: int
    company_id: Optional[int] = None
    contract_type_id: Optional[int] = None
    
    # NUEVOS CAMPOS DE CONTRATACIÓN
    contract_end_date: Optional[date] = None
    working_day_type_id: Optional[int] = None
    work_schedule: Optional[str] = None
    work_days: Optional[str] = None
    salary_type_id: Optional[int] = None
    base_salary: Optional[float] = None
    currency_id: Optional[int] = None
    payment_method_id: Optional[int] = None
    bank_id: Optional[int] = None
    cost_center_id: Optional[int] = None

    # CONTACTO Y UBICACIÓN
    address: Optional[str] = None
    personal_email: Optional[EmailStr] = None
    phone: Optional[str] = None
    emergency_contacts: Optional[str] = None

    institutional_email: Optional[EmailStr] = None
    secondary_emails: Optional[str] = None
    personal_email: Optional[EmailStr] = None
    birthday: Optional[date] = None
    blood_type: Optional[str] = None
    
    dietary_restriction_ids: List[int] = []
    
    gender: Optional[str] = None
    marital_status: Optional[str] = None
    nationality: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    internal_extension: Optional[str] = None
    office_location: Optional[str] = None
    employment_status: EmploymentStatus = EmploymentStatus.ACTIVE

    @field_validator('dietary_restriction_ids', mode='before')
    @classmethod
    def parse_json_list(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except ValueError:
                return []
        return v
    
    @field_validator(
        'institutional_email', 'personal_email', 'secondary_emails', 
        'contract_type_id', 'working_day_type_id', 'salary_type_id',
        'currency_id', 'payment_method_id', 'bank_id', 'cost_center_id',
        mode='before'
    )
    @classmethod
    def empty_string_to_none(cls, v):
        if v == "": return None
        return v

class EmployeeCreate(EmployeeBase):
    pass

class EmployeeUpdate(BaseModel):
    employee_position_id: Optional[int] = None # Para editar un cargo específico (secundario)
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    document_id: Optional[str] = None
    position_id: Optional[int] = None
    company_id: Optional[int] = None
    contract_type_id: Optional[int] = None
    
    # NUEVOS CAMPOS DE CONTRATACIÓN
    contract_end_date: Optional[date] = None
    working_day_type_id: Optional[int] = None
    work_schedule: Optional[str] = None
    work_days: Optional[str] = None
    salary_type_id: Optional[int] = None
    base_salary: Optional[float] = None
    currency_id: Optional[int] = None
    payment_method_id: Optional[int] = None
    bank_id: Optional[int] = None
    cost_center_id: Optional[int] = None

    # PERIODO DE PRUEBA
    probation_duration_id: Optional[int] = None
    probation_start_date: Optional[date] = None
    probation_end_date: Optional[date] = None
    probation_evaluation: Optional[str] = None
    probation_status: Optional[str] = None

    # CONTACTO Y UBICACIÓN
    address: Optional[str] = None
    personal_email: Optional[EmailStr] = None
    phone: Optional[str] = None
    emergency_contacts: Optional[str] = None

    institutional_email: Optional[EmailStr] = None
    secondary_emails: Optional[str] = None
    birthday: Optional[date] = None
    blood_type: Optional[str] = None
    
    dietary_restriction_ids: Optional[List[int]] = None
    
    is_active: Optional[bool] = None
    gender: Optional[str] = None
    marital_status: Optional[str] = None
    nationality: Optional[str] = None
    internal_extension: Optional[str] = None
    office_location: Optional[str] = None

    @field_validator('dietary_restriction_ids', mode='before')
    @classmethod
    def parse_json_list(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except ValueError:
                return []
        return v

    @field_validator(
        'institutional_email', 'personal_email', 'birthday', 'secondary_emails',
        'contract_type_id', 'working_day_type_id', 'salary_type_id',
        'currency_id', 'payment_method_id', 'bank_id', 'cost_center_id',
        'probation_duration_id',
        mode='before'
    )
    @classmethod
    def empty_string_to_none(cls, v):
        if v == "": return None
        return v

class EmployeeList(BaseModel):
    id: int
    full_name: str
    document_id: str
    institutional_email: Optional[str] = None
    position_obj: Optional[PositionRead] = None
    company: Optional[CompanyRead] = None
    is_active: bool
    employment_status: EmploymentStatus
    birthday: Optional[date] = None
    photo_url: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

class EmployeeRead(EmployeeBase):
    id: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    full_name: str
    document_id: str
    institutional_email: Optional[str] = None
    secondary_emails: Optional[str] = None
    personal_email: Optional[str] = None
    birthday: Optional[date] = None
    blood_type: Optional[str] = None
    
    dietary_restrictions: List[DietaryRestrictionRead] = []
    
    photo_url: Optional[str] = None
    is_active: bool
    exit_date: Optional[date] = None
    
    position_obj: Optional[PositionRead] = None
    company: Optional[CompanyRead] = None
    emergency_contacts: List[EmergencyContactRead] = []
    positions_history: List[EmployeePositionRead] = []
    history: List[HistoryRead] = []
    trainings: List[EnrollmentSimple] = []
    documents: List[DocumentRead] = []
    benefits: List[EmployeeBenefitRead] = []
    sanctions: List[SanctionRead] = []
    recognitions: List[RecognitionRead] = []
    
    model_config = ConfigDict(from_attributes=True)

# --- ACTIONS PAYLOADS ---
class PromotionPayload(BaseModel):
    new_position_id: int
    new_company_id: Optional[int] = None
    new_contract_type_id: Optional[int] = None # NUEVO
    date: date
    notes: Optional[str] = None
    is_primary_promotion: bool = True 
    previous_employee_position_id: Optional[int] = None

class AddPositionPayload(BaseModel):
    position_id: int
    company_id: Optional[int] = None
    contract_type_id: Optional[int] = None
    start_date: date
    notes: Optional[str] = None
    
    # NUEVOS CAMPOS POR ROL
    contract_end_date: Optional[date] = None
    working_day_type_id: Optional[int] = None
    work_schedule: Optional[str] = None
    work_days: Optional[str] = None
    salary_type_id: Optional[int] = None
    base_salary: Optional[float] = None
    currency_id: Optional[int] = None
    payment_method_id: Optional[int] = None
    bank_id: Optional[int] = None
    cost_center_id: Optional[int] = None

    # PERIODO DE PRUEBA
    probation_duration_id: Optional[int] = None
    probation_start_date: Optional[date] = None
    probation_evaluation: Optional[str] = None

class ExitPayload(BaseModel):
    date: date
    notes: str

class RehirePayload(BaseModel):
    new_position_id: int
    new_company_id: Optional[int] = None
    new_contract_type_id: Optional[int] = None # NUEVO
    date: date
    notes: Optional[str] = None

class ChangeContractPayload(BaseModel):
    new_contract_type_id: int
    date: date
    notes: Optional[str] = None

class SalaryChangePayload(BaseModel):
    employee_position_id: int # ID específico de la relación cargo-persona
    new_base_salary: float
    new_currency_id: int
    date: date
    notes: Optional[str] = None