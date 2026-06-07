from datetime import datetime, timedelta
import sys
import traceback
import logging
from typing import List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select, desc, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.modules.scheduler.models import AutomationRule, TaskExecutionLog, AutomationRuleType, FrequencyType
from app.modules.scheduler.tasks import TASK_REGISTRY
from app.core.tenants import set_current_tenant
from app.modules.tenants.models import Tenant

# Configurar logger localmente también por seguridad
logger = logging.getLogger(__name__)

# Instancia Global
scheduler = AsyncIOScheduler()

# --- WRAPPER ---
async def job_wrapper(rule_id: int, func_name: str, tenant_id: int, param_value: int = None):
    """Ejecuta la lógica y guarda el log en el contexto del tenant."""
    async with AsyncSessionLocal() as db:
        # Recuperar el tenant
        result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = result.scalar_one_or_none()
        
        if not tenant:
            print(f"❌ [SCHEDULER] Tenant ID {tenant_id} no encontrado. Abortando.")
            return
            
        set_current_tenant(tenant)
        # Seteamos el search_path manualmente para este worker
        await db.execute(text(f'SET search_path TO "{tenant.schema_name}", public'))

    print(f"⚡ [SCHEDULER] [{tenant.subdomain}] Ejecutando tarea: {func_name} (Rule ID: {rule_id})")
    
    status = "SUCCESS"
    msg = "Ejecución exitosa"
    items_count = 0
    
    try:
        func = TASK_REGISTRY.get(func_name)
        if func:
            # Ejecutar worker
            result = await func(rule_id=rule_id, param_value=param_value)
            if result: 
                msg = str(result)
                try:
                    items_count = int(''.join(filter(str.isdigit, msg)))
                except:
                    pass
            
            print(f"✅ [SCHEDULER] [{tenant.subdomain}] Tarea {func_name} finalizada: {msg}")
        else:
            raise ValueError(f"Lógica no encontrada para {func_name}")
            
    except Exception as e:
        status = "ERROR"
        msg = str(e)
        print(f"❌ [SCHEDULER] [{tenant.subdomain}] Error en {func_name}: {e}")
        traceback.print_exc()
    
    # Guardar Log en BD del Tenant
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text(f'SET search_path TO "{tenant.schema_name}", public'))
            log = TaskExecutionLog(
                rule_id=rule_id, 
                task_name=func_name, 
                status=status, 
                message=msg,
                items_processed=items_count
            )
            db.add(log)
            
            rule = await db.get(AutomationRule, rule_id)
            if rule:
                rule.last_run = datetime.now()
            
            await db.commit()
    except Exception as db_e:
        print(f"🔥 [SCHEDULER] Error crítico guardando log en BD para {tenant.subdomain}: {db_e}")

# --- GESTIÓN ---

def start_scheduler():
    if not scheduler.running:
        scheduler.start()
        print("🕒 APScheduler iniciado.")

async def sync_jobs_from_db(db: AsyncSession):
    """Lee reglas activas de TODOS los tenants y las programa."""
    scheduler.remove_all_jobs()
    
    # 1. Obtener todos los tenants activos
    result = await db.execute(select(Tenant).where(Tenant.is_active == True))
    tenants = result.scalars().all()
    
    print(f"🔄 Sincronizando reglas para {len(tenants)} tenants...")
    
    for tenant in tenants:
        # 2. Para cada tenant, buscar sus reglas
        try:
            async with AsyncSessionLocal() as tenant_db:
                await tenant_db.execute(text(f'SET search_path TO "{tenant.schema_name}", public'))
                stmt = select(AutomationRule).where(AutomationRule.is_active == True)
                rules = (await tenant_db.execute(stmt)).scalars().all()
                
                for rule in rules:
                    schedule_rule(rule, tenant)
        except Exception as e:
            print(f"❌ Error sincronizando reglas para tenant {tenant.subdomain}: {e}")

def schedule_rule(rule: AutomationRule, tenant: Tenant):
    job_id = f"{tenant.id}_{rule.id}"
    
    # Parsear hora
    try:
        hour, minute = map(int, rule.execution_time.split(":"))
    except:
        hour, minute = 8, 0

    trigger = None
    
    if rule.frequency == FrequencyType.DAILY:
        trigger = CronTrigger(hour=hour, minute=minute)
        
    elif rule.frequency == FrequencyType.WEEKLY:
        days = ['mon','tue','wed','thu','fri','sat','sun']
        day_str = days[rule.day_of_week] if rule.day_of_week is not None else 'mon'
        trigger = CronTrigger(day_of_week=day_str, hour=hour, minute=minute)
        
    elif rule.frequency == FrequencyType.MONTHLY:
        day_num = rule.day_of_month or 1
        trigger = CronTrigger(day=day_num, hour=hour, minute=minute)

    elif rule.frequency == FrequencyType.CUSTOM:
        days_interval = rule.param_value or 1
        now = datetime.now()
        start_date = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if start_date < now:
            start_date += timedelta(days=1)
        trigger = IntervalTrigger(days=days_interval, start_date=start_date)

    if trigger:
        scheduler.add_job(
            job_wrapper,
            trigger,
            id=job_id,
            replace_existing=True,
            kwargs={
                "rule_id": rule.id, 
                "func_name": rule.rule_type.value,
                "tenant_id": tenant.id,
                "param_value": rule.param_value
            }
        )

