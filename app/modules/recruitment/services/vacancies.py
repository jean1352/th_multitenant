from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks
from sqlalchemy import desc, func, or_, select, case, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.auth.models import User
from app.modules.employees.models import Employee, EmployeeHistory, MovementType, EmployeePosition
from app.modules.notifications.service import send_email_notification
from app.modules.organization.models import Area, Position, Sede
from app.modules.recruitment import schemas
from app.modules.recruitment.business_calendar import add_business_days, get_holidays_set
from app.modules.recruitment.models import (
    ProcessStatus,
    RecruitmentAudit,
    RecruitmentProcess,
    Vacancy,
    VacancyStage,
    VacancyType,
    HiringReason
)
from app.modules.recruitment.services.audit import log_audit
from app.modules.recruitment.services.processes import get_process_detail
from app.core.config import settings


async def get_users_for_assignment(db: AsyncSession) -> List[User]:
    """Obtiene usuarios agrupados por sede y área para asignación."""
    stmt = (
        select(User)
        .join(User.area, isouter=True)
        .join(Area.sede, isouter=True)
        .options(
            selectinload(User.area).selectinload(Area.sede),
            selectinload(User.sede)
        )
        .order_by(Sede.name, Area.name, User.full_name)
    )
    return (await db.execute(stmt)).scalars().all()


async def get_recruiters(db: AsyncSession) -> List[User]:
    """Obtiene lista de reclutadores y managers para asignación."""
    from app.modules.auth.models import UserRole
    stmt = select(User).where(
        or_(
            User.role == UserRole.TH, 
            User.role == UserRole.MANAGER,
            User.role == UserRole.ADMIN
        )
    ).order_by(User.full_name)
    return (await db.execute(stmt)).scalars().all()


async def get_vacancy_counts(db: AsyncSession) -> Dict[str, int]:
    """Obtiene el conteo de vacantes por estado."""
    stmt = select(Vacancy.status, func.count(Vacancy.id)).group_by(Vacancy.status)
    result = await db.execute(stmt)
    
    counts = {row[0].value: row[1] for row in result}
    
    final_counts = {
        "open": counts.get("open", 0),
        "closed": counts.get("closed", 0),
        "cancelled": counts.get("cancelled", 0),
    }
    final_counts["all"] = sum(final_counts.values())
    
    return final_counts


