"""
Lógica de negocio para el módulo de Organización.
Maneja CRUD de estructura organizacional y generación de datos para gráficos.
"""

from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.organization import schemas
from app.modules.organization.models import (
    Area, Position, Sede, Company, ContractType,
    WorkingDayType, SalaryType, Currency, PaymentMethod, Bank, CostCenter,
    ProbationDuration, RelationshipType
)
from app.modules.employees.models import Employee
from app.core.config import settings


# --- CONTRACT TYPES CRUD ---

async def get_contract_types(
    db: AsyncSession, active_only: bool = False
) -> List[ContractType]:
    """Obtiene lista de tipos de contrato."""
    stmt = select(ContractType).order_by(ContractType.name)
    if active_only:
        stmt = stmt.where(ContractType.is_active == True)
    result = await db.execute(stmt)
    return result.scalars().all()

async def create_contract_type(
    db: AsyncSession, data: schemas.ContractTypeCreate
) -> ContractType:
    """Crea un nuevo tipo de contrato."""
    obj = ContractType(**data.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj

async def update_contract_type(
    db: AsyncSession, id: int, data: schemas.ContractTypeUpdate
) -> Optional[ContractType]:
    """Actualiza un tipo de contrato."""
    obj = await db.get(ContractType, id)
    if not obj: return None
    
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
        
    await db.commit()
    await db.refresh(obj)
    return obj

async def delete_contract_type(db: AsyncSession, id: int) -> bool:
    """Elimina un tipo de contrato."""
    obj = await db.get(ContractType, id)
    if not obj: return False
    await db.delete(obj)
    await db.commit()
    return True


# --- WORKING DAY TYPES CRUD ---
async def get_working_day_types(db: AsyncSession, active_only: bool = False) -> List[WorkingDayType]:
    stmt = select(WorkingDayType).order_by(WorkingDayType.name)
    if active_only: stmt = stmt.where(WorkingDayType.is_active == True)
    return (await db.execute(stmt)).scalars().all()

async def create_working_day_type(db: AsyncSession, data: schemas.WorkingDayTypeCreate) -> WorkingDayType:
    obj = WorkingDayType(**data.model_dump())
    db.add(obj); await db.commit(); await db.refresh(obj)
    return obj

async def update_working_day_type(db: AsyncSession, id: int, data: schemas.WorkingDayTypeUpdate) -> Optional[WorkingDayType]:
    obj = await db.get(WorkingDayType, id)
    if not obj: return None
    for k, v in data.model_dump(exclude_unset=True).items(): setattr(obj, k, v)
    await db.commit(); await db.refresh(obj)
    return obj

async def delete_working_day_type(db: AsyncSession, id: int) -> bool:
    obj = await db.get(WorkingDayType, id); 
    if not obj: return False
    await db.delete(obj); await db.commit(); return True


# --- SALARY TYPES CRUD ---
async def get_salary_types(db: AsyncSession, active_only: bool = False) -> List[SalaryType]:
    stmt = select(SalaryType).order_by(SalaryType.name)
    if active_only: stmt = stmt.where(SalaryType.is_active == True)
    return (await db.execute(stmt)).scalars().all()

async def create_salary_type(db: AsyncSession, data: schemas.SalaryTypeCreate) -> SalaryType:
    obj = SalaryType(**data.model_dump())
    db.add(obj); await db.commit(); await db.refresh(obj)
    return obj

async def update_salary_type(db: AsyncSession, id: int, data: schemas.SalaryTypeUpdate) -> Optional[SalaryType]:
    obj = await db.get(SalaryType, id)
    if not obj: return None
    for k, v in data.model_dump(exclude_unset=True).items(): setattr(obj, k, v)
    await db.commit(); await db.refresh(obj)
    return obj

async def delete_salary_type(db: AsyncSession, id: int) -> bool:
    obj = await db.get(SalaryType, id); 
    if not obj: return False
    await db.delete(obj); await db.commit(); return True


# --- CURRENCIES CRUD ---
async def get_currencies(db: AsyncSession, active_only: bool = False) -> List[Currency]:
    stmt = select(Currency).order_by(Currency.name)
    if active_only: stmt = stmt.where(Currency.is_active == True)
    return (await db.execute(stmt)).scalars().all()

async def create_currency(db: AsyncSession, data: schemas.CurrencyCreate) -> Currency:
    obj = Currency(**data.model_dump())
    db.add(obj); await db.commit(); await db.refresh(obj)
    return obj

async def update_currency(db: AsyncSession, id: int, data: schemas.CurrencyUpdate) -> Optional[Currency]:
    obj = await db.get(Currency, id)
    if not obj: return None
    for k, v in data.model_dump(exclude_unset=True).items(): setattr(obj, k, v)
    await db.commit(); await db.refresh(obj)
    return obj

async def delete_currency(db: AsyncSession, id: int) -> bool:
    obj = await db.get(Currency, id); 
    if not obj: return False
    await db.delete(obj); await db.commit(); return True


# --- PAYMENT METHODS CRUD ---
async def get_payment_methods(db: AsyncSession, active_only: bool = False) -> List[PaymentMethod]:
    stmt = select(PaymentMethod).order_by(PaymentMethod.name)
    if active_only: stmt = stmt.where(PaymentMethod.is_active == True)
    return (await db.execute(stmt)).scalars().all()

async def create_payment_method(db: AsyncSession, data: schemas.PaymentMethodCreate) -> PaymentMethod:
    obj = PaymentMethod(**data.model_dump())
    db.add(obj); await db.commit(); await db.refresh(obj)
    return obj

async def update_payment_method(db: AsyncSession, id: int, data: schemas.PaymentMethodUpdate) -> Optional[PaymentMethod]:
    obj = await db.get(PaymentMethod, id)
    if not obj: return None
    for k, v in data.model_dump(exclude_unset=True).items(): setattr(obj, k, v)
    await db.commit(); await db.refresh(obj)
    return obj

async def delete_payment_method(db: AsyncSession, id: int) -> bool:
    obj = await db.get(PaymentMethod, id); 
    if not obj: return False
    await db.delete(obj); await db.commit(); return True


# --- BANKS CRUD ---
async def get_banks(db: AsyncSession, active_only: bool = False) -> List[Bank]:
    stmt = select(Bank).order_by(Bank.name)
    if active_only: stmt = stmt.where(Bank.is_active == True)
    return (await db.execute(stmt)).scalars().all()

async def create_bank(db: AsyncSession, data: schemas.BankCreate) -> Bank:
    obj = Bank(**data.model_dump())
    db.add(obj); await db.commit(); await db.refresh(obj)
    return obj

async def update_bank(db: AsyncSession, id: int, data: schemas.BankUpdate) -> Optional[Bank]:
    obj = await db.get(Bank, id)
    if not obj: return None
    for k, v in data.model_dump(exclude_unset=True).items(): setattr(obj, k, v)
    await db.commit(); await db.refresh(obj)
    return obj

async def delete_bank(db: AsyncSession, id: int) -> bool:
    obj = await db.get(Bank, id); 
    if not obj: return False
    await db.delete(obj); await db.commit(); return True


# --- COST CENTERS CRUD ---
async def get_cost_centers(db: AsyncSession, active_only: bool = False) -> List[CostCenter]:
    stmt = select(CostCenter).order_by(CostCenter.name)
    if active_only: stmt = stmt.where(CostCenter.is_active == True)
    return (await db.execute(stmt)).scalars().all()

async def create_cost_center(db: AsyncSession, data: schemas.CostCenterCreate) -> CostCenter:
    obj = CostCenter(**data.model_dump())
    db.add(obj); await db.commit(); await db.refresh(obj)
    return obj

async def update_cost_center(db: AsyncSession, id: int, data: schemas.CostCenterUpdate) -> Optional[CostCenter]:
    obj = await db.get(CostCenter, id)
    if not obj: return None
    for k, v in data.model_dump(exclude_unset=True).items(): setattr(obj, k, v)
    await db.commit(); await db.refresh(obj)
    return obj

async def delete_cost_center(db: AsyncSession, id: int) -> bool:
    obj = await db.get(CostCenter, id); 
    if not obj: return False
    await db.delete(obj); await db.commit(); return True


# --- PROBATION DURATIONS CRUD ---
async def get_probation_durations(db: AsyncSession, active_only: bool = False) -> List[ProbationDuration]:
    stmt = select(ProbationDuration).order_by(ProbationDuration.days)
    if active_only: stmt = stmt.where(ProbationDuration.is_active == True)
    return (await db.execute(stmt)).scalars().all()

async def create_probation_duration(db: AsyncSession, data: schemas.ProbationDurationCreate) -> ProbationDuration:
    obj = ProbationDuration(**data.model_dump())
    db.add(obj); await db.commit(); await db.refresh(obj)
    return obj

async def update_probation_duration(db: AsyncSession, id: int, data: schemas.ProbationDurationUpdate) -> Optional[ProbationDuration]:
    obj = await db.get(ProbationDuration, id)
    if not obj: return None
    for k, v in data.model_dump(exclude_unset=True).items(): setattr(obj, k, v)
    await db.commit(); await db.refresh(obj)
    return obj

async def delete_probation_duration(db: AsyncSession, id: int) -> bool:
    obj = await db.get(ProbationDuration, id); 
    if not obj: return False
    await db.delete(obj); await db.commit(); return True


# --- RELATIONSHIP TYPES CRUD ---
async def get_relationship_types(db: AsyncSession, active_only: bool = False) -> List[RelationshipType]:
    stmt = select(RelationshipType).order_by(RelationshipType.name)
    if active_only: stmt = stmt.where(RelationshipType.is_active == True)
    return (await db.execute(stmt)).scalars().all()

async def create_relationship_type(db: AsyncSession, data: schemas.RelationshipTypeCreate) -> RelationshipType:
    obj = RelationshipType(**data.model_dump())
    db.add(obj); await db.commit(); await db.refresh(obj)
    return obj

async def update_relationship_type(db: AsyncSession, id: int, data: schemas.RelationshipTypeUpdate) -> Optional[RelationshipType]:
    obj = await db.get(RelationshipType, id)
    if not obj: return None
    for k, v in data.model_dump(exclude_unset=True).items(): setattr(obj, k, v)
    await db.commit(); await db.refresh(obj)
    return obj

async def delete_relationship_type(db: AsyncSession, id: int) -> bool:
    obj = await db.get(RelationshipType, id); 
    if not obj: return False
    await db.delete(obj); await db.commit(); return True


# --- COMPANIES CRUD ---

async def get_companies(
    db: AsyncSession, skip: int = 0, limit: int = 100
) -> List[Company]:
    """Obtiene lista paginada de empresas."""
    result = await db.execute(select(Company).offset(skip).limit(limit))
    return result.scalars().all()


async def create_company(db: AsyncSession, company: schemas.CompanyCreate) -> Company:
    """Crea una nueva empresa."""
    db_company = Company(name=company.name, tax_id=company.tax_id)
    db.add(db_company)
    await db.commit()
    await db.refresh(db_company)
    return db_company


async def update_company(
    db: AsyncSession, company_id: int, company_update: schemas.CompanyUpdate
) -> Optional[Company]:
    """Actualiza una empresa existente."""
    db_company = await db.get(Company, company_id)
    if not db_company:
        return None
    for key, value in company_update.model_dump(exclude_unset=True).items():
        setattr(db_company, key, value)
    await db.commit()
    await db.refresh(db_company)
    return db_company


async def delete_company(db: AsyncSession, company_id: int) -> bool:
    """Elimina una empresa."""
    db_company = await db.get(Company, company_id)
    if not db_company:
        return False
    await db.delete(db_company)
    await db.commit()
    return True


# --- SEDES CRUD ---

async def get_sedes(
    db: AsyncSession, skip: int = 0, limit: int = 100
) -> List[Sede]:
    """Obtiene lista paginada de sedes."""
    result = await db.execute(select(Sede).offset(skip).limit(limit))
    return result.scalars().all()


async def create_sede(db: AsyncSession, sede: schemas.SedeCreate) -> Sede:
    """Crea una nueva sede."""
    db_sede = Sede(name=sede.name, address=sede.address)
    db.add(db_sede)
    await db.commit()
    await db.refresh(db_sede)
    return db_sede


async def update_sede(
    db: AsyncSession, sede_id: int, sede_update: schemas.SedeUpdate
) -> Optional[Sede]:
    """Actualiza una sede existente."""
    db_sede = await db.get(Sede, sede_id)
    if not db_sede:
        return None
    for key, value in sede_update.model_dump(exclude_unset=True).items():
        setattr(db_sede, key, value)
    await db.commit()
    await db.refresh(db_sede)
    return db_sede


async def delete_sede(db: AsyncSession, sede_id: int) -> bool:
    """Elimina una sede."""
    db_sede = await db.get(Sede, sede_id)
    if not db_sede:
        return False
    await db.delete(db_sede)
    await db.commit()
    return True


# --- AREAS CRUD ---

async def get_areas(
    db: AsyncSession, 
    search: Optional[str] = None,
    sede_id: Optional[int] = None
) -> List[Area]:
    """Obtiene lista de áreas con filtros y relaciones cargadas."""
    stmt = select(Area).options(
        selectinload(Area.sede), selectinload(Area.positions)
    )
    if search:
        stmt = stmt.where(Area.name.ilike(f"%{search}%"))
    
    if sede_id:
        stmt = stmt.where(Area.sede_id == sede_id)

    stmt = stmt.order_by(Area.name)
    result = await db.execute(stmt)
    return result.scalars().all()


async def get_area_by_id(db: AsyncSession, area_id: int) -> Optional[Area]:
    """Obtiene detalle de un área."""
    stmt = (
        select(Area)
        .options(
            selectinload(Area.sede), 
            selectinload(Area.positions).selectinload(Position.parent)
        )
        .where(Area.id == area_id)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def create_area(db: AsyncSession, area: schemas.AreaCreate) -> Area:
    """Crea una nueva área."""
    db_area = Area(
        name=area.name,
        sede_id=area.sede_id,
        responsible_email=area.responsible_email,
    )
    db.add(db_area)
    await db.commit()
    
    return await get_area_by_id(db, db_area.id)


async def update_area(
    db: AsyncSession, area_id: int, area_update: schemas.AreaUpdate
) -> Optional[Area]:
    """Actualiza un área existente."""
    db_area = await db.get(Area, area_id)
    if not db_area:
        return None
    for key, value in area_update.model_dump(exclude_unset=True).items():
        setattr(db_area, key, value)
    
    await db.commit()
    return await get_area_by_id(db, area_id)


async def delete_area(db: AsyncSession, area_id: int) -> bool:
    """Elimina un área."""
    db_area = await db.get(Area, area_id)
    if not db_area:
        return False
    await db.delete(db_area)
    await db.commit()
    return True


# --- POSITIONS CRUD ---

async def create_position(
    db: AsyncSession, pos: schemas.PositionCreate
) -> Position:
    """Crea un nuevo cargo."""
    db_pos = Position(
        name=pos.name, 
        area_id=pos.area_id,
        parent_id=pos.parent_id,
        is_leader=pos.is_leader
    )
    db.add(db_pos)
    await db.commit()
    
    # CORRECCIÓN: Cargar 'area', 'sede' y 'company' para evitar MissingGreenlet
    stmt = (
        select(Position)
        .options(
            selectinload(Position.parent),
            selectinload(Position.area).selectinload(Area.sede)
        )
        .where(Position.id == db_pos.id)
    )
    result = await db.execute(stmt)
    return result.scalar_one()


async def update_position(
    db: AsyncSession, pos_id: int, pos_data: schemas.PositionUpdate
) -> Optional[Position]:
    """Actualiza un cargo existente."""
    pos = await db.get(Position, pos_id)
    if not pos:
        return None
    
    update_data = pos_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(pos, key, value)
        
    await db.commit()
    
    # CORRECCIÓN: Cargar 'area', 'sede' y 'company' para evitar MissingGreenlet
    stmt = (
        select(Position)
        .options(
            selectinload(Position.parent),
            selectinload(Position.area).selectinload(Area.sede)
        )
        .where(Position.id == pos_id)
    )
    result = await db.execute(stmt)
    return result.scalar_one()


async def delete_position(db: AsyncSession, pos_id: int) -> bool:
    """Elimina un cargo."""
    pos = await db.get(Position, pos_id)
    if not pos:
        return False
    await db.delete(pos)
    await db.commit()
    return True


# --- CHART DATA GENERATORS ---

def build_hierarchy_recursive(position: Position, all_positions: List[Position]) -> Dict[str, Any]:
    """Construye el árbol basado en parent_id (Jerarquía de Cargos)."""
    children_positions = [p for p in all_positions if p.parent_id == position.id]
    
    node = {
        "name": position.name,
        "type": "position",
        "area": position.area.name if position.area else "Sin Área",
        "is_leader": position.is_leader,
        "children": []
    }

    # En este modo, los empleados son hojas del cargo
    if position.employees:
        for emp in position.employees:
            if emp.is_active:
                node["children"].append({
                    "name": emp.full_name,
                    "type": "employee",
                    "value": 1,
                    "photo": emp.photo_url,
                    "id": emp.id,
                    "position": position.name,
                    "company": emp.company.name if emp.company else ""
                })

    for child in children_positions:
        node["children"].append(build_hierarchy_recursive(child, all_positions))

    if not node["children"]:
        del node["children"]
        node["value"] = 1
    
    return node

async def get_hierarchy_data(db: AsyncSession) -> Dict[str, Any]:
    """Datos para el modo RED (Jerarquía de Cargos)."""
    stmt = select(Position).options(
        selectinload(Position.employees).selectinload(Employee.company),
        selectinload(Position.area)
    )
    all_positions = (await db.execute(stmt)).scalars().all()
    root_positions = [p for p in all_positions if p.parent_id is None]

    hierarchy_children = []
    for root_pos in root_positions:
        hierarchy_children.append(build_hierarchy_recursive(root_pos, all_positions))

    return {
        "name": settings.BUSINESS_NAME,
        "type": "root",
        "children": hierarchy_children
    }

async def get_structure_data(db: AsyncSession) -> Dict[str, Any]:
    """Datos para el modo BURBUJA (Sede -> Área)."""
    stmt = select(Sede).options(
        selectinload(Sede.areas)
        .selectinload(Area.positions)
        .selectinload(Position.employees).selectinload(Employee.company)
    )
    sedes = (await db.execute(stmt)).scalars().all()

    children_sedes = []
    for sede in sedes:
        children_areas = []
        for area in sede.areas:
            children_employees = []
            for pos in area.positions:
                for emp in pos.employees:
                    if emp.is_active:
                        children_employees.append({
                            "name": emp.full_name,
                            "position": pos.name,
                            "value": 1,
                            "type": "employee",
                            "photo": emp.photo_url,
                            "id": emp.id,
                            "company": emp.company.name if emp.company else ""
                        })
            
            area_node = {"name": area.name, "type": "area", "children": children_employees}
            if not children_employees:
                area_node["value"] = 0.5
                del area_node["children"]
            children_areas.append(area_node)

        sede_node = {"name": sede.name, "type": "sede", "children": children_areas}
        if not children_areas:
            sede_node["value"] = 1
            del sede_node["children"]
        children_sedes.append(sede_node)

    return {
        "name": settings.BUSINESS_NAME,
        "type": "root",
        "children": children_sedes
    }

# --- NUEVO MODO: JERARQUÍA DE PERSONAS ---

def build_people_tree(position: Position, all_positions: List[Position]) -> List[Dict[str, Any]]:
    """
    Construye un árbol donde los nodos son PERSONAS.
    Si un cargo tiene múltiples personas, cada una es un nodo padre de los subordinados del cargo hijo.
    """
    # Empleados en este cargo (Jefes actuales)
    current_employees = [e for e in position.employees if e.is_active]
    
    # Cargos subordinados directos
    child_positions = [p for p in all_positions if p.parent_id == position.id]
    
    # Construir sub-árbol de subordinados (recursivo)
    subordinates_nodes = []
    for child_pos in child_positions:
        subordinates_nodes.extend(build_people_tree(child_pos, all_positions))
    
    # Si no hay empleados en este cargo, pero hay subordinados, creamos un nodo "Vacante"
    # para no romper la cadena de mando visual.
    if not current_employees:
        if not subordinates_nodes:
            return [] # Hoja vacía, no mostrar
        
        return [{
            "name": f"[VACANTE] {position.name}",
            "type": "vacancy",
            "area": position.area.name,
            "children": subordinates_nodes
        }]

    # Si hay empleados, cada uno es un nodo que tiene como hijos a TODOS los subordinados
    # (Asumimos que si hay 2 gerentes, ambos mandan sobre los analistas)
    nodes = []
    for emp in current_employees:
        emp_node = {
            "name": emp.full_name,
            "type": "employee",
            "position": position.name,
            "area": position.area.name,
            "photo": emp.photo_url,
            "id": emp.id,
            "company": emp.company.name if emp.company else "",
            "children": subordinates_nodes # Comparten los mismos subordinados
        }
        if not subordinates_nodes:
            del emp_node["children"]
            emp_node["value"] = 1
        nodes.append(emp_node)
    
    return nodes

async def get_people_data(db: AsyncSession) -> Dict[str, Any]:
    """Datos para el modo RED DE PERSONAS."""
    stmt = select(Position).options(
        selectinload(Position.employees).selectinload(Employee.company),
        selectinload(Position.area)
    )
    all_positions = (await db.execute(stmt)).scalars().all()
    
    # Cargos raíz (sin jefe)
    root_positions = [p for p in all_positions if p.parent_id is None]
    
    people_tree = []
    for root_pos in root_positions:
        people_tree.extend(build_people_tree(root_pos, all_positions))
        
    return {
        "name": settings.BUSINESS_NAME,
        "type": "root",
        "children": people_tree
    }

async def get_org_chart_data(db: AsyncSession, mode: str = "hierarchy") -> Dict[str, Any]:
    """Dispatcher para obtener los datos según el modo."""
    if mode == "structure":
        return await get_structure_data(db)
    elif mode == "people":
        return await get_people_data(db)
    return await get_hierarchy_data(db)