import asyncio
import logging
from datetime import datetime, time
from sqlalchemy import select
from sqlalchemy.orm import selectinload

# Configuración básica de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from app.core.database import AsyncSessionLocal

# --- IMPORTACIONES CRÍTICAS PARA EL REGISTRO DE SQLALCHEMY ---
import app.modules.auth.models
import app.modules.organization.models
import app.modules.recruitment.models
import app.modules.employees.models
import app.modules.trainings.models
import app.modules.calendar.models
import app.modules.notifications.models
import app.modules.benefits.models # <--- AGREGADO

from app.modules.recruitment.models import Vacancy, ProcessStatus, VacancyType

async def close_completed_vacancies():
    logger.info("🔍 Buscando vacantes listas para cerrar...")
    
    async with AsyncSessionLocal() as session:
        # 1. Obtener todas las vacantes ABIERTAS cargando sus etapas
        stmt = (
            select(Vacancy)
            .options(selectinload(Vacancy.stages))
            .where(Vacancy.status == ProcessStatus.OPEN)
        )
        result = await session.execute(stmt)
        vacancies = result.scalars().all()
        
        closed_count = 0
        
        for vac in vacancies:
            if not vac.stages:
                continue
            
            # 2. Identificar la última etapa (mayor order_index)
            sorted_stages = sorted(vac.stages, key=lambda s: s.order_index)
            last_stage = sorted_stages[-1]
            
            # 3. Verificar si la última etapa está terminada
            if last_stage.end_date:
                logger.info(f"  -> Cerrando Vacante ID {vac.id}: '{vac.title}'")
                logger.info(f"     Última etapa '{last_stage.name}' finalizó el {last_stage.end_date}")
                
                # Actualizar estado
                vac.status = ProcessStatus.CLOSED
                
                # Establecer fecha de cierre igual a la fecha fin de la última etapa
                close_dt = datetime.combine(last_stage.end_date, time.min)
                vac.closed_at = close_dt
                
                # Opcional: Si no tiene tipo de vacante, asignar uno por defecto
                if not vac.vacancy_type:
                    vac.vacancy_type = VacancyType.EXTERNAL 
                
                closed_count += 1
        
        if closed_count > 0:
            await session.commit()
            logger.info(f"✅ Se cerraron exitosamente {closed_count} vacantes.")
        else:
            logger.info("ℹ️  No se encontraron vacantes pendientes de cierre automático.")

if __name__ == "__main__":
    asyncio.run(close_completed_vacancies())