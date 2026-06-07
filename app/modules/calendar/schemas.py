"""
Esquemas Pydantic para el módulo de Calendario.
"""

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from .models import EnrollmentStatus


# --- EVENT TYPES ---

class EventTypeBase(BaseModel):
    name: str
    color: str = "#3B82F6"
    affects_sla: bool = False
    description: Optional[str] = None

class EventTypeCreate(EventTypeBase):
    pass

class EventTypeRead(EventTypeBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


# --- EVENTS ---

class CalendarEventBase(BaseModel):
    title: str
    description: Optional[str] = None
    date: date
    event_type_id: int
    is_enrollable: bool = False

class CalendarEventCreate(CalendarEventBase):
    pass

class CalendarEventRead(CalendarEventBase):
    id: int
    event_type: Optional[EventTypeRead] = None
    enrollment_count: int = 0
    model_config = ConfigDict(from_attributes=True)


# --- ENROLLMENTS ---

class EventEnrollmentCreate(BaseModel):
    employee_id: int

class EventEnrollmentRead(BaseModel):
    id: int
    employee_name: str
    employee_area: str
    status: EnrollmentStatus
    invitation_sent_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


# --- FULLCALENDAR ---

class FullCalendarEvent(BaseModel):
    id: str
    title: str
    start: date
    end: Optional[date] = None
    backgroundColor: str
    borderColor: str
    extendedProps: dict


# --- INVITATION ---

class InvitationPayload(BaseModel):
    sede_ids: List[int] = []
    area_ids: List[int] = []
    subject: str
    html_body: str 

class PublicResponse(BaseModel):
    action: str