from typing import List, Optional
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.recruitment.models import (
    RecruitmentProcess, 
    ProcessStage, 
    Vacancy, 
    ProcessStatus,
    VacancyStage,
    RecruitmentAudit
)
from app.modules.recruitment import schemas

# --- PROCESS MANAGEMENT ---

async def get_processes(db: AsyncSession) -> List[RecruitmentProcess]:
    """Obtiene todos los procesos de selección configurados."""
    stmt = (
        select(RecruitmentProcess)
        .options(
            selectinload(RecruitmentProcess.stages_config)
            .selectinload(ProcessStage.responsible)
        )
        .order_by(RecruitmentProcess.id)
    )
    return (await db.execute(stmt)).scalars().all()


async def get_process_detail(
    db: AsyncSession, process_id: int
) -> Optional[RecruitmentProcess]:
    """Obtiene el detalle de un proceso específico."""
    stmt = (
        select(RecruitmentProcess)
        .options(
            selectinload(RecruitmentProcess.stages_config)
            .selectinload(ProcessStage.responsible)
        )
        .where(RecruitmentProcess.id == process_id)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def create_process(
    db: AsyncSession, process_in: schemas.ProcessCreate
) -> RecruitmentProcess:
    """Crea un nuevo proceso de selección."""
    proc = RecruitmentProcess(**process_in.model_dump())
    db.add(proc)
    await db.commit()
    await db.refresh(proc, attribute_names=["stages_config"])
    return proc


async def update_process(
    db: AsyncSession, process_id: int, process_in: schemas.ProcessCreate
) -> Optional[RecruitmentProcess]:
    """Actualiza un proceso existente."""
    proc = await db.get(RecruitmentProcess, process_id)
    if not proc:
        return None
    for key, value in process_in.model_dump(exclude_unset=True).items():
        setattr(proc, key, value)
    await db.commit()
    await db.refresh(proc, attribute_names=["stages_config"])
    return proc


async def delete_process(db: AsyncSession, process_id: int) -> bool:
    """Elimina un proceso si no tiene vacantes asociadas."""
    if await db.scalar(
        select(func.count(Vacancy.id)).where(Vacancy.process_id == process_id)
    ) > 0:
        raise ValueError(
            "No se puede eliminar: Hay vacantes usando este proceso."
        )
    proc = await db.get(RecruitmentProcess, process_id)
    if not proc:
        return False
    await db.delete(proc)
    await db.commit()
    return True


# --- PROCESS STAGE MANAGEMENT ---

async def add_stage_to_process(
    db: AsyncSession, process_id: int, stage_in: schemas.ProcessStageCreate
) -> ProcessStage:
    """Añade una etapa a un proceso."""
    stage = ProcessStage(process_id=process_id, **stage_in.model_dump())
    db.add(stage)
    await db.commit()
    await db.refresh(stage, attribute_names=["responsible"])
    return stage


async def update_process_stage(
    db: AsyncSession, stage_id: int, stage_in: schemas.ProcessStageCreate
) -> Optional[ProcessStage]:
    """Actualiza la configuración de una etapa."""
    stage = await db.get(ProcessStage, stage_id)
    if not stage:
        return None

    stage.name = stage_in.name
    stage.sla_days = stage_in.sla_days
    stage.owner = stage_in.owner
    stage.responsible_id = stage_in.responsible_id
    stage.order_index = stage_in.order_index

    await db.commit()
    await db.refresh(stage, attribute_names=["responsible"])
    return stage


async def delete_process_stage(db: AsyncSession, stage_id: int) -> bool:
    """
    Elimina una etapa de la configuración del proceso.
    ADVERTENCIA: Si hay vacantes activas, elimina la etapa correspondiente en esas vacantes
    y recalcula el SLA implícitamente al remover los días de esa etapa.
    """
    # 1. Obtener la etapa a eliminar
    stage_def = await db.get(ProcessStage, stage_id)
    if not stage_def:
        return False

    process_id = stage_def.process_id
    deleted_order_index = stage_def.order_index
    stage_name = stage_def.name

    # 2. Buscar vacantes ABIERTAS que usen este proceso
    stmt_vacancies = select(Vacancy).options(selectinload(Vacancy.stages)).where(
        Vacancy.process_id == process_id,
        Vacancy.status == ProcessStatus.OPEN
    )
    active_vacancies = (await db.execute(stmt_vacancies)).scalars().all()

    # 3. Eliminar la etapa equivalente en las vacantes activas
    for vac in active_vacancies:
        # Buscar la etapa en la vacante que coincida (por nombre y orden aproximado)
        # Usamos una lista para poder modificarla
        stages_to_keep = []
        target_stage_found = False
        
        for s in vac.stages:
            # Criterio de coincidencia: Mismo nombre y mismo índice original
            if s.name == stage_name and s.order_index == deleted_order_index:
                await db.delete(s)
                target_stage_found = True
                
                # Registrar auditoría
                audit = RecruitmentAudit(
                    vacancy_id=vac.id,
                    action="STAGE_DELETED_ADMIN",
                    details=f"Etapa '{stage_name}' eliminada por cambio en la plantilla del proceso. SLA recalculado."
                )
                db.add(audit)
            else:
                stages_to_keep.append(s)
        
        # 4. Reordenar las etapas restantes de la vacante
        if target_stage_found:
            stages_to_keep.sort(key=lambda x: x.order_index)
            for idx, s in enumerate(stages_to_keep):
                s.order_index = idx
            db.add_all(stages_to_keep)

    # 5. Eliminar la definición de la etapa (Template)
    await db.delete(stage_def)

    # 6. Reordenar las etapas restantes del proceso (Template)
    stmt_remaining = select(ProcessStage).where(
        ProcessStage.process_id == process_id
    ).order_by(ProcessStage.order_index)
    
    remaining_stages = (await db.execute(stmt_remaining)).scalars().all()
    
    for idx, s in enumerate(remaining_stages):
        s.order_index = idx
        db.add(s)

    await db.commit()
    return True