async def get_vacancies_paginated(
    db: AsyncSession,
    page: int = 1,
    limit: int = 10,
    search: Optional[str] = None,
    status: Optional[str] = None,
    sede_id: Optional[int] = None,
    area_id: Optional[int] = None,
    sla_status: Optional[str] = None,
    scope: Optional[str] = "all", # 'all' | 'mine'
    current_user_id: Optional[int] = None,
    sort_by: Optional[str] = "created_at",
    sort_order: Optional[str] = "desc"
) -> Dict[str, Any]:
    """Obtiene lista paginada de vacantes con filtros avanzados y ordenamiento."""
    offset = (page - 1) * limit
    
    # Subquery para calcular el SLA total de cada vacante
    sla_subquery = (
        select(
            VacancyStage.vacancy_id,
            func.sum(VacancyStage.sla_days_snapshot).label("total_sla")
        )
        .group_by(VacancyStage.vacancy_id)
        .subquery()
    )

    query = (
        select(
            Vacancy,
            Area.name.label("area_name"),
            Sede.name.label("sede_name"),
            RecruitmentProcess.name.label("process_name"),
            HiringReason.name.label("hiring_reason_name"),
        )
        .join(Area, Vacancy.area_id == Area.id)
        .join(Sede, Area.sede_id == Sede.id)
        .join(RecruitmentProcess, Vacancy.process_id == RecruitmentProcess.id)
        .outerjoin(HiringReason, Vacancy.hiring_reason_id == HiringReason.id)
        .outerjoin(sla_subquery, Vacancy.id == sla_subquery.c.vacancy_id)
        .outerjoin(User, Vacancy.recruiter_id == User.id)
        .options(
            selectinload(Vacancy.stages).selectinload(VacancyStage.responsible),
            selectinload(Vacancy.position).selectinload(Position.parent),
            selectinload(Vacancy.position).selectinload(Position.area).selectinload(Area.sede),
            selectinload(Vacancy.hiring_reason),
            selectinload(Vacancy.recruiter),
            # CORRECCIÓN CRÍTICA: Carga profunda de área y sus relaciones anidadas
            # Vacancy -> Area -> Positions -> Parent (Esto causaba el MissingGreenlet)
            selectinload(Vacancy.area).options(
                selectinload(Area.sede),
                selectinload(Area.positions).selectinload(Position.parent),
                selectinload(Area.positions).selectinload(Position.area) # Backref safety
            )
        )
    )

    # Filtros
    if scope == "mine" and current_user_id:
        query = query.where(Vacancy.recruiter_id == current_user_id)

    if status and status != "all":
        query = query.where(Vacancy.status == status)
    
    if search:
        search_term = f"%{search}%"
        query = query.where(
            or_(
                Vacancy.title.ilike(search_term),
                Vacancy.description.ilike(search_term),
                Area.name.ilike(search_term),
                Sede.name.ilike(search_term),
            )
        )

    if sede_id:
        query = query.where(Sede.id == sede_id)
    
    if area_id:
        query = query.where(Area.id == area_id)

    if sla_status:
        days_elapsed_expr = func.extract(
            'day', 
            func.coalesce(Vacancy.closed_at, func.now()) - Vacancy.created_at
        )
        total_sla_expr = func.coalesce(sla_subquery.c.total_sla, 0)

        if sla_status == "ok":
            query = query.where(days_elapsed_expr <= total_sla_expr)
        elif sla_status == "overdue":
            query = query.where(days_elapsed_expr > total_sla_expr)

    # Conteo Total
    count_query = select(func.count()).select_from(query.subquery())
    total_items = await db.scalar(count_query) or 0

    # Ordenamiento
    order_column = Vacancy.created_at
    
    if sort_by == 'title': order_column = Vacancy.title
    elif sort_by == 'area': order_column = Area.name
    elif sort_by == 'recruiter': order_column = User.full_name
    elif sort_by == 'start_date': order_column = Vacancy.created_at
    elif sort_by == 'status': order_column = Vacancy.status
    elif sort_by == 'sla': order_column = func.coalesce(sla_subquery.c.total_sla, 0)

    if sort_order == 'asc':
        query = query.order_by(order_column.asc())
    else:
        query = query.order_by(order_column.desc())
        
    query = query.order_by(Vacancy.id.desc())

    # Paginación
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)

    vacancies = []
    for row in result:
        vac = row[0]
        # Asignamos atributos planos para compatibilidad con schemas antiguos si es necesario
        vac.area_name = row[1]
        vac.sede_name = row[2]
        vac.process_name = row[3]
        vacancies.append(vac)

    total_pages = (total_items + limit - 1) // limit
    
    return {
        "items": vacancies,
        "total": total_items,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    }


