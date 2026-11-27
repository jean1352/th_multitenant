"""
Utilidad para el cálculo de fechas hábiles (SLA) considerando feriados y fines de semana.
"""
from datetime import date, timedelta
from typing import Dict, Optional, Set

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.calendar.models import CalendarEvent, CalendarEventType


# Cache de días no laborables aislado por esquema de tenant. Permite que los
# esquemas Pydantic (síncronos y sin acceso a la DB) cuenten días hábiles sin
# mezclar feriados entre organizaciones.
_holidays_cache_by_tenant: Dict[str, Set[date]] = {}


def _current_tenant_cache_key() -> str:
    from app.core.tenants import get_current_tenant
    tenant = get_current_tenant()
    return tenant.schema_name if tenant else "public"


def set_holidays_cache(holidays: Set[date]) -> None:
    """Establece el cache de días no laborables (feriados) para el tenant actual."""
    _holidays_cache_by_tenant[_current_tenant_cache_key()] = set(holidays)


def get_holidays_cache() -> Set[date]:
    """Devuelve el cache de días no laborables del tenant actual."""
    return _holidays_cache_by_tenant.get(_current_tenant_cache_key(), set())


async def refresh_holidays_cache(db: AsyncSession) -> None:
    """
    Carga TODOS los días no laborables (afectan SLA) al cache global.
    Se usa tanto en el arranque como antes de serializar vacantes para que
    el contador de días hábiles transcurridos sea correcto.
    """
    stmt = (
        select(CalendarEvent.date)
        .join(CalendarEventType)
        .where(CalendarEventType.affects_sla == True)
    )
    result = await db.execute(stmt)
    set_holidays_cache(set(result.scalars().all()))


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


def next_business_day(
    start_date: date,
    holidays: Optional[Set[date]] = None,
) -> date:
    """
    Devuelve el siguiente día hábil estrictamente posterior a start_date.

    Salta Sábados (5), Domingos (6) y feriados configurados.
    Se usa para evitar que dos etapas consecutivas se solapen en el tiempo:
    si una etapa termina (deadline/fin real) un día, la siguiente inicia el
    siguiente día hábil.
    """
    if holidays is None:
        holidays = get_holidays_cache()

    current = start_date + timedelta(days=1)
    while current.weekday() >= 5 or current in holidays:
        current += timedelta(days=1)

    return current


def count_business_days(
    start_date: date,
    end_date: date,
    holidays: Optional[Set[date]] = None,
) -> int:
    """
    Cuenta los días hábiles en el intervalo (start_date, end_date].
    Excluye Sábados (5), Domingos (6) y feriados configurados.

    Es consistente con add_business_days: si add_business_days(start, N) == end,
    entonces count_business_days(start, end) == N.
    """
    if holidays is None:
        holidays = get_holidays_cache()

    if end_date < start_date:
        return 0

    total = 0
    current = start_date + timedelta(days=1)
    while current <= end_date:
        if current.weekday() < 5 and current not in holidays:
            total += 1
        current += timedelta(days=1)

    return total


_WEEKDAY_NAMES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


def weekday_name(d: date) -> str:
    """Nombre en español del día de la semana."""
    return _WEEKDAY_NAMES[d.weekday()]


async def get_holidays_with_names(
    db: AsyncSession, start_date: date, end_date: date
) -> Dict[date, str]:
    """
    Devuelve un diccionario {fecha: título} de los días no laborables
    (affects_sla=True) dentro del rango, para poder auditar el SLA.
    """
    stmt = (
        select(CalendarEvent.date, CalendarEvent.title)
        .join(CalendarEventType)
        .where(
            CalendarEventType.affects_sla == True,
            CalendarEvent.date.between(start_date, end_date),
        )
    )
    result = await db.execute(stmt)
    return {row[0]: row[1] for row in result}


def classify_days(
    start_date: date,
    end_date: date,
    holidays: Optional[Dict[date, str]] = None,
) -> Dict[str, list]:
    """
    Clasifica cada día del rango [start_date, end_date] para auditoría del SLA.

    - El día de inicio se marca como "inicio" (referencia, no se cuenta).
    - Los días hábiles posteriores al inicio se marcan "contado".
    - Sábados, domingos y feriados (affects_sla=True) se marcan "excluido" con su motivo.

    Devuelve {"days": [...], "counted": [fechas hábiles]}.
    """
    if holidays is None:
        holidays = {}

    days = [{"date": start_date, "status": "inicio", "reason": None}]
    counted = []

    current = start_date + timedelta(days=1)
    while current <= end_date:
        if current.weekday() >= 5:
            reason = "Sábado" if current.weekday() == 5 else "Domingo"
            days.append({"date": current, "status": "excluido", "reason": reason})
        elif current in holidays:
            days.append(
                {"date": current, "status": "excluido", "reason": f"Feriado: {holidays[current]}"}
            )
        else:
            days.append({"date": current, "status": "contado", "reason": None})
            counted.append(current)
        current += timedelta(days=1)

    return {"days": days, "counted": counted}