"""
Esquemas Pydantic para el módulo de Reclutamiento.
Define la estructura de datos para validación y serialización de API.
"""

from datetime import date, datetime
from typing import List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from .models import ProcessStatus, StageOwner, VacancyType
from app.modules.organization.schemas import PositionRead, AreaRead


class UserSimple(BaseModel):
    """Representación simplificada de un usuario."""
    id: int
    full_name: str
    model_config = ConfigDict(from_attributes=True)


class AuditRead(BaseModel):
    """Esquema de lectura para auditoría."""
    id: int
    action: str
    details: str
    timestamp: datetime
    user: Optional[UserSimple] = None
    model_config = ConfigDict(from_attributes=True)


class ProcessStageBase(BaseModel):
    """Datos base para una etapa de proceso."""
    name: str
    sla_days: int
    owner: StageOwner
    order_index: int
    responsible_id: Optional[int] = None


class ProcessStageCreate(ProcessStageBase):
    """Esquema para crear una etapa de proceso."""
    pass


class ProcessStageRead(ProcessStageBase):
    """Esquema de lectura para una etapa de proceso."""
    id: int
    process_id: int
    responsible: Optional[UserSimple] = None
    model_config = ConfigDict(from_attributes=True)


class ProcessBase(BaseModel):
    """Datos base para un proceso de selección."""
    name: str
    description: Optional[str] = None
    is_active: bool = True


class HiringReasonBase(BaseModel):
    """Datos base para un motivo de contratación."""
    name: str = Field(..., min_length=2, max_length=100)
    is_active: bool = True


class HiringReasonCreate(HiringReasonBase):
    pass


class HiringReasonUpdate(HiringReasonBase):
    pass


