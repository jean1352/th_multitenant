import pytest
from datetime import datetime, timedelta, date
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import patch

from app.modules.organization.models import Sede, Area, Position
from app.modules.recruitment.models import Vacancy, RecruitmentProcess, HiringReason
from app.modules.auth.models import User, UserRole
from app.modules.scheduler.models import AutomationRule, TriggerType, AutomationState, EscalationStatus
from app.modules.scheduler.evaluator import AdvancedConditionEvaluator
from app.modules.scheduler.tasks import run_advanced_automations

class AsyncContextManagerMock:
    def __init__(self, value):
        self.value = value
    async def __aenter__(self):
        return self.value
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

@pytest.fixture
async def evaluator_data_setup(db_session: AsyncSession):
    # Create a user to act as requester/recruiter
    user = User(
        email="eval_user@test.com",
        full_name="Eval User",
        role=UserRole.TH,
        is_active=True,
        hashed_password="hashed_password"
    )
    db_session.add(user)
    await db_session.flush()

    # Create dependencies
    sede = Sede(name="Sede Evaluator", address="Address Test")
    db_session.add(sede)
    await db_session.flush()

    area = Area(name="Area Evaluator", sede_id=sede.id, responsible_email="evaluator@test.com")
    db_session.add(area)
    await db_session.flush()

    position = Position(name="Reclutador Especialista", area_id=area.id)
    db_session.add(position)
    await db_session.flush()

    process = RecruitmentProcess(name="Process Evaluator", description="Desc")
    db_session.add(process)
    await db_session.flush()

    hiring_reason = HiringReason(name="Replacement Evaluator", is_active=True)
    db_session.add(hiring_reason)
    await db_session.flush()

    # Create older vacancy to test time operator
    old_date = datetime.now() - timedelta(days=20)
    old_vacancy = Vacancy(
        title="Older Vacancy",
        description="Older Description",
        vacancy_type="external",
        is_headcount_increase=False,
        start_date=old_date.date(),
        area_id=area.id,
        position_id=position.id,
        process_id=process.id,
        hiring_reason_id=hiring_reason.id,
        status="open",
        requester_id=user.id,
        recruiter_id=user.id
    )
    db_session.add(old_vacancy)

    # Create new vacancy
    new_vacancy = Vacancy(
        title="Newer Vacancy",
        description="Newer Description",
        vacancy_type="external",
        is_headcount_increase=False,
        start_date=date.today(),
        area_id=area.id,
        position_id=position.id,
        process_id=process.id,
        hiring_reason_id=hiring_reason.id,
        status="open",
        requester_id=user.id,
        recruiter_id=user.id
    )
    db_session.add(new_vacancy)

    await db_session.commit()
    return {
        "area_id": area.id,
        "old_vacancy_id": old_vacancy.id,
        "new_vacancy_id": new_vacancy.id,
        "user_email": user.email
    }

@pytest.mark.asyncio
async def test_evaluate_rule_simple_and_relational(db_session: AsyncSession, evaluator_data_setup: dict):
    # Rule to find Newer Vacancy using nested joins
    rule = AutomationRule(
        name="Test Rule Simple",
        description="Test Rule Simple",
        trigger_type=TriggerType.CRON_SCHEDULED,
        conditions={
            "model": "Vacancy",
            "operator": "AND",
            "rules": [
                {"field": "title", "operator": "==", "value": "Newer Vacancy"},
                {"field": "area.name", "operator": "==", "value": "Area Evaluator"},
                {"field": "position.name", "operator": "==", "value": "Reclutador Especialista"}
            ]
        }
    )
    
    results = await AdvancedConditionEvaluator.evaluate_rule(db_session, rule)
    assert len(results) == 1
    assert results[0].id == evaluator_data_setup["new_vacancy_id"]

@pytest.mark.asyncio
async def test_evaluate_rule_days_ago_greater_than(db_session: AsyncSession, evaluator_data_setup: dict):
    # Rule to find Older Vacancy (start_date > 15 days ago)
    rule = AutomationRule(
        name="Test Rule Days Ago",
        description="Test Rule Days Ago",
        trigger_type=TriggerType.CRON_SCHEDULED,
        conditions={
            "model": "Vacancy",
            "operator": "AND",
            "rules": [
                {"field": "status", "operator": "==", "value": "open"},
                {"field": "start_date", "operator": "days_ago_greater_than", "value": 15}
            ]
        }
    )
    
    results = await AdvancedConditionEvaluator.evaluate_rule(db_session, rule)
    assert len(results) == 1
    assert results[0].id == evaluator_data_setup["old_vacancy_id"]

@pytest.mark.asyncio
async def test_evaluate_rule_no_match(db_session: AsyncSession, evaluator_data_setup: dict):
    # Rule that shouldn't find anything
    rule = AutomationRule(
        name="Test Rule No Match",
        description="Test Rule No Match",
        trigger_type=TriggerType.CRON_SCHEDULED,
        conditions={
            "model": "Vacancy",
            "operator": "AND",
            "rules": [
                {"field": "title", "operator": "==", "value": "Non-existent Vacancy"}
            ]
        }
    )
    
    results = await AdvancedConditionEvaluator.evaluate_rule(db_session, rule)
    assert len(results) == 0

@pytest.mark.asyncio
async def test_run_advanced_automations_full_flow(db_session: AsyncSession, evaluator_data_setup: dict):
    # Define an active rule with conditions and actions
    rule = AutomationRule(
        name="Full Flow Advanced Rule",
        description="Rule with conditions and actions",
        is_active=True,
        trigger_type=TriggerType.CRON_SCHEDULED,
        conditions={
            "model": "Vacancy",
            "operator": "AND",
            "rules": [
                {"field": "title", "operator": "==", "value": "Newer Vacancy"}
            ]
        },
        actions=[
            {
                "type": "EMAIL",
                "to": evaluator_data_setup["user_email"],
                "subject": "New Alert: {title}",
                "body": "This is an alert for vacancy {title} under {area.name}.",
                "is_html": False
            }
        ],
        escalation_interval="6h"
    )
    db_session.add(rule)
    await db_session.commit()
    
    # Run advanced automations for this specific rule, mocking the Session to use the test db_session
    with patch("app.modules.scheduler.tasks.AsyncSessionLocal", return_value=AsyncContextManagerMock(db_session)):
        res_msg = await run_advanced_automations(rule_id=rule.id)
        
    assert "Reglas: 1" in res_msg
    assert "Disparos: 1" in res_msg
    assert "Estados actualizados: 1" in res_msg
    
    # Check that AutomationState was successfully created
    stmt = select(AutomationState).where(AutomationState.rule_id == rule.id)
    states = (await db_session.execute(stmt)).scalars().all()
    assert len(states) == 1
    state = states[0]
    assert state.target_entity_id == evaluator_data_setup["new_vacancy_id"]
    assert state.status == EscalationStatus.ACTIVE_ESCALATION
    
    # Next run should be set to ~6 hours from now
    diff_hours = (state.next_run_at.replace(tzinfo=None) - datetime.now()).total_seconds() / 3600
    assert 5.9 <= diff_hours <= 6.1
