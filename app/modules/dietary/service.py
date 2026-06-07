from typing import List, Optional, Dict, Any
from fastapi import HTTPException
from sqlalchemy import func, select, distinct
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.dietary import schemas
from app.modules.dietary.models import DietaryRestriction, employee_dietary_association
from app.modules.employees.models import Employee
from app.modules.organization.models import Area, Position, Sede

async def get_all(db: AsyncSession) -> List[DietaryRestriction]:
    """Obtiene todas las restricciones con conteo de uso."""
    stmt = select(DietaryRestriction).order_by(DietaryRestriction.name)
    restrictions = (await db.execute(stmt)).scalars().all()
    
    for r in restrictions:
        count_stmt = select(func.count()).select_from(employee_dietary_association).where(
            employee_dietary_association.c.dietary_restriction_id == r.id
        )
        r.employee_count = await db.scalar(count_stmt)
    
    return restrictions

async def get_by_id(db: AsyncSession, id: int) -> Optional[DietaryRestriction]:
    return await db.get(DietaryRestriction, id)

async def get_employees_paginated(
    db: AsyncSession, 
    restriction_id: int,
    page: int = 1,
    limit: int = 20,
    search: Optional[str] = None,
    sede_id: Optional[int] = None,
    area_id: Optional[int] = None
) -> Dict[str, Any]:
    """Obtiene empleados paginados para una restricción específica."""
    
    offset = (page - 1) * limit

    # --- QUERY BASE ---
    # Usamos la tabla intermedia explícitamente para asegurar el filtrado correcto
    # Esto genera un INNER JOIN: Solo trae empleados que tengan esa restricción específica.
    stmt = (
        select(Employee)
        .join(employee_dietary_association, Employee.id == employee_dietary_association.c.employee_id)
        .join(Position, Employee.position_id == Position.id)
        .join(Area, Position.area_id == Area.id)
        .join(Sede, Area.sede_id == Sede.id)
        .where(
            employee_dietary_association.c.dietary_restriction_id == restriction_id,
            Employee.is_active == True
        )
    )

    # Filtros Dinámicos
    if sede_id:
        stmt = stmt.where(Sede.id == sede_id)
    
    if area_id:
        stmt = stmt.where(Area.id == area_id)

    if search:
        term = f"%{search}%"
        stmt = stmt.where(Employee.full_name.ilike(term))

    # --- CONTEO TOTAL ---
    # Usamos func.count sobre la misma estructura de query
    # select_from(stmt.subquery()) a veces falla si el subquery tiene columnas ambiguas
    # Mejor construimos el count sobre la query limpia.
    
    # Opción A: Usar subquery (generalmente seguro si la query base está bien formada)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    
    total = await db.scalar(count_stmt) or 0

    # --- OBTENCIÓN DE DATOS ---
    # Añadimos ordenamiento, paginación y carga de relaciones
    stmt = (
        stmt
        .options(
            selectinload(Employee.position_obj).selectinload(Position.area).selectinload(Area.sede)
        )
        .order_by(Employee.full_name)
        .offset(offset)
        .limit(limit)
    )
    
    result = await db.execute(stmt)
    employees = result.scalars().all()

    total_pages = (total + limit - 1) // limit

    return {
        "data": employees,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1
    }

async def create(db: AsyncSession, data: schemas.DietaryRestrictionCreate) -> DietaryRestriction:
    item = DietaryRestriction(**data.model_dump())
    db.add(item)
    try:
        await db.commit()
        await db.refresh(item)
        return item
    except IntegrityError:
        await db.rollback()
        raise HTTPException(400, "Ya existe una restricción con ese nombre.")

async def update(db: AsyncSession, id: int, data: schemas.DietaryRestrictionCreate) -> DietaryRestriction:
    item = await db.get(DietaryRestriction, id)
    if not item:
        raise HTTPException(404, "Restricción no encontrada")
    
    item.name = data.name
    item.description = data.description
    try:
        await db.commit()
        await db.refresh(item)
        return item
    except IntegrityError:
        await db.rollback()
        raise HTTPException(400, "El nombre ya está en uso.")

async def delete(db: AsyncSession, id: int):
    item = await db.get(DietaryRestriction, id)
    if not item:
        raise HTTPException(404, "Restricción no encontrada")
    
    # Verificar uso
    count_stmt = select(func.count()).select_from(employee_dietary_association).where(
        employee_dietary_association.c.dietary_restriction_id == id
    )
    usage = await db.scalar(count_stmt)
    if usage > 0:
        raise HTTPException(400, f"No se puede eliminar: Está asignada a {usage} colaboradores.")
        
    await db.delete(item)
    await db.commit()