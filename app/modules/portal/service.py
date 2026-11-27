"""
Lógica de negocio para el Portal del Colaborador:
- Jerarquía de líderes (colaboradores estrictamente debajo en el organigrama).
- Solicitudes formales de vacaciones (creación, cancelación, aprobación/rechazo con motivo y notificaciones).
- Consultas de área para líderes (solicitudes pendientes, reclutamientos, eventos y capacitaciones, legajo de subordinados).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.tenants import get_current_tenant, get_tenant_base_url
from app.modules.auth.models import User, UserRole
from app.modules.benefits.models import (
    BenefitRequest,
    BenefitRequestItem,
    EmployeeBenefit,
)
from app.modules.calendar.models import (
    CalendarEvent,
    EventEnrollment,
)
from app.modules.employees.models import (
    EmergencyContact,
    Employee,
    EmployeeHistory,
    EmployeePosition,
)
from app.modules.notifications.service import send_email_notification
from app.modules.organization.models import Area, Position, Sede
from app.modules.portal import schemas
from app.modules.portal.models import VacationRequest
from app.modules.recruitment.business_calendar import get_holidays_set
from app.modules.recruitment.models import Vacancy, VacancyStage
from app.modules.recruitment.schemas import VacancyRead
from app.modules.trainings.models import (
    Training,
    TrainingEnrollment,
)


async def get_employee_active_position_ids(
    db: AsyncSession, employee: Employee
) -> Set[int]:
    """Obtiene todos los IDs de cargos activos (principal + secundarios) de un colaborador."""
    pos_ids: Set[int] = set()
    if employee.position_id:
        pos_ids.add(employee.position_id)

    stmt = select(EmployeePosition.position_id).where(
        EmployeePosition.employee_id == employee.id,
        EmployeePosition.end_date.is_(None),
    )
    rows = (await db.execute(stmt)).scalars().all()
    for pid in rows:
        if pid:
            pos_ids.add(pid)
    return pos_ids


async def get_leader_context(
    db: AsyncSession,
    employee: Optional[Employee],
    user: Optional[User] = None,
) -> Dict[str, Any]:
    """
    Calcula el contexto jerárquico del colaborador logueado.
    Solo incluye cargos y colaboradores estrictamente DEBAJO del líder en Position.parent_id.
    """
    empty_ctx = {
        "is_leader": False,
        "leader_position_ids": set(),
        "direct_position_ids": set(),
        "subordinate_position_ids": set(),
        "subordinate_employee_ids": set(),
        "direct_employee_ids": set(),
        "leader_area_ids": set(),
        "subordinates": [],
        "pending_vacations_count": 0,
        "active_vacation_emp_ids": set(),
    }
    if not employee:
        return empty_ctx

    leader_pos_ids = await get_employee_active_position_ids(db, employee)

    all_positions = (
        await db.execute(
            select(Position).options(selectinload(Position.area).selectinload(Area.sede))
        )
    ).scalars().all()
    pos_map: Dict[int, Position] = {p.id: p for p in all_positions}

    children_by_parent: Dict[int, List[Position]] = {}
    for p in all_positions:
        if p.parent_id is not None:
            children_by_parent.setdefault(p.parent_id, []).append(p)

    direct_pos_ids: Set[int] = set()
    for lpid in leader_pos_ids:
        for child in children_by_parent.get(lpid, []):
            if child.id not in leader_pos_ids:
                direct_pos_ids.add(child.id)

    subordinate_pos_ids: Set[int] = set()
    queue = list(direct_pos_ids)
    while queue:
        curr_id = queue.pop(0)
        if curr_id in subordinate_pos_ids or curr_id in leader_pos_ids:
            continue
        subordinate_pos_ids.add(curr_id)
        for child in children_by_parent.get(curr_id, []):
            if child.id not in subordinate_pos_ids and child.id not in leader_pos_ids:
                queue.append(child.id)

    leader_area_ids: Set[int] = set()
    for pid in leader_pos_ids | subordinate_pos_ids:
        pos_obj = pos_map.get(pid)
        if pos_obj and pos_obj.area_id:
            leader_area_ids.add(pos_obj.area_id)
    if user and user.area_id:
        leader_area_ids.add(user.area_id)

    subordinates: List[Employee] = []
    subordinate_emp_ids: Set[int] = set()
    direct_emp_ids: Set[int] = set()

    if subordinate_pos_ids:
        active_ep_subq = (
            select(EmployeePosition.employee_id)
            .where(
                EmployeePosition.end_date.is_(None),
                EmployeePosition.position_id.in_(subordinate_pos_ids),
            )
            .scalar_subquery()
        )
        stmt_emps = (
            select(Employee)
            .options(
                selectinload(Employee.position_obj)
                .selectinload(Position.area)
                .selectinload(Area.sede),
                selectinload(Employee.position_obj).selectinload(Position.parent),
                selectinload(Employee.company),
                selectinload(Employee.positions_history).selectinload(
                    EmployeePosition.position
                ),
            )
            .where(
                Employee.is_active == True,
                Employee.id != employee.id,
                or_(
                    Employee.position_id.in_(subordinate_pos_ids),
                    Employee.id.in_(active_ep_subq),
                ),
            )
            .order_by(Employee.full_name)
        )
        subordinates = (await db.execute(stmt_emps)).scalars().all()
        for sub in subordinates:
            subordinate_emp_ids.add(sub.id)
            is_direct = sub.position_id in direct_pos_ids or any(
                ep.end_date is None and ep.position_id in direct_pos_ids
                for ep in sub.positions_history
            )
            if is_direct:
                direct_emp_ids.add(sub.id)

    has_leader_position = any(
        pos_map.get(pid) and pos_map[pid].is_leader for pid in leader_pos_ids
    )
    is_leader = bool(
        has_leader_position
        or len(subordinate_pos_ids) > 0
        or (user is not None and user.role == UserRole.MANAGER)
    )

    pending_vacations_count = 0
    active_vacation_emp_ids: Set[int] = set()
    if subordinate_emp_ids:
        pending_vacations_count = (
            await db.scalar(
                select(func.count(VacationRequest.id)).where(
                    VacationRequest.employee_id.in_(subordinate_emp_ids),
                    VacationRequest.status == "Pendiente",
                )
            )
            or 0
        )
        today = date.today()
        active_vac_rows = (
            await db.execute(
                select(VacationRequest.employee_id).where(
                    VacationRequest.employee_id.in_(subordinate_emp_ids),
                    VacationRequest.status == "Aprobada",
                    VacationRequest.start_date <= today,
                    VacationRequest.end_date >= today,
                )
            )
        ).scalars().all()
        active_vacation_emp_ids = set(active_vac_rows)

    return {
        "is_leader": is_leader,
        "leader_position_ids": leader_pos_ids,
        "direct_position_ids": direct_pos_ids,
        "subordinate_position_ids": subordinate_pos_ids,
        "subordinate_employee_ids": subordinate_emp_ids,
        "direct_employee_ids": direct_emp_ids,
        "leader_area_ids": leader_area_ids,
        "subordinates": subordinates,
        "pending_vacations_count": pending_vacations_count,
        "active_vacation_emp_ids": active_vacation_emp_ids,
    }


async def count_inclusive_business_days(
    db: AsyncSession, start_date: date, end_date: date
) -> int:
    """Cuenta los días hábiles inclusivos entre start_date y end_date."""
    if end_date < start_date:
        return 0
    holidays = await get_holidays_set(db, start_date, years_ahead=2)
    total = 0
    current = start_date
    while current <= end_date:
        if current.weekday() < 5 and current not in holidays:
            total += 1
        current += timedelta(days=1)
    return total


async def get_employee_email(db: AsyncSession, emp: Employee) -> Optional[str]:
    """Obtiene el mejor correo disponible del colaborador."""
    if emp.institutional_email and emp.institutional_email.strip():
        return emp.institutional_email.strip()
    user_email = await db.scalar(
        select(User.email).where(User.employee_id == emp.id, User.is_active == True)
    )
    if user_email and user_email.strip():
        return user_email.strip()
    if emp.personal_email and emp.personal_email.strip():
        return emp.personal_email.strip()
    return None


async def get_employee_superiors_and_emails(
    db: AsyncSession, employee: Employee
) -> Tuple[Optional[Employee], List[Employee], List[str]]:
    """
    Identifica al superior inmediato (subiendo por Position.parent_id hasta hallar un colaborador activo,
    o líder del área como respaldo) y recopila sus correos + el correo del encargado del área.
    """
    all_positions = (
        await db.execute(select(Position).options(selectinload(Position.area)))
    ).scalars().all()
    pos_map = {p.id: p for p in all_positions}

    current_pos = pos_map.get(employee.position_id)
    visited: Set[int] = set()
    superiors: List[Employee] = []

    parent_id = current_pos.parent_id if current_pos else None
    while parent_id and parent_id not in visited:
        visited.add(parent_id)
        active_ep_subq = (
            select(EmployeePosition.employee_id)
            .where(
                EmployeePosition.end_date.is_(None),
                EmployeePosition.position_id == parent_id,
            )
            .scalar_subquery()
        )
        stmt = (
            select(Employee)
            .options(selectinload(Employee.position_obj))
            .where(
                Employee.is_active == True,
                Employee.id != employee.id,
                or_(
                    Employee.position_id == parent_id,
                    Employee.id.in_(active_ep_subq),
                ),
            )
            .order_by(Employee.full_name)
        )
        found = (await db.execute(stmt)).scalars().all()
        if found:
            superiors = found
            break
        parent_pos = pos_map.get(parent_id)
        parent_id = parent_pos.parent_id if parent_pos else None

    if not superiors and current_pos and current_pos.area_id:
        area_leader_pos_ids = [
            p.id
            for p in all_positions
            if p.area_id == current_pos.area_id
            and p.is_leader
            and p.id != current_pos.id
        ]
        if area_leader_pos_ids:
            stmt = (
                select(Employee)
                .options(selectinload(Employee.position_obj))
                .where(
                    Employee.is_active == True,
                    Employee.id != employee.id,
                    Employee.position_id.in_(area_leader_pos_ids),
                )
                .order_by(Employee.full_name)
            )
            superiors = (await db.execute(stmt)).scalars().all()

    requester_email = await get_employee_email(db, employee)
    emails: List[str] = []
    seen_emails: Set[str] = set()

    for sup in superiors:
        sup_email = await get_employee_email(db, sup)
        if sup_email and sup_email.lower() not in seen_emails:
            seen_emails.add(sup_email.lower())
            emails.append(sup_email)

    area_resp_email = (
        current_pos.area.responsible_email.strip()
        if current_pos and current_pos.area and current_pos.area.responsible_email
        else None
    )
    if area_resp_email and area_resp_email.lower() not in seen_emails:
        if not (
            requester_email
            and area_resp_email.lower() == requester_email.lower()
            and len(emails) > 0
        ):
            seen_emails.add(area_resp_email.lower())
            emails.append(area_resp_email)

    primary_sup = superiors[0] if superiors else None
    return primary_sup, superiors, emails


async def list_my_vacation_requests(
    db: AsyncSession, employee_id: int
) -> List[VacationRequest]:
    stmt = (
        select(VacationRequest)
        .options(
            selectinload(VacationRequest.employee),
            selectinload(VacationRequest.assigned_approver),
            selectinload(VacationRequest.approver),
            selectinload(VacationRequest.reviewer_user),
        )
        .where(VacationRequest.employee_id == employee_id)
        .order_by(desc(VacationRequest.created_at))
    )
    return (await db.execute(stmt)).scalars().all()


async def list_leader_vacation_requests(
    db: AsyncSession,
    subordinate_employee_ids: Set[int],
    status_filter: Optional[str] = None,
) -> List[VacationRequest]:
    if not subordinate_employee_ids:
        return []
    stmt = (
        select(VacationRequest)
        .options(
            selectinload(VacationRequest.employee)
            .selectinload(Employee.position_obj)
            .selectinload(Position.area),
            selectinload(VacationRequest.assigned_approver),
            selectinload(VacationRequest.approver),
            selectinload(VacationRequest.reviewer_user),
        )
        .where(VacationRequest.employee_id.in_(subordinate_employee_ids))
    )
    if status_filter:
        stmt = stmt.where(VacationRequest.status == status_filter)
    stmt = stmt.order_by(desc(VacationRequest.created_at))
    return (await db.execute(stmt)).scalars().all()


async def get_vacation_request_by_id(
    db: AsyncSession, req_id: int
) -> Optional[VacationRequest]:
    """Obtiene una solicitud de vacaciones con sus relaciones cargadas para serialización."""
    stmt = (
        select(VacationRequest)
        .options(
            selectinload(VacationRequest.employee)
            .selectinload(Employee.position_obj)
            .selectinload(Position.area),
            selectinload(VacationRequest.assigned_approver),
            selectinload(VacationRequest.approver),
            selectinload(VacationRequest.reviewer_user),
        )
        .where(VacationRequest.id == req_id)
        .execution_options(populate_existing=True)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def create_vacation_request(
    db: AsyncSession,
    employee: Employee,
    data: schemas.VacationRequestCreate,
    background_tasks: Optional[BackgroundTasks] = None,
) -> VacationRequest:
    overlap_stmt = select(VacationRequest).where(
        VacationRequest.employee_id == employee.id,
        VacationRequest.status.in_(["Pendiente", "Aprobada"]),
        VacationRequest.start_date <= data.end_date,
        VacationRequest.end_date >= data.start_date,
    )
    overlapping = (await db.execute(overlap_stmt)).scalar_one_or_none()
    if overlapping:
        raise HTTPException(
            400,
            f"Ya existe una solicitud {overlapping.status.lower()} ({overlapping.request_code}) que se superpone con esas fechas.",
        )

    days_requested = (data.end_date - data.start_date).days + 1
    business_days = await count_inclusive_business_days(
        db, data.start_date, data.end_date
    )

    max_id = (await db.execute(select(func.max(VacationRequest.id)))).scalar() or 0
    request_code = f"VAC{max_id + 1:03d}"

    primary_sup, _, recipient_emails = await get_employee_superiors_and_emails(
        db, employee
    )

    vac_req = VacationRequest(
        request_code=request_code,
        employee_id=employee.id,
        start_date=data.start_date,
        end_date=data.end_date,
        days_requested=days_requested,
        business_days=business_days,
        reason=(data.reason or "").strip() or None,
        status="Pendiente",
        assigned_approver_id=primary_sup.id if primary_sup else None,
    )
    db.add(vac_req)
    await db.flush()

    created = await get_vacation_request_by_id(db, vac_req.id)
    pos_name = employee.position_obj.name if employee.position_obj else "-"
    area_name = (
        employee.position_obj.area.name
        if employee.position_obj and employee.position_obj.area
        else "-"
    )

    await db.commit()

    if recipient_emails:
        tenant = get_current_tenant()
        business_name = tenant.name if tenant else settings.BUSINESS_NAME
        portal_leader_url = f"{get_tenant_base_url()}/portal/leader"
        reason_html = (
            f"<tr><td style='padding:8px 0;color:#666;border-bottom:1px solid #eee;'>Motivo:</td>"
            f"<td style='padding:8px 0;color:#333;border-bottom:1px solid #eee;'>{created.reason}</td></tr>"
            if created.reason
            else ""
        )

        subject = f"Nueva Solicitud de Vacaciones ({request_code}): {employee.full_name}"
        body = (
            f"<div style=\"font-family:Arial,sans-serif;max-width:600px;margin:0 auto;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;\">"
            f"<div style=\"background:#003366;color:#fff;padding:18px;text-align:center;\">"
            f"<h2 style=\"margin:0;font-size:19px;\">Solicitud Formal de Vacaciones</h2>"
            f"<p style=\"margin:4px 0 0;font-size:12px;opacity:.85;\">{business_name}</p></div>"
            f"<div style=\"padding:24px;\"><p>El colaborador <strong>{employee.full_name}</strong> registro una solicitud de vacaciones:</p>"
            f"<table style=\"width:100%;border-collapse:collapse;font-size:14px;margin:16px 0;\">"
            f"<tr><td style=\"padding:8px 0;color:#666;border-bottom:1px solid #eee;\">Codigo:</td><td style=\"padding:8px 0;font-weight:bold;color:#003366;border-bottom:1px solid #eee;\">{request_code}</td></tr>"
            f"<tr><td style=\"padding:8px 0;color:#666;border-bottom:1px solid #eee;\">Cargo / Area:</td><td style=\"padding:8px 0;border-bottom:1px solid #eee;\">{pos_name} &bull; {area_name}</td></tr>"
            f"<tr><td style=\"padding:8px 0;color:#666;border-bottom:1px solid #eee;\">Desde:</td><td style=\"padding:8px 0;font-weight:bold;border-bottom:1px solid #eee;\">{created.start_date.strftime('%d/%m/%Y')}</td></tr>"
            f"<tr><td style=\"padding:8px 0;color:#666;border-bottom:1px solid #eee;\">Hasta:</td><td style=\"padding:8px 0;font-weight:bold;border-bottom:1px solid #eee;\">{created.end_date.strftime('%d/%m/%Y')}</td></tr>"
            f"<tr><td style=\"padding:8px 0;color:#666;border-bottom:1px solid #eee;\">Duracion:</td><td style=\"padding:8px 0;font-weight:600;border-bottom:1px solid #eee;\">{days_requested} dias calendario ({business_days} habiles)</td></tr>"
            f"{reason_html}</table>"
            f"<div style=\"text-align:center;margin:24px 0 8px;\">"
            f"<a href=\"{portal_leader_url}\" style=\"background:#003366;color:#fff;padding:11px 22px;text-decoration:none;border-radius:6px;font-weight:bold;font-size:14px;display:inline-block;\">Revisar y Responder en el Portal</a>"
            f"</div></div></div>"
        )
        await send_email_notification(
            db,
            ", ".join(recipient_emails),
            subject,
            body,
            background_tasks=background_tasks,
            is_html=True,
        )

    return created


async def cancel_vacation_request(
    db: AsyncSession, employee: Employee, req_id: int
) -> VacationRequest:
    vac_req = await db.get(VacationRequest, req_id)
    if not vac_req or vac_req.employee_id != employee.id:
        raise HTTPException(404, "Solicitud de vacaciones no encontrada.")
    if vac_req.status != "Pendiente":
        raise HTTPException(
            400, "Solo puedes cancelar solicitudes que estén en estado Pendiente."
        )
    vac_req.status = "Cancelada"
    await db.flush()
    cancelled = await get_vacation_request_by_id(db, vac_req.id)
    await db.commit()
    return cancelled


async def review_vacation_request(
    db: AsyncSession,
    reviewer_emp: Optional[Employee],
    reviewer_user: User,
    req_id: int,
    data: schemas.VacationRequestDecision,
    background_tasks: Optional[BackgroundTasks] = None,
) -> VacationRequest:
    stmt = (
        select(VacationRequest)
        .options(
            selectinload(VacationRequest.employee)
            .selectinload(Employee.position_obj)
            .selectinload(Position.area),
            selectinload(VacationRequest.assigned_approver),
        )
        .where(VacationRequest.id == req_id)
    )
    vac_req = (await db.execute(stmt)).scalar_one_or_none()
    if not vac_req:
        raise HTTPException(404, "Solicitud de vacaciones no encontrada.")

    if reviewer_emp and vac_req.employee_id == reviewer_emp.id:
        raise HTTPException(
            403, "No puedes aprobar o rechazar tu propia solicitud de vacaciones."
        )

    leader_ctx = await get_leader_context(db, reviewer_emp, reviewer_user)
    is_subordinate = vac_req.employee_id in leader_ctx["subordinate_employee_ids"]
    is_assigned_approver = (
        reviewer_emp is not None and vac_req.assigned_approver_id == reviewer_emp.id
    )
    is_system_admin = reviewer_user.role == UserRole.ADMIN

    if not (is_subordinate or is_assigned_approver or is_system_admin):
        raise HTTPException(
            403,
            "No tienes permisos para aprobar o rechazar solicitudes de este colaborador.",
        )

    if vac_req.status != "Pendiente":
        raise HTTPException(
            400, f"Esta solicitud ya fue procesada (estado actual: {vac_req.status})."
        )

    vac_req.status = data.status
    vac_req.decision_reason = data.decision_reason
    vac_req.approver_id = reviewer_emp.id if reviewer_emp else None
    vac_req.reviewer_user_id = reviewer_user.id
    vac_req.reviewed_at = datetime.now()

    await db.flush()
    updated = await get_vacation_request_by_id(db, vac_req.id)

    target_emp = updated.employee
    emp_email = await get_employee_email(db, target_emp)
    await db.commit()

    if emp_email:
        tenant = get_current_tenant()
        business_name = tenant.name if tenant else settings.BUSINESS_NAME
        vacations_url = f"{get_tenant_base_url()}/portal/vacations"

        is_approved = data.status == "Aprobada"
        badge_bg = "#dcfce7" if is_approved else "#fee2e2"
        badge_color = "#166534" if is_approved else "#991b1b"
        reviewer_name = (
            reviewer_emp.full_name if reviewer_emp else reviewer_user.full_name
        )
        reason_row = (
            f"<tr><td style='padding:8px 0;color:#666;border-bottom:1px solid #eee;'>Motivo / Observaciones:</td>"
            f"<td style='padding:8px 0;color:#333;border-bottom:1px solid #eee;'>{updated.decision_reason}</td></tr>"
            if updated.decision_reason
            else ""
        )

        subject = f"Solicitud de Vacaciones {data.status} ({updated.request_code})"
        body = (
            f"<div style=\"font-family:Arial,sans-serif;max-width:600px;margin:0 auto;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;\">"
            f"<div style=\"background:#003366;color:#fff;padding:18px;text-align:center;\">"
            f"<h2 style=\"margin:0;font-size:19px;\">Resolucion de Vacaciones</h2>"
            f"<p style=\"margin:4px 0 0;font-size:12px;opacity:.85;\">{business_name}</p></div>"
            f"<div style=\"padding:24px;\"><p>Hola <strong>{target_emp.full_name}</strong>,</p>"
            f"<p>Tu solicitud de vacaciones <strong>{updated.request_code}</strong> fue revisada:</p>"
            f"<div style=\"margin:14px 0;padding:10px;background:{badge_bg};color:{badge_color};border-radius:6px;font-weight:bold;text-align:center;\">Estado: {data.status.upper()}</div>"
            f"<table style=\"width:100%;border-collapse:collapse;font-size:14px;margin:16px 0;\">"
            f"<tr><td style=\"padding:8px 0;color:#666;border-bottom:1px solid #eee;\">Periodo:</td><td style=\"padding:8px 0;font-weight:bold;border-bottom:1px solid #eee;\">{updated.start_date.strftime('%d/%m/%Y')} al {updated.end_date.strftime('%d/%m/%Y')} ({updated.days_requested} dias)</td></tr>"
            f"<tr><td style=\"padding:8px 0;color:#666;border-bottom:1px solid #eee;\">Revisado por:</td><td style=\"padding:8px 0;font-weight:600;border-bottom:1px solid #eee;\">{reviewer_name}</td></tr>"
            f"{reason_row}</table>"
            f"<div style=\"text-align:center;margin:24px 0 8px;\">"
            f"<a href=\"{vacations_url}\" style=\"background:#003366;color:#fff;padding:11px 22px;text-decoration:none;border-radius:6px;font-weight:bold;font-size:14px;display:inline-block;\">Ver Mis Solicitudes</a>"
            f"</div></div></div>"
        )
        await send_email_notification(
            db,
            emp_email,
            subject,
            body,
            background_tasks=background_tasks,
            is_html=True,
        )

    return updated


async def get_area_pending_benefit_requests(
    db: AsyncSession, subordinate_emp_ids: Set[int]
) -> List[BenefitRequest]:
    """Obtiene solicitudes de beneficios pendientes de colaboradores a cargo del líder."""
    if not subordinate_emp_ids:
        return []
    stmt = (
        select(BenefitRequest)
        .options(
            selectinload(BenefitRequest.employee)
            .selectinload(Employee.position_obj)
            .selectinload(Position.area),
            selectinload(BenefitRequest.requester),
            selectinload(BenefitRequest.request_type),
            selectinload(BenefitRequest.grant_reason),
            selectinload(BenefitRequest.items).selectinload(
                BenefitRequestItem.benefit_type
            ),
        )
        .where(
            BenefitRequest.employee_id.in_(subordinate_emp_ids),
            BenefitRequest.status == "Pendiente",
        )
        .order_by(desc(BenefitRequest.created_at))
    )
    return (await db.execute(stmt)).scalars().all()


async def get_area_vacancies_status(
    db: AsyncSession, leader_area_ids: Set[int]
) -> List[Dict[str, Any]]:
    """Obtiene el estado de los reclutamientos (vacantes) de las áreas del líder."""
    if not leader_area_ids:
        return []
    from app.modules.recruitment.business_calendar import refresh_holidays_cache

    await refresh_holidays_cache(db)
    stmt = (
        select(Vacancy)
        .options(
            selectinload(Vacancy.area).selectinload(Area.sede),
            selectinload(Vacancy.area)
            .selectinload(Area.positions)
            .selectinload(Position.parent),
            selectinload(Vacancy.position).selectinload(Position.parent),
            selectinload(Vacancy.position)
            .selectinload(Position.area)
            .selectinload(Area.sede),
            selectinload(Vacancy.stages).selectinload(VacancyStage.responsible),
            selectinload(Vacancy.hiring_reason),
            selectinload(Vacancy.recruiter),
            selectinload(Vacancy.process),
        )
        .where(Vacancy.area_id.in_(leader_area_ids))
        .order_by(desc(Vacancy.created_at))
    )
    vacancies = (await db.execute(stmt)).scalars().all()
    result = []
    for v in vacancies:
        v.area_name = v.area.name if v.area else None
        v.sede_name = v.area.sede.name if v.area and v.area.sede else None
        v.process_name = v.process.name if v.process else None
        dto = VacancyRead.model_validate(v).model_dump()
        stages = dto.get("stages") or []
        completed = len([s for s in stages if s.get("end_date") is not None])
        dto["progress_percent"] = int((completed / len(stages)) * 100) if stages else 0
        current_stage = next((s for s in stages if not s.get("end_date")), None)
        dto["current_stage"] = current_stage
        result.append(dto)
    return result


async def get_team_events_participation(
    db: AsyncSession, subordinate_emp_ids: Set[int]
) -> List[EventEnrollment]:
    """Obtiene la participación en eventos de los colaboradores a cargo."""
    if not subordinate_emp_ids:
        return []
    stmt = (
        select(EventEnrollment)
        .join(CalendarEvent)
        .options(
            selectinload(EventEnrollment.event).selectinload(CalendarEvent.event_type),
            selectinload(EventEnrollment.employee)
            .selectinload(Employee.position_obj)
            .selectinload(Position.area),
        )
        .where(EventEnrollment.employee_id.in_(subordinate_emp_ids))
        .order_by(desc(CalendarEvent.date))
        .limit(100)
    )
    return (await db.execute(stmt)).scalars().all()


async def get_team_trainings_participation(
    db: AsyncSession, subordinate_emp_ids: Set[int]
) -> List[TrainingEnrollment]:
    """Obtiene la participación en capacitaciones de los colaboradores a cargo."""
    if not subordinate_emp_ids:
        return []
    stmt = (
        select(TrainingEnrollment)
        .join(TrainingEnrollment.training)
        .options(
            selectinload(TrainingEnrollment.training),
            selectinload(TrainingEnrollment.employee)
            .selectinload(Employee.position_obj)
            .selectinload(Position.area),
        )
        .where(TrainingEnrollment.employee_id.in_(subordinate_emp_ids))
        .order_by(desc(Training.start_date))
        .limit(100)
    )
    return (await db.execute(stmt)).scalars().all()


async def get_subordinate_employee_detail(
    db: AsyncSession,
    leader_ctx: Dict[str, Any],
    target_emp_id: int,
) -> Optional[Dict[str, Any]]:
    """
    Obtiene el legajo completo de un colaborador SOLO si está estrictamente debajo del líder.
    """
    if target_emp_id not in leader_ctx["subordinate_employee_ids"]:
        return None

    stmt = (
        select(Employee)
        .options(
            selectinload(Employee.position_obj)
            .selectinload(Position.area)
            .selectinload(Area.sede),
            selectinload(Employee.position_obj).selectinload(Position.parent),
            selectinload(Employee.company),
            selectinload(Employee.positions_history)
            .selectinload(EmployeePosition.position)
            .selectinload(Position.area)
            .selectinload(Area.sede),
            selectinload(Employee.positions_history).selectinload(
                EmployeePosition.company
            ),
            selectinload(Employee.positions_history).selectinload(
                EmployeePosition.contract_type
            ),
            selectinload(Employee.positions_history).selectinload(
                EmployeePosition.working_day_type
            ),
            selectinload(Employee.positions_history).selectinload(
                EmployeePosition.probation_duration
            ),
            selectinload(Employee.positions_history).selectinload(
                EmployeePosition.probation_stages
            ),
            selectinload(Employee.trainings).selectinload(TrainingEnrollment.training),
            selectinload(Employee.emergency_contacts).selectinload(
                EmergencyContact.relationship
            ),
            selectinload(Employee.history)
            .selectinload(EmployeeHistory.new_position)
            .selectinload(Position.area),
            selectinload(Employee.history).selectinload(EmployeeHistory.company),
            selectinload(Employee.history).selectinload(EmployeeHistory.contract_type),
            selectinload(Employee.documents),
            selectinload(Employee.benefits).selectinload(EmployeeBenefit.benefit_type),
            selectinload(Employee.sanctions),
            selectinload(Employee.recognitions),
            selectinload(Employee.dietary_restrictions),
        )
        .where(Employee.id == target_emp_id)
    )
    emp = (await db.execute(stmt)).scalar_one_or_none()
    if not emp:
        return None

    events_stmt = (
        select(EventEnrollment)
        .join(CalendarEvent)
        .options(
            selectinload(EventEnrollment.event).selectinload(CalendarEvent.event_type)
        )
        .where(EventEnrollment.employee_id == target_emp_id)
        .order_by(desc(CalendarEvent.date))
    )
    events = (await db.execute(events_stmt)).scalars().all()
    vacations = await list_my_vacation_requests(db, target_emp_id)

    return {
        "employee": emp,
        "events": events,
        "vacations": vacations,
        "is_direct": target_emp_id in leader_ctx["direct_employee_ids"],
    }


async def get_leader_hierarchy_tree(
    db: AsyncSession,
    leader_emp: Employee,
    leader_ctx: Dict[str, Any],
    mode: str = "people",
) -> Dict[str, Any]:
    """
    Construye el árbol jerárquico D3.js enraizado en el Líder actual,
    mostrando únicamente posiciones y colaboradores estrictamente debajo de él/ella.
    """
    allowed_pos_ids = (
        leader_ctx["leader_position_ids"] | leader_ctx["subordinate_position_ids"]
    )
    stmt = (
        select(Position)
        .options(
            selectinload(Position.area).selectinload(Area.sede),
            selectinload(Position.employees).selectinload(Employee.company),
        )
        .where(Position.id.in_(allowed_pos_ids))
    )
    positions = (await db.execute(stmt)).scalars().all()
    pos_map = {p.id: p for p in positions}
    children_by_parent: Dict[int, List[Position]] = {}
    for p in positions:
        if (
            p.parent_id is not None
            and p.parent_id in allowed_pos_ids
            and p.id not in leader_ctx["leader_position_ids"]
        ):
            children_by_parent.setdefault(p.parent_id, []).append(p)

    active_vac_ids = leader_ctx["active_vacation_emp_ids"]
    direct_emp_ids = leader_ctx["direct_employee_ids"]
    allowed_emp_ids = {leader_emp.id} | leader_ctx["subordinate_employee_ids"]

    def build_positions_subtree(pos: Position, visited: Set[int]) -> Dict[str, Any]:
        visited.add(pos.id)
        node: Dict[str, Any] = {
            "name": pos.name,
            "type": "position",
            "area": pos.area.name if pos.area else "Sin Área",
            "is_leader": pos.is_leader,
            "children": [],
        }
        for emp in sorted(
            [e for e in pos.employees if e.is_active and e.id in allowed_emp_ids],
            key=lambda x: x.full_name,
        ):
            node["children"].append({
                "name": emp.full_name,
                "type": "employee",
                "id": emp.id,
                "is_self": emp.id == leader_emp.id,
                "is_direct": emp.id in direct_emp_ids,
                "on_vacation": emp.id in active_vac_ids,
                "position": pos.name,
                "area": pos.area.name if pos.area else "",
                "company": emp.company.name if emp.company else "",
                "photo": emp.photo_url,
                "value": 1,
            })
        for child in sorted(children_by_parent.get(pos.id, []), key=lambda x: x.name):
            if child.id not in visited:
                node["children"].append(build_positions_subtree(child, set(visited)))
        if not node["children"]:
            del node["children"]
            node["value"] = 1
        return node

    def build_people_subtree(pos: Position, visited: Set[int]) -> List[Dict[str, Any]]:
        visited.add(pos.id)
        sub_nodes: List[Dict[str, Any]] = []
        for child in sorted(children_by_parent.get(pos.id, []), key=lambda x: x.name):
            if child.id not in visited:
                sub_nodes.extend(build_people_subtree(child, set(visited)))

        emps = sorted(
            [e for e in pos.employees if e.is_active and e.id in allowed_emp_ids],
            key=lambda x: x.full_name,
        )
        if not emps:
            if not sub_nodes:
                return []
            return [{
                "name": f"[VACANTE] {pos.name}",
                "type": "vacancy",
                "area": pos.area.name if pos.area else "",
                "position": pos.name,
                "children": sub_nodes,
            }]

        nodes = []
        for emp in emps:
            node = {
                "name": emp.full_name,
                "type": "employee",
                "id": emp.id,
                "is_self": emp.id == leader_emp.id,
                "is_direct": emp.id in direct_emp_ids,
                "on_vacation": emp.id in active_vac_ids,
                "position": pos.name,
                "area": pos.area.name if pos.area else "",
                "company": emp.company.name if emp.company else "",
                "photo": emp.photo_url,
                "children": list(sub_nodes),
            }
            if not node["children"]:
                del node["children"]
                node["value"] = 1
            nodes.append(node)
        return nodes

    primary_pos = pos_map.get(leader_emp.position_id)
    if mode == "positions":
        if primary_pos:
            return build_positions_subtree(primary_pos, set())
        return {"name": leader_emp.full_name, "type": "employee", "is_self": True, "value": 1}

    if primary_pos:
        people_nodes = build_people_subtree(primary_pos, set())
        self_node = next((n for n in people_nodes if n.get("id") == leader_emp.id), None)
        if self_node:
            return self_node
    return {
        "name": leader_emp.full_name,
        "type": "employee",
        "id": leader_emp.id,
        "is_self": True,
        "position": leader_emp.position_obj.name if leader_emp.position_obj else "",
        "area": leader_emp.position_obj.area.name if leader_emp.position_obj and leader_emp.position_obj.area else "",
        "photo": leader_emp.photo_url,
        "value": 1,
    }


async def get_subordinate_timeline(
    db: AsyncSession,
    leader_ctx: Dict[str, Any],
    emp_id: int,
) -> Optional[List[Dict[str, Any]]]:
    """Obtiene los hitos de línea de tiempo de un colaborador subordinado."""
    if emp_id not in leader_ctx["subordinate_employee_ids"]:
        return None
    from app.modules.employees import service as emp_service

    events = await emp_service.get_employee_timeline(db, emp_id)
    items = [e.model_dump(mode="json") for e in events]

    vacations = await list_my_vacation_requests(db, emp_id)
    for v in vacations:
        color = (
            "emerald"
            if v.status == "Aprobada"
            else ("red" if v.status == "Rechazada" else "amber")
        )
        items.append({
            "date": v.start_date.isoformat(),
            "category": "vacation",
            "type_label": f"Vacaciones ({v.status})",
            "title": f"Vacaciones {v.request_code} ({v.status})",
            "description": f"Del {v.start_date.strftime('%d/%m/%Y')} al {v.end_date.strftime('%d/%m/%Y')} ({v.days_requested} días). {v.decision_reason or v.reason or ''}".strip(),
            "color": color,
            "icon": "umbrella-beach",
        })

    items.sort(key=lambda x: x["date"], reverse=True)
    return items


async def generate_subordinate_legajo_excel(
    db: AsyncSession,
    leader_ctx: Dict[str, Any],
    emp_id: int,
):
    """Genera el reporte Excel (.xlsx) del legajo individual de un subordinado."""
    detail = await get_subordinate_employee_detail(db, leader_ctx, emp_id)
    if not detail:
        return None

    import io
    import pandas as pd

    emp = detail["employee"]
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame([{
            "Nombre Completo": emp.full_name,
            "Documento": emp.document_id,
            "Cargo": emp.position_obj.name if emp.position_obj else "-",
            "Área": emp.position_obj.area.name if emp.position_obj and emp.position_obj.area else "-",
            "Sede": emp.position_obj.area.sede.name if emp.position_obj and emp.position_obj.area and emp.position_obj.area.sede else "-",
            "Empresa": emp.company.name if emp.company else "-",
            "Email Institucional": emp.institutional_email or "-",
            "Teléfono": emp.phone or "-",
            "Estado": emp.employment_status.value.upper(),
        }]).to_excel(writer, index=False, sheet_name="Resumen")

        hist_rows = [{
            "Fecha": h.date.strftime("%d/%m/%Y"),
            "Movimiento": h.movement_type.value.upper(),
            "Cargo": h.new_position.name if h.new_position else (h.previous_position_name or "-"),
            "Empresa": h.company.name if h.company else "-",
            "Contrato": h.contract_type.name if h.contract_type else "-",
            "Notas": h.notes or "-",
        } for h in emp.history]
        (pd.DataFrame(hist_rows) if hist_rows else pd.DataFrame(columns=["Fecha", "Movimiento", "Cargo", "Empresa", "Contrato", "Notas"])).to_excel(writer, index=False, sheet_name="Historial")

        sanc_rows = [{
            "Fecha": s.date.strftime("%d/%m/%Y"),
            "Tipo": s.type.value.upper(),
            "Motivo": s.reason,
            "Ministerio": "Sí" if s.sent_to_ministry else "No",
            "Notas": s.notes or "-",
        } for s in emp.sanctions]
        (pd.DataFrame(sanc_rows) if sanc_rows else pd.DataFrame(columns=["Fecha", "Tipo", "Motivo", "Ministerio", "Notas"])).to_excel(writer, index=False, sheet_name="Sanciones")

        rec_rows = [{
            "Fecha": r.date.strftime("%d/%m/%Y"),
            "Tipo": r.type.value.upper(),
            "Título": r.title,
            "Descripción": r.description or "-",
        } for r in emp.recognitions]
        (pd.DataFrame(rec_rows) if rec_rows else pd.DataFrame(columns=["Fecha", "Tipo", "Título", "Descripción"])).to_excel(writer, index=False, sheet_name="Reconocimientos")

        vac_rows = [{
            "Código": v.request_code,
            "Desde": v.start_date.strftime("%d/%m/%Y"),
            "Hasta": v.end_date.strftime("%d/%m/%Y"),
            "Días": v.days_requested,
            "Estado": v.status,
            "Motivo": v.reason or "-",
            "Resolución": v.decision_reason or "-",
        } for v in detail["vacations"]]
        (pd.DataFrame(vac_rows) if vac_rows else pd.DataFrame(columns=["Código", "Desde", "Hasta", "Días", "Estado", "Motivo", "Resolución"])).to_excel(writer, index=False, sheet_name="Vacaciones")

    output.seek(0)
    return output, emp


async def generate_leader_excel_report(
    db: AsyncSession,
    leader_emp: Employee,
    leader_ctx: Dict[str, Any],
    section: str = "all",
):
    """Genera un archivo Excel (.xlsx) con los datos del equipo y área del líder."""
    import io
    import pandas as pd

    sub_ids = leader_ctx["subordinate_employee_ids"]
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        if section in ("all", "team"):
            rows = [{
                "Colaborador": s.full_name,
                "Documento": s.document_id,
                "Cargo": s.position_obj.name if s.position_obj else "-",
                "Área": s.position_obj.area.name if s.position_obj and s.position_obj.area else "-",
                "Sede": s.position_obj.area.sede.name if s.position_obj and s.position_obj.area and s.position_obj.area.sede else "-",
                "Tipo Reporte": "Directo" if s.id in leader_ctx["direct_employee_ids"] else "Indirecto",
                "Email": s.institutional_email or s.personal_email or "-",
                "Teléfono": s.phone or "-",
                "Estado": s.employment_status.value.upper(),
                "En Vacaciones Hoy": "Sí" if s.id in leader_ctx["active_vacation_emp_ids"] else "No",
            } for s in leader_ctx["subordinates"]]
            cols = ["Colaborador", "Documento", "Cargo", "Área", "Sede", "Tipo Reporte", "Email", "Teléfono", "Estado", "En Vacaciones Hoy"]
            (pd.DataFrame(rows) if rows else pd.DataFrame(columns=cols)).to_excel(writer, index=False, sheet_name="Mi Equipo")

        if section in ("all", "vacations"):
            vacs = await list_leader_vacation_requests(db, sub_ids)
            rows = [{
                "Código": v.request_code,
                "Colaborador": v.employee.full_name if v.employee else "-",
                "Cargo": v.employee.position_obj.name if v.employee and v.employee.position_obj else "-",
                "Desde": v.start_date.strftime("%d/%m/%Y"),
                "Hasta": v.end_date.strftime("%d/%m/%Y"),
                "Días Cal.": v.days_requested,
                "Días Hábiles": v.business_days if v.business_days is not None else v.days_requested,
                "Estado": v.status,
                "Motivo": v.reason or "-",
                "Revisor": v.approver.full_name if v.approver else (v.reviewer_user.full_name if v.reviewer_user else "-"),
                "Motivo Decisión": v.decision_reason or "-",
            } for v in vacs]
            cols = ["Código", "Colaborador", "Cargo", "Desde", "Hasta", "Días Cal.", "Días Hábiles", "Estado", "Motivo", "Revisor", "Motivo Decisión"]
            (pd.DataFrame(rows) if rows else pd.DataFrame(columns=cols)).to_excel(writer, index=False, sheet_name="Vacaciones")

        if section in ("all", "recruitment"):
            recs = await get_area_vacancies_status(db, leader_ctx["leader_area_ids"])
            rows = [{
                "Vacante": r["title"],
                "Área": r.get("area_name") or "-",
                "Proceso": r.get("process_name") or "-",
                "Reclutador": r["recruiter"]["full_name"] if r.get("recruiter") else "-",
                "Estado": (r["status"].value if hasattr(r["status"], "value") else r["status"]).upper(),
                "Etapa Actual": r["current_stage"]["name"] if r.get("current_stage") else "Finalizado",
                "Días": r.get("total_days_elapsed", 0),
                "SLA (días)": r.get("total_sla_days", 0),
                "Estado SLA": "Retrasado" if r.get("global_sla_status") == "overdue" else "En Tiempo",
                "Avance %": r.get("progress_percent", 0),
            } for r in recs]
            cols = ["Vacante", "Área", "Proceso", "Reclutador", "Estado", "Etapa Actual", "Días", "SLA (días)", "Estado SLA", "Avance %"]
            (pd.DataFrame(rows) if rows else pd.DataFrame(columns=cols)).to_excel(writer, index=False, sheet_name="Reclutamientos")

        if section in ("all", "events"):
            ev_list = await get_team_events_participation(db, sub_ids)
            tr_list = await get_team_trainings_participation(db, sub_ids)
            rows = [
                {
                    "Tipo": "Evento",
                    "Actividad": ev.event.title if ev.event else "-",
                    "Fecha": ev.event.date.strftime("%d/%m/%Y") if ev.event else "-",
                    "Colaborador": ev.employee.full_name if ev.employee else "-",
                    "Estado": ev.status.value.upper(),
                } for ev in ev_list
            ] + [
                {
                    "Tipo": "Capacitación",
                    "Actividad": tr.training.name if tr.training else "-",
                    "Fecha": tr.training.start_date.strftime("%d/%m/%Y") if tr.training else "-",
                    "Colaborador": tr.employee.full_name if tr.employee else "-",
                    "Estado": tr.status.value.upper(),
                } for tr in tr_list
            ]
            cols = ["Tipo", "Actividad", "Fecha", "Colaborador", "Estado"]
            (pd.DataFrame(rows) if rows else pd.DataFrame(columns=cols)).to_excel(writer, index=False, sheet_name="Eventos y Cursos")

    output.seek(0)
    return output