# --- CRUD ---

async def get_rules(db: AsyncSession) -> List[AutomationRule]:
    return (await db.execute(select(AutomationRule).order_by(AutomationRule.id))).scalars().all()

async def update_rule(db: AsyncSession, id: int, data: dict):
    rule = await db.get(AutomationRule, id)
    if not rule: return None
    
    for k, v in data.items():
        setattr(rule, k, v)
        
    await db.commit()
    
    # Reschedule
    # Para re-programar necesitamos el objeto tenant. Lo buscamos.
    from app.core.tenants import get_current_tenant
    tenant = get_current_tenant()
    
    if tenant:
        job_id = f"{tenant.id}_{id}"
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
            
        if rule.is_active:
            schedule_rule(rule, tenant)
        
    return rule

async def toggle_rule(db: AsyncSession, id: int):
    rule = await db.get(AutomationRule, id)
    if not rule: return False
    
    rule.is_active = not rule.is_active
    await db.commit()
    
    from app.core.tenants import get_current_tenant
    tenant = get_current_tenant()
    
    if tenant:
        job_id = f"{tenant.id}_{id}"
        if rule.is_active:
            schedule_rule(rule, tenant)
        else:
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)
            
    return rule.is_active

async def run_rule_now(db: AsyncSession, id: int):
    """Ejecución manual inmediata."""
    rule = await db.get(AutomationRule, id)
    from app.core.tenants import get_current_tenant
    tenant = get_current_tenant()

    if rule and tenant:
        print(f"▶️ Ejecución manual solicitada para: {rule.name} en tenant {tenant.subdomain}")
        scheduler.add_job(
            job_wrapper,
            kwargs={
                "rule_id": rule.id, 
                "func_name": rule.rule_type.value,
                "tenant_id": tenant.id,
                "param_value": rule.param_value
            }
        )

async def get_logs(db: AsyncSession, limit: int = 20):
    return (await db.execute(select(TaskExecutionLog).order_by(desc(TaskExecutionLog.executed_at)).limit(limit))).scalars().all()

# --- SEEDING INICIAL ---
async def seed_default_rules(db: AsyncSession):
    """Crea las reglas por defecto si no existen."""
    defaults = [
        {
            "rule_type": AutomationRuleType.VACANCY_WEEKLY_REPORT,
            "name": "Reporte de Vacantes",
            "description": "Envía un correo con el estado actual (HTML) a cada responsable de área que tenga vacantes abiertas.",
            "frequency": FrequencyType.WEEKLY,
            "day_of_week": 0, # Lunes
            "execution_time": "09:00"
        },
        {
            "rule_type": AutomationRuleType.VACANCY_STAGNATION,
            "name": "Alerta de Estancamiento",
            "description": "Notifica si una vacante lleva X días (configurable) desde su creación sin cerrarse.",
            "frequency": FrequencyType.DAILY,
            "execution_time": "08:00",
            "param_value": 10 # Días por defecto
        },
        {
            "rule_type": AutomationRuleType.EVENT_REMINDER,
            "name": "Recordatorio de Eventos",
            "description": "Envía recordatorio a invitados que no han respondido, X días antes del evento.",
            "frequency": FrequencyType.DAILY,
            "execution_time": "10:00",
            "param_value": 2 # Días antes
        },
        {
            "rule_type": AutomationRuleType.CONTRACT_EXPIRATION,
            "name": "Vencimiento de Contratos",
            "description": "Notifica al responsable del área X días antes de que venza un documento tipo 'Contrato'.",
            "frequency": FrequencyType.DAILY,
            "execution_time": "08:30",
            "param_value": 30 # Días de anticipación
        },
        {
            "rule_type": AutomationRuleType.PROBATION_END,
            "name": "Fin Periodo de Prueba",
            "description": "Notifica 15 días antes de que se cumpla el periodo de prueba (X días) de un colaborador.",
            "frequency": FrequencyType.DAILY,
            "execution_time": "08:30",
            "param_value": 90 # Duración del periodo de prueba
        }
    ]
    
    for d in defaults:
        stmt = select(AutomationRule).where(AutomationRule.rule_type == d["rule_type"])
        existing = (await db.execute(stmt)).scalar_one_or_none()
        
        if not existing:
            rule = AutomationRule(**d)
            db.add(rule)
        else:
            if d["rule_type"] == AutomationRuleType.VACANCY_WEEKLY_REPORT and existing.name == "Reporte Semanal de Vacantes":
                existing.name = "Reporte de Vacantes"
    
    await db.commit()