async def get_vacancy_by_id(db: AsyncSession, vacancy_id: int) -> Optional[Vacancy]:
    """
    Obtiene una vacante por ID con las relaciones necesarias cargadas para edición (API).
    """
    stmt = (
        select(Vacancy)
        .options(
            # Cargar Área, su Sede y sus Cargos (necesario para AreaRead)
            selectinload(Vacancy.area).options(
                selectinload(Area.sede),
                selectinload(Area.positions).selectinload(Position.parent) # FIX MissingGreenlet
            ),
            # Cargar Posición de la vacante
            selectinload(Vacancy.position).options(
                selectinload(Position.parent),
                selectinload(Position.area).selectinload(Area.sede)
            ),
            selectinload(Vacancy.stages).selectinload(VacancyStage.responsible),
            selectinload(Vacancy.hiring_reason),
            selectinload(Vacancy.recruiter)
        )
        .where(Vacancy.id == vacancy_id)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_vacancy_detail(
    db: AsyncSession, vacancy_id: int
) -> Optional[Vacancy]:
    """
    Obtiene el detalle completo de una vacante para la vista HTML.
    """
    stmt = (
        select(Vacancy)
        .options(
            # 1. Carga profunda del Área (Sede y Cargos son necesarios para AreaRead)
            selectinload(Vacancy.area).options(
                selectinload(Area.sede),
                selectinload(Area.positions).selectinload(Position.parent) # FIX MissingGreenlet
            ),

            # 2. Carga profunda del Cargo de la vacante
            selectinload(Vacancy.position).selectinload(Position.parent),
            selectinload(Vacancy.position).selectinload(Position.area).selectinload(Area.sede),

            # 3. Carga de Etapas y Responsables
            selectinload(Vacancy.stages).selectinload(VacancyStage.responsible),

            # 4. Carga de Auditoría y Usuarios
            selectinload(Vacancy.audits).selectinload(RecruitmentAudit.user),

            # 5. Otros catálogos
            selectinload(Vacancy.process),
            selectinload(Vacancy.hiring_reason),
            selectinload(Vacancy.recruiter)
        )
        .where(Vacancy.id == vacancy_id)
    )
    
    result = await db.execute(stmt)
    vac = result.scalar_one_or_none()
    
    if not vac:
        return None

    # Asignación manual de campos planos para compatibilidad con templates que no usan Pydantic
    if vac.area:
        vac.area_name = vac.area.name
        if vac.area.sede:
            vac.sede_name = vac.area.sede.name
            
    if vac.process:
        vac.process_name = vac.process.name
        
    return vac


async def create_vacancy(
    db: AsyncSession, vacancy_in: schemas.VacancyCreate, user_id: int
) -> Vacancy:
    """Crea una nueva vacante e instancia sus etapas con cálculo de SLA real."""
    process = await get_process_detail(db, vacancy_in.process_id)
    if not process:
        raise ValueError("El proceso seleccionado no existe")
    
    new_vacancy = Vacancy(
        title=vacancy_in.title,
        description=vacancy_in.description,
        area_id=vacancy_in.area_id,
        position_id=vacancy_in.position_id,
        process_id=vacancy_in.process_id,
        requester_id=user_id,
        recruiter_id=vacancy_in.recruiter_id,
        status=ProcessStatus.OPEN,
        vacancy_type=None,
        is_headcount_increase=vacancy_in.is_headcount_increase,
        hiring_reason_id=vacancy_in.hiring_reason_id
    )
    db.add(new_vacancy)
    await db.flush()
    
    await log_audit(db, new_vacancy.id, "CREATED", "Vacante creada", user_id)

    stages = []
    current_date = new_vacancy.created_at.date()
    holidays = await get_holidays_set(db, current_date)

    for config_stage in process.stages_config:
        deadline = await add_business_days(db, current_date, config_stage.sla_days, holidays)
        
        stage = VacancyStage(
            vacancy_id=new_vacancy.id,
            name=config_stage.name,
            owner=config_stage.owner,
            responsible_id=config_stage.responsible_id,
            sla_days_snapshot=config_stage.sla_days,
            order_index=config_stage.order_index,
            start_date=current_date,
            deadline_date=deadline,
        )
        stages.append(stage)
        current_date = deadline

    db.add_all(stages)
    await db.commit()
    
    # Recargar para devolver objeto completo
    return await get_vacancy_detail(db, new_vacancy.id)


async def update_vacancy(
    db: AsyncSession,
    vacancy_id: int,
    vac_in: schemas.VacancyUpdate,
    background_tasks: Optional[BackgroundTasks] = None,
    user_id: Optional[int] = None
) -> Optional[Vacancy]:
    """Actualiza una vacante y notifica si se cierra. Maneja contratación/promoción."""
    # Usamos get_vacancy_detail para asegurar que todo esté cargado al devolver
    vac = await get_vacancy_detail(db, vacancy_id)
    if not vac:
        return None

    update_data = vac_in.model_dump(exclude_unset=True)
    audit_details = []

    # --- LÓGICA DE CIERRE Y CONTRATACIÓN ---
    if "status" in update_data and update_data["status"] == ProcessStatus.CLOSED:
        
        vacancy_type = update_data.get("vacancy_type")
        if not vacancy_type:
            raise ValueError("Debe seleccionar el tipo de cobertura para cerrar la vacante.")
        
        start_date = update_data.get("start_date")
        if not start_date:
            raise ValueError("La fecha de inicio del colaborador es obligatoria.")

        target_position_id = update_data.get("position_id") or vac.position_id
        if not target_position_id:
            raise ValueError("La vacante debe tener un Cargo/Puesto asignado para realizar una contratación.")

        # NUEVO: Tipo de Contrato y Empresa
        contract_type_id = update_data.get("contract_type_id")
        company_id = update_data.get("company_id")

        if not company_id:
            raise ValueError("Debe seleccionar la Empresa (Razón Social) para cerrar la vacante.")

        candidate_info = ""

        # Contratación Externa
        if vacancy_type == VacancyType.EXTERNAL:
            if not update_data.get("candidate_name") or not update_data.get("candidate_document"):
                raise ValueError("Para contratación externa, nombre y documento son obligatorios.")
            
            full_name = update_data["candidate_name"].strip()
            parts = full_name.split(" ")
            first_name = parts[0]
            last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

            new_emp = Employee(
                first_name=first_name,
                last_name=last_name,
                full_name=full_name,
                document_id=update_data["candidate_document"],
                personal_email=update_data.get("candidate_email"),
                position_id=target_position_id,
                company_id=company_id, # Asignar empresa
                is_active=True
            )
            db.add(new_emp)
            await db.flush()
            
            # Crear Cargo Principal
            emp_pos = EmployeePosition(
                employee_id=new_emp.id,
                position_id=target_position_id,
                company_id=company_id, # Asignar empresa
                contract_type_id=contract_type_id, # Asignar contrato
                is_primary=True,
                start_date=start_date
            )
            db.add(emp_pos)

            history = EmployeeHistory(
                employee_id=new_emp.id,
                movement_type=MovementType.ENTRY,
                date=start_date,
                new_position_id=target_position_id,
                company_id=company_id, # Asignar empresa
                contract_type_id=contract_type_id, # Asignar contrato
                notes=f"Ingreso por vacante: {vac.title}"
            )
            db.add(history)
            candidate_info = f"Externo: {new_emp.full_name}"

        # Promoción Interna o Traslado
        elif vacancy_type in [VacancyType.INTERNAL, VacancyType.TRANSFER]:
            emp_id = update_data.get("selected_employee_id")
            if not emp_id:
                raise ValueError("Debe seleccionar un colaborador para promoción/traslado.")
            
            stmt_emp = select(Employee).options(selectinload(Employee.position_obj).selectinload(Position.area)).where(Employee.id == emp_id)
            emp = (await db.execute(stmt_emp)).scalar_one_or_none()
            if not emp:
                raise ValueError("Colaborador seleccionado no encontrado.")
            
            prev_pos_name = emp.position_obj.name if emp.position_obj else "Sin Cargo"
            prev_area_name = emp.position_obj.area.name if emp.position_obj and emp.position_obj.area else "Sin Área"

            mov_type = MovementType.PROMOTION if vacancy_type == VacancyType.INTERNAL else MovementType.TRANSFER

            # Cerrar cargo anterior
            await db.execute(update(EmployeePosition).where(
                EmployeePosition.employee_id == emp.id, 
                EmployeePosition.is_primary == True, 
                EmployeePosition.end_date.is_(None)
            ).values(end_date=start_date, is_primary=False))

            # Actualizar empresa del empleado si se seleccionó una nueva
            if company_id:
                emp.company_id = company_id

            # Crear nuevo cargo
            new_pos = EmployeePosition(
                employee_id=emp.id,
                position_id=target_position_id,
                company_id=company_id or emp.company_id, # Usa la nueva o mantiene la actual
                contract_type_id=contract_type_id, # Nuevo contrato
                is_primary=True,
                start_date=start_date
            )
            db.add(new_pos)

            history = EmployeeHistory(
                employee_id=emp.id,
                movement_type=mov_type,
                date=start_date,
                previous_position_name=prev_pos_name,
                previous_area_name=prev_area_name,
                new_position_id=target_position_id,
                company_id=company_id or emp.company_id,
                contract_type_id=contract_type_id, # Nuevo contrato
                notes=f"Movimiento por vacante: {vac.title}"
            )
            db.add(history)
            emp.position_id = target_position_id
            candidate_info = f"Interno: {emp.full_name}"

        if not vac.closed_at:
            vac.closed_at = datetime.now()
        
        vac.start_date = start_date
        audit_details.append(f"Vacante CERRADA. Tipo: {vacancy_type}. {candidate_info}")

        # Notificación HTML Moderna
        if vac.area and vac.area.responsible_email:
            clean_title = vac.title.replace("\n", " ").replace("\r", "")
            subject = f"✅ Vacante Cerrada: {clean_title}"
            
            # Mapeo de tipo para mostrar texto amigable
            type_map = {
                "external": "Contratación Externa",
                "internal": "Promoción Interna",
                "transfer": "Traslado"
            }
            readable_type = type_map.get(vacancy_type.value, vacancy_type.value)

            body = f"""
            <!DOCTYPE html>
            <html>
            <body style="font-family: 'Helvetica', Arial, sans-serif; line-height: 1.6; color: #333; background-color: #f4f4f4; margin: 0; padding: 20px;">
                <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <!-- Header -->
                    <div style="background-color: #003366; padding: 20px; text-align: center;">
                        <h2 style="color: #ffffff; margin: 0; font-size: 20px;">Proceso Finalizado</h2>
                    </div>
                    
                    <!-- Content -->
                    <div style="padding: 30px;">
                        <p style="margin-top: 0; color: #666; font-size: 14px;">
                            Se informa que el proceso de selección para la siguiente vacante ha concluido exitosamente:
                        </p>
                        
                        <h3 style="color: #003366; margin: 15px 0; font-size: 18px; border-bottom: 2px solid #f0f0f0; padding-bottom: 10px;">
                            {vac.title}
                        </h3>
                        
                        <table style="width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 14px;">
                            <tr>
                                <td style="padding: 10px 0; color: #666; border-bottom: 1px solid #eee; width: 40%;">Fecha de Cierre:</td>
                                <td style="padding: 10px 0; font-weight: 600; color: #333; border-bottom: 1px solid #eee;">{vac.closed_at.strftime('%d/%m/%Y')}</td>
                            </tr>
                            <tr>
                                <td style="padding: 10px 0; color: #666; border-bottom: 1px solid #eee;">Inicio Colaborador:</td>
                                <td style="padding: 10px 0; font-weight: 600; color: #333; border-bottom: 1px solid #eee;">{start_date.strftime('%d/%m/%Y')}</td>
                            </tr>
                            <tr>
                                <td style="padding: 10px 0; color: #666; border-bottom: 1px solid #eee;">Modalidad:</td>
                                <td style="padding: 10px 0; font-weight: 600; color: #333; border-bottom: 1px solid #eee;">
                                    <span style="background-color: #e0f2fe; color: #0369a1; padding: 4px 8px; border-radius: 4px; font-size: 12px;">
                                        {readable_type}
                                    </span>
                                </td>
                            </tr>
                        </table>

                        <div style="margin-top: 25px; padding: 15px; background-color: #f0fdf4; border-left: 4px solid #22c55e; border-radius: 4px;">
                            <p style="margin: 0; color: #166534; font-size: 13px;">
                                <strong>Estado:</strong> Cerrada Exitosamente
                            </p>
                        </div>
                    </div>
                    
                    <!-- Footer -->
                    <div style="background-color: #f8fafc; padding: 15px; text-align: center; border-top: 1px solid #e2e8f0;">
                        <p style="margin: 0; font-size: 12px; color: #94a3b8;">
                            Talento Humano UP
                            <br>
                            {settings.BUSINESS_NAME}
                        </p>
                    </div>
                </div>
            </body>
            </html>
            """
            
            await send_email_notification(
                db, vac.area.responsible_email, subject, body, background_tasks, is_html=True
            )

    # --- LÓGICA DE CANCELACIÓN ---
    elif "status" in update_data and update_data["status"] == ProcessStatus.CANCELLED:
        if not vac.closed_at:
            vac.closed_at = datetime.now()
        audit_details.append("Vacante CANCELADA")
        
        if vac.area and vac.area.responsible_email:
            subject = f"Vacante CANCELADA: {vac.title}"
            body = f"La vacante ha sido cancelada.\nObservaciones: {update_data.get('description', '')}"
            await send_email_notification(db, vac.area.responsible_email, subject, body, background_tasks)

    # Actualizar campos básicos
    valid_fields = Vacancy.__table__.columns.keys()
    for key, value in update_data.items():
        if key in valid_fields and getattr(vac, key) != value:
            if key not in ['status', 'closed_at', 'start_date', 'recruiter_id']:
                audit_details.append(f"Campo '{key}' modificado")
            setattr(vac, key, value)

    if audit_details:
        await log_audit(db, vac.id, "UPDATE", "; ".join(audit_details), user_id)

    await db.commit()
    # Devolver objeto actualizado con relaciones cargadas
    return await get_vacancy_detail(db, vacancy_id)


async def delete_vacancy(db: AsyncSession, vacancy_id: int) -> bool:
    """Elimina una vacante."""
    vac = await db.get(Vacancy, vacancy_id)
    if not vac:
        return False
    await db.delete(vac)
    await db.commit()
    return True


async def notify_vacancy_status(
    db: AsyncSession, 
    vacancy_id: int, 
    background_tasks: BackgroundTasks
) -> bool:
    """
    Genera un reporte HTML del estado actual de la vacante y lo envía
    al responsable del área.
    """
    # 1. Obtener datos completos
    vac = await get_vacancy_detail(db, vacancy_id)
    if not vac:
        return False
    
    # Asegurar carga de área para el email
    await db.refresh(vac, attribute_names=["area"])
    
    recipient = vac.area.responsible_email
    if not recipient:
        raise ValueError("El área no tiene un correo de responsable configurado.")

    # 2. Convertir a Schema para usar propiedades computadas (SLA status, days_elapsed)
    vac_dto = schemas.VacancyDetail.model_validate(vac)

    # 3. Construir HTML (Estilos Inline para Email)
    rows_html = ""
    for stage in vac_dto.stages:
        # Colores para badges
        status_color = "#10B981" if stage.end_date else "#F59E0B" # Verde o Amarillo
        status_text = "Completado" if stage.end_date else "Pendiente"
        
        sla_color = "#10B981" if stage.sla_status == 'ok' else "#EF4444" # Verde o Rojo
        sla_text = "En Tiempo" if stage.sla_status == 'ok' else "Retrasado"
        
        responsible_name = stage.responsible.full_name if stage.responsible else stage.owner.value

        rows_html += f"""
        <tr style="border-bottom: 1px solid #eee;">
            <td style="padding: 10px; color: #333;">{stage.name}</td>
            <td style="padding: 10px; color: #666;">{responsible_name}</td>
            <td style="padding: 10px; text-align: center;">{stage.start_date.strftime('%d/%m')}</td>
            <td style="padding: 10px; text-align: center;">{stage.end_date.strftime('%d/%m') if stage.end_date else '-'}</td>
            <td style="padding: 10px; text-align: center;">
                <span style="background-color: {status_color}20; color: {status_color}; padding: 3px 8px; border-radius: 10px; font-size: 11px; font-weight: bold;">
                    {status_text}
                </span>
            </td>
            <td style="padding: 10px; text-align: center;">
                <span style="color: {sla_color}; font-weight: bold; font-size: 11px;">
                    {sla_text}
                </span>
            </td>
        </tr>
        """

    # Colores globales
    global_sla_color = "#10B981" if vac_dto.global_sla_status == 'ok' else "#EF4444"
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: 'Helvetica', 'Arial', sans-serif; color: #333; line-height: 1.6; }}
            .container {{ max-width: 700px; margin: 0 auto; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; }}
            .header {{ background-color: #003366; color: white; padding: 20px; text-align: center; }}
            .content {{ padding: 20px; background-color: #ffffff; }}
            .info-grid {{ display: table; width: 100%; margin-bottom: 20px; background-color: #f8fafc; padding: 15px; border-radius: 6px; }}
            .info-item {{ display: table-cell; width: 33%; vertical-align: top; }}
            .label {{ font-size: 11px; text-transform: uppercase; color: #64748b; font-weight: bold; display: block; margin-bottom: 4px; }}
            .value {{ font-size: 14px; font-weight: 600; color: #1e293b; }}
            table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
            th {{ text-align: left; background-color: #f1f5f9; padding: 10px; color: #475569; font-weight: 600; font-size: 11px; text-transform: uppercase; }}
            .footer {{ background-color: #f8fafc; padding: 15px; text-align: center; font-size: 11px; color: #94a3b8; border-top: 1px solid #e5e7eb; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2 style="margin:0;">Reporte de Estado de Vacante</h2>
                <p style="margin:5px 0 0 0; font-size: 14px; opacity: 0.9;">{settings.BUSINESS_NAME} - Talento Humano</p>
            </div>
            
            <div class="content">
                <p>Estimado responsable,</p>
                <p>A continuación se detalla el avance actual del proceso de selección para la vacante solicitada.</p>
                
                <div class="info-grid">
                    <div class="info-item">
                        <span class="label">Vacante</span>
                        <span class="value">{vac.title}</span>
                    </div>
                    <div class="info-item">
                        <span class="label">Área / Sede</span>
                        <span class="value">{vac.area_name} ({vac.sede_name})</span>
                    </div>
                    <div class="info-item">
                        <span class="label">Estado Global</span>
                        <span class="value" style="color: {global_sla_color};">{vac_dto.total_days_elapsed} / {vac_dto.total_sla_days} días</span>
                    </div>
                </div>

                <h3 style="color: #003366; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; margin-top: 0;">Detalle de Etapas</h3>
                
                <table>
                    <thead>
                        <tr>
                            <th>Etapa</th>
                            <th>Responsable</th>
                            <th style="text-align: center;">Inicio</th>
                            <th style="text-align: center;">Fin</th>
                            <th style="text-align: center;">Estado</th>
                            <th style="text-align: center;">SLA</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>
                
                <p style="margin-top: 20px; font-size: 13px; color: #666;">
                    Progreso total: <strong>{vac_dto.progress_percent}%</strong>
                </p>
            </div>
            
            <div class="footer">
                Este es un correo automático generado por el sistema de Talento Humano.<br>
                &copy; {datetime.now().year} {settings.BUSINESS_NAME}.
            </div>
        </div>
    </body>
    </html>
    """

    # 4. Enviar Correo (SANITIZADO)
    clean_title = vac.title.replace("\n", " ").replace("\r", "").strip()
    subject = f"📊 Estado de Vacante: {clean_title}"
    
    await send_email_notification(
        db, recipient, subject, html_content, background_tasks, is_html=True
    )
    
    return True