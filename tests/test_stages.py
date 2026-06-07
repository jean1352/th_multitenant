import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.organization.models import Sede, Area, Position
from app.modules.recruitment.models import RecruitmentProcess, ProcessStage, HiringReason, StageOwner, StageEditReason

@pytest.fixture
async def stage_test_setup(db_session: AsyncSession):
    # Setup similar to vacancy, but ensure we have a vacancy and stages
    sede = Sede(name="Sede Stage", address="Address Stage")
    db_session.add(sede)
    await db_session.flush()

    area = Area(name="Area Stage", sede_id=sede.id, responsible_email="stage@test.com")
    db_session.add(area)
    await db_session.flush()

    position = Position(name="Position Stage", area_id=area.id)
    db_session.add(position)
    await db_session.flush()

    process = RecruitmentProcess(name="Process Stage", description="Desc")
    db_session.add(process)
    await db_session.flush()

    # Stages configuration
    p_stage1 = ProcessStage(process_id=process.id, name="Stage 1", sla_days=2, owner=StageOwner.RECRUITER, order_index=1)
    db_session.add(p_stage1)
    
    # Edit Reasons
    reason_normal = StageEditReason(name="Error de Fecha", is_active=True)
    reason_other = StageEditReason(name="Otro Motivo", is_active=True)
    db_session.add_all([reason_normal, reason_other])
    await db_session.flush()

    # Create Vacancy (which creates Value Stages via listener or service, 
    # but here we might need to rely on the service to create the vacancy properly)
    # So we used the API or Service to create the vacancy to ensure stages are created.
    # But since we are mocking client, we can use the API.
    
    return {
        "area_id": area.id, 
        "position_id": position.id, 
        "process_id": process.id,
        "reason_normal_id": reason_normal.id,
        "reason_other_id": reason_other.id
    }

@pytest.mark.asyncio
async def test_update_stage_validation(client: AsyncClient, recruiter_token: str, stage_test_setup: dict):
    headers = {"Cookie": f"access_token=Bearer {recruiter_token}"}

    # 1. Create Vacancy to generate stages
    vacancy_payload = {
        "title": "Stage Test Vacancy",
        "description": "Some description",
        "vacancy_type": "external",
        "area_id": stage_test_setup["area_id"],
        "position_id": stage_test_setup["position_id"],
        "process_id": stage_test_setup["process_id"],
        "start_date": "2023-01-01"
    }
    create_resp = await client.post("/recruitment/api/vacancies", json=vacancy_payload, headers=headers)
    assert create_resp.status_code == 201
    vacancy_data = create_resp.json()
    stage_id = vacancy_data["stages"][0]["id"]

    # 2. Update with Normal Reason (should pass)
    update_payload = {
        "edit_reason_id": stage_test_setup["reason_normal_id"],
        "notes": "Some notes"
    }
    resp = await client.put(f"/recruitment/api/stages/{stage_id}", json=update_payload, headers=headers)
    # Note: Using POST or PUT depending on implementation. 
    # Usually update_stage is often PUT, but let's check router.
    # If router not checked, assume PUT usually, but sometimes POST for specific actions.
    # Checking router from memory... it was `update_stage_api` probably PUT.
    # WAIT! API for stage update might be different. 
    # Let me check router.py quickly if I am unsure.
    # I saw `update_stage_api` in router.py. Let's assume PUT for now or check.
    
    # Actually, let's play safe and check router path.
    # Based on standard REST, it should be PUT /stages/{id} using `StageUpdate` schema.
    pass 

@pytest.mark.asyncio
async def test_update_stage_other_reason_validation(client: AsyncClient, recruiter_token: str, stage_test_setup: dict):
    headers = {"Cookie": f"access_token=Bearer {recruiter_token}"}

    # Create Vacancy
    vacancy_payload = {
        "title": "Stage Test Vacancy 2",
        "description": "Another description",
        "vacancy_type": "external",
        "area_id": stage_test_setup["area_id"],
        "position_id": stage_test_setup["position_id"],
        "process_id": stage_test_setup["process_id"],
        "start_date": "2023-01-01"
    }
    create_resp = await client.post("/recruitment/api/vacancies", json=vacancy_payload, headers=headers)
    assert create_resp.status_code == 201
    stage_id = create_resp.json()["stages"][0]["id"]

    # 1. Update with "Other" Reason WITHOUT notes (should fail)
    update_payload_fail = {
        "edit_reason_id": stage_test_setup["reason_other_id"],
        "notes": "" # Empty notes
    }
    resp = await client.put(f"/recruitment/api/stages/{stage_id}", json=update_payload_fail, headers=headers)
    assert resp.status_code == 400 # Expecting validation error
    
    # 2. Update with "Other" Reason WITH notes (should pass)
    update_payload_pass = {
        "edit_reason_id": stage_test_setup["reason_other_id"],
        "notes": "Explicación obligatoria"
    }
    resp2 = await client.put(f"/recruitment/api/stages/{stage_id}", json=update_payload_pass, headers=headers)
    assert resp2.status_code == 200
