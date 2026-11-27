from datetime import date, timedelta
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.modules.auth.models import User, UserRole
from app.modules.employees.models import Employee, EmployeePosition
from app.modules.organization.models import Area, Position, Sede


@pytest.fixture
async def portal_hierarchy_setup(db_session: AsyncSession):
    sede = Sede(name="Sede Portal", address="Av. Test 123")
    db_session.add(sede)
    await db_session.flush()

    area_ti = Area(name="TI", sede_id=sede.id, responsible_email="ti.jefe@test.com")
    area_fin = Area(name="Finanzas", sede_id=sede.id, responsible_email="fin.jefe@test.com")
    db_session.add_all([area_ti, area_fin])
    await db_session.flush()

    pos_dir = Position(name="Director General", area_id=area_ti.id, is_leader=True)
    db_session.add(pos_dir)
    await db_session.flush()

    pos_mgr_ti = Position(name="Gerente TI", area_id=area_ti.id, is_leader=True, parent_id=pos_dir.id)
    pos_mgr_fin = Position(name="Gerente Finanzas", area_id=area_fin.id, is_leader=True, parent_id=pos_dir.id)
    db_session.add_all([pos_mgr_ti, pos_mgr_fin])
    await db_session.flush()

    pos_dev = Position(name="Desarrollador", area_id=area_ti.id, is_leader=False, parent_id=pos_mgr_ti.id)
    db_session.add(pos_dev)
    await db_session.flush()

    emp_dir = Employee(
        first_name="Laura", last_name="Dir", full_name="Laura Dir",
        document_id="1001", position_id=pos_dir.id,
        institutional_email="laura@test.com", is_active=True,
    )
    emp_mgr_ti = Employee(
        first_name="Carlos", last_name="TI", full_name="Carlos TI",
        document_id="1002", position_id=pos_mgr_ti.id,
        institutional_email="carlos@test.com", is_active=True,
    )
    emp_mgr_fin = Employee(
        first_name="Sofia", last_name="Fin", full_name="Sofia Fin",
        document_id="1003", position_id=pos_mgr_fin.id,
        institutional_email="sofia@test.com", is_active=True,
    )
    emp_dev = Employee(
        first_name="Diego", last_name="Dev", full_name="Diego Dev",
        document_id="1004", position_id=pos_dev.id,
        institutional_email="diego@test.com", is_active=True,
    )
    db_session.add_all([emp_dir, emp_mgr_ti, emp_mgr_fin, emp_dev])
    await db_session.flush()

    for emp in (emp_dir, emp_mgr_ti, emp_mgr_fin, emp_dev):
        db_session.add(EmployeePosition(
            employee_id=emp.id, position_id=emp.position_id, is_primary=True, start_date=date.today()
        ))

    u_dir = User(email="laura@test.com", full_name="Laura Dir", role=UserRole.EMPLOYEE, is_active=True, hashed_password="x", employee_id=emp_dir.id, area_id=area_ti.id)
    u_mgr_ti = User(email="carlos@test.com", full_name="Carlos TI", role=UserRole.EMPLOYEE, is_active=True, hashed_password="x", employee_id=emp_mgr_ti.id, area_id=area_ti.id)
    u_mgr_fin = User(email="sofia@test.com", full_name="Sofia Fin", role=UserRole.EMPLOYEE, is_active=True, hashed_password="x", employee_id=emp_mgr_fin.id, area_id=area_fin.id)
    u_dev = User(email="diego@test.com", full_name="Diego Dev", role=UserRole.EMPLOYEE, is_active=True, hashed_password="x", employee_id=emp_dev.id, area_id=area_ti.id)
    db_session.add_all([u_dir, u_mgr_ti, u_mgr_fin, u_dev])
    await db_session.commit()

    return {
        "emp_dir": emp_dir,
        "emp_mgr_ti": emp_mgr_ti,
        "emp_mgr_fin": emp_mgr_fin,
        "emp_dev": emp_dev,
        "tok_dir": create_access_token({"sub": u_dir.email, "id": u_dir.id, "role": u_dir.role.value}),
        "tok_mgr_ti": create_access_token({"sub": u_mgr_ti.email, "id": u_mgr_ti.id, "role": u_mgr_ti.role.value}),
        "tok_mgr_fin": create_access_token({"sub": u_mgr_fin.email, "id": u_mgr_fin.id, "role": u_mgr_fin.role.value}),
        "tok_dev": create_access_token({"sub": u_dev.email, "id": u_dev.id, "role": u_dev.role.value}),


@pytest.mark.asyncio
async def test_leader_hierarchy_legajo_access(client: AsyncClient, portal_hierarchy_setup: dict):
    s = portal_hierarchy_setup
    hdr_mgr_ti = {"Cookie": f"access_token=Bearer {s['tok_mgr_ti']}"}
    hdr_dev = {"Cookie": f"access_token=Bearer {s['tok_dev']}"}

    r_ok = await client.get(f"/portal/leader/employees/{s['emp_dev'].id}", headers=hdr_mgr_ti)
    assert r_ok.status_code == 200

    r_up = await client.get(f"/portal/leader/employees/{s['emp_dir'].id}", headers=hdr_mgr_ti)
    assert r_up.status_code == 403
    r_peer = await client.get(f"/portal/leader/employees/{s['emp_mgr_fin'].id}", headers=hdr_mgr_ti)
    assert r_peer.status_code == 403

    r_dev = await client.get("/portal/leader", headers=hdr_dev)
    assert r_dev.status_code == 403


@pytest.mark.asyncio
async def test_vacation_request_and_leader_decision(client: AsyncClient, portal_hierarchy_setup: dict):
    s = portal_hierarchy_setup
    hdr_dev = {"Cookie": f"access_token=Bearer {s['tok_dev']}"}
    hdr_mgr_ti = {"Cookie": f"access_token=Bearer {s['tok_mgr_ti']}"}
    hdr_mgr_fin = {"Cookie": f"access_token=Bearer {s['tok_mgr_fin']}"}

    start = date.today() + timedelta(days=10)
    end = start + timedelta(days=4)

    r_create = await client.post(
        "/portal/api/vacations",
        json={"start_date": str(start), "end_date": str(end), "reason": "Viaje familiar"},
        headers=hdr_dev,
    )
    assert r_create.status_code == 201, r_create.text
    vac_data = r_create.json()
    assert vac_data["status"] == "Pendiente"
    assert vac_data["days_requested"] == 5
    assert vac_data["assigned_approver_id"] == s["emp_mgr_ti"].id
    req_id = vac_data["id"]

    r_forbid = await client.post(
        f"/portal/api/leader/vacations/{req_id}/decision",
        json={"status": "Aprobada"},
        headers=hdr_mgr_fin,
    )
    assert r_forbid.status_code == 403

    r_no_reason = await client.post(
        f"/portal/api/leader/vacations/{req_id}/decision",
        json={"status": "Rechazada", "decision_reason": "   "},
        headers=hdr_mgr_ti,
    )
    assert r_no_reason.status_code == 422

    r_rej = await client.post(
        f"/portal/api/leader/vacations/{req_id}/decision",
        json={"status": "Rechazada", "decision_reason": "Cierre de sprint en esa semana"},
        headers=hdr_mgr_ti,
    )
    assert r_rej.status_code == 200
    assert r_rej.json()["status"] == "Rechazada"
    assert r_rej.json()["decision_reason"] == "Cierre de sprint en esa semana"

    r_create2 = await client.post(
        "/portal/api/vacations",
        json={"start_date": str(start + timedelta(days=14)), "end_date": str(start + timedelta(days=16))},
        headers=hdr_dev,
    )
    assert r_create2.status_code == 201
    req_id2 = r_create2.json()["id"]

    r_app = await client.post(
        f"/portal/api/leader/vacations/{req_id2}/decision",
        json={"status": "Aprobada", "decision_reason": "Aprobado, buen descanso"},
        headers=hdr_mgr_ti,
    )
    assert r_app.status_code == 200
    assert r_app.json()["status"] == "Aprobada"

    }