class HiringReasonRead(HiringReasonBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class StageEditReasonBase(BaseModel):
    """Datos base para motivo de edición de etapa."""
    name: str = Field(..., min_length=2, max_length=100)
    is_active: bool = True


class StageEditReasonCreate(StageEditReasonBase):
    pass


class StageEditReasonUpdate(StageEditReasonBase):
    pass


class StageEditReasonRead(StageEditReasonBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class ProcessCreate(ProcessBase):
    """Esquema para crear un proceso."""
    pass


class ProcessRead(ProcessBase):
    """Esquema de lectura para un proceso."""
    id: int
    stages_config: List[ProcessStageRead] = []
    model_config = ConfigDict(from_attributes=True)


class StageUpdate(BaseModel):
    """Esquema para actualizar una etapa de vacante."""
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    deadline_date: Optional[date] = None
    notes: Optional[str] = None
    responsible_id: Optional[int] = None
    edit_reason_id: Optional[int] = None

    @field_validator('end_date', 'start_date', 'deadline_date', mode='before')
    @classmethod
    def parse_empty_date(cls, v):
        if v == "":
            return None
        return v


class StageRead(BaseModel):
    """Esquema de lectura para una etapa de vacante con campos calculados."""
    id: int
    name: str
    owner: StageOwner
    responsible_id: Optional[int] = None
    responsible: Optional[UserSimple] = None
    sla_days_snapshot: int
    order_index: int
    start_date: date
    end_date: Optional[date] = None
    deadline_date: Optional[date] = None
    notes: Optional[str] = None

    @computed_field
    def days_taken(self) -> int:
        """Calcula los días tomados para completar la etapa."""
        end = self.end_date or date.today()
        delta = (end - self.start_date).days
        return max(1, delta) if self.end_date else max(0, delta)

    @computed_field
    def sla_status(self) -> str:
        """Determina si la etapa está vencida."""
        if self.deadline_date:
            compare_date = self.end_date or date.today()
            if compare_date > self.deadline_date:
                return "overdue"
        return "ok"

    model_config = ConfigDict(from_attributes=True)


class VacancyBase(BaseModel):
    """Datos base para una vacante."""
    title: str = Field(..., min_length=5, max_length=100)
    description: str
    area_id: int
    process_id: int
    position_id: Optional[int] = None
    is_headcount_increase: bool = False
    hiring_reason_id: Optional[int] = None
    recruiter_id: Optional[int] = None


class VacancyCreate(VacancyBase):
    """Esquema para crear una vacante. No incluye vacancy_type."""
    pass


class VacancyUpdate(BaseModel):
    """Esquema para actualizar una vacante (incluye cierre y contratación)."""
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[ProcessStatus] = None
    vacancy_type: Optional[VacancyType] = None
    
    # Nuevos campos editables
    area_id: Optional[int] = None
    position_id: Optional[int] = None
    is_headcount_increase: Optional[bool] = None
    hiring_reason_id: Optional[int] = None
    recruiter_id: Optional[int] = None
    
    start_date: Optional[date] = None

    candidate_name: Optional[str] = None
    candidate_document: Optional[str] = None
    candidate_email: Optional[str] = None
    
    selected_employee_id: Optional[int] = None
    
    # NUEVO: Tipo de Contrato al cerrar
    contract_type_id: Optional[int] = None
    company_id: Optional[int] = None

    @field_validator('selected_employee_id', 'vacancy_type', 'start_date', 'position_id', 'area_id', 'hiring_reason_id', 'contract_type_id', 'company_id', mode='before')
    @classmethod
    def empty_string_to_none(cls, v):
        if v == "":
            return None
        return v


class VacancyRead(VacancyBase):
    """Esquema de lectura básico para una vacante."""
    id: int
    status: ProcessStatus
    vacancy_type: Optional[VacancyType] = None
    start_date: Optional[date] = None
    created_at: datetime
    closed_at: Optional[datetime] = None
    requester_id: int
    area_name: Optional[str] = None
    sede_name: Optional[str] = None
    process_name: Optional[str] = None
    position: Optional[PositionRead] = None
    area: Optional[AreaRead] = None
    hiring_reason: Optional[HiringReasonRead] = None
    recruiter: Optional[UserSimple] = None
    
    stages: List[StageRead] = [] 

    @computed_field
    def hiring_reason_name(self) -> Optional[str]:
        if self.hiring_reason:
            return self.hiring_reason.name
        return None

    @computed_field
    def sede_id(self) -> Optional[int]:
        """Obtiene el ID de la sede a través del área."""
        if hasattr(self, 'area') and self.area:
            return self.area.sede_id
        return None

    @computed_field
    def process_start_date(self) -> date:
        """
        Retorna la fecha de inicio de la PRIMERA etapa del proceso.
        Si no hay etapas, retorna la fecha de creación.
        """
        if not self.stages:
            return self.created_at.date()
        
        # Ordenar etapas por índice para encontrar la primera (0)
        sorted_stages = sorted(self.stages, key=lambda s: s.order_index)
        
        # Retornar la fecha de inicio de la primera etapa
        return sorted_stages[0].start_date

    @computed_field
    def total_sla_days(self) -> int:
        """Suma total de días SLA de todas las etapas."""
        return sum(s.sla_days_snapshot for s in self.stages)

    @computed_field
    def total_days_elapsed(self) -> int:
        """Calcula días transcurridos desde el inicio de la primera etapa."""
        # Usamos process_start_date como base en lugar de created_at
        start_date = self.process_start_date
        start = datetime.combine(start_date, datetime.min.time())

        if self.created_at.tzinfo:
             start = start.replace(tzinfo=self.created_at.tzinfo)
             now = datetime.now(self.created_at.tzinfo)
        else:
             now = datetime.now()

        end = self.closed_at or now

        if start.tzinfo and not end.tzinfo:
            start = start.replace(tzinfo=None)
        elif not start.tzinfo and end.tzinfo:
            end = end.replace(tzinfo=None)

        delta = (end - start).days

        if self.status == ProcessStatus.OPEN:
            return max(1, delta)

        return max(0, delta)

    @computed_field
    def global_sla_status(self) -> str:
        """Estado global del SLA de la vacante."""
        if self.total_days_elapsed > self.total_sla_days:
            return "overdue"
        return "ok"

    model_config = ConfigDict(from_attributes=True)


class VacancyPagination(BaseModel):
    """Esquema para respuestas paginadas de vacantes."""
    items: List[VacancyRead]
    total: int
    page: int
    limit: int
    total_pages: int
    has_next: bool
    has_prev: bool


class VacancyDetail(VacancyRead):
    """Esquema detallado de vacante con métricas adicionales y auditoría."""
    audits: List[AuditRead] = []

    @computed_field
    def progress_percent(self) -> int:
        """Calcula el porcentaje de avance."""
        if not self.stages:
            return 0
        completed = len([s for s in self.stages if s.end_date is not None])
        return int((completed / len(self.stages)) * 100)

    @computed_field
    def sla_consumption_percent(self) -> int:
        """Porcentaje de consumo del tiempo SLA total."""
        if self.total_sla_days == 0:
            return 0
        return int((self.total_days_elapsed / self.total_sla_days) * 100)