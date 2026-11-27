from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.modules.tenants.models import Tenant
from app.core.database import Base, engine, validate_schema_name, AsyncSessionLocal
import logging

logger = logging.getLogger(__name__)

async def create_tenant(db: AsyncSession, name: str, subdomain: str) -> Tenant:
    """
    Crea un nuevo tenant, su esquema en la base de datos y todas las tablas necesarias.
    """
    schema_name = validate_schema_name(f"tenant_{subdomain.replace('-', '_')}")
    
    # 1. Crear el registro en la tabla pública
    new_tenant = Tenant(
        name=name,
        subdomain=subdomain,
        schema_name=schema_name
    )
    db.add(new_tenant)
    await db.commit()
    await db.refresh(new_tenant)
    
    # 2. Crear el esquema en PostgreSQL
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))
        
        # 3. Crear las tablas en el nuevo esquema
        await conn.execute(text(f'SET search_path TO "{schema_name}"'))
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text('SET search_path TO public'))

    # 4. Sembrar reglas por defecto de automatización en el nuevo tenant
    try:
        from app.modules.scheduler.service import seed_default_rules
        async with AsyncSessionLocal() as tenant_db:
            await tenant_db.execute(text(f'SET search_path TO "{schema_name}", public'))
            await seed_default_rules(tenant_db)
    except Exception as e:
        logger.warning(f"No se pudieron sembrar reglas iniciales para '{schema_name}': {e}")
        
    logger.info(f"Tenant '{name}' creado con esquema '{schema_name}'")
    return new_tenant

async def get_tenant_by_subdomain(db: AsyncSession, subdomain: str) -> Tenant:
    from sqlalchemy import select
    result = await db.execute(select(Tenant).where(Tenant.subdomain == subdomain))
    return result.scalar_one_or_none()
