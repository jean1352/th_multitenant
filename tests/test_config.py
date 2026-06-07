import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_hiring_reasons_crud(client: AsyncClient, recruiter_token: str):
    headers = {"Cookie": f"access_token=Bearer {recruiter_token}"}

    # 1. Create
    resp = await client.post(
        "/recruitment/api/config/hiring-reasons",
        json={"name": "New Position", "is_active": True},
        headers=headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "New Position"
    reason_id = data["id"]

    # 2. Update
    resp = await client.put(
        f"/recruitment/api/config/hiring-reasons/{reason_id}",
        json={"name": "Updated Position", "is_active": False},
        headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Position"
    assert resp.json()["is_active"] == False

    # 3. Delete
    resp = await client.delete(
        f"/recruitment/api/config/hiring-reasons/{reason_id}",
        headers=headers
    )
    assert resp.status_code == 204

@pytest.mark.asyncio
async def test_stage_edit_reasons_crud(client: AsyncClient, recruiter_token: str):
    headers = {"Cookie": f"access_token=Bearer {recruiter_token}"}

    # 1. Create
    resp = await client.post(
        "/recruitment/api/config/stage-edit-reasons",
        json={"name": "Date Error", "is_active": True},
        headers=headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Date Error"
    reason_id = data["id"]

    # 2. Update
    resp = await client.put(
        f"/recruitment/api/config/stage-edit-reasons/{reason_id}",
        json={"name": "Typo Error", "is_active": True},
        headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Typo Error"

    # 3. Delete
    resp = await client.delete(
        f"/recruitment/api/config/stage-edit-reasons/{reason_id}",
        headers=headers
    )
    assert resp.status_code == 204
