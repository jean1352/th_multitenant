"""
Utilidad para el cálculo de fechas hábiles (SLA) considerando feriados y fines de semana.
"""
from datetime import date, timedelta
from typing import Set, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.calendar.models import CalendarEvent, CalendarEventType


async def get_holidays_set(db: AsyncSession, start_date: date, years_ahead: int = 1) -> Set[date]:
    """
    Obtiene un conjunto de fechas que son feriados o días no laborables
    basado en la configuración del Tipo de Evento (affects_sla=True).
    """
    end_date = start_date + timedelta(days=365 * years_ahead)
    
    stmt = (
        select(CalendarEvent.date)
        .join(CalendarEventType)
        .where(
            CalendarEventType.affects_sla == True,
            CalendarEvent.date.between(start_date, end_date)
        )
    )
    result = await db.execute(stmt)
    return set(result.scalars().all())


async def add_business_days(
    db: AsyncSession, 
    start_date: date, 
    days_to_add: int,
    holidays_cache: Optional[Set[date]] = None
) -> date:
    """
    Calcula la fecha futura sumando días hábiles.
    Salta Sábados (5), Domingos (6) y Feriados configurados.
    """
    if days_to_add == 0:
        return start_date

    if holidays_cache is None:
        holidays_cache = await get_holidays_set(db, start_date)

    current_date = start_date
    days_added = 0
    step = 1 if days_to_add > 0 else -1
    target_days = abs(days_to_add)

    while days_added < target_days:
        current_date += timedelta(days=step)
        
        weekday = current_date.weekday()
        
        if weekday >= 5: # Fin de semana
            continue 
            
        if current_date in holidays_cache: # Feriado / No Laborable
            continue 
            
        days_added += 1

    return current_